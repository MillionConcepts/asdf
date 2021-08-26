"""
functions for running around the filesystem and mashing together big messes
of products
"""
import os
from pathlib import Path
import re
from typing import Union
from urllib.error import URLError

from astropy.io import fits
from cytoolz.dicttoolz import valfilter
from cytoolz.functoolz import curry
from cytoolz.itertoolz import partition
from dustgoggles.scrape import cached_ls, cached_exists
from fs.osfs import OSFS
import numpy as np
import pandas as pd
from more_itertools import all_equal

import asdf_settings as settings
from asdf.asdf_utils import dir_fs
from dustgoggles.structures import listify
from dustgoggles.pivot import split_on, pdstr
from asdf.console import ASDFLOG
from asdf.network import get_public_m20_waypoints
from asdf.parse import (
    parse_marslab_fn,
    parse_pointing,
    parse_zcam_fn,
    pix_reference,
    looks_like_marslab,
    looks_like_roi,
)
from asdf.labels import cached_aux_skimmer, is_pixel_map_heuristic


# TODO: make all the error-printing statements in this module more consistent
#  with style in other modules
def drop_mismatched_versions(siblings, base_version=None):
    if len(siblings["VERSION"].unique()) == 1:
        return siblings
    versioned = siblings.copy()
    if base_version is None:
        base_version = versioned["VERSION"].max()
    dupes = versioned.loc[versioned["FILTER"].duplicated(keep=False)]
    for filter_name in dupes["FILTER"].unique():
        filter_slice = versioned.loc[versioned["FILTER"] == filter_name]
        if base_version in filter_slice["VERSION"].values:
            target_version = base_version
        else:
            target_version = filter_slice["VERSION"].max()
        versioned.drop(
            filter_slice.loc[filter_slice["VERSION"] != target_version].index,
            inplace=True,
        )
    return versioned


def skim_products(
    products, field_filters=None, aux_skimmer=cached_aux_skimmer
):
    # prefilters that don't require dipping into the header,
    #  for speed and stability on networked filesystems
    if field_filters:
        for field, value in field_filters.items():
            target_values = listify(value)
            if products[field].dtype.char in np.typecodes["AllInteger"]:
                target_values = [int(value) for value in target_values]
            filtered_products = products.loc[
                products[field].isin(target_values)
            ].copy()
            # TODO: shift these down to hidden...
            ASDFLOG.info(
                "... {} / {} matching {} criterion ...".format(
                    str(len(filtered_products)), str(len(products)), field
                )
            )
            products = filtered_products
    ASDFLOG.info("... skimming headers for grouping information ...")
    products = products.sort_values(by="CTIME").reset_index(drop=True)
    skim_results = []
    bad_files = []
    keep_paths = []
    for product in products["PATH"]:
        try:
            skim_results.append(aux_skimmer(product))
            keep_paths.append(product)
        except (FileNotFoundError, TypeError, KeyError):
            bad_files.append(product)
    if len(bad_files) > 0:
        ASDFLOG.warning(
            f"... only {str(len(skim_results))} "
            f"/ {str(len(products))} could be opened and read ..."
        )
        if len(bad_files) < 20:
            ASDFLOG.warning(
                "couldn't open:\n" + ",".join([file for file in bad_files])
            )
        else:
            ASDFLOG.warning(
                "... suppressing corrupt file list due to length ..."
            )
    return pd.concat(
        [
            products.loc[products["PATH"].isin(keep_paths)]
            .drop("PATH", axis=1)
            .reset_index(drop=True),
            pd.DataFrame(skim_results),
            pd.Series(keep_paths, name="PATH"),
        ],
        axis=1,
    )


def ls_zcam(root_dir, recursive, file_regex):
    if recursive is True:
        scan_fs = OSFS(str(root_dir))
        files = [scan_fs.getsyspath(file) for file in scan_fs.walk.files()]
    else:
        files = [file for file in Path(root_dir).iterdir()]
    ASDFLOG.info(
        "... {} files found in search path ...".format(str(len(files)))
    )
    if file_regex:
        matches = tuple(
            filter(curry(re.match, file_regex, flags=re.I), map(str, files))
        )
        if len(matches) != len(files):
            ASDFLOG.info(
                "... {} / {} matching regex {} ...".format(
                    str(len(matches)), str(len(files)), file_regex
                )
            )
        files = matches
    products = tuple(filter(None, map(parse_zcam_fn, files)))
    if products:
        products = pd.DataFrame(products)
        ASDFLOG.info(
            "... {} / {} have parsable ZCAM filenames ...".format(
                str(len(products)), str(len(files))
            )
        )
        return products.sort_values(by="CTIME").reset_index(drop=True)
    return None


