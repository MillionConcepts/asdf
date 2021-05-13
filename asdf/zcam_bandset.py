import datetime as dt
from functools import partial
from pathlib import Path

import asdf
from asdf import settings
from asdf.asdf_utils import (
    dupe_df_block,
    load_roi_file,
    null_marslab_data_section,
)
from asdf.scrape import (
    make_pointing_name,
    bulk_scrape_metadata,
    add_derived_illumination_geometry,
    melt_metadata,
    parse_pointing,
    check_and_drop_duplicate_columns,
)
from marslab.bandset import BandSet, rasterio_load_scaled
from marslab.compat.mertools import add_merspect_colors_to_edgemaps
from marslab.compat.xcam import (
    DERIVED_CAM_DICT,
    NARROWBAND_TO_BAYER,
    count_rois_on_xcam_images,
)
import pandas as pd
from marslab.imgops import (
    RGGB_PATTERN,
    make_roi_edgemaps,
    draw_edgemaps_on_image,
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
    def __init__(self, pointing, rois, suffix=""):
        files = setup_zcam_bandset_metadata(pointing)
        load_method = partial(rasterio_load_scaled, preserve_constants=[0])
        bayer_info = {"pattern": RGGB_PATTERN}
        super(ZcamBandSet, self).__init__(
            metadata=files,
            load_method=load_method,
            bayer_info=bayer_info,
            rois=rois,
        )
        # scrape headers for all desired metadata fields and derive values
        # from them as necessary
        headers = pd.DataFrame(bulk_scrape_metadata(self.metadata["PATH"]))
        self.metadata = pd.concat((self.metadata, headers), axis=1)
        self.metadata = add_derived_illumination_geometry(self.metadata)
        self.name = make_pointing_name(self.metadata)
        if suffix != "":
            self.suffix = "-" + suffix

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
            print("No ROI data loaded.")
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
            print("No ROI data loaded.")
            return ""
        if isinstance(self.rois, (str, Path)):
            self.load_rois()
        self.counts = count_rois_on_xcam_images(
            self.rois,
            self.raw,
            "ZCAM",
            bayer_pixel_dict=self.metadata["BAYER_PIXEL"].to_dict(),
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

    def write_data_files(self, output_path, verbose=False):
        metadata_fn = str(
            Path(output_path, self.name + self.suffix + "-marslab.csv")
        )
        extended_metadata_fn = str(
            Path(
                output_path, self.name + self.suffix + "-marslab-extended.csv"
            )
        )
        if verbose:
            print(
                "Writing extended-format marslab file: " + extended_metadata_fn
            )
        self.extended.fillna("-").to_csv(
            extended_metadata_fn,
            index=False,
        )
        if verbose:
            print("Writing compact-format marslab file: " + metadata_fn)
        self.compact.fillna("-").to_csv(metadata_fn, index=False)
        return metadata_fn, extended_metadata_fn

    def write_context_image(
        self,
        edgemaps,
        eye,
    ):
        instruction = {
            "operation": "enhanced color",
            "options": {
                "special_constants": [0],
                "normalize": (0, 1, 1, 1)
            },
            "crop": (25, 25, 11, 11),
        }
        if eye[0].upper() + "0R" in self.metadata["BAND"]:
            instruction["bands"] = (eye[0] + "0R", eye[0] + "0G", eye[0] + "0B")
        else:
            band = self.metadata.loc[self.metadata["BAND"].str.startswith(eye[0]), "BAND"].iloc[0]
            instruction["bands"] = (band, band, band)
        self.make_look_set({'context ' + eye: instruction})
        # wait do i not look at key? do i need to set 'name'? yikes
        context_image = self.looks['context ' + eye]
        eye_edgemaps = {
            key: value for key, value in edgemaps.items() if eye in key
        }

        # context_image = draw_edgemaps_on_image(base_image, eye_edgemaps,
        #                                        width=0.1)
        # pointing_name, target_name = titular_names(pointing)
        # if suffix != "":
        #     target_name = target_name + " " + suffix + " "
        #     pointing_name = pointing_name + "-" + suffix
        # title = "\n".join(
        #     (
        #         target_name + eye + " ROI context image",
        #         make_pointing_annotation(pointing),
        #         settings.rapidlooks.CREDIT_TEXT,
        #     )
        # )
        # context_image.axes[0].set_xlabel(
        #     title, loc="center", fontproperties=settings.rapidlooks.TITLE_FONT
        # )
        # print(
        #     "writing "
        #     + str(Path(outpath, pointing_name + "-context-" + eye + ".png"))
        # )
        # context_image.savefig(
        #     Path(outpath, pointing_name + "-context-" + eye + ".png"),
        #     dpi=240,
        # )
        # return context_image

    def make_context_images(self, verbose=False):
        # TODO: automatically try to count ROIs and stuff
        if verbose:
            print("... making ROI context images ...")
        edgemaps = make_roi_edgemaps(self.rois, calculate_centers=False)
        edgemaps = add_merspect_colors_to_edgemaps(edgemaps)
        for eye in ("left", "right"):
            eye_image = write_context_image(
                preloaded_images,
                edgemaps,
                eye,
                pointing,
                outpath,
                onboard_debayer,
                suffix,
            )
            if eye_image:
                context_images["context image " + eye] = eye_image
        return context_images
