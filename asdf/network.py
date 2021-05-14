"""
functions for uploading, downloading, querying, fetching, etc.
"""
import datetime as dt
import json
import os
from collections.abc import Callable
from pathlib import Path
import time
import urllib.request
import tarfile
from typing import Any

import boto3
import botocore.config
from botocore.exceptions import ClientError
import gspread
import io
import pandas as pd

from asdf.asdf_utils import itemize_numpy, obfuscated_name
import asdf.settings as settings


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
    file_or_buffer) is
        used -- will most likely look bad if it's a buffer
    :param client: botocore.client.S3 instance; makes a default s3 client if
    None
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
    if isinstance(upload_object, str):
        if pass_string:
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
    client = boto3.client(
        "s3",
        aws_access_key_id=secrets["Access key ID"],
        aws_secret_access_key=secrets["Secret access key"],
        config=aws_config,
    )
    return client


def bind_asdf_bucket() -> Callable[Any, str]:
    client = make_asdf_s3_client()
    bucket = settings.sources.BACKUP_BUCKET

    def upload_to_default_bucket(obj, key, pass_string=False):
        return upload_s3(bucket, obj, key, pass_string, client)

    return upload_to_default_bucket


def backup_marslab_files(bandset, roi_fits_fn, debug_prefix=""):
    print("backing up marslab & ROI files.")
    upload = bind_asdf_bucket()
    epoch = str(round(time.time()))
    s3_prefix = "marslab/" + debug_prefix + epoch + "_" + os.getlogin() + "_"
    marslab_stem = bandset.name + bandset.suffix
    marslab_key = s3_prefix + marslab_stem + "-marslab.csv"
    extended_key = s3_prefix + marslab_stem + "-marslab-extended.csv"
    marslab, extended = bandset.write_data_files()
    upload_hopper = [(marslab, marslab_key), (extended, extended_key)]
    if roi_fits_fn is not None:
        # TODO: is this going to create some kind of weird upload permissions
        #  issue? keep an eye on this
        fits_tar_key = os.path.split(roi_fits_fn)[-1].replace("fits", "tar.gz")
        tarbuffer = io.BytesIO()
        fits_tar = tarfile.open(fileobj=tarbuffer, mode="w:gz")
        fits_tar.add(roi_fits_fn, os.path.split(roi_fits_fn)[-1])
        fits_tar.close()
        upload_hopper.append((fits_tar, fits_tar_key))
    for obj, key in upload_hopper:
        try:
            upload(obj, key)
        except ClientError as error:
            print("sorry, couldn't upload a backup file: " + str(error))


def upload_thumbnails(thumbnails, pointing_name, debug_prefix):
    if not thumbnails:
        return {}
    print("uploading thumbnails.")
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
            print("sorry, couldn't upload thumb " + name + " " + str(error))
    return links


def upload_asdf_analysis(bandset, thumbnails, roi_fits_fn, debug=False):
    if debug is True:
        sheet_id = settings.sources.DEBUG_GOOGLE_SHEET_ID
        folder_id = settings.sources.DEBUG_METADATA_BACKUP_FOLDER_ID
        s3_debug_prefix = "debug/"
    else:
        sheet_id = settings.sources.GOOGLE_SHEET_ID
        folder_id = settings.sources.METADATA_BACKUP_FOLDER_ID
        s3_debug_prefix = ""
    backup_marslab_files(bandset, roi_fits_fn, s3_debug_prefix)
    try:
        thumbnail_links = upload_thumbnails(
            thumbnails, bandset.name, s3_debug_prefix
        )
        if thumbnail_links:
            for name, link in thumbnail_links.items():
                bandset.summary[name] = '=IMAGE("' + link + '")'
        sheetbot = gspread.service_account(
            settings.sources.GOOGLE_CLIENT_SECRETS_FILE
        )
        metadata_sheet = sheetbot.open_by_key(sheet_id).worksheets()[0]
        metadata_sheet_values = metadata_sheet.get_all_values()
        if len(metadata_sheet_values) == 0:
            print("note: existing metadata sheet contains no content")
            new_sheet = (
                bandset.summary.copy().T.applymap(itemize_numpy).fillna("-")
            )
            post_google_sheet(new_sheet, sheet_id, sheetbot)
        else:
            print("saving backup sheet")
            # TODO: when gspread implements this, replace it with .copy()
            backup = sheetbot.create(
                title="metadata backup " + dt.datetime.utcnow().isoformat(),
                folder_id=folder_id,
            )
            backup.worksheets()[0].update(metadata_sheet_values)
            print("posting new metadata")
            columns = metadata_sheet_values[0]
            row_df = bandset.summary.reindex(columns).fillna("-")
            metadata_sheet.append_row(
                row_df.apply(itemize_numpy).tolist(),
                value_input_option="USER_ENTERED",
            )
    except gspread.exceptions.APIError as api_error:
        print("Couldn't update online metadata: " + str(api_error))
