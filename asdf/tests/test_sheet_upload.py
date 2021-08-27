from pathlib import Path
from random import randint

import gspread
import pandas as pd

from asdf.network import update_google_sheet
from asdf_settings.sources import (
    DEBUG_METADATA_BACKUP_FOLDER_ID,
    DEBUG_GOOGLE_SHEET_ID,
    GOOGLE_CLIENT_SECRETS_FILE,
)


class MockSummarizedBandset:
    def __init__(self, summary):
        self.summary = summary


def test_sheet_upload():
    bandset = MockSummarizedBandset(
        pd.read_csv(
            Path(
                Path(__file__).parent,
                "data",
                "misc",
                "sheet_test_bandset_summary.csv",
            )
        )
    )
    bandset.summary.index = bandset.summary.iloc[:, 0]
    bandset.summary = bandset.summary.iloc[:, 1]
    secret_number = randint(0, 100000000)
    bandset.summary.loc["SCLK"] = secret_number
    sheetbot = gspread.service_account(GOOGLE_CLIENT_SECRETS_FILE)
    update_google_sheet(
        bandset,
        DEBUG_METADATA_BACKUP_FOLDER_ID,
        DEBUG_GOOGLE_SHEET_ID,
        sheetbot,
    )
    sheet = sheetbot.open_by_key(DEBUG_GOOGLE_SHEET_ID).worksheets()[0]
    sheet_values = sheet.get_all_values()
    sheetframe = pd.DataFrame(sheet_values[1:])
    sheetframe.columns = sheet_values[0]
    assert int(sheetframe["SCLK"].values[-1]) == secret_number
