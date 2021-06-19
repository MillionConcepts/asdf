"""
functions for uploading, downloading, querying, fetching, etc.
TODO, maybe: consolidate utility-type functions into their own module
 and move top-level handlers to chatter?
"""
import datetime as dt
import io
import json
import logging
import os
import time
import urllib.request
from collections.abc import Callable, MutableMapping
from pathlib import Path
from typing import Any

import boto3
import botocore.config
from botocore.exceptions import ClientError
import gspread
import pandas as pd
import pydrive2.files

# TODO: handling authentication differently in gspread and pydrive
#  is messy but expedient. it's possible that it will be more stable
#  and/or performant to merge these through a lower-level oauth call,
#  however, and this should be evaluated.
from oauth2client.service_account import ServiceAccountCredentials
from pydrive2.auth import GoogleAuth
from pydrive2.drive import GoogleDrive

import asdf.settings as settings
from asdf.asdf_utils import itemize_numpy, obfuscated_name, tar_bytes
from asdf.console import ASDF_CONSOLE, aprint, ASDF_PROGRESS, ASDF_RPH, ASDFLOG
from asdf.format import md5sum
from asdf.zcam_bandset import ZcamBandSet


def get_public_m20_waypoints():
    waypoint_server_response = urllib.request.urlopen(
        settings.sources.PUBLIC_WAYPOINTS_URL
    )
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


def upload_s3(
    bucket,
    upload_object=None,
    object_name=None,
    client=None,
    pass_string=False,
):
    """Upload a file or buffer to an S3 bucket

    :param upload_object: String, pathlike, or filelike object to upload
    :param bucket: Bucket to upload to
    :param object_name: S3 object name. If not specified then str(
        file_or_buffer) is used -- will most likely look bad if it's a buffer
    :param client: botocore.client.S3 instance; makes a default client if None
    :param pass_string -- write passed string directly to file instead of
        interpreting as a path
    :return: ClientError if file was not uploaded, True if it was
    """
    if client is None:
        client = boto3.client("s3")

    # If S3 object_name was not specified, use string rep of
    # passed object, up to 90 characters
    if object_name is None:
        object_name = str(upload_object)

    # 'touch' - type behavior
    if upload_object is None:
        upload_object = io.BytesIO()

    # encode string to bytes if we're writing it to S3 object instead
    # of interpreting it as a path
    if isinstance(upload_object, str) and pass_string:
        upload_object = io.BytesIO(upload_object.encode("utf-8"))
    # Upload the file
    try:
        if isinstance(upload_object, (Path, str)):
            client.upload_file(str(upload_object), bucket, object_name)
        else:
            client.upload_fileobj(upload_object, bucket, object_name)
    except ClientError as e:
        return e
    return True


def make_asdf_s3_client():
    aws_config = botocore.config.Config(
        region_name=settings.sources.AWS_REGION
    )
    secrets = pd.read_csv(settings.sources.AWS_IAM_SECRETS_FILE).iloc[0]
    return boto3.client(
        "s3",
        aws_access_key_id=secrets["Access key ID"],
        aws_secret_access_key=secrets["Secret access key"],
        config=aws_config,
    )


def bind_asdf_bucket() -> Callable[Any, str]:
    client = make_asdf_s3_client()
    bucket = settings.sources.BACKUP_BUCKET

    def upload_to_default_bucket(obj, key, pass_string=False):
        return upload_s3(bucket, obj, key, client, pass_string)

    return upload_to_default_bucket


def backup_data_to_s3(bandset, roi_fits_fn, debug_prefix=""):
    upload = bind_asdf_bucket()
    epoch = str(round(time.time()))
    s3_prefix = "marslab/" + debug_prefix + epoch + "_" + os.getlogin() + "_"
    marslab_stem = bandset.name + bandset.suffix
    marslab_key = s3_prefix + marslab_stem + "-marslab.csv"
    extended_key = s3_prefix + marslab_stem + "-marslab-extended.csv"
    marslab, extended = bandset.write_data_files(in_memory=True)
    upload_hopper = [(marslab, marslab_key), (extended, extended_key)]
    if roi_fits_fn is not None:
        feed_into_hopper(roi_fits_fn, s3_prefix, upload_hopper)
    for obj, key in upload_hopper:
        try:
            upload(obj, key)
        except ClientError as error:
            aprint(
                "[bold red]sorry, couldn't upload a backup file: " + str(error)
            )


