import datetime as dt
import re
from itertools import product
from pathlib import Path

import cv2
import numpy as np
import pandas as pd
import sh
import skimage
from astropy.io import fits
from astropy.table import Table
from dustgoggles.func import gmap
from dustgoggles.pivot import dupe_df_block
from pdr.np_utils import enforce_order_and_object

import asdf
from asdf.asdf_utils import cast_to_reference, null_marslab_data_section
from asdf.console import aprint, ASDFLOG
from asdf.format import drop_excess_stats, melt_metadata
from asdf.parse import parse_pointing
from asdf.zcam_bandset import polish_metadata
from asdf_settings.metadata import COMPACT_ZCAM_MARSLAB_FIELDS
from asdf_settings.rapidlooks import CROP_SETTINGS
from marslab.bandset import BandSet
from marslab.compat.xcam import DERIVED_CAM_DICT
from marslab.imgops.imgutils import crop

PREFERRED_REF_BANDS = (1, 2, 3, 4, 5, 6, "0R", "0G", "0B")

LONG_METADATA_DTYPES = {
    "SOL": "int16",
    "WAVELENGTH": "float16",
    "IX": "uint8",
    "SOLAR_ELEVATION": "float32",
    "INSTRUMENT_ELEVATION": "float32",
    "L_S": "float32",
    "INSTRUMENT_AZIMUTH": "float32",
    "SOLAR_AZIMUTH": "float32",
    "SCLK": "float64",
    "SITE": "int16",
    "DRIVE": "int16",
    "CTIME": "int64",
    "ZOOM": "uint8",
    "VERSION": "uint8",
    "RSM": "int16",
    "CALTARGET_LTST": "float32",
    "SUBFRAME": str,
    "MINI_HEADER": str,
    "RMC": str,
    "BAYER_PIXEL": str,
    "COMPRESSION_QUALITY": str,
}


def bounce_mosaic_input_files(mosaic, scratch_path=".temp/mosaic"):
    Path(scratch_path).mkdir(exist_ok=True)
    bands = mosaic[0].metadata["BAND"].unique()
    tiff_info = []
    for bandset, band in product(mosaic, bands):
        bandset.load([band])
        bandset.bulk_debayer([band])
        cropped = crop(bandset.get_band(band), CROP_SETTINGS["crop"])
        tiff_path = Path(scratch_path, f"{band}_{bandset.name}.tiff")
        # note: hugin crashes if the input extension is "tif", but insists
        # on writing it as "tiff".
        # it also exhibits different behavior based on tiff file data type.
        # also note that cv2 will write but not read 32-bit tiff files, and
        # pillow won't do either. scikit-image can read them.
        cv2.imwrite(str(tiff_path), cropped)
        aprint(f"wrote {tiff_path}")
        # for -f argument to pto_gen
        azimuth_fov = bandset.precached[
            bandset.metadata.loc[
                bandset.metadata["BAND"] == band, "PATH"
            ].iloc[0]
        ].metaget("AZIMUTH_FOV")["value"]
        tiff_rec = {
            "band": band,
            "rsm": bandset.metadata["RSM"].iloc[0],
            "seq_id": bandset.metadata["SEQ_ID"].iloc[0],
            "bandset_name": bandset.name,
            "path": tiff_path,
            "fov": azimuth_fov,
            "eye": band[0],
        }
        tiff_info.append(tiff_rec)
        bandset.purge()
    return pd.DataFrame(tiff_info)


def zcam_pto_gen(paths, azimuth_fov, output_file=None):
    if output_file is None:
        output_file = Path(Path(paths[0]).parent, Path(paths[0]).stem + ".pto")
    return (
        sh.pto_gen(
            *("-o", str(output_file)),
            *("-p", 0),
            *("-f", azimuth_fov),
            *("-s", len(paths)),
            "--ignore-fov-rectilinear",
            *tuple(map(str, paths)),
        ),
        output_file,
    )


# they really like to put it in there
def remove_hugin_crop_instruction(pto_file):
    with open(pto_file) as stream:
        text = stream.read()
    dimension_match = re.search(r"f\d+ w(\d+) h(\d+)", text)
    width, height = dimension_match.group(1), dimension_match.group(2)
    crop_match = re.search(r'k\d+ E\d+ R\d+ (S(\d|,)+) n"TIFF', text)
    text = text.replace(crop_match.group(1), f"S0,{width},0,{height}")
    with open(pto_file, "w") as stream:
        stream.write(text)
    return width, height


