import shutil

import pytest

import asdf.asdf_utils
import asdf.chatter
import asdf.cli_endpoint
import asdf.flow
import asdf.pretty
from asdf.console import ASDFLOG
from asdf.tests.data.test_cases import TEST_CASES
from asdf.tests.utilz.test_utilz import (
    compare_asdf_outputs,
    create_fdsa_e2e_mocks,
)
import asdf_settings

ASDFLOG.setLevel("WARNING")

asdf_settings.process.THREADS = {"look": None, "save": None}

e2e_cases = {
    case_name: case
    for case_name, case in TEST_CASES.items()
    if (
            (case["type"] == "asdf e2e")
            # ignore cases irrelevant to or nonsensical for fdsa
            and ("thumbs" not in case_name)
            and ("clear_only" not in case_name)
            and (case["roi_path"] is not None)
    )
}


@pytest.mark.parametrize("case_name,case", e2e_cases.items())
def test_fdsa_e2e(case_name, case):
    if case["fdsa_test_output_path"].exists():
        shutil.rmtree(case["fdsa_test_output_path"])
    patches = create_fdsa_e2e_mocks()
    for e2e_patch in patches:
        e2e_patch.start()
    asdf.cli_endpoint.fdsa_initiate(
        marslab_path=case["reference_output_path"],
        image_path=case["input_product_path"],
        output=case["fdsa_test_output_path"],
    )
    for e2e_patch in patches:
        e2e_patch.stop()
    if case["reference_output_path"].exists():
        problems = compare_asdf_outputs(
            case["fdsa_test_output_path"], case["reference_output_path"],
            ignore_fields=["ROI_SOURCE", "ORIGINAL_ROI_SOURCE"]
        )
        if len(problems):
            raise ValueError(problems)
    else:
        raise FileNotFoundError(
            "No reference outputs found for this case, cannot perform "
            "end-to-end regression test."
        )
