"""
functions for running around the filesystem and mashing together big messes
of products
"""
import os
import re
from pathlib import Path
from typing import Union
from urllib.error import URLError

import numpy as np
import pandas as pd
from cytoolz.dicttoolz import valfilter
from cytoolz.functoolz import curry
from cytoolz.itertoolz import partition
from fs.osfs import OSFS

import asdf.settings as settings
from asdf.asdf_utils import load_roi_file, split_on, dir_fs
from asdf.console import ASDFLOG
from asdf.network import get_public_m20_waypoints
from asdf.parse import (
    parse_marslab_fn,
    parse_pointing,
    parse_zcam_fn,
    pix_reference,
    is_pixel_map,
    looks_like_marslab,
    looks_like_roi,
)
from asdf.scrape import (
    cached_aux_skimmer,
    is_iof_est_heuristic,
    cached_ls,
    cached_exists,
)


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
    files, field_filters=None, file_regex=None, aux_skimmer=cached_aux_skimmer
):
    if file_regex:
        matches = tuple(
            filter(curry(re.match, file_regex, flags=re.I), files)
        )
        if len(matches) != len(files):
            ASDFLOG.info(
                "... {} / {} matching regex {} ...".format(
                    str(len(matches)), str(len(files)), file_regex
                )
            )
        files = matches
    products = tuple(filter(None, map(parse_zcam_fn, files)))
    if not products:
        return None
    ASDFLOG.info(
        "... {} / {} have parsable ZCAM filenames ...".format(
            str(len(products)), str(len(files))
        )
    )
    products = pd.DataFrame(products)
    # TODO: merge these with other prefilters below?
    # prefilters that don't require dipping into the header,
    #  for speed on networked filesystems
    if field_filters:
        for field, value in field_filters.items():
            if products[field].dtype.char in np.typecodes["AllInteger"]:
                value = int(value)
            filtered_products = products.loc[products[field] == value].copy()
            # TODO: shift these down to hidden...
            ASDFLOG.info(
                "... {} / {} matching {} criterion ...".format(
                    str(len(filtered_products)), str(len(products)), field
                )
            )
            products = filtered_products
    products = products.sort_values(by="CTIME").reset_index(drop=True)
    return pd.concat(
        (
            products.drop("PATH", axis=1),
            pd.DataFrame(products["PATH"].map(aux_skimmer).tolist()),
            products["PATH"],
        ),
        axis=1,
    )


