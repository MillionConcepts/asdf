USE_PUBLIC_WAYPOINTS = True
PUBLIC_WAYPOINTS_URL = (
    "https://mars.nasa.gov/mmgis-maps/M20/Layers/json/M20_waypoints.json"
)
FIND_EFFECTIVE_TAUS = True
EFFECTIVE_TAU_PATH = "/project/m2020/gds/radcal/effective_taus/"

# abbreviated path settings
PATH_ABBREVIATIONS = {
    'here': "/home/michael/Desktop/zcam_data/",
    'scratch': "/scratch/cal_wg/flight/products/",
    "proj": "/project/m2020/mastcamz/surface/flight/products",
}
DEFAULT_PRODUCT_SUBDIRECTORY = 'iof'


GOOGLE_CLIENT_SECRETS_FILE = "asdf/secrets/google_client_secrets.json"
GOOGLE_SHEET_ID = "1mUg_gsvOuB5FACW9BEDEIXEpPtXewOC3-l5NHj_LN9Q"
METADATA_BACKUP_FOLDER_ID = "1iu-AS6pv924f_zN9t4HjlV6qaqRYtu46"

AWS_IAM_SECRETS_FILE = "asdf/secrets/s3_iam_secrets.csv"
BACKUP_BUCKET = "g4452h324"
AWS_REGION = 'us-east-1'
OBFUSCATE_THUMBNAIL_NAMES = True

DEBUG_GOOGLE_SHEET_ID = "1G7T3Xb63wkdsOWJY4qaYDkFghjRqHvUaAwHpsBbrqSY"
DEBUG_METADATA_BACKUP_FOLDER_ID = "1pqP4Ohdsc8ACTh9EQ1HAvjFyL11fgiXE"
