"""
simple script to regenerate test cases and write checksum files for them.
notify users about changes from the current reference file,
if it exists. the new outputs can then be manually expected and
used to update the tests if they pass muster.

TODO: add CLI hook with options.
"""
import rich

from asdf.tests.data.test_cases import TEST_CASES
from asdf.tests.utilz.test_utilz import regen_asdf_e2e_case


e2e_cases = {
    case_name: case
    for case_name, case in TEST_CASES.items()
    # if case["type"] == "asdf e2e"
    if "zcam03110" in case_name
}

for case_name, case in e2e_cases.items():
    rich.print(f"[bold hot_pink blink]{case_name}")
    regen_asdf_e2e_case(case)
