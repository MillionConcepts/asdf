import datetime as dt
import re
import time
from ast import literal_eval
from functools import partial
from itertools import product
from pathlib import Path

import cv2
import matplotlib as mpl
import numpy as np
import pandas as pd
import sh
import skimage
from astropy.io import fits
from astropy.table import Table
from dustgoggles.func import gmap
from pdr.np_utils import enforce_order_and_object
from scipy.ndimage import center_of_mass, label
from marslab.imgops.render import flatten_into_figure, simple_figure

import asdf
from asdf.asdf_utils import cast_to_reference
from asdf.console import aprint, ASDFLOG
from asdf.parse import parse_pointing
from asdf.zcam_bandset import polish_metadata
from asdf_settings import process, rapidlooks
from marslab.bandset import BandSet
from marslab.compat.xcam import DERIVED_CAM_DICT
from marslab.imgops.imgutils import crop, normalize_range, eightbit

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


def bounce_to_tiff(mosaic, scratch_path=".temp/mosaic"):
    Path(scratch_path).mkdir(exist_ok=True)
    bandlist = [set(b.metadata["BAND"].unique()) for b in mosaic]
    if len(set(map(frozenset, bandlist))) != 1:
        aprint(
            "[bold red]Mismatched availability between bands in these frames."
            " Unable to mosaic."
        )
        return
    bands = sorted(bandlist[0])
    tiff_info = []
    for bandset, band in product(mosaic, bands):
        bandset.load([band])
        bandset.bulk_debayer([band])
        cropped = crop(
            bandset.get_band(band), rapidlooks.CROP_SETTINGS["crop"]
        )
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
            "shape": cropped.shape
        }
        tiff_info.append(tiff_rec)
        bandset.purge()
    tiff_info = pd.DataFrame(tiff_info)
    locator_info, rsms = [], [bs.metadata["RSM"].iloc[0] for bs in mosaic]
    cmap_names = ("Set1", "tab10")
    colors = []
    # TODO: ...these don't actually need to be different colors, do they
    for bandset in mosaic:
        rsm = bandset.metadata["RSM"].iloc[0]
        frameslice = tiff_info.loc[tiff_info['rsm'] == rsm]
        # it is probably unnecessary to write all of these files, but it's not
        # very expensive and i'm being defensive about some kind of weird
        # subframe edge case
        for eye in frameslice['eye'].unique():
            ref = frameslice.loc[frameslice['eye'] == eye].iloc[0]
            # feeding hugin b/w ref maps results in pathological behavior
            # when blending the location maps in some cases
            here = np.dstack(
                # note that cv2.imwrite turns this 'red' into 'blue' because
                # of cv2's default BGR colorspace
                [np.full(ref['shape'], c, np.uint8) for c in (255, 0, 0)]
            )
            loc_path = Path(scratch_path, f"{eye}_loc_{bandset.name}.tiff")
            cv2.imwrite(str(loc_path), here)
            aprint(f"wrote {loc_path}")
            loc_rec = {
                "rsm": rsm,
                "seq_id": bandset.metadata["SEQ_ID"].iloc[0],
                "bandset_name": bandset.name,
                "path": loc_path,
                "fov": ref['fov'],
                "eye": eye,
                "shape": ref['shape'],
                'type': f'present_{rsm}'
            }
            locator_info.append(loc_rec)
            not_here = np.dstack(
                [np.full(ref['shape'], 100, np.uint8) for _ in range(3)]
            )
            loc0_path = Path(scratch_path, f"{eye}_loc0_{bandset.name}.tiff")
            cv2.imwrite(str(loc0_path), not_here)
            aprint(f"wrote {loc0_path}")
            for other_rsm in filter(lambda r: r != rsm, rsms):
                loc0_rec = loc_rec | {
                    'path': loc0_path,
                    'rsm': other_rsm,
                    'type': f'absent_{rsm}'
                }
                locator_info.append(loc0_rec)
    return tiff_info, pd.DataFrame(locator_info)


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
    # TODO: is this a pathological condition?
    if crop_match is None:
        return width, height
    text = text.replace(crop_match.group(1), f"S0,{width},0,{height}")
    with open(pto_file, "w") as stream:
        stream.write(text)
    return width, height


