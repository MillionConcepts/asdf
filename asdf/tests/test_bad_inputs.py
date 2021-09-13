import sys

from dustgoggles.func import constant
import pytest

import asdf.asdf_utils
import asdf.chatter
import asdf.cli_endpoint
import asdf.flow
import asdf.pretty
from asdf.tests.data.test_cases import TEST_CASES, TEST_CASE_WORKING_DIRECTORY
from asdf.tests.utilz.test_utilz import (
    compare_asdf_outputs,
    return_first_choice,
)
from asdf.console import ASDFLOG

ASDFLOG.setLevel("WARNING")

e2e_cases = {
    case_name: case
    for case_name, case in TEST_CASES.items()
    if (
        (case["type"] == "asdf bad input")
    )
}


@pytest.mark.parametrize("case_name,case", e2e_cases.items())
def test_bad_inputs(case_name, case, capsys):
    asdf.cli_endpoint.asdf_initiate(
        case["input_product_path"],
        case["roi_path"],
        output=case["test_output_path"],
        config=TEST_CASE_WORKING_DIRECTORY,
        **case["endpoint_kwargs"]
    )
    capture = capsys.readouterr()
    if "we_should_mention" in case.keys():
        assert case["we_should_mention"] in capture.out
