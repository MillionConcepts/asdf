"""
formatting and helper functions for other asdf modules.
"""
import os
import re
from functools import partial
from hashlib import md5
from pathlib import Path

import matplotlib.figure
import numpy as np
import pandas as pd

import asdf_settings as settings
from dustgoggles.structures import NestingDict
from asdf.console import ASDF_CONSOLE, aprint
from asdf.parse import parse_pointing
from asdf_settings.metadata import PIXEL_FLAG_NAMES, COMPACT_MARSLAB_STATS
from marslab.compat.xcam import DERIVED_CAM_DICT
from marslab.imgops.imgutils import absolutely_destroy
from marslab.imgops.regions import count_rois_on_image, roi_stats
from marslab.imgops.render import make_thumbnail, simple_figure


def compile_looks():
    """
    compile looks at runtime -- makes settings.rapidlooks readable while
    avoiding circular imports.
    """
    rapidlooks = settings.generators.look_assembler.RAPIDLOOKS
    # interleave 'hard' rapidlooks for efficiency
    return (
        rapidlooks[slice(None, None, 3)]
        + rapidlooks[slice(1, None, 3)]
        + rapidlooks[slice(2, None, 3)]
    )


# TODO: generate browse and data paths explicitly
def make_asdf_outpath(output, bandset):
    """
    where are we locally writing files? by default, directories separated
    by user and sol.
    """
    if output is None:
        outpath = Path(
            "output/",
            os.getlogin(),
            format(bandset.metadata["SOL"].iloc[0], "0>4"),
        )
    else:
        outpath = Path(output)
    os.makedirs(outpath, exist_ok=True)
    return outpath


def make_pointing_annotation(pointing):
    return ", ".join(
        key.lower() + " " + str(value)
        for key, value in parse_pointing(pointing).items()
    )


def save_plainly(look, filename, outpath):
    if isinstance(look, matplotlib.figure.Figure):
        for ix, axis in enumerate(look.axes):
            if ix > 0:
                axis.remove()
            else:
                axis.axis("off")
        look.savefig(
            Path(outpath, filename), dpi=275, bbox_inches="tight", pad_inches=0
        )
    else:
        look.save(Path(outpath, filename))


def annotate_and_save(title, annotation, look, filename, outpath):
    # TODO: decide if these annotation things should live on zcambandset --
    #  this is not urgent. I think _maybe_ they should be separate.
    if not isinstance(look, matplotlib.figure.Figure):
        look = simple_figure(look)
    ax = look.axes[0]
    render_figure_labels(ax, title, annotation)
    look.savefig(
        Path(outpath, filename), dpi=275, bbox_inches="tight", pad_inches=0
    )
    absolutely_destroy(look)
    return 0


def render_figure_labels(ax, title, annotation):
    render = partial(
        ax.text,
        x=0.5,
        horizontalalignment="center",
        verticalalignment="center",
        transform=ax.transAxes,
    )
    render(
        y=settings.rapidlooks.TITLE_POSITION,
        s=title,
        fontproperties=settings.rapidlooks.TITLE_FONT,
    )
    render(
        y=settings.rapidlooks.ANNOTATION_POSITION,
        s=annotation,
        fontproperties=settings.rapidlooks.ANNOTATION_FONT,
    )

def clean_sequence_id(seq_id):
    # Make sure that the sequence ID is in the proper format
    if not seq_id:
        return None
    if "ZCAM" in str(seq_id).upper():
        return seq_id.upper()
    seq_id = "ZCAM" + format(int(seq_id), "0>5")
    return seq_id

