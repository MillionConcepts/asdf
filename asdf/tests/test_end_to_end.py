import pytest

import asdf.asdf_utils
import asdf.chatter
import asdf.cli_endpoint
import asdf.flow
import asdf.pretty
from asdf.tests.data.test_cases import TEST_CASES, TEST_CASE_WORKING_DIRECTORY
from asdf.tests.utilz.test_utilz import (
    compare_asdf_outputs,
    constant,
    return_first_choice,
)
from asdf.console import ASDFLOG

ASDFLOG.setLevel("WARNING")

e2e_cases = {
    case_name: case
    for case_name, case in TEST_CASES.items()
    if (
        (case["type"] == "asdf e2e")
        and ("noninteractive" not in case["endpoint_kwargs"].keys())
    )
}

# TODO: add a suppress output option to asdf; the way I am using logging to
#  control console output in asdf messes with pytest's log capturing pretty
#  badly and makes it a hassle to diagnose errors, and it will be useful for
#  some other applications as well


@pytest.mark.parametrize("case_name,case", e2e_cases.items())
def test_end_to_end_noninteractive(case_name, case, mocker):
    if "observation_choice" in case.keys():
        mocker.patch.object(
            asdf.chatter,
            "offer_observation_choice",
            constant(case["observation_choice"]),
        )
    mocker.patch.object(asdf.chatter, "confirm_observation", constant("Y"))
    if ("ignore_unspecified_inputs" in case.keys()) and (
        "noninteractive" not in case["endpoint_kwargs"].keys()
    ):
        mocker.patch.object(asdf.flow, "name_prompt", constant("TEST"))
        mocker.patch.object(
            asdf.pretty, "metadata_open_prompt", constant("TEST")
        )
        # TODO: why does this only work when I patch it in both modules?
        #  track this down.
        mocker.patch.object(
            asdf.pretty, "metadata_choice_prompt", return_first_choice
        )
        mocker.patch.object(
            asdf.chatter, "metadata_choice_prompt", return_first_choice
        )
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
