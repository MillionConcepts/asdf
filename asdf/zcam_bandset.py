import datetime as dt
import io
import os
import shutil
import warnings
from collections.abc import MutableMapping
from functools import partial
from pathlib import Path

import numpy as np
import pandas as pd
import pdr
from cytoolz import keyfilter
from matplotlib import pyplot as plt

import asdf
import asdf_settings
from asdf.asdf_utils import (
    load_roi_file,
    null_marslab_data_section,
    dashify,
    save_roi_file,
    cast_to_reference,
)
from dustgoggles.pivot import dupe_df_block, check_and_drop_duplicate_columns
from dustgoggles.structures import to_records, NestingDict
from asdf.console import aprint
from asdf.format import (
    melt_metadata,
    METADATA_DTYPES,
    count_rois_on_pixmaps,
    drop_excess_stats,
    perfectly_black_rectangular_solid,
)
from asdf.parse import parse_pointing, make_pointing_name
from asdf.physics import add_derived_illumination_geometry
from asdf.labels import bulk_scrape_asdf_metadata
from asdf.rc_parser import find_rc_file, read_rc_file
from asdf_settings.metadata import (
    PIXEL_FLAG_NAMES,
    PIXEL_FLAG_STYLE,
    COMPACT_MARSLAB_STATS,
)
from asdf_settings.rapidlooks import LEGEND_FONT
from marslab.compat.mertools import add_merspect_colors_to_edgemaps
from marslab.compat.xcam import (
    DERIVED_CAM_DICT,
    BAND_TO_BAYER,
    count_rois_on_xcam_images,
    construct_field_ordering,
)
from marslab.bandset import BandSet
from marslab.geom import transform_angle, get_coordinates
from marslab.imgops.debayer import RGGB_PATTERN, mask_bayer_pixels
from marslab.imgops.imgutils import normalize_range
from marslab.imgops.loaders import pdr_load
from marslab.imgops.pltutils import remove_ticks, despine
from marslab.imgops.regions import (
    make_roi_edgemaps,
    draw_edgemaps_on_image,
    draw_edgemaps_on_axis,
)


def polish_metadata(metadata, creation_time):
    metadata["FILE_TIMESTAMP"] = creation_time
    dataframe = check_and_drop_duplicate_columns(metadata)
    ordering = construct_field_ordering(
        filters=tuple(DERIVED_CAM_DICT["ZCAM"]["filters"].keys()),
        fields=dataframe.columns
    )
    return pd.concat(
        [
            dataframe[[f for f in ordering if f in dataframe.columns]],
            dataframe[[f for f in dataframe.columns if f not in ordering]]
        ],
        axis=1
    )


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
    if bayer_filter_rows:
        metadata = pd.concat(
            (metadata, pd.concat(bayer_filter_rows, axis=1).T)
        )
    # add wavelengths and bayer pixel mappings
    metadata["WAVELENGTH"] = pd.Series(DERIVED_CAM_DICT["ZCAM"]["filters"])[
        metadata["BAND"]
    ]
    metadata["BAYER_PIXEL"] = pd.Series(BAND_TO_BAYER["ZCAM"])[
        metadata["BAND"]
    ]
    return metadata.reset_index(drop=True)


