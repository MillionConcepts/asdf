import socket
from io import BytesIO, StringIO
from pathlib import Path
from random import randint
from unittest.mock import patch

import gspread
import pandas as pd
from dustgoggles.func import zero
from oauth2client.service_account import ServiceAccountCredentials
from pydrive2.auth import GoogleAuth

import asdf.network
from asdf.network import (
    update_google_sheet,
    upload_asdf_analysis,
    DriveBot,
    make_asdf_s3_client,
    backup_data_to_s3,
)
import asdf_settings as settings
from asdf_settings.generators import glom
from asdf_settings.sources import (
    DEBUG_METADATA_BACKUP_FOLDER_ID,
    DEBUG_GOOGLE_SHEET_ID,
    GOOGLE_CLIENT_SECRETS_FILE,
)


class VeryMockBandset:
    def __init__(self, summary):
        self.summary = summary
        self.compact = pd.DataFrame(summary.T)
        self.compact.columns = self.compact.iloc[0]
        self.compact.drop(self.compact.index[0], inplace=True)
        self.name = "test bandset"
        self.local_files = ["this.csv", "that.png", "the_other.fits.gz"]
        self.suffix = "test"

    def write_data_files(self, *args, **kwargs):
        return BytesIO(str(self.summary).encode('utf-8')), BytesIO(str(self.compact).encode('utf-8'))


SHEET_TEST_BANDSET = VeryMockBandset(
    pd.read_csv(
        Path(
            Path(__file__).parent,
            "data",
            "misc",
            "sheet_test_bandset_summary.csv",
        )
    )
)


def test_s3_upload():
    bandset = SHEET_TEST_BANDSET
    s3_keys = backup_data_to_s3(
        bandset,
        glom(
            Path(__file__).parent,
            "data",
            "rois",
            "SOL0046_SEQIDzcam03110_SITE3_DRIVE1416_RMS64_ZOOM034-lightpebbles-roi.fits.gz",
        ),
        "test/"
    )
    client = make_asdf_s3_client()
    api_response = client.list_objects_v2(
        Bucket=settings.sources.BACKUP_BUCKET,
        Prefix="marslab/test/0086/"
    )
    objects = [
        obj['Key'] for obj in api_response['Contents']
    ]
    assert all([s3_key in objects for s3_key in s3_keys])


#
# def test_sheet_upload():
#     bandset = SHEET_TEST_BANDSET
#     bandset.summary.index = bandset.summary.iloc[:, 0]
#     bandset.summary = bandset.summary.iloc[:, 1]
#     secret_number = randint(0, 100000000)
#     bandset.summary.loc["SCLK"] = secret_number
#     sheetbot = gspread.service_account(GOOGLE_CLIENT_SECRETS_FILE)
#     update_google_sheet(
#         bandset,
#         DEBUG_METADATA_BACKUP_FOLDER_ID,
#         DEBUG_GOOGLE_SHEET_ID,
#         sheetbot,
#     )
#     sheet = sheetbot.open_by_key(DEBUG_GOOGLE_SHEET_ID).worksheets()[0]
#     sheet_values = sheet.get_all_values()
#     sheetframe = pd.DataFrame(sheet_values[1:])
#     sheetframe.columns = sheet_values[0]
#     assert int(sheetframe["SCLK"].values[-1]) == secret_number
#
#
# def times_out():
#     gauth = GoogleAuth()
#     scope = ["https://www.googleapis.com/auth/drive"]
#     gauth.credentials = ServiceAccountCredentials.from_json_keyfile_name(
#         settings.sources.GOOGLE_CLIENT_SECRETS_FILE, scope
#     )
#     gauth.http_timeout = 0.001
#     return DriveBot(gauth)
#
#
# # noinspection PyTypeChecker
# def test_drive_upload_failure(capsys):
#     bandset = SHEET_TEST_BANDSET
#     broken = patch.object(asdf.network, "make_asdf_pydrive_client", times_out)
#     zeroed = [
#         patch.object(asdf.network, "backup_data_to_s3", zero),
#         patch.object(asdf.network, "upload_and_link_thumbnails", zero),
#         patch.object(asdf.network, "update_google_sheet", zero)
#         ]
#     broken.start()
#     for zeroer in zeroed:
#         zeroer.start()
#     try:
#         upload_asdf_analysis(bandset, [], "junk.fits.gz", debug=True)
#
#     except socket.timeout:
#         capture = capsys.readouterr()
#         assert "Sorry, couldn't upload files to drive: timed out" in capture.out
#         return
#     except Exception:
#         raise ValueError("failed the wrong way!")
#     raise ValueError("should have failed!")
