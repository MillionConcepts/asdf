"""user-facing noninteractive pretty_plot utility"""

import fire

# import importlib
# pretty_plot = importlib.import_module("pretty-plot")

import pretty_plot

# tell fire to handle command line call
if __name__ == '__main__':
    fire.Fire(pretty_plot.cli.do_pplot)
