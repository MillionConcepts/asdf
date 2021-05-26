"""
settings for what metadata we both collect and write out. adding items to
these literals should generally be safe; removing them may not be.
TODO: perhaps it would be better to place unsafe items in a separate file?
"""

from itertools import chain
from types import MappingProxyType

from marslab.compat.xcam import make_xcam_filter_dict


# fields we want to ask the user about at each ROI.
ROI_METADATA_FIELDS = (
    "FLOAT",
    "FEATURE",
    "MORPHOLOGY",
    "SCAM",
    "TARGET",
    "DISTANCE",
    "WORKSPACE",
)
# special prompt text for these
ROI_METADATA_FIELD_PROMPTS = {
    "FLOAT": "Is the feature associated with {title} ROI a {field}?",
    "FEATURE": "What category of {field} is {title} ROI?",
    "MORPHOLOGY": "Which named {field} type does the rock in {title} "
    "ROI belong to?",
    "SCAM": "Is the area in {title} ROI also a {field} target?",
    "TARGET": "What named {field} does {title} ROI cover? "
              "(press Enter to skip)",
    "DISTANCE": "What {field} category does {title} ROI fall into?",
    "WORKSPACE": "What {field} is {title} ROI in?  (press Enter to skip)",
}
# restrictions, if any, on value choices for these ROIs.
ROI_METADATA_FIELD_CHOICES = {
    "FEATURE": [
        "rock",
        "soil",
        "pebble",
        "remnant",
        "delta",
        "hardware",
        "crater rim",
        "wheel track",
    ],
    "MORPHOLOGY": ["pitted", "paver", "massive"],
    "DISTANCE": ["nearfield", "midfield", "farfield"],
    "SCAM": ["Y", "N"],
    "FLOAT": ["Y", "N"]
}

# fields relevant only to rocks.
LITHOLOGICAL_ROI_FIELDS = ["MORPHOLOGY", "FLOAT"]

# TODO...implement lookup table for location by sol.
# right now just has the one.
# LOCATION_SOL_TABLE = {(0, None): "Octavia E. Butler Landing"}


# fields we put in the 'compact' marslab file. metadata fields are
# explicitly listed for easy modification; the *list(chain.from_iterable(...
# statement near the bottom adds the data fields based on our ZCAM instrument
# definition in marslab.compat.xcam.
COMPACT_ZCAM_MARSLAB_FIELDS = (
    "NAME",
    "COLOR",
    "ANALYSIS_NAME",
    "SOL",
    "SEQ_ID",
    *ROI_METADATA_FIELDS,
    "SITE",
    "DRIVE",
    "RMS",
    "ZOOM",
    "L_S",
    "SCLK",
    "SOLAR_ELEVATION",
    "INCIDENCE_ANGLE",
    "EMISSION_ANGLE",
    "PHASE_ANGLE",
    "LTST",
    "LAT",
    "LON",
    "ODOMETRY",
    "ROVER_ELEVATION",
    "TARGET_ELEVATION",
    "FILE_TIMESTAMP",
    "INSTRUMENT",
    "COMPRESSION",
    *list(
        chain.from_iterable(
            [
                (filt, filt + "_ERR")
                for filt in make_xcam_filter_dict("ZCAM").keys()
            ]
        )
    ),
)

# # metadata fields we want in the summary spreadsheet.
# # TODO: this is somewhat redundant with column-checking in the upload
# #  functions. assess.
# SUMMARY_COLUMNS = (
#     "NAME",
#     "SOL",
#     "SEQ_ID",
#     "SCLK",
#     "LMST",
#     "LTST",
#     "SOLAR_ELEVATION",
#     "INCIDENCE_ANGLE",
#     "INCIDENCE_AZIMUTH",
#     "EMISSION_ANGLE",
#     "EMISSION_AZIMUTH",
#     "PHASE_ANGLE",
#     "L_S",
#     "SITE",
#     "DRIVE",
#     "LAT",
#     "LON",
#     "ROVER_ELEVATION",
#     "ODOMETRY",
#     "ZOOM",
#     "CREATOR",
#     "FILE_TIMESTAMP",
#     "COMPRESSION",
# )


# regexes for yoinking label data from attached file headers without parsing
# the PVL. this structure defines _everything_ we look for in a label header.
IOF_METADATA_REGEX_STRINGS = MappingProxyType(
    {
        # the zoom motor count seems to be given several places in the label --
        # but the malin mini header line has other interesting contents
        "MINI_HEADER": r"(?<=ARTICULATION_DEV_POSITION ).*(\(.*\))",
        "FRAME_TYPE": r"(?<=FRAME_TYPE ).*?(\w+)",
        "RMC": r"(?<=ROVER_MOTION_COUNTER ).*(\(.*\))",
        "SEQ_ID": r"(?<=SEQUENCE_ID).*(zcam\d+)",
        "SOL": r"(?<=PLANET_DAY_NUMBER).*?(\d+)",
        "FILTER": r"FILTER_NAME.*ZCAM_([LR][\w\d])(?=_)",
        "IMAGE_TIME": r"(?<=IMAGE_TIME ).*?([\d\-T:]+)",
        "LTST": r"(?<=LOCAL_TRUE_SOLAR_TIME ).*?([\d:]+)",
        "LMST": r"(?<=LOCAL_MEAN_SOLAR_TIME ).*?M([\d:]+)",
        "PRODUCT_CREATION_TIME": r"(?<=PRODUCT_CREATION_TIME ).*?([\d\-T:]+)",
        "L_S": r"(?<=SOLAR_LONGITUDE ).*?([\d\.]+)",
        "COMPRESSION": r"(?<=INST_CMPRS_NAME ).*?(\w+)",
        "BAYER": r"(?<=BAYER_METHOD ).*?([\w_]+)",
        "SOLAR_ELEVATION": r"(?<=SOLAR_ELEVATION ).*?([\d\.]+)",
        "SOLAR_AZIMUTH": r"(?<=SOLAR_AZIMUTH ).*?([\d\.]+)",
        # note: starting sclk only
        "SCLK": r"(?<=SPACECRAFT_CLOCK_START_COUNT ).*?([\d\.]+)",
        "COMPLETION": r"(?<=PRODUCT_COMPLETION_STATUS ).*?([\w_]+)",
        # these files appear to currently be stored in
        # # /project/m2020/gds/radcal/effective_taus on islamorada
        "TAU_ESTIMATE_FILENAME": r"(?<=TAU_ESTIMATE_FILENAME).*?(\w+\.csv)",
        "INSTRUMENT_ELEVATION": r"(?<=INSTRUMENT_ELEVATION ).*?([\d\.]+)",
        "INSTRUMENT_AZIMUTH": r"(?<=INSTRUMENT_AZIMUTH ).*?([\d\.]+)",
    }
)



metadata_dtypes = {
    "SOL": "int16",
    "WAVELENGTH": "float16",
    "IX": "uint8",
    "SOLAR_ELEVATION": "float32",
    "INSTRUMENT_ELEVATION": "float32",
    "L_S": "float32",
    "INSTRUMENT_AZIMUTH": "float32",
    "SOLAR_AZIMUTH": "float32",
    "SCLK": "float64",
}
