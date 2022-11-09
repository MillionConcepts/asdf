"""
secondary-level handlers & wrappers for asdf workflow
"""
import os
from itertools import chain
from pathlib import Path
from typing import Callable
import warnings

import pandas as pd
from cytoolz.dicttoolz import valfilter
from dustgoggles.scrape import cached_exists
from marslab.compat.xcam import DERIVED_CAM_DICT
from marslab.poolutils import wait_for_it
from pathos.multiprocessing import ProcessPool
from rich.rule import Rule
from rich.text import Text

from asdf.asdf_utils import dashify
from dustgoggles.func import pass_parameters
from asdf.console import (
    ASDF_CONSOLE,
    ASDF_PROGRESS_SPIN,
    ASDF_RPH_SPIN,
    aprint,
    ASDFLOG,
)
from asdf.format import (
    preprocess_scan_path,
    annotate_and_save,
    save_plainly,
    construct_filename,
    construct_title_and_annotation,
)
from asdf.pretty import (
    print_scan_results,
    colorize_merspect_roi_name,
    dispatched_metadata_prompt,
    style_prog,
    print_observation,
    metadata_choice_prompt,
    confirm_observation,
    offer_observation_choice,
    tw,
    confirm_fdsa_metadata,
    confirm_fdsa_data,
)
from asdf.scan import (
    scan_zcam_files,
    cluster_analyses,
    find_obs_metamaps,
    compare_roi_colors,
    fetch_analysis_files,
    make_marslab_metadata_df,
    prune_analysis_df,
    add_public_waypoints_to_metadata,
    add_effective_taus,
    cluster_observations,
    find_matching_observations,
)
from asdf_settings.metadata import (
    ROI_METADATA_FIELDS,
    FEATURE_EXCLUSIVE_ROI_FIELDS,
    EMPTY_METADATA_FIELDS,
    PIXEL_FLAG_NAMES,
    ROI_METADATA_FIELD_CHOICES,
    LEGACY_METADATA_FIELDS, FEATURE_SUBTYPES, LEGACY_SUBTYPE_FIELDS,
)
from asdf_settings.sources import USE_PUBLIC_WAYPOINTS, FIND_EFFECTIVE_TAUS
import pplot


# TODO: rewrite strings / rich printing in this module with better or at least
#  more consistent markup


def get_scan_results(
    explicit_path, keep_broadband, keep_caltarget, root_dir, scan_kwargs
):
    with ASDF_PROGRESS_SPIN as prog:
        ASDF_RPH_SPIN.task_id = prog.add_task(" ... scanning files ...")
        style_prog(prog, "green")
        try:
            root_dir, target_file = preprocess_scan_path(
                root_dir, explicit_path
            )
            products = scan_zcam_files(root_dir, **scan_kwargs)
            aprint(" ... chunking products into observations ...")
            results, problems, hidden, _ = cluster_observations(
                products, target_file, keep_broadband, keep_caltarget
            )
        except (ValueError, FileNotFoundError, PermissionError) as err:
            # TODO: silly hack, fix signatures
            return list(reject_scan(f"{err} :confused_face:\n")) + [None]
        finally:
            prog.remove_task(ASDF_RPH_SPIN.task_id)
    return results, problems, hidden


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
    # TODO: pass polite error message rather than not-enough-values traceback
    #  when no results are found in a directory
    results, problems, hidden = get_scan_results(
        explicit_path, keep_broadband, keep_caltarget, root_dir, scan_kwargs
    )
    # meaningful error message for this case should have been printed in
    # get_scan_results
    if results is None:
        return None, None
    print_scan_results(results)
    for category, color in zip((problems, hidden), ("dark_orange", "purple")):
        if len(category) == 0:
            continue
        for subcategory in category:
            aprint(subcategory, style=f"{color} bold")
        aprint("\n")
    if not len(results):
        suffix = ""
        if problems:
            if any(["cluster" in problem for problem in problems]):
                suffix = (
                    "This observation seems to be too complicated for "
                    "the automated clustering algorithm. "
                )
        return reject_scan(
            f"Sorry, no usable observations found. {suffix}:confused_face:\n"
        )
    if noninteractive:
        if noninteractive == "all":
            aprint(
                "noninteractive-all mode; processing all observations.",
                style="dark_orange bold",
            )
            return tuple(results.values()), True
        aprint(
            "noninteractive mode; using #1. If this isn't the one you "
            "wanted, please run asdf again and explicitly pass a file "
            "from the observation you want."
        )
        return tuple(results.values())[0], False
    if len(results) > 1:
        obs_choice = offer_observation_choice(len(results))
        if obs_choice == "0":
            return reject_scan(
                "halting due to user rejection of file list. If "
                "[italic]asdf[/italic] didn't find what you expected, "
            )
        if obs_choice != "a":
            return tuple(results.values())[int(obs_choice) - 1], False
        return tuple(results.values()), True
    else:
        if not confirm_observation():
            return reject_scan(
                "halting due to user rejection of file list. If "
                "[italic]asdf[/italic] didn't find what you expected, "
            )
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
        # ignore legacy fields
        if field in LEGACY_METADATA_FIELDS:
            continue
        # fill 'empty' fields like notes
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
        # sideloaded options for flowdown from within-category choices.
        # currently used only for FORMATION / MEMBER.
        # TODO: kind of a hack.
        options = None
        if field == "MEMBER":
            if "FORMATION" not in roi_metadata.keys():
                continue
            options = ROI_METADATA_FIELD_CHOICES["MEMBER"].get(
                roi_metadata["FORMATION"]
            )
            if options is None:
                continue
        if field == "FEATURE_SUBTYPE":
            if "FEATURE" not in roi_metadata.keys():
                continue
            options = FEATURE_SUBTYPES[roi_metadata["FEATURE"]]
        roi_metadata[field] = ci(
            dispatched_metadata_prompt, field, roi_title, options
        )
    return roi_metadata


