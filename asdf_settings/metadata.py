"""
settings for what metadata we both collect and write out. adding items to
these literals should generally be safe; removing them may not be.
"""

# don't change this
from itertools import chain

# these are intended to be populated manually when needed. we don't actually
# ask the user about autogenerate them. fdsa will, however, propagate them.
# TODO: this may be completely legacy at this point; checl.
EMPTY_METADATA_FIELDS = ["NOTES"]

# these are old fields that should never be used in new files. we do repopulate
# them during FDSA runs.
LEGACY_METADATA_FIELDS = [
    "SOIL_COLOR",
    "LANDFORM TYPE",
    "WORKSPACE",
    "TARGET",
    "MORPHOLOGY"
]

# TODO: this can be removed shortly
# treat these fields as "FEATURE_SUBTYPE" during fdsa
LEGACY_SUBTYPE_FIELDS = ["ROCK_SURFACE", "SOIL_LOCATION"]

# fields relevant only to specific feature types. users will only be queried
# about these fields if they have set FEATURE = the key of the list.
FEATURE_EXCLUSIVE_ROI_FIELDS = {
    # similarly, for the special MEMBER selection behavior to work, FORMATION
    # needs to come before MEMBER in this list.
    "rock": ["FEATURE_SUBTYPE", "FORMATION", "MEMBER", "FLOAT"],
    "soil": ["FEATURE_SUBTYPE", "GRAIN_SIZE"],
}

# don't mess with this statement if you want to be able to use exclusive_fields
# later. it pulls all the lists out of FEATURE_EXCLUSIVE_ROI_FIELDS
exclusive_fields = sorted(
    set(
        chain.from_iterable(FEATURE_EXCLUSIVE_ROI_FIELDS.values())
    )
)

# defines ROIs that depend on answers to other fields. For each key-value pair,
# we will never attempt to ask the user about the field corresponding to the
# key before the field corresponding to the value.
CONDITIONAL_FIELDS = {k: 'FEATURE' for k in exclusive_fields} | {
    'MEMBER': 'FORMATION',
}

# fields we could ask the user about at each ROI. This order is preserved
# except as necessary to ensure the ordering of CONDITIONAL_FIELDS.
# the asterisk is shorthand for "insert all of these fields at this position".
ROI_METADATA_FIELDS = (
    "FEATURE",
    *exclusive_fields,
    "DISTANCE",
    "DESCRIPTION",
    *EMPTY_METADATA_FIELDS,
    *LEGACY_METADATA_FIELDS,
    *LEGACY_SUBTYPE_FIELDS
)

# special prompt text for these
# {title} is replaced with the title of the ROI, currently always its color
# {field} is replaced with the field name
ROI_METADATA_FIELD_PROMPTS = {
    "FEATURE": "What category of {field} is / are {title} ROI(s)?",
    "FEATURE_SUBTYPE": "What category of {field} is / are {title} ROI(s)?",
    "FLOAT": "Is / are the rock(s) associated with {title} ROI(s) a {field}?",
    "DESCRIPTION": "Enter any additional {field} for {title} ROI(s)"
    "(press Enter to skip)",
    "TARGET": "What named {field} do / does {title} ROI(s) cover? "
    "(press Enter to skip)",
    "GRAIN_SIZE": "What is the {field} of the soil in {title} ROI? Skip if "
    "the soil is too distant to tell. (press Enter to skip)",
    "FORMATION": "What {field} do / does {title} ROI(s) belong to?",
    "MEMBER": "What {field} of their parent formation do / does {title} ROIs "
    "belong to?",
    "DISTANCE": "What {field} category do / does {title} ROI(s) fall into?",
}

FEATURE_SUBTYPES = {
    "soil": (
        "undisturbed regolith",
        "on rock",
        "wheel track compressed",
        "wheel track disturbed",
        "disturbed surface (not wheel track)",
        "bedform crest/slope",
        "on hardware",
    ),
    "rock": (
        "bright natural surface",
        "dark natural surface",
        "thick dust",
        "LIBS-cleared surface",
        "gDRT-cleared surface",
        "abraded surface",
        "coating (not dust)",
        "clast/inclusion",
        "tailings",
        "wheel scuffed surface",
    )
}

