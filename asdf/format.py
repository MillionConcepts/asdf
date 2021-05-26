"""
formatting and output helper functions for other asdf modules.
"""
import os
from pathlib import Path

import matplotlib.figure
import pandas as pd

import asdf.settings as settings
from asdf.console import ASDF_CONSOLE, aprint
from asdf.parse import parse_pointing
from marslab.imgops.imgutils import absolutely_destroy
from marslab.imgops.pltutils import set_label
from marslab.imgops.render import make_thumbnail, simple_mpl_figure


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


def annotate_and_save(annotation, look, filename, outpath):
    # TODO: decide if these annotation things should live on zcambandset --
    #  this is not urgent. I think _maybe_ they should be separate.
    if not isinstance(look, matplotlib.figure.Figure):
        look = simple_mpl_figure(look)
    set_label(look, annotation, fontproperties=settings.rapidlooks.TITLE_FONT)
    look.savefig(
        Path(outpath, filename), dpi=275, bbox_inches="tight", pad_inches=0
    )
    absolutely_destroy(look)
    return 0


def handle_abbreviation(
    sol,
    seq_id,
    root=None,
    filetype=None,
):
    sol_path = format(int(sol), "0>4") if sol else ""
    # default path root and subdirectory, which can be overridden
    if root:
        try:
            path_root = settings.sources.PATH_ABBREVIATIONS[root]
        except KeyError:
            source_names = ", ".join(
                settings.sources.PATH_ABBREVIATIONS.keys()
            )
            ASDF_CONSOLE.log(
                "sorry, I don't know the abbreviation {}. I know: {}.".format(
                    root, source_names
                ),
                style="bold red",
            )
            return None, None, None
    else:
        path_root = list(settings.sources.PATH_ABBREVIATIONS.values())[0]
    if filetype:
        product_subdirectory = filetype
    else:
        product_subdirectory = settings.sources.DEFAULT_PRODUCT_SUBDIRECTORY
    directory = Path(path_root, sol_path, product_subdirectory)
    if seq_id:
        seq_id = "ZCAM" + str(seq_id)
    return directory, sol, seq_id


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
        "INSTRUMENT",
        "LAT",
        "LON",
        "ODOMETRY",
        "ROVER_ELEVATION",
        "CREATOR",
        "ANALYSIS_NAME",
        "NAME"
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
