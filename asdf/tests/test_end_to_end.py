import pytest

import asdf.cli_endpoint
from asdf.tests.data.test_cases import TEST_CASES, TEST_CASE_WORKING_DIRECTORY
from asdf.tests.utilz.test_utilz import (
    compare_asdf_outputs,
)
from asdf.console import ASDFLOG
ASDFLOG.setLevel("WARNING")

e2e_cases = {
    case_name: case
    for case_name, case in TEST_CASES.items()
    if (
        (case["type"] == "asdf e2e")
        and ("noninteractive" in case["endpoint_kwargs"].keys())
    )
}

# TODO: add a suppress output option to asdf; the way I am using logging to
#  control console output in asdf messes with pytest's log capturing pretty
#  badly and makes it a hassle to diagnose errors

@pytest.mark.parametrize("case_name,case", e2e_cases.items())
def test_end_to_end_noninteractive(case_name, case):
    asdf.cli_endpoint.asdf_initiate(
        case["input_product_path"],
        case["roi_path"],
        output=case["test_output_path"],
        config=TEST_CASE_WORKING_DIRECTORY,
        **case["endpoint_kwargs"],
    )
    if case["reference_output_path"].exists():
        problems = compare_asdf_outputs(
            case["test_output_path"], case["reference_output_path"]
        )
        if len(problems):
            raise ValueError(problems)
    else:
        raise FileNotFoundError(
            "No reference outputs found for this case, cannot perform "
            "end-to-end regression test."
        )

    # TODO: old checksum version, kept for reference -- remove when unneeded
