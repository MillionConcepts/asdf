# regex patterns for marslab fields we intend to be different on different
# executions
from pathlib import Path

VARCOLS = ("CREATOR", "FILE_TIMESTAMP", ".*_PATH$")

REF_INPUT_PATH = Path(__file__).parent.parent / "data/reference_inputs"
ERRDUMP_LOG_PATH = Path(__file__).parent.parent / "logs" / "test_errors.log"