def hugin_assistant(pto_file, timeout=15):
    cmd = sh.hugin_executor("--assistant", pto_file, _bg=True, _bg_exc=False)
    start = time.time()
    while cmd.is_alive():
        time.sleep(0.05)
        runtime = time.time() - start
        if runtime > timeout:
            raise TimeoutError
    if cmd.exit_code != 0:
        raise ValueError
    return cmd


def execute_hugin_stitch(pto_file, threads=1, prefix=None):
    command_parts = ["-s", pto_file, "-t", threads]
    if prefix is not None:
        command_parts = ["-p", prefix] + command_parts
    return sh.hugin_executor(*command_parts)


def read_first_channel(path):
    return skimage.io.imread(path)[:, :, 0]


def pano_modify(
    pto_file,
    output_type="NORMAL",
    # projection: 0=rectilinear, 1=cylindrical, 2=equirectangular, 3=fisheye
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


def crop_outer(array, return_bounds=False):
    nzy, nzx = np.nonzero(array)
    bounds = nzx.min(), nzx.max(), nzy.min(), nzy.max()
    if return_bounds is False:
        return crop(array, bounds)
    return crop(array, bounds), bounds


def mark_borders(
    array,
    border_threshold=0,
    how=np.less_equal,
    special_constant=-9999,
    inplace=True
):
    """marks outer borders of array with a special constant"""
    if inplace is False:
        array = array.copy()
    zeromask = how(array, border_threshold)
    borderlabels = label(~zeromask)[0]
    exterior = np.zeros(array.shape, dtype=bool)
    for label_ix in np.unique(borderlabels):
        region = borderlabels == label_ix
        zero_pred = zeromask[region].all()
        if zero_pred:
            exterior[region] = True
    array[np.nonzero(exterior)] = special_constant
    return array


def concat_mosaic_fn(sol, seq_id, eye):
    return f"sol{str(sol).zfill(4)}_{seq_id.lower()}_{eye.lower()}_mosaic.fits"


def make_single_band_mosaics(eye, band_info, loc_info, bandsets, **pto_kwargs):
    eye_name = {"L": "left", "R": "right"}[eye]
    available_bands = band_info["band"].tolist()
    eye_bands = [b for b in available_bands if b.startswith(eye)]
    if len(eye_bands) == 0:
        return {}, None
    ref_band = next(
        (
            f"{eye}{n}" for n in PREFERRED_REF_BANDS
            if f"{eye}{n}" in eye_bands
        )
    )
    ref_slice = band_info.loc[band_info['band'] == ref_band]
    ref_tiffs = []
    for bandset in bandsets:
        bandset.load([ref_band])
        bandset.bulk_debayer([ref_band])
        reference_image = normalize_range(
            crop(bandset.get_band(ref_band), rapidlooks.CROP_SETTINGS["crop"]),
            (0, 1),
            5
        )
        tiff_path = Path(
            Path(ref_slice['path'].iloc[0]).parent,
            f"{ref_band}_reference_{bandset.name}.tiff"
        )
        cv2.imwrite(str(tiff_path), reference_image)
        rsm = bandset.metadata['RSM'].iloc[0]
        ref_tiffs.append({'path': tiff_path, 'rsm': rsm})
        aprint(f"wrote {eye_name}-eye reference image for RSM {rsm}")
    try:
        ref_pto_file, _ = ref_projection(
            [rt['path'] for rt in ref_tiffs],
            np.mean(ref_slice['fov']),
            **pto_kwargs
        )
    except (TimeoutError, ValueError, sh.ErrorReturnCode) as err:
        aprint(
            f"[bold red] Unable to find usable reference projection for "
            f"{eye_name}-eye mosaic."
        )
        return None, None, None
    ASDFLOG.info(f"generated projection for {eye_name}-eye mosaic")
    with open(ref_pto_file) as stream:
        ref_text = stream.read()
    pto_files, band_tifs = {ref_band: ref_pto_file}, {}
    for band in eye_bands:
        band_slice = band_info.loc[band_info["band"] == band]
        pto_file = Path(
            ref_pto_file.parent, ref_pto_file.name.replace(ref_band, band)
        )
        insert_band_filenames(pto_file, band_slice, ref_text, ref_tiffs)
        sh.pto_var(
            pto_file,
            set="Vb=0,Vc=0,Vd=0",
            output=Path(pto_file.parent, pto_file.stem + "_var.pto")
        )
        pto_files[band] = Path(pto_file.parent, pto_file.stem + "_var.pto")
    ASDFLOG.info("generated per-band projection instructions")
    try:
        create_intermediate_mosaics(pto_files, band_tifs)
    except sh.ErrorReturnCode:
        aprint(
            f"[bold red] reference projection for {eye_name}-eye mosaic "
            f"failed to generate a usable mosaic."
        )
        return None, None, None
    eye_locators = loc_info.loc[loc_info['eye'] == eye]
    loc_pto_files, loc_tifs = {}, {}
    for rsm in loc_info['rsm'].unique():
        pto_file = Path(
            ref_pto_file.parent,
            ref_pto_file.name.replace(ref_band, f"{rsm}_{eye}")
        )
        insert_locator_filenames(
            pto_file, eye_locators, ref_text, ref_tiffs, rsm
        )
        sh.pto_var(
            pto_file,
            set="Vb=0,Vc=0,Vd=0",
            output=Path(pto_file.parent, pto_file.stem + "_var.pto")
        )
        loc_pto_files[f"{rsm}_{eye}"] = Path(
            pto_file.parent, pto_file.stem + "_var.pto"
        )
    create_intermediate_mosaics(loc_pto_files, loc_tifs)
    return band_tifs, loc_tifs, ref_text


def insert_band_filenames(pto_file, band_slice, ref_text, ref_tiffs):
    band_text = ref_text
    for rec in ref_tiffs:
        band_path = band_slice.loc[
            (band_slice['rsm'] == rec['rsm']), 'path'
        ].iloc[0]
        band_text = band_text.replace(rec['path'].name, band_path.name)
    with pto_file.open("w") as stream:
        stream.write(band_text)


def insert_locator_filenames(pto_file, eye_locators, ref_text, ref_tiffs, rsm):
    loc_text = ref_text
    for rec in ref_tiffs:
        prefix = "present" if rec['rsm'] == rsm else "absent"
        loc_path = eye_locators.loc[
            eye_locators['type'] == f"{prefix}_{rec['rsm']}", 'path'
        ].iloc[0]
        loc_text = loc_text.replace(rec['path'].name, loc_path.name)
    with pto_file.open("w") as stream:
        stream.write(loc_text)


def create_intermediate_mosaics(pto_files, tif_files):
    parent = Path(list(pto_files.values())[0]).parent
    for band, pto_file in pto_files.items():
        stdout = execute_hugin_stitch(
            pto_file,
            threads=process.THREADS['mosaic_gen'],
            prefix=Path(pto_file.parent, band)
        )
        intermediate_tif_file = re.search(r'saving (.*?.tif)', stdout).group(1)
        tif_files[band] = Path(parent, f"{intermediate_tif_file[:-8]}.tif")
        ASDFLOG.info(f"wrote {band} intermediate mosaic file")


def ref_projection(tiff_files, fov, projection=1):
    _, ref_pto_file = zcam_pto_gen(tiff_files, fov)
    assistant_cmd = hugin_assistant(ref_pto_file)
    pano_modify(ref_pto_file, canvas="AUTO", projection=projection)
    remove_hugin_crop_instruction(ref_pto_file)
    return ref_pto_file, assistant_cmd


def preprocess_mosaic_metadata(bandsets):
    all_metadata = pd.concat([b.metadata for b in bandsets])
    all_metadata = all_metadata.drop(columns=["ANALYSIS_NAME", "stem", "PATH"])
    return cast_to_reference(all_metadata, LONG_METADATA_DTYPES)


def concatenate_mosaic(process_info, eye, all_metadata, outpath=None):
    band_tifs, loc_tifs, ref_text = process_info[eye]
    arrays = {}
    for band, file in band_tifs.items():
        cropped, bounds = crop_outer(
            read_first_channel(file), return_bounds=True
        )
        arrays[band] = mark_borders(cropped)
    if not len({arr.shape for arr in arrays.values()}) == 1:
        raise ValueError("apparent misalignment.")
    reference_blue = (0, 0, 255)
    for rsm, file in loc_tifs.items():
        # noinspection PyUnboundLocalVariable
        color_loc = crop(skimage.io.imread(file), bounds)
        outside = np.nonzero(np.mean(color_loc, axis=-1) == 0)
        color_loc = color_loc.astype(np.int16)
        channels = []
        for i in range(3):
            channels.append(
                255 - np.abs(color_loc[:, :, i] - reference_blue[i])
            )
        restacked = np.dstack(channels)
        flattened = np.mean(restacked, axis=2)
        flattened[flattened < 137] = 137
        normed = normalize_range(flattened, (0, 255), 1).astype(np.uint8)
        normed[outside] = 0
        arrays[f'{rsm}_loc'] = normed
    image_hdus = [
        fits.ImageHDU(arrays[band], name=band)
        for band in sorted(arrays.keys())
    ]
    meta_hdu = fits.table_to_hdu(
        Table.from_pandas(
            all_metadata.loc[all_metadata["BAND"].isin(arrays.keys())]
        )
    )
    meta_hdu.name = "metadata"
    ref_lines = tuple(filter(None, ref_text.split('\n')))
    text_column = fits.Column(
        name='text', array=ref_lines, format=f'A{max(map(len, ref_lines))}'
    )
    proj_hdu = fits.TableHDU.from_columns([text_column], name='projection')
    hdul = fits.HDUList([fits.PrimaryHDU(), *image_hdus, proj_hdu, meta_hdu])
    if outpath is None:
        outpath = tuple(band_tifs.values())[0].parent
    mosaic_fn = concat_mosaic_fn(
        meta_hdu.data['SOL'][0], meta_hdu.data['SEQ_ID'][0], eye
    )
    if Path(outpath, mosaic_fn).exists():
        Path(outpath, mosaic_fn).unlink()
    hdul.writeto(Path(outpath, mosaic_fn), overwrite=True)
    return Path(outpath, mosaic_fn)


def simple_fits_load(
    path, metadata, bands, _precached, missing_constants=None
):
    """extremely simple fits loader for BandSet. Loads from HDUs by index."""
    hdul = fits.open(path)
    arrays = {}
    for band in bands:
        band_ix = metadata.loc[metadata["BAND"] == band, "IX"]
        if len(band_ix) == 0:
            continue
        array = hdul[band_ix.iloc[0]].data
        # TODO, maybe: actual scaling rather than just special constant masking
        #  (although astropy handles that to same extent by default)
        if missing_constants is not None:
            array = np.ma.masked_where(
                np.isin(array, missing_constants), array
            )
        arrays[band] = array
    return arrays


class ZMosaicBandSet(BandSet):
    def __init__(self, mosaic_fits_files, threads=None):
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
            DERIVED_CAM_DICT["ZCAM"]["filters"].get(band)
            for band in metadata["BAND"]
        ]
        super().__init__(
            metadata=metadata,
            load_method=partial(simple_fits_load, missing_constants=(-9999,)),
            threads=threads
        )
        self.extended = pd.concat(extended).reset_index(drop=True)
        self.extended['RMC'] = self.extended['RMC'].map(literal_eval)
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


