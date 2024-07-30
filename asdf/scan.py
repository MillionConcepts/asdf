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
from typing import Union, Sequence, Optional, Literal, Callable, Collection, MutableMapping, MutableSequence, Any
from urllib.error import URLError

from cytoolz.dicttoolz import valfilter
from cytoolz.functoolz import curry
from cytoolz.itertoolz import partition
from dustgoggles.pivot import split_on, pdstr
from dustgoggles.scrape import cached_ls, cached_exists
from dustgoggles.structures import listify
from fs.osfs import OSFS
import numpy as np
import pandas as pd
from more_itertools import all_equal

from asdf._types import Waypoints
from asdf.asdf_utils import dir_fs
from asdf.console import ASDFLOG
from asdf.labels import cached_aux_skimmer
from asdf.network import get_public_m20_waypoints
from asdf.parse import (
    parse_marslab_fn,
    parse_pointing,
    parse_zcam_fn,
    pix_reference,
    looks_like_marslab,
    looks_like_roi,
)
from asdf_settings import sources


# TODO: make all the error-printing statements in this module more consistent
#  with style in other modules


def skim_products(
    products: pd.DataFrame,
    field_filters: Optional[dict[str, Any]] = None,
    aux_skimmer: Callable[[Union[str, Path]], dict] = cached_aux_skimmer,
    rsm: Optional[Collection[int]] = None
) -> pd.DataFrame:
    """
    Helper function for scan_zcam_files(). Skims all ZCAM files referenced in a
    dataframe for basic identifying information. Is only expected to work
    reliably for IOFs and IOEs.
    """
    # prefilters that don't require dipping into the header,
    #  for speed and stability on networked filesystems
    if field_filters is not None:
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
    skim_results, bad_files, keep_paths, rsm_rejects = [], [], [], []
    for product in products["PATH"]:
        try:
            skim_result = aux_skimmer(product)
            if rsm is not None and skim_result['RSM'] not in rsm:
                rsm_rejects.append(product)
                continue
            skim_results.append(skim_result)
            keep_paths.append(product)
        except (FileNotFoundError, TypeError, KeyError, SyntaxError) as _error:
            bad_files.append(product)
    if len(rsm_rejects) > 0:
        ASDFLOG.info(
            f"... rejected {len(rsm_rejects)} / {len(products)} "
            f"on RSM criterion ..."
        )
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


def ls_zcam(
    root_dir: Union[str, Path],
    recursive: bool = False,
    file_regex: Optional[Union[str, re.Pattern]] = ""
) -> Optional[pd.DataFrame]:
    """
    Simple, fast `ls` for ZCAM products that only examines filenames and does
    not skim headers. Used in initial steps of several file-grouping routines,
    including `find_and_offer_observations()`, but is also very useful a la
    carte in data exploration and corpus validation. If it finds any files
    that appear to be ZCAM products, returns a dataframe of paths and basic
    identifying file information; otherwise, returns None.

    Should work on IOFs, RADs, pixmaps, IOEs, EDRs, and rcfiles.
    """
    if recursive is True:
        scan_fs = OSFS(str(root_dir))
        files = [scan_fs.getsyspath(file) for file in scan_fs.walk.files()]
    else:
        files = [file for file in Path(root_dir).iterdir()]
    ASDFLOG.info(f"... {len(files)} files found in search path ...")
    if file_regex not in (None, ""):
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
    if len(products) > 0:
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
    target_sol: Optional[Union[int, str, pd.Series]] = None,
    target_seq_id: Optional[Union[str, pd.Series]] = None,
    regex_filter: Optional[Union[str, re.Pattern]] = None,
    keep_thumbnails: bool = False,
    recursive: bool = False,
    rsm: Optional[Collection[int]] = None
) -> pd.DataFrame:
    """
    Provide extensive identifying information about ZCAM files in a directory
    or directory tree with optional exclusion filters.. Builds on ls_zcam() by
    skimming PVL headers as well as simply parsing filenames. Is only expected
    to work reliably for IOFs and IOEs. Used in setup steps of various file-
    finding and clustering routines, but is also useful a la carte in data
    exploration and corpus validation. Returns a dataframe of per-file
    metadata.
    """
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
    elif target_sol not in (None, ""):
        field_filters["SOL"] = target_sol
    if isinstance(target_seq_id, (pd.Series, np.ndarray)):
        field_filters["SEQ_ID"] = target_seq_id
    elif target_seq_id not in (None, ""):
        field_filters["SEQ_ID"] = target_seq_id
    if keep_thumbnails is False:
        field_filters["THUMBNAIL"] = "N"
    products = skim_products(products, field_filters, rsm=rsm)
    if len(products) == 0:
        raise ValueError("sorry, no matching products found in path.")
    stems = products["PATH"].str.rsplit("/", n=1, expand=True)
    stems = stems[1] if len(stems.columns) > 1 else stems[0]
    products["stem"] = stems.str.slice(0, 49)
    return products


