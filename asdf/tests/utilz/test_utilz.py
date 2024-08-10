from functools import partial

from more_itertools import all_equal
from operator import eq
from pathlib import Path
from random import randint
from string import ascii_letters, digits, printable
import re
from types import NoneType
from typing import (
    Collection, Hashable, Literal, NotRequired, Optional, TypedDict, Union, Sequence
)
from unittest.mock import patch

from astropy.io import fits
from cytoolz import valfilter
from dustgoggles.func import constant, disjoint, intersection, gmap
from fs.osfs import OSFS
import numpy as np
import pandas as pd
import pdr
from PIL import Image
import rich
import shutil

import asdf.chatter
import asdf.cli_endpoint
import asdf.flow
import asdf.pretty
from asdf.tests.utilz.settings import MARSLAB_VARCOLS, SPACE_VARKEYS

from marslab.imgops.imgutils import ravel_valid

# noinspection PyTypedDict
RELEVANT_TYPECODES = ''.join(
    {*[np.typecodes[t] for t in ['AllInteger', 'AllFloat']], 'O'}
)
RNG = np.random.default_rng()
RUNTIME_VARIABLE_COLUMNS = re.compile(
    r"(ASDF_VERSION|FILE_TIMESTAMP|CREATOR|.*_PATH)"
)


def _insert_nulls_inplace(
    series: pd.Series, length: int, null: Union[NoneType, np.nan, Literal['-']]
) -> None:
    series.loc[
        RNG.choice(series.index, RNG.integers(1, min(length - 1, 20)))
    ] = null


def tree(root_path):
    tree_fs = OSFS(str(root_path))
    return list(map(lambda f: f.strip('/'), tree_fs.walk.files()))


def record_mismatches(results, absent, novel):
    for file in absent:
        results[str(file)] = ["missing from output"]
    for file in novel:
        results[str(file)] = ["not found in reference"]
    return results


def _undash(series):
    if series.dtype.char != 'O':
        return series
    series = series.replace('-', None)
    try:
        return series.astype(float)
    except ValueError:
        return series


class SeriesComparison(TypedDict):
    ref: pd.Series
    test: pd.Series
    ix: pd.Index


class CSVComparison(TypedDict):
    row_count: NotRequired[dict[Literal["ref", "test"], int]]
    column_count: NotRequired[dict[Literal["ref", "test"], int]]
    column_names: NotRequired[dict[Literal["new", "missing"], list[Hashable]]]
    elements: NotRequired[SeriesComparison]
    issues: NotRequired[
        list[Literal["row_count", "column_count", "column_names", "elements"]]
    ]


def compare_nested_float_series(rv, tv):
    rv, tv = np.vstack(rv.values), np.vstack(tv.values)
    close = np.isclose(rv, tv, equal_nan=True)
    return np.nonzero(close.all(axis=1))[0]


def compare_series(
    ref: pd.Series, test: pd.Series, rtol: float = 1e-5, atol: float = 1e-5
) -> Optional[SeriesComparison]:
    # TODO, maybe: doesn't handle nested float sequences of variable length
    #  (currently we shouldn't have any, though)
    maxlen = min(len(ref), len(test))
    rv, tv = map(lambda s: _undash(s.iloc[:maxlen].copy()), (ref, test))
    if (
        isinstance(rv.iloc[0], Sequence)
        and isinstance(rv.iloc[0], float)
        and all_equal(rv.map(len))
    ):
        val_mismatch = compare_nested_float_series(rv, tv)
    else:
        if all(map(pd.api.types.is_float_dtype, (rv, tv))):
            # note that equal_nan kwarg to isclose() does not work reliably
            # with all forms of pandas null
            equal = partial(np.isclose, rtol=rtol, atol=atol)
        else:
            equal = eq
        val_mismatch = ~(equal(rv, tv)) & ~(pd.isnull(rv) & pd.isnull(tv))
    if not val_mismatch.any():
        return None
    return {
        k: s[val_mismatch].values
        for k, s in zip(('ref', 'test', 'ix'), (rv, tv, val_mismatch.index))
    }