def scan_zcam_files(
    root_dir: Union[str, Path] = "",
    target_sol: Union[int, str] = "",
    target_seq_id: str = "",
    regex_filter=None,
    keep_thumbnails=False,
    recursive=False,
    target_product_type=None,
):
    if recursive is True:
        scan_fs = OSFS(str(root_dir))
        files = [scan_fs.getsyspath(file) for file in scan_fs.walk.files()]
    else:
        files = [file for file in Path(root_dir).iterdir()]
    ASDFLOG.info(
        "... {} files found in search path ...".format(str(len(files)))
    )
    # TODO, maybe: add handling for edge cases that may someday occur
    #  in which site, drive, or zoom become distinguishing features
    field_filters = {}
    if target_sol:
        field_filters["SOL"] = target_sol
    if target_seq_id:
        field_filters["SEQ_ID"] = target_seq_id
    if keep_thumbnails is False:
        field_filters["THUMBNAIL"] = "N"
    products = skim_products(files, regex_filter, field_filters)
    if products is None:
        raise ValueError(
            "sorry, no files in " + str(root_dir) + " have parsable"
            " ZCAM filenames."
        )
    if target_product_type:
        target_product_type = target_product_type.upper()
        if target_product_type in ("IOF", "IOF_EST"):
            ioflikes = products.loc[products["PRODUCT_TYPE"] == "IOF"].copy()
            # TODO: this may not be reliable or good, at least yet. probably
            #  better to filter directories.
            is_iof_est = ioflikes["PATH"].map(is_iof_est_heuristic)
            if target_product_type == "IOF":
                is_iof_est = ~is_iof_est
            typeproducts = ioflikes[~is_iof_est]
        else:
            typeproducts = products.loc[
                products["PRODUCT_TYPE"] == target_product_type
            ].copy()
        ASDFLOG.info(
            "... {} / {} match the requested product type ...".format(
                str(len(typeproducts)), str(len(products))
            )
        )
        products = typeproducts
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
        versioned = drop_mismatched_versions(group, base_version)
        if len(versioned) != len(group):
            rejected_version_count += len(group) - len(versioned)
            group = versioned
        # TODO: hideous logic
        # handle non-repointed-observation case: simply split by RMS
        if (group["FRAME_TYPE"] == "STEREO").all():
            rmsgroups = group.groupby(["RMS"])
            for rms, rmsgroup in rmsgroups:
                if target_file and (
                    target_file not in rmsgroup["PATH"].values
                ):
                    continue
                if not rmsgroup["FILTER"].duplicated().any():
                    observations[name + "_RMS" + str(rms)] = rmsgroup
                else:
                    parser_warnings.append(
                        "warning: an uncategorized issue may have prevented"
                        " me from correctly clustering  {}.".format(seq_id)
                    )
                    rmsgroup = rmsgroup.drop_duplicates(subset="FILTER")
                    if not rmsgroup["FILTER"].duplicated().any():
                        observations[name + "_RMS" + str(rms)] = rmsgroup
        elif (group["FRAME_TYPE"] == "MONO").all():
            # handle repointed-stereo-observation case: split by pairs of RMS
            # TODO: this will currently fail if all filters from a single eye
            #  are missing

            if len(group["RMS"].unique()) % 2 != 0:
                parser_warnings.append(
                    "warning: {} has a mast movement pattern I cannot "
                    "interpret. files may not have been chunked "
                    "correctly.".format(seq_id)
                )
            for repoint in partition(2, group["RMS"].unique()):
                observation = group.loc[group["RMS"].isin(repoint)]
                if target_file and (
                    target_file not in observation["PATH"].values
                ):
                    continue
                if not observation["FILTER"].duplicated().any():
                    observations[name + "_RMS" + str(repoint[0])] = observation
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
    search_dirs = [product_dir, Path(sol_dir, "pix_map")]
    search_dirs += [
        Path(root, sol_dir.name, "pix_map")
        for root in settings.sources.PIX_ROOTS
    ]
    # get all the files in these directories
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
    possible_pixmaps = list(filter(is_pixel_map, possible_pixmaps))
    # TODO: find an actual way way to associate these across versions --
    #  just adding a version number check for now but this is not reliable
    #  ideally the pixmap header should reference the RAD but it does not
    # check 3: does the candidate we pick have PRODUCT_ID that matches
    # the data product's SOURCE_PRODUCT_ID? (CANCELLED FOR NOW)
    if len(possible_pixmaps) > 1:
        match_warnings.append(
            "multiple matches for " + product_path.name + ", using first"
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


def cluster_analyses(marslab: pd.DataFrame, roi: pd.DataFrame):
    roi_stems = roi["PATH"].str.replace("-roi.fits", "", regex=False)
    marslab_stems = marslab["PATH"].str.replace(
        "-marslab.csv", "", regex=False
    )

    paired_marslab, lonely_marslab = split_on(
        marslab, marslab_stems.isin(roi_stems)
    )
    paired_roi, lonely_roi = split_on(roi, roi_stems.isin(marslab_stems))
    paired_marslab = (
        paired_marslab.copy().sort_values(by="PATH").reset_index(drop=True)
    )
    paired_roi = (
        paired_roi.copy().sort_values(by="PATH").reset_index(drop=True)
    )
    # did something go horribly wrong?
    check_equal = (
        paired_roi.iloc[:, 1:]
        .dropna(axis=1)
        .eq(paired_marslab.iloc[:, 1:].dropna(axis=1))
    )
    assert check_equal.all(axis=None), "clustering has gone horribly wrong."
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
        subset=["SOL", "SEQ_ID", "SITE", "DRIVE", "RMS", "ZOOM"]
    )
    for field in ("SOL", "SITE", "DRIVE", "RMS", "ZOOM"):
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
        roi, _ = load_roi_file(row["ROI"], verbose=False)
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
    available_files = scan_zcam_files(
        search_dir,
        recursive=True,
        regex_filter=search_regex,
    )
    # prefilter df for efficiency
    for field in ["SOL", "SEQ_ID"]:
        relevant_values = analyses[field].unique()
        available_files = available_files.loc[
            available_files[field].isin(relevant_values)
        ].copy()
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
            lambda df: analysis["RMS"] in df["RMS"].values, clusters
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
