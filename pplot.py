"""user-facing noninteractive pplot utility"""

from clize import run

import importlib
pretty_plot = importlib.import_module("pretty-plot")


# tell clize to handle command line call
if __name__ == '__main__':
    run(pretty_plot.pplot.cli.do_pplot)