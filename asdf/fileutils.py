import os
from pathlib import Path
from typing import Generator


class FileRoot:
    """
    simple replacement for the parts of PyFilesystem2's OSFS functionality we
    were using
    """

    def __init__(self, root: Path | str):
        self.root = Path(root).absolute()

    def getsyspath(self, file: Path | str) -> Path:
        return self.root / file

    def walk(self) -> Generator[Path, None, None]:
        walker, files = os.walk(self.root), []
        folder, _, files = next(walker)
        folder = Path(folder)
        while True:
            try:
                # noinspection PyUnresolvedReferences
                yield (folder / files.pop()).relative_to(self.root)
            except IndexError:
                try:
                    folder, _, files = next(walker)
                    folder = Path(folder)
                except StopIteration:
                    break
