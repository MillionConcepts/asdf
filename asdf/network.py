"""
functions for uploading, downloading, querying, fetching, etc.
"""
import datetime as dt
import json
import os
from pathlib import Path
import time
import urllib.request
import tarfile


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


def backup_marslab_files(metadata_fn, extended_metadata_fn, roi_fn=None):
    print("backing up marslab & ROI files.")
    client = make_asdf_s3_client()
    bucket = settings.sources.BACKUP_BUCKET
    epoch = round(time.time())
    marslab_key = (
        "marslab/" + str(epoch) + "_" + os.path.split(metadata_fn)[-1]
    )
    extended_marslab_key = (
        "marslab/" + str(epoch) + "_" + os.path.split(extended_metadata_fn)[-1]
    )
    try:
        upload_s3(bucket, metadata_fn, marslab_key, client)
        upload_s3(bucket, extended_metadata_fn, extended_marslab_key, client)
    except ClientError as error:
        print("sorry, couldn't upload marslab file backups: " + str(error))
    # TODO: clean this up; i.e., create iterable of closures of upload_s3
    if roi_fn is not None:
        tar_fn = (
            os.path.split(metadata_fn)[0]
            + "/"
            + os.path.split(roi_fn)[-1]
            + ".tar.gz"
        )
        tar = tarfile.open(tar_fn, "w:gz")
        tar.add(roi_fn, os.path.split(roi_fn)[-1])
        tar.close()
        roi_key = "marslab/" + str(epoch) + "_" + os.path.split(tar_fn)[-1]
        try:
            upload_s3(bucket, tar_fn, roi_key, client)
        except ClientError as error:
            print("sorry, couldn't upload ROI file backup: " + str(error))
        # os.remove(tar_fn)


def upload_thumbnails(thumbnails, pointing_name):
    if not thumbnails:
        return {}
    print("uploading thumbnails.")
    client = make_asdf_s3_client()
    bucket = settings.sources.BACKUP_BUCKET
    bucket_url = "https://" + bucket + ".s3.amazonaws.com/"
    links = {}
    for name, image_buffer in thumbnails.items():
        try:
            if settings.sources.OBFUSCATE_THUMBNAIL_NAMES:
                key = "thumb/" + obfuscated_name()
            else:
                key = name + "_thumb_" + pointing_name
            image_buffer.seek(0)
            upload_s3(bucket, image_buffer, key, client)
            links[name] = bucket_url + key
        except ClientError as error:
            print("sorry, couldn't upload thumb " + name + " " + str(error))
    return links


def upload_metadata(
    pointing_summary,
    thumbnails,
    pointing_name,
    metadata_fn,
    extended_metadata_fn,
    roi_fn=None,
):
    backup_marslab_files(metadata_fn, extended_metadata_fn, roi_fn)
    try:
        thumbnail_links = upload_thumbnails(thumbnails, pointing_name)
        if thumbnail_links:
            for name, link in thumbnail_links.items():
                pointing_summary[name] = '=IMAGE("' + link + '")'
        sheetbot = gspread.service_account(
            settings.sources.GOOGLE_CLIENT_SECRETS_FILE
        )
        metadata_sheet = sheetbot.open_by_key(
            settings.sources.GOOGLE_SHEET_ID
        ).worksheets()[0]
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
            post_google_sheet(
                new_sheet, settings.sources.GOOGLE_SHEET_ID, sheetbot
            )
        else:
            print("saving backup sheet")
            # TODO: when gspread implements this, replace it with .copy()
            backup = sheetbot.create(
                title="metadata backup " + dt.datetime.utcnow().isoformat(),
                folder_id=settings.sources.METADATA_BACKUP_FOLDER_ID,
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
