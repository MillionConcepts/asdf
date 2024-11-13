from contextlib import redirect_stdout
import datetime as dt
from io import StringIO
from importlib import import_module, reload
import json
from pathlib import Path
import shutil
import sys
from warnings import catch_warnings

from asdf._patcher import monkeypatch_literals
from marslab.tests.utilz.div0 import divide_by_zero
import pytest

from asdf.console import ASDFLOG
from asdf.tests.e2e_cases import TEST_CASES
from asdf.tests.utilz.e2e_utilz import generate_e2e_outputs
from asdf.tests.utilz.settings import (
    E2E_FAILURE_DIR, REF_OUTPUT_DIR, TEST_OUTPUT_DIR
)
from asdf.tests.utilz.test_utilz import compare_asdf_outputs

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
        # if (TEST_OUTPUT_DIR / case['name']).exists():
        #     shutil.rmtree(TEST_OUTPUT_DIR / case['name'])


@pytest.mark.public
@pytest.mark.parametrize(
    "case", TEST_CASES, ids=[c['name'] for c in TEST_CASES]
)
def test_e2e_public(case):
    import asdf_settings.metadata
    # noinspection PyUnresolvedReferences
    import asdf

    case['name'] = f'{case["name"]}_public'
    monkeypatch_literals(
        asdf_settings.metadata,
        import_module(".dummy_metadata", package="asdf.tests")
    )

    _e2e_test_inner(case)


@pytest.mark.private
@pytest.mark.parametrize(
    "case", TEST_CASES, ids=[c['name'] for c in TEST_CASES]
)
def test_e2e_private(case):
    import asdf_settings.metadata
    reload(asdf_settings.metadata)
    try:
        import asdf_settings.user_metadata

        monkeypatch_literals(
            asdf_settings.user_metadata, asdf_settings.metadata
        )
    except ImportError:
        pass

    _e2e_test_inner(case)