def parse_abbreviated_inputs(
    sol,
    seq_id,
    root_path_abbreviation=None,
    product_subdirectory=None,
):
    """Commonly used directory paths have standard abbreviations which are
    defined in asdf_settings.sources. Defining them in settings rather than
    this function facilitates environment-specific deployments (local, ASU,
    etc.)  This function expands these abbreviations and concatenates sol and
    optionally subdirectory into an appropriately formatted working directory
    pathlib.Path object. Defaults to the first entry in
    asdf_settings.sources.PATH_ABBREVIATIONS and IOF subdirectory.
    Also returns a correctly formatted seq_id (by prepending 'ZCAM').
    """
    sol_path = format(int(sol), "0>4") if sol else ""
    # default path root and subdirectory, which can be overridden
    if root_path_abbreviation:
        try:
            path_root = settings.sources.PATH_ABBREVIATIONS[root_path_abbreviation]
        except KeyError:
            source_names = ", ".join(
                settings.sources.PATH_ABBREVIATIONS.keys()
            )
            ASDF_CONSOLE.log(
                "sorry, I don't know the abbreviation {}. I know: {}.".format(
                    root_path_abbreviation, source_names
                ),
                style="bold red",
            )
            return None, None
    else:
        path_root = list(settings.sources.PATH_ABBREVIATIONS.values())[0]
    if not product_subdirectory:
        product_subdirectory = settings.sources.DEFAULT_PRODUCT_SUBDIRECTORY
    directory = Path(path_root, sol_path, product_subdirectory)

    return directory, clean_sequence_id(seq_id)


def make_rapidlook_thumbnails(rapidlooks, size):
    aprint("... making thumbnails (if necessary) ...")
    thumbnails = {}
    for name, image in rapidlooks.items():
        thumbnails[name] = make_thumbnail(image, size)
    return thumbnails


def preprocess_scan_path(root_directory, explicit_path):
    if not (root_directory or explicit_path):
        raise ValueError(
            "sorry, I need an explicit or abbreviated path to find files."
        )
    if explicit_path and not os.path.exists(explicit_path):
        raise ValueError("sorry, " + str(explicit_path) + " does not exist.")
    if explicit_path:
        if Path(explicit_path).is_dir():
            root_directory = Path(explicit_path)
            target_file = None
        else:
            root_directory = Path(explicit_path).parent
            target_file = str(explicit_path)
    else:
        root_directory = Path(root_directory)
        target_file = None
    if not root_directory.exists():
        raise ValueError("sorry, " + str(root_directory) + " does not exist.")
    return root_directory, target_file


def melt_metadata(metadata: pd.DataFrame, unpivot="BAND") -> pd.DataFrame:
    """
    unpivot a metadata frame by key (default BAND), for appending per-file
    metadata to the extended marslab format
    """
    unchanging_columns = (
        "SOL",
        "SEQ_ID",
        "SITE",
        "DRIVE",
        "ZOOM",
        "INSTRUMENT",
        "LAT",
        "LON",
        "ODOMETRY",
        "ROVER_ELEVATION",
        "CREATOR",
        "ANALYSIS_NAME",
        "NAME",
        "LOCATION",
        "IX",
        "PRODUCER",
        "PRODUCT_TYPE",
    )
    uc_here = [col for col in unchanging_columns if col in metadata.columns]
    unchanging_block = metadata.reindex(columns=uc_here)
    melted = metadata.drop(columns=uc_here)
    melted = melted.melt(unpivot).T
    melted.columns = melted.loc[unpivot] + "_" + melted.loc["variable"]
    melted = (
        melted.drop([unpivot, "variable"])
        .reset_index(drop=True)
        .sort_index(axis=1)
    )
    return pd.DataFrame(
        pd.concat([unchanging_block.loc[0], melted.loc[0]], axis=0)
    ).T


METADATA_DTYPES = {
    "SOL": "int16",
    "WAVELENGTH": "float16",
    "IX": "uint8",
    "SOLAR_ELEVATION": "float32",
    "INSTRUMENT_ELEVATION": "float32",
    "L_S": "float32",
    "INSTRUMENT_AZIMUTH": "float32",
    "SOLAR_AZIMUTH": "float32",
    "SCLK": "float64",
}


def md5sum(path_or_file, hash_function=md5):
    hasher = hash_function()
    if isinstance(path_or_file, (str, Path)):
        with open(path_or_file, "rb") as file_to_be_hashed:
            hashbuffer = file_to_be_hashed.read()
            hasher.update(hashbuffer)
    else:
        hasher.update(path_or_file)
        path_or_file.seek(0)

    return hasher.hexdigest()


