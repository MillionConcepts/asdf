"""
functions for actively scraping metadata from input files, web sources, etc.
"""

import os
import re
from ast import literal_eval
from pathlib import Path
from types import MappingProxyType
from typing import Union, Mapping, Callable, Iterable
from urllib.error import URLError

import numpy as np
import pandas as pd
from cytoolz.curried import keyfilter
from marslab.compat.xcam import piecewise_interpolate_focal_length

from asdf.network import get_public_m20_waypoints
import asdf.settings as settings

METADATA_REGEX = MappingProxyType(
    {
        field: re.compile(pattern)
        for field, pattern in settings.metadata.IOF_METADATA_REGEX_STRINGS.items()
    }
)

# fields relevant to discrimination of pointings and enumeration of their
# primary members
POINTING_FIELDS = (
    "MINI_HEADER",
    "RMC",
    "SEQ_ID",
    "SOL",
    "FILTER",
    "COMPLETION",
)

# special-case block finder
SUBFRAME_GROUP = re.compile(r"SUBFRAME.*?END", re.DOTALL)

# I don't really know if this is fixed, but I doubt we're ever
# missing anything important if we skim this much off the top
IOF_LABEL_BYTES = 35592

# note: all these scrape functions could plausibly be sped up a little by
# iterating line-by-line, applying them en bloc to each line, and popping
# them out of the bloc once they match -- but this is probably not worth the
# effort


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


