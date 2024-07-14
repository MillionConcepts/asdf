import datetime as dt
import json
from pathlib import Path
import shutil
from unittest.mock import patch

import pytest

import asdf.asdf_utils
import asdf.chatter
import asdf.cli_endpoint
import asdf.flow
import asdf.pretty
import asdf_settings.process
from asdf.console import ASDFLOG
from asdf.tests.e2e_cases import USER_INPUT_TEST_RESPONSES
from asdf.tests.utilz.settings import U, VARCOLS, \
    ERRDUMP_LOG_PATH
from asdf.tests.utilz.test_utilz import callgen, compare_asdf_outputs

# pytest isn't good at attaching to child processes
asdf_settings.process.THREADS = {
    k: None for k in asdf_settings.process.THREADS
}

ASDFLOG.setLevel("ERROR")
TEST_OUTPUT_DIR = Path("temp_test_output")
REF_INPUT_DIR = Path(__file__).parent / "data" / "reference_inputs"

# TODO: add a suppress output option to asdf; the way I am using logging to
#  control console output in asdf messes with pytest's log capturing pretty
#  badly and makes it a hassle to diagnose errors, and it will be useful for
#  some other applications as well


def stamp():
    return dt.datetime.now().astimezone(dt.UTC).isoformat()[:-9]


def _start_input_patch(responses, name, obs_ix="y"):
    responses = [obs_ix, name, *responses]
    input_patch = patch("rich.console.input", callgen(responses))
    input_patch.start()
    return input_patch


def generate_e2e_outputs(
    path, roi_path, name, responses=(), **kwargs
):
    input_patch = _start_input_patch(responses, name)
    try:
        asdf.cli_endpoint.asdf_initiate(
            path,
            roi_path,
            output=TEST_OUTPUT_DIR / name,
            **kwargs
        )
    finally:
        input_patch.stop()


def e2e_test_target(case):
    issues = ()
    try:
        generate_e2e_outputs(**case)
        issues = compare_asdf_outputs(
            TEST_OUTPUT_DIR / case['name'], REF_INPUT_DIR / case['name']
        )
        if len(issues) > 0:
            raise ValueError("outputs do not match, see test log")
    finally:
        if (TEST_OUTPUT_DIR / case['name']).exists():
            shutil.rmtree(TEST_OUTPUT_DIR / case['name'])
        if len(issues) > 0:
            ERRDUMP_LOG_PATH.parent.mkdir(exist_ok=True)
            with (ERRDUMP_LOG_PATH / case['name']).open("w") as stream:
                stream.write(
                    json.dumps(issues | {'timestamp': stamp()}), indent=4
                )

# # @pytest.mark.parametrize("case_name,case", e2e_cases.items())
# def test_asdf_e2e(case_name, case):
#     if case["test_output_path"].exists():
#         shutil.rmtree(case["test_output_path"])
#     patches = create_asdf_e2e_mocks(case)
#     for e2e_patch in patches:
#         e2e_patch.start()
#     asdf.cli_endpoint.asdf_initiate(
#         case["input_product_path"],
#         case["roi_path"],
#         output=case["test_output_path"],
#         **case["endpoint_kwargs"],
#     )
#     for e2e_patch in patches:
#         e2e_patch.stop()
#     if case["reference_output_path"].exists():
#         problems = compare_asdf_outputs(
#             case["test_output_path"], case["reference_output_path"]
#         )
#         if len(problems):
#             raise ValueError(problems)
#     else:
#         raise FileNotFoundError(
#             "No reference outputs found for this case, cannot perform "
#             "end-to-end regression test."
#         )
