"""
shared objects for formatting output to terminal
"""
import logging

from rich.highlighter import Highlighter, RegexHighlighter
from rich.theme import Theme

from marslab.imgops.bandset import log as bandlog
from rich.console import Console
from rich.progress import Progress


class RichProgressHandler(logging.Handler):
    """blunt instrument to treat log messages as progress callbacks"""
    def __init__(self, *args, prog=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.prog = prog
        self.level = logging.INFO
        self.task_id = None
        self.verbose = True

    def emit(self, record):
        if self.task_id is not None:
            if self.task_id in self.prog.task_ids:
                self.prog.advance(self.task_id)
        if self.verbose:
            self.prog.print(record.msg, highlight=None)


class EmailHighlighter(RegexHighlighter):
    """Apply style to anything that looks like an email."""

    base_style = "example."
    highlights = [r"(?P<email>[\w-]+@([\w-]+\.)+[\w-]+)"]


class ASDFGH(RegexHighlighter):
    base_style = "ASDF."
    highlights = [
        r"(?P<good>(loaded|generated|wrote|writing))",
        r"(?<=[Z _])(?P<id>[R|L]\d[RGB]?)", r"(?P<id>(zcam|ZCAM)\d\d\d\d\d)"
    ]

ASDFTH = Theme({"ASDF.good": "sea_green2", "ASDF.id": "turquoise2"})

# set up ```rich``` objects for formatting
ASDF_CONSOLE = Console(highlighter=ASDFGH(), theme=ASDFTH)
ASDF_PROGRESS = Progress(console=ASDF_CONSOLE)
ASDF_RPH = RichProgressHandler(prog=ASDF_PROGRESS)
ASDFLOG = logging.getLogger(__name__)
for log in (bandlog, ASDFLOG):
    log.setLevel(logging.INFO)
    log.addHandler(ASDF_RPH)
