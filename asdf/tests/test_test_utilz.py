from string import printable

import pandas as pd
import random

from pathlib import Path

import numpy as np
from PIL import Image

from asdf.tests.utilz.test_utilz import compare_browse_images, \
    make_awful_random_dataframe, RNG, compare_csv_files

COMP_EXPECTATIONS = {
    'alpha': ['images have different modes or color spaces'],
    'blue': [
        'images differ on average',  # floating point omitted
        'images have > 500 pixels that differ by > 50'
    ],
    'lil': ['images are different sizes'],
    'ok': []
}


def test_compare_browse_images():
    ref_path = Path(__file__).parent / "data/misc/squirrel.png"
    test_cases = ('ok', 'blue', 'lil', 'alpha')
    testpaths = {
        case: Path(__file__).parent / f'data/misc/squirrel_{case}.png'
        for case in test_cases
    }
    try:
        base_squirrel = np.asarray(Image.open(ref_path))
        Image.fromarray(base_squirrel.copy()).save(testpaths['ok'])
        blue_squirrel = np.dstack([
            base_squirrel[:, :, 0],
            base_squirrel[:, :, 1],
            np.full(base_squirrel.shape[:2], 255),
        ])
        Image.fromarray(blue_squirrel.astype('u1')).save(testpaths['blue'])
        lil_squirrel = Image.fromarray(base_squirrel.copy())
        lil_squirrel.thumbnail((255, 255))
        lil_squirrel.save(testpaths['lil'])
        alpha_squirrel = Image.fromarray(base_squirrel.copy())
        alpha_squirrel.convert('RGBA').save(testpaths['alpha'])
        del alpha_squirrel, lil_squirrel, blue_squirrel, base_squirrel
        comps = {
            case: compare_browse_images(ref_path, testpaths[case])
            for case in test_cases
        }
        for case, comp in comps.items():
            assert len(COMP_EXPECTATIONS[case]) == len(comp)
            for v_ref, v_test in zip(COMP_EXPECTATIONS[case], comp):
                # TODO: there are stringified floating point values that should
                #  just be formatted more nicely, hence this weird check to
                #  avoid false positives from floating point error
                assert v_test.startswith(v_ref)
    finally:
        for path in testpaths.values():
            path.unlink(missing_ok=True)


def test_compare_csv_files():
    ref_path = Path(__file__).parent / "ref.csv"
    cases = ("ok", "colcount", "rowcount", "colnames", "elements")
    test_paths = {c: Path(__file__).parent / f"test_{c}.csv" for c in cases}
    for _ in range(20):
        ref_df = make_awful_random_dataframe()
        ref_df.to_csv(ref_path, index=None)
        for case in cases:
            test_df = ref_df.copy()
            if case == "colcount":
                test_df = test_df.iloc[:, 0:RNG.integers(1, len(ref_df) - 1)]
            elif case == "rowcount":
                test_df = test_df.iloc[0:RNG.integers(1, len(ref_df) - 1)]
            elif case == "colnames":
                bad_colix = RNG.integers(len(test_df.columns))
                test_df.columns = [
                    c if i != bad_colix else f"{test_df.columns[bad_colix]}_haha!"
                    for i, c in enumerate(test_df.columns)
                ]
            elif case == "elements":
                tcol = test_df.columns[RNG.integers(len(test_df.columns))]
                trows = RNG.choice(test_df.index, RNG.integers(1, len(ref_df) - 1))
                if pd.api.types.is_float_dtype(test_df[tcol]):
                    test_df.loc[trows, tcol] = RNG.random(len(trows))
                elif pd.api.types.is_integer_dtype(test_df[tcol]):
                    test_df.loc[trows, tcol] = RNG.integers(-100, 100, len(trows))
                else:
                    test_df.loc[
                        trows, tcol
                    ] = RNG.choice([*printable, None], len(trows))
            elif case != "ok":
                raise ValueError(f"unknown CSV test case {case}")
            test_df.to_csv(test_paths[case], index=None)
            comparison = compare_csv_files(ref_path, test_paths[case])