def scan_zcam_files(
    root_dir: Union[str, Path] = "",
    target_sol: Union[int, str, pd.Series] = None,
    target_seq_id: Union[str, pd.Series] = None,
    regex_filter=None,
    keep_thumbnails=False,
    recursive=False,
):

    products = ls_zcam(root_dir, recursive, regex_filter)
    if products is None:
        raise ValueError(
            "sorry, no files in " + str(root_dir) + " have parsable"
            " ZCAM filenames."
        )
    # TODO, maybe: add handling for edge cases that may someday occur
    #  in which site, drive, or zoom become distinguishing features
    field_filters = {}
    if isinstance(target_sol, (pd.Series, np.ndarray)):
        field_filters["SOL"] = target_sol
    elif target_sol:
        field_filters["SOL"] = target_sol
    if isinstance(target_seq_id, (pd.Series, np.ndarray)):
        field_filters["SEQ_ID"] = target_seq_id
    elif target_seq_id:
        field_filters["SEQ_ID"] = target_seq_id
    if keep_thumbnails is False:
        field_filters["THUMBNAIL"] = "N"
    products = skim_products(products, field_filters)
    if len(products) == 0:
        raise ValueError("sorry, no matching products found in path.")
    return products


def cluster_observations(
    products,
    target_file=None,
    keep_broadband=False,
    keep_caltarget=False,
):
    groups = products.groupby(
        ["SOL", "SEQ_ID", "PRODUCT_TYPE", "THUMBNAIL", "PRODUCER"]
    )
    base_version = None
    observations = {}
    parser_warnings = []
    rejected_bb_count, rejected_cal_count, rejected_version_count = (0, 0, 0)
    for group_ix, group in groups:
        sol, seq_id, product_type, thumb, producer = group_ix
        if keep_broadband is False:
            # TODO: this sequence id heuristic might be crappy
            if group["FILTER"].isin(("L0", "R0")).all() or (
                int(seq_id[4:]) > 5000
            ):
                rejected_bb_count += len(group)
                continue
        if keep_caltarget is False:
            # TODO: this sequence id heuristic might be crappy
            if int(seq_id[4:]) < 3100:
                rejected_cal_count += len(group)
                continue
        name = "_".join(
            [format(sol, "0>4"), seq_id, product_type, thumb, producer]
        )
        # TODO: hideous logic
        # handle simultaneous stereo / single-eye observation: simply split by RSM
        if (group["FRAME_TYPE"] == "STEREO").all() or all_equal(
            products["FILTER"].str.slice(0, 1).values
        ):
            RSMgroups = group.groupby(["RSM"])
            for RSM, RSMgroup in RSMgroups:
                if target_file and (
                    target_file not in RSMgroup["PATH"].values
                ):
                    continue
                versioned = drop_mismatched_versions(RSMgroup, base_version)
                if len(versioned) != len(RSMgroup):
                    rejected_version_count += len(RSMgroup) - len(versioned)
                    RSMgroup = versioned
                if not RSMgroup["FILTER"].duplicated().any():
                    observations[name + "_RSM" + str(RSM)] = RSMgroup
                else:
                    parser_warnings.append(
                        "warning: an uncategorized issue may have prevented"
                        " me from correctly clustering  {}.".format(seq_id)
                    )
                    RSMgroup = RSMgroup.drop_duplicates(subset="FILTER")
                    if not RSMgroup["FILTER"].duplicated().any():
                        observations[name + "_RSM" + str(RSM)] = RSMgroup
        elif (group["FRAME_TYPE"] == "MONO").all():
            # handle repointed-stereo-observation case: split by pairs of RSM
            # TODO: this will currently fail if all filters from a single eye
            #  are missing
            if len(group["RSM"].unique()) % 2 != 0:
                parser_warnings.append(
                    f"warning: {seq_id} has a mast movement pattern I cannot "
                    "interpret, or not all files from the observation are "
                    "currently present in the directory. files may not have "
                    "been chunked correctly."
                )
            for repoint in partition(2, group["RSM"].unique()):
                observation = group.loc[group["RSM"].isin(repoint)]
                if target_file and (
                    target_file not in observation["PATH"].values
                ):
                    continue
                versioned = drop_mismatched_versions(observation, base_version)
                if not versioned["FILTER"].duplicated().any():
                    observations[name + "_RSM" + str(repoint[0])] = versioned
                else:
                    parser_warnings.append(
                        "warning: an unknown windowing issue may have "
                        "prevented me from correctly clustering {}.".format(
                            seq_id
                        )
                    )
        else:
            parser_warnings.append(
                "warning: MONO and STEREO mixed in {}; could not be "
                "clustered.".format(seq_id)
            )
    hidden_things = []
    for count, line in zip(
        (rejected_bb_count, rejected_cal_count, rejected_version_count),
        (
            "from broadband-only sequences",
            "from caltarget observations",
            "of lower/mismatched versions",
        ),
    ):
        if count > 0:
            hidden_things.append(
                "({} file(s) {} hidden)".format(str(count), line)
            )
    return observations, parser_warnings, hidden_things