def compare_dfs(
    ref: pd.DataFrame,
    test: pd.DataFrame,
    varcols: Collection[str] = (),
    key_column: Optional[Hashable] = None,
    rtol: float = 1e-5,
    atol: float = 1e-5
) -> CSVComparison:
    if key_column is not None:
        ref = ref.sort_values(by=key_column).reset_index(drop=True)
        test = test.sort_values(by=key_column).reset_index(drop=True)
    comparison = {}
    if len(ref) != len(test):
        comparison["row_count"] = {"ref": len(ref), "test": len(test)}
    if len(ref.columns) != len(test.columns):
        comparison["column_count"] = {
            "ref": len(ref.columns), "test": len(test.columns)
        }
    missing_cols = list(set(ref.columns).difference(test.columns))
    new_cols = list(set(test.columns.difference(ref.columns)))
    if len(missing_cols) + len(new_cols) > 0:
        comparison["column_names"] = {"new": new_cols, "missing": missing_cols}
    shared = list(set(ref.columns).intersection(test.columns))
    if len(varcols) > 0:
        varpat = re.compile('|'.join(varcols))
        shared = {s for s in shared if not re.match(varpat, s)}
    element_mismatches = valfilter(
        lambda d: d is not None,
        {c: compare_series(ref[c], test[c], rtol, atol) for c in shared}
    )
    if len(element_mismatches) > 0:
        comparison["elements"] = element_mismatches
    if len(comparison.keys()) > 0:
        comparison["issues"] = list(comparison.keys())
    return comparison


def compare_csv_files(
    ref_path: Union[str, Path],
    test_path: Union[str, Path],
    varcols: Collection[Hashable] = (),
    key_column: Optional[Hashable] = None,
    rtol: float = 1e-5,
    atol: float = 1e-5
) -> CSVComparison:
    # noinspection PyTypeChecker
    return compare_dfs(
        *map(pd.read_csv, (ref_path, test_path)),
        varcols,
        key_column,
        rtol,
        atol
    )


def compare_browse_images(ref_path, test_path):
    problems = []
    test_image, ref_image = (Image.open(test_path), Image.open(ref_path))
    if not (test_image.getbands() == ref_image.getbands()):
        problems.append("images have different modes or color spaces")
        return problems
    test_array, ref_array = np.array(test_image), np.array(ref_image)
    if not (test_array.shape == ref_array.shape):
        problems.append("images are different sizes")
        return problems
    diff = abs(test_array.astype(np.float32) - ref_array.astype(np.float32))
    # TODO, maybe: make these thresholds configurable
    if np.mean(diff) > 1.5e-2:
        problems.append(
            f"images differ on average by {np.mean(diff)}, > 1.5e-2"
        )
    if diff[diff > 50].size > 500:
        problems.append(f"images have > 500 pixels that differ by > 50")
    return problems


def compare_roi_fits(ref_path, test_path):
    # TODO, maybe: make all of this a little more verbose
    problems = []
    test_fits, ref_fits = fits.open(test_path), fits.open(ref_path)
    if test_fits.info(False) != ref_fits.info(False):
        problems.append("files have mismatched hdulists")
        return problems
    for test_hdu, ref_hdu in zip(test_fits, ref_fits):
        if test_hdu.header != ref_hdu.header:
            problems.append(f"{test_hdu.name} headers mismatched")
        # these are 0/1-valued uint8 arrays, so should be identical
        # noinspection PyUnresolvedReferences
        if not (test_hdu.data == ref_hdu.data).all():
            problems.append(f"{test_hdu.name} data mismatched")
    return problems


