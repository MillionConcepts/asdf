import datetime as dt
import io
from functools import partial
from pathlib import Path

from cytoolz import keyfilter

from asdf.console import ASDF_CONSOLE
from marslab.imgops.bandset import BandSet
from marslab.imgops.debayer import RGGB_PATTERN
from marslab.imgops.imgutils import normalize_range
from marslab.imgops.loaders import rasterio_load
from marslab.imgops.regions import make_roi_edgemaps, draw_edgemaps_on_image

from marslab.compat.mertools import add_merspect_colors_to_edgemaps
from marslab.compat.xcam import (
    DERIVED_CAM_DICT,
    NARROWBAND_TO_BAYER,
    count_rois_on_xcam_images,
)
import pandas as pd

import asdf
from asdf import settings
from asdf.asdf_utils import (
    dupe_df_block,
    load_roi_file,
    null_marslab_data_section,
    check_and_drop_duplicate_columns,
    dashify,
)
from asdf.scrape import (
    make_pointing_name,
    bulk_scrape_metadata,
    add_derived_illumination_geometry,
    melt_metadata,
    parse_pointing,
)


def polish_metadata(metadata, creation_time):
    metadata["FILE_TIMESTAMP"] = creation_time
    dataframe = check_and_drop_duplicate_columns(metadata)
    extra_columns = [
        column
        for column in dataframe.columns
        if column not in settings.metadata.COMPACT_ZCAM_MARSLAB_FIELDS
    ]
    ordered_fields = dataframe.reindex(
        settings.metadata.COMPACT_ZCAM_MARSLAB_FIELDS, axis=1
    )
    return pd.concat([ordered_fields, dataframe[extra_columns]], axis=1)


def setup_zcam_bandset_metadata(metadata):
    if "FILTER" in metadata.columns:
        metadata["BAND"] = metadata["FILTER"]
        metadata.drop("FILTER", axis=1)
    metadata.index = metadata["BAND"]
    # add references to the secret bands hidden inside the L0 and R0 images
    bayer_filter_rows = []
    for eye in ("L", "R"):
        if eye + "0" not in metadata.index:
            continue
        eye_row = metadata.loc[eye + "0"]
        for color in ("R", "G", "B"):
            eye_color_row = eye_row.copy()
            eye_color_row["BAND"] = eye + "0" + color
            eye_color_row.name = eye + "0" + color
            bayer_filter_rows.append(eye_color_row)
        metadata = metadata.drop(eye_row.name)
    metadata = pd.concat((metadata, pd.concat(bayer_filter_rows, axis=1).T))
    # add wavelengths and bayer pixel mappings
    metadata["WAVELENGTH"] = pd.Series(DERIVED_CAM_DICT["ZCAM"]["filters"])[
        metadata["BAND"]
    ]
    metadata["BAYER_PIXEL"] = pd.Series(NARROWBAND_TO_BAYER["ZCAM"])[
        metadata["BAND"]
    ]
    return metadata.reset_index(drop=True)


