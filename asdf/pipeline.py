"""
inline handling functions for runtime asdf workflow
"""
import datetime as dt
import os
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
from astropy.io import fits
from clize import UserError
from cytoolz import keyfilter, valfilter
from marslab.compat.mertools import (
    add_merspect_colors_to_edgemaps,
    is_sel_file,
    sel_to_roi,
)
from marslab.compat.xcam import (
    NARROWBAND_TO_BAYER,
)
from marslab.imgops import (
    draw_edgemaps_on_image,
    make_thumbnail,
    rgb_from_bayer,
    RGGB_PATTERN,
    normalize_range,
    make_roi_edgemaps,
    depth_stack,
)

import asdf
import asdf.settings as settings
import pplot
from asdf.asdf_utils import absolutely_destroy, dupe_df_block
from asdf.chatter import ask_user_about_roi, get_and_offer_pointing
from asdf.scrape import (
    make_pointing_name,
    parse_pointing,
    check_and_drop_duplicate_columns,
    melt_metadata,
    add_effective_taus,
    add_public_waypoints_to_metadata,
)
from pplot.convert import convert_for_plot


def collect_dispersed_metadata(metadata):
    """
    handler function for asdf.cli that runs around to several distinct
    sources asking them for additional info prior to ROI evaluation
    """
    if settings.sources.USE_PUBLIC_WAYPOINTS:
        print(
            "... scraping localization information from public "
            "waypoints file ..."
        )
        metadata = add_public_waypoints_to_metadata(metadata)
    if settings.sources.FIND_EFFECTIVE_TAUS:
        metadata = add_effective_taus(metadata)
    return metadata


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


def annotate_and_save_rapidlook(
    target_name, look_name, pointing, figure, pointing_name, output_path
):
    title = "\n".join(
        (
            target_name + look_name,
            make_pointing_annotation(pointing),
            settings.rapidlooks.CREDIT_TEXT,
        )
    )
    figure.axes[0].set_xlabel(
        title, loc="center", fontproperties=settings.rapidlooks.TITLE_FONT
    )
    filename = pointing_name + " " + look_name + ".png"
    print("writing " + filename)
    figure.savefig(Path(output_path, filename), dpi=275)
    absolutely_destroy(figure)
    return 0








def handle_pretty_plot(
    marslab_file_name, fixed_target, outpath, pointing_name, suffix=""
):
    print("pretty-plotting data")
    marslab_file = pd.read_csv(marslab_file_name).replace("-", np.nan)
    if fixed_target is not None:
        titular_plot_target = fixed_target
    else:
        targets = marslab_file["NAME"].dropna().unique()
        if len(targets) > 0:
            titular_plot_target = targets[0]
        else:
            titular_plot_target = "unknown target"
    if suffix != "":
        pointing_name = pointing_name + "-" + suffix
    print("Writing " + str(Path(outpath, pointing_name + "-pretty-plot.png")))
    marslab_spectra = convert_for_plot(str(marslab_file_name)).replace(
        "-", np.nan
    )
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        pplot.pplot_utils.pretty_plot(
            marslab_spectra,
            target_name=titular_plot_target,
            sol=marslab_file["SOL"].iloc[0],
            solar_elevation=marslab_file["SOLAR_ELEVATION"].iloc[0],
            seq_id=marslab_file["SEQ_ID"].iloc[0],
            plot_fn=Path(outpath, pointing_name + "-pretty-plot.png"),
            underplot=None,
        )


def handle_abbreviation(
    sol, seq_id, root=None, filetype=None, noninteractive=False, binocular=True
):
    # TODO: clean this up and document it
    sol_path = format(int(sol), "0>4")
    # default path root and subdirectory, which can be overridden
    if root:
        try:
            path_root = settings.sources.PATH_ABBREVIATIONS[root]
        except KeyError:
            raise UserError(
                "sorry, I don't know the abbreviation \""
                + root
                + '".  I know '
                + " ".join(
                    [
                        '"' + key + '",'
                        for key in settings.sources.PATH_ABBREVIATIONS.keys()
                    ]
                )
            )
    else:
        path_root = list(settings.sources.PATH_ABBREVIATIONS.values())[0]
    if filetype:
        product_subdirectory = filetype
    else:
        product_subdirectory = settings.sources.DEFAULT_PRODUCT_SUBDIRECTORY
    iof_search_path = Path(path_root, sol_path, product_subdirectory)
    candidates = [
        path for path in iof_search_path.iterdir() if seq_id in path.name
    ]
    if len(candidates) == 0:
        raise UserError(
            "Sorry, couldn't find a file with seq_id "
            + seq_id
            + " in "
            + str(iof_search_path)
        )
    version_slice = slice(-6, -4)
    versions = {path: int(path.name[version_slice]) for path in candidates}
    latest_version = max(versions.values())
    good_input = False
    iof_path = None
    pointing = None
    latest_candidates = iter(
        valfilter(lambda key: int(key) == latest_version, versions)
    )
    while good_input is not True:
        try:
            iof_path = Path(next(latest_candidates))
        except StopIteration:
            latest_version -= 1
            if latest_version <= 0:
                raise UserError(
                    "No pointings in this directory matching the requested "
                    "seq_id appear usable."
                )
            latest_candidates = iter(
                valfilter(lambda key: int(key) == latest_version, versions)
            )
            continue
        try:
            pointing = get_and_offer_pointing(
                iof_path, noninteractive, binocular
            )
        except (UserError, ValueError):
            continue
        good_input = True
    return pointing


def create_marslab_output(
    marslab_data, metadata, outpath, pointing_name, suffix
):
    (
        marslab_compact,
        marslab_extended,
        pointing_summary,
    ) = assemble_marslab_versions(marslab_data, metadata, suffix)
    metadata_fn, extended_metadata_fn = verbosely_write_marslab_versions(
        marslab_compact, marslab_extended, outpath, pointing_name, suffix
    )
    return pointing_summary, metadata_fn, extended_metadata_fn


def xlabel_figure(fig, text, fontproperties):
    fig.axes[0].set_xlabel(
        xlabel=text, loc="center", fontproperties=fontproperties
    )


def make_pointing_annotation(pointing):
    return ", ".join(
        [
            key.lower() + " " + str(value)
            for key, value in parse_pointing(pointing).items()
        ]
    )


def add_input_roi_metadata(marslab_data, fixed_target, ci):
    for region in marslab_data["COLOR"]:
        ci(print, "Please enter information about the " + region + " ROI.")
        user_provided_roi_metadata = ask_user_about_roi(
            fixed_target, region, ci
        )
        for field, value in user_provided_roi_metadata.items():
            marslab_data.loc[marslab_data["COLOR"] == region, field] = value
    return marslab_data


def titular_names(pointing):
    pointing_name = make_pointing_name(pointing)
    if "NAME" in pointing.keys():
        target_name = pointing["NAME"].iloc[0] + " "
    else:
        target_name = ""
    return pointing_name, target_name





def make_rapidlook_thumbnails(rapidlooks, size):
    print("making thumbnails (if necessary).")
    thumbnails = {}
    for name, image in rapidlooks.items():
        thumbnails[name] = make_thumbnail(image, size)
    return thumbnails


def make_context_images(
    roi_fits,
    preloaded_images,
    pointing,
    outpath,
    onboard_debayer=False,
    suffix="",
):
    context_images = {}
    print("... making ROI context images ...")
    edgemaps = make_roi_edgemaps(roi_fits, calculate_centers=False)
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