def compare_space_fits(ref_path, test_path, varkeys=SPACE_VARKEYS):
    problems = []
    ref, test = pdr.read(ref_path), pdr.read(test_path)
    if ref.keys() != test.keys():
        problems.append("files have mismatched hdulists")
        return problems
    for k in ref.keys():
        if 'HEADER' in k:
            continue
        hproblems = {}
        tblock, rblock = ref.metablock_(k), test.metablock_(k)
        shared = set(tblock.keys()).intersection(rblock.keys())
        if varkeys is not None:
            varpat = re.compile('|'.join(varkeys))
            shared = {s for s in shared if not re.match(varpat, s)}
        distinct = set(tblock.keys()).symmetric_difference(rblock.keys())
        if len(distinct) > 0:
            hproblems['header_keys'] = list(distinct)
        badvals = {}
        for key in sorted(shared):
            if (tv := tblock.get(key)) != (rv := rblock.get(key)):
                badvals[key] = {"ref": rv, "test": tv}
        if len(badvals) > 0:
            hproblems['header_values'] = badvals
        if len(hproblems) > 0:
            problems.append(hproblems)
        if (k == "PRIMARY") or ("HEADER" in k):
            continue
        # TODO, maybe: configurable tolerances
        # NOTE: these are RICE-compressed files, so we expect the offsets to be
        #  above floating-point error here, but still far under the resolution
        #  of the data -- 1 mm absolute tolerance, a hundredth of a percent
        #  relative tolerance.
        mismask = ~np.isclose(
            ref[k], test[k], equal_nan=True, atol=1e-4, rtol=1e-4
        )
        if not mismask.any():
            continue
        # convert to Python floats because json.dumps() fails on numpy scalars
        hproblems["data"] = {
            "max_offset": float(abs(ref[k][mismask] - test[k][mismask]).max()),
            "ref_ptp": float(np.ptp(ravel_valid(test[k]))),
            "test_ptp": float(np.ptp(ravel_valid(ref[k])))
        }
    return problems


def dispatched_asdf_comparison(
    file,
    ref_root: Path,
    test_root: Path,
    use_color_as_key_column: bool = True,
    marslab_rtol: float = 1e-5,
    marslab_atol: float = 1e-5,
    varcols: Collection[str] = MARSLAB_VARCOLS,
):
    ref_path, test_path = ref_root / file, test_root / file
    if file.suffix == '.csv' and file.name.startswith('marslab'):
        return compare_csv_files(
            ref_path,
            test_path,
            varcols,
            "COLOR" if use_color_as_key_column is True else None,
            marslab_rtol,
            marslab_atol
        )
    if file.suffix == ".png":
        return compare_browse_images(ref_path, test_path)
    if ".fits" in file.suffixes:
        if file.name.startswith("roi"):
            return compare_roi_fits(ref_path, test_path)
        if file.name.startswith("space"):
            return compare_space_fits(ref_path, test_path)
        return [f"unknown file type ({ref_path.name}"]
    if file.stem.endswith("naveval"):
        return compare_csv_files(ref_path, test_path)
    # TODO, maybe: write a comparison for these?
    if file.suffix == '.sel':
        return []
    return [f"unknown file type ({ref_path.name})"]


def compare_asdf_outputs(
    ref_root: Path,
    test_root: Path,
    use_color_as_key_column: bool = True,
    marslab_rtol: float = 1e-5,
    marslab_atol: float = 1e-5,
    varcols: Collection[str] = MARSLAB_VARCOLS,
    skiptypes: Collection[str] = ()
):
    test, reference = gmap(Path, tree(test_root)), gmap(Path, tree(ref_root))
    if len(skiptypes) > 0:
        skippy = re.compile('|'.join(skiptypes))
        test = [t for t in test if not re.match(skippy, t.name)]
        reference = [r for r in reference if not re.match(skippy, r.name)]
    problems = {}
    novel_files, absent_files = disjoint(test, reference)
    # note files that are completely new or missing
    if len(novel_files + absent_files) > 0:
        problems |= record_mismatches(problems, absent_files, novel_files)
    # do comparisons between others
    for file in intersection(test, reference):
        problems[str(file)] = dispatched_asdf_comparison(
            file,
            ref_root,
            test_root,
            use_color_as_key_column,
            marslab_rtol,
            marslab_atol,
            varcols
        )
    return valfilter(lambda x: x is not None and len(x) > 0, problems)


def print_mismatches(absent_files, novel_files):
    rich.print("[bold red]missing or changed filenames[/]")
    rich.print("unique to new: ")
    for file in novel_files:
        rich.print(f"[italic]{file}")
    rich.print("unique to old: ")
    for file in absent_files:
        rich.print(f"[italic]{file}")


def return_first_choice(_, choices):
    return choices[0]


# TODO: why is this nonsense necessary sometimes? track this down.
def pretty_chatter_patch(obj, new):
    return (asdf.pretty, obj, new), (asdf.chatter, obj, new)


