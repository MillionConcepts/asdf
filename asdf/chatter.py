"""
Secondary-level handlers & wrappers for asdf/fdsa flow. Functions in this
module are intended primarily for use in interactive sessions or pipelines
that mock interactive sessions like fdsa. They intentionally print a lot of
formatted output to the console and require highly preprocessed inputs; they
are inappropriate for most uses outside the asdf/fdsa flow.
"""
from __future__ import annotations

from itertools import chain
import os
from pathlib import Path
import re
from typing import (
    Any, Callable, Optional, Literal, Mapping, TYPE_CHECKING, Union, Collection, TypedDict
)
import warnings

from cytoolz import groupby
from cytoolz.dicttoolz import valfilter
from dustgoggles.func import pass_parameters
from dustgoggles.scrape import cached_exists
from marslab.compat.xcam import DERIVED_CAM_DICT
from marslab.poolutils import wait_for_it
import pandas as pd
from pathos.multiprocessing import ProcessPool
from rich.rule import Rule
from rich.text import Text

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
    construct_browse_filename,
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
    confirm_fdsa_data, confirm_fdsa_warnings,
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
    METAMAP_TYPES,
)
from asdf_settings.metadata import (
    ROI_METADATA_FIELDS,
    FEATURE_EXCLUSIVE_ROI_FIELDS,
    EMPTY_METADATA_FIELDS,
    PIXEL_FLAG_NAMES,
    ROI_METADATA_FIELD_CHOICES,
    LEGACY_METADATA_FIELDS,
    LEGACY_SUBTYPE_FIELDS,
    CONDITIONAL_FIELDS,
    FEATURE_SUBTYPES
)
from asdf_settings.sources import USE_PUBLIC_WAYPOINTS, FIND_EFFECTIVE_TAUS

if TYPE_CHECKING:
    # noinspection PyProtectedMember
    from multiprocessing.pool import ApplyResult
    from matplotlib.figure import Figure
    from PIL.Image import Image
    from asdf.zcam_bandset import ZcamBandSet


# TODO: rewrite strings / rich printing in this module with better or at least
#  more consistent markup

