"""
Subclass of marslab.bandset.BandSet, along with helper functions, that
implements ZCAM and asdf-specific behaviors.
"""
from collections.abc import MutableMapping
import datetime as dt
from functools import partial
import os
from io import BytesIO
from pathlib import Path
import shutil
from typing import Sequence, Optional, Union
import warnings

from dustgoggles.func import zero
import numpy as np
import pandas as pd
import pdr

from asdf_settings import rapidlooks
from cytoolz import keyfilter, groupby
from matplotlib import pyplot as plt

import asdf
from asdf.asdf_utils import (
    load_roi_file,
    null_marslab_data_section,
    dashwrite,
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
from asdf.parse import parse_pointing, make_pointing_name, parse_zcam_fn
from asdf.physics import add_derived_illumination_geometry
from asdf.labels import bulk_scrape_asdf_metadata
from asdf.rc_parser import find_rc_file, read_rc_file
import asdf_settings.meta as meta
from asdf_settings.rapidlooks import LEGEND_FONT
from marslab.compat.mertools import add_merspect_colors_to_edgemaps
from marslab.compat.xcam import (
    DERIVED_CAM_DICT,
    BAND_TO_BAYER,
    count_rois_on_xcam_images,
    construct_field_ordering,
)
from marslab.bandset import BandSet
from marslab.geom import get_coordinates
from marslab.imgops.debayer import RGGB_PATTERN, mask_bayer_pixels
from marslab.imgops.imgutils import normalize_range, cropmask
from marslab.imgops.loaders import pdr_load
from marslab.imgops.pltutils import remove_ticks, despine
from marslab.imgops.regions import (
    make_roi_edgemaps,
    draw_edgemaps_on_image,
    draw_edgemaps_on_axis,
)
from marslab.parse import site, drive
from asdf.xyr import make_space_fits, make_spatial_products


def sitedrive(path: Path) -> tuple[str, str]:
    """Parse site and drive numbers from a file path"""
    return site(path.name), drive(path.name)


def polish_metadata(
    metadata: pd.DataFrame, creation_time: str
) -> pd.DataFrame:
    """
    Last-pass fixup function for turning the compact, extended, or summary
    dataframes of a ZcamBandSet into a nice clean writable format. Inserts
    a file format, applies any defined column ordering, and drops any
    duplicate columns.
    """
    # TODO: should this not be modifying metadata inplace?
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


def setup_zcam_bandset_metadata(metadata: pd.DataFrame) -> pd.DataFrame:
    """
    Applies interpretive rules to postprocess a dataframe of metadata skimmed
    from ZCAM IOF attached headers and/or filenames into a metadata dataframe
    appropriate for ZcamBandSet.
    """
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
    """
    Subclass of marslab.bandset.BandSet, along with helper functions, that
    implements ZCAM and asdf-specific behaviors. Intended to be built around
    a group of IOFs (an 'observation'), but can also pull in information
    from their associated pixel quality maps and radiometric calibration files.
    """
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
        self.metadata = self.metadata.sort_values(
            by=['SCLK', 'BAND']
        ).reset_index(drop=True)
        self.name = make_pointing_name(self.metadata)
        # TODO: this is horrible, refactor this garbage attribute
        if self.rois is None and suffix == "":
            suffix = "empty"
        self.suffix = "-" + suffix if suffix != "" else suffix
        self.metadata["ANALYSIS_NAME"] = suffix
        self.check_onboard_debayer(fix_metadata=True)
        self.pixmaps = {}
        self.pixmap_counts = {}
        self.ioferrs = {}
        self.ioferr_counts = {}
        self.local_files = []
        # additional tables to hold metadata / marslab-like files scraped
        # from rc files
        self.rc_metadata = None
        self.rc_compact = None
        # a slightly goofy holding location for things like google drive ids
        self.remote_resource_id = None
        self.xyrs = None

    def scrape_rc_files(self):
        """
        Scrapes metadata from RC files associated with the bandset's IOFs in
        order to further populate metadata that will eventually be written
        into compact and extended-format marslab files, and also to generate
        secondary metadata objects that will eventually be written into
        rc-format marslab files..
        """
        rc_table_map = {}
        rc_metadata = {}
        for ix, row in self.metadata.iterrows():
            caltarget_sol = parse_zcam_fn(row['CALTARGET_FILE'])['SOL']
            rc_file = find_rc_file(row["RC_FILE"], row["PATH"], caltarget_sol)
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
    def _make_caltarget_table(
        rc_metadata: pd.DataFrame, rc_table_map: dict[str, pd.DataFrame]
    ) -> pd.DataFrame:
        """
        A single RC file contains information on intensity at a particular band
        for many different caltarget elements -- in other words, a single
        column of a marslab file's filter section. This assembles those data
        from a group of RC files into a marslab-style table.
        """
        rc_marslab_chunks = []
        for band, table in rc_table_map.items():
            band_metadata = rc_metadata[band]
            for col, value in band_metadata.items():
                table[col] = value
            table.columns = [
                # matching 'reflectance field is the band name' convention
                f"{band}_{col}".strip("_")
                for col in table.columns
            ]
            rc_marslab_chunks.append(table)
        # copy defrag
        rc_marslab = pd.concat(rc_marslab_chunks, axis=1).copy()
        rc_marslab["INSTRUMENT"] = "ZCAM"
        return rc_marslab.copy()  # copy defrag

    def _get_headers_from_precached_metadata(self):
        headers = pd.DataFrame(bulk_scrape_asdf_metadata(self.precached))
        geometry = []
        for data in self.precached.values():
            instrument = get_coordinates(data)["SITE"]["INSTRUMENT"]
            solar = get_coordinates(data)["SITE"]["SOLAR"]
            geometry.append(
                {
                    "INSTRUMENT_ELEVATION": instrument["ELEVATION"],
                    "INSTRUMENT_AZIMUTH": instrument["AZIMUTH"],
                    "SOLAR_ELEVATION": solar["ELEVATION"],
                    "SOLAR_AZIMUTH": solar["AZIMUTH"],
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

    def load_rois(
        self,
        title: Optional[str] = None,
        outpath: Union[str, Path] = ".",
        save: bool = False
    ):
        """
        Loads ROIs from a marslab ROI FITS file or a .sel file, formatting them
        in memory as ndarrays and saving a ROI FITS file into the output
        directory. If the source is a .sel file, also copies it into the output
        directory.
        """
        from astropy.io.fits import HDUList
        from marslab.compat.sel_to_roi import is_sel_file

        if self.rois is None:
            aprint("No ROI data loaded.")
            return
        if isinstance(self.rois, (MutableMapping, HDUList)):
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

    def associate_metamaps(
        self, metamaps: dict[str, str], code: str = 'pix_map'
    ):
        """
        Inserts path information for 'metamaps' (like pixmaps or error maps)
        into the bandset's metadata.
        """
        pcol = f"{code.replace('_', '').upper()}_PATH"
        if pcol not in self.metadata.columns:
            self.metadata[pcol] = pd.Series(dtype=object)
        for path in self.metadata["PATH"].unique():
            self.metadata.loc[
                self.metadata["PATH"] == path, pcol
            ] = str(metamaps[path])

    def load_metamaps(self, verbose: bool = False, code: str = "pix_map"):
        """
        Loads arrays from 'metamaps' (like pixmaps or error maps) into memory,
        formatting them as appropriate.
        """
        codestr = code.replace('_','')
        if f"{codestr.upper()}_PATH" not in self.metadata.columns:
            return
        # this doesn't need to be fancy; these files are smallish and have a
        # known structure
        for _, row in self.metadata.iterrows():
            if not row[f"{codestr.upper()}_PATH"]:
                continue
            band = row["BAND"]
            # TODO: the L0/R0 pixmaps now, at least sometimes, have
            #  meaningfully separate bayer channels. verify that this is
            #  consistent.
            if band in getattr(self,f"{codestr}s").keys():
                continue
            # don't open each clear filter three times
            band = band[0:2] if band[0:2] in ("L0", "R0") else band
            data = pdr.open(row[f"{codestr.upper()}_PATH"])
            # the IOE maps need to be converted to floating point
            if code == "iof_err":
                metamap = data.get_scaled(
                    'IMAGE',inplace=True,float_dtype=np.dtype('float32')
                )
            else:
                metamap = data.IMAGE
            if len(metamap.shape) == 3:
                for band_ix, pixel in zip((0, 1, 2), ("R", "G", "B")):
                    getattr(self,f"{codestr}s")[band + pixel] = metamap[band_ix]
            else:
                getattr(self, f"{codestr}s")[band] = metamap

            if verbose:
                aprint("loaded " + row[f"{codestr.upper()}_PATH"])

    def count_rois(self) -> Union[pd.DataFrame, str]:
        """
        Count loaded ROIs on loaded images, producing a dataframe usable as the
        filter section of a marslab file. Currently returns an empty string if
        there are no ROIs loaded.
        """
        if self.rois is None:
            # TODO: this should probably be an exception
            aprint("No ROI data loaded.")
            return ""
        if isinstance(self.rois, (str, Path)):
            self.load_rois()
        self.counts = count_rois_on_xcam_images(
            self.rois,  # list of roi hdus
            self.raw,  # dict of image masked_arrays
            "ZCAM",
            pixel_map_dict=self.pixmaps,  # dict of pixel flag arrays
            error_map_dict=self.ioferrs,  # dict of error map arrays
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
        """
        Counts loaded ROIs on pixmaps, generating a dataframe whose columns
        represent unique pixmap values per eye and whose rows represent ROIs.
        This dataframe is used to mask bad pixels during primary ROI counting,
        and is also written into the bandset's metadata files.

        Works only if ROIs and pixmaps are both loaded.
        """
        # TODO: should this actually raise an exception rather than returning
        #  an empty string?
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

    # TODO: this whole workflow needs clearer documentation.
    def format_metadata(self):
        """
        Performs lots of data manipulation to make summary, compact, and
        extended metadata frames. Summary frames are used to populate the
        google sheet; compact and extended frames become the respective marslab
        files.
        """
        if self.counts is None:
            self.counts = null_marslab_data_section()
        # "summary" values made from chronologically first image
        summary = self.metadata.sort_values(by=["SCLK", "BAND"]).iloc[0].copy()
        metadata_block = dupe_df_block(
            melt_metadata(self.metadata), len(self.counts.index)
        )
        extended = pd.concat([metadata_block, self.counts], axis=1).copy()
        if isinstance(self.pixmap_counts, pd.DataFrame):
            pixmap_counts = self.pixmap_counts.copy()
            pixmap_counts.index = pixmap_counts["COLOR"]
            pixmap_counts = (
                pixmap_counts.reindex(extended["COLOR"])
                .drop("COLOR", axis=1)
                .reset_index(drop=True)
            )
            extended = pd.concat([extended, pixmap_counts], axis=1).copy()
        compact = self.counts.copy()
        compact = drop_excess_stats(compact)
        # write canonical pointing-identifying values into all frames
        for field, value in parse_pointing(summary).items():
            summary[field] = value
            extended[field] = value
            compact[field] = value
        # set variable-by-image values equal to chronologically first value
        # in compact version
        for field, value in summary.items():
            if field in meta.COMPACT_ZCAM_MARSLAB_FIELDS:
                compact[field] = value
        creation_time = dt.datetime.utcnow().isoformat()
        summary["FILE_TIMESTAMP"] = creation_time
        extended["ASDF_VERSION"] = asdf.__version__
        self.summary = summary
        self.extended = polish_metadata(extended, creation_time)
        self.compact = polish_metadata(compact, creation_time)
        if self.rc_metadata is not None:
            self._assemble_rc_compact(creation_time)

    def _assemble_rc_compact(self, creation_time: str):
        """
        Formatting function that generates the 'compact' version of the rc
        metadata. This directly becomes the rc_marslab file.
        """
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
        for field, value in rc_summary.items():
            if field in meta.COMPACT_ZCAM_MARSLAB_FIELDS:
                self.rc_compact[field] = value
        self.rc_compact["SOL"] = self.summary["SOL"]
        self.rc_compact["FEATURE"] = "caltarget"
        self.rc_compact["CALTARGET_ELEMENT"] = self.rc_compact.index
        self.rc_compact["COLOR"] = "black"
        self.rc_compact = polish_metadata(self.rc_compact, creation_time)
        self.rc_compact = self.rc_compact.copy()  # defrag

    def _marslab_to_memory(self) -> list[BytesIO]:
        """
        Writes compact, extended, and (if available) rc marslab files as
        binary blobs into BytesIO objects. This is used to facilitate uploads
        to s3.
        """
        buffers = []
        for attr, suf in zip(("compact", "extended"), ("", "_extended")):
            buffers.append(dashwrite(getattr(self, attr)))
        if self.rc_compact is not None:
            buffers.append(dashwrite(self.rc_compact))
        else:
            buffers.append(None)
        return buffers

    def _marslab_to_disk(
        self, outpath: Union[str, Path], verbose: bool
    ) -> tuple[str, str, Optional[str]]:
        """
        Writes all generated metadata dataframes as marslab files to disk,
        in the order: compact, extended, rc. Returns a tuple of stringified
        paths for the written compact, extended, and rc marslab files; if
        no rc information was loaded, the last element will be None.
        """
        datapath = Path(outpath, "data")
        if not datapath.exists():
            os.makedirs(datapath)
        files, stem = [], f"_{self.name + self.suffix}.csv"
        pr = aprint if verbose is True else zero
        for attr, suf in zip(("compact", "extended"), ("", "_extended")):
            files.append(str(datapath / f"marslab{suf}{stem}"))
            dashwrite(getattr(self, attr), files[-1])
            self.local_files.append(files[-1])
            pr(f"wrote {attr}-format marslab file: {files[-1]}")
        if self.rc_compact is not None:
            files.append(str(datapath / f"marslab_rc{stem}"))
            self.local_files.append(files[-1])
            dashwrite(self.rc_compact, files[-1])
            pr(f"wrote caltarget marslab file: {files[-1]}")
        else:
            files.append(None)
        # noinspection PyTypeChecker
        return tuple(files)

    def write_marslab_files(self, outpath=".", verbose=False, in_memory=False):
        if in_memory is False:
            return self._marslab_to_disk(outpath, verbose)
        return self._marslab_to_memory()

    # TODO: so very very sloppy
    @staticmethod
    def chain_cropmask(func):
        """
        Applies a crop to a series of images. This is currently used only by
        ZcamBandSet.draw_context(), which defines a rapidlook inline.
        """
        def mask_in_chain(image, *args, **kwargs):
            cropped = cropmask(image, rapidlooks.CROP_SETTINGS['crop'])
            return func(cropped, *args, **kwargs)
        return mask_in_chain

    def draw_context(self, edgemaps: dict[str, np.ndarray], eye: str):
        """Renders context images."""
        inst = {
            "name": "context image " + eye,
            "no_band_names": True,
            "look": "composite",
            "prefilter": {
                "function": self.chain_cropmask(normalize_range),
                "params": {"stretch": (1.25, 1)},
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

    def draw_eye_pixmaps(
        self,
        edgemaps: dict[str, np.ndarray],
        eye: str,
        verbose: bool = False
    ):
        """Renders per-eye pixmaps."""
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

    def render_pixmap_context(
        self,
        edgemaps: dict[str, np.ndarray],
        eye: str,
        pixmap: np.ndarray,
        name: str,
        verbose: bool
    ):
        """
        Renders a specific pixmap context image as a matplotlib figure and
        places it in this bandset's looks attribute. Draws ROI polygons on the
        figure if available.
        """
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
            style = meta.PIXEL_FLAG_STYLE[flag - 1]
            label = meta.PIXEL_FLAG_NAMES[flag - 1]
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
    def flatten_pixmaps(pixmaps: dict[str, np.ndarray]) -> np.ndarray:
        """
        Preprocessing function for 'narrowband' concatenated per-eye pixmaps.
        Get 'worst' flag value of pixel across all bands, masking
        wrong-element bayer pixels (both because they are frequently off-scale
        due to gain and because they will never be counted and are thus
        irrelevant).
        """
        # for each x, y position, find the 'worst' flag value of any pixel
        # we used across all bands. note that order doesn't matter.
        pixmap_cube = np.dstack(tuple(pixmaps.values()))
        return np.max(pixmap_cube, axis=2)

    def get_pixmap_dict(self, eye: str) -> dict[str, np.ndarray]:
        """Gets all pixmaps associated with a particular eye."""
        eye_pixmaps = {}
        for band, pixmap in keyfilter(
            lambda key: key.startswith(eye[0].upper()), self.pixmaps
        ).items():
            eye_pixmaps |= self._pixmap_to_dict(band, pixmap)
        return eye_pixmaps

    def _pixmap_to_dict(
        self, band: str, pixmap: np.ndarray
    ) -> dict[str, np.ndarray]:
        """
        Generates a dict of pixmaps for a particular band, masking for bayer
        elements as necessary. For narrowband filters, this dict will only
        have one item; for bayers, it will have 3.
        """
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

    def make_context_images(self, verbose: bool = False):
        """
        Generate context browse images: RGB images and pixmaps with overlaid
        ROI boundaries. Will not attempt to generate pixmap context images if
        there aren't any pixmaps, or to draw ROI boundaries if there are no
        ROIs.
        """
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

    def match_navcam(self, roots: Optional[Sequence[Path]] = None):
        """
        Caches paths to candidate navcam XYR images (i.e., ones that match the
        observation's SITE and DRIVE) in this bandset's xyrs attribute.
        """
        roots = [] if roots is None else roots
        roots.append(Path(self.metadata['PATH'][0]).parents[2])
        nsite = {}
        for root in roots:
            nsite |= groupby(sitedrive, root.rglob('nxyr/**/*.IMG'))
        try:
            self.xyrs = nsite[
                (self.metadata['SITE'][0], self.metadata['DRIVE'][0])
            ]
        except KeyError:
            return

    def fetch_precached(self, band: str) -> pdr.Metadata:
        """
        Utility function that fetches the precached pdr.Metadata object
        associated with a particular band.
        """
        return self.precached[
            self.metadata.loc[self.metadata['BAND'] == band, 'PATH'].iloc[0]
        ]

    def _spatial_ref_bands(self):
        preference_order = (1, 2, 3, 4, 5, 6, "0R", "0G", "0B")
        ref_bands = []
        for eye in ("L", "R"):
            try:
                for band in iter(preference_order):
                    if self.metadata["FILTER"].str.contains(
                        f"{eye}{band}"
                    ).any():
                        ref_bands.append(f"{eye}{band}")
                        break
            except StopIteration:
                pass
        return ref_bands

    def make_space_fits(self, outpath=".", roots=None):
        """
        Makes a spatial FITS file for this observation if appropriate navcam
        XYR files are available.
        """
        if self.xyrs is None:
            self.match_navcam(roots)
        if self.xyrs is None:
            raise FileNotFoundError("No matching XYRs found.")
        outputs, successful = make_space_fits(
            self, self._spatial_ref_bands(), outpath
        )
        self.local_files += outputs
        return successful

    def make_spatial_products(
        self,
        outpath=".",
        write_images=True,
        calc_rois=True
    ):
        """
        Makes spatial rapidlooks and calculates per-ROI spatial metadata. Must
        be preceded by a successful execution of ZcamBandSet.make_space_fits().
        """
        if (self.counts is None) and self.rois and calc_rois:
            self.load("all")
            self.bulk_debayer("all")
            self.count_rois()
        self.format_metadata()
        dims = make_spatial_products(
            self, outpath, self._spatial_ref_bands(), write_images, calc_rois
        )
        # TODO: check this typecheck behavior
        if isinstance(dims, pd.DataFrame):
            self.compact = pd.merge(self.compact, dims, on='COLOR')
        return dims

    def has_space_fits(self, outpath: Path):
        missed = 0
        for eye in ('L', 'R'):
            if not (self.metadata['BAND'].str.startswith(eye)).any():
                missed += 1
                continue
            if not (outpath / f"data/space_{eye}_{self.name}.fits").exists():
                return False
        if missed == 2:
            raise FileNotFoundError("This bandset has no valid metadata.")
        return True