def find_matching_pixmap(product_path):
    # look where we are, look in ../pix_map, look in hardcoded roots --
    # like the /scratch directories on islamorada; they don't live in /project.
    # or whatever you define locally.
    match_warnings = []
    product_path = Path(product_path)
    product_dir = product_path.parent
    sol_dir = product_dir.parent
    search_dirs = [Path(sol_dir, "pix_map")]
    search_dirs += [
        Path(root, sol_dir.name, "pix_map")
        for root in settings.sources.PIX_ROOTS
    ]
    search_dirs = set(search_dirs)
    # get all the files in these directories
    # TODO: i think we do care, actually
    # (functions are cached so we don't care about calling ls for every file)
    # and do filter step 1:
    # do they match timestamp, filter, seq_id, thumb?

    def pix_predicate(pixpath):
        return pix_reference(pixpath.name) == pix_reference(product_path.name)

    possible_pixmaps = match_in_dirs(search_dirs, product_path, pix_predicate)
    # sorry!
    if len(possible_pixmaps) == 0:
        return None, match_warnings
    # check 2: are they pixmaps?
    possible_pixmaps = list(filter(is_pixel_map_heuristic, possible_pixmaps))
    # TODO: find an actual way to associate these across versions --
    #  even adding a version number check will inappropriately reject
    #  many pixmaps because they do not increment the version numbers
    #  consistently. (I think.) ideally the pixmap header should reference the
    #  RAD but it does not
    # check 3: does the candidate we pick have PRODUCT_ID that matches
    # the data product's SOURCE_PRODUCT_ID? (CANCELLED FOR NOW)
    possible_pixmaps = prune_excessive_pixmap_matches(
        match_warnings, possible_pixmaps, product_path
    )
    pixmap = possible_pixmaps[0]
    # data_source_id = scrape_product_id(
    #     cached_label_loader(product_path), "SOURCE_"
    # )
    # pix_input_id = scrape_product_id(cached_label_loader(pixmap), "")
    # if pix_input_id != data_source_id:
    #     match_warnings.append(
    #         "input id mismatch for {}, not using it".format(str(pixmap))
    #     )
    #     return None, match_warnings
    return pixmap, match_warnings


def prune_excessive_pixmap_matches(
    match_warnings, possible_pixmaps, product_path
):
    if len(possible_pixmaps) > 1:
        ok_pixmaps = []
        parsed_fns = list(map(parse_zcam_fn, possible_pixmaps))
        versions = [parsed["VERSION"] for parsed in parsed_fns]
        for parsed in parsed_fns:
            if parsed["VERSION"] == max(versions):
                ok_pixmaps.append(Path(parsed["PATH"]))
        match_warnings.append(
            f"multiple matches for {product_path.name}, "
            f"using highest version # or first if version #s are equal;"
        )
        possible_pixmaps = ok_pixmaps
    return possible_pixmaps


def match_in_dirs(search_dirs, product_path, predicate=None):
    possible_matches = []
    for search_dir in search_dirs:
        if not cached_exists(search_dir):
            continue
        possible_matches += [
            Path(search_dir, file)
            for file in cached_ls(search_dir)
            if Path(file).name != product_path.name
        ]
    possible_matches = list(filter(predicate, possible_matches))
    return possible_matches


def find_obs_pixmaps(product_paths):
    all_match_warnings = []
    pixmaps = {}
    for path in product_paths:
        path = Path(path)
        pixmap, match_warnings = find_matching_pixmap(path)
        if pixmap is not None:
            pixmaps[str(path)] = str(pixmap)
        all_match_warnings += match_warnings
    return pixmaps, all_match_warnings


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
    try:
        m20_waypoint_dict = get_public_m20_waypoints()
    except (ValueError, URLError, OSError) as e:
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


