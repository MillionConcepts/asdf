"""
simple script to regenerate test cases and write checksum files for them.
notify users about changes from the current reference file,
if it exists. the new outputs can then be manually expected and
used to update the tests if they pass muster.

TODO: add CLI hook with options.
"""
from pathlib import Path

import pandas as pd

import asdf.cli_endpoint
from asdf.tests.data.test_cases import TEST_CASES, TEST_CASE_WORKING_DIRECTORY
from asdf.tests.utilz.test_utilz import make_test_checksums, \
    compare_to_reference_checksums

e2e_cases = {
    case_name: case
    for case_name, case in TEST_CASES.items()
    if case["type"] == "asdf e2e"
}


for case in e2e_cases.values():
    asdf.cli_endpoint.asdf_initiate(
        case["data_path"],
        case["roi_path"],
        output=case["temp_path"],
        config=TEST_CASE_WORKING_DIRECTORY,
        **case["endpoint_kwargs"],
    )
    checksums = make_test_checksums(case, "temp_path")

    checksum_df = pd.DataFrame(checksums, columns=["file", "md5"])
    checksum_df.to_csv(
        Path(case["temp_path"], case["checksum_path"].name), index=False
    )

    if case["checksum_path"].exists():
        compare_to_reference_checksums(
            checksum_df, case["checksum_path"], fail_on_mismatch=False
        )


