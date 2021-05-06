"""
functions for uploading, downloading, querying, fetching, etc.
"""
import datetime as dt
import json
import ssl
import urllib.request

import gspread
import pandas as pd
from oauth2client.service_account import ServiceAccountCredentials
from pydrive.auth import GoogleAuth
from pydrive.drive import GoogleDrive
from pydrive.files import ApiRequestError

from asdf.asdf_utils import itemize_numpy, obfuscated_name
from asdf.settings.sources import (
    PUBLIC_WAYPOINTS_URL,
    GOOGLE_CLIENT_SECRETS_FILE,
    GOOGLE_SHEET_ID,
    METADATA_BACKUP_FOLDER_ID,
    OBFUSCATE_THUMBNAIL_NAMES,
    THUMB_FOLDER_ID,
)


def get_public_m20_waypoints():
    waypoint_server_response = urllib.request.urlopen(PUBLIC_WAYPOINTS_URL)
    return json.loads(waypoint_server_response.read())["features"]


def gspread_credentials(credentials=None, service_account_file=None):
    """
    maybe unnecessary
    """
    if (credentials is None) and (service_account_file is None):
        raise ValueError("credentials or an account file must be provided")
    if credentials is None:
        credentials = gspread.service_account(service_account_file)
    return credentials


def get_google_sheet(
    sheet_id,
    credentials=None,
    service_account_file=None,
    worksheet_ix=0,
    convert_numeric=True,
):
    """maybe unnecessary"""
    credentials = gspread_credentials(credentials, service_account_file)
    worksheet = credentials.open_by_key(sheet_id).worksheets()[worksheet_ix]
    content = worksheet.get_all_values()
    if content:
        frame = pd.DataFrame(content[1:], columns=content[0])
        if convert_numeric:
            for column in frame.columns:
                frame[column] = pd.to_numeric(frame[column], errors="ignore")
        return frame

    return pd.DataFrame()


def post_google_sheet(
    dataframe,
    sheet_id,
    credentials=None,
    service_account_file=None,
    worksheet_ix=0,
):
    """maybe unnecessary"""
    credentials = gspread_credentials(credentials, service_account_file)
    spreadsheet = credentials.open_by_key(sheet_id)
    return spreadsheet.worksheets()[worksheet_ix].update(
        [dataframe.columns.values.tolist()]
        + dataframe.fillna("-").values.tolist()
    )


def upload_thumbnails(thumbnails, pointing_name):
    if not thumbnails:
        return {}
    print("uploading thumbnails.")
    gauth = GoogleAuth()
    scope = ["https://www.googleapis.com/auth/drive"]
    gauth.credentials = ServiceAccountCredentials.from_json_keyfile_name(
        GOOGLE_CLIENT_SECRETS_FILE, scope
    )
    drivebot = GoogleDrive(gauth)
    links = {}
    for name, image_buffer in thumbnails.items():
        try:
            if OBFUSCATE_THUMBNAIL_NAMES:
                title = obfuscated_name()
            else:
                title = name + "_thumb_" + pointing_name
            drivethumb = drivebot.CreateFile(
                {
                    "title": title,
                    "parents": [{"id": THUMB_FOLDER_ID}],
                }
            )
            drivethumb.content = image_buffer
            drivethumb.Upload()
            links[name] = drivethumb["thumbnailLink"]
        except (ssl.SSLError, ssl.SSLEOFError, ApiRequestError) as error:
            print("sorry, couldn't upload thumb " + error)
    return links


def upload_metadata(pointing_summary, thumbnails, pointing_name):
    try:
        thumbnail_links = upload_thumbnails(thumbnails, pointing_name)
        if thumbnail_links:
            for name, link in thumbnail_links.items():
                pointing_summary[name] = '=IMAGE("' + link + '")'
        sheetbot = gspread.service_account(GOOGLE_CLIENT_SECRETS_FILE)
        metadata_sheet = sheetbot.open_by_key(GOOGLE_SHEET_ID).worksheets()[0]
        metadata_sheet_values = metadata_sheet.get_all_values()
        # TODO: maybe just do this right in the first place
        pointing_summary["NAME"] = pointing_summary["NAME"].iloc[0]
        if len(metadata_sheet_values) == 0:
            print("note: existing metadata sheet contains no content")
            new_sheet = (
                pd.DataFrame(pointing_summary)
                .copy()
                .T.applymap(itemize_numpy)
                .fillna("-")
            )
            post_google_sheet(new_sheet, GOOGLE_SHEET_ID, sheetbot)
        else:
            print("saving backup sheet")
            # TODO: when gspread implements this, replace it with .copy()
            backup = sheetbot.create(
                title="metadata backup " + dt.datetime.utcnow().isoformat(),
                folder_id=METADATA_BACKUP_FOLDER_ID,
            )
            backup.worksheets()[0].update(metadata_sheet_values)
            print("posting new metadata")
            columns = metadata_sheet_values[0]
            pointing_summary = pointing_summary.reindex(columns).fillna("-")
            metadata_sheet.append_row(
                pointing_summary.apply(itemize_numpy).tolist(),
                value_input_option="USER_ENTERED",
            )
    except gspread.exceptions.APIError as api_error:
        print("Couldn't update online metadata: " + str(api_error))