def feed_into_hopper(roi_fits_fn, s3_prefix, upload_hopper):
    fits_tar_key = s3_prefix + Path(roi_fits_fn).name.replace("fits", "tar.gz")
    tarbuffer = tar_bytes(roi_fits_fn)
    upload_hopper.append((tarbuffer, fits_tar_key))


def upload_thumbnails(thumbnails, pointing_name, debug_prefix):
    if not thumbnails:
        return {}
    aprint("... uploading thumbnails ...")
    upload = bind_asdf_bucket()
    bucket_url = (
        "https://" + settings.sources.BACKUP_BUCKET + ".s3.amazonaws.com/"
    )
    links = {}
    for name, image_buffer in thumbnails.items():
        try:
            if settings.sources.OBFUSCATE_THUMBNAIL_NAMES is True:
                key = "thumb/" + debug_prefix + obfuscated_name()
            else:
                key = "thumb/" + name + "_thumb_" + pointing_name
            image_buffer.seek(0)
            upload(image_buffer, key)
            links[name] = bucket_url + key
        except ClientError as error:
            aprint(
                "sorry, couldn't upload thumb " + name + " " + str(error),
                style="bold red",
            )
    return links


def make_asdf_pydrive_client():
    gauth = GoogleAuth()
    scope = ["https://www.googleapis.com/auth/drive"]
    gauth.credentials = ServiceAccountCredentials.from_json_keyfile_name(
        settings.sources.GOOGLE_CLIENT_SECRETS_FILE, scope
    )
    return GoogleDrive(gauth)


def bandset_gdrive_folder_name(bandset):
    folder_name = " ".join(
        [
            str(bandset.compact["SOL"].iloc[0]).zfill(4),
            bandset.compact["SEQ_ID"].iloc[0],
            bandset.compact["NAME"].iloc[0],
            "RMS " + str(bandset.compact["RMS"].iloc[0]),
        ]
    )
    return folder_name


def gdrive_cp(drivebot, source_path, target_folder):
    upload = drivebot.CreateFile(
        {
            "title": Path(source_path).name,
            "parents": [{"id": target_folder}],
        }
    )
    upload.SetContentFile(source_path)
    upload.Upload()


def gdrive_mkdir(drivebot, folder_name, parent):
    gdrive_folder = drivebot.CreateFile(
        {
            "title": folder_name,
            "parents": [{"id": parent}],
            "mimeType": "application/vnd.google-apps.folder",
        }
    )
    gdrive_folder.Upload()
    folder_id = gdrive_folder["id"]
    return folder_id


# TODO: maybe consider doing this with one of the fs contrib things instead?
#  so you can have a single gdrive / s3 interface? or perhaps not
def upload_bandset_to_gdrive(bandset, debug=False):
    if debug is True:
        root = settings.sources.DEBUG_GOOGLE_DRIVE_ROOT
    else:
        root = settings.sources.GOOGLE_DRIVE_ROOT
    drivebot = make_asdf_pydrive_client()
    filelist = gdrive_ls(drivebot, root)
    folder_name = bandset_gdrive_folder_name(bandset)
    # reversing this is a silly hack to make the progress timer
    # more realistic, because the smallest files (csv and ROI)
    # will generally be at the front of the list.
    bandset.local_files.reverse()
    aprint("uploading all files to " + folder_name)
    ASDFLOG.info("checking folder structure")
    existing_folders = [
        file for file in filelist if file["title"] == folder_name
    ]
    if existing_folders:
        # note: this may produce unexpected behavior if people dupe folders
        aprint("found existing folder")
        folder_id = existing_folders[0]["id"]
        existing_title_checksums = {
            file.get("title"): file.get("md5Checksum")
            for file in gdrive_ls(drivebot, folder_id)
        }
    else:
        aprint("created new google drive folder")
        folder_id = gdrive_mkdir(drivebot, folder_name, root)
        existing_title_checksums = {}

    for file in bandset.local_files:
        if is_apparent_duplicate(file, existing_title_checksums):
            ASDFLOG.info(
                file + " appears to be an exact duplicate of an existing "
                "file on Google Drive, skipping"
            )
            continue
        ASDFLOG.info("uploading " + file)
        gdrive_cp(drivebot, file, folder_id)


