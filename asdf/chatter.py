"""
secondary-level handlers & wrappers for asdf workflow
"""
import os
from itertools import chain
from pathlib import Path
from typing import Callable
import warnings

from cytoolz.dicttoolz import valfilter
from marslab.compat.xcam import DERIVED_CAM_DICT
from marslab.imgops.poolutils import wait_for_it
from pathos.multiprocessing import ProcessPool
from rich.prompt import Prompt, Confirm
from rich.rule import Rule
from rich.text import Text

from asdf.asdf_utils import pass_parameters, dashify
from asdf.console import (
    ASDF_CONSOLE,
    ASDF_PROGRESS_SPIN,
    ASDF_RPH_SPIN,
    aprint,
    ASDFLOG,
)
from asdf.format import (
    preprocess_scan_path,
    make_pointing_annotation,
    annotate_and_save,
    save_plainly,
    insert_wavelengths_into_text, remove_stretch_names,
)
from asdf.pretty import (
    print_scan_results,
    colorize_merspect_roi_name,
    dispatched_metadata_prompt,
    style_prog,
    print_observation,
    metadata_choice_prompt,
)
from asdf.scan import (
    scan_zcam_files,
    cluster_analyses,
    find_obs_pixmaps,
    compare_roi_colors,
    fetch_analysis_files,
    make_marslab_metadata_df,
    prune_analysis_df,
    add_public_waypoints_to_metadata,
    add_effective_taus,
    cluster_observations,
    find_matching_observations,
)
from asdf.scrape import cached_exists
import asdf_settings as settings
from asdf_settings.metadata import (
    ROI_METADATA_FIELDS,
    FEATURE_EXCLUSIVE_ROI_FIELDS,
    EMPTY_METADATA_FIELDS,
    PIXEL_FLAG_NAMES,
)
import pplot


# TODO: rewrite everything in this module with better markup


def find_and_offer_observations(
    root_dir,
    explicit_path,
    noninteractive,
    keep_broadband,
    keep_caltarget,
    **scan_kwargs,
):
    """
    process a request for ZCAM files; print the results of the request to
    console; ask the user to select a observation if there is more than one;
    ask the user to confirm the observation if there is only one.
    """
    with ASDF_PROGRESS_SPIN as prog:
        ASDF_RPH_SPIN.task_id = prog.add_task(" ... scanning files ...")
        style_prog(prog, "green")
        try:
            root_dir, target_file = preprocess_scan_path(
                root_dir, explicit_path
            )
            products = scan_zcam_files(root_dir, **scan_kwargs)
            aprint(" ... chunking products into observations ...")
            results, problems, hidden_things = cluster_observations(
                products, target_file, keep_broadband, keep_caltarget
            )
        except (ValueError, FileNotFoundError, PermissionError) as err:
            prog.remove_task(ASDF_RPH_SPIN.task_id)
            aprint(str(err) + " :confused_face:", style="bold red")
            return None, False
        prog.remove_task(ASDF_RPH_SPIN.task_id)
    print_scan_results(results)
    if problems:
        for problem in problems:
            aprint(problem, style="dark_orange bold")
        aprint("\n")
    if hidden_things:
        for category in hidden_things:
            aprint(category, style="purple bold")
        aprint("\n")
    if len(results) == 0:
        aprint(
            "[bold red]Sorry, no usable observations found. :confused_face:"
        )
        return None, False
    if noninteractive:
        if (len(results) > 1) and (noninteractive != "all"):
            aprint(
                "noninteractive mode; using #1. If this isn't the one you "
                "wanted, please run asdf again and explicitly pass a file "
                "from the observation you want."
            )
            return tuple(results.values())[0], False
        if (len(results) > 1) and (noninteractive == "all"):
            aprint(
                "noninteractive-all mode; processing all observations.",
                style="dark_orange bold",
            )
            return tuple(results.values()), True
        return tuple(results.values())[0], False

    if len(results) > 1:
        obs_choice = Prompt.ask(
            "Please select an observation (0 to exit, a for all)",
            # 1-index for kindness
            choices=[str(ix) for ix in range(len(results) + 1)] + ["a"],
            default="1",
            console=ASDF_CONSOLE,
        )
        if obs_choice == "0":
            return reject_scan()
        if obs_choice != "a":
            return tuple(results.values())[int(obs_choice) - 1], False
        return tuple(results.values()), True
    else:
        if not Confirm.ask(
            "Does this look ok?", default="Y", console=ASDF_CONSOLE
        ):
            return reject_scan()
        return tuple(results.values())[0], False


