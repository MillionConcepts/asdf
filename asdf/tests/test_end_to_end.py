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
from asdf.tests.e2e_cases import E2E_INPUT_TEST_RESPONSES
from asdf.tests.utilz.settings import E2E_INPUT_TEST_PATHS, VARCOLS, \
    ERRDUMP_LOG_PATH
from asdf.tests.utilz.test_utilz import callgen, compare_asdf_outputs

# pytest isn't good at attaching to child processes
asdf_settings.process.THREADS = {
    k: None for k in asdf_settings.process.THREADS
}

ASDFLOG.setLevel("ERROR")
TEST_OUTPUT_DIR = Path("temp_test_output")
E2E_INPUT_CASE_DIR = Path(__file__).parent / "data" / "e2e_input_tests"

# TODO: add a suppress output option to asdf; the way I am using logging to
#  control console output in asdf messes with pytest's log capturing pretty
#  badly and makes it a hassle to diagnose errors, and it will be useful for
#  some other applications as well


def testheader(test_id):
    return (
        f"\n****{test_id}****"
        f"\n{dt.datetime.now().astimezone(dt.UTC).isoformat()[:-9]}\n\n"
    )


def test_e2e_user_inputs(test_number, responses):
    responses = ["y", f"TEST_{test_number}", *responses]
    issues = ()
    input_patch = patch("rich.console.input", callgen(responses))
    input_patch.start()
    try:
        asdf.cli_endpoint.asdf_initiate(
            **E2E_INPUT_TEST_PATHS,
            output=TEST_OUTPUT_DIR,
            seriously_no_images=True
        )
        issues = compare_asdf_outputs(
            TEST_OUTPUT_DIR, E2E_INPUT_CASE_DIR / f"test_{test_number}"
        )
        if len(issues) > 0:
            raise ValueError("outputs do not match, see test log")
    finally:
        if TEST_OUTPUT_DIR.exists():
            shutil.rmtree(TEST_OUTPUT_DIR)
        input_patch.stop()
        if len(issues) > 0:
            ERRDUMP_LOG_PATH.parent.mkdir(exist_ok=True)
            with ERRDUMP_LOG_PATH.open("a") as stream:
                stream.write(testheader(f"e2e_user_input_{test_number}"))
                stream.write(json.dumps(issues))
                stream.write("\n")


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
