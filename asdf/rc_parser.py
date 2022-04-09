"""
parser for "rc" files used by the Mastcam-Z photometric calibration pipeline
"""
from cytoolz import valfilter
import pandas as pd

RC_FIELD_MAPPING = {
    "channel": "CHANNEL",
    "uncertainty": "UNCERTAINTY",
    "RC file format version": "FORMAT_VERSION",
    "local true solar time": "LTST",
    "unique sequence identifier": "SEQ_ID",
    "RC file creation time": "CREATION_TIME",
    "responsivity constants file": "FILE",
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
    "rad-to-iof scaling factor": "SCALING_FACTOR"
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
    "reflectances": "REF"
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


def parse_rc_line(rc_line):
    if rc_line.startswith("camera"):
        return parse_terminal_line(rc_line)
    parameter, value = rc_line.split(":", maxsplit=1)
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
    return table.rename(index=RC_ROI_FIELD_MAPPING).T


def read_rc_file(rc_fn):
    with open(rc_fn) as file:
        rcfile = file.read()
    lines = filter(None, map(str.strip, rcfile.split("#")))
    parsed = {}
    for line in lines:
        parsed |= parse_rc_line(line)
    table_fields = valfilter(lambda v: isinstance(v, tuple), parsed)
    metadata = {
        RC_FIELD_MAPPING[k]: v for k, v in parsed.items()
        if k not in table_fields.keys()
    }
    table = extract_roi_table(table_fields)
    for k, v in metadata.items():
        table[k] = v
    return table.copy()