def is_feature_mismatch(metadata, field):
    if field not in list(
        chain.from_iterable(FEATURE_EXCLUSIVE_ROI_FIELDS.values())
    ):
        return False
    if metadata.get("FEATURE") is None:
        return True
    if FEATURE_EXCLUSIVE_ROI_FIELDS.get(metadata["FEATURE"]) is None:
        return True
    return field not in FEATURE_EXCLUSIVE_ROI_FIELDS[metadata["FEATURE"]]


def ask_user_about_roi(
    roi_title=None, ci: Callable = pass_parameters, constants: dict = None
) -> dict:
    """
    ask the user about all of the ROI properties we care about, unless
    the application is in noninteractive mode, in which case return our
    null value "-" for all of them.

    :param roi_title: title of the ROI we're asking about -- presently always
        color, but no logical reason it must be
    :param ci: optional wrapper function that suppresses attempts to request
        input. for noninteractive mode.
    :param constants: a dictionary of fields and values that the user
        has asserted are constant across all ROIs.
    """
    if constants is None:
        constants = {}
    metadata_fields = list(ROI_METADATA_FIELDS)
    roi_metadata = {}
    for field in metadata_fields:
        # fill 'empty' fields like notes and coordinated observations
        if field in EMPTY_METADATA_FIELDS:
            roi_metadata[field] = ""
            continue
        # don't ask people soil questions about rocks, etc
        if is_feature_mismatch(roi_metadata, field):
            roi_metadata[field] = ""
            continue
        # if a user has told us a field is the same everywhere, don't bother
        # them about it
        if field in constants.keys():
            roi_metadata[field] = constants[field]
            continue
        roi_metadata[field] = ci(dispatched_metadata_prompt, field, roi_title)
    return roi_metadata


def input_roi_metadata(marslab_data, ci):
    constants = {}
    for field in ROI_METADATA_FIELDS:
        # TODO: this may be sloppy
        if field in EMPTY_METADATA_FIELDS:
            continue
        if is_feature_mismatch(constants, field):
            continue
        if ci(
            metadata_choice_prompt,
            Text(f"Is the value of {field} the same for all ROIs?"),
            ("Yes", "No"),
        ) == "Yes":
            constants[field] = dispatched_metadata_prompt(field)
    # TODO: this might be confusing if all fields are constant for all ROIs,
    #  but this is probably a rare case.
    for region in marslab_data["COLOR"]:
        ci(
            aprint,
            Text("Please enter information about the ")
            .append_text(colorize_merspect_roi_name(region))
            .append_text(Text(" ROI.")),
        )
        user_provided_metadata = ask_user_about_roi(region, ci, constants)
        for field, value in user_provided_metadata.items():
            marslab_data.loc[marslab_data["COLOR"] == region, field] = value
    return marslab_data


def handle_map_checks(bandset):
    pixmaps, match_warnings = find_obs_pixmaps(
        bandset.metadata["PATH"].unique()
    )
    if match_warnings:
        for warning in match_warnings:
            aprint("[bold purple]" + warning)
    pixmaps = valfilter(lambda x: x is not None, pixmaps)
    if not pixmaps:
        aprint(
            "[bold dark_orange]no matching pixmaps found; "
            "cancelling pixmap processing."
        )
        return
    if len(pixmaps) != len(bandset.metadata["PATH"].unique()):
        aprint(
            "[bold dark_orange] some data products missing pixmaps; "
            "cancelling pixmap processing."
        )
        return
    aprint("... found matching pixmaps for all images ...")
    bandset.metadata["PIXMAP_PATH"] = ""
    bandset.associate_pixmaps(pixmaps)
    bandset.load_pixmaps(verbose=True)


