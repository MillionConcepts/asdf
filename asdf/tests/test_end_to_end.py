import datetime as dt
import json
import pytest
import shutil
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from warnings import catch_warnings

from asdf.console import ASDFLOG
from asdf.tests.e2e_cases import TEST_CASES
from asdf.tests.utilz.e2e_utilz import (
    generate_e2e_outputs, _prep_public_e2e_test, _prep_private_e2e_test
)
from asdf.tests.utilz.settings import (
    E2E_FAILURE_DIR, REF_OUTPUT_DIR, TEST_OUTPUT_DIR
)
from asdf.tests.utilz.test_utilz import compare_asdf_outputs
from marslab.tests.utilz.div0 import divide_by_zero

ASDFLOG.setLevel("ERROR")


def stamp():
    return dt.datetime.now().astimezone(dt.UTC).isoformat()[:-9]


def _e2e_test_inner(case):
    issues, stdout_buffer = (), StringIO()
    err_json_file = E2E_FAILURE_DIR / f"{case['name']}.json"
    err_json_file.unlink(missing_ok=True)
    try:
        with (redirect_stdout(stdout_buffer), catch_warnings()):
            divide_by_zero()
            generate_e2e_outputs(**case)
        issues = compare_asdf_outputs(
            REF_OUTPUT_DIR / case['name'], TEST_OUTPUT_DIR / case['name']
        )
        if len(issues) > 0:
            raise ValueError("outputs do not match, see test dumps")
    finally:
        if (errdir := (E2E_FAILURE_DIR / case['name'])).exists():
            shutil.rmtree(errdir)
        if len(issues) > 0:
            errdir.mkdir(parents=True)
            err_json_file = errdir / f"{case['name']}.json"
            with err_json_file.open("w") as stream:
                stream.write(
                    json.dumps(issues | {'timestamp': stamp()}, indent=4)
                )
            if (TEST_OUTPUT_DIR / case['name']).exists():
                for fpath in map(Path, issues.keys()):
                    tpath = TEST_OUTPUT_DIR / case['name'] / fpath
                    rpath = REF_OUTPUT_DIR / case['name'] / fpath
                    if not (tpath.exists() and rpath.exists()):
                        continue
                    shutil.copy(
                        TEST_OUTPUT_DIR / case['name'] / fpath,
                        errdir / f"{fpath.stem}_test{fpath.suffix}"
                    )
                    shutil.copy(
                        REF_OUTPUT_DIR / case['name'] / fpath,
                        errdir / f"{fpath.stem}_ref{fpath.suffix}"
                    )
            if stdout_buffer.tell() > 0:
                console_dump_file = errdir / f"{case['name']}.dump"
                stdout_buffer.seek(0)
                with console_dump_file.open("w") as stream:
                    stream.write(stdout_buffer.read())
        if (TEST_OUTPUT_DIR / case['name']).exists():
            shutil.rmtree(TEST_OUTPUT_DIR / case['name'])


@pytest.mark.public
@pytest.mark.parametrize(
    "case", TEST_CASES, ids=[c['name'] for c in TEST_CASES]
)
def test_e2e_public(case):
    _e2e_test_inner(_prep_public_e2e_test(case))


@pytest.mark.private
@pytest.mark.parametrize(
    "case", TEST_CASES, ids=[c['name'] for c in TEST_CASES]
)
def test_e2e_private(case):
    _e2e_test_inner(_prep_private_e2e_test(case))
