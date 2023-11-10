# must be True or False, no quotation marks
from .generators import ASDF_MODULE_PATH, glom

USE_PUBLIC_WAYPOINTS = True
PUBLIC_WAYPOINTS_URL = (
    "https://mars.nasa.gov/mmgis-maps/M20/Layers/json/M20_waypoints.json"
)

FIND_EFFECTIVE_TAUS = True
EFFECTIVE_TAU_PATH = "/project/m2020/gds/radcal/effective_taus/"

META_ROOTS = ["/scratch/cal_wg/flight/products/"]

# resolvers for asdf -a
PATH_ABBREVIATIONS = {
    "proj": "/project/m2020/mastcamz/surface/flight/products",
    "scratch": "/scratch/cal_wg/flight/products/",
}
DEFAULT_PRODUCT_SUBDIRECTORY = "iof"

# a little gibberish that finds the absolute path of the asdf directory
# on this system
GOOGLE_CLIENT_SECRETS_FILE = glom(
    ASDF_MODULE_PATH, "secrets", "google_client_secrets.json"
)
GOOGLE_SHEET_ID = "1jpqxmu0kc0W4aMq1uswrOSljeotFCxf_Zl8SxdE4xKQ"
METADATA_BACKUP_FOLDER_ID = "1-nbgqasqLbfmnn68FE0o1W8gFm-zKPT9"
GOOGLE_DRIVE_ROOT = "1WuvGtj3DAxH2yDALAmqm-HqkQmI-M-17"
GOOGLE_SHARED_DRIVE_ID = "0APqiZpxj6EYeUk9PVA"

AWS_IAM_SECRETS_FILE = glom(ASDF_MODULE_PATH, "secrets", "s3_iam_secrets.csv")
BACKUP_BUCKET = "g4452h324"
AWS_REGION = "us-east-1"
OBFUSCATE_THUMBNAIL_NAMES = True

# debug-mode locations for testing uploads without dirtying live content
DEBUG_GOOGLE_SHEET_ID = "15f3Cjvfz7AUjpY6BciRY1OjEw9vUdoMe6g8WQAbT1Yc"
DEBUG_METADATA_BACKUP_FOLDER_ID = "1w6SwfC3yd_h6tUbRzhJBBZ1Mmr31QtMG"
DEBUG_GOOGLE_DRIVE_ROOT = "1VJtmgETE7T4HSLziehDEdVkhUetMbwQI"
DEBUG_GOOGLE_SHARED_DRIVE_ID = "0ALWRvwRESb26Uk9PVA"

OLD_CUTOFF = 87000