def make_mosaic_map(eye, mosaic):
    locs = mosaic.metadata[
        mosaic.metadata['BAND'].str.match(rf"\d+_{eye}_LOC")
    ]
    cmap_names = ("Set1", "tab10")
    colors = []
    for i in range(len(locs['BAND'])):
        if i <= 7:
            cmap = mpl.colormaps.get_cmap(cmap_names[0])
            colors.append(cmap(i)[:3])
        else:
            cmap = mpl.colormaps.get_cmap(cmap_names[1])
            colors.append(cmap(i - 8)[:3])
    loc_images, centers = [], []
    mosaic.load(locs['BAND'].tolist())
    for color, name in zip(colors, locs['BAND']):
        alpha = mosaic.get_band(name) / 255
        centers.append(center_of_mass(alpha))
        rsm_loc = np.dstack(
            [
                np.full(alpha.shape, color[0]),
                np.full(alpha.shape, color[1]),
                np.full(alpha.shape, color[2]),
                alpha
            ]
        )
        loc_images.append(rsm_loc)
    fig, ax = flatten_into_figure(loc_images)
    for name, center in zip(locs['BAND'], centers):
        rsm = name.split("_")[0]
        ax.text(
            *reversed(center),
            f"{rsm}{eye}",
            fontproperties=rapidlooks.TITLE_FONT
        )
    return fig


def just_render(array, clip=0.1):
    if array.dtype != np.uint8:
        array = eightbit(array, clip)
    return simple_figure(array, cmap='Greys_r')