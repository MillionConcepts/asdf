# regex patterns for marslab fields we intend to be different on different
# executions
from pathlib import Path

VARCOLS = ("CREATOR", "FILE_TIMESTAMP", ".*_PATH$")

E2E_INPUT_TEST_PATHS = {
    "path": "/datascratch/zcam_data/products/1180/iof",
    "roi_path": "/home/michael/Desktop/asdf/asdf/tests/data/e2e_input_tests/test_0/data/zcam03921.sel"
}

ERRDUMP_LOG_PATH = Path(__file__).parent.parent / "logs" / "test_errors.log"
