from functools import partial
from pathlib import Path

TEST_CASE_WORKING_DIRECTORY = Path(__file__).parent
subdir = partial(Path, TEST_CASE_WORKING_DIRECTORY)
# TEST_SETTINGS_MODULE = subdir("asdf_settings")
ROI_DIRECTORY = subdir("rois")
# CHECKSUM_DIRECTORY = subdir("checksums")
REFERENCE_INPUT_DIRECTORY = subdir("input_products")
REFERENCE_OUTPUT_DIRECTORY = subdir("reference_output")
TEST_OUTPUT_DIRECTORY = subdir("test_output")
TEMP_OUTPUT_DIRECTORY = subdir("temp_output")
# TODO: generate this more nicely
TEST_CASES = {
    "SOL0086_SEQIDzcam03135_RMS92": {
        "type": "asdf e2e",
        "input_product_path": Path(REFERENCE_INPUT_DIRECTORY, "0086", "iof"),
        "reference_output_path": Path(REFERENCE_OUTPUT_DIRECTORY, "0086"),
        "test_output_path": Path(TEST_OUTPUT_DIRECTORY, "0086"),
        "temp_output_path": Path(TEMP_OUTPUT_DIRECTORY, "0086"),
        "roi_path": Path(
            ROI_DIRECTORY,
            "SOL0086_SEQIDzcam03135_SITE4_DRIVE0_RMS92_ZOOM110-roi.fits.gz",
        ),
        # "checksum_path": Path(
        #     CHECKSUM_DIRECTORY,
        #     "SOL0086_SEQIDzcam03135_RMS92_checksum.csv"
        # ),
        "endpoint_kwargs": {"noninteractive": True, "debug": True},
    }
}