def create_fdsa_e2e_mocks():
    patch_specs = []
    patch_specs += pretty_chatter_patch("confirm_fdsa_metadata", constant("Y"))
    patch_specs += pretty_chatter_patch("confirm_fdsa_data", constant("Y"))
    return [patch.object(*spec) for spec in patch_specs]


def create_asdf_e2e_mocks(case):
    patch_specs = []
    patch_specs += pretty_chatter_patch("confirm_observation", constant("Y"))
    if "observation_choice" in case.keys():
        patch_specs += pretty_chatter_patch(
            "offer_observation_choice", constant(case["observation_choice"])
        )
    noninteractive = "noninteractive" not in case["endpoint_kwargs"].keys()
    if not noninteractive:
        oc = (
            case["observation_choice"]
            if case.get("observation_choice") is not None
            else 1
        )
        patch_specs.append(
            (asdf.chatter, "offer_observation_choice", constant(oc))
        )
    if ("ignore_unspecified_inputs" in case.keys()) and (
        "noninteractive" not in case["endpoint_kwargs"].keys()
    ):
        patch_specs.append((asdf.flow, "name_prompt", constant("TEST")))
        patch_specs.append(
            (asdf.pretty, "metadata_open_prompt", constant("TEST"))
        )
        patch_specs += pretty_chatter_patch(
            "metadata_choice_prompt", return_first_choice
        )
    return [patch.object(*spec) for spec in patch_specs]


def regen_asdf_e2e_case(case):
    if case["temp_output_path"].exists():
        shutil.rmtree(case["temp_output_path"])
    patches = create_asdf_e2e_mocks(case)
    for e2e_patch in patches:
        e2e_patch.start()
    # note: don't necessarily need to use the test version of asdf_settings
    # b/c threading is not an issue?
    asdf.cli_endpoint.asdf_initiate(
        case["input_product_path"],
        case["roi_path"],
        output=case["temp_output_path"],
        **case["endpoint_kwargs"],
    )
    for e2e_patch in patches:
        e2e_patch.stop()
    if not case["reference_output_path"].exists():
        return
    problems = compare_asdf_outputs(
        case["reference_output_path"], case["temp_output_path"]
    )
    if len(problems) == 0:
        return
    for file, file_problems in problems.items():
        rich.print(f"[bold red] {file}:\n")
        for file_problem in file_problems:
            rich.print(f"[italic] {file_problem}")


def _random_string_series(length: int) -> pd.Series:
    strings = [
        ''.join(RNG.choice(tuple(printable), RNG.integers(0, 50)))
        for _ in range(length)
    ]
    return pd.Series(strings)


def make_awful_random_dataframe():
    colnames = [
        ''.join(RNG.choice(tuple(ascii_letters + digits), 12))
        for _ in range(randint(3, 50))
    ]
    dtype_codes = RNG.choice(tuple(RELEVANT_TYPECODES), len(colnames))
    length, columns = RNG.integers(1, 3000), {}
    for colname, code in zip(colnames, dtype_codes):
        null = np.nan
        if code in np.typecodes['AllFloat']:
            columns[colname] = pd.Series(
                RNG.random(length) * 10.0 ** RNG.integers(-10, 10, length)
            )
        elif code in np.typecodes['AllInteger']:
            columns[colname] = pd.Series(RNG.integers(-10000, 10000, length))
        elif code == 'O':
            columns[colname] = _random_string_series(length)
            # noinspection PyTypeChecker
            null = RNG.choice([None, '-', np.nan])
        if code in np.typecodes['AllFloat'] + 'O' and RNG.random() > 0.5:
            _insert_nulls_inplace(columns[colname], length, null)
    return pd.DataFrame(columns)


def callgen(responses):
    """creates a generator-like callable"""
    response_iter = iter(responses)

    def get_next_response(*_, **__):
        resp = next(response_iter)
        print(f" ****{resp}**** ")
        return resp

    return get_next_response


# lazy convenience functions for recording console input when
# generating test cases

def make_input_tee(fn):
    def tee_input():
        result = input()
        with open(fn, "a") as stream:
            stream.write(f"{result}\n")
        return result

    return tee_input


def record_console_input(fn='recording.log'):
    input_patch = patch("rich.console.input", make_input_tee(fn))
    input_patch.start()
    return input_patch
