from asdf.tests.utilz.settings import REF_INPUT_DIR

PROD_PATH = REF_INPUT_DIR / "products"
ROI_PATH = REF_INPUT_DIR / "rois"

# tests for a bunch of different user responses on the same inputs
USER_INPUT_PRODUCT_PATH = PROD_PATH / "1180/iof"
USER_INPUT_ROI_FILE = ROI_PATH / "zcam03921.sel"
USER_INPUT_TEST_RESPONSES = {
    # answer 1 to everything
    0: ('1',) * 14,
    # hit enter to skip for everything
    1: ("\n",) * 38,
    # no metadata field is the same for all ROIs, arbitrary selections after
    2: (
        '2', '2', '2', '4', '\n', '\n', '1', '8', '1', '5',
        '\n', '\n', '2', '1', '2', '2', 'TEST', '2', '3', '1', '1', '\n', '2',
        '7', '\n', '\n', 'test', '3', '1', 'asdfgh', '1', '2', '1', '2', '3',
        '3', 'test', '\n'
    ),
    # like an sPDL
    3: (
        '2', '1', '1', '2', '1', '1', '2', '5',
        'possible clast', '1', '6', '2', '5', '\n', '1', '6', '2', '5', '\n',
        '1', '1', '2', '5', '\n', '3', '\n', '3', '\n', '2', '2', '3', '\n',
        '\n'
    ),
    # everything is (individually) a rock
    4: (
        '\n', '1', '3', '1', 'test description', '1', '6',
        '2', '\n', '1', '4', '1', '3', '1', '\n', '1', '5', '1', '10', '3',
        '3', '1', '5', '\n', '1', '\n', '1', '1', '2', '4', '1', '2', '1',
        '1', '4', '\n'
    ),
    # everything is (collectively) soil
    5: (
        '1', '2', '\n', '2', '2', '\n', '7', '\n', '1', '\n', '6', '3', '2',
        '\n', '4', '\n', '\n', 'TEST', '3', '3', '3', 'test', '5', '1', '2',
        '\n', '2', '2', '2', '2', '1', '1', '1', '\n', '\n'
    ),
    # pebbles, hardware, or nothing
    6: ('2', '1', '\n', '1', 'asdfgh', '3', '4', '\n', '3', '\n', '\n', '4')
}

NO_ROI_CASES = {
    0: {'path': PROD_PATH / "0036/iof", 'noninteractive': True},
    1: {'path': PROD_PATH / "0557/iof"}
}
FULL_CASES = {
    0: {
        'path': PROD_PATH / "0782/iof",
        'roi_path': (
            ROI_PATH / "roi_SOL0782_zcam03635_RSM1114-regolith.fits.gz"
        ),
        'obs_ix': 1,
        'responses': (2, 1, 1, 1, "\n", 1, 4, 2, 2, 1, 1, 1, 1, 2, 2, 2, 1)
    },
    1: {
        'path': PROD_PATH / "0383/iof",
        'roi_path': ROI_PATH / 'roi_SOL0383_zcam03336_RSM98.fits.gz',
        'obs_ix': 2,
        'responses': (
            1, 2, 1, 1, 1, 3, 1, 2, 2, "good regolith", "bad regolith",
            "excellent regolith", "not sure", "mixed feelings again",
            "i forget about this one"
        )
    }
}
SPATIAL_CASES = {
    0: {
        'path': PROD_PATH / "0106/iof",
        'roi_path': ROI_PATH / "roi_SOL0106_zcam03153_RSM286.fits.gz",
        'noninteractive': True,
    }
}

# concatenate all cases including general per-category settings
TEST_CASES = [
    {
        'name': f"user_input_{k}",
        'responses': v,
        'path': USER_INPUT_PRODUCT_PATH,
        'roi_path': USER_INPUT_ROI_FILE,
        'seriously_no_images': True
    }
    for k, v in USER_INPUT_TEST_RESPONSES.items()
]
TEST_CASES += [
    {'name': f'no_roi_{k}', 'roi_path': None} | v
    for k, v in NO_ROI_CASES.items()
]
TEST_CASES += [{'name': f'full_{k}'} | v for k, v in FULL_CASES.items()]
TEST_CASES += [
    {
        'name': f'spatial_{k}',
        'reuse_spatial': False,
        'spatial': True,
    } | v for k, v in SPATIAL_CASES.items()
]
