"""
This file contains settings for where to find files on a particular system.
It is shipped largely 'unpopulated' and should be overridden by values in
asdf_settings.user_sources to reflect the structure of a particular system.
"""

# must be True or False, no quotation marks
from .generators import ASDF_MODULE_PATH

USE_PUBLIC_WAYPOINTS = True
PUBLIC_WAYPOINTS_URL = (
    "https://mars.nasa.gov/mmgis-maps/M20/Layers/json/M20_waypoints.json"
)

FIND_EFFECTIVE_TAUS = False
# location in which to look for effective tau files. only necessary if
# FIND_EFFECTIVE_TAUS is True.
EFFECTIVE_TAU_PATH = None

# additional roots in which to look for 'metamap' products. Fill this out if
# you keep metmaps in a separate tree from primary data products.
META_ROOTS = []

# resolvers for asdf -a. Fill these out if you would like to use abbreviated
# paths on your system, like {"primary": "/path/to/sol/root"}. The first one
# will always be default and its name will not need to be explicitly specified.
PATH_ABBREVIATIONS = {}
DEFAULT_PRODUCT_SUBDIRECTORY = "iof"

# a little gibberish that finds the absolute path of the asdf directory
# on this system
GOOGLE_CLIENT_SECRETS_FILE = (
    ASDF_MODULE_PATH / "secrets" / "google_client_secrets.json"
)

# It is necessary to fill these out if you would like to use the upload
# feature. They correspond to the long alphanumeric codes in drive.google.com
# and sheets.google.com URLs.
GOOGLE_SHEET_ID = None
METADATA_BACKUP_FOLDER_ID = None
GOOGLE_DRIVE_ROOT = None
GOOGLE_SHARED_DRIVE_ID = None

# debug-mode locations for testing uploads without dirtying live content.
# necessary to fill these out if you would like to use upload in debug mode.
DEBUG_GOOGLE_SHEET_ID = None
DEBUG_METADATA_BACKUP_FOLDER_ID = None
DEBUG_GOOGLE_DRIVE_ROOT = None
DEBUG_GOOGLE_SHARED_DRIVE_ID = None

AWS_IAM_SECRETS_FILE = ASDF_MODULE_PATH / "secrets" / "s3_iam_secrets.csv"
# name and region of S3 bucket where we write backups of ROIs and marslab
# files. It is necessary to fill these out if you would like to use the
# upload feature.
BACKUP_BUCKET = None
AWS_REGION = None
# obfuscate names of uploaded thumbnails?
OBFUSCATE_THUMBNAIL_NAMES = True