def loudly_ingest_analyses(path, sol=None, seq_id=None, file_regex=None):
    ASDF_CONSOLE.style = "FDSA"
    if not cached_exists(path):
        aprint("[hot_pink bold]sorry, {} does not exist.".format(str(path)))
        return
    aprint(
        "[hot_pink italic bold underline]... finding ROI and marslab files ..."
    )
    marslab_files, roi_files, other_files = fetch_analysis_files(path)
    reject_count = len(other_files)
    if (len(marslab_files) == 0) or (len(roi_files) == 0):
        aprint(
            "[italic dark_turquoise]found[bright_green] {} ROI and {} "
            "marslab files".format(len(roi_files), len(marslab_files))
        )
        return sorry_analysis()
    marslab = make_marslab_metadata_df(marslab_files)
    roi = make_marslab_metadata_df(roi_files)
    reject_count += len(marslab_files) - len(marslab)
    reject_count += len(roi_files) - len(roi)
    aprint(
        "[italic dark_turquoise]found[bright_green] {} ROI and {} "
        "marslab files; [slate_blue1]ignoring {} other files of other "
        "types".format(str(len(roi)), str(len(marslab)), reject_count)
    )
    if (len(roi) == 0) or (len(marslab) == 0):
        return sorry_analysis()
    marslab = prune_analysis_df(marslab, sol, seq_id, file_regex)
    roi = prune_analysis_df(roi, sol, seq_id, file_regex)
    aprint(
        "[italic bright_green]{} ROI and {} marslab files in path "
        "[dark_turquoise]matched[/dark_turquoise] sol, "
        "seq_id, and regex filters".format(str(len(roi)), str(len(marslab)))
    )
    if (len(roi) == 0) or (len(marslab) == 0):
        return sorry_analysis()
    aprint(
        "\n[hot_pink italic bold underline]... "
        "clustering ROI and metadata files ..."
    )
    analyses, lonely_marslab, lonely_roi = cluster_analyses(marslab, roi)
    if len(lonely_marslab) > 0:
        ASDF_CONSOLE.style = "FDSA.warning"
        aprint(
            "[bold]warning: these -marslab.csv files had no matching "
            "-roi.fits:\n\n[/bold]" + "\n".join(lonely_marslab["PATH"]) + "\n"
        )
    if len(lonely_roi) > 0:
        ASDF_CONSOLE.style = "FDSA.warning"
        aprint(
            (
                "[bold]warning: these -roi.fits files had no matching "
                "-marslab.csv:\n\n[/bold] " + "\n".join(lonely_roi["PATH"])
            ),
            style="slate_blue1",
        )

    if len(analyses) == 0:
        return sorry_analysis()
    ok_analyses, bad_analyses = compare_roi_colors(analyses)
    if len(bad_analyses) > 0:
        ASDF_CONSOLE.style = "FDSA.warning"
        aprint(
            "the following pairs of ROI/marslab files did not have "
            "matching colors: ",
        )
        for badmars, badroi in bad_analyses[["MARSLAB", "ROI"]].values:
            aprint(badmars + ", " + badroi)
    ASDF_CONSOLE.style = "FDSA"
    if len(ok_analyses) == 0:
        return sorry_analysis()
    aprint(
        "\n[bold white] found {} usable ROI/marslab pairs:\n".format(
            len(ok_analyses)
        )
    )
    for _, row in ok_analyses.iterrows():
        aprint("* " + row["MARSLAB"] + "\n" + "* " + row["ROI"] + "\n")
    if not Confirm.ask(
        Text(
            "Look for images to reprocess from metadata in these files?",
            style="bold white on black",
        ),
        default="Y",
        console=ASDF_CONSOLE,
    ):
        aprint(
            "[deep_pink2 bold]\nHalting. If you didn't see the marslab/ROI "
            "files you wanted to, "
            " check to make sure they're actually in the search tree and have "
            "matching names. If they are, try using different search "
            "parameters or copying the files interest into separate "
            "directories.",
        )
        return None
    return ok_analyses.reset_index(drop=True)