def is_apparent_duplicate(file, existing_title_checksums):
    if Path(file).name in existing_title_checksums.keys():
        if md5sum(file) == existing_title_checksums[Path(file).name]:
            return True
    return False


def gdrive_ls(drivebot, root):
    filelist = drivebot.ListFile(
        {"q": "'{}' in parents".format(root)}
    ).GetList()
    return filelist


def update_google_sheet(bandset, folder_id, sheet_id, sheetbot):
    aprint("... opening metadata sheet ...")
    metadata_sheet = sheetbot.open_by_key(sheet_id).worksheets()[0]
    metadata_sheet_values = metadata_sheet.get_all_values()
    if len(metadata_sheet_values) == 0:
        aprint(
            "note: existing metadata sheet contains no content.",
            style="bold dark_orange",
        )
        new_sheet = (
            bandset.summary.copy().T.applymap(itemize_numpy).fillna("-")
        )
        post_google_sheet(new_sheet, sheet_id, sheetbot)
    else:
        aprint("... backing up metadata sheet ...")
        # TODO: when gspread implements this, replace it with .copy()
        backup = sheetbot.create(
            title="metadata backup " + dt.datetime.utcnow().isoformat(),
            folder_id=folder_id,
        )
        backup.worksheets()[0].update(metadata_sheet_values)
        aprint("... posting new metadata ...")
        columns = metadata_sheet_values[0]
        row_df = bandset.summary.reindex(columns).fillna("-")
        metadata_sheet.append_row(
            row_df.apply(itemize_numpy).tolist(),
            value_input_option="USER_ENTERED",
            table_range="A1:A9999",
        )
    aprint("completed metadata sheet update")


def upload_and_link_thumbnails(bandset, s3_debug_prefix, thumbnails):
    thumbnail_links = upload_thumbnails(
        thumbnails, bandset.name, s3_debug_prefix
    )
    if thumbnail_links:
        for name, link in thumbnail_links.items():
            bandset.summary[name] = '=IMAGE("' + link + '")'


def upload_asdf_analysis(
    bandset: ZcamBandSet,
    thumbnails: MutableMapping,
    roi_fits_fn: str,
    debug: bool = False,
):
    if debug is True:
        sheet_id = settings.sources.DEBUG_GOOGLE_SHEET_ID
        folder_id = settings.sources.DEBUG_METADATA_BACKUP_FOLDER_ID
        s3_debug_prefix = "debug/"
    else:
        sheet_id = settings.sources.GOOGLE_SHEET_ID
        folder_id = settings.sources.METADATA_BACKUP_FOLDER_ID
        s3_debug_prefix = ""
    with ASDF_CONSOLE.status(
        "... backing up marslab & ROI files ...", spinner="star"
    ):
        backup_data_to_s3(bandset, roi_fits_fn, s3_debug_prefix)
    aprint("completed marslab and ROI backup")
    with ASDF_CONSOLE.status("handling google sheet", spinner="star"):
        try:
            upload_and_link_thumbnails(bandset, s3_debug_prefix, thumbnails)
            sheetbot = gspread.service_account(
                settings.sources.GOOGLE_CLIENT_SECRETS_FILE
            )
            update_google_sheet(bandset, folder_id, sheet_id, sheetbot)
        except gspread.exceptions.APIError as api_error:
            aprint(
                ":confused_face: Sorry, couldn't update online metadata: "
                + str(api_error),
                style="bold red",
            )
    aprint("... uploading files to Google Drive space ...")
    with ASDF_PROGRESS as prog:
        ASDF_RPH.task_id = prog.add_task(
            "",
            total=len(bandset.local_files) + 1,
        )
        try:
            upload_bandset_to_gdrive(bandset, debug)
            aprint("completed Google Drive upload")
        except pydrive2.files.ApiRequestError as api_error:
            aprint(
                ":confused_face: Sorry, couldn't upload files to drive: "
                + str(api_error),
                style="bold red",
            )
        prog.remove_task(ASDF_RPH.task_id)
