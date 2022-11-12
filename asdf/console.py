"""
lightweight shared objects for formatting output to terminal
"""
import logging
from functools import reduce
from operator import add
from pathlib import Path

from rich.console import Console
from rich.highlighter import RegexHighlighter
from rich.padding import Padding
from rich.progress import Progress, TextColumn
from rich.spinner import Spinner
from rich.text import Text
from rich.theme import Theme


class RichProgressHandler(logging.Handler):
    """blunt instrument to treat log messages as progress callbacks"""

    def __init__(self, *args, prog=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.prog = prog
        self.level = logging.INFO
        self.task_id = None
        self.verbose = True
        self.padded = True

    def emit(self, record):
        if self.task_id is not None and self.task_id in self.prog.task_ids:
            self.prog.advance(self.task_id)
        if self.verbose:
            message = Padding(record.msg) if self.padded else record.msg
            self.prog.print(message, highlight=None)


class ASDFGH(RegexHighlighter):
    base_style = "ASDF."
    highlights = [
        r"(?P<missing>(skipping))",
        r"(?P<prep>(uploaded|loaded|generated|found|converted))",
        r"(?P<output>(wrote|completed))",
        r"(?<=[Z _])(?P<id>[R|L]\d[RGB]?)",
        r"(?P<id>(zcam|ZCAM)\d\d\d\d\d)",
        r"(?P<id>(sol|SOL)\d{2,4})",
        r"(?P<selection>\(\d{1,3}\))",
        r"(?P<marslab>(.*roi.*fits.*)|(.*marslab.*csv))",
    ]


# TODO: dark and light themes
ASDFTH = Theme(
    {
        "ASDF.output": "green1",
        "ASDF.prep": "aquamarine3",
        "ASDF.id": "dark_turquoise",
        "ASDF.selection": "bold",
        "ASDF.missing": "purple4",
        "ASDF.marslab": "italic orchid1",
        "FDSA": "hot_pink on black",
        "FDSA.warning": "slate_blue1 on black",
    }
)


# set up ```rich``` objects for formatting
ASDF_CONSOLE = Console(highlighter=ASDFGH(), theme=ASDFTH)


def aprint(renderable, padded=True, **print_kwargs):
    if padded:
        renderable = Padding(renderable)
    return ASDF_CONSOLE.print(renderable, **print_kwargs)


ASDF_PROGRESS = Progress(console=ASDF_CONSOLE)


def render_spinners(spinners, task):
    return reduce(
        add, [spinner.render(task.get_time()) for spinner in spinners]
    )


class SpinTextColumn(TextColumn):
    def __init__(
        self,
        text_format: str,
        spinner_names=None,
        postspinner_names=None,
        style="none",
        speed: float = 1.0,
        **kwargs
    ) -> None:
        super().__init__(text_format, style, **kwargs)
        if spinner_names:
            self.spinners = [
                Spinner(spinner_name, style=style, speed=speed)
                for spinner_name in spinner_names
            ]
        else:
            self.spinners = []
        if postspinner_names:
            self.postspinners = [
                Spinner(spinner_name, style=style, speed=speed)
                for spinner_name in postspinner_names
            ]
        else:
            self.postspinners = []

    def render(self, task: "Task"):
        _text = self.text_format.format(task=task)
        if self.markup:
            text = Text.from_markup(
                _text, style=self.style, justify=self.justify
            )
        else:
            text = Text(_text, style=self.style, justify=self.justify)
        if self.highlighter:
            self.highlighter.highlight(text)
        if self.spinners:
            text = render_spinners(self.spinners, task) + text
        if self.postspinners:
            text = text + render_spinners(self.postspinners, task)
        return text


ASDF_PROGRESS_SPIN = Progress(
    SpinTextColumn(
        text_format="{task.description}                            ",
        spinner_names=["star"],
    ),
    console=ASDF_CONSOLE,
    expand=True,
)

ASDF_RPH = RichProgressHandler(prog=ASDF_PROGRESS)
ASDF_RPH_SPIN = RichProgressHandler(prog=ASDF_PROGRESS_SPIN)

ASDFLOG = logging.getLogger(__name__)
log_dir = Path(Path(__file__).parent.parent, "logs")
log_dir.mkdir(exist_ok=True)
ASDFLOG.addHandler(logging.FileHandler(Path(log_dir, "asdf.log")))
