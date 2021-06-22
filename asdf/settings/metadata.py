"""
settings for what metadata we both collect and write out. adding items to
these literals should generally be safe; removing them may not be.
"""

from asdf.settings.generators import FILTER_DATA_COLUMNS

# lookup table for location by sol
LOCATION_TABLE = {
    101: "Octavia E. Butler Landing",
    99999: "Green Zone Campaign",
}

# fields we want to ask the user about at each ROI. This order is preserved.
ROI_METADATA_FIELDS = (
    "FEATURE",
    "FLOAT",
    "MORPHOLOGY",
    "SCAM",
    "TARGET",
    "DISTANCE",
    "WORKSPACE",
)

# fields relevant only to rocks. users will only be queried about these fields
# if they have set FEATURE = rock. Don't put these before the FEATURE query
# or they'll never be asked about.
LITHOLOGICAL_ROI_FIELDS = ["MORPHOLOGY", "FLOAT"]

# special prompt text for these
ROI_METADATA_FIELD_PROMPTS = {
    "FLOAT": "Is / are the rock(s) associated with {title} ROI(s) a {field}?",
    "FEATURE": "What category of {field} is / are {title} ROI(s)?",
    "MORPHOLOGY": "Which named {field} type do / does the rock in {title} "
    "ROI(s) belong to?",
    "SCAM": "Is the area in {title} ROI(s) also a {field} target?",
    "TARGET": "What named {field} do / does {title} ROI(s) cover? "
    "(press Enter to skip)",
    "DISTANCE": "What {field} category do / does {title} ROI(s) fall into?",
    "WORKSPACE": "What {field} is / are {title} ROI(s) in? (press Enter to "
                 "skip)",
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
    "FLOAT": ["Y", "N"],
}

# TODO, once we have more locations: implement lookup table for LOCATION.
#  i.e. LOCATION_TABLE = {(0, None): "Octavia E. Butler Landing", ...}

# Columns of the compact -marslab.csv file.
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
    *FILTER_DATA_COLUMNS,
)

COMPACT_MARSLAB_STATS = ["ERR"]

# regexes for getting metadata from attached PDS3 product labels without
# parsing PVL. this structure defines almost everything we look for in a label.
IOF_METADATA_REGEX = {
    # the zoom motor count is to be given several places in the label,
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
    "SCLK": r"(?<=SPACECRAFT_CLOCK_START_COUNT ).*?([\d\.]+)",
    "COMPLETION": r"(?<=PRODUCT_COMPLETION_STATUS ).*?([\w_]+)",
    # TODO: check if they're in the headers now
    # these files appear to currently be stored in
    # # /project/m2020/gds/radcal/effective_taus on islamorada
    "TAU_ESTIMATE_FILENAME": r"(?<=TAU_ESTIMATE_FILENAME).*?(\w+\.csv)",
    "INSTRUMENT_ELEVATION": r"(?<=INSTRUMENT_ELEVATION ).*?([\d\.]+)",
    "INSTRUMENT_AZIMUTH": r"(?<=INSTRUMENT_AZIMUTH ).*?([\d\.]+)",
}

PIXEL_FLAG_NAMES = ("bad", "no_signal", "nonlinear", "saturated", "hot")

PIXEL_FLAG_STYLE = (
    # (1, "#ff5fd7", "o"),
    (1, "#aa5fd7", "3"),
    (4, "#f0fbfb", "."),
    (0.2, "#87ff00", "o"),
    (7, "#00ffd7", "*"),
    (5, "#d7af00", "|"),
)