def hugin_assistant(pto_file):
    return sh.hugin_executor("--assistant", pto_file)

#
# def autooptimiser(pto_file):
#     return sh.autooptimiser(
#         *("-o", str(pto_file)), "-a", "-s", "-p", pto_file
#     )


def execute_hugin_stitch(pto_file, prefix=None):
    command_parts = ["-s", pto_file]
    if prefix is not None:
        command_parts = ["-p", prefix] + command_parts
    return sh.hugin_executor(*command_parts)


def read_first_channel(path):
    return skimage.io.imread(path)[:, :, 0]


def pano_modify(
    pto_file,
    output_type="NORMAL",
    # projection: 0=equirectangular, 1=cylindrical, ...?
    projection=1,
    **kwargs,
):
    return sh.pano_modify(
        pto_file,
        output=pto_file,
        projection=projection,
        output_type=output_type,
        **kwargs,
    )


def crop_outer(array):
    nzy, nzx = np.nonzero(array)
    return crop(array, (nzx.min(), nzx.max(), nzy.min(), nzy.max()))


def concat_mosaic_fn(sol, seq_id, eye):
    return f"sol{str(sol).zfill(4)}_{seq_id.lower()}_{eye.lower()}_mosaic.fits"


def make_eye_mosaics(eye, tiff_info):
    eye_name = {"L": "left", "R": "right"}[eye]
    available_bands = tiff_info["band"].tolist()
    eye_bands = [b for b in available_bands if b.startswith(eye)]
    if len(eye_bands) == 0:
        return {}, None
    tried_bands = []
    ref_band, ref_pto_file, ref_slice, tried_bands = ref_projection(
        eye, eye_bands, tiff_info, tried_bands
    )
    with open(ref_pto_file) as stream:
        ref_text = stream.read()
    pto_files, tif_files = {ref_band: ref_pto_file}, {}
    for band in filter(lambda b: b != ref_band, eye_bands):
        band_slice = tiff_info.loc[tiff_info["band"] == band]
        if len(band_slice) != len(ref_slice):
            raise ValueError("mismatched availability between bands.")
        pto_file = Path(
            ref_pto_file.parent, ref_pto_file.name.replace(ref_band, band)
        )
        band_text = ref_text
        for _, row in ref_slice.iterrows():
            ref_path = row["path"]
            band_path = band_slice.loc[
                band_slice["rsm"] == row["rsm"], "path"
            ].iloc[0]
            band_text = band_text.replace(ref_path.name, band_path.name)
        with pto_file.open("w") as stream:
            stream.write(band_text)
        pto_files[band] = pto_file
    ASDFLOG.info(f"generated projection for {eye_name}-eye mosaic")
    ok = False
    while (ok is False) and (len(tried_bands) < len(PREFERRED_REF_BANDS)):
        try:
            create_intermediate_mosaics(pto_files, tif_files)
            ok = True
        except sh.ErrorReturnCode:
            aprint("[bold dark_orange] bad projection solution. retrying...")
            ref_band, ref_pto_file, ref_slice, tried_bands = ref_projection(
                eye, eye_bands, tiff_info, tried_bands
            )
    if ok is False:
        raise ValueError("Unable to find usable reference projection.")
    return pto_files, tif_files, ref_text


def create_intermediate_mosaics(pto_files, tif_files):
    for band, pto_file in pto_files.items():
        stdout = execute_hugin_stitch(pto_file).stdout.decode('utf-8')
        intermediate_tif_file = re.search(r'saving (.*?.tif)', stdout).group(1)
        tif_files[band] = f"{intermediate_tif_file[:-8]}.tif"
        ASDFLOG.info(f"wrote {band} intermediate mosaic file")


def ref_projection(eye, eye_bands, tiff_info, tried_bands):
    ref_band = next(
        (
            f"{eye}{n}" for n in PREFERRED_REF_BANDS
            if f"{eye}{n}" in eye_bands
            and f"{eye}{n}" not in tried_bands
        )
    )
    tried_bands.append(ref_band)
    ref_slice = tiff_info.loc[tiff_info["band"] == ref_band]
    ref_paths, ref_fovs = ref_slice["path"].tolist(), ref_slice["fov"]
    _, ref_pto_file = zcam_pto_gen(ref_paths, float(np.mean(ref_fovs)))
    hugin_assistant(ref_pto_file)
    pano_modify(ref_pto_file, canvas="AUTO")
    remove_hugin_crop_instruction(ref_pto_file)
    return ref_band, ref_pto_file, ref_slice, tried_bands


