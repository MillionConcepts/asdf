import os
import re
from ast import literal_eval
from functools import cache
from pathlib import Path
from types import MappingProxyType
from typing import Callable, Union, Iterable

import asdf_settings

# I don't really know if this is fixed, but I doubt we're ever
# missing anything important if we skim this much off the top
IOF_LABEL_BYTES = 35592

METADATA_REGEX = MappingProxyType(
    {
        field: re.compile(pattern)
        for field, pattern in asdf_settings.metadata.IOF_METADATA_REGEX.items()
    }
)

# metadata necessary for to discrimination of observations and enumeration of
# their members that cannot be derived from the filename
AUX_FIELDS = ("MINI_HEADER", "RMC", "COMPLETION", "FRAME_TYPE", "LTST")

# special-case block finder
SUBFRAME_GROUP = re.compile(r"SUBFRAME.*?END", re.DOTALL)


def scrape_subframe(label_text: str) -> tuple:
    """
    special case -- making a sequence from multiple pvl fields
    in a block. can generalize if necessary. output is:
    first line (row), first line sample (column),
    total lines, total line samples
    if image is not subframed, should be (1, 1, 1200, 1648)
    """
    return literal_eval(
        ",".join(
            re.findall(r"\d+", re.search(SUBFRAME_GROUP, label_text).group())
        )
    )


def scrape_product_id(label_text: str, prefix: str = ""):
    """special case: they put line breaks in these"""

    expression = re.compile(
        r"(?<= " + prefix + r"PRODUCT_ID ).*?(Z.+?)\"", re.M + re.DOTALL
    )
    broken_string = re.search(expression, label_text).group(1)
    return re.sub(r"\s", "", broken_string)


def aux_skim_header(label: Union[Path, str]) -> dict:
    """
    get auxiliary sequencing metadata from a ZCAM file's attached PDS3 header
    """
    label_text = cached_label_loader(label)
    # little closure for neatness
    scrape = make_scraper(label_text)
    skim = {
        field: scrape(pattern)
        for field, pattern in METADATA_REGEX.items()
        if field in AUX_FIELDS
    }
    skim["RMS"] = skim["RMC"][6]
    return skim


def make_scraper(label_text: str) -> Callable:
    """
    makes a little function that scrapes a particular text for patterns
    """

    def scrape(pattern):
        result = re.search(pattern, label_text)
        if result is None:
            return None
        try:
            return literal_eval(result.group(1))
        except (ValueError, SyntaxError):
            return result.group(1)

    return scrape


def get_label_text(label: Union[Path, str]) -> str:
    """
    why not overload the label-getter? literally no reason
    """
    if isinstance(label, str):
        label = Path(label)
    with open(label, "rb") as file:
        return file.read(IOF_LABEL_BYTES).decode()


# cached versions for faster operation on networked filesystems.
cached_label_loader = cache(get_label_text)
cached_aux_skimmer = cache(aux_skim_header)


@cache
def scrape_from_file(label, pattern):
    return make_scraper(cached_label_loader(label))(pattern)


@cache
def is_iof_est_heuristic(label):
    return "SCALING" not in cached_label_loader(label)


@cache
def scrape_asdf_metadata(label: Union[Path, str]) -> dict:
    """
    grabs all the metadata from an IOF header that asdf cares about.
    cached by default.
    """
    label_text = cached_label_loader(label)
    # little closure for neatness
    scrape = make_scraper(label_text)
    # general-case fields
    metadata = {
        field: scrape(pattern) for field, pattern in METADATA_REGEX.items()
    }
    # special cases
    metadata["SUBFRAME"] = scrape_subframe(label_text)
    metadata["IOF_FILE"] = Path(label).name
    metadata["INPUT_PRODUCT_ID"] = scrape_product_id(label_text, "INPUT_")
    metadata["INSTRUMENT"] = "ZCAM"
    return metadata


def bulk_scrape_metadata(iof_files: Iterable) -> list[dict]:
    """
    scrapes all the asdf metadata from all the files you pass it, and
    that's that
    """
    metaframe = []
    for iof in iof_files:
        metaframe.append(scrape_asdf_metadata(iof))
    return metaframe


# cached filesystem functions for execution speed on networked filesystems
cached_ls = cache(os.listdir)
cached_exists = cache(os.path.exists)


@cache
def is_pixel_map_heuristic(putative_pixmap_path):
    """
    TODO: determine if they are the actually only ones that even mention this
     identifier
    """
    return "PIXEL_MAP" in get_label_text(putative_pixmap_path)
