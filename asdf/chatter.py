"""
functionality for directly addressing and listening to the user from the
command line goes in this module, including interactive wrappers for scraping
functions, etc.
"""
import os.path
from types import MappingProxyType
from typing import Callable

from clize import UserError

from asdf.console import ASDF_CONSOLE
from marslab.compat.mertools import MERSPECT_M20_COLOR_MAPPINGS
from rich.highlighter import Highlighter
from rich.prompt import Prompt, Confirm
from rich.table import Table
from rich.text import Text

import asdf.settings as settings
from asdf.asdf_utils import pass_parameters, extract_constants
from asdf.scrape import scan_zcam_dir


# TODO: this isn't spanning across instruments, should fold into
#   marslab.parse, blah blah
CAM_IMAGE_SLICES = MappingProxyType(
    {
        "instrument": (0, 1),
        "filter": (1, 3),
        "sol": (4, 8),
        "venue": (8, 9),
        "stime": (9, 19),
        "ttime": (20, 23),
        "ptype": (23, 26),
        "geometry": (26, 27),
        "thumbnail": (27, 28),
        "site": (28, 31),
        "drive": (31, 35),
        "sequence": (35, 44),
        "cam_specific": (44, 48),
        "downsample": (48, 49),
        "compression": (49, 51),
        "producer": (51, 52),
        "version": (52, 54),
        "ext": (54, 58),
    }
)


class M20CameraHighlighter(Highlighter):
    def highlight(self, text):
        for section, slice_ix in CAM_IMAGE_SLICES.items():
            if section in ("sol", "stime"):
                text.stylize("green", *slice_ix)
            elif section in ("sequence", "filter"):
                text.stylize("bold dark_turquoise", *slice_ix)
            elif section == "thumbnail":
                text.stylize("yellow", *slice_ix)
            elif section == "ptype":
                text.stylize("red", *slice_ix)


def print_scan(scan):
    ASDF_CONSOLE.print("\n")
    if len(scan) == 0:
        ASDF_CONSOLE.print(
            "Sorry, no usable observations found. :confused_face:",
            style="red bold",
        )
        return
    if len(scan) > 1:
        is_multiple = True
        ASDF_CONSOLE.print(
            "found {} observations (ordered by seq_id / "
            "chronologically within seq_ids):".format(len(scan)),
        )
    else:
        is_multiple = False
        ASDF_CONSOLE.print("found 1 observation:")
    ASDF_CONSOLE.print("\n")
    for ix, extracted_observation in enumerate(extract_scan_constants(scan)):

        headline, tailtext, printframe = format_observation(
            extracted_observation
        )
        table = Table(padding=(0, 3, 0, 1), show_edge=False)
        if is_multiple:
            table.add_column(str(ix + 1) + ":", style="bold turquoise2")
        else:
            table.add_column("")
        headline.append_text(Text("\n")).append_text(tailtext)
        table.add_column(headline)

        camhighlight = M20CameraHighlighter()
        for row in printframe.to_records(index=False):
            table.add_row(row[0], camhighlight(row[1]))
        ASDF_CONSOLE.print(table)
        ASDF_CONSOLE.print("\n")


def format_roi_title(roi_title):
    prompt_text = Text()
    if roi_title is not None:
        prompt_text.append("the ")
        prompt_text.append(colorize_merspect_roi_name(roi_title))
    else:
        prompt_text.append("this")
    return prompt_text


def name_prompt() -> str:
    """what is the overall name of this observation? tell me."""
    prompt_text = Text("Please enter the ")
    prompt_text.append_text(Text("name ", style="bold orchid1"))
    prompt_text.append_text(Text("of this observation."))
    return Prompt.ask(prompt_text, console=ASDF_CONSOLE)


def y_n_prompt(prompt_text, title=None):
    texts = prompt_text.split("{title}")
    title = format_roi_title(title)
    formatted_text = texts[0].append_text(title).append_text(texts[1])
    value = Confirm.ask(formatted_text, default=False, console=ASDF_CONSOLE)
    if value is True:
        return "Y"
    return "N"


