from functools import partial
from pathlib import Path

TEST_CASE_WORKING_DIRECTORY = Path(__file__).parent
subdir = partial(Path, TEST_CASE_WORKING_DIRECTORY)
# TEST_SETTINGS_MODULE = subdir("asdf_settings")
E2E_DIRECTORY = subdir("e2e")
E2E_TEMP_DIRECTORY = subdir("e2e_temp")
ROI_DIRECTORY = subdir("rois")
CHECKSUM_DIRECTORY = subdir("checksums")
PRODUCT_DIRECTORY = subdir("products")
# TODO: generate this more nicely
TEST_CASES = {
    "SOL0086_SEQIDzcam03135_RMS92": {
        "type": "asdf e2e",
        "data_path": Path(PRODUCT_DIRECTORY, "0086", "iof"),
        "output_path": Path(E2E_DIRECTORY, "0086"),
        "temp_path": Path(E2E_TEMP_DIRECTORY, "0086"),
        "roi_path": Path(
            ROI_DIRECTORY,
            "SOL0086_SEQIDzcam03135_SITE4_DRIVE0_RMS92_ZOOM110-roi.fits.gz",
        ),
        "checksum_path": Path(
            CHECKSUM_DIRECTORY,
            "SOL0086_SEQIDzcam03135_RMS92_checksum.csv"
        ),
        "endpoint_kwargs": {"noninteractive": True, "debug": True},
    }
}
