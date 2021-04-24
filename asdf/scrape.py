import re
from pathlib import Path
from ast import literal_eval
from types import MappingProxyType
from typing import Union, Mapping, Callable, Any, Iterable

from marslab.compat.xcam import ZCAM_ZOOM_MOTOR_COUNT_TO_FOCAL_LENGTH
import pandas as pd


# regexes for yoinking label data from IOFs without parsing the PVL
IOF_METADATA_REGEX_STRINGS = MappingProxyType(
    {
        # the zoom motor count seems to be given several places in the label --
        # but the malin mini header line has other interesting contents
        "MINI_HEADER": r"(?<=ARTICULATION_DEV_POSITION ).*(\(.*\))",
        "RMC": r"(?<=ROVER_MOTION_COUNTER ).*(\(.*\))",
        "SEQ_ID": r"(?<=SEQUENCE_ID).*(zcam\d+)",
        "SOL": r"(?<=PLANET_DAY_NUMBER).*(\d+)",
        "FILTER": r"FILTER_NAME.*ZCAM_([LR][\w\d])(?=_)",
        "IMAGE_TIME": r"(?<=IMAGE_TIME ).*?([\d\-T:]+)",
        "LTST": r"(?<=LOCAL_TRUE_SOLAR_TIME ).*?([\d:]+)",
        "PRODUCT_CREATION_TIME": r"(?<=PRODUCT_CREATION_TIME ).*?([\d\-T:]+)",
        "L_S": r"(?<=SOLAR_LONGITUDE ).*?([\d\.]+)",
        "COMPRESSION": r"(?<=INST_CMPRS_NAME ).*?(\w+)",
        "BAYER": r"(?<=BAYER_METHOD ).*?([\w_]+)",
        "SOLAR_ELEVATION": r"(?<=SOLAR_ELEVATION ).*?([\d\.]+)",
        # note: starting sclk only
        "SCLK": r"(?<=SPACECRAFT_CLOCK_START_COUNT ).*?([\d\.]+)",
        "COMPLETION": r"(?<=PRODUCT_COMPLETION_STATUS ).*?([\w_]+)"
    }
)

# view of compiled regexes from that dict
METADATA_REGEX = MappingProxyType(
    {
        field: re.compile(pattern)
        for field, pattern in IOF_METADATA_REGEX_STRINGS.items()
    }
)

# fields relevant to discrimination of pointings and enumeration of their
# primary members
POINTING_FIELDS = ("MINI_HEADER", "RMC", "SEQ_ID", "SOL", "FILTER", "COMPLETION")

# special-case block finder
SUBFRAME_GROUP = re.compile(r"SUBFRAME.*?END", re.DOTALL)

# I don't really know if this is fixed, but I doubt we're ever
# missing anything important if we skim this much off the top
IOF_LABEL_BYTES = 35592

# note: all these scrape functions could plausibly be sped up a little by
# iterating line-by-line, applying them en bloc to each line, and popping
# them out of the bloc once they match -- but this is probably not worth the
# effort


def make_scraper(label_text: str) -> Callable[[Union[str, re.Pattern]], Any]:
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


