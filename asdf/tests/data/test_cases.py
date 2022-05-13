from functools import partial
from pathlib import Path

TEST_CASE_WORKING_DIRECTORY = Path(__file__).parent
subdir = partial(Path, TEST_CASE_WORKING_DIRECTORY)
# TEST_SETTINGS_MODULE = subdir("asdf_settings")
ROI_DIRECTORY = subdir("rois")
# CHECKSUM_DIRECTORY = subdir("checksums")
REFERENCE_INPUT_DIRECTORY = subdir("input_products")
REFERENCE_OUTPUT_DIRECTORY = subdir("reference_output")
FDSA_OUTPUT_DIRECTORY = subdir("fdsa_test_output")
TEST_OUTPUT_DIRECTORY = subdir("test_output")
TEMP_OUTPUT_DIRECTORY = subdir("temp_output")
TEST_CASES = {
    "zcam03175": {
        "type": "asdf e2e",
        "directory_name": "0130",
        "roi_path": Path(
            ROI_DIRECTORY,
            "SOL0130_SEQIDzcam03175_SITE4_DRIVE2222_RMS112_ZOOM110"
            "-roi.fits.gz",
        ),
        "endpoint_kwargs": {"debug": True},
        "ignore_unspecified_inputs": True,
    },
    "zcam03134": {
        "type": "asdf e2e",
        "directory_name": "0084",
        "roi_path": Path(
            ROI_DIRECTORY,
            "SOL0084_SEQIDzcam03134_SITE3_DRIVE2430_RMS1480_ZOOM110"
            "-roi.fits.gz",
        ),
        "endpoint_kwargs": {"debug": True},
        "observation_choice": 2,
        "ignore_unspecified_inputs": True,
    },
    "zcam03135_1": {
        "type": "asdf e2e",
        "directory_name": "0086",
        "roi_path": Path(
            ROI_DIRECTORY,
            "SOL0086_SEQIDzcam03135_SITE4_DRIVE0_RMS92_ZOOM110-roi.fits.gz",
        ),
        "endpoint_kwargs": {"noninteractive": True, "debug": True},
    },
    "zcam03175_missing_filters": {
        "type": "asdf e2e",
        "directory_name": "0130_mf",
        "roi_path": Path(
            ROI_DIRECTORY,
            "SOL0130_SEQIDzcam03175_SITE4_DRIVE2222_RMS112_ZOOM110"
            "-roi.fits.gz",
        ),
        "endpoint_kwargs": {"debug": True},
        "ignore_unspecified_inputs": True,
    },
    "zcam03153": {
        "type": "asdf e2e",
        "directory_name": "0106",
        "roi_path": Path(ROI_DIRECTORY, "hastaa_2_of_3_rois_02.sel"),
        "endpoint_kwargs": {"debug": True, "noninteractive": True},
    },
    "zcam03153_left_eye": {
        "type": "asdf e2e",
        "directory_name": "0106_le",
        "roi_path": Path(ROI_DIRECTORY, "hastaa_2_of_3_rois_02.sel"),
        "endpoint_kwargs": {"debug": True, "noninteractive": True},
    },
    "zcam03014": {
        "type": "asdf e2e",
        "directory_name": "0073",
        "roi_path": None,
        "endpoint_kwargs": {
            "debug": True,
            "noninteractive": True,
            "keep_caltarget": True,
        },
    },
    "zcam03110_no_clear": {
        "type": "asdf e2e",
        "directory_name": "0046",
        "roi_path": Path(
            ROI_DIRECTORY,
            "SOL0046_SEQIDzcam03110_SITE3_DRIVE1416_RMS64_ZOOM034-"
            "lightpebbles-roi.fits.gz",
        ),
        "endpoint_kwargs": {"debug": True, "suffix": "lightpebbles"},
        "ignore_unspecified_inputs": True,
    },
    "zcam03110_clear_only": {
        "type": "asdf e2e",
        "directory_name": "0046_co",
        "roi_path": Path(
            ROI_DIRECTORY,
            "SOL0046_SEQIDzcam03110_SITE3_DRIVE1416_RMS64_ZOOM034-"
            "lightpebbles-roi.fits.gz",
        ),
        "endpoint_kwargs": {
            "debug": True,
            "keep_broadband": True,
            "suffix": "lightpebbles",
        },
        "ignore_unspecified_inputs": True,
    },
    "zcam03207_thumbs": {
        "type": "asdf e2e",
        "directory_name": "0178",
        "roi_path": None,
        "endpoint_kwargs": {"debug": True, "keep_thumbnails": True},
        "ignore_unspecified_inputs": True,
    },
    "bad_sel": {
        "type": "asdf bad input",
        "input_product_path": Path(REFERENCE_INPUT_DIRECTORY, "0086", "iof"),
        "test_output_path": Path(TEST_OUTPUT_DIRECTORY, "0086_bad_sel"),
        "roi_path": Path(ROI_DIRECTORY, "bad.sel"),
        "endpoint_kwargs": {"noninteractive": True, "debug": True},
        "we_should_mention": "something is wrong with the passed ROI file",
    },
    "zero_file": {
        "type": "asdf bad input",
        "input_product_path": Path(
            REFERENCE_INPUT_DIRECTORY, "0178_zero", "iof"
        ),
        "test_output_path": Path(TEST_OUTPUT_DIRECTORY, "0178_zero"),
        "roi_path": None,
        "endpoint_kwargs": {
            "noninteractive": True,
            "debug": True,
            "keep_thumbnails": True,
        },
        "we_should_mention": "only 13 / 14 could be opened and read",
    },
}

for case_name, rules in TEST_CASES.items():
    if "directory_name" not in rules.keys():
        continue
    for path_type, root in (
        ("input_product_path", REFERENCE_INPUT_DIRECTORY),
        ("test_output_path", TEST_OUTPUT_DIRECTORY),
        ("reference_output_path", REFERENCE_OUTPUT_DIRECTORY),
        ("temp_output_path", TEMP_OUTPUT_DIRECTORY),
        ("fdsa_test_output_path", FDSA_OUTPUT_DIRECTORY),
    ):
        if path_type in rules.keys():
            continue
        if path_type == "input_product_path":
            rules[path_type] = Path(root, rules["directory_name"], "iof")
        else:
            rules[path_type] = Path(root, rules["directory_name"])
