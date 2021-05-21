"""
functions for actively scraping metadata from input files, web sources, etc.
"""
from functools import cache
import os
import re
from ast import literal_eval
from pathlib import Path
from types import MappingProxyType
from typing import Union, Mapping, Callable, Iterable
from urllib.error import URLError

from cytoolz.functoolz import juxt
from cytoolz.itertoolz import partition

import marslab.parse as mp
from asdf.console import ASDF_CONSOLE
from marslab.compat.xcam import piecewise_interpolate_focal_length
import numpy as np
import pandas as pd

from asdf.network import get_public_m20_waypoints
import asdf.settings as settings


METADATA_REGEX = MappingProxyType(
    {
        field: re.compile(pattern)
        for field, pattern in settings.metadata.IOF_METADATA_REGEX_STRINGS.items()
    }
)

# metadata necessary for to discrimination of observations and enumeration of
# their members that cannot be derived from the filename
AUX_FIELDS = ("MINI_HEADER", "RMC", "COMPLETION", "FRAME_TYPE", "LTST")

# special-case block finder
SUBFRAME_GROUP = re.compile(r"SUBFRAME.*?END", re.DOTALL)

# I don't really know if this is fixed, but I doubt we're ever
# missing anything important if we skim this much off the top
IOF_LABEL_BYTES = 35592


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


def aux_skim_header(label: Union[Path, str]) -> dict:
    """
    get auxiliary sequencing metadata from a ZCAM file's attached PDS3 header
    """
    label_text = get_label_text(label)
    # little closure for neatness
    scrape = make_scraper(label_text)
    skim = {
        field: scrape(pattern)
        for field, pattern in METADATA_REGEX.items()
        if field in AUX_FIELDS
    }
    skim["RMS"] = skim["RMC"][6]
    return skim


# cached version for faster operation on networked filesystems.
cached_aux_skimmer = cache(aux_skim_header)


# similar, slightly experimental
@cache
def scrape_from_file(label, pattern):
    return make_scraper(get_label_text(label))(pattern)


