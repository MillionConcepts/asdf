"""specialty ZCAM/isla-specific additions to generic label-scraping tools"""

import re
from functools import cache
from pathlib import Path
from typing import Mapping, Union

import pdr
from dustgoggles.scrape import (
    get_label_text, cached_label_loader, make_scraper, scrape_subframe,
)

from asdf_settings.metadata import IOF_METADATA_FIELDS


def keygetter(mapping, keys):
    for key in keys:
        mapping = mapping[key]
    return mapping


def dequantizer(value):
    """
    pdr.parselabel.pds3 parses pvl quantities into dicts. if we find ourselves
    with a dict, take its 'value' key.
    """
    if isinstance(value, dict):
        return value['value']
    return value


def scrape_field(metadata, field):
    if isinstance(field, str):
        return dequantizer(metadata.metaget(field))
    else:
        value = dequantizer(keygetter(metadata, field['keys']))
    if 'regex' not in field.keys():
        return value
    return re.search(field['regex'], value).group(0)


def assemble_subframe(scraped: dict) -> dict:
    fields = ("FIRST_LINE", "FIRST_LINE_SAMPLE", "LINES", "LINE_SAMPLES")
    subframe = []
    for field in fields:
        subframe.append(int(scraped.pop(field)))
    scraped["SUBFRAME"] = tuple(subframe)
    return scraped


def pluck_rsm(scraped: dict) -> dict:
    scraped["RSM"] = scraped["RMC"][6]
    return scraped


def auxiliary_asdf_metadata_polisher(scraped: dict) -> dict:
    polishing_functions = (assemble_subframe, pluck_rsm)
    for func in polishing_functions:
        scraped = func(scraped)
    return scraped


def scrape_asdf_metadata(
    metadata: "pdr.Metadata", field_specifications: Mapping
) -> dict:
    scraped = {
        field_name: scrape_field(metadata, field_specification)
        for field_name, field_specification in field_specifications.items()
    }
    return auxiliary_asdf_metadata_polisher(scraped)


def bulk_scrape_asdf_metadata(
    data_cache: Mapping[str, "pdr.Data"]
) -> list[dict]:
    bulk_scraped = []
    for path, data in data_cache.items():
        scraped = scrape_asdf_metadata(data.metadata, IOF_METADATA_FIELDS)
        scraped["PATH"] = path
        scraped["IOF_FILE"] = Path(path).name
        bulk_scraped.append(scraped)
    return bulk_scraped


def get_pixel_map_heuristic(putative_pixmap_path):
    data = pdr.read(putative_pixmap_path)
    if data.metaget("PIXEL_MAP_VALUES") is not None:
        return data
    return None


"""
pure text-parsing based 'skimmer' functions for speed and stability on 
networked filesystems.
"""

SKIMMER_REGEX = {
    "MINI_HEADER": r"(?<=ARTICULATION_DEV_POSITION ).*(\(.*\))",
    "RMC": r"(?<=ROVER_MOTION_COUNTER ).*(\(.*\))",
    "COMPLETION": r"(?<=PRODUCT_COMPLETION_STATUS ).*?([\w_]+)",
    "FRAME_TYPE": r"(?<=FRAME_TYPE ).*?(\w+)",
    "LTST": r"(?<=LOCAL_TRUE_SOLAR_TIME ).*?([\d:]+)",
}


def aux_skim_header(label: Union[Path, str]) -> dict:
    """
    get auxiliary sequencing metadata from a ZCAM file's attached PDS3 header
    """
    label_text = cached_label_loader(label)
    # little closure for neatness
    scrape = make_scraper(label_text)
    skim = {
        field: scrape(pattern) for field, pattern in SKIMMER_REGEX.items()
    }
    # for labels with (overflow?) line breaks
    # TODO: is this multiline rep dangerous?
    if skim.get("RMC") is None:
        skim["RMC"] = scrape(
            r"(?<=ROVER_MOTION_COUNTER ).*(\((?:.|\n)+?\))"
        )
    skim["RSM"] = skim["RMC"][6]
    skim["SUBFRAME"] = scrape_subframe(label_text)
    return skim


# cached versions for faster operation on networked filesystems.
cached_aux_skimmer = cache(aux_skim_header)