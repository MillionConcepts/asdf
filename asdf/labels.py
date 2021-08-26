"""specialty ZCAM/isla-specific additions to generic label-scraping tools"""

import re
from functools import cache, partial
from pathlib import Path
from types import MappingProxyType
from typing import Union

from dustgoggles.scrape import (
    bulk_scrape_metadata,
    cached_label_loader,
    get_label_text,
    make_scraper,
    scrape_subframe,
    scrape_patterns,
)

import asdf_settings


ASDF_METADATA_REGEX = MappingProxyType(
    {
        field: re.compile(pattern)
        for field, pattern in asdf_settings.metadata.IOF_METADATA_REGEX.items()
    }
)

# metadata necessary for to discrimination of observations and enumeration of
# their members that cannot be derived from the filename
AUX_FIELDS = ("MINI_HEADER", "RMC", "COMPLETION", "FRAME_TYPE", "LTST")


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
        for field, pattern in ASDF_METADATA_REGEX.items()
        if field in AUX_FIELDS
    }
    skim["RSM"] = skim["RMC"][6]
    return skim


# cached versions for faster operation on networked filesystems.
cached_aux_skimmer = cache(aux_skim_header)


@cache
def is_iof_est_heuristic(label):
    return "SCALING" not in cached_label_loader(label)


@cache
def supplemental_scraper(label, label_text):
    # special cases
    return {
        "SUBFRAME": scrape_subframe(label_text),
        "IOF_FILE": Path(label).name,
        "INPUT_PRODUCT_ID": scrape_product_id(label_text, "INPUT_"),
        "INSTRUMENT": "ZCAM",
    }


scrape_asdf_metadata = cache(
    partial(
        scrape_patterns,
        metadata_regex=ASDF_METADATA_REGEX,
        supplemental_search_function=supplemental_scraper,
    )
)


bulk_scrape_asdf_metadata = partial(
    bulk_scrape_metadata, pattern_scraper=scrape_asdf_metadata
)


@cache
def is_pixel_map_heuristic(putative_pixmap_path):
    """
    TODO: determine if they are the actually only ones that even mention this
     identifier
    """
    return "PIXEL_MAP" in get_label_text(putative_pixmap_path)