def preprocess_mosaic_metadata(bandsets):
    all_metadata = pd.concat([b.metadata for b in bandsets])
    all_metadata = all_metadata.drop(columns=["ANALYSIS_NAME", "stem", "PATH"])
    return cast_to_reference(all_metadata, LONG_METADATA_DTYPES)


def concatenate_mosaic(process_info, eye, all_metadata, outpath=None):
    eye_pto_files, eye_tif_files, eye_ref_text = process_info[eye]
    parent_directory = Path(list(eye_pto_files.values())[0]).parent
    paths = {
        band: Path(parent_directory, p) for band, p in eye_tif_files.items()
    }
    arrays = {
        band: crop_outer(read_first_channel(phot))
        for band, phot in paths.items()
    }
    if not len({arr.shape for arr in arrays.values()}) == 1:
        raise ValueError("apparent misalignment.")
    hdus = [fits.PrimaryHDU()]
    hdus += [
        fits.ImageHDU(arrays[band], name=band)
        for band in sorted(arrays.keys())
    ]
    meta_hdu = fits.table_to_hdu(
        Table.from_pandas(
            all_metadata.loc[all_metadata["BAND"].isin(arrays.keys())]
        )
    )
    meta_hdu.name = "metadata"
    hdus.append(meta_hdu)

    hdul = fits.HDUList(hdus)
    if outpath is None:
        outpath = parent_directory
    mosaic_fn = concat_mosaic_fn(
        meta_hdu.data['SOL'][0], meta_hdu.data['SEQ_ID'][0], eye
    )
    if Path(outpath, mosaic_fn).exists():
        Path(outpath, mosaic_fn).unlink()
    hdul.writeto(Path(outpath, mosaic_fn))
    return Path(outpath, mosaic_fn)


def simple_fits_load(path, metadata, bands):
    """
    extremely simple fits loader for BandSet.
    Loads from specified HDUs within a FITS file.
    """
    hdul = fits.open(path)
    arrays = {}
    for band in bands:
        band_ix = metadata.loc[metadata["BAND"] == band, "IX"]
        if len(band_ix) == 0:
            continue
        arrays[band] = hdul[band_ix.iloc[0]].data
    return arrays


class ZMosaicBandSet(BandSet):
    def __init__(self, mosaic_fits_files):
        mosaic_fits_files = gmap(str, mosaic_fits_files)
        metadata, extended = [], []
        for file in mosaic_fits_files:
            hdul = fits.open(file)
            band_hdu = {
                info[1]: info[0]
                for info in hdul.info(False)
                if info[3] == "ImageHDU"
            }
            eye_metadata = pd.DataFrame(
                {
                    "BAND": list(band_hdu.keys()),
                    "IX": list(band_hdu.values()),
                    "PATH": file,
                }
            )
            ext_records = hdul[-1].data
            eye_ext = pd.DataFrame(enforce_order_and_object(ext_records))
            for c in eye_ext.columns:
                if isinstance(eye_ext[c].iloc[0], bytes):
                    eye_ext[c] = eye_ext[c].map(lambda b: b.decode("utf-8"))
            metadata.append(eye_metadata)
            extended.append(eye_ext)
        metadata = pd.concat(metadata).reset_index(drop=True)
        metadata["WAVELENGTH"] = [
            DERIVED_CAM_DICT["ZCAM"]["filters"][band]
            for band in metadata["BAND"]
        ]
        super().__init__(metadata=metadata, load_method=simple_fits_load)
        self.extended = pd.concat(extended).reset_index(drop=True)
        for id_key in ('SOL', 'NAME', 'SEQ_ID', 'SITE', 'DRIVE'):
            self.metadata[id_key] = self.extended[id_key].iloc[0]
        self.name = (
            f"{str(self.extended['SOL'].iloc[0]).zfill(4)}_"
            f"{self.extended['SEQ_ID'].iloc[0].lower()}_mosaic"
        )
        self.local_files = list(mosaic_fits_files)

    def format_metadata(self):
        # "summary" values made from chronologically first image
        summary = self.extended.sort_values(by=["SCLK", "BAND"]).iloc[0].copy()
        # write canonical pointing-identifying values into all frames
        for field, value in parse_pointing(summary).items():
            summary[field] = value
            self.extended[field] = value
        creation_time = dt.datetime.utcnow().isoformat()
        summary["FILE_TIMESTAMP"] = creation_time
        self.extended["ASDF_VERSION"] = asdf.__version__
        self.summary = summary
        self.extended = polish_metadata(self.extended, creation_time)
