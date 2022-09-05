"""
parser for "rc" responsivity-constant files used by the Mastcam-Z photometric
calibration pipeline
"""
from pathlib import Path

from cytoolz import valfilter
import pandas as pd

RC_FIELD_MAPPING = {
    "channel": "CHANNEL",
    "uncertainty": "UNCERTAINTY",
    "RC file format version": "FORMAT_VERSION",
    "local true solar time": "LTST",
    "RC file creation time": "CREATION_TIME",
    "responsivity constants file": "FULL_PATH",
    "associated selection filename": "SEL_FILE",
    "outliers excluded from selections": "OUTLIERS_EXCLUDED",
    "dust correction": "DUST_CORRECTION",
    "force fit to intercept origin": "FORCE_FIT",
    "cal-target file": "CALTARGET_FILE",
    "solar azimuth (rover frame)": "SOLAR_AZIMUTH",
    "solar elevation (rover frame)": "SOLAR_ELEVATION",
    "fit method": "FIT_METHOD",
    "camera id": "CAMERA_ID",
    "filter number": "FILTER_NUMBER",
    "rad-to-iof scaling factor": "SCALING_FACTOR",
}

RC_ROI_FIELD_MAPPING = {
    "is selected": "SELECTED",
    "marked bad": "BAD",
    "used in fit": "USED",
    "radiances": "RAD",
    "uncertainty": "ERR",
    "count": "COUNT",
    "incidence angle": "INCIDENCE_ANGLE",
    "emission angle": "EMISSION_ANGLE",
    "azimutih angle": "AZIMUTH_ANGLE",
    "reflectances": ""
}


def rc_typecast(string):
    if string.startswith('"'):
        return string.strip('"')
    for constructor in (int, float):
        try:
            return constructor(string)
        except ValueError:
            continue
    return string


def parse_terminal_line(terminal_line):
    headers, row = terminal_line.split("\n")
    headers = headers.split(", ")
    row = filter(None, row.split(" "))
    return {header: rc_typecast(value) for header, value in zip(headers, row)}


def parse_sequence_identifier(value):
    identifier = value.split("_")
    return {
        "SOL": int(identifier[0]),
        "SEQ_ID": identifier[1].upper(),
        "BOOT_COUNT": int(identifier[2])
        # TODO: what is the final value? ignoring for now.
    }


def parse_rc_line(rc_line):
    if rc_line.startswith("camera"):
        return parse_terminal_line(rc_line)
    parameter, value = rc_line.split(":", maxsplit=1)
    if parameter.startswith("unique sequence"):
        return parse_sequence_identifier(value)
    if "file format version" in parameter:
        putative_values = (value,)
    elif '"' in value:
        putative_values = value.split('"')
    else:
        putative_values = value.split(" ")
    raw_values = filter(None, map(str.strip, putative_values))
    values = tuple(map(rc_typecast, raw_values))
    if len(values) == 1:
        values = values[0]
    return {parameter: values}


def extract_roi_table(rc_roi_dict):
    table = pd.DataFrame.from_dict(rc_roi_dict, orient='index')
    table.index = table.index.str.replace("ROI", "").str.strip()
    table.columns = table.loc['names'].str.upper().str.replace(" ", "_").values
    table = table.drop('names')
    # TODO: find a way to notoverwrite all files l,ater
    names = RC_ROI_FIELD_MAPPING.copy()
    if 'azimuth angle' in table.index.to_list():
        names['azimuth angle'] = names['azimutih angle']
        del names['azimutih angle']
    return table.rename(index=names).T


def read_rc_file(rc_fn):
    with open(rc_fn) as file:
        rcfile = file.read()
    lines = filter(None, map(str.strip, rcfile.split("#")))
    parsed = {}
    for line in lines:
        parsed |= parse_rc_line(line)
    table_fields = valfilter(lambda v: isinstance(v, tuple), parsed)
    metadata = {}
    for k, v in parsed.items():
        if k in table_fields.keys():
            continue
        if k in RC_FIELD_MAPPING.keys():
            metadata[RC_FIELD_MAPPING[k]] = v
        else:
            metadata[k] = v
    table = extract_roi_table(table_fields)
    for angle in ["AZIMUTH_ANGLE", "EMISSION_ANGLE", "INCIDENCE_ANGLE"]:
        metadata[angle] = table[angle].loc["BLACK_CHIP_CENTER"]
    return table, metadata


def find_rc_file(rc_file, product_path):
    from asdf_settings import sources

    if rc_file is None:
        return

    sol_dir = Path(product_path).parent.parent
    search_dirs = [Path(sol_dir, "rc_files")]
    search_dirs += [
        Path(root, sol_dir.name, "rc_files") for root in sources.RC_ROOTS
    ]
    for search_dir in search_dirs:
        if Path(search_dir, rc_file).exists():
            return Path(search_dir, rc_file)