def scam_prompt(title=None) -> str:
    """is this a SCAM target? tell me."""
    prompt_text = Text("Is the feature associated with {title} ROI a ")
    prompt_text.append_text(Text("SCAM target", style="bold"))
    return y_n_prompt(prompt_text, title)


def float_prompt(title=None) -> str:
    """is this a float? tell me."""
    prompt_text = Text("Is the feature associated with {title} ROI a ")
    prompt_text.append_text(Text("float", style="bold"))
    return y_n_prompt(prompt_text, title)


def colorize_merspect_roi_name(roi_color_name=None):
    roi_color_hex = MERSPECT_M20_COLOR_MAPPINGS.get(roi_color_name)
    if roi_color_hex is None:
        return Text(roi_color_name, style="bold white")
    return Text(roi_color_name, style="bold " + roi_color_hex)


def generic_metadata_prompt(field_name, title=None) -> str:
    """extremely generic metadata input with no error checking or anything"""
    prompt_text = Text("Please enter the name of the ")
    prompt_text.append(field_name, style="bold")
    prompt_text.append(" associated with ")
    prompt_text.append(format_roi_title(title))
    prompt_text.append(" image sequence or ROI. (press Enter to skip)")
    return Prompt.ask(prompt_text, console=ASDF_CONSOLE)


def dispatched_metadata_prompt(field_name: str, title: str = None) -> str:
    """
    ask user for the value of a metadata field. calls specific functions as
    necessary to provide sensical and grammatically correct prompts
    """
    if field_name.lower() == "float":
        return float_prompt(title)
    if field_name.lower() == "scam":
        return scam_prompt(title)
    # etc., etc., etc.
    return generic_metadata_prompt(field_name, title)


def format_observation(extracted_observation):
    constant_dict, filterframe = extracted_observation
    printframe = filterframe[["FILTER", "PATH"]].copy()
    printframe = printframe.sort_values(by="FILTER")
    printframe["PATH"] = [
        os.path.split(path)[-1] for path in printframe["PATH"]
    ]
    tailtext = Text()
    if constant_dict.get("FRAME_TYPE") == "STEREO":
        tailtext.append("eyes simultaneous")
    elif constant_dict.get("FRAME_TYPE") == "MONO":
        tailtext.append("repointed stereo")
    # TODO: this colorizing gets overwritten by the default table header style
    if constant_dict.get("COMPLETION") != "COMPLETE_CHECKSUM_PASS":
        tailtext.append(", ")
        tailtext.append("contains partials", style="dark_orange")
    if constant_dict.get("THUMBNAIL") == "T":
        tailtext.append(", ")
        tailtext.append("thumbnails", style="dark_orange")
    headline_keys = ["SOL", "SEQ_ID", "SITE", "DRIVE"]

    headline = Text(
        ", ".join(
            [key + " " + str(constant_dict.get(key)) for key in headline_keys]
        )
    )
    if constant_dict.get("LTST"):  # single simultaneous stereo pair case
        starting_ltst = constant_dict["LTST"]
    else:
        starting_ltst = filterframe["LTST"].iloc[0]
    tailtext.append(", starting LTST " + str(starting_ltst))
    return headline, tailtext, printframe


def extract_scan_constants(observations):
    scan = []
    for observation in observations.values():
        scan.append(extract_constants(observation))
    return scan


def reject_scan():
    ASDF_CONSOLE.print(
        "\nhalting due to user rejection of file list. If you didn't see the"
        "products you wanted and you passed an abbreviated path, try passing "
        "a full path instead. If all else fails, try copying the files you "
        "want to work with into a separate directory.",
        style="red bold",
    )
    return None, False