class ZcamBandSet(BandSet):
    def __init__(self, pointing, rois, suffix="", threads=None):
        files = setup_zcam_bandset_metadata(pointing)
        load_method = partial(rasterio_load, preserve_constants=[0])
        bayer_info = {"pattern": RGGB_PATTERN}
        super().__init__(
            metadata=files,
            load_method=load_method,
            bayer_info=bayer_info,
            rois=rois,
            threads=threads,
        )
        # scrape headers for all desired metadata fields and derive values
        # from them as necessary
        dtypes = settings.metadata.metadata_dtypes
        self.metadata = self.metadata.astype(
            keyfilter(lambda key: key in self.metadata.columns, dtypes)
        )
        headers = pd.DataFrame(bulk_scrape_metadata(self.metadata["PATH"]))
        headers = headers.astype(
            keyfilter(lambda key: key in headers.columns, dtypes)
        )
        self.metadata = pd.concat(
            [self.metadata, headers], axis=1, join="inner"
        )
        # todo: maybe add some checks here, it's a headache
        concat = pd.concat((self.metadata, headers), axis=1)
        self.metadata = concat.iloc[:, ~concat.columns.duplicated()].copy()
        self.metadata = add_derived_illumination_geometry(self.metadata)
        self.name = make_pointing_name(self.metadata)
        if suffix != "":
            self.suffix = "-" + suffix
        else:
            self.suffix = suffix
        self.check_onboard_debayer()

    def check_onboard_debayer(self):
        """
        if this observation was debayered onboard, drop all references to
        bayer pixels to avoid inappropriate debayering later. add
        references to additional bands of R0 / L0 image files (that don't
        exist in raw bayer images).
        TODO: verify that there are no pointings for which only some images
          are debayered onboard
        """
        if all(self.metadata["BAYER"] == "RAW_BAYER"):
            return False
        self.metadata["BAYER_PIXEL"] = None
        for color, ix in zip(("R", "G", "B"), (0, 1, 2)):
            self.metadata.loc[
                self.metadata["BAND"].str.endswith(color), "IX"
            ] = ix
        return True

    def load_rois(self, title=None, outpath=None, convert=False):
        if self.rois is None:
            ASDF_CONSOLE.print("No ROI data loaded.")
            return ""
        if title is None:
            title = self.name
        roi_hdulist, roi_fn = load_roi_file(
            self.rois, title=title, outpath=outpath, convert=convert
        )
        self.rois = roi_hdulist
        return roi_fn

    def count_rois(self):
        if self.rois is None:
            ASDF_CONSOLE.print("No ROI data loaded.")
            return ""
        if isinstance(self.rois, (str, Path)):
            self.load_rois()
        self.counts = count_rois_on_xcam_images(
            self.rois,
            self.raw,
            "ZCAM",
            bayer_pixel_dict={
                band: pixel
                for band, pixel in zip(
                    self.metadata["BAND"].tolist(),
                    self.metadata["BAYER_PIXEL"].tolist(),
                )
            },
        )
        return self.counts

    def format_metadata(self):
        if self.counts is None:
            self.counts = null_marslab_data_section()
        # "summary" values made from chronologically first image
        summary = self.metadata.sort_values(by="SCLK").iloc[0].copy()
        metadata_block = dupe_df_block(
            melt_metadata(self.metadata), len(self.counts.index)
        )
        extended = pd.concat([metadata_block, self.counts], axis=1)
        compact = self.counts.copy()
        # write canonical pointing-identifying values into all frames
        for field, value in parse_pointing(summary).items():
            summary[field] = value
            extended[field] = value
            compact[field] = value
        # set variable-by-image values equal to chronologically first value
        # in compact version
        for field, value in summary.iteritems():
            if field in settings.metadata.COMPACT_ZCAM_MARSLAB_FIELDS:
                compact[field] = value
        creation_time = dt.datetime.utcnow().isoformat()
        summary["FILE_TIMESTAMP"] = creation_time
        summary["NAME"] = summary["NAME"] + self.suffix
        extended["ASDF_VERSION"] = asdf.__version__
        self.summary = summary
        self.extended = polish_metadata(extended, creation_time)
        self.compact = polish_metadata(compact, creation_time)

    def write_data_files(self, outpath=".", verbose=False, in_memory=False):
        if in_memory is False:
            stem = str(Path(outpath, self.name + self.suffix))
            metadata_file = stem + "-marslab.csv"
            extended_file = stem + "-marslab-extended.csv"
        else:
            metadata_file = io.BytesIO()
            extended_file = io.BytesIO()
        if verbose and (in_memory is not False):
            ASDF_CONSOLE.print(
                "Writing extended-format marslab file: " + extended_file
            )

        dashify(self.extended).to_csv(extended_file, index=False)
        if verbose and (in_memory is not False):
            ASDF_CONSOLE.print(
                "Writing compact-format marslab file: " + metadata_file
            )
        dashify(self.compact).to_csv(metadata_file, index=False)
        return metadata_file, extended_file

    def draw_context(self, edgemaps, eye):
        inst = {
            "name": "context image " + eye,
            "no_band_names": True,
            "look": "composite",
            "params": {"special_constants": [0]},
            "limiter": {
                "function": normalize_range,
                "params": {"stretch": 0.1},
            },
        }
        initial = eye[0].upper()
        if initial + "0R" in self.metadata["BAND"].values:
            inst["bands"] = (initial + "0R", initial + "0G", initial + "0B")
        else:
            band = self.metadata.loc[
                self.metadata["BAND"].str.startswith(initial), "BAND"
            ].iloc[0]
            inst["bands"] = (band, band, band)
        self.make_look_set({"context " + eye: inst})
        eye_edgemaps = {
            key: value for key, value in edgemaps.items() if eye in key
        }
        self.looks["context image " + eye] = draw_edgemaps_on_image(
            self.looks["context image " + eye], eye_edgemaps, width=0.1
        )

    def make_context_images(self, verbose=False):
        # TODO: automatically try to count ROIs and stuff
        if verbose:
            ASDF_CONSOLE.print("... making ROI context images ...")
        edgemaps = make_roi_edgemaps(self.rois, calculate_centers=False)
        edgemaps = add_merspect_colors_to_edgemaps(edgemaps)
        for eye in ("left", "right"):
            self.draw_context(edgemaps, eye)

    def titular_target(self):
        """
        return the observation name, if set, falling back
        to the first ROI target name, if available
        """
        target_name = self.metadata["NAME"].iloc[0]
        if (not target_name) and (self.counts is not None):
            if len(self.counts["TARGET"].dropna()) > 0:
                target_name = self.metadata["TARGET"].dropna().iloc[0]
        # TODO: check if this is a nan, make it an empty string or whatever
        if target_name:
            return target_name
        return ""