# restrictions, if any, on value choices for these fields.
ROI_METADATA_FIELD_CHOICES = {
    "FEATURE": ["rock", "soil", "pebble", "hardware"],
    "FLOAT": ["float", "in-place", "unclear"],
    "FORMATION": [
        "Maaz", "Seitah", "delta", "margin unit", "Neretva Vallis", "Crater Rim"
    ],
    "MEMBER": {
        "Maaz": ["Chal", "Nataani", "Rochette", "Artuby", "Roubion"],
        "Seitah": ["Content", "Bastide", "Issole"],
    },
    "GRAIN_SIZE": [
        "fine (grains not resolvable)", "coarse (grains resolvable)", "mixed",
    ],
    "DISTANCE": ["nearfield", "midfield", "farfield"],
}

RC_METADATA_COLUMNS = (
    "CALTARGET_FILE",
    "SOL",
    "SEQ_ID",
    "LTST",
    "SOLAR_AZIMUTH",
    "INCIDENCE_ANGLE",
    "AZIMUTH_ANGLE",
    "EMISSION_ANGLE",
    "SCALING_FACTOR",
    "UNCERTAINTY",
    "SEL_FILE"
)

# Only the metadata fields here will appear in the compact -marslab.csv file.
# *ROI_METADATA_FIELDS are the user-input fields defined above.
COMPACT_ZCAM_MARSLAB_FIELDS = (
    "NAME",
    "COLOR",
    "ANALYSIS_NAME",
    "SOL",
    "SEQ_ID",
    "FEATURE",
    "DESCRIPTION",
    "SITE",
    "DRIVE",
    "RSM",
    "LTST",
    "INCIDENCE_ANGLE",
    "EMISSION_ANGLE",
    "PHASE_ANGLE",
    "SOLAR_ELEVATION",
    "SOLAR_AZIMUTH",
    "LAT",
    "LON",
    "ODOMETRY",
    "ROVER_ELEVATION",
    "TARGET_ELEVATION",
    "INSTRUMENT",
    "SCLK",
    *ROI_METADATA_FIELDS,
    # TODO: determine if this moves somewhere else or if we always
    #  automatically populate caltarget element
    "CALTARGET_ELEMENT",
    "ZOOM",
    "L_S",
    "SOLAR_ELEVATION",
    "SOLAR_AZIMUTH",
    # TODO: RC-file value. ?
    "AZIMUTH_ANGLE",
    "CREATOR",
    "FILE_TIMESTAMP",
    "ROI_SOURCE",
    "ORIGINAL_ROI_SOURCE",
    "COMPRESSION",
    "COMPRESSION_QUALITY",
    "ROW",
    "COLUMN",
    "DET_RAD",
    "DET_THETA",
    *[f"RC_{col}" for col in RC_METADATA_COLUMNS],
    "FORMAT_VERSION",
)

# statistical/metadata columns we add along with mean value to
# FILTER_DATA_COLUMNS
COMPACT_MARSLAB_STATS = [
    "STD", "COUNT", "W", "H", "HW", "A", "D", "I", "E", "P"
]

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
    "SOURCE_PRODUCT_ID": "SOURCE_PRODUCT_ID",
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
    "SCLK": "SPACECRAFT_CLOCK_START_COUNT",
    "COMPLETION": "PRODUCT_COMPLETION_STATUS",
    "INPUT_PRODUCT_ID": "INPUT_PRODUCT_ID",
    "RC_FILE": "RC_FILE",
    # subframe parameters to be assembled later
    "FIRST_LINE": "FIRST_LINE",
    "FIRST_LINE_SAMPLE": "FIRST_LINE_SAMPLE",
    "LINES": "LINES",
    "LINE_SAMPLES": "LINE_SAMPLES",
    "CALTARGET_LTST": "CALTARGET_LTST",
    "SOFTWARE_VERSION_ID": "SOFTWARE_VERSION_ID",
    "SPICE_FILE_NAME": "SPICE_FILE_NAME"
}

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
