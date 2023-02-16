"""
functions for running around the filesystem and mashing together big messes
of products
"""
import os
from collections import defaultdict
from functools import reduce
from operator import mul
from pathlib import Path
import re
from typing import Union, Sequence
from urllib.error import URLError

from cytoolz.dicttoolz import valfilter
from cytoolz.functoolz import curry
from cytoolz.itertoolz import partition
from dustgoggles.scrape import cached_ls, cached_exists
from fs.osfs import OSFS
import numpy as np
import pandas as pd
from more_itertools import all_equal

from asdf_settings import sources
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
from asdf.labels import get_pixel_map_heuristic, cached_aux_skimmer

# TODO: make all the error-printing statements in this module more consistent
#  with style in other modules


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
        except (FileNotFoundError, TypeError, KeyError, SyntaxError) as _error:
            bad_files.append(product)
    if len(bad_files) > 0:
        ASDFLOG.warning(
            f"... only {str(len(skim_results))} "
            f"/ {str(len(products))} could be opened and read ..."
        )
        if len(bad_files) < 20:
            ASDFLOG.warning(
                "couldn't open:\n" + ", ".join([file for file in bad_files])
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
            pd.Series(keep_paths, name="PATH", dtype=str),
        ],
        axis=1,
    )


def ls_zcam(root_dir, recursive=False, file_regex=""):
    if recursive is True:
        scan_fs = OSFS(str(root_dir))
        files = [scan_fs.getsyspath(file) for file in scan_fs.walk.files()]
    else:
        files = [file for file in Path(root_dir).iterdir()]
    ASDFLOG.info(f"... {len(files)} files found in search path ...")
    if file_regex:
        matches = tuple(
            filter(curry(re.match, file_regex, flags=re.I), map(str, files))
        )
        if len(matches) != len(files):
            ASDFLOG.info(
                f"... {len(matches)} / {len(files)} "
                f"matching regex {file_regex} ..."
            )
        files = matches
    matches = [
        file
        for file in files
        if not re.match(r".*\.(xml|lbl)$", str(file), re.I)
    ]
    if len(matches) != len(files):
        ASDFLOG.info(
            f"... {len(matches)} / {len(files)} "
            f"are not detached label files ..."
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
    stems = products["PATH"].str.rsplit("/", n=1, expand=True)
    stems = stems[1] if len(stems.columns) > 1 else stems[0]
    products["stem"] = stems.str.slice(0, 49)
    return products


def cluster_observations(
    products,
    target_file=None,
    keep_broadband=False,
    keep_caltarget=False,
):
    groups = products.groupby(["SOL", "SEQ_ID", "PRODUCT_TYPE", "THUMBNAIL"])
    observations = {}
    parser_warnings = []
    rejects = defaultdict(list)
    for group_ix, group in groups:
        if target_file and (target_file not in group["PATH"].values):
            continue
        sol, seq_id, product_type, thumb = group_ix
        if keep_broadband is False:
            if group["FILTER"].isin(("L0", "R0")).all() or (
                int(seq_id[4:]) > 5000
            ):
                rejects["bb"] += group["PATH"].tolist()
                continue
        if keep_caltarget is False:
            if int(seq_id[4:]) < 3100:
                rejects["cal"] += group["PATH"].tolist()
                continue
        # drop off-size subframes -- focus(?) frames, etc.
        frame_sizes = (
            group["SUBFRAME"]
            .map(lambda seq: seq[2:])
            .map(lambda pair: reduce(mul, pair))
        )
        if not all_equal(frame_sizes.values):
            smaller = group.loc[frame_sizes != frame_sizes.max()]
            rejects["frame"] += smaller["PATH"].tolist()
            group = group.drop(smaller.index)
        old_spice = group[
            "SPICE_FILE_NAME"
        ].str.startswith('chronos.m2020_jez')
        if old_spice.all():
            parser_warnings.append(
                f"All files in {seq_id} appear to have been sourced from old "
                f"EDRs. Use caution."
            )
        elif old_spice.any():
            older = group.loc[old_spice]
            rejects["provenance"] += older["PATH"].tolist()
            group = group.drop(older.index)
        # apply file quality selection logic:  take the 'best' version of
        # each image. this is intended to handle cases in which lower-quality
        # products were downlinked later due to various transmission
        # exigencies.
        stem_groups = group.groupby("stem")
        ok_indices = []
        for stem, siblings in stem_groups:
            merit_criteria = (
                rate_completion,
                rate_compression,
                rate_cal_offset,
                rate_rc_version,
                rate_version,
                rate_creation_time,
            )
            for merit_criterion in merit_criteria:
                if len(siblings) == 1:
                    break
                predicate = merit_criterion(siblings)
                if predicate is None:
                    continue
                # noinspection PyTypeChecker
                ok, not_ok = split_on(siblings, predicate)
                if len(ok) != len(siblings):
                    rejects[
                        merit_criterion.__name__.replace("rate_", "")
                    ] += not_ok["PATH"].tolist()
                    siblings = ok
            ok_indices += siblings.index.tolist()
        group = group.loc[ok_indices].sort_values(by="CTIME")
        # rc validation check
        # TODO: this currently makes running asdf on RADs fail...which is
        #  not a major issue, but should probably be addressed.
        parsed_rc_fns = group["RC_FILE"].map(parse_zcam_fn)
        cal_bailout = False
        for key in ("SITE", "DRIVE", "SEQ_ID", "VERSION"):
            if not all_equal([fn[key] for fn in parsed_rc_fns]):
                parser_warnings.append(
                    f"warning: cannot process {seq_id}. it appears to have "
                    f"mismatched calibrations. this probably indicates an "
                    f"issue in the photometric pipeline or accidental data "
                    f"deletion."
                )
                cal_bailout = True
                rejects["mismatched_cal"] += group["PATH"].tolist()
                break
        if cal_bailout is True:
            continue
        if "CALTARGET_LTST" not in group.columns:
            parser_warnings.append("old-format files!! things may be wrong.")
        name = "_".join([format(sol, "0>4"), seq_id, product_type, thumb])
        # TODO: hideous logic
        # handle simultaneous stereo or single-eye observations: group by RSM
        if (group["FRAME_TYPE"] == "STEREO").all() or all_equal(
            group["FILTER"].str.slice(0, 1).values
        ):
            rsm_groups = group.groupby("RSM")
            for RSM, rsm_group in rsm_groups:
                dupes = rsm_group.loc[
                    rsm_group["FILTER"].duplicated(keep=False)
                ]
                if len(dupes) == 0:
                    observations[name + "_RSM" + str(RSM)] = rsm_group
                # stereo ranging shot before sequence
                elif detect_ranging_shot(dupes):
                    rejects['ranging'] += rsm_group.iloc[:2]['PATH'].to_list()
                    observations[name + "_RSM" + str(RSM)] = rsm_group.iloc[2:]
                else:
                    parser_warnings.append(
                        f"warning: an uncategorized issue may have prevented "
                        f"me from correctly clustering {seq_id}."
                    )
                    rsm_group = rsm_group.drop_duplicates(subset="FILTER")
                    observations[name + "_RSM" + str(RSM)] = rsm_group
        # elif (group["FRAME_TYPE"] == "MONO").all():
        else:
            # try to filter ranging shots here
            # if not (group["FRAME_TYPE"] == "MONO").all():
                # stereo = group.loc[group["FRAME_TYPE"] == "STEREO"]
                # if (set(stereo["FILTER"]) == {"L0", "R0"}) and (
                #     set(group["FILTER"] != {"L0", "R0"})
                # ):
                #     rejects['ranging'] += group.loc[
                #         group['FRAME_TYPE'] != 'MONO']['PATH'
                #     ].to_list()
                #     group = group.loc[group["FRAME_TYPE"] == "MONO"]
                # else:
                #     parser_warnings.append(
                #         f"warning: MONO and STEREO mixed in {seq_id}; could "
                #         f"not be clustered."
                #     )
                #     rejects["mono_stereo"] += group["PATH"].tolist()
                #     continue
            # handle repointed-stereo-observation case: split by pairs of RSM
            # TODO: this will currently fail if all filters from a single eye
            #  are missing
            if len(group["RSM"].unique()) % 2 != 0:
                parser_warnings.append(
                    f"warning: {seq_id} has a mast movement pattern I cannot "
                    f"interpret, or not all files from the observation are "
                    f"currently present in the directory. files may not have "
                    f"been chunked correctly."
                )
            for repoint in partition(2, group["RSM"].unique()):
                observation = group.loc[group["RSM"].isin(repoint)]
                if observation["FILTER"].duplicated().any():
                    parser_warnings.append(
                        f"warning: an unknown windowing issue may have "
                        f"prevented me from correctly clustering {seq_id}."
                    )
                    observation = observation.drop_duplicates(subset="FILTER")
                observations[name + "_RSM" + str(repoint[0])] = observation
    hidden_things = []
    for reason, line in zip(
        (
            "bb",
            "cal",
            "frame",
            "completion",
            "compression",
            "cal_offset",
            "rc_version",
            "version",
            "creation_time",
            "mono_stereo",
            "mismatched_cal",
            "provenance",
            "ranging"
        ),
        (
            "from broadband-only sequences",
            "from caltarget observations",
            "with off-size subframes",
            "with partial completion status",
            "worse compression types",
            "with less chronologically appropriate caltarget observations",
            "with lower rc file version numbers",
            "with lower version numbers",
            "with older creation times",
            "mixed mono and stereo",
            "with mismatched calibrations",
            "sourced from old EDRs",
            "with 'ranging' intent"
        ),
    ):
        if rejects.get(reason) is not None:
            hidden_things.append(
                f"({len(rejects[reason])} file(s) {line} hidden)"
            )
    return observations, parser_warnings, hidden_things, rejects


def find_matching_metamap(product_path: str, code="pix_map"):
    # look where we are, look in ../pix_map, look in hardcoded roots --
    # like the /scratch directories on islamorada; they don't live in /project.
    # or whatever you define locally.
    match_warnings = []
    if not code in ["pix_map", "iof_err", "rad_err"]:
        raise TypeError(f"metamap {code} is invalid")
    product_path = Path(product_path)
    product_dir = product_path.parent
    sol_dir = product_dir.parent
    search_dirs = [Path(sol_dir, code)]
    search_dirs += [
        Path(root, sol_dir.name, code) for root in sources.META_ROOTS
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
    # TODO: gross hack to deal with non-standard directory structures given
    # the problem that pixel maps and RAD files have colliding filenames
    ###if code == "pix_map":
    ###    possible_pixmaps = filter(
    ###        None, map(get_pixel_map_heuristic, possible_pixmaps)
    ###    )
    # TODO: find an actual way to associate these across versions --
    #  even adding a version number check will inappropriately reject
    #  many pixmaps because they do not increment the version numbers
    #  consistently. (I think.) ideally the pixmap header should reference the
    #  RAD but it does not
    # check 3: does the candidate we pick have PRODUCT_ID that matches
    # the data product's SOURCE_PRODUCT_ID? (CANCELLED FOR NOW)
    possible_pixmaps = prune_excessive_pixmap_matches(
        match_warnings, list(possible_pixmaps), product_path
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


# TODO: make this work appropriately with the new selection system.
def prune_excessive_pixmap_matches(
    match_warnings, possible_pixmaps, product_path
):
    if len(possible_pixmaps) > 1:
        ok_pixmaps = []
        parsed_fns = list(
            map(parse_zcam_fn, [pix.name for pix in possible_pixmaps])
        )
        versions = [parsed["VERSION"] for parsed in parsed_fns]
        for parsed, pix in zip(parsed_fns, possible_pixmaps):
            if parsed["VERSION"] == max(versions):
                ok_pixmaps.append(pix)
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


def find_obs_metamaps(product_paths: Union[list, pd.DataFrame], code="pix_map"):
    if not code in ["pix_map", "iof_err", "rad_err"]:
        raise TypeError(f"metamap {code} is invalid")
    all_match_warnings = []
    metamaps = {}
    for path in product_paths:
        path = Path(path)
        metamap, match_warnings = find_matching_metamap(path, code=code)
        if metamap is not None:
            metamaps[str(path)] = str(metamap)
        all_match_warnings += match_warnings
    return metamaps, all_match_warnings


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
        taupath = sources.EFFECTIVE_TAU_PATH + taufile
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


def is_marslab_empty(marslab_path: Union[str, Path]) -> bool:
    return pd.read_csv(marslab_path)["COLOR"].iloc[0] == "-"


def cluster_analyses(marslab: pd.DataFrame, roi: pd.DataFrame):
    stemmer = pdstr("replace", r"(roi|\.|fits|gz|marslab|csv)", "", regex=True)
    roi_stems = stemmer(roi["PATH"])
    marslab_stems = stemmer(marslab["PATH"])

    paired_marslab, lonely_marslab = split_on(
        marslab, marslab_stems.isin(roi_stems)
    )
    empty_marslab, lonely_marslab = split_on(
        lonely_marslab, lonely_marslab["PATH"].map(is_marslab_empty)
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
    return analysis_df, lonely_marslab, empty_marslab, lonely_roi


def make_marslab_metadata_df(marslab_fn_list):
    marslab_df = pd.DataFrame(marslab_fn_list, columns=["PATH"])
    marslab_df = pd.concat(
        [
            marslab_df,
            pd.DataFrame(marslab_df["PATH"].map(parse_marslab_fn).to_list()),
        ],
        axis=1,
    )
    marslab_df = marslab_df.dropna(subset=["SOL", "SEQ_ID", "RSM"])
    for field in ("SOL", "RSM"):
        marslab_df[field] = marslab_df[field].astype("int16")
    marslab_df["SEQ_ID"] = marslab_df["SEQ_ID"].str.upper()
    return marslab_df


def prune_analysis_df(
    df: pd.DataFrame, sol=None, seq_id=None, file_regex=None
):
    if sol not in (None, ""):
        if isinstance(sol, Sequence) and not isinstance(sol, str):
            df = df.loc[df["SOL"].between(*map(int, sol))]
        else:
            df = df.loc[df["SOL"] == int(sol)].copy()
    if seq_id:
        df = df.loc[
            df["SEQ_ID"].str.lower().str.contains(seq_id.lower())
        ].copy()
    if file_regex:
        df = df.loc[df["PATH"].str.match(file_regex)]
    return df


def fetch_analysis_files(path: Union[str, Path]):
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


def compare_roi_colors(analyses: pd.DataFrame):
    """
    extra soft check to help verfiy that a ROI file corresponds to a compact
    marslab file
    """
    from astropy.io import fits

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


def find_matching_observations(
    analyses: pd.DataFrame, search_dir: str, search_regex: str
):
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
        # TODO: is this a bad idea? should we just pull filenames out of the
        #  marslab files, chopping off versions? or do we want this to be
        #  robust to even changes in naming conventions ... ?
        if len(sol_seq_files) > 0:
            clusters, _, _, _ = cluster_observations(
                sol_seq_files, keep_caltarget=True, keep_broadband=True
            )
            matches = valfilter(
                lambda df: analysis["RSM"] in df["RSM"].values, clusters
            )
        else:
            matches = {}
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


def rate_completion(siblings: pd.DataFrame):
    """
    merit criterion for file selection. return the files
    that are not partials, if any are not partials.
    """
    if (siblings["COMPLETION"] == "COMPLETE_CHECKSUM_PASS").any():
        return siblings["COMPLETION"] == "COMPLETE_CHECKSUM_PASS"


def rate_compression(siblings: pd.DataFrame):
    """
    merit criterion for file selection. return the files with the best
    compression type.
    """
    for compression in ("NONE", "MSSS_LOSSLESS", "JPEG"):
        if (siblings["COMPRESSION"] == compression).any():
            return siblings["COMPRESSION"] == compression


def rate_cal_offset(siblings: pd.DataFrame):
    """
    merit criterion for file selection. caltarget observation chronological
    distance from image time.
    """
    if "CALTARGET_LTST" not in siblings.columns:
        return pd.Series([True for _ in siblings.index], index=siblings.index)
    decimal_ltst = (
        siblings["LTST"].str.slice(0, 2).astype(int)
        + siblings["LTST"].str.slice(3, 5).astype(int) / 60
    )
    ltst_offset = decimal_ltst - siblings["CALTARGET_LTST"].abs()
    sol = siblings['SOL'].iloc[0]
    sol_offset = np.array(
        [
            abs(sol - rec["SOL"])
            for rec in siblings["CALTARGET_FILE"].map(parse_zcam_fn)
        ]
    )
    cal_chron_score = sol_offset + ltst_offset
    return cal_chron_score.abs() == cal_chron_score.abs().min()


def rate_version(siblings: pd.DataFrame):
    """
    merit criterion for file selection. return files with highest version #s.
    """
    return siblings["VERSION"] == siblings["VERSION"].max()


def rate_rc_version(siblings: pd.DataFrame):
    parsed_rc_fns = siblings["RC_FILE"].map(parse_zcam_fn)
    max_version = max([fn["VERSION"] for fn in parsed_rc_fns])
    return pd.Series(
        [
            True if fn["VERSION"] == max_version
            else False
            for fn in parsed_rc_fns
        ],
        index=siblings.index
    )


def rate_creation_time(siblings: pd.DataFrame):
    """
    merit criterion for file selection. return most recently made file.
    """
    return (
        siblings["PRODUCT_CREATION_TIME"]
        == siblings["PRODUCT_CREATION_TIME"].max()
    )


def detect_ranging_shot(dupes):
    """are these duplicate filters due to a 3D-supporting ranging shot?"""
    return (
        (set(dupes["FILTER"]) == {"L0", "R0"})
        and (len(dupes) == 4)
        and (set(dupes["FILTER"].iloc[0:2]) == {"L0", "R0"})
    )
