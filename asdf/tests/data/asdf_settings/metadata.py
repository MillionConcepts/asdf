"""
settings for what metadata we both collect and write out. adding items to
these literals should generally be safe; removing them may not be.
"""

# don't change this
from itertools import chain

from .generators import FILTER_DATA_COLUMNS

# lookup table for location by sol -- number is final sol of location
LOCATION_TABLE = {
    101: "Octavia E. Butler Landing",
    99999: "Green Zone Campaign",
}
# these are always generated blank and intended to be populated manually when
# needed. we don't actually ask the user about them. they will, however,
# repopulate from saved files using fdsa.
EMPTY_METADATA_FIELDS = [
    "SCAM_LIBS",
    "SCAM_VISIR",
    "SCAM_RMI",
    "SCAM_RAMAN",
    "PIXL",
    "SHERLOC",
    "WATSON",
    "NOTES",
]

# fields relevant only to specific feature types. users will only be queried
# about these fields if they have set FEATURE = the key of the list. Don't put
# these before the FEATURE query or they'll never be asked about.
FEATURE_EXCLUSIVE_ROI_FIELDS = {
    "rock": ["MORPHOLOGY", "FLOAT", "ROCK SURFACE"],
    "soil": ["GRAIN SIZE", "SOIL LOCATION", "SOIL COLOR"],
    "landform": ["LANDFORM TYPE"],
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
    "TARGET",
    "DISTANCE",
    "WORKSPACE",
    "DESCRIPTION",
    *EMPTY_METADATA_FIELDS,
)

# special prompt text for these
# {title} is replaced with the title of the ROI, currently always its color
# {field} is replaced with the field name
ROI_METADATA_FIELD_PROMPTS = {
    "FLOAT": "Is / are the rock(s) associated with {title} ROI(s) a {field}?",
    "FEATURE": "What category of {field} is / are {title} ROI(s)?",
    "DESCRIPTION": "Enter any additional {field} {title} ROI(s) require(s) "
    "(press Enter to skip)",
    "MORPHOLOGY": "Which named {field} type do / does the rock in {title} "
    "ROI(s) belong to?",
    "TARGET": "What named {field} do / does {title} ROI(s) cover? "
    "(press Enter to skip)",
    "DISTANCE": "What {field} category do / does {title} ROI(s) fall into?",
    "WORKSPACE": "What {field} is / are {title} ROI(s) in? (press Enter to "
    "skip)",
}

# restrictions, if any, on value choices for these fields.
ROI_METADATA_FIELD_CHOICES = {
    "FEATURE": [
        "rock",
        "soil",
        "landform",
        "pebble",
        "hardware",
    ],
    "FLOAT": ["float", "in-place", "unclear"],
    "MORPHOLOGY": ["pitted", "paver", "massive", "layered"],
    "ROCK SURFACE": [
        "bright natural surface",
        "dark natural surface",
        "thick dust",
        "LIBS-cleared surface",
        "gDRT-cleared surface",
        "abraded surface",
        "coating (not dust)",
        "clast/inclusion",
    ],
    "GRAIN SIZE": ["fine", "coarse", "mixed"],
    "SOIL LOCATION": [
        "undisturbed regolith",
        "on rock",
        "wheel track/disturbed surface",
        "bedform slope",
        "bedform crest",
        "bedform trough",
        "on hardware",
    ],
    "SOIL COLOR": [
        "bright/dusty",
        "dark/neutral",
        "blueish/purplish",
        "reddish/orangeish",
    ],
    "LANDFORM TYPE": ["delta", "remnant", "Jezero rim"],
    "DISTANCE": ["nearfield", "midfield", "farfield"],
}

# Columns of the compact -marslab.csv file. columns not here won't appear in
# the compact version.
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
    "COMPRESSION_QUALITY",
    *FILTER_DATA_COLUMNS,
)

# statistical columns we add along with mean value to FILTER_DATA_COLUMNS
COMPACT_MARSLAB_STATS = ["ERR", "COUNT"]

# regexes for getting metadata from attached PDS3 product labels without
# parsing PVL. this structure defines almost everything we look for in a label.
IOF_METADATA_REGEX = {
    # the zoom motor count is given several places in the label,
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
    # note that JPEG compression is rendered as a negative number under
    # IMG_REQUEST_PARMS, which is why we're specifying the one from
    # COMPRESSION_PARMS here
    "COMPRESSION_QUALITY": r"(?:COMPRESSION_PARMS("
    r"?:\n|\r|.)*?INST_CMPRS_QUALITY ).*?([-\d]+)",
    "BAYER": r"(?<=BAYER_METHOD ).*?([\w_]+)",
    "SOLAR_ELEVATION": r"(?<=SOLAR_ELEVATION ).*?([\d\.]+)",
    "SOLAR_AZIMUTH": r"(?<=SOLAR_AZIMUTH ).*?([\d\.]+)",
    "SCLK": r"(?<=SPACECRAFT_CLOCK_START_COUNT ).*?([\d\.]+)",
    "COMPLETION": r"(?<=PRODUCT_COMPLETION_STATUS ).*?([\w_]+)",
    # TODO: check if they're in the headers now
    # these files appear to currently be stored in
    # # /project/m2020/gds/radcal/effective_taus on islamorada
    "TAU_ESTIMATE_FILENAME": r"(?<=TAU_ESTIMATE_FILENAME).*?(\w+\.csv)",
    "INSTRUMENT_ELEVATION": r"(?:SITE_DERIVED_GEOMETRY_PARMS("
    r"?:\n|\r|.)*?INSTRUMENT_ELEVATION ).*?(["
    r"-\d\.]+)",
    "INSTRUMENT_AZIMUTH": r"(?:SITE_DERIVED_GEOMETRY_PARMS("
    r"?:\n|\r|.)*?INSTRUMENT_AZIMUTH ).*?([-\d\.]+)",
}

PIXEL_FLAG_NAMES = ("bad", "no_signal", "nonlinear", "saturated", "hot")

PIXEL_FLAG_STYLE = (
    # (1, "#ff5fd7", "o"),
    (1, "#aa5fd7", "3"),
    (4, "#888888", "."),
    (0.2, "#87ff00", "o"),
    (7, "#00ffd7", "*"),
    (5, "#d7af00", "|"),
)
