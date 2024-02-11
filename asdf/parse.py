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


MARSLAB_FN_PATTERN = re.compile(
    r"(?P<FTYPE>marslab|roi|space)"
    r"(_((?P<EYE>[LR])|(?P<FORMAT>extended|rc)))?"
    r"_SOL(?P<SOL>\d{4})"
    r"_(?P<SEQ_ID>\w+)"
    r"_RSM(?P<RSM>\d+)"
    r"(-(?P<ANALYSIS_NAME>.+?))?"
    r"\.(?P<EXTENSION>fits\.gz|fits|csv)"
)


def parse_marslab_fn(fn):
    fn = fn.name if isinstance(fn, Path) else fn
    parsed = MARSLAB_FN_PATTERN.search(fn).groupdict()
    if parsed['FTYPE'] == 'marslab' and parsed['FORMAT'] is None:
        parsed['FORMAT'] = 'compact'
    elif parsed['FTYPE'].startswith('space'):
        parsed['FTYPE'] = 'space'
    return parsed


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
        "PATH": str(path)
    }


def parse_zcam_fn(path):
    """use mp.parse rules to get basic file identifiers"""
    filename = Path(path).name
    try:
        if filename.startswith("rc_"):
            return parse_zcam_rc_fn(path)
        values = list(juxt(*ZCAM_FN_PARSERS.values())(filename))
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
    except (KeyError, IndexError, ValueError):
        return None


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