def find_and_offer_observations(
    explicit_path=None,
    dir_from_abbrev=None,
    sol_from_abbrev=None,
    seq_id_from_abbrev=None,
    noninteractive=False,
    keep_broadband=False,
    keep_caltarget=False
):
    """
    process a request for ZCAM files; print the results of the request to
    console; ask the user to select a observation if there is more than one;
    ask the user to confirm the observation if there is only one.
    """
    # TODO: some kind of exception handling for printing console statements
    scan_results, scan_warnings = scan_zcam_dir(
        explicit_path=explicit_path,
        directory=dir_from_abbrev,
        target_sol=sol_from_abbrev,
        target_seq_id=seq_id_from_abbrev,
        keep_broadband=keep_broadband,
        keep_caltarget=keep_caltarget
    )
    if scan_results is None:
        return None, False
    print_scan(scan_results)
    if scan_warnings:
        for problem in scan_warnings:
            ASDF_CONSOLE.print(problem, style="dark_orange bold")
        ASDF_CONSOLE.print("\n")
    if len(scan_results) == 0:
        return None, False
    if noninteractive:
        if (len(scan_results) > 1) and (noninteractive != "a"):
            ASDF_CONSOLE.print(
                "noninteractive mode; using #1. If this isn't the one you "
                "wanted, please run asdf again and explicitly pass a file "
                "from the observation you want."
            )
            return tuple(scan_results.values())[0], False
        if (len(scan_results) > 1) and (noninteractive == "a"):
            ASDF_CONSOLE.print("noninteractive mode; processing all scans.")
            return scan_results, True
        return scan_results, False

    if len(scan_results) > 1:
        obs_choice = Prompt.ask(
            "Please select an observation (0 to exit, a for all)",
            # 1-index for kindness
            choices=[str(ix) for ix in range(len(scan_results) + 1)] + ["a"],
            default="1",
            console=ASDF_CONSOLE,
        )
        if obs_choice == "0":
            return reject_scan()
        if obs_choice != "a":
            return tuple(scan_results.values())[int(obs_choice) - 1], False
        return tuple(scan_results.values()), True
    else:
        if not Confirm.ask(
            "Does this look ok?", default="Y", console=ASDF_CONSOLE
        ):
            return reject_scan()
        return tuple(scan_results.values())[0], False


def wrapped_obs_get(path, noninteractive, debug=False, keep_broadband=False, keep_caltarget=False):
    """
    debug wrapper for find_and_offer_observations
    TODO: probably a cleaner way to do this, like actually swapping out the
      function? maybe not. cost in verbosity.
    """
    if debug:
        return find_and_offer_observations(
            path, noninteractive, keep_broadband=keep_broadband, keep_caltarget=keep_caltarget
        )
    try:
        return find_and_offer_observations(
            path, noninteractive, keep_broadband=keep_broadband, keep_caltarget=keep_caltarget
        )
    except (ValueError, FileNotFoundError) as err:
        raise UserError(err)
    except UserError:
        raise


def ask_user_about_roi(roi_title=None, ci: Callable = pass_parameters) -> dict:
    """
    ask the user about all of the ROI properties we care about, unless
    the application is in noninteractive mode, in which case return our
    null value "-" for all of them.

    :param roi_title: title of the ROI we're asking about -- presently always
        color, but no logical reason it must be
    :param ci: optional wrapper function that suppresses attempts to request
        input. for noninteractive mode.
    """
    roi_metadata = {}
    metadata_fields = list(settings.metadata.ROI_METADATA_FIELDS)
    for field in metadata_fields:
        roi_metadata[field] = ci(dispatched_metadata_prompt, field, roi_title)
    return roi_metadata


def input_roi_metadata(marslab_data, ci):
    for region in marslab_data["COLOR"]:
        ci(
            ASDF_CONSOLE.print,
            Text("Please enter information about the ")
            .append_text(colorize_merspect_roi_name(region))
            .append_text(Text(" ROI.")),
        )
        user_provided_roi_metadata = ask_user_about_roi(region, ci)
        for field, value in user_provided_roi_metadata.items():
            marslab_data.loc[marslab_data["COLOR"] == region, field] = value
    return marslab_data
