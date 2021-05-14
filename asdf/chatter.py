"""
functionality for directly addressing and listening to the user from the
command line goes in this module, including interactive wrappers for scraping
functions, etc.
"""
from pathlib import Path
from typing import Callable

from clize import UserError
import pandas as pd

from asdf.asdf_utils import pass_parameters
from asdf.scrape import find_iof_siblings
import asdf.settings as settings


def name_prompt() -> str:
    """what is the overall name of this observation? tell me."""
    return input(
        " Please enter the name of this observation (press Enter to skip)"
    )


def float_prompt(title=None) -> str:
    """is this a float? tell me."""
    if title is None:
        title = "this"
    else:
        title = "the " + title
    value = "-"
    while value.upper() not in ("Y", "N", ""):
        value = input(
            "    Is the feature associated with "
            + title
            + " ROI a float? (Y/N) (press Enter for N)"
        )
    if value == "":
        value = "N"
    return value.upper()


def generic_metadata_prompt(field_name, title=None) -> str:
    """extremely generic metadata input with no error checking or anything"""
    if title is None:
        title = "this"
    else:
        title = "the " + title
    if field_name == "NAME":
        field_name = "TARGET"
    return input(
        "    Please enter the name of the "
        + field_name
        + " associated with "
        + title
        + " image sequence or ROI. "
        + "(press Enter to skip)"
    )


def dispatched_metadata_prompt(field_name: str, title: str = None) -> str:
    """
    ask user for the value of a metadata field. calls specific functions as
    necessary to provide sensical and grammatically correct prompts
    """
    if field_name.lower() == "float":
        return float_prompt(title)
    # etc., etc., etc.
    return generic_metadata_prompt(field_name, title)


def get_and_offer_pointing(iof_path, noninteractive, binocular):
    """
    look for siblings of the passed IOF and ask the user if the detected
    set is ok.
    """
    pointing = pd.DataFrame(
        find_iof_siblings(iof_path, binocular=binocular)
    ).sort_values(by="FILTER")
    print("Found the following IOFs associated with this pointing:")
    for filt, path in zip(pointing["FILTER"], pointing["PATH"]):
        print(filt, "    ", Path(path).name)
    ok_input = False
    if noninteractive:
        return pointing
    while ok_input is not True:
        ok_input = input("Does this look right? (Y/N) ")
        if ok_input.lower() == "n":
            raise UserError(
                "halting due to user rejection of file list. If you passed an "
                "abbreviated path, try passing a full path instead. You could "
                "also try copying the files you want to work with into their "
                "own subdirectory."
            )
        elif ok_input.lower() == "y":
            ok_input = True
    return pointing


def get_pointing_wrapper(iof_path, noninteractive, binocular, debug=False):
    """
    debug wrapper for get_and_offer_pointing
    TODO: probably a cleaner way to do this, like actually swapping out the
      function? maybe not. cost in verbosity.
    """
    if debug:
        return get_and_offer_pointing(iof_path, noninteractive, binocular)
    try:
        return get_and_offer_pointing(iof_path, noninteractive, binocular)
    except (ValueError, FileNotFoundError) as err:
        raise UserError(err)
    except UserError:
        raise


def ask_user_about_roi(
    fixed_target=None, roi_title=None, ci: Callable = pass_parameters
) -> dict:
    """
    ask the user about all of the ROI properties we care about, unless
    the application is in noninteractive mode, in which case return our
    null value "-" for all of them.

    :param fixed_target: this is a string that defines a single target for
        every ROI so that we don't bother the user. currently set if no ROIs
        or if copy_target is passed.
    :param roi_title: title of the ROI we're asking about -- presently always
        color, but no logical reason it must be
    :param ci: optional wrapper function that suppresses attempts to request
        input. for noninteractive mode.
    """
    roi_metadata = {}
    metadata_fields = list(settings.metadata.ROI_METADATA_FIELDS)
    if fixed_target is None:
        metadata_fields.append("NAME")
    else:
        roi_metadata["NAME"] = fixed_target
    for field in metadata_fields:
        roi_metadata[field] = ci(dispatched_metadata_prompt, field, roi_title)
    return roi_metadata