def cluster_analyses(marslab: pd.DataFrame, roi: pd.DataFrame):
    stemmer = pdstr(
        "replace", "(roi|\.|fits|gz|marslab|csv)", "", regex=True
    )
    roi_stems = stemmer(roi["PATH"])
    marslab_stems = stemmer(marslab["PATH"])

    paired_marslab, lonely_marslab = split_on(
        marslab, marslab_stems.isin(roi_stems)
    )
    paired_roi, lonely_roi = split_on(roi, roi_stems.isin(marslab_stems))
    paired_marslab = (
        paired_marslab.copy()
        .sort_values(by="PATH", key=stemmer)
        .reset_index(drop=True)
    )
    paired_roi = (
        paired_roi.copy()
        .sort_values(by="PATH", key=stemmer)
        .reset_index(drop=True)
    )
    # did something go horribly wrong?
    check_equal = (
        paired_roi.iloc[:, 1:]
        .dropna(axis=1)
        .eq(paired_marslab.iloc[:, 1:].dropna(axis=1))
    )
    if not check_equal.all(axis=None):
        raise ValueError("clustering has gone horribly wrong.")
    marslab_path = paired_marslab["PATH"]
    marslab_path.name = "MARSLAB"
    roi_path = paired_roi["PATH"]
    roi_path.name = "ROI"
    analysis_df = pd.concat(
        [marslab_path, roi_path, paired_roi.iloc[:, 1:]], axis=1
    )
    return analysis_df, lonely_marslab, lonely_roi


def make_marslab_metadata_df(marslab_fn_list):
    marslab_df = pd.DataFrame(marslab_fn_list, columns=["PATH"])
    marslab_df = pd.concat(
        [
            marslab_df,
            pd.DataFrame(marslab_df["PATH"].map(parse_marslab_fn).to_list()),
        ],
        axis=1,
    )
    marslab_df = marslab_df.dropna(
        subset=["SOL", "SEQ_ID", "RSM"]
    )
    for field in ("SOL", "RSM"):
        marslab_df[field] = marslab_df[field].astype("int16")
    marslab_df["SEQ_ID"] = marslab_df["SEQ_ID"].str.upper()
    return marslab_df


def prune_analysis_df(df, sol=None, seq_id=None, file_regex=None):
    if sol:
        df = df.loc[df["SOL"] == int(sol)].copy()
    if seq_id:
        df = df.loc[
            df["SEQ_ID"].str.lower().str.contains(seq_id.lower())
        ].copy()
    if file_regex:
        df = df.loc[df["PATH"].str.match(file_regex)]
    return df


def fetch_analysis_files(path):
    analysis_fs = dir_fs(path)
    syspath = dir_fs(path).getsyspath
    marslab_files = []
    roi_files = []
    other_files = []
    for file in analysis_fs.walk.files():
        if looks_like_marslab(file):
            marslab_files.append(syspath(file))
        elif looks_like_roi(file):
            roi_files.append(syspath(file))
        else:
            other_files.append(syspath(file))
    return marslab_files, roi_files, other_files


def compare_roi_colors(analyses):
    """
    extra soft check to help verfiy that a ROI file corresponds to a compact
    marslab file
    """
    ok_indices = []
    bad_indices = []
    for ix, row in analyses.iterrows():
        marslab = pd.read_csv(row["MARSLAB"])
        roi = fits.open(row["ROI"])
        marslab_colors = set(marslab["COLOR"].unique())
        roi_colors = {hdu.header["NAME"].strip() for hdu in roi}
        if marslab_colors == roi_colors:
            ok_indices.append(ix)
        else:
            bad_indices.append(ix)
    return analyses.loc[ok_indices], analyses.loc[bad_indices]


def find_matching_observations(analyses, search_dir, search_regex):
    # This does not presently support thumbnails; we may need to collect
    # more metadata

    # prefilters for efficiency and reduced chance
    # of bizarre permissions errors on networked
    # filesystems
    target_sols = analyses["SOL"].unique()
    target_seq_ids = analyses["SEQ_ID"].unique()
    available_files = scan_zcam_files(
        search_dir,
        recursive=True,
        regex_filter=search_regex,
        target_sol=target_sols,
        target_seq_id=target_seq_ids,
    )
    parser_warnings = []
    misses = []
    reprocess_pairs = {}

    # try to match each analysis with an observation
    # (note: this is a many-to-one relationship)
    for _, analysis in analyses.iterrows():
        sol_seq_files = available_files.loc[
            (
                available_files[["SOL", "SEQ_ID"]]
                == analysis[["SOL", "SEQ_ID"]]
            ).all(axis=1)
        ]
        clusters, _, _ = cluster_observations(sol_seq_files)
        matches = valfilter(
            lambda df: analysis["RSM"] in df["RSM"].values, clusters
        )
        if len(matches) == 0:
            misses.append(analysis["MARSLAB"])
            continue
        if len(matches) > 1:
            parser_warnings.append(
                "multiple potential observations found for "
                + analysis["MARSLAB"]
                + ". This may indicate an overly broad search or something "
                "unusual going on with file names. Using the first."
            )
        reprocess_pairs[analysis["MARSLAB"]] = list(matches.values())[0]
    return reprocess_pairs, parser_warnings, misses
