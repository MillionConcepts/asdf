"""
settings for what metadata we both collect and write out. adding items to
these literals should generally be safe; removing them may not be.
"""

# don't change this
from itertools import chain

from .metagenerators import FILTER_DATA_COLUMNS

# lookup table for location by sol -- number is final sol of location
LOCATION_TABLE = {
    101: "Octavia E. Butler Landing",
    99999: "Green Zone Campaign",
}
# these are always generated blank and intended to be populated manually when
# needed. we don't actually ask the user about them. they will, however,
# repopulate from saved files using fdsa.
EMPTY_METADATA_FIELDS = ["NOTES"]

# we don't ask users about these, or even generate them, but do repopulate
# them during FDSA runs.
LEGACY_METADATA_FIELDS = [
    "SOIL_COLOR",
    "LANDFORM TYPE",
    "WORKSPACE",
    "TARGET",
    "DISTANCE",
]

# fields relevant only to specific feature types. users will only be queried
# about these fields if they have set FEATURE = the key of the list. Don't put
# these before the FEATURE query or they'll never be asked about.
FEATURE_EXCLUSIVE_ROI_FIELDS = {
    # similarly, for the special MEMBER selection behavior to work, FORMATION
    # needs to come before MEMBER in this list.
    "rock": ["FORMATION", "MEMBER", "MORPHOLOGY", "FLOAT", "ROCK_SURFACE"],
    "soil": ["GRAIN_SIZE", "SOIL_LOCATION"],
}
# don't mess with this statement if you want to be able to use exclusive_fields
# later. it pulls all the lists out of FEATURE_EXCLUSIVE_ROI_FIELDS
exclusive_fields = list(
    chain.from_iterable(FEATURE_EXCLUSIVE_ROI_FIELDS.values())
)

# fields we want to ask the user about at each ROI. This order is preserved.
# the asterisk is a shorthand for "insert all of these fields at this position"
ROI_METADATA_FIELDS = (
    "FEATURE",
    *exclusive_fields,
    "DESCRIPTION",
    *EMPTY_METADATA_FIELDS,
    *LEGACY_METADATA_FIELDS,
)

# special prompt text for these
# {title} is replaced with the title of the ROI, currently always its color
# {field} is replaced with the field name
ROI_METADATA_FIELD_PROMPTS = {
    "FLOAT": "Is / are the rock(s) associated with {title} ROI(s) a {field}?",
    "FEATURE": "What category of {field} is / are {title} ROI(s)?",
    "DESCRIPTION": "Enter any additional {field} for {title} ROI(s)"
    "(press Enter to skip)",
    "MORPHOLOGY": "Which named {field} type do / does the rock in {title} "
    "ROI(s) belong to?",
    "TARGET": "What named {field} do / does {title} ROI(s) cover? "
    "(press Enter to skip)",
    "GRAIN_SIZE": "What is the {field} of the soil in {title} ROI? Skip if "
    "the soil is too distant to tell. (press Enter to skip)",
    "FORMATION": "What {field} do / does {title} ROI(s) belong to?",
    "MEMBER": "What {field} of their parent formation do / does {title} ROIs "
    "belong to?",
}

# restrictions, if any, on value choices for these fields.
ROI_METADATA_FIELD_CHOICES = {
    "FEATURE": ["rock", "soil", "pebble", "hardware"],
    "FLOAT": ["float", "in-place", "unclear"],
    "MORPHOLOGY": ["pitted", "paver", "massive", "layered"],
    "FORMATION": ["Maaz", "Seitah"],
    "MEMBER": {
        "Maaz": ["Chal", "Nataani", "Rochette", "Artuby", "Roubion"],
        "Seitah": ["Content", "Bastide", "Issole"],
    },
    "ROCK_SURFACE": [
        "bright natural surface",
        "dark natural surface",
        "thick dust",
        "LIBS-cleared surface",
        "gDRT-cleared surface",
        "abraded surface",
        "coating (not dust)",
        "clast/inclusion",
        "tailings",
    ],
    "GRAIN_SIZE": [
        "fine (grains not resolvable)",
        "coarse (grains resolvable)",
        "mixed",
    ],
    "SOIL_LOCATION": [
        "undisturbed regolith",
        "on rock",
        "wheel track compressed",
        "wheel track disturbed",
        "disturbed surface (not wheel track)",
        "bedform crest/slope",
        "on hardware",
    ],
}

