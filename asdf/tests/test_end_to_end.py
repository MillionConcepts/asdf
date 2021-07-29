import pandas as pd
import pytest

import asdf.cli_endpoint

from pathlib import Path
from fs.osfs import OSFS

from asdf.tests.data.test_cases import TEST_CASES, TEST_CASE_WORKING_DIRECTORY
from asdf.tests.utilz.test_utilz import (
    md5sum,
    make_test_checksums,
    compare_to_reference_checksums,
)

e2e_cases = {
    case_name: case
    for case_name, case in TEST_CASES.items()
    if (
        (case["type"] == "asdf e2e")
        and ("noninteractive" in case["endpoint_kwargs"].keys())
    )
}


@pytest.mark.parametrize("case_name,case", e2e_cases.items())
def test_end_to_end_noninteractive(case_name, case):
    asdf.cli_endpoint.asdf_initiate(
        case["data_path"],
        case["roi_path"],
        output=case["output_path"],
        config=TEST_CASE_WORKING_DIRECTORY,
        **case["endpoint_kwargs"],
    )
    checksums = make_test_checksums(case)
    checksum_df = pd.DataFrame(checksums, columns=["file", "md5"])
    if case["checksum_path"].exists():
        compare_to_reference_checksums(
            checksum_df, case["checksum_path"], fail_on_mismatch=True
        )
    else:
        raise FileNotFoundError(
            "No reference checksum manifest found for this case, cannot perform test."
        )