# TODO, maybe: cal checks make running asdf on RADs fail. We should probably
#  decide once and for all whether to fully deprecate the idea of running
#  asdf directly on RADs.
def cluster_observations(
    products: pd.DataFrame,
    target_file=None,
    keep_broadband=False,
    keep_caltarget=False,
) -> tuple[
    dict[str, pd.DataFrame],
    tuple[str, ...],
    tuple[str, ...],
    dict[str, list[str]]
]:
    """
    Business-end function for clustering ZCAM IOFs into 'observations'.
    Applies a wide variety of heuristics and integrity checks that handle
    most standard and nonstandard multispectral sequences and detect/reject
    most extant and many likely pathological cases.

    For more detail on some of these heuristics and integrity checks, see:
    * https://docs.google.com/document/d/1l-zljFZJeCoX_aqJ-BlZ_J79I4T3NW7pgcI2Zcd7qNU
    * https://docs.google.com/document/d/1l8RElG_AhibozjkfOVjSVhbXOXcSEcQWquVcvbwFovI
    """
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
        cal_ok, cal_warn = validate_caltarget_sol_consistency(group, seq_id)
        if cal_ok is False:
            rejects["mismatched_cal_sol"] += group["PATH"].tolist()
            parser_warnings.append(cal_warn)
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
                # rc validation check
                rc_ok, rc_warn = validate_rc_consistency(rsm_group, seq_id)
                if rc_ok is False:
                    rejects["mismatched_rc"] += rsm_group["PATH"].tolist()
                    parser_warnings.append(rc_warn)
                    continue
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
        else:
            # TODO: see footnote for dead mono filtering code. generally too
            #  strict but available as a reference.
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
                observation: pd.DataFrame = group.loc[
                    group["RSM"].isin(repoint)
                ]
                rc_ok, rc_warn = validate_rc_consistency(observation, seq_id)
                if rc_ok is False:
                    rejects["mismatched_rc"] += observation["PATH"].tolist()
                    parser_warnings.append(rc_warn)
                    continue
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
            "mismatched_cal_sol",
            "mismatched_rc",
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
            "using caltarget observations from multiple sols",
            "with mismatched rc files",
            "sourced from old EDRs",
            "with 'ranging' intent"
        ),
    ):
        if rejects.get(reason) is not None:
            hidden_things.append(
                f"({len(rejects[reason])} file(s) {line} hidden)"
            )
    # noinspection PyTypeChecker
    return observations, tuple(set(parser_warnings)), hidden_things, rejects


def validate_caltarget_sol_consistency(
    group: pd.DataFrame, seq_id: str
) -> tuple[bool, Optional[str]]:
    """
    Inline validation function for `find_and_offer_observations()`. Verify
    that all IOFs in a stemgroup were calibrated using caltarget images taken
    on the same sol as one another (not necessarily the same sol as the IOFs).
    """
    parsed_caltarget_fns = group['CALTARGET_FILE'].map(parse_zcam_fn)
    caltarget_ok, caltarget_warning = True, None
    if not all_equal(fn['SOL'] for fn in parsed_caltarget_fns):
        caltarget_warning, caltarget_ok = (
            f"warning: could not process {seq_id}. It was calibrated using "
            f"caltarget observations on different sols. "
        ) + CAL_WARN_BOILERTPLATE, False
    return caltarget_ok, caltarget_warning


