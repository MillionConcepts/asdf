"""
simple script to regenerate test cases and write checksum files for them.
notify users about changes from the current reference file,
if it exists. the new outputs can then be manually expected and
used to update the tests if they pass muster.

TODO: add CLI hook with options.
"""

import rich

import asdf.cli_endpoint
from asdf.tests.data.test_cases import TEST_CASES, TEST_CASE_WORKING_DIRECTORY
from asdf.tests.utilz.test_utilz import compare_asdf_outputs

e2e_cases = {
    case_name: case
    for case_name, case in TEST_CASES.items()
    if case["type"] == "asdf e2e"
}


for case in e2e_cases.values():
    asdf.cli_endpoint.asdf_initiate(
        case["input_product_path"],
        case["roi_path"],
        output=case["temp_output_path"],
        config=TEST_CASE_WORKING_DIRECTORY,
        **case["endpoint_kwargs"],
    )
    # checksums = make_test_checksums(case, "temp_path")
    #
    # checksum_df = pd.DataFrame(checksums, columns=["file", "md5"])
    # checksum_df.to_csv(
    #     Path(case["temp_path"], case["checksum_path"].name), index=False
    # )
    if not case["reference_output_path"].exists():
        continue
    problems = compare_asdf_outputs(case["temp_output_path"], case["reference_output_path"])
    if len(problems):
        for file, file_problems in problems.items():
            rich.print(f"[bold red] {file}:\n")
            for file_problem in file_problems:
                rich.print([f"[italic] {file_problem}"])