def get_scan_results(
    explicit_path: Optional[Union[str, Path]],
    keep_broadband: bool,
    keep_caltarget: bool,
    root_dir: Optional[Union[str, Path]],
    scan_kwargs: Mapping
) -> Union[tuple[dict, tuple[str, ...], tuple[str, ...]], list]:
    """
    Handler function used in the find_and_offer_observations() workflow.
    Scans one or more directories for ZCAM IOF files and attempts to group
    them into valid 'clusters', recording a variety of failure states and
    intentional exclusions in the process.
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
            results, problems, hidden, _ = cluster_observations(
                products, target_file, keep_broadband, keep_caltarget
            )
        # TODO: what is going on here?
        except Exception:
            raise
        except (ValueError, FileNotFoundError, PermissionError) as err:
            # TODO: silly hack, fix signatures
            return list(reject_scan(f"{err} :confused_face:\n")) + [None]
        finally:
            prog.remove_task(ASDF_RPH_SPIN.task_id)
    return results, problems, hidden


def format_rsm_option(rsm):
    try:
        rsm = (rsm,) if not isinstance(rsm, tuple) else rsm
        assert isinstance(rsm[0], int)
        return rsm
    except (KeyError, AssertionError):
        aprint(
            "[bold red]Invalid format for --rsm argument. "
            "::sad_face:: Please pass an integer or a comma-separated "
            "list of integers."
        )


def find_and_offer_observations(
    root_dir,
    explicit_path=None,
    noninteractive=False,
    keep_broadband=False,
    keep_caltarget=False,
    mosaic=False,
    **scan_kwargs,
) -> tuple[
    Union[pd.DataFrame, tuple[pd.DataFrame, ...], None], Union[bool, None]
]:
    """
    Process a request for ZCAM files; print the results of the request to
    console; ask the user to select a observation if there is more than one;
    ask the user to confirm the observation if there is only one.

    Returns a tuple whose elements are:
    1. If we are in noninteractive-all mode and observations were found, or if
     multiple observations were found and the user requested that asdf run
     all of them, a tuple of dataframes; if we are in interactive or regular
     noninteractive mode, observations were found, and the user did not reject
     them, a single dataframe; if no observations were found or the user
     rejected them, None
    2. A status code that is True if asdf should expect to run multiple
     observations, False if it should expect to run only one, and None if no
     usable observations were found or the user rejected them.
    """
    if (rsm := scan_kwargs.get('rsm')) is not None:
        scan_kwargs['rsm'] = format_rsm_option(rsm)
    # TODO: pass polite error message rather than not-enough-values traceback
    #  when no results are found in a directory
    results, problems, hidden = get_scan_results(
        explicit_path, keep_broadband, keep_caltarget, root_dir, scan_kwargs
    )
    # meaningful error message for this case should have been printed in
    # get_scan_results
    if results is None:
        return None, None
    if mosaic is True:
        results = groupby(
            lambda item: item[1]['SEQ_ID'].iloc[0], results.items()
        )
        results = {k: v for k, v in results.items() if len(v) > 1}
    print_scan_results(results, mosaic)
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
        elif mosaic is True:
            suffix = "Can't perform mosaicking on a single-frame observation."
        return reject_scan(
            f"Sorry, no usable observations found. {suffix}:confused_face:\n"
        )
    if noninteractive is not False:
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
    if confirm_observation() is not True:
        return reject_scan(
            "halting due to user rejection of file list. If "
            "[italic]asdf[/italic] didn't find what you expected, "
        )
    return tuple(results.values())[0], False


def is_feature_mismatch(metadata: dict[str, str], field: str) -> bool:
    """
    Predicate function for ask_user_about_roi() workflow. Returns True if a
    particular metadata field is irrelevant to an ROI's assigned feature (e.g.
    MEMBER for an ROI with FEATURE 'soil')
    """
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
    fields, roi_metadata = _sort_fields(), constants.copy()
    for field in fields:
        # ignore legacy fields, constants, etc.
        if _checkskip(field, roi_metadata) != "ok":
            continue
        options, is_invalid = _check_field_options(field, roi_metadata)
        if is_invalid is True:
            continue
        roi_metadata[field] = ci(
            dispatched_metadata_prompt, field, roi_title, options
        )
    return roi_metadata


def _fix_order(order: dict[str, int]) -> bool:
    """
    Helper function for ROI metadata field-sorting algorithm. Swaps the first
    pair of fields it finds that are out of required ask order (e.g.,
    FEATURE_SUBTYPE before
    FEATURE), then returns False. If it finds no fields out of order, returns
    True, meaning the sort is done.
    """
    for k, v in CONDITIONAL_FIELDS.items():
        if order[k] < order[v]:
            order[v] = min(order.values()) - 1
            return False
    return True


def _sort_fields() -> list[str]:
    """
    Sorts ROI metadata fields we ask users about, ensuring we will always ask
    about them in the right order (e.g., we must ask about FEATURE before
    FEATURE_SUBTYPE). Returns a list of sorted fields.
    """
    order = {f: i for i, f in enumerate(ROI_METADATA_FIELDS)}
    while _fix_order(order) is False:
        continue
    fields = []
    for v in sorted(order.values()):
        fields.append(next(k for k in order.keys() if order[k] == v))
    return fields


def _checkskip(
    field: str, roi_metadata: dict
) -> Literal["skip", "mismatch", "constant", "ok"]:
    """
    Helper function for ROI question-asking workflow. Returns "skip" if a field
    is legacy (meaning that it should be propagated into the metadata but not
    further considered); "mismatch" if a field is inapplicable to the
    established FEATURE of an ROI (e.g. SOIL_LOCATION for an ROI with FEATURE
    "rock"), "constant" if a user has said a field is the same for all ROIs,
    meaning that it must be considered in the remainder of the question-asking
    workflow but the user should not be prompted about it, and "ok" if the
    user should be prompted about the field.
    """
    if field in (
        LEGACY_METADATA_FIELDS + LEGACY_SUBTYPE_FIELDS + EMPTY_METADATA_FIELDS
    ):
        return "skip"
    if is_feature_mismatch(roi_metadata, field):
        return "mismatch"
    if field in roi_metadata.keys():
        return "constant"
    return "ok"


def _check_field_options(
    field: str, roi_metadata: dict[str, str]
) -> tuple[Optional[list[str]], bool]:
    """
    Get valid options for per-ROI metadata fields depending on the
    preestablished values of other per-ROI metadata fields.
    """
    if field == "MEMBER":
        if "FORMATION" not in roi_metadata.keys():
            return None, True
        options = ROI_METADATA_FIELD_CHOICES["MEMBER"].get(
            roi_metadata["FORMATION"]
        )
        if options is None:
            return None, True
        return options, False
    elif field == "FEATURE_SUBTYPE":
        if "FEATURE" not in roi_metadata.keys():
            # note that we should only ever hit this condition during the
            # "do all ROIs have the same value" routine
            return None, True
        # also note that FEATURE_SUBTYPE should never get to
        # this function at all if the previously-specified FEATURE does not
        # have subtypes; it should have been filtered by _checkskip()
        return FEATURE_SUBTYPES[roi_metadata['FEATURE']], False
    return None, False


def input_roi_metadata(
    marslab_data: pd.DataFrame, ci: Callable[[Callable, Any, ...], str]
) -> pd.DataFrame:
    """
    Handler function that prompts a user for per-ROI metadata and inserts it
    into a dataframe of ROI counts.
    """
    fields, constants = _sort_fields(), {}
    for field in fields:
        if (field_disposition := _checkskip(field, constants)) == "skip":
            continue
        marslab_data[field] = ""
        if field_disposition == "mismatch":
            continue
        options, is_invalid = _check_field_options(field, constants)
        if is_invalid is True:
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
            if field not in marslab_data.columns:
                # TODO: why do we initialize this differently here?
                marslab_data[field] = pd.Series(dtype=object)
            marslab_data.loc[marslab_data["COLOR"] == region, field] = value
    return marslab_data


def handle_map_checks(
    bandset: ZcamBandSet, code: Literal[METAMAP_TYPES] = "pix_map"
):
    """
    Finds 'metamaps' of a particular type that match an observation loaded into
    a bandset (in the current pipeline, only pixmaps are fully supported)
    and loads them metamaps into that bandset. Prints various attractive status
    messages while doing so.
    """
    metamaps, match_warnings = find_obs_metamaps(
        bandset.metadata["PATH"].unique(), code=code,
    )
    if match_warnings:
        for warning in match_warnings:
            aprint("[bold purple]" + warning)
    metamaps = valfilter(lambda x: x is not None, metamaps)
    codestr = code.replace('_', '')
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
    bandset.associate_metamaps(metamaps, code=code)
    bandset.load_metamaps(verbose=True, code=code)


def loudly_ingest_analyses(
    path: Union[str, Path],
    sol: Optional[Union[str, int]] = None,
    seq_id: Optional[str] = None,
    file_regex: Optional[Union[str, re.Pattern]] = None,
    do_empties: Literal[True, False, "only"] = True,
    rsm: Optional[Union[int, Collection[int]]] = None
) -> Optional[pd.DataFrame]:
    """
    Chatty handler function for fdsa setup. Searches recursively under `path`
    for ROI FITS files and compact marslab files, optionally filtering them
    by sol, sequence id, or arbitrary filename regex, then attempts to match
    them to one another. Prints attractive messages about successful and
    failed matches while doing so. If `do_empties` is False, filters compact
    marslab files that contain no ROIs. If `do_empties` is "only", filters
    compact marslab files that _do_ contain ROIs.

    Returns a dataframe of "analyses" (information about matched compact
    marslab / ROI pairs, along with empty compact marslabs if do_empties is
    True or "only").
    """
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
    marslab = prune_analysis_df(marslab, sol, seq_id, file_regex, rsm)
    roi = prune_analysis_df(roi, sol, seq_id, file_regex, rsm)
    aprint(
        f"[italic bright_green]{len(roi)} ROI and {len(marslab)} marslab "
        f"files in path [dark_turquoise]matched[/dark_turquoise] sol, seq_id, "
        f"rsm, and regex filters"
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


FDSA_HALT_BOILERPLATE = (
    "\nHalting at user request. If you didn't see the products you wanted, "
    "check to make sure they're actually in the file system; if they are, try "
    "using different search parameters or copying the image files "
    "of interest into separate directories."
)


def setup_reprocess(
    marslab_path: Union[str, Path] = ".",
    image_path: Union[str, Path] = ".",
    sol: Optional[Union[str, int]] = None,
    seq_id: Optional[str] = None,
    marslab_regex: Optional[Union[str, re.Pattern]] = None,
    image_regex: Optional[Union[str, re.Pattern]] = None,
    do_empties: Literal[True, False, "only"] = True,
    rsm: Optional[Union[int, Collection[int]]] = None
) -> Union[tuple[dict[str, pd.DataFrame], pd.DataFrame], tuple[None, None]]:
    """
    Chatty handler function for top-level fdsa setup. Searches under
    `marslab_path` for compact marslab files and ROI files, then attempts to
    match them to one another, forming 'analyses'. Then, searches under
    `image_path` for IOFs and attempts to cluster them into observations that
    match each analysis. If at all successful, returns a dict matching compact
    marslab file paths to observation dataframes and a dataframe containing
    all unfiltered analyses. If not, returns (None, None). Prints various
    attractive status messages during operation.
    """
    analyses = loudly_ingest_analyses(
        marslab_path, sol, seq_id, marslab_regex, do_empties, rsm
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
            ) = find_matching_observations(
                analyses, image_path, image_regex, rsm
            )
        except (PermissionError, FileNotFoundError, ValueError) as err:
            prog.remove_task(ASDF_RPH_SPIN.task_id)
            aprint(str(err) + " :confused_face:", style="bold red")
            return None, None
        prog.remove_task(ASDF_RPH_SPIN.task_id)
    if parser_warnings:
        for pw in parser_warnings:
            aprint(pw, style="purple bold")
            if not confirm_fdsa_warnings():
                aprint(FDSA_HALT_BOILERPLATE, style="deep_pink2 italic")
                return None, None
    if misses:
        for miss_path in misses:
            aprint(f"[slate_blue1]no matching observations for {miss_path}")
            analyses = analyses.drop(
                analyses.loc[analyses["MARSLAB"].isin(misses)].index
            )
    if len(reprocess_pairs) == 0:
        return sorry_analysis(), None
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
        return None, None
    return reprocess_pairs, analyses


def sorry_analysis() -> None:
    """Prints an analysis-finding failure message."""
    aprint(
        "[bold red]sorry, no usable analyses found for recreation."
        " :confused_face:"
    )


def reject_scan(msg: str) -> tuple[None, None]:
    """
    Prints a user-rejected-results failure message and returns a tuple of
    (None, None) to match expected signatures.
    """
    aprint(
        f"[red bold]{msg}Try copying the specific files you want to work "
        f"with into a separate directory and running [italic]asdf[/italic] on "
        f"them there.\n"
        f"If you passed an abbreviated (-a) path, you could instead try "
        f"passing a full path to one of the files you want to work with."
    )
    return None, None


def collect_dispersed_metadata(
    metadata: pd.DataFrame, silent: bool = False
) -> pd.DataFrame:
    """
    Helper function for primary asdf workflow. Runs around to external sources
    asking them for additional info prior to ROI evaluation and adds them to a
    dataframe of metadata about an observation. At present this is mostly only
    for geospatial data from the waypoints server.
    """
    if USE_PUBLIC_WAYPOINTS:
        if not silent:
            aprint(
                "... scraping localization information from public "
                "waypoints file ..."
            )
        metadata = add_public_waypoints_to_metadata(metadata)
    if FIND_EFFECTIVE_TAUS:
        metadata = add_effective_taus(metadata)
    return metadata


def _write_plain_image(
    look: Union[Figure, Image],
    look_name: str,
    outpath: Union[str, Path],
    pool: Optional[ProcessPool],
    basename: str,
    results: dict[str, ApplyResult]
) -> str:
    """
    Writes a figure or image as a PNG file 'plainly', i.e., with no added
    caption. Shuold be called only as part of the save_looks() workflow.
    """
    filename = construct_browse_filename(look_name, basename)
    # TODO: make this special case less gross
    if "mosaic" not in filename:
        filename = filename.split(".")[0] + "-plain.png"
    if pool is None:
        save_plainly(look, filename, outpath)
        ASDFLOG.info("wrote " + filename)
    else:
        results[filename] = pool.apipe(save_plainly, look, filename, outpath)
    return filename


def _write_annotated_image(
    bandset: ZcamBandSet,
    look: Union[Figure, Image],
    look_name: str,
    outpath: Union[str, Path],
    pool: Optional[ProcessPool],
    prefix: str,
    results: dict[str, ApplyResult]
) -> str:
    """
    Write a Figure or Image to disk as a PNG file with a standardized caption.
    Should be called only as part of the save_looks() workflow.
    """
    annotation, title = construct_title_and_annotation(bandset, look_name)
    filename = construct_browse_filename(look_name, prefix)
    if pool is None:
        annotate_and_save(title, annotation, look, filename, outpath)
        ASDFLOG.info("wrote " + filename)
    else:
        results[filename] = pool.apipe(
            annotate_and_save, title, annotation, look, filename, outpath
        )
    return filename


def save_looks(
    bandset: ZcamBandSet,
    outpath: Union[str, Path],
    basename: Optional[str] = None,
    threads: Optional[int] = None,
    plain: bool = False
) -> None:
    """
    Chatty handler function to save all rapidlooks associated with a bandset
    as PNG images. Applies various naming rules and, optionally, performs
    writes in multiple threads. If `plain` is True, saves images with no
    captions.
    """
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
            filename = _write_plain_image(
                look, look_name, image_path, pool, basename, results
            )
        else:
            filename = _write_annotated_image(
                bandset, look, look_name, image_path, pool, basename, results
            )
        bandset.local_files.append(str(Path(image_path, filename)))
    if pool is not None:
        # TODO: extend this, generally speaking, to give useful messages about
        #  failure
        wait_for_it(pool, results, ASDFLOG, "wrote ")


def pretty_plot_bandset(
    bandset: ZcamBandSet, outpath: Union[str, Path]
) -> None:
    """
    Preprocesses a bandset's ROI data and metadata and feeds it to pretty-plot,
    which plots it and saves it to disk as a PNG file.
    """
    aprint(Rule(" pretty-plotting data "))
    plot_fn_stem = str(
        Path(outpath, f"pretty_plot_{bandset.name + bandset.suffix}")
    )
    from pretty_plot.pplot_utils import pretty_plot
    from asdf_settings.pretty_plots import PRETTY_PLOT_DEFINITIONS

    # TODO: what was this?
    # target_name = ""
    # if bandset.compact["NAME"].iloc[0]:
    #     target_name = bandset.compact["NAME"].iloc[0]

    plot_data = bandset.compact.copy()
    for band in DERIVED_CAM_DICT["ZCAM"]["filters"].keys():
        if plot_data[band].isna().any():
            plot_data.drop(columns=[band, band + "_STD"], inplace=True)
    plot_fns, kwargs = [], []
    for ppdef in PRETTY_PLOT_DEFINITIONS:
        plot_fns.append(
            f"{plot_fn_stem}.png"
            if "suffix" not in ppdef.keys()
            else f"{plot_fn_stem}-{ppdef['suffix']}.png"
        )
        kwargs.append(ppdef.get("kwargs", {}))
    if len(plot_fns) != len(set(plot_fns)):
        ASDFLOG.error(
            "Duplicate pretty-plot definition names. Stopping plot generation."
        )
        return
    obsgeom = {
        "incidence": bandset.compact["INCIDENCE_ANGLE"].iloc[0],
        "emission": bandset.compact["EMISSION_ANGLE"].iloc[0],
        "phase": bandset.compact["PHASE_ANGLE"].iloc[0]
    }
    for fn, kw in zip(plot_fns, kwargs):
        pretty_plot(
            plot_data,
            solar_elevation=bandset.compact["SOLAR_ELEVATION"].iloc[0],
            plot_fn=fn,
            observation_geometry=obsgeom,
            **kw
        )
        aprint("wrote " + Path(fn).name)
        bandset.local_files.append(fn)

# TODO: improve structure
def fdsa_insert(
    marslab_data: pd.DataFrame, prototype: pd.DataFrame
) -> pd.DataFrame:
    """
    fdsa-mode version of ask-user-about-ROIs workflow. Propagates metadata
    loaded from a compact marslab file into a dataframe of counted ROIs.
    """
    fields_skipped = []
    for field in ROI_METADATA_FIELDS:
        if field not in prototype.columns:
            if field in LEGACY_METADATA_FIELDS + LEGACY_SUBTYPE_FIELDS:
                # who cares!
                continue
            fields_skipped.append(field)
            marslab_data[field] = ""
            continue
    usable_fields = [f for f in prototype.columns if f in ROI_METADATA_FIELDS]
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
        for field in usable_fields:
            proto_value = proto_slice[field].iloc[0]
            if proto_value == "-":
                continue
            use_message = f" {field} "
            if field in LEGACY_METADATA_FIELDS:
                use_message += "(retained legacy field) "
            fields_used.append_text(
                Text(use_message, style="default bold")
            ).append_text(Text(str(proto_value), style="bold hot_pink"))
            # TODO: can cut this shortly
            if field in LEGACY_SUBTYPE_FIELDS:
                if isinstance(proto_value, str):
                    target = "FEATURE_SUBTYPE"
                else:
                    continue
            else:
                target = field
            if target not in marslab_data.columns:
                marslab_data[target] = pd.Series(dtype=object)
            marslab_data.loc[
                marslab_data["COLOR"] == color, target
            ] = proto_value
        aprint(colorize_merspect_roi_name(color).append_text(fields_used))

    if len(fields_skipped) > 0:
        aprint(
            f"note: no {', '.join(set(fields_skipped))} "
            f"field(s) in this marslab file, "
            f"probably from an earlier asdf version\n"
        )

    return marslab_data


# TODO: improve structure
def complain_about_pixmap_counts(quality_df: pd.DataFrame):
    """Print information about bad/hot/etc. pixels to console."""
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


def check_mosaic_paths(
    bandsets: list[ZcamBandSet],
    outpath: Union[str, Path]
) -> Optional[dict[Literal["L", "R"], Path]]:
    """
    Assemble expected names for existing mosaic files, check if they're
    present, and print an error if they're not. Returns a dict like
    {'L': l_path, 'R': r_path} if found and None if not (which cues asdf to
    bail out).

    Intended for reuse_mosaics workflow.
    """
    from asdf.mosaic import concat_mosaic_fn

    mosaic_filenames = {
        eye: concat_mosaic_fn(
            bandsets[0].metadata["SOL"].iloc[0],
            bandsets[0].metadata["SEQ_ID"].iloc[0],
            eye
        )
        for eye in ("L", "R")
    }
    mosaic_paths = {
        k: Path(outpath, "data", v) for k, v in mosaic_filenames.items()
    }
    for k, v in mosaic_paths.items():
        if not Path(v).exists():
            aprint(
                "[red bold]--reuse_mosaics passed, but concatenated "
                "mosaic files not available. Please run again without "
                "this flag or provide the files. Bailing out."
            )
        return
    # noinspection PyTypeChecker
    return mosaic_paths
