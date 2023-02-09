"""functions that basically instantiate text parsing rules"""

import re
from pathlib import Path
from typing import Union, Mapping

import pandas as pd
from cytoolz.functoolz import juxt

from marslab import parse as mp


def offlabel_producer(fn):
    """
    we want to treat the undefined producer codes used by zcam as distinct
    """
    return fn[51:52]


ZCAM_FN_PARSERS = {
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
    "PRODUCER": offlabel_producer,
}


def parse_marslab_fn(fn):
    basename = Path(fn).name
    field_regexes = {
        # TODO: legacy support, remove RMS later
        "RSM": r"(?:RMS|RSM)(\d+)",
        "SOL": r"SOL(\d+)",
        "SEQ_ID": r"(zcam\d+)",
        # TODO: legacy support, remove marslab and roi later
        "ANALYSIS_NAME": r".*?-(.*?)-(?=(marslab|roi|csv|fits))",
    }
    parsedict = {}
    for field, regex in field_regexes.items():
        search = re.search(regex, basename)
        parsedict[field] = search.group(1) if search else None
    return parsedict


def parse_pointing(sequence: Union[Mapping, pd.DataFrame]) -> dict:
    """
    basically a parsing rule: grab the subset of pointing-discriminating
    fields from a dict of metadata. pointings are basically equivalence
    relations: every product with these values for these fields
    is in the same pointing, no product that does not have these
    values for these fields is in that pointing. the relaxed "binocular"
    version of this allows RSM to differ for for observations in which
    the mast moves in the middle of a sequence to coregister eyes on the
    same target.
    """
    row = sequence
    if isinstance(sequence, pd.DataFrame):
        row = sequence.iloc[0]
    return {
        "SOL": row["SOL"],
        "SEQ_ID": row["SEQ_ID"].lower(),
        "SITE": row["RMC"][0],
        "DRIVE": row["RMC"][1],
        "RSM": row["RMC"][6],
        "ZOOM": row["ZOOM"],
    }


def make_pointing_name(pointing):
    parsed = parse_pointing(pointing.iloc[0])
    fields = [
        "SOL" + str(parsed["SOL"]).zfill(4),
        parsed["SEQ_ID"],
        "RSM" + str(parsed["RSM"]),
    ]
    pointing_name = "_".join(fields)
    return pointing_name


def parse_zcam_rc_fn(path):
    """
    parse rad-to-iof rc file filenames. these filenames are a variant of SIS
    standard: somewhat different layout, don't contain quite as much
    information. most notably, for our purposes, they don't list sol.

    this _shouldn't_ be necessary in the primary pipeline, because clear links
    should be present from each IOF file to the relevant rc files. But it is
    useful to scrape lots of rc files, etc., and more generally for
    completeness.
    """
    if Path(path).suffix == ".jpg":  # graphs of model fits
        return None
    split = tuple(filter(None, Path(path).stem.split("_")))
    return {
        "SITE": int(split[3][:3]),
        "DRIVE": int(split[3][3:7]),
        "SEQ_ID": split[3][7:16],
        "CTIME": int(split[2]),
        "FILTER": split[1],
        "VERSION": int(split[4]),
        "PRODUCT_TYPE": split[0].upper(),
        "PATH": str(path),
        "THUMBNAIL": False
    }


def parse_zcam_mosaic_fn(mosaic_fn):
    mosaic_path = Path(mosaic_fn)
    # multispectral mosaics
    try:
        parsed = parse_zcam_standard_image_fn(mosaic_path)
        parsed |= {
            "PRODUCT_TYPE": "mosaic",
            "MOSAIC_TYPE": "nonstrategic",
            # TODO: maybe not always?
            "MOSAIC_SUBTYPE": "multispectral",
            "LTST": "UNK"
        }
        # TODO: presumably there are others
        if "CYL" in mosaic_path.name:
            parsed["PROJ"] = "CYL"
        return parsed
    except KeyError:
        pass
    if not mosaic_path.name.startswith("CZ"):
        raise ValueError("unknown mosaic type.")
    # strategic mosaics
    parts = mosaic_path.stem.split("_")
    parsed = {
        "SOL": int(parts[1][3:]),
        "SITE": "UNK",
        "DRIVE": "UNK",
        "CTIME": -9999,
        "SEQ_ID": parts[2],
        "ZOOM": parts[3],
        "FILTER": parts[4],
        "UNKNOWN_2": parts[6],
        "PROJ": parts[7],
        "PATH": mosaic_path.absolute(),
        "PRODUCT_TYPE": "mosaic",
        "MOSAIC_TYPE": "strategic",
        "MOSAIC_SUBTYPE": parts[5],
        "THUMBNAIL": "N",
        "LTST": "UNK"
    }
    target_name = []
    for part in parts[8:]:
        if "flag" in part:
            parsed["FLAG"] = part
            parsed["MOSAIC_SUBTYPE"] += f"_{part}"
        elif part.isnumeric():
            parsed["VERSION"] = part
        else:
            target_name.append(part)
    if parsed["FILTER"] == "L0R0":
        parsed["MOSAIC_SUBTYPE"] += "_L0R0"
    return parsed | {"TARGET": "_".join(target_name)}


def parse_zcam_fn(path):
    """use mp.parse rules to get basic file identifiers"""
    path = Path(path)
    filename = path.name
    try:
        if filename.endswith("IMG") and (
            # strategic mosaics
            filename.startswith("CZ")
            # multispectral mosaics
            or (filename[-9:-6] == "LUQ")
            # TODO: presumably other projections can exist
            or (filename[-8:-5] == "CYL")
        ):
            return parse_zcam_mosaic_fn(path)
        if filename.startswith("rc_"):
            return parse_zcam_rc_fn(path)
        return parse_zcam_standard_image_fn(path)
    except (KeyError, IndexError, ValueError):
        return None


def parse_zcam_standard_image_fn(path):
    values = list(juxt(*ZCAM_FN_PARSERS.values())(path.name))
    # chop off currently not-used-as-specified stereo counter
    values[5] = values[5][1:]
    # just keep filter name, not SIS-nominal wavelength
    values[6] = values[6][:2]
    parsed = {
        field: value
        for field, value in zip(ZCAM_FN_PARSERS.keys(), values)
    }
    parsed["PATH"] = str(path)
    return parsed


def pix_reference(thing):
    """
    simple, dumb pixmap-naming function that doesn't die when you feed it a
    directory or whatever
    """
    try:
        return juxt(
            mp.secondary_timestamp,
            mp.color_filter,
            mp.sequence,
            mp.thumbnail,
            # TODO: version check appears too harsh at the moment but some
            #  kind of stricter association rule needs to be made
            #  mp.version,
        )(thing)
    except (KeyError, ValueError, FileNotFoundError):
        return None


def looks_like_marslab(fn):
    # TODO: Fail back to interrogating properties of the file contents.
    #  Michael notes: these functions are used primarily to scan directories.
    #  it will result in very, very slow operation if we have them also open
    #  every file in the search path. where they are *not* being used to scan
    #  directories, they are probably being inappropriately used and some other
    #  functions should replace them.
    return bool(
        ("marslab" in fn)
        and not ("extended" in fn)
        and not ("marslab_rc" in fn)
        and (fn.endswith(".csv"))
    )


def looks_like_roi(fn):
    # TODO: Fail back to interrogating properties of the file contents.
    return bool(("roi" in fn) and (".fits" in fn))