def validate_rc_consistency(
    group: pd.DataFrame, seq_id: str
) -> tuple[bool, Optional[str]]:
    """
    Inline validation function for `find_and_offer_observations()`. Verify
    that all IOFs in a stemgroup were calibrated using RC files produced from
    the same caltarget sequence. This works alongside
    validate_caltarget_sol_consistency() to provide an additional layer of
    calibration integrity verification.
    """
    parsed_rc_fns = group["RC_FILE"].map(parse_zcam_fn)
    rc_ok, rc_warning = True, None
    for key in ("SITE", "DRIVE", "SEQ_ID", "VERSION"):
        if not all_equal([fn[key] for fn in parsed_rc_fns]):
            rc_warning, rc_ok = (
                f"warning: could not process some or all pointings of "
                f"{seq_id} due to mismatched calibrations. "
            ) + CAL_WARN_BOILERTPLATE, False
            break
    return rc_ok, rc_warning


CAL_WARN_BOILERTPLATE = (
    "This could indicate an issue in the photometric pipeline, accidental "
    "data deletion, or limited data availability (for instance, the sequence "
    "may not be completely downlinked)."
)


METAMAP_TYPES = ("pix_map", "iof_err", "rad_err")
"""
Recognized (if not necessarily fully supported) categories of metadata image 
array product.
"""


# NOTE: all the dead code essentially serves as notes for disambiguation code
#  in the case that nonstandard directory structures exist.
def find_matching_metamap(
    product_path: Union[str, Path], code: Literal[METAMAP_TYPES] = "pix_map"
) -> tuple[Optional[Path], list[str]]:
    """
    Find a 'metamap' file that matches an IOF -- a product containing an
    array whose elements provide metadata for the corresponding elements
    of the IOF image. Currently, only pix_map is actually supported.

    Returns a tuple whose first element is a Path object for a matching
    metamap if any were found and None if none were found, and whose second
    element is a list of warnings about ambiguous cases found in matching.
    """
    # look where we are, look in ../pix_map, look in hardcoded roots --
    # like the /scratch directories on islamorada; they don't live in /project.
    # or whatever you define locally.
    match_warnings = []
    if code not in ["pix_map", "iof_err", "rad_err"]:
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
    match_warnings: MutableSequence[str],
    possible_pixmaps: Collection[Path],
    product_path: Path
) -> list[Path]:
    """
    If there are multiple matching pixmaps for a particular product, pick the
    one with the highest version number. This is not strictly correct given the
    matching system adopted in 2022, but there do not seem to be any actually-
    existing cases in which it leads to issues, because picking the wrong
    pixmap would require a really pathological case (most would simply lead
    to name collisions).
    """
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


def match_in_dirs(
    search_dirs: Collection[Union[str, Path]],
    product_path: Path,
    predicate: Optional[Callable[[Path], bool]] = None
) -> list[Path]:
    """
    Helper function for find_matching_metamap(). Filters the contents
    of `search_dirs()` using a provided predicate function while also rejecting
    the related file itself.
    """
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


def find_obs_metamaps(
    product_paths: Collection[Union[str, Path]],
    code: METAMAP_TYPES = "pix_map"
) -> tuple[dict[str, str], list[str]]:
    if code not in METAMAP_TYPES:
        """
        Handler function for find_matching_metamap(). Attempts to find matching
        metamaps of the type matching `code` for all files in `product_paths`.
        """
        raise TypeError(f"metamap type {code} is invalid")
    all_match_warnings = []
    metamaps = {}
    for path in product_paths:
        path = Path(path)
        metamap, match_warnings = find_matching_metamap(path, code=code)
        if metamap is not None:
            metamaps[str(path)] = str(metamap)
        all_match_warnings += match_warnings
    return metamaps, all_match_warnings


def matching_waypoints(
    site: Union[int, str], drive: Union[int, str], waypoints: Waypoints
) -> Waypoints:
    """
    Selects the waypoint or waypoints -- there will _generally_ be only one --
    associated with a particular site and drive from a list of waypoints
    produced by parsing GeoJSON fetched from the M20 public waypoint server.
    """
    return [
        feature
        for feature in waypoints
        if (int(feature["properties"]["site"]) == int(site))
        and (int(feature["properties"]["drive"]) == int(drive))
    ]


