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
    "zcam03135_1": {
        "type": "asdf e2e",
        "input_product_path": Path(REFERENCE_INPUT_DIRECTORY, "0086", "iof"),
        "reference_output_path": Path(REFERENCE_OUTPUT_DIRECTORY, "0086"),
        "test_output_path": Path(TEST_OUTPUT_DIRECTORY, "0086"),
        "temp_output_path": Path(TEMP_OUTPUT_DIRECTORY, "0086"),
        "roi_path": Path(
            ROI_DIRECTORY,
            "SOL0086_SEQIDzcam03135_SITE4_DRIVE0_RMS92_ZOOM110-roi.fits.gz",
        ),
        "endpoint_kwargs": {"noninteractive": True, "debug": True},
    },
    "zcam03134": {
        "type": "asdf e2e",
        "input_product_path": Path(REFERENCE_INPUT_DIRECTORY, "0084", "iof"),
        "reference_output_path": Path(REFERENCE_OUTPUT_DIRECTORY, "0084"),
        "test_output_path": Path(TEST_OUTPUT_DIRECTORY, "0084"),
        "temp_output_path": Path(TEMP_OUTPUT_DIRECTORY, "0084"),
        "roi_path": Path(
            ROI_DIRECTORY,
            "SOL0084_SEQIDzcam03134_SITE3_DRIVE2430_RMS1480_ZOOM110"
            "-roi.fits.gz",
        ),
        "endpoint_kwargs": {"debug": True},
        "observation_choice": 2,
        "ignore_unspecified_inputs": True,
    },
    "zcam03175": {
        "type": "asdf e2e",
        "input_product_path": Path(REFERENCE_INPUT_DIRECTORY, "0130", "iof"),
        "reference_output_path": Path(REFERENCE_OUTPUT_DIRECTORY, "0130"),
        "test_output_path": Path(TEST_OUTPUT_DIRECTORY, "0130"),
        "temp_output_path": Path(TEMP_OUTPUT_DIRECTORY, "0130"),
        "roi_path": Path(
            ROI_DIRECTORY,
            "SOL0130_SEQIDzcam03175_SITE4_DRIVE2222_RMS112_ZOOM110"
            "-roi.fits.gz",
        ),
        "endpoint_kwargs": {"debug": True, "skip_rapidlooks": True},
        "ignore_unspecified_inputs": True,
    },
}