def input_roi_metadata(marslab_data, ci):
    constants = {}
    for field in ROI_METADATA_FIELDS:
        # TODO: this may all be excessively sloppy
        options = None
        if field in chain.from_iterable(
            [EMPTY_METADATA_FIELDS + LEGACY_METADATA_FIELDS]
        ):
            continue
        if is_feature_mismatch(constants, field):
            continue
        if field == "MEMBER":
            if "FORMATION" not in constants.keys():
                continue
            options = ROI_METADATA_FIELD_CHOICES["MEMBER"].get(
                constants["FORMATION"]
            )
            if options is None:
                continue
        constant_query = ci(
            metadata_choice_prompt,
            Text(f"Is the value of {field} the same for all ROIs?"),
            ("Yes", "No"),
        )
        if constant_query == "Yes":
            constants[field] = dispatched_metadata_prompt(
                field, sideload_options=options
            )
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


def handle_map_checks(bandset,code="pix_map"):
    metamaps, match_warnings = find_obs_metamaps(
        bandset.metadata["PATH"].unique(),code=code,
    )
    if match_warnings:
        for warning in match_warnings:
            aprint("[bold purple]" + warning)
    metamaps = valfilter(lambda x: x is not None, metamaps)
    codestr = code.replace('_','')
    if not metamaps:
        aprint(
            f"[bold dark_orange]no matching {codestr}s found; "
            f"cancelling {codestr} processing."
        )
        return
    if len(metamaps) != len(bandset.metadata["PATH"].unique()):
        aprint(
            f"[bold dark_orange] some data products missing {codestr}s; "
            f"cancelling {codestr} processing."
        )
        return
    aprint(f"... found matching {codestr}s for all images ...")
    bandset.metadata[f"{codestr.upper()}_PATH"] = ""
    bandset.associate_metamaps(metamaps,code=code)
    bandset.load_metamaps(verbose=True, code=code)


