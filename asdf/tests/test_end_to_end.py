from io import StringIO

from contextlib import redirect_stdout

import datetime as dt
import json
import pytest
import shutil

import asdf_settings.process
from asdf.console import ASDFLOG
from asdf.tests.e2e_cases import TEST_CASES
from asdf.tests.utilz.e2e_utilz import generate_e2e_outputs
from asdf.tests.utilz.settings import (
    ERRDUMP_LOG_PATH, REF_OUTPUT_DIR, TEST_OUTPUT_DIR
)
from asdf.tests.utilz.test_utilz import compare_asdf_outputs

ASDFLOG.setLevel("ERROR")


def stamp():
    return dt.datetime.now().astimezone(dt.UTC).isoformat()[:-9]


@pytest.mark.parametrize(
    "case", TEST_CASES, ids=[c['name'] for c in TEST_CASES]
)
def test_e2e(case):
    issues, stdout_buffer = (), StringIO()
    err_json_file = ERRDUMP_LOG_PATH / f"{case['name']}.json"
    err_json_file.unlink(missing_ok=True)
    try:
        with redirect_stdout(stdout_buffer):
            generate_e2e_outputs(**case)
        issues = compare_asdf_outputs(
            TEST_OUTPUT_DIR / case['name'], REF_OUTPUT_DIR / case['name']
        )
        if len(issues) > 0:
            raise ValueError("outputs do not match, see test dumps")
    finally:
        if (TEST_OUTPUT_DIR / case['name']).exists():
            shutil.rmtree(TEST_OUTPUT_DIR / case['name'])
        if len(issues) > 0:
            ERRDUMP_LOG_PATH.parent.mkdir(exist_ok=True, parents=True)
            err_json_file = ERRDUMP_LOG_PATH / f"{case['name']}.json"
            with err_json_file.open("w") as stream:
                stream.write(
                    json.dumps(issues | {'timestamp': stamp()}), indent=4
                )
            if stdout_buffer.tell() > 0:
                console_dump_file = ERRDUMP_LOG_PATH / f"{case['name']}.dump"
                stdout_buffer.seek(0)
                with console_dump_file.open("w") as stream:
                    stream.write(stdout_buffer.read())