def scrape_subframe(label_text: str) -> tuple:
    """
    a bit of a special case -- making a sequence from multiple pvl fields
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


def scrape_sequence_dict(label: Union[Path, str]) -> dict:
    """
    scrape sequence-relevant information from an IOF file's attached
    PDS3 header without parsing PVL
    """
    label_text = get_label_text(label)
    # little closure for neatness
    scrape = make_scraper(label_text)
    return {
        field: scrape(pattern)
        for field, pattern in METADATA_REGEX.items()
        if field in POINTING_FIELDS
    }


def scrape_asdf_metadata(label: Union[Path, str]) -> dict:
    """
    grabs all the metadata from an IOF file that asdf cares about.
    perhaps a little redundant.
    """
    label_text = get_label_text(label)
    # little closure for neatness
    scrape = make_scraper(label_text)
    # general-case fields
    metadata = {
        field: scrape(pattern) for field, pattern in METADATA_REGEX.items()
    }
    # special cases
    metadata["SUBFRAME"] = scrape_subframe(label_text)
    metadata["IOF_FILE"] = Path(label).name
    metadata["INSTRUMENT"] = "ZCAM"
    return metadata


def pointing_from_sequence(sequence: Union[Mapping, pd.DataFrame]) -> dict:
    """
    basically a parsing rule: grab the subset of pointing-discriminating
    fields from a dict of metadata. recall: pointings are equivalence
    relations.
    every product with these values for these fields is in a pointing. no
    product that does not have these values for these fields is in that
    pointing. every product is in the same pointing as itself.
    """
    row = sequence
    if isinstance(sequence, pd.DataFrame):
        row = sequence.iloc[0]
    return {
        "SITE": row["RMC"][0],
        "DRIVE": row["RMC"][1],
        "RMS": row["RMC"][6],
        "SOL": row["SOL"],
        "SEQ_ID": row["SEQ_ID"],
        "ZOOM": ZCAM_ZOOM_MOTOR_COUNT_TO_FOCAL_LENGTH[
            row["MINI_HEADER"][2]
        ],
    }


def make_pointing_name(pointing):
    pointing_name = "_".join(
        [
            key + str(value)
            for key, value in pointing_from_sequence(pointing.iloc[0]).items()
        ]
    )
    return pointing_name


def drop_mismatched_versions(sibling_df, base_version):
    # these are absolute paths and not base names and we don't translate them
    # here, so slicing backwards
    version_ix = (-6, -4)
    version_series = sibling_df["PATH"].str.slice(*version_ix).astype(int)
    for filter_name in sibling_df['FILTER'].unique():
        filter_slice = sibling_df.loc[sibling_df['FILTER'] == filter_name]
        if len(filter_slice) == 1:
            continue
        version_slice = version_series[filter_slice.index]
        if base_version in version_slice.values:
            target_version = base_version
        else:
            target_version = version_slice.max()

        sibling_df.drop(
            version_slice.loc[version_slice.values != target_version].index,
            inplace=True
        )
    return sibling_df


def find_iof_siblings(path_to_iof: str, override_names=False) -> pd.DataFrame:
    base_iof = Path(path_to_iof)
    # don't scrape thumbnails
    if "IOF_N" not in base_iof.name:
        if not override_names:
            raise ValueError("This filename doesn't look like an IOF file's.")
    # indices containing unique string for site, drive, seq_id -- we don't
    # care about actually parsing it
    sitedriveseq_ix = (28, 44)
    # this generates an identifier that significantly narrows down
    # potential 'pointings'
    base_sitedriveseq = base_iof.name[slice(*sitedriveseq_ix)]
    # matching version numbers is also desirable
    version_ix = (52, 54)
    base_version = int(base_iof.name[slice(*version_ix)])
    # and then to fully specify
    base_sequence_dict = scrape_sequence_dict(base_iof)
    if base_sequence_dict.pop("COMPLETION") != "COMPLETE_CHECKSUM_PASS":
        raise ValueError(
            "asdf does not currently support partially-received images."
        )
    base_sequence_dict["PATH"] = path_to_iof
    base_pointing = pointing_from_sequence(base_sequence_dict)
    siblings = [base_sequence_dict]
    for potential_sibling in base_iof.parent.iterdir():
        if (potential_sibling.name == base_iof.name) or (
            "IOF_N" not in potential_sibling.name
        ):
            continue
        # does it have the same site, drive, seq?
        if (
            potential_sibling.name[slice(*sitedriveseq_ix)]
            != base_sitedriveseq
        ):
            continue
        # ok then actually look at the label
        sequence_dict = scrape_sequence_dict(potential_sibling)
        if sequence_dict.pop("COMPLETION") != "COMPLETE_CHECKSUM_PASS":
            continue
        pointing = pointing_from_sequence(sequence_dict)
        if pointing == base_pointing:
            # if it's cool save the info
            sequence_dict["PATH"] = str(potential_sibling)
            siblings.append(sequence_dict)
    sibdf = pd.DataFrame(siblings)
    # rectify version numbers
    return drop_mismatched_versions(sibdf, base_version)


def bulk_scrape_metadata(iof_files: Iterable) -> list[dict]:
    """
    scrapes all the asdf metadata from all the files you pass it, and
    that's that
    """
    metaframe = []
    for iof in iof_files:
        metaframe.append(scrape_asdf_metadata(iof))
    return metaframe
