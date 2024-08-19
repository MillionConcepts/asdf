"""user-facing asdf CLI script"""

import fire


# TODO: just replace Fire entirely with argparse
def rearrange_args(args):
    """
    Rearrange args for Fire, permitting flags both before and after
    positional arguments.
    """
    base, pos, flag = [args[0]], [], []
    for a in args[1:]:
        target = flag if a.startswith('-') else pos
        target.append(a)
    return base + pos + flag


# tell fire to handle command line call
if __name__ == "__main__":
    import asdf.cli_endpoint
    import sys

    sys.argv = rearrange_args(sys.argv)
    fire.Fire(asdf.cli_endpoint.asdf_initiate)