def parse_pointing(sequence: Union[Mapping, pd.DataFrame]) -> dict:
    """
    basically a parsing rule: grab the subset of pointing-discriminating
    fields from a dict of metadata. pointings are basically equivalence
    relations: every product with these values for these fields
    is in the same pointing, no product that does not have these
    values for these fields is in that pointing. the relaxed "binocular"
    version of this allows RMS to differ for for observations in which
    the mast moves in the middle of a sequence to coregister eyes on the
    same target.
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
        "ZOOM": piecewise_interpolate_focal_length(row["MINI_HEADER"][2]),
    }


def make_pointing_name(pointing):
    pointing_name = "_".join(
        [
            key + str(value)
            for key, value in parse_pointing(pointing.iloc[0]).items()
        ]
    )
    pointing_name = pointing_name.replace("SEQ_ID", "SEQID")
    pointing_name = pointing_name.replace(".", "_")
    return pointing_name


def drop_mismatched_versions(sibling_df, base_version):
    # these are absolute paths and not base names and we don't translate them
    # here, so slicing backwards
    version_ix = (-6, -4)
    version_series = sibling_df["PATH"].str.slice(*version_ix).astype(int)
    for filter_name in sibling_df["FILTER"].unique():
        filter_slice = sibling_df.loc[sibling_df["FILTER"] == filter_name]
        if len(filter_slice) == 1:
            continue
        version_slice = version_series[filter_slice.index]
        if base_version in version_slice.values:
            target_version = base_version
        else:
            target_version = version_slice.max()
        sibling_df.drop(
            version_slice.loc[version_slice.values != target_version].index,
            inplace=True,
        )
    return sibling_df


def find_iof_siblings(
    path_to_iof: str, override_names=False, binocular=False
) -> pd.DataFrame:
    # TODO: make sure RMS propagates into extended even if binocular
    base_iof = Path(path_to_iof)
    # don't scrape thumbnails
    # TODO: scrape thumbnails
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
    base_sequence_dict["PATH"] = str(path_to_iof)
    base_pointing = parse_pointing(base_sequence_dict)
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
        pointing = parse_pointing(sequence_dict)
        if binocular:
            # permit coregistered binocular observations with different
            # RMS to be defined as a single pointing
            no_rms = keyfilter(lambda key: key != "RMS")
            pointings_are_equal = no_rms(pointing) == no_rms(base_pointing)
        else:
            pointings_are_equal = pointing == base_pointing
        if pointings_are_equal:
            # if it's cool save the info
            sequence_dict["PATH"] = str(potential_sibling)
            siblings.append(sequence_dict)
    sibdf = pd.DataFrame(siblings)
    # rectify version numbers
    versioned = drop_mismatched_versions(sibdf, base_version)
    if not any(versioned["FILTER"].duplicated()):
        return versioned
    # perhaps not a binocular observation after all? check this possiblity..
    if binocular:
        print(
            "Warning: asdf found too many images for this seq_id and is "
            "falling back to strict mode. This may mean that a sequence "
            "that includes a mast movement was executed several times during "
            "this sol. It may also not mean that. If you don't see all the "
            "images you want, try copying the specific files you want "
            "into a separate directory and running asdf on them there."
        )
        return find_iof_siblings(path_to_iof, override_names, binocular=False)
    else:
        raise ValueError(
            "There are multiple pointings in this directory that, for whatever"
            " reason, I can't distinguish. Try pulling the files you want to"
            " use into another directory. If you passed an abbreviated path,"
            " try passing a full path instead."
        )


def bulk_scrape_metadata(iof_files: Iterable) -> list[dict]:
    """
    scrapes all the asdf metadata from all the files you pass it, and
    that's that
    """
    metaframe = []
    for iof in iof_files:
        metaframe.append(scrape_asdf_metadata(iof))
    return metaframe


def melt_metadata(metadata: pd.DataFrame, unpivot="BAND") -> pd.DataFrame:
    """
    unpivot a metadata frame by key (default BAND), for appending per-file
    metadata to the extended marslab format
    """
    unchanging_columns = (
        "SOL",
        "SEQ_ID",
        "INSTRUMENT",
        "LAT",
        "LON",
        "ODOMETRY",
        "ROVER_ELEVATION",
        "CREATOR",
    )
    uc_here = [col for col in unchanging_columns if col in metadata.columns]
    unchanging_block = metadata.reindex(columns=uc_here)
    melted = metadata.drop(columns=uc_here)
    melted = melted.melt(unpivot).T
    melted.columns = melted.loc[unpivot] + "_" + melted.loc["variable"]
    melted = (
        melted.drop([unpivot, "variable"])
        .reset_index(drop=True)
        .sort_index(axis=1)
    )
    return pd.DataFrame(
        pd.concat([unchanging_block.loc[0], melted.loc[0]], axis=0)
    ).T


def matching_waypoints(site, drive, m20_waypoint_dict):
    """
    I don't think the waypoints are defined more granularly than site and
    drive.
    """
    return [
        feature
        for feature in m20_waypoint_dict
        if (int(feature["properties"]["site"]) == int(site))
        and (int(feature["properties"]["drive"]) == int(drive))
    ]


def associate_waypoints(metadata, m20_waypoint_dict):
    pointing = parse_pointing(metadata)
    matches = matching_waypoints(
        pointing["SITE"], pointing["DRIVE"], m20_waypoint_dict
    )
    if len(matches) == 1:
        match = matches[0]
        try:
            # trying various formats they switch without notice
            metadata["ROVER_ELEVATION"] = match["properties"]["elev_geoid"]
            metadata["ODOMETRY"] = match["properties"]["dist_total_m"]
            metadata["LAT"] = match["geometry"]["coordinates"][1]
            metadata["LON"] = match["geometry"]["coordinates"][0]
        except KeyError:
            try:
                for meta_field, waypoint_field in (
                    ("LAT", "lat"),
                    ("LON", "lon"),
                    ("ROVER_ELEVATION", "elev_geoid"),
                    ("ODOMETRY", "dist_total"),
                ):
                    metadata[meta_field] = match["properties"][waypoint_field]
            except KeyError:
                print(
                    "The public waypoint sheet has changed formats again; I "
                    "don't understand this one. Not adding localization data."
                )

        return metadata
    if len(matches) == 0:
        print(
            "No matching waypoints in this JSON file. Not adding localization "
            "data."
        )
    elif len(matches) > 1:
        print(
            "Multiple matching waypoints in this JSON file. Weird! Not adding "
            "localization data."
        )
    return metadata


def add_public_waypoints_to_metadata(metadata):
    # TODO: add a timeout
    try:
        m20_waypoint_dict = get_public_m20_waypoints()
    except (ValueError, URLError) as e:
        print(str(e) + " ; not adding waypoints to metadata")
        return metadata
    return associate_waypoints(metadata, m20_waypoint_dict)


def add_effective_taus(metadata):
    if "TAU_ESTIMATE_FILENAME" not in metadata.columns:
        return metadata
    if len(metadata["TAU_ESTIMATE_FILENAME"].dropna()) == 0:
        return metadata
    stringified_taus = []
    for taufile in metadata["TAU_ESTIMATE_FILENAME"]:
        taupath = settings.sources.EFFECTIVE_TAU_PATH + taufile
        if not os.path.exists(taupath):
            stringified_taus.append(np.nan)
        else:
            stringified_taus.append(
                ",".join(
                    pd.read_csv(taupath, header=None).values[0].astype(str)
                )
            )
    if len(pd.Series(stringified_taus).dropna()) == 0:
        return metadata
    print("One or more effective tau files found, recording values.")
    metadata["EFFECTIVE_TAUS"] = stringified_taus
    return metadata


def add_derived_illumination_geometry(metadata):
    """
    derive canonical incidence, emission, and phase angles from other metadata
    fields. see Shepherd et al. 2008, Rice et al. 2020, Rice 2021 (p.comm.)
    """
    incidence_angle = metadata["SOLAR_ELEVATION"] - 90
    emission_angle = metadata["INSTRUMENT_ELEVATION"] + 90

    incidence_azimuth = metadata["SOLAR_AZIMUTH"]
    emission_azimuth = metadata["INSTRUMENT_AZIMUTH"] + 180
    # angle between the projection of the incidence vector and the emission
    # vector on the surface
    delta_phi = abs(
        np.radians(incidence_azimuth) - np.radians(emission_azimuth)
    )
    # just converting to radians for neatness in subsequent expression
    theta_i = np.radians(incidence_angle)
    theta_e = np.radians(emission_angle)
    cos_phase = np.cos(theta_i) * np.cos(theta_e) + np.sin(theta_i) * np.sin(
        theta_e
    ) * np.cos(delta_phi)
    phase_angle = np.degrees(np.arccos(cos_phase))
    for field, variable in zip(
        [
            "INCIDENCE_ANGLE",
            "INCIDENCE_AZIMUTH",
            "EMISSION_ANGLE",
            "EMISSION_AZIMUTH",
            "PHASE_ANGLE",
        ],
        [
            incidence_angle,
            incidence_azimuth,
            emission_angle,
            emission_azimuth,
            phase_angle,
        ],
    ):
        metadata[field] = variable
    return metadata