# Only the columns listed here will appear in the compact -marslab.csv file.
# Their order here is preserved in the .csv file.
# *ROI_METADATA_FIELDS are the user-input fields defined above.
# *FILTER_DATA_COLUMNS are the per-filter mean/std pixel count columns.
COMPACT_ZCAM_MARSLAB_FIELDS = (
    "NAME",
    "COLOR",
    "ANALYSIS_NAME",
    "SOL",
    "SEQ_ID",
    *ROI_METADATA_FIELDS,
    "LOCATION",
    "SITE",
    "DRIVE",
    "RSM",
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
    "CREATOR",
    "FILE_TIMESTAMP",
    "ROI_SOURCE",
    "ORIGINAL_ROI_SOURCE",
    "INSTRUMENT",
    "COMPRESSION",
    "COMPRESSION_QUALITY",
    *FILTER_DATA_COLUMNS,
    "ROW",
    "COLUMN",
    "DET_RAD",
    "DET_THETA",
)

# statistical columns we add along with mean value to FILTER_DATA_COLUMNS
COMPACT_MARSLAB_STATS = ["ERR", "COUNT"]


# mapping from field names to label parameters.

# this structure defines almost everything we look for in a label

# format of label keys / parameters (values of this dictionary):
# if they're strings, we just grab the first matching parameter
# using Metadata.metablock.
# they can also be mappings with key names "keys" and "regex".
# "keys" can be used to specify a hierarchy of keys -- for instance, if azimuth
# angle is given twice in the label, in two separate coordinate frames, and
# you would like it from one of those in particular.
# "regex" is used to peel a specific portion of a value from the label out --
# say, the filter's labeled name is 'ZCAM_R1_800NM' but our internal
# canonical name for that filter is simply 'R1'.
# the first capturing group of the regular expression is assigned to the
# BandSet's metadata.
# if we receive dicts from any queries, we assume they are parsed pvl.
IOF_METADATA_FIELDS = {
    # the zoom motor count is given several places in the label,
    # but the malin mini header line has other interesting contents
    "MINI_HEADER": "ARTICULATION_DEV_POSITION",
    "FRAME_TYPE": "FRAME_TYPE",
    "RMC": "ROVER_MOTION_COUNTER",
    "SEQ_ID": "SEQUENCE_ID",
    "SOL": "PLANET_DAY_NUMBER",
    "FILTER": {
        "keys": ("INSTRUMENT_STATE_PARMS", "FILTER_NAME",),
        "regex": r"ZCAM_([LR][\w\d])(?=_)"
    },
    # prior version cut the milliseconds, but I think unnecessarily
    "IMAGE_TIME": "IMAGE_TIME",
    "LTST": "LOCAL_TRUE_SOLAR_TIME",
    "LMST": {"keys": ("LOCAL_MEAN_SOLAR_TIME",), "regex": r"\d\d:.*"},
    # prior version cut the milliseconds, but I think unnecessarily
    "PRODUCT_CREATION_TIME": "PRODUCT_CREATION_TIME",
    "L_S": "SOLAR_LONGITUDE",
    "COMPRESSION": "INST_CMPRS_NAME",
    # JPEG compression is rendered as a negative number under
    # IMG_REQUEST_PARMS, so we specify the one from COMPRESSION_PARMS here
    "COMPRESSION_QUALITY": {
        'keys': ('COMPRESSION_PARMS', 'INST_CMPRS_QUALITY')
    },
    "BAYER": "BAYER_METHOD",
    "SOLAR_ELEVATION": "SOLAR_ELEVATION",
    "SOLAR_AZIMUTH": "SOLAR_AZIMUTH",
    "SCLK": "SPACECRAFT_CLOCK_START_COUNT",
    "COMPLETION": "PRODUCT_COMPLETION_STATUS",
    # TODO: check if they're in the headers now
    # these files appear to currently be stored in
    # # /project/m2020/gds/radcal/effective_taus on islamorada
    "TAU_ESTIMATE_FILENAME": "TAU_ESTIMATE_FILENAME",
    "INSTRUMENT_ELEVATION": {
        "keys": ("SITE_DERIVED_GEOMETRY_PARMS", "INSTRUMENT_ELEVATION")
    },
    "INSTRUMENT_AZIMUTH": {
        "keys": ("SITE_DERIVED_GEOMETRY_PARMS", "INSTRUMENT_AZIMUTH")
    },
    "INPUT_PRODUCT_ID": "INPUT_PRODUCT_ID",
    # subframe parameters to be assembled later
    "FIRST_LINE": "FIRST_LINE",
    "FIRST_LINE_SAMPLE": "FIRST_LINE_SAMPLE",
    "LINES": "LINES",
    "LINE_SAMPLES": "LINE_SAMPLES"
}