def add_image_hashes(bandset):
    paths = bandset.metadata["PATH"].unique()
    md5s = tuple(map(md5sum, paths))
    for path, md5_string in zip(paths, md5s):
        bandset.metadata.loc[
            bandset.metadata["PATH"] == path, "SOURCE_MD5SUM"
        ] = md5_string


def count_rois_on_pixmaps(roi_arrays, roi_names, pixmap_dict):
    all_counts = NestingDict()
    for filt, bayer_masked_flag_array in pixmap_dict.items():
        all_counts[filt] = count_rois_on_pixmap(
            bayer_masked_flag_array, roi_arrays, roi_names
        )
    return all_counts


def perfectly_black_rectangular_solid(xy_shape):
    return np.zeros((*xy_shape, 3))


def count_rois_on_pixmap(bayer_masked_flag_array, roi_arrays, roi_names):
    all_counts = NestingDict()
    flag_counts = {}
    for flag_value, flag_name in zip([1, 2, 3, 4, 5], PIXEL_FLAG_NAMES):
        # don't bother counting absent flags
        if flag_value not in bayer_masked_flag_array:
            flag_counts[flag_name] = {
                name: roi_stats(np.array([0])) for name in roi_names
            }
            continue
        flagmap = np.zeros_like(bayer_masked_flag_array)
        flagmap[bayer_masked_flag_array == flag_value] = 1
        flag_counts[flag_name] = count_rois_on_image(
            roi_arrays, roi_names, flagmap
        )
    for flag_name, count_dict in flag_counts.items():
        for roi_name, counts in count_dict.items():
            all_counts[roi_name][flag_name] = counts["total"]
    return all_counts


def drop_excess_stats(compact):
    # TODO: garbage placeholder
    filts = list(DERIVED_CAM_DICT["ZCAM"]["filters"])
    for column in compact.columns:
        if column.startswith("LEFT") or column.startswith("RIGHT"):
            compact = compact.drop(column, axis=1)
        if "_" not in column:
            continue
        if (
            column.split("_")[0] in filts
            and column.split("_")[1] not in COMPACT_MARSLAB_STATS
        ):
            compact = compact.drop(column, axis=1)
    return compact


def rearrange_band_depth_for_filename(text):
    filts = re.split(r"([L|R]\d[RGB]?)", text, maxsplit=0)
    return f"{filts[0]}{filts[3]} shoulders {filts[1]} {filts[5]}{filts[6]}"


def rearrange_band_depth_for_title(text):
    filts = re.split(r"([L|R]\d[RGB]?)", text, maxsplit=0)
    return f"{filts[0]}{filts[3]}, " f"shoulders at {filts[1]} and {filts[5]}"


def insert_wavelengths_into_text(text: str):
    if "depth" in text:
        text = rearrange_band_depth_for_title(text)
    for filt, wavelength in DERIVED_CAM_DICT["ZCAM"]["filters"].items():
        text = re.sub(filt, filt + " (" + str(wavelength) + "nm)", text)
    text = re.sub(r"_", r" ", text)
    return text


def remove_stretch_names(look_name):
    bands_present = re.search(r"([L|R]\d[RGB]?_?)+", look_name)
    if bands_present:
        look_name = look_name[: bands_present.span()[1]]
    return look_name


def construct_filename(look_name, basename):
    if "band_depth" in look_name:
        look_name = rearrange_band_depth_for_filename(look_name)
    filename = f"{look_name.replace(' ', '_')}_{basename}.png"
    return filename


def construct_title_and_annotation(bandset, look_name):
    # aggressively remove names of stretches &c
    title = remove_stretch_names(look_name)
    title = insert_wavelengths_into_text(title)
    annotation = "\n".join(
        (
            make_pointing_annotation(bandset.metadata),
            settings.rapidlooks.CREDIT_TEXT,
        )
    )
    return annotation, title