def associate_waypoints(
    metadata: Union[MutableMapping, pd.DataFrame], waypoints: Waypoints
) -> Union[MutableMapping, pd.DataFrame]:
    """
    Parses the site and drive information from a metadata structure produced
    during scanning, finds the matching feature in a list of waypoints, and
    adds geospatial information for that feature to the metadata structure.
    """
    pointing = parse_pointing(metadata)
    matches = matching_waypoints(
        pointing["SITE"], pointing["DRIVE"], waypoints
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


def add_public_waypoints_to_metadata(
    metadata: Union[MutableMapping, pd.DataFrame]
) -> Union[MutableMapping, pd.DataFrame]:
    """
    Handler function: add geospatial information from the public waypoints
    server to `metadata`.
    """
    try:
        m20_waypoint_dict = get_public_m20_waypoints()
    except (ValueError, URLError, OSError) as e:
        print(str(e) + " ; not adding waypoints to metadata")
        return metadata
    return associate_waypoints(metadata, m20_waypoint_dict)


# TODO: check to what extent this is ever working
def add_effective_taus(metadata: pd.DataFrame) -> pd.DataFrame:
    """
    Search for tau (atmospheric opacity) files and add their contents to
    `metadata`. In practice, these may not ever be available.
    """
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
            # noinspection PyTypeChecker
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
    """
    Filtering predicate for the fdsa clustering routine. Returns True if a
    marslab file is 'empty' (i.e., contains no ROIs) and False otherwise.
    """
    return pd.read_csv(marslab_path)["COLOR"].iloc[0] == "-"


def cluster_analyses(
    marslab: pd.DataFrame, roi: pd.DataFrame
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """
    Step of fdsa setup routine that associates ROI files with marslab files
    by checking their stems and 'emptiness'. Returns a tuple of 4 dataframes,
    respectively:
     1. matched marslab files and ROI files
     2. 'lonely' marslab files (marslab files that contain ROI information but
        have no matching ROI file)
     3. 'empty' marslab files (marslab files with no ROI information)
     4. 'lonely' ROI files (ROI files with no apparent matching marslab files)
    """
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
    matchcols = ['SOL', 'SEQ_ID', 'RSM', 'ANALYSIS_NAME']
    checkroi = paired_roi[[c for c in paired_roi.columns if c in matchcols]]
    checkmars = paired_marslab[[c for c in paired_marslab.columns if c in matchcols]]
    check_equal = (
        checkroi.iloc[:, 1:]
        .dropna(axis=1)
        .eq(checkmars.iloc[:, 1:].dropna(axis=1))
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


def make_marslab_metadata_df(marslab_fn_list: Sequence[str]) -> pd.DataFrame:
    """
    Helper function for fdsa setup routine. Parses a sequence of marslab
    or ROI filenames and constructs a dataframe of basic identifying metadata.
    """
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
    df: pd.DataFrame,
    sol: Optional[Union[int, str]] = None,
    seq_id: Optional[str] = None,
    file_regex: Optional[Union[str, re.Pattern]] = None,
    rsm: Optional[Collection[int]] = None
) -> pd.DataFrame:
    """
    Helper function for fdsa setup routine that applies a series of optional
    filters to a dataframe of basic identifying information about a set of
    marslab or ROI files, permitting users to restrict an fdsa run by sol,
    sequence id, or arbitrary file pattern.
    """
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
    if rsm is not None:
        df = df.loc[df['RSM'].isin(rsm)]
    return df


def fetch_analysis_files(
    path: Union[str, Path]
) -> tuple[list[str], list[str], list[str]]:
    """
    Helper function for fdsa setup routine. Recursively walks through a
    directory tree and returns a tuple whose elements are a list of paths to
    files that appear to be compact marslab files, a list of paths to files
    that appear to be ROI FITS files, and a list of paths to files that don't
    appear to be either.
    """
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


def compare_roi_colors(
    analyses: pd.DataFrame
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Check used in fdsa setup routine to help verify that ROI files match
    their paired compact marslab files.  Returns a tuple whose elements are a
    dataframe containing those marslab/ROI pairs whose colors match and a
    dataframe containing those that do not.

    NOTE: Could fail if someone swapped in inappropriate ROI files that had the
     same colors/numbers of ROIs.
    """
    from astropy.io import fits
    from isal import igzip

    ok_indices = []
    bad_indices = []
    for ix, row in analyses.iterrows():
        marslab = pd.read_csv(row["MARSLAB"])
        with igzip.open(row["ROI"]) as decompressed:
            roi = fits.open(decompressed)
            roi_colors = {
                rec[1].split(' ')[0].lower() for rec in roi.info(False)
            }
        marslab_colors = set(marslab["COLOR"].unique())
        if marslab_colors == roi_colors:
            ok_indices.append(ix)
        else:
            bad_indices.append(ix)
    return analyses.loc[ok_indices], analyses.loc[bad_indices]


def find_matching_observations(
    analyses: pd.DataFrame,
    search_dir: str,
    search_regex: str,
    rsm: Optional[Collection[int]] = None
) -> tuple[dict[str, pd.DataFrame], list[str], list[str]]:
    """
    Step of fdsa setup routine that attempts to match each row of a dataframe
    of marslab/ROI file pairs with a set of IOF files available on the system.

    Returns a tuple whose elements are:
     1. a dict whose keys are paths to compact marslab files and whose values
      are cluster dataframes
     2. A list of warnings about ambiguous matches
     3. A list of paths to compact marslab files for which no matching
      observation was found on the system
    """
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
        rsm=rsm
    )
    parser_warnings, misses, reprocess_pairs = [], [], {}

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


def rate_completion(siblings: pd.DataFrame) -> Optional[pd.Series]:
    """
    Merit criterion for file selection in observation clustering. Return a
    boolean mask for the files that are not partials, if any are not partials;
    if all are partials, return None.
    """
    if (siblings["COMPLETION"] == "COMPLETE_CHECKSUM_PASS").any():
        return siblings["COMPLETION"] == "COMPLETE_CHECKSUM_PASS"


def rate_compression(siblings: pd.DataFrame):
    """
    Merit criterion for file selection in observation clustering. Return a
    boolean mask for the files with the 'best' compression type: uncompressed
    is best, MSSS 'lossless' (companded) is second best, JPEG is worst. Does
    not attempt to distinguish between levels of JPEG compression (sequences
    are never, in practice, downlinked multiple times at different levels of
    JPEG compression).
    """
    for compression in ("NONE", "MSSS_LOSSLESS", "JPEG"):
        if (siblings["COMPRESSION"] == compression).any():
            return siblings["COMPRESSION"] == compression
    raise ValueError(
        f"Unknown compression types referenced in dataframe: "
        f"{', '.join(siblings['COMPRESSION'].unique())}"
    )


def rate_cal_offset(siblings: pd.DataFrame) -> pd.Series:
    """
    Merit criterion for file selection in observation clustering. Return a
    boolean mask for those files whose associated caltarget observations have
    the highest 'score', based on sol and LTST offsets.
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
    # noinspection PyTypeChecker
    return cal_chron_score.abs() == cal_chron_score.abs().min()


def rate_version(siblings: pd.DataFrame) -> pd.Series:
    """
    Merit criterion for file selection in observation clustering. Return a
    boolean mask for the files with the highest version #s (among all available
    version #s).
    """
    # noinspection PyTypeChecker
    return siblings["VERSION"] == siblings["VERSION"].max()


def rate_rc_version(siblings: pd.DataFrame) -> pd.Series:
    """
    Merit criterion for file selection in observation clustering. Return a
    boolean mask for the files whose associated RC files have the highest
    version # (among all available version #s).
    """
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


def rate_creation_time(siblings: pd.DataFrame) -> pd.Series:
    """
    Merit criterion for file selection. Return a boolean mask that is True for
    the most recently-made file and False otherwise.
    """
    # noinspection PyTypeChecker
    return (
        siblings["PRODUCT_CREATION_TIME"]
        == siblings["PRODUCT_CREATION_TIME"].max()
    )


def detect_ranging_shot(dupes) -> bool:
    """
    Heuristic for observation clustering. Return True if duplicate filters in
    a dataframe of images from a single observation appear to be duplicated
    because they were used in a 3D-supporting ranging shot.
    """
    return (
        (set(dupes["FILTER"]) == {"L0", "R0"})
        and (len(dupes) == 4)
        and (set(dupes["FILTER"].iloc[0:2]) == {"L0", "R0"})
    )


"""
footnote: dead mono ranging shot filtering code
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
"""
