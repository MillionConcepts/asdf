from importlib import import_module
from pathlib import Path

from itertools import product
import re
from typing import Literal, Sequence, Union
from unittest.mock import patch

import rich

from asdf._patcher import monkeypatch_literals
from asdf.tests.utilz.test_utilz import callgen
from asdf.tests.utilz.settings import (
    REF_OUTPUT_DIR, REGEN_OUTPUT_DIR, TEST_OUTPUT_DIR
)


def _start_input_patch(responses, name, obs_ix):
    responses = [str(obs_ix), name, *map(str, responses)]
    input_patch = patch("rich.console.input", callgen(responses))
    input_patch.start()
    return input_patch


def _prep_public_e2e_test(case):
    # noinspection PyUnresolvedReferences
    import asdf.cli_endpoint
    import asdf.tests.dummy_meta
    import asdf_settings.meta
    import asdf_settings.sources

    setattr(asdf_settings.sources, "META_ROOTS", [])
    setattr(asdf.cli_endpoint, "_PATCHBLOCK", True)
    monkeypatch_literals(asdf.tests.dummy_meta, asdf_settings.meta)
    case = case.copy()
    case['name'] = f"{case['name']}_public"
    case['skip_pixmaps'] = True
    return case


def _prep_private_e2e_test(case):
    # noinspection PyUnresolvedReferences
    import asdf.cli_endpoint
    import asdf.tests
    import asdf_settings.meta
    import asdf_settings.sources

    private = (
        Path(asdf.tests.__file__).parent
        / "data" / "reference_inputs" / "private"
    )
    setattr(asdf_settings.sources, "META_ROOTS", [private])

    setattr(asdf.cli_endpoint,"_PATCHBLOCK", True)
    monkeypatch_literals(
        import_module("asdf_settings.user_meta"), asdf_settings.meta
    )
    case = case.copy()
    case['name'] = f"{case['name']}_private"
    return case


def regenerate_test_outputs(
    which: Union[Literal["all", "missing"], Sequence[int], re.Pattern] = "all",
    side: Union[Literal["both", "public", "private"]] = "both"
):
    sides = ("public", "private") if side == "both" else (side,)
    from asdf.tests.e2e_cases import TEST_CASES

    cases = [(c, s) for c, s in product(TEST_CASES, sides)]
    if isinstance(which, re.Pattern):
        cases = [(c, s) for c, s in cases if which.match(c['name'])]
    elif isinstance(which, Sequence) and isinstance(which[0], int):
        cases = [c for i, (c, s) in enumerate(cases) if i in which]
    elif which == "all":
        pass
    elif which == "missing":
        # TODO: inefficient, obviously
        cases = [
            (c, s) for c, s in cases
            if not (REF_OUTPUT_DIR / f"{c['name']}_{s}").exists()
        ]
    else:
        raise TypeError("'which' argument not understood")
    for case, side in cases:
        rich.print(f"[bold hot_pink blink]{case['name']}")
        if side == 'public':
            case = _prep_public_e2e_test(case)
        else:
            case = _prep_private_e2e_test(case)
        generate_e2e_outputs(**case, output_root=REGEN_OUTPUT_DIR)


def generate_e2e_outputs(
    path,
    roi_path,
    name,
    responses=(),
    obs_ix='y',
    output_root=TEST_OUTPUT_DIR,
    **kwargs
):
    import asdf.cli_endpoint

    input_patch = _start_input_patch(responses, name, obs_ix)
    try:
        asdf.cli_endpoint.asdf_initiate(
            path, roi_path, output=output_root / name, **kwargs
        )
    finally:
        input_patch.stop()
