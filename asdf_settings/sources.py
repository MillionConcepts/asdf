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
GOOGLE_SHEET_ID = "19Qwm1rKctb807YrWt1l3t81vMpPpuoEjQxpuuiu1e1o"
METADATA_BACKUP_FOLDER_ID = "1-nbgqasqLbfmnn68FE0o1W8gFm-zKPT9"
GOOGLE_DRIVE_ROOT = "1WuvGtj3DAxH2yDALAmqm-HqkQmI-M-17"

AWS_IAM_SECRETS_FILE = glom(ASDF_MODULE_PATH, "secrets", "s3_iam_secrets.csv")
BACKUP_BUCKET = "g4452h324"
AWS_REGION = "us-east-1"
OBFUSCATE_THUMBNAIL_NAMES = True

# debug-mode locations for testing uploads without dirtying live content
DEBUG_GOOGLE_SHEET_ID = "19Qwm1rKctb807YrWt1l3t81vMpPpuoEjQxpuuiu1e1o"
DEBUG_METADATA_BACKUP_FOLDER_ID = "1-nbgqasqLbfmnn68FE0o1W8gFm-zKPT9"
DEBUG_GOOGLE_DRIVE_ROOT = "1WuvGtj3DAxH2yDALAmqm-HqkQmI-M-17"