def loudly_ingest_analyses(
    path, sol=None, seq_id=None, file_regex=None, do_empties=True
):
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
        f"[italic bright_green]{len(roi)} ROI and {len(marslab)} marslab "
        f"files in path [dark_turquoise]matched[/dark_turquoise] sol, seq_id, "
        f"and regex filters"
    )
    if len(marslab) == 0:
        return sorry_analysis()
    aprint(
        "\n[hot_pink italic bold underline]... "
        "clustering ROI and metadata files ..."
    )
    analyses, lonely_marslab, empty_marslab, lonely_roi = cluster_analyses(
        marslab, roi
    )
    if len(empty_marslab) > 0:
        ASDF_CONSOLE.style = "FDSA.warning"
        aprint(
            "[bold]warning: these -marslab.csv files contain no data: "
            "\n\n[/bold]" + "\n".join(empty_marslab["PATH"]) + "\n"
        )
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
                "[bold]warning: these -roi.* files had no matching "
                "-marslab.csv:\n\n[/bold] " + "\n".join(lonely_roi["PATH"])
            ),
            style="slate_blue1",
        )
    if (do_empties == "only") and (len(analyses) > 0):
        aprint(
            "\n[bold dark_orange]note: do_empties = 'only' passed, ignoring "
            "all non-empty marslab files"
        )
        analyses = analyses.drop(analyses.index)
    elif (do_empties is False) and (len(empty_marslab) > 0):
        aprint(
            "\n[bold dark_orange]note: do_empties = False passed, ignoring "
            "all empty marslab files"
        )
        empty_marslab = empty_marslab.drop(empty_marslab.index)
    if len(analyses) + len(empty_marslab) == 0:
        return sorry_analysis()
    if len(analyses) > 0:
        aprint(
            "\n[hot_pink italic bold underline]... "
            "checking marslab/ROI pairs for matching colors ..."
        )
        analyses, bad_analyses = compare_roi_colors(analyses)
        if len(bad_analyses) > 0:
            ASDF_CONSOLE.style = "FDSA.warning"
            aprint(
                "\n\n[bold]warning: these pairs of ROI/marslab files did not "
                "have matching colors:\n",
            )
            for badmars, badroi in bad_analyses[["MARSLAB", "ROI"]].values:
                aprint(badmars + ", " + badroi)
    ASDF_CONSOLE.style = "FDSA"
    if len(analyses) + len(empty_marslab) == 0:
        return sorry_analysis()
    message = (
        f"\n[bold white] found {len(analyses)} usable " f"ROI/marslab pair(s) "
    )
    if len(empty_marslab) > 0:
        message += f"and {len(empty_marslab)} empty marslab files"
    aprint(message + ":\n")
    empty_marslab["MARSLAB"] = empty_marslab["PATH"]
    empty_marslab["ROI"] = None
    analyses = pd.concat(
        [analyses, empty_marslab[analyses.columns]]
    ).sort_values(by="SOL")
    for _, row in analyses.iterrows():
        aprint(f"* {row['MARSLAB']}\n* {row['ROI']}\n")
    if not confirm_fdsa_metadata():
        aprint(
            "[deep_pink2 bold]\nHalting. If you didn't see the marslab/ROI "
            "files you wanted to, check to make sure they're actually in "
            "the search tree and have matching names. If they are, try using "
            "different search parameters or copying the files of interest "
            "into separate directories.",
        )
        return None
    return analyses.reset_index(drop=True)


def setup_reprocess(
    marslab_path=".",
    image_path=".",
    sol=None,
    seq_id=None,
    marslab_regex=None,
    image_regex=None,
    do_empties=True,
):
    analyses = loudly_ingest_analyses(
        marslab_path, sol, seq_id, marslab_regex, do_empties
    )
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
            aprint(f"[slate_blue1]no matching observations for {miss_path}")
            analyses = analyses.drop(
                analyses.loc[analyses["MARSLAB"].isin(misses)].index
            )
    if len(reprocess_pairs) == 0:
        sorry_analysis()
    aprint(
        f"[bold white]found {len(reprocess_pairs)} observation-metadata "
        f"pair(s) for reprocessing.\n"
    )

    for marslab, obs in reprocess_pairs.items():
        aprint("[white bold]" + marslab)
        print_observation(obs)
    if not confirm_fdsa_data():
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


def reject_scan(msg):
    aprint(
        f"[red bold]{msg}Try copying the specific files you want to work "
        f"with into a separate directory and running [italic]asdf[/italic] on "
        f"them there.\n"
        f"If you passed an abbreviated (-a) path, you could instead try "
        f"passing a full path to one of the files you want to work with."
    )
    return None, None


