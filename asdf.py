"""user-facing asdf CLI script"""
from inspect import signature
import re
import sys
from types import MappingProxyType
from typing import Callable, Mapping

import fire

ARG_ABBREVIATIONS = {
    "o": "output",
    "a": "abbreviate",
    "r": "skip-rapidlooks",
    "s": "suffix",
    "n": "noninteractive",
    "na": "noninteractive-all",
    "d": "debug",
    "kb": "keep-broadband",
    "kg": "keep-caltarget",
    "kt": "keep-thumbnails",
    "m": "mosaic",
    "mer": "merspect",
    "v": "recursive",
    "pd": "pathdump",
    "ir": "image-regex",
    "sp": "skip-pixmaps",
    "se": "skip-errmaps",
    "sn": "seriously-no-images",
    "rm": "reuse-mosaic",
    "ki": "keep-intermediate",
    "xyz": "spatial"
}


def rearrange_args(
    func: Callable,
    args: list[str],
    abbreviations: Mapping = MappingProxyType({})
):
    """
    Rearrange args for Fire, permitting flags both before and after
    positional arguments.
    """
    params = {
        k.replace('_', '-'): v for k, v in
        dict(signature(func).parameters).items()
    }
    beginning, middle, end = [args[0]], [], []
    position = 0
    while position + 1 < len(args):
        position += 1
        arg = args[position]
        if not arg.startswith('-'):
            middle.append(arg)
            continue
        if re.match(r"-\w", arg) and arg.strip('-') in abbreviations.keys():
            argrep = f"--{abbreviations[arg.strip('-')]}"
        else:
            argrep = arg
        maparg = argrep.strip('-').replace('_', '-')
        if maparg not in params.keys():
            raise TypeError(f"Argument {arg} not understood.")
        if (params[maparg].annotation == bool) or (position + 1 == len(args)):
            end.append(argrep)
            continue
        middle += [argrep, args[position + 1]]
        position += 1
    return beginning + middle + end


# TODO: just replace Fire entirely with argparse
# tell Fire to handle command line call
if __name__ == "__main__":
    import asdf.cli_endpoint

    if not any("help" in a for a in sys.argv):
        sys.argv = rearrange_args(
            asdf.cli_endpoint.asdf_initiate,
            sys.argv,
            ARG_ABBREVIATIONS
        )
    fire.Fire(asdf.cli_endpoint.asdf_initiate)
