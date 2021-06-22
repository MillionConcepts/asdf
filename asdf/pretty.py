"""
CLI infrastructure that does not notionally consist of shared objects goes
in this module
"""

import os.path
from types import MappingProxyType

import pandas as pd
from rich.highlighter import Highlighter
from rich.prompt import PromptBase, Prompt, Confirm
from rich.table import Table
from rich.text import Text

from asdf.asdf_utils import extract_constants
from asdf.console import aprint, ASDF_CONSOLE
from asdf.settings.metadata import (
    ROI_METADATA_FIELD_PROMPTS,
    ROI_METADATA_FIELD_CHOICES,
)
from marslab.compat.mertools import MERSPECT_M20_COLOR_MAPPINGS


def style_prog(rich_progress, style):
    rich_progress.style = style
    for column in rich_progress.columns:
        if "style" in dir(column):
            column.style = style
        if "spinner" in dir(column):
            column.spinner.style = style
        if "spinners" in dir(column):
            for spinner in column.spinners:
                spinner.style = style


class NumberedChoicePrompt(PromptBase):
    """prompt type for our enumerated shortcut ROI prompts"""

    def __init__(self, *args, skippable=True, **kwargs):
        super().__init__(*args, **kwargs)
        choices = kwargs.get("choices")
        if choices is None:
            raise ValueError(
                "A NumberedChoicePrompt must be initialized with at least one "
                "choice."
            )
        self.choices = [str(ix + 1) for ix in range(len(choices))]
        self.choice_lookup = choices
        self.skippable = skippable

    show_choices = False

    def make_prompt(self, default):
        numbered_choices = []
        for ix, choice in enumerate(self.choice_lookup):
            # convert to 1-indexing for readability
            numbered_choices.append("({}) {}".format(str(ix + 1), choice))
        prompt = self.prompt.copy()
        prompt_choices = " " + ", ".join(numbered_choices)
        if self.skippable is True:
            prompt_choices += " (press Enter to skip):"
        return prompt + prompt_choices

    def process_response(self, value: str):
        if (value.strip()) == "" and (self.skippable is True):
            return ""
        value = super().process_response(value)
        # convert back to 0-indexing
        return self.choice_lookup[int(value) - 1]


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
            elif section in ["ptype", "producer"]:
                text.stylize("magenta1", *slice_ix)


def format_roi_title(roi_title):
    prompt_text = Text()
    if roi_title is not None:
        prompt_text.append("the ")
        prompt_text.append(colorize_merspect_roi_name(roi_title))
    else:
        prompt_text.append("this / these")
    return prompt_text


def name_prompt() -> str:
    """what is the overall name of this observation? tell me."""
    prompt_text = Text("Please enter the ")
    prompt_text.append_text(Text("name ", style="bold orchid1"))
    prompt_text.append_text(Text("of this observation."))
    return Prompt.ask(prompt_text, console=ASDF_CONSOLE)


def y_n_prompt(prompt_text, title=None):
    """generate and perform Y/N prompts"""
    texts = prompt_text.split("{title}")
    title = format_roi_title(title)
    formatted_text = texts[0].append_text(title).append_text(texts[1])
    value = Confirm.ask(formatted_text, default=False, console=ASDF_CONSOLE)
    if value is True:
        return "Y"
    return "N"


def colorize_merspect_roi_name(roi_color_name=None):
    roi_color_hex = MERSPECT_M20_COLOR_MAPPINGS.get(roi_color_name)
    if roi_color_hex is None:
        return Text(roi_color_name, style="bold white")
    return Text(roi_color_name, style="bold " + roi_color_hex)


def generic_metadata_prompt_text(field, title):
    """
    fallback text for ROI metadata field prompts that don't have
    specified text in settings.metadata.ROI_METADATA_FIELD_PROMPTS
    """
    prompt_text = Text.from_markup(
        "What is the [bold]{}[/] value of ".format(field)
    ).append_text(format_roi_title(title) + " ROI(s)? (press Enter to skip)")
    return prompt_text


def format_metadata_prompt(text, field, title):
    text = Text(text).split("{title}")
    text = text[0].append_text(format_roi_title(title)).append_text(text[1])
    text = text.split("{field}")
    return text[0].append_text(Text(field, style="bold")).append_text(text[1])


def metadata_choice_prompt(text, choices) -> str:
    """metadata input with numerically-keyed choices"""
    return NumberedChoicePrompt.ask(
        text, choices=choices, console=ASDF_CONSOLE
    )


def metadata_open_prompt(text) -> str:
    """free metadata input with no error checking or anything"""
    return Prompt.ask(text, console=ASDF_CONSOLE)


def dispatched_metadata_prompt(field: str, title: str = None) -> str:
    """
    ask user for the value of a metadata field. calls specific functions as
    necessary to provide sensical and grammatically correct prompts
    """
    if field.upper() in ROI_METADATA_FIELD_PROMPTS.keys():
        text = format_metadata_prompt(
            ROI_METADATA_FIELD_PROMPTS[field.upper()], field, title
        )
    else:
        text = generic_metadata_prompt_text(field, title)
    if field.upper() in ROI_METADATA_FIELD_CHOICES.keys():
        return metadata_choice_prompt(
            text, ROI_METADATA_FIELD_CHOICES[field.upper()]
        )
    return metadata_open_prompt(text)


def format_observation(observation: pd.DataFrame):
    constant_dict, filterframe = extract_constants(observation)
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
        tailtext.append("contains partial(s)", style="dark_orange")
    if constant_dict.get("THUMBNAIL") in ["T", "Y"]:
        tailtext.append(", ")
        tailtext.append("thumbnails", style="dark_orange")
    headline_keys = ["SOL", "SEQ_ID", "SITE", "DRIVE"]

    headline = Text(
        ", ".join(
            key + " " + str(constant_dict.get(key)) for key in headline_keys
        )
    )

    if constant_dict.get("LTST"):  # single simultaneous stereo pair case
        starting_ltst = constant_dict["LTST"]
    else:
        starting_ltst = filterframe["LTST"].iloc[0]
    tailtext.append(", starting LTST " + str(starting_ltst))
    return headline, tailtext, printframe


def print_observation(observation, ix=0, is_multiple=False):
    headline, tailtext, printframe = format_observation(observation)
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
    aprint(table)
    aprint("\n")


def print_scan_results(results):
    aprint("\n")
    if len(results) == 0:
        return
    if len(results) > 1:
        is_multiple = True
        aprint(
            "found {} observations (ordered by seq_id / "
            "chronologically within seq_ids):".format(len(results)),
        )
    else:
        is_multiple = False
        aprint("found 1 observation:")
    aprint("\n")
    for ix, observation in enumerate(results.values()):
        print_observation(observation, ix, is_multiple)
