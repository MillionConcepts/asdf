"""user-facing noninteractive pretty_plot utility"""

from clize import run

# import importlib
# pretty_plot = importlib.import_module("pretty-plot")

import pretty_plot

# tell clize to handle command line call
if __name__ == '__main__':
    run(pretty_plot.cli.do_pplot)
