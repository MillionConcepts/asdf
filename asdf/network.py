"""
functions for uploading, downloading, querying, fetching, etc.
TODO, maybe: consolidate utility-type functions into their own module
 and move top-level handlers to chatter?
"""
import datetime as dt
import io
import json
import os
import time
import urllib.request
from collections.abc import Callable, MutableMapping
from numbers import Number
from pathlib import Path
import socket
from typing import Any, Union

import boto3
import botocore.config
from boto3.exceptions import S3UploadFailedError
from botocore.exceptions import ClientError
import gspread
import pandas as pd
import pydrive2.files

# TODO: handling authentication differently in gspread and pydrive
#  is messy but expedient. it's possible that it will be more stable
#  and/or performant to merge these through a lower-level oauth call,
#  however, and this should be evaluated.
from googleapiclient.errors import HttpError
from oauth2client.service_account import ServiceAccountCredentials
from pydrive2.auth import GoogleAuth
from pydrive2.drive import GoogleDrive
from urllib3.connection import BaseSSLError

import asdf_settings as settings
from asdf.asdf_utils import obfuscated_name, tar_bytes
from dustgoggles.pivot import itemize_numpy
from asdf.console import ASDF_CONSOLE, aprint, ASDF_PROGRESS, ASDF_RPH, ASDFLOG
from asdf.format import md5sum
from asdf.zcam_bandset import ZcamBandSet


