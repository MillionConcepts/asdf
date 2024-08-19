import re

from typing import Union, Literal, Collection, Sequence

from unittest.mock import patch

import rich

from asdf.tests.utilz.test_utilz import callgen
from asdf.tests.utilz.settings import (
    REF_OUTPUT_DIR, TEST_OUTPUT_DIR, REGEN_OUTPUT_DIR
)


def _start_input_patch(responses, name, obs_ix):
    responses = [str(obs_ix), name, *map(str, responses)]
    input_patch = patch("rich.console.input", callgen(responses))
    input_patch.start()
    return input_patch


def generate_e2e_outputs(
    path,
    roi_path,
    name,
    responses=(),
    obs_ix='y',
    output_root=TEST_OUTPUT_DIR,
    **kwargs
):
    from asdf_settings import sources
    
    # necessary for running tests in deployment environment --
    # intentionally-missing inputs will be findable, 
    # metamaps may have changed, etc.
    setattr(sources, "META_ROOTS", [])

    import asdf.cli_endpoint

    input_patch = _start_input_patch(responses, name, obs_ix)
    try:
        asdf.cli_endpoint.asdf_initiate(
            path, roi_path, output=output_root / name, **kwargs
        )
    finally:
        input_patch.stop()


def regenerate_test_outputs(
    which: Union[Literal["all", "missing"], Sequence[int], re.Pattern] = "all"
):
    from asdf.tests.e2e_cases import TEST_CASES

    if isinstance(which, re.Pattern):
        cases = [c for c in TEST_CASES if which.match(c['name'])]
    elif isinstance(which, Sequence) and isinstance(which[0], int):
        cases = [c for i, c in enumerate(TEST_CASES) if i in which]
    elif which == "all":
        cases = TEST_CASES
    elif which == "missing":
        cases = [
            c for c in TEST_CASES if not (REF_OUTPUT_DIR / c['name']).exists()
        ]
    else:
        raise TypeError("'which' argument not understood")
    for case in cases:
        rich.print(f"[bold hot_pink blink]{case['name']}")
        generate_e2e_outputs(**case, output_root=REGEN_OUTPUT_DIR)
