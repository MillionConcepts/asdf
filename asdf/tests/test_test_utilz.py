from pathlib import Path

import numpy as np
from PIL import Image

from asdf.tests.utilz.test_utilz import compare_browse_images

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