def collect_dispersed_metadata(metadata):
    """
    handler function for asdf.cli that runs around to several distinct
    sources asking them for additional info prior to ROI evaluation
    """

    if USE_PUBLIC_WAYPOINTS:
        aprint(
            "... scraping localization information from public "
            "waypoints file ..."
        )
        metadata = add_public_waypoints_to_metadata(metadata)
    if FIND_EFFECTIVE_TAUS:
        metadata = add_effective_taus(metadata)
    return metadata


def save_looks(bandset, outpath, basename=None, threads=None, plain=False):
    # TODO: decide if this and annotate_and_save_rapidlook() should live on
    #  zcambandset -- this is not urgent.
    if basename is None:
        basename = bandset.name
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
        image_path = str(outpath)
        if "pixmap" in look_name:
            image_path = str(Path(image_path, "pixmaps"))
        if not os.path.exists(image_path):
            os.makedirs(image_path)
        if plain is True:
            filename = write_plain_image(
                look, look_name, image_path, pool, basename, results
            )
        else:
            filename = write_annotated_image(
                bandset, look, look_name, image_path, pool, basename, results
            )
        bandset.local_files.append(str(Path(image_path, filename)))
    if pool is not None:
        # TODO: extend this, generally speaking, to give useful messages about
        #  failure
        wait_for_it(pool, results, ASDFLOG, "wrote ")


def write_plain_image(look, look_name, outpath, pool, basename, results):
    filename = f"{look_name.replace(' ', '_')}_{basename}-plain.png"
    if pool is None:
        save_plainly(look, filename, outpath)
        ASDFLOG.info("wrote " + filename)
    else:
        results[filename] = pool.apipe(save_plainly, look, filename, outpath)
    return filename


def write_annotated_image(
    bandset, look, look_name, outpath, pool, prefix, results
):
    annotation, title = construct_title_and_annotation(bandset, look_name)
    filename = construct_filename(look_name, prefix)
    if pool is None:
        annotate_and_save(title, annotation, look, filename, outpath)
        ASDFLOG.info("wrote " + filename)
    else:
        results[filename] = pool.apipe(
            annotate_and_save, title, annotation, look, filename, outpath
        )
    return filename


def pretty_plot_bandset(bandset, outpath):
    aprint(Rule(" pretty-plotting data "))
    plot_fn = str(
        Path(outpath, f"pretty_plot_{bandset.name + bandset.suffix}.png")
    )
    from pplot.convert import scale_eyes

    target_name = ""
    if bandset.compact["NAME"].iloc[0]:
        target_name = bandset.compact["NAME"].iloc[0]
    plot_data = scale_eyes(bandset.compact.copy(), method="scale_to_avg")
    for band in DERIVED_CAM_DICT["ZCAM"]["filters"].keys():
        if plot_data[band].isna().any():
            plot_data.drop(columns=[band, band + "_STD"], inplace=True)
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


# TODO: improve structure
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
                if field in LEGACY_METADATA_FIELDS + LEGACY_SUBTYPE_FIELDS:
                    # who cares!
                    continue
                fields_skipped.append(
                    f"note: no {field} field in this marslab file, probably "
                    f"from an earlier asdf version\n"
                )
                marslab_data[field] = ""
                continue
            proto_value = proto_slice[field].iloc[0]
            use_message = f" {field} "
            if field in LEGACY_METADATA_FIELDS:
                if proto_value == "-":
                    continue
                use_message += "(retained legacy field) "
            fields_used.append_text(
                Text(use_message, style="default bold")
            ).append_text(Text(str(proto_value), style="bold hot_pink"))
            # TODO: can cut this shortly
            if field in LEGACY_SUBTYPE_FIELDS:
                target = "FEATURE_SUBTYPE"
            else:
                target = field
            marslab_data.loc[
                marslab_data["COLOR"] == color, target
            ] = proto_value
        aprint(colorize_merspect_roi_name(color).append_text(fields_used))
        if fields_skipped:
            aprint(fields_skipped)

    return marslab_data


# TODO: improve structure
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