def get_public_m20_waypoints():
    waypoint_server_response = urllib.request.urlopen(
        settings.sources.PUBLIC_WAYPOINTS_URL, timeout=15
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


def stringify_unspreadsheetly_values(obj: Any):
    spreadsheetly_types = (Number, dt.datetime, str)
    return obj if isinstance(obj, spreadsheetly_types) else str(obj)


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
        + dataframe.fillna("-")
        .applymap(stringify_unspreadsheetly_values)
        .values.tolist(),
        value_input_option="USER_ENTERED"
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
    except ClientError as error:
        return error
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


def bind_asdf_bucket() -> Callable[[Any, str], Union[ClientError, bool]]:
    client = make_asdf_s3_client()
    bucket = settings.sources.BACKUP_BUCKET

    def upload_to_default_bucket(obj, key, pass_string=False):
        return upload_s3(bucket, obj, key, client, pass_string)

    return upload_to_default_bucket


def backup_data_to_s3(bandset, debug_prefix=""):
    upload = bind_asdf_bucket()
    epoch = str(round(time.time()))
    # TODO: why am I writing these like this?
    s3_prefix = (
        f"marslab/{debug_prefix}"
        f"{str(bandset.compact['SOL'].iloc[0]).zfill(4)}"
        f"/{epoch}_{os.getlogin()}_"
    )
    marslab_key = f"{s3_prefix}marslab_{bandset.name + bandset.suffix}.csv"
    extended_key = (
        f"{s3_prefix}marslab_extended_{bandset.name + bandset.suffix}.csv"
    )
    marslab, extended = bandset.write_data_files(in_memory=True)
    upload_hopper = [(marslab, marslab_key), (extended, extended_key)]
    for fn in bandset.local_files:
        if Path(fn).suffix in (".fits", ".fits.gz", ".sel"):
            upload_hopper.append((fn, s3_prefix + Path(fn).name))
    for obj, key in upload_hopper:
        try:
            upload(obj, key)
        except (ClientError, S3UploadFailedError) as error:
            aprint(
                "[bold red]sorry, couldn't upload a backup file: " + str(error)
            )
    # note: return value currently used only in tests
    return [key for obj, key in upload_hopper]


# TODO: don't tar this
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
    return DriveBot(gauth)


def bandset_gdrive_folder_names(bandset):
    sol_folder_name = f"""{str(bandset.compact["SOL"].iloc[0]).zfill(4)}"""
    obs_folder_name = (
        f"""{bandset.compact["SEQ_ID"].iloc[0]}"""
        + f""" {bandset.compact["NAME"].iloc[0]}"""
        + f""" {"RSM " + str(bandset.compact["RSM"].iloc[0])}"""
    )
    return sol_folder_name, obs_folder_name


class DriveBot(GoogleDrive):
    """
    convenience wrapper adding abstract pseudo-filesystem operations to
    a pydrive2 GoogleDrive object
    """

    # TODO: maybe consider doing this with one of the fs contrib things
    #  instead? so you can have a single gdrive / s3 interface? or perhaps
    #  combining it in some way with google sheets, maybe even dropping to
    #  lower-level API functions? or perhaps not.
    def mkdir(self, folder_name, parent_id):
        gdrive_folder = self.CreateFile(
            {
                "title": folder_name,
                "parents": [{"id": parent_id}],
                "mimeType": "application/vnd.google-apps.folder",
            }
        )
        gdrive_folder.Upload()
        folder_id = gdrive_folder["id"]
        return folder_id

    def cp(self, source_path, target_folder):
        upload = self.CreateFile(
            {
                "title": Path(source_path).name,
                "parents": [{"id": target_folder}],
            }
        )
        upload.SetContentFile(source_path)
        upload.Upload()

    def ls(self, folder_id):
        filelist = self.ListFile(
            {"q": "'{}' in parents".format(folder_id)}
        ).GetList()
        return filelist

    def get_checksums(self, folder_id, file_list=None):
        if file_list is None:
            file_list = self.ls(folder_id)
        return {
            file.get("title"): file.get("md5Checksum") for file in file_list
        }

    def cd(self, folder_name, parent_id):
        root_filelist = self.ls(parent_id)
        folder_list = [
            file for file in root_filelist if file["title"] == folder_name
        ]
        if folder_list:
            folder_id = folder_list[0]["id"]
        else:
            folder_id = self.mkdir(folder_name, parent_id)
        return folder_id


def upload_bandset_to_gdrive(bandset, debug=False):
    # reversing this list is a silly hack to make the progress timer
    # more realistic, because the smallest files (csv and fits.tar.gz)
    # will generally be at the front of the list.
    bandset.local_files.reverse()
    # id of root folder
    if debug is True:
        root = settings.sources.DEBUG_GOOGLE_DRIVE_ROOT
    else:
        root = settings.sources.GOOGLE_DRIVE_ROOT
    drivebot = make_asdf_pydrive_client()
    ASDFLOG.info("checking folder structure")
    sol_folder_name, obs_folder_name = bandset_gdrive_folder_names(bandset)
    # note: this may produce unexpected behavior if people dupe folders and
    # remove the default copy suffixes, etc.
    sol_folder_id = drivebot.cd(sol_folder_name, root)
    obs_folder_id = drivebot.cd(obs_folder_name, sol_folder_id)
    data_folder_id = drivebot.cd("data", obs_folder_id)
    browse_folder_id = drivebot.cd("browse", obs_folder_id)
    pixmap_folder_id = drivebot.cd("pixmaps", data_folder_id)
    aprint(f"uploading all files to {sol_folder_name}/{obs_folder_name}")
    title_checksum_dict = (
        drivebot.get_checksums(data_folder_id)
        | drivebot.get_checksums(pixmap_folder_id)
        | drivebot.get_checksums(browse_folder_id)
    )
    for file in bandset.local_files:
        if is_apparent_duplicate(file, title_checksum_dict):
            ASDFLOG.info(
                f"{file} appears to be an exact duplicate of an existing "
                "file on Google Drive, skipping"
            )
            continue
        ASDFLOG.info(f"uploading {file}")
        if "pixmap" in file:
            drivebot.cp(file, pixmap_folder_id)
        elif "data" in Path(file).parts:
            drivebot.cp(file, data_folder_id)
        elif "browse" in Path(file).parts:
            drivebot.cp(file, browse_folder_id)
    url = f"https://drive.google.com/drive/folders/{obs_folder_id}"
    bandset.summary[
        "NAME"
    ] = f"""=HYPERLINK("{url}", "{bandset.summary['NAME']}")"""


def is_apparent_duplicate(file, existing_title_checksums):
    if Path(file).name in existing_title_checksums.keys():
        if md5sum(file) == existing_title_checksums[Path(file).name]:
            return True
    return False


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
            pd.DataFrame(bandset.summary).T.applymap(itemize_numpy).fillna("-")
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
        # explicitly setting table_range is necessary to avoid a weird default
        # API behavior: if someone accidentally types a character somewhere
        # below the last row and this parameter is not set, the sheets will
        # treat that character's column as the first column of the table
        metadata_sheet.append_row(
            row_df.apply(itemize_numpy).tolist(),
            value_input_option="USER_ENTERED",
            table_range="A1:A99999",
        )
    aprint("completed metadata sheet update")


def upload_and_link_thumbnails(bandset, s3_debug_prefix, thumbnails):
    thumbnail_links = upload_thumbnails(
        thumbnails, bandset.name, s3_debug_prefix
    )
    if thumbnail_links:
        for name, link in thumbnail_links.items():
            bandset.summary[name] = '=IMAGE("' + link + '")'


def clear_google_drive_trash(debug=False):
    trash = settings.sources.GOOGLE_DRIVE_TRASH
    if trash is None:
        return
    drivebot = make_asdf_pydrive_client()
    trash_list = drivebot.ls(trash)
    if not trash_list:
        return
    aprint(f"... clearing {len(trash_list)} unneeded Drive files ...")
    with ASDF_PROGRESS as prog:
        task_id = prog.add_task("", total=len(trash_list))
        for drivefile in trash_list:
            try:
                drivefile.Delete()
            except (HttpError, pydrive2.files.ApiRequestError) as hte:
                if debug:
                    aprint(f"couldn't delete {drivefile['title']}: {hte}")
            prog.advance(task_id, 1)
        prog.remove_task(task_id)


# TODO: this and its precursors are excessively baroque. Consider turning
#  bandset.local_files into a dictionary to simplify this?
def upload_asdf_analysis(
    bandset: ZcamBandSet,
    thumbnails: MutableMapping,
    debug: bool = False,
):
    if debug is True:
        sheet_id = settings.sources.DEBUG_GOOGLE_SHEET_ID
        sheet_backup_folder_id = (
            settings.sources.DEBUG_METADATA_BACKUP_FOLDER_ID
        )
        s3_debug_prefix = "debug/"
    else:
        sheet_id = settings.sources.GOOGLE_SHEET_ID
        sheet_backup_folder_id = settings.sources.METADATA_BACKUP_FOLDER_ID
        s3_debug_prefix = ""
    with ASDF_CONSOLE.status(
        "... backing up marslab & ROI files ...", spinner="star"
    ):
        backup_data_to_s3(bandset, s3_debug_prefix)
    aprint("completed marslab and ROI backup")
    aprint("... uploading files to Google Drive space ...")
    with ASDF_PROGRESS as prog:
        ASDF_RPH.task_id = prog.add_task(
            "",
            total=len(bandset.local_files) + 1,
        )
        try:
            upload_bandset_to_gdrive(bandset, debug)
            aprint("completed Google Drive upload")
        except (pydrive2.files.ApiRequestError, socket.timeout) as api_error:
            aprint(
                ":confused_face: Sorry, couldn't upload files to drive: "
                + str(api_error),
                style="bold red",
            )
        prog.remove_task(ASDF_RPH.task_id)
    with ASDF_CONSOLE.status("handling google sheet", spinner="star"):
        try:
            upload_and_link_thumbnails(bandset, s3_debug_prefix, thumbnails)
            sheetbot = gspread.service_account(
                settings.sources.GOOGLE_CLIENT_SECRETS_FILE
            )
            update_google_sheet(
                bandset, sheet_backup_folder_id, sheet_id, sheetbot
            )
        except (
            gspread.exceptions.APIError,
            BaseSSLError,
            socket.timeout,
            gspread.exceptions.NoValidUrlKeyFound,
        ) as api_error:
            aprint(
                ":confused_face: Sorry, couldn't update online metadata: "
                + str(api_error),
                style="bold red",
            )
    aprint("... cleaning up trash ...")
    clear_google_drive_trash(debug)