class ZcamBandSet(BandSet):
    def __init__(self, pointing, rois=None, suffix="", threads=None):
        files = setup_zcam_bandset_metadata(pointing)
        load_method = partial(pdr_load, preserve_constants=[0])
        bayer_info = {"pattern": RGGB_PATTERN}
        super().__init__(
            metadata=files,
            load_method=load_method,
            bayer_info=bayer_info,
            rois=rois,
            threads=threads,
        )
        # convert metadata dataframe to specified dtypes
        self.metadata = cast_to_reference(self.metadata, METADATA_DTYPES)
        # initialize pdr.Data objects to read metadata from files and later
        # load images (if relevant)
        for path in self.metadata["PATH"].unique():
            self.precached[path] = pdr.Data(
                path, label_fn=path, skip_existence_check=True
            )
        # scrape headers for all desired metadata fields
        headers = self._get_headers_from_precached_metadata()
        self.metadata = pd.concat(
            [self.metadata, headers], axis=1, join="inner"
        )
        self.metadata = self.metadata.iloc[
            :, ~self.metadata.columns.duplicated()
        ].copy()
        self.metadata = add_derived_illumination_geometry(self.metadata)
        self.name = make_pointing_name(self.metadata)
        # TODO: this is horrible, refactor this garbage attribute
        self.suffix = "-" + suffix if suffix != "" else suffix
        self.metadata["ANALYSIS_NAME"] = suffix
        self.check_onboard_debayer(fix_metadata=True)
        self.pixmaps = {}
        self.pixmap_counts = {}
        self.local_files = []
        # additional tables to hold metadata / marslab-like files scraped
        # from rc files
        self.rc_metadata = None
        self.rc_compact = None
        # a slightly goofy holding location for things like google drive ids
        self.remote_resource_id = None
        self.special_constants = [0]

    def scrape_rc_files(self):
        rc_table_map = {}
        rc_metadata = {}
        for ix, row in self.metadata.iterrows():
            rc_file = find_rc_file(row["RC_FILE"], row["PATH"])
            # TODO: handle this more prettily
            if rc_file is None:
                aprint(
                    f"[bold dark orange]Missing rc file(s), cancelling rc "
                    f"file processing."
                )
                return
            rc_roi_table, rc_file_metadata = read_rc_file(rc_file)
            rc_table_map[row["BAND"]] = rc_roi_table
            rc_metadata[row["BAND"]] = rc_file_metadata
        rc_metadata = pd.DataFrame(rc_metadata)
        superfluous = filter(
            lambda c: c in rc_metadata.columns, ("FILTER_NUMBER", "CHANNEL")
        )
        rc_metadata = rc_metadata.drop(list(superfluous), axis=1)
        self.rc_metadata = self._make_caltarget_table(
            rc_metadata, rc_table_map
        )
        rc_metadata = rc_metadata.T.reset_index(drop=True)
        rc_metadata.columns = [f"RC_{col}" for col in rc_metadata.columns]
        self.metadata = pd.concat([self.metadata, rc_metadata], axis=1)

    @staticmethod
    def _make_caltarget_table(rc_metadata, rc_table_map):
        rc_marslab_chunks = []
        for band, table in rc_table_map.items():
            band_metadata = rc_metadata[band]
            for col, value in band_metadata.iteritems():
                table[col] = value
            table.columns = [
                # matching 'reflectance field is the band name' convention
                f"{band}_{col}".strip("_")
                for col in table.columns
            ]
            rc_marslab_chunks.append(table.copy())  # copy defrag
        rc_marslab = pd.concat(rc_marslab_chunks, axis=1)
        rc_marslab["INSTRUMENT"] = "ZCAM"
        return rc_marslab.copy()  # copy defrag

    def _get_headers_from_precached_metadata(self):
        headers = pd.DataFrame(bulk_scrape_asdf_metadata(self.precached))
        geometry = []
        for data in self.precached.values():
            instrument = get_coordinates(data)["ROVER"]["INSTRUMENT"]
            solar_el, solar_az, _ = transform_angle(
                "SITE", "ROVER", "SOLAR", data
            )
            geometry.append(
                {
                    "INSTRUMENT_ELEVATION": instrument["ELEVATION"],
                    "INSTRUMENT_AZIMUTH": instrument["AZIMUTH"],
                    "SOLAR_ELEVATION": solar_el,
                    "SOLAR_AZIMUTH": solar_az,
                }
            )
        headers = pd.concat([headers, pd.DataFrame(geometry)], axis=1)
        headers = cast_to_reference(headers, METADATA_DTYPES)
        # dupe rows as necessary to recreate bayer pixels w/out reading
        # files with pdr.Data again or setting up some silly cache
        header_rows = []
        for _, row in self.metadata.iterrows():
            match = headers.loc[headers["PATH"] == row["PATH"]].copy()
            if row["FILTER"] in ("L0", "R0"):
                # each bayer band has a separate rc file, but the file headers
                # only point to the red-band file
                match["RC_FILE"] = match["RC_FILE"].str.replace(
                    f"{row['FILTER']}R", row["BAND"]
                )
            header_rows.append(match)
        return pd.concat(header_rows).reset_index(drop=True)

    def check_onboard_debayer(self, *, fix_metadata=False):
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
        if fix_metadata:
            self.metadata["BAYER_PIXEL"] = None
            for color, ix in zip(("R", "G", "B"), (0, 1, 2)):
                self.metadata.loc[
                    self.metadata["BAND"].str.endswith(color), "IX"
                ] = ix
        return True

    def load_rois(self, title=None, outpath=".", save=False):
        from marslab.compat.sel_to_roi import is_sel_file

        if self.rois is None:
            aprint("No ROI data loaded.")
            return
        if isinstance(self.rois, MutableMapping):
            aprint("ROIs appear to already be loaded; reinitialize to reload")
            return
        # store filename in input_rois
        input_rois = self.rois
        if title is None:
            title = self.name
        self.rois = load_roi_file(self.rois, title=title)
        if save is not True:
            return
        if not Path(outpath, "data").exists():
            os.makedirs(Path(outpath, "data"))
        if is_sel_file(input_rois):
            sel_fn = shutil.copy(input_rois, Path(outpath, "data"))
            self.local_files.append(sel_fn)
            aprint(f"wrote {input_rois} to {sel_fn}")
        roi_fits_fn = save_roi_file(self.rois, Path(outpath, "data"))
        self.local_files.append(roi_fits_fn)

    def associate_pixmaps(self, pixmaps):
        for path in self.metadata["PATH"].unique():
            self.metadata.loc[
                self.metadata["PATH"] == path, "PIXMAP_PATH"
            ] = str(pixmaps[path])

    def load_pixmaps(self, verbose=False):
        if "PIXMAP_PATH" not in self.metadata.columns:
            return
        # this doesn't need to be fancy; these files are smallish and have a
        # known structure
        for _, row in self.metadata.iterrows():
            if not row["PIXMAP_PATH"]:
                continue
            band = row["BAND"]
            # TODO: the L0/R0 pixmaps now, at least sometimes, have
            #  meaningfully separate bayer channels. verify that this is
            #  consistent.
            if band in self.pixmaps.keys():
                continue
            # don't open each clear filter three times
            band = band[0:2] if band[0:2] in ("L0", "R0") else band
            pixmap = pdr.open(row["PIXMAP_PATH"]).IMAGE
            if len(pixmap.shape) == 3:
                for band_ix, pixel in zip((0, 1, 2), ("R", "G", "B")):
                    self.pixmaps[band + pixel] = pixmap[band_ix]
            else:
                self.pixmaps[band] = pixmap

            if verbose:
                aprint("loaded " + row["PIXMAP_PATH"])

    def count_rois(self):
        if self.rois is None:
            aprint("No ROI data loaded.")
            return ""
        if isinstance(self.rois, (str, Path)):
            self.load_rois()
        self.counts = count_rois_on_xcam_images(
            self.rois,
            self.raw,
            "ZCAM",
            pixel_map_dict=self.pixmaps,
            bayer_pixel_dict={
                band: pixel
                for band, pixel in zip(
                    self.metadata["BAND"].tolist(),
                    self.metadata["BAYER_PIXEL"].tolist(),
                )
            },
        )
        return self.counts

    def count_pixmaps(self):
        if self.rois is None:
            aprint("No ROI data loaded.")
            return ""
        if self.pixmaps is None:
            aprint("No pixmap data loaded.")
            return ""
        pixmap_roi_dict = NestingDict()
        for eye in ("left", "right"):
            eye_rois = [roi for roi in self.rois if eye in roi.name.lower()]
            roi_arrays = [roi.data.astype(bool) for roi in eye_rois]
            roi_names = [roi.name.split(" ")[0].lower() for roi in eye_rois]
            eye_pixmap_dict = self.get_pixmap_dict(eye)
            pixmap_roi_dict |= count_rois_on_pixmaps(
                roi_arrays, roi_names, eye_pixmap_dict
            )
        # TODO: is this excessively complicated; should it be organized
        #  differently at the counting step?
        pixframe = pd.DataFrame(
            to_records(pixmap_roi_dict, level_names=["BAND", "COLOR"])
        )
        pixdict = {}
        colorgroups = pixframe.groupby("COLOR")
        for color, colorframe in colorgroups:
            color_rows = {}
            for _, row in colorframe.melt(["BAND", "COLOR"]).iterrows():
                color_rows[row["BAND"] + "_" + row["variable"]] = row["value"]
            pixdict[color] = color_rows
        pixdf = pd.DataFrame(pixdict).T
        pixdf["COLOR"] = pixdf.index
        self.pixmap_counts = pixdf.reset_index(drop=True)

    def format_metadata(self):
        if self.counts is None:
            self.counts = null_marslab_data_section()
        # "summary" values made from chronologically first image
        summary = self.metadata.sort_values(by=["SCLK", "BAND"]).iloc[0].copy()
        metadata_block = dupe_df_block(
            melt_metadata(self.metadata), len(self.counts.index)
        )
        extended = pd.concat([metadata_block, self.counts], axis=1)
        if isinstance(self.pixmap_counts, pd.DataFrame):
            pixmap_counts = self.pixmap_counts.copy()
            pixmap_counts.index = pixmap_counts["COLOR"]
            pixmap_counts = (
                pixmap_counts.reindex(extended["COLOR"])
                .drop("COLOR", axis=1)
                .reset_index(drop=True)
            )
            extended = pd.concat([extended, pixmap_counts], axis=1)
        compact = self.counts.copy()
        compact = drop_excess_stats(compact)
        # write canonical pointing-identifying values into all frames
        for field, value in parse_pointing(summary).items():
            summary[field] = value
            extended[field] = value
            compact[field] = value
        # set variable-by-image values equal to chronologically first value
        # in compact version
        for field, value in summary.iteritems():
            if field in asdf_settings.metadata.COMPACT_ZCAM_MARSLAB_FIELDS:
                compact[field] = value
        creation_time = dt.datetime.utcnow().isoformat()
        summary["FILE_TIMESTAMP"] = creation_time
        extended["ASDF_VERSION"] = asdf.__version__
        self.summary = summary
        self.extended = polish_metadata(extended, creation_time)
        self.compact = polish_metadata(compact, creation_time)
        if self.rc_metadata is not None:
            self._assemble_rc_compact(creation_time)

    def _assemble_rc_compact(self, creation_time):
        self.rc_compact = drop_excess_stats(self.rc_metadata)
        # convoluted vertical version of horizontal summary procedure
        # above (because this is not from the same kind of source)
        ltst_block = self.rc_metadata[
            [c for c in self.rc_metadata.columns if "LTST" in c]
        ]
        first_frame_ix = ltst_block.values.argmin(axis=1)[0]
        first_filt = ltst_block.columns[first_frame_ix].split("_")[0]
        rc_summary = self.rc_metadata[
            [c for c in self.rc_metadata.columns if c.startswith(first_filt)]
        ].iloc[0]
        rc_summary.index = [
            ix.replace(first_filt, "").strip("_") for ix in rc_summary.index
        ]
        for field, value in rc_summary.iteritems():
            if field in asdf_settings.metadata.COMPACT_ZCAM_MARSLAB_FIELDS:
                self.rc_compact[field] = value
        self.rc_compact["SOL"] = self.summary["SOL"]
        self.rc_compact["FEATURE"] = "caltarget"
        self.rc_compact["CALTARGET_ELEMENT"] = self.rc_compact.index
        self.rc_compact["COLOR"] = "black"
        self.rc_compact = polish_metadata(self.rc_compact, creation_time)
        self.rc_compact = self.rc_compact.copy()  # defrag

    def write_data_files(self, outpath=".", verbose=False, in_memory=False):
        if in_memory is False:
            datapath = Path(outpath, "data")
            stem = f"_{self.name + self.suffix}.csv"
            metadata_file = str(Path(datapath, f"marslab{stem}"))
            extended_file = str(Path(datapath, f"marslab_extended{stem}"))
            if self.rc_compact is not None:
                rc_metadata_file = str(Path(datapath, f"marslab_rc{stem}"))
            else:
                rc_metadata_file = None
            if not datapath.exists():
                os.makedirs(datapath)
        else:
            metadata_file = io.BytesIO()
            extended_file = io.BytesIO()
            rc_metadata_file = io.BytesIO()
        dashify(self.extended).to_csv(extended_file, index=False)
        if verbose and (in_memory is False):
            aprint("wrote extended-format marslab file: " + extended_file)
        dashify(self.compact).to_csv(metadata_file, index=False)
        if verbose and (in_memory is False):
            aprint("wrote compact-format marslab file: " + metadata_file)
        if self.rc_compact is not None:
            dashify(self.rc_compact).to_csv(rc_metadata_file, index=False)
            if verbose and (in_memory is False):
                aprint("wrote caltarget marslab file: " + rc_metadata_file)
        if in_memory is True:
            metadata_file.seek(0)
            extended_file.seek(0)
            rc_metadata_file.seek(0)
        else:
            self.local_files.append(extended_file)
            self.local_files.append(metadata_file)
            if self.rc_compact is not None:
                self.local_files.append(rc_metadata_file)
        return metadata_file, extended_file, rc_metadata_file

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
        if not self.metadata["BAND"].str.startswith(initial).any():
            return
        if initial + "0R" in self.metadata["BAND"].values:
            inst["bands"] = (initial + "0R", initial + "0G", initial + "0B")
        else:
            band = self.metadata.loc[
                self.metadata["BAND"].str.startswith(initial), "BAND"
            ].iloc[0]
            inst["bands"] = (band, band, band)
        self.make_look_set([inst])
        eye_edgemaps = {
            key: value for key, value in edgemaps.items() if eye in key
        }
        self.looks["context image " + eye] = draw_edgemaps_on_image(
            self.looks["context image " + eye], eye_edgemaps, width=0.1
        )

    def draw_eye_pixmaps(self, edgemaps, eye, verbose=False):
        # TODO: consider reorganizing this whole situation
        eye_pixmaps = self.get_pixmap_dict(eye)
        if len(eye_pixmaps) < 1:
            return
        eye_pixmaps["flat"] = self.flatten_pixmaps(eye_pixmaps)
        narrow = keyfilter(
            lambda k: (k[1] != "0") and (k != "flat"), eye_pixmaps
        )
        if len(narrow) > 0:
            eye_pixmaps["narrow"] = self.flatten_pixmaps(narrow)
        for name, pixmap in eye_pixmaps.items():
            self.render_pixmap_context(edgemaps, eye, pixmap, name, verbose)

    def render_pixmap_context(self, edgemaps, eye, pixmap, name, verbose):
        # regenerate matplotlib objects from bytes
        background = perfectly_black_rectangular_solid(pixmap.shape)
        context = plt.figure()
        ax = context.add_subplot()
        ax.imshow(background, interpolation=None)
        # flag off-scale, saturated, hot pixels with special markers
        extant_flags = np.unique(pixmap)
        for flag in extant_flags:
            if flag == 0:
                continue
            posmap = pixmap.copy()
            pix_y, pix_x = np.where(posmap == flag)
            style = PIXEL_FLAG_STYLE[flag - 1]
            label = PIXEL_FLAG_NAMES[flag - 1]
            ax.scatter(pix_x, pix_y, *style, label=label)
        remove_ticks(ax)
        despine(ax)
        if edgemaps is not None:
            eye_edgemaps = keyfilter(lambda key: eye in key, edgemaps)
            draw_edgemaps_on_axis(ax, eye_edgemaps, width=8, colorize=False)
        context.legend(
            prop=LEGEND_FONT,
            bbox_to_anchor=(0.12, 0.92, 0.5, 0),
            # frameon=False,
            mode="expand",
            ncol=5,
            labelcolor="white",
            markerscale=2,
            facecolor="black",
        )
        if name == "flat":
            name = eye
        elif name == "narrow":
            name = eye + "_narrow"
        self.looks[f"pixmap context image {name}"] = context
        if verbose:
            aprint(f"generated context pixmap {name}")

    @staticmethod
    def flatten_pixmaps(pixmaps):
        """
        get 'worst' flag value of pixel across all bands, masking
        wrong-element bayer pixels (both because they are frequently off-scale
        due to gain and because they will never be counted and are thus
        irrelevant)
        """
        # for each x, y position, find the 'worst' flag value of any pixel
        # we used across all bands. note that order doesn't matter.
        pixmap_cube = np.dstack(tuple(pixmaps.values()))
        return np.max(pixmap_cube, axis=2)

    def get_pixmap_dict(self, eye):
        eye_pixmaps = {}
        for band, pixmap in keyfilter(
            lambda key: key.startswith(eye[0].upper()), self.pixmaps
        ).items():
            eye_pixmaps |= self._pixmap_to_dict(band, pixmap)
        return eye_pixmaps

    def _pixmap_to_dict(self, band, pixmap):
        output_pixmaps = {}
        if band in ("L0", "R0"):
            bands = [band + color for color in ("R", "G", "B")]
        else:
            bands = [band]
        for band in bands:
            # use all pixels from bayer-transparent and onboard-debayered
            # frames; otherwise mask bayer_pixels
            do_mask = (self.check_onboard_debayer() is False) and (
                BAND_TO_BAYER["ZCAM"].get(band) is not None
            )
            if do_mask is True:
                self.make_db_masks(pixmap.shape)
                pixel = BAND_TO_BAYER["ZCAM"][band]
                output_pixmaps[band] = mask_bayer_pixels(
                    pixmap, pixel, masks=self.bayer_info["masks"]
                )
            else:
                output_pixmaps[band] = pixmap
        return output_pixmaps

    def make_context_images(self, verbose=False):
        # TODO: automatically try to count ROIs and stuff? maybe?
        # TODO: parallelize now that we're making a million of these?
        if self.rois:
            if verbose:
                aprint("... making ROI context images ...")
            edgemaps = make_roi_edgemaps(self.rois, calculate_centers=False)
            edgemaps = add_merspect_colors_to_edgemaps(edgemaps)
            for eye in ("left", "right"):
                self.draw_context(edgemaps, eye)
        else:
            edgemaps = None
        if not self.pixmaps:
            return
        if verbose:
            aprint("... making pixmap context images ...")
        # suppress irrelevant warnings from matplotlib about figure count
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            for eye in ("left", "right"):
                self.draw_eye_pixmaps(edgemaps, eye, verbose)

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