def scrape_asdf_metadata(label: Union[Path, str]) -> dict:
    """
    grabs all the metadata from an IOF header that asdf cares about.
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
        "SEQ_ID": row["SEQ_ID"].lower(),  # TODO: does this break anything?
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


def drop_mismatched_versions(siblings, base_version=None):
    if len(siblings["VERSION"].unique()) == 1:
        return siblings
    if base_version is None:
        base_version = siblings["VERSION"].max()
    dupes = siblings.loc[siblings["FILTER"].duplicated(keep=False)]
    for filter_name in dupes["FILTER"].unique():
        filter_slice = siblings.loc[siblings["FILTER"] == filter_name]
        if base_version in filter_slice["VERSION"].values:
            target_version = base_version
        else:
            target_version = filter_slice["VERSION"].max()
        siblings.drop(
            filter_slice.loc[filter_slice["VERSION"] != target_version].index,
            inplace=True,
        )
    return siblings


def parse_zcam_fn(filename):
    """use mp.parse rules to get basic file identifiers"""
    parsers = {
        "SOL": mp.sol,
        "SITE": mp.site,
        "DRIVE": mp.drive,
        "SEQ_ID": mp.sequence,
        "CTIME": mp.secondary_timestamp,
        "ZOOM": mp.cam_specific,
        "FILTER": mp.color_filter,
        "VERSION": mp.version,
        "PRODUCT_TYPE": mp.product_type,
        "THUMBNAIL": mp.thumbnail,
    }
    values = list(juxt(*parsers.values())(filename))
    # chop off currently not-used-as-specified stereo counter
    values[5] = values[5][1:]
    # just keep filter name, not SIS-nominal wavelength
    values[6] = values[6][:2]
    return {field: value for field, value in zip(parsers.keys(), values)}


def skim_products(directory, aux_skimmer=cached_aux_skimmer):
    products = tuple(
        map(parse_zcam_fn, [path.name for path in directory.iterdir()])
    )
    products = pd.DataFrame(products)
    products["PATH"] = [str(path) for path in directory.iterdir()]
    products = (
        pd.DataFrame(products).sort_values(by="CTIME").reset_index(drop=True)
    )
    return pd.concat(
        (
            products.drop("PATH", axis=1),
            pd.DataFrame(products["PATH"].map(aux_skimmer).tolist()),
            products["PATH"],
        ),
        axis=1,
    )


def scan_zcam_dir(
    explicit_path: Union[str, Path] = "",
    directory: Union[str, Path] = "",
    target_sol: Union[int, str] = "",
    target_seq_id: str = "",
    verbose=True,
):
    if not (directory or explicit_path):
        ASDF_CONSOLE.print(
            "need an explicitly or implicitly-passed path to find files",
            style="bold red",
        )
        raise ValueError("no path passed to scan_zcam_dir")
    if explicit_path and not os.path.exists(explicit_path):
        ASDF_CONSOLE.print(
            str(explicit_path) + " does not exist.", style="bold red"
        )
        raise ValueError(str(explicit_path) + " does not exist.")
    if explicit_path:
        if Path(explicit_path).is_dir():
            directory = Path(explicit_path)
            target_file = None
        else:
            directory = Path(explicit_path).parent
            target_file = str(explicit_path)
    else:
        directory = Path(directory)
        target_file = None
    products = skim_products(directory)
    # TODO, maybe: add handling for edge cases that may someday occur
    #  in which site, drive, or zoom become distinguishing features
    if target_sol:
        products = products.loc[products["SOL"] == int(target_sol)].copy()
    if target_seq_id:
        products = products.loc[products["SEQ_ID"] == target_seq_id].copy()
    # TODO: decide whether to add this functionality back in
    # if strict_stereo:
    #     groups = products.groupby(["SOL", "SEQ_ID", "PRODUCT_TYPE", "RMS"])
    # else:
    groups = products.groupby(["SOL", "SEQ_ID", "PRODUCT_TYPE", "THUMBNAIL"])
    base_version = None
    observations = {}
    parser_warnings = []
    for group_ix, group in groups:
        if target_file and (target_file not in group["PATH"].values):
            continue
        sol, seq_id, product_type, thumb = group_ix
        name = "_".join([format(sol, "0>4"), seq_id, product_type, thumb])
        group = drop_mismatched_versions(group, base_version)
        if not group["FILTER"].duplicated().any():
            observations[name] = group
            continue
        # handle non-repointed-observation case: simply split by RMS
        if (group["FRAME_TYPE"] == "STEREO").all():
            rmsgroups = group.groupby(["RMS"])
            for rms, rmsgroup in rmsgroups:
                if not rmsgroup["FILTER"].duplicated().any():
                    observations[name + "_RMS" + str(rms)] = rmsgroup
                else:
                    parser_warnings.append(
                        (group["SEQ_ID"].iloc[0], "unknown issue")
                    )
        elif (group["FRAME_TYPE"] == "MONO").all():
            # handle repointed-stereo-observation case: split by pairs of RMS
            # TODO: this will currently crash if all filters from a single eye
            #  are missing
            if len(group["RMS"].unique()) % 2 != 0:
                parser_warnings.append(
                    (
                        seq_id,
                        "appears to involve a complex mast movement pattern I "
                        "cannot interpret.",
                    )
                )
            for repoint in partition(2, group["RMS"].unique()):
                observation = group.loc[group["RMS"].isin(repoint)]
                if not observation["FILTER"].duplicated().any():
                    observations[name + "_RMS" + str(repoint[0])] = observation
                else:
                    parser_warnings.append(
                        (
                            seq_id,
                            "unknown RMS windowing issue",
                        )
                    )
        else:
            parser_warnings.append(
                (seq_id, "MONO and STEREO mixed in sequence")
            )
    return observations, parser_warnings


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