def setup_reprocess(
    marslab_path=".",
    image_path=".",
    sol=None,
    seq_id=None,
    marslab_regex=None,
    image_regex=None,
):
    analyses = loudly_ingest_analyses(marslab_path, sol, seq_id, marslab_regex)
    if analyses is None:
        return None, None
    aprint(Rule(" finding observational data ", style="deep_pink2 blink"))
    with ASDF_PROGRESS_SPIN as prog:
        style_prog(prog, "hot_pink on black")
        ASDF_RPH_SPIN.task_id = prog.add_task(" ... scanning files ...")
        try:
            (
                reprocess_pairs,
                parser_warnings,
                misses,
            ) = find_matching_observations(analyses, image_path, image_regex)
        except (PermissionError, FileNotFoundError, ValueError) as err:
            prog.remove_task(ASDF_RPH_SPIN.task_id)
            aprint(str(err) + " :confused_face:", style="bold red")
            return None, None
        prog.remove_task(ASDF_RPH_SPIN.task_id)
    if parser_warnings:
        for pw in parser_warnings:
            aprint(pw, style="purple bold")
    if misses:
        for miss_path in misses:
            aprint(
                "[slate_blue1]no matching observations in path for "
                "{}".format(miss_path),
            )
    if len(reprocess_pairs) == 0:
        sorry_analysis()
    aprint(
        "[bold white]found {} observation-metadata pair(s) for "
        "reprocessing.\n".format(str(len(reprocess_pairs)))
    )

    for marslab, obs in reprocess_pairs.items():
        aprint("[white bold]" + marslab)
        print_observation(obs)
    if not Confirm.ask(
        "Proceed with reprocessing these observations?",
        default="Y",
        console=ASDF_CONSOLE,
    ):
        aprint(
            "\nHalting. If you didn't see the products you wanted, check to "
            "make sure they're actually in the file system; if they are, try "
            "using different search parameters or copying the image files "
            "of interest into separate directories.",
            style="deep_pink2 italic",
        )
    return reprocess_pairs, analyses


def sorry_analysis():
    aprint(
        "[bold red]sorry, no usable analyses found for recreation."
        " :confused_face:"
    )
    return None


def reject_scan():
    aprint(
        "\nhalting due to user rejection of file list. If you didn't see the "
        "products you wanted and you passed an abbreviated path, try passing "
        "a full path instead. If all else fails, try copying the files you "
        "want to work with into a separate root_dir.",
        style="red bold",
    )
    return None, False


def collect_dispersed_metadata(metadata):
    """
    handler function for asdf.cli that runs around to several distinct
    sources asking them for additional info prior to ROI evaluation
    """

    if settings.sources.USE_PUBLIC_WAYPOINTS:
        aprint(
            "... scraping localization information from public "
            "waypoints file ..."
        )
        metadata = add_public_waypoints_to_metadata(metadata)
    if settings.sources.FIND_EFFECTIVE_TAUS:
        metadata = add_effective_taus(metadata)
    return metadata


def save_looks(bandset, outpath, prefix=None, threads=None, plain=False):
    # TODO: decide if this and annotate_and_save_rapidlook() should live on
    #  zcambandset -- this is not urgent.
    if prefix is None:
        prefix = bandset.name
    pool = None
    results = {}
    # TODO: dispatch these cases
    if threads is not None:
        ASDFLOG.info("... initializing worker pool ...")
        pool = ProcessPool(threads)
        pool.restart()
        ASDFLOG.info("... serializing images ...")
    for look_name, look in bandset.looks.items():
        # TODO: ugh.
        image_path = outpath
        if "pixmap" in look_name:
            image_path = str(Path(image_path, "pixmaps"))
        if not os.path.exists(image_path):
            os.makedirs(image_path)
        if plain is True:
            filename = write_plain_image(
                look, look_name, image_path, pool, prefix, results
            )
        else:
            filename = write_annotated_image(
                bandset, look, look_name, image_path, pool, prefix, results
            )
        bandset.local_files.append(str(Path(image_path, filename)))
    if pool is not None:
        # TODO: extend this, generally speaking, to give useful messages about
        #  failure
        wait_for_it(pool, results, ASDFLOG, "wrote ")


def write_plain_image(look, look_name, outpath, pool, prefix, results):
    filename = prefix + " " + look_name + "-plain.png"
    if pool is None:
        save_plainly(look, filename, outpath)
        ASDFLOG.info("wrote " + filename)
    else:
        results[filename] = pool.apipe(save_plainly, look, filename, outpath)
    return filename


