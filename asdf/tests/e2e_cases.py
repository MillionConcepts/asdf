from pathlib import Path


E2E_INPUT_TEST_PATHS = {
    "iof_path": "/datascratch/zcam_data/products/1180/iof",
    "sel_path": "/home/michael/Desktop/asdf/asdf/tests/data/e2e_input_tests/test_0/data/zcam03921.sel"
}


E2E_INPUT_TEST_RESPONSES = {
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