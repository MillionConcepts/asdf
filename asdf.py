"""user-facing asdf CLI script"""

from clize import run

import asdf.cli


# tell clize to handle command line call
if __name__ == "__main__":
    run(asdf.cli.asdf)