# # regexes for getting metadata from attached PDS3 product labels without
# # parsing PVL. this structure defines almost everything we look for in a label.
# IOF_METADATA_REGEX = {
#     # the zoom motor count is given several places in the label,
#     # but the malin mini header line has other interesting contents
#     "MINI_HEADER": r"(?<=ARTICULATION_DEV_POSITION ).*(\(.*\))",
#     "FRAME_TYPE": r"(?<=FRAME_TYPE ).*?(\w+)",
#     "RMC": r"(?<=ROVER_MOTION_COUNTER ).*(\(.*\))",
#     "SEQ_ID": r"(?<=SEQUENCE_ID).*(zcam\d+)",
#     "SOL": r"(?<=PLANET_DAY_NUMBER).*?(\d+)",
#     "FILTER": r"FILTER_NAME.*ZCAM_([LR][\w\d])(?=_)",
#     "IMAGE_TIME": r"(?<=IMAGE_TIME ).*?([\d\-T:]+)",
#     "LTST": r"(?<=LOCAL_TRUE_SOLAR_TIME ).*?([\d:]+)",
#     "LMST": r"(?<=LOCAL_MEAN_SOLAR_TIME ).*?M([\d:]+)",
#     "PRODUCT_CREATION_TIME": r"(?<=PRODUCT_CREATION_TIME ).*?([\d\-T:]+)",
#     "L_S": r"(?<=SOLAR_LONGITUDE ).*?([\d\.]+)",
#     "COMPRESSION": r"(?<=INST_CMPRS_NAME ).*?(\w+)",
#     # note that JPEG compression is rendered as a negative number under
#     # IMG_REQUEST_PARMS, which is why we're specifying the one from
#     # COMPRESSION_PARMS here
#     "COMPRESSION_QUALITY": r"(?:COMPRESSION_PARMS("
#     r"?:\n|\r|.)*?INST_CMPRS_QUALITY ).*?([-\d]+)",
#     "BAYER": r"(?<=BAYER_METHOD ).*?([\w_]+)",
#     "SOLAR_ELEVATION": r"(?<=SOLAR_ELEVATION ).*?([\d\.]+)",
#     "SOLAR_AZIMUTH": r"(?<=SOLAR_AZIMUTH ).*?([\d\.]+)",
#     "SCLK": r"(?<=SPACECRAFT_CLOCK_START_COUNT ).*?([\d\.]+)",
#     "COMPLETION": r"(?<=PRODUCT_COMPLETION_STATUS ).*?([\w_]+)",
#     # TODO: check if they're in the headers now
#     # these files appear to currently be stored in
#     # # /project/m2020/gds/radcal/effective_taus on islamorada
#     "TAU_ESTIMATE_FILENAME": r"(?<=TAU_ESTIMATE_FILENAME).*?(\w+\.csv)",
#     "INSTRUMENT_ELEVATION": r"(?:SITE_DERIVED_GEOMETRY_PARMS("
#     r"?:\n|\r|.)*?INSTRUMENT_ELEVATION ).*?(["
#     r"-\d\.]+)",
#     "INSTRUMENT_AZIMUTH": r"(?:SITE_DERIVED_GEOMETRY_PARMS("
#     r"?:\n|\r|.)*?INSTRUMENT_AZIMUTH ).*?([-\d\.]+)",
# }
# quantities and take the value of their 'value' keys, ignoring 'units'.

# Define the types of pixel flags that we care about
PIXEL_FLAG_NAMES = ("bad", "no_signal", "nonlinear", "saturated", "hot")

# Define the size, color, and symbol for flagged pixels
PIXEL_FLAG_STYLE = (
    # (1, "#ff5fd7", "o"),
    (1, "#aa5fd7", "3"),  # bad
    (4, "#888888", "."),  # no_signal
    (0.2, "#87ff00", "o"),  # nonlinear
    (7, "#00ffd7", "*"),  # saturated
    (5, "#d7af00", "|"),  # hot
)
