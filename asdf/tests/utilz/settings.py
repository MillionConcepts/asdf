# regex patterns for marslab fields we intend to be different on different
# executions
from pathlib import Path

VARCOLS = ("CREATOR", "FILE_TIMESTAMP", ".*_PATH$")
ERRDUMP_LOG_PATH = Path(__file__).parent.parent / "e2e_failure_dumps"
TEST_OUTPUT_DIR = Path(__file__).parent.parent / "temp/test_outputs"
REGEN_OUTPUT_DIR = Path(__file__).parent.parent / "temp/regen_outputs"
REF_INPUT_DIR = Path(__file__).parent.parent / "data/reference_inputs"
REF_OUTPUT_DIR = Path(__file__).parent.parent / "data/reference_outputs"
