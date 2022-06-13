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
METADATA_BACKUP_FOLDER_ID = "1CDoFWK4secmEaxN42poaK3oA-QSu7JOG"
GOOGLE_DRIVE_ROOT = "110wJGkFyqx9cWZJjLs08lYntTRskKFOh"
GOOGLE_DRIVE_TRASH = "1Oq5aW86qVxG0NyesV3u9q8X10EpD-j8-"

AWS_IAM_SECRETS_FILE = glom(ASDF_MODULE_PATH, "secrets", "s3_iam_secrets.csv")
BACKUP_BUCKET = "g4452h324"
AWS_REGION = "us-east-1"
OBFUSCATE_THUMBNAIL_NAMES = True

# debug-mode locations for testing uploads without dirtying live content
# DEBUG_GOOGLE_SHEET_ID = "18r9wBG9rnVGQOv7XglqsZJmXK7ebBupLAJxHAIr_uH8"
# DEBUG_METADATA_BACKUP_FOLDER_ID = "1pqP4Ohdsc8ACTh9EQ1HAvjFyL11fgiXE"
# DEBUG_GOOGLE_DRIVE_ROOT = "1Fv7oKhwdz3pu4FCzvLVLUkcfx7VFX1Rx"

# 'staging' locations
DEBUG_GOOGLE_SHEET_ID = "16Xznv0YodjvneaBN8-5mSNSbsR6NJIpWK2vFbW4ncEU"
DEBUG_METADATA_BACKUP_FOLDER_ID = "182dVJ1WKMdTSBrn4mqFl-UZBOijT8qvC"
DEBUG_GOOGLE_DRIVE_ROOT = "1bpgoxWdFcckJgMQg8ww96VcoopuJuJ1V"