def write_annotated_image(
    bandset, look, look_name, outpath, pool, prefix, results
):
    filename = prefix + " " + look_name + ".png"
    # aggressively remove names of stretches &c
    look_name = remove_stretch_names(look_name)
    look_name = insert_wavelengths_into_text(look_name, "band" in look_name)
    # annotation = "\n".join(
    #     (
    #         look_name,
    #         make_pointing_annotation(bandset.metadata),
    #         settings.rapidlooks.CREDIT_TEXT,
    #     )
    # )
    annotation = "\n".join(
        (
            make_pointing_annotation(bandset.metadata),
            settings.rapidlooks.CREDIT_TEXT,
        )
    )
    if pool is None:
        annotate_and_save(look_name, annotation, look, filename, outpath)
        ASDFLOG.info("wrote " + filename)
    else:
        results[filename] = pool.apipe(
            annotate_and_save, look_name, annotation, look, filename, outpath
        )
    return filename


def pretty_plot_bandset(bandset, outpath):
    aprint(Rule(" pretty-plotting data "))
    plot_fn = str(
        Path(outpath, bandset.name + bandset.suffix + "-pretty-plot.png")
    )
    from pplot.convert import scale_eyes

    target_name = ""
    if bandset.compact["NAME"].iloc[0]:
        target_name = bandset.compact["NAME"].iloc[0]
    plot_data = scale_eyes(bandset.compact.copy(), method="scale_to_avg")
    for band in DERIVED_CAM_DICT["ZCAM"]["filters"].keys():
        if plot_data[band].isna().any():
            plot_data.drop(columns=[band, band + "_ERR"], inplace=True)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        pplot.pplot_utils.pretty_plot(
            dashify(plot_data),
            target_name=target_name,
            sol=bandset.compact["SOL"].iloc[0],
            solar_elevation=bandset.compact["SOLAR_ELEVATION"].iloc[0],
            seq_id=bandset.compact["SEQ_ID"].iloc[0],
            plot_fn=plot_fn,
            underplot=None,
        )
    aprint("wrote " + Path(plot_fn).name)
    bandset.local_files.append(plot_fn)


def tw(text):
    return Text(text, style="bold dark_orange")


def fdsa_insert(marslab_data, prototype):
    for color in prototype["COLOR"].unique():
        proto_slice = prototype.loc[prototype["COLOR"] == color]
        if len(proto_slice) > 1:
            aprint(
                tw("this marslab file has multiple rows for ")
                .append_text(colorize_merspect_roi_name(color))
                .append_text(tw("... skipping."))
            )
            continue
        if len(proto_slice) == 0:
            aprint(
                tw("this marslab file is missing a row for ")
                + colorize_merspect_roi_name(color)
                + tw(". Something is wrong in fdsa's matching... skipping.")
            )
            continue
        fields_used = Text("")
        fields_skipped = Text("")
        for field in ROI_METADATA_FIELDS:
            if field not in prototype.columns:
                fields_skipped.append(
                    "note: no {} field in this marslab file, probably from an "
                    "earlier asdf version\n".format(field)
                )
                continue
            proto_value = proto_slice[field].iloc[0]
            fields_used.append_text(
                Text(" " + field + " ", style="default bold")
            ).append_text(Text(str(proto_value), style="bold hot_pink"))

            marslab_data.loc[
                marslab_data["COLOR"] == color, field
            ] = proto_value
        aprint(colorize_merspect_roi_name(color).append_text(fields_used))
        if fields_skipped:
            aprint(fields_skipped)
    return marslab_data


def complain_about_pixmap_counts(quality_df):
    for _, counts in quality_df.iterrows():
        color = counts["COLOR"]
        for flag in PIXEL_FLAG_NAMES:
            flag_counts = counts[
                [
                    ix
                    for ix in counts.index
                    if ((flag in ix) and counts[ix] != 0)
                ]
            ].copy()
            if len(flag_counts) == 0:
                continue
            flag_counts.index = flag_counts.index.str.replace("_" + flag, "")
            if flag in ("bad", "no_signal", "saturated"):
                mask_note = "masked from counting"
            else:
                mask_note = "not masked from counting"
            header = Text("note: ", style="dark_orange bold")
            roi = colorize_merspect_roi_name(color)
            complaint = Text(
                f" ROI has {flag} pixels ({mask_note}):\n",
                style="dark_orange bold",
            )
            values = "; ".join(
                [
                    band + ": " + str(count)
                    for band, count in flag_counts.items()
                ]
            )
            aprint(header.append(roi).append(complaint).append(values))
