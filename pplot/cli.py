from pathlib import Path
import warnings

from fs.osfs import OSFS
import numpy as np
import pandas as pd

import pplot
from pplot.convert import convert_for_plot


def looks_like_marslab(fn):
    if str(fn).endswith('-marslab.csv'):
        return True
    return False


def directory_of(path):
    if path.is_dir():
        return path
    return path.parent


def do_pplot(
        path_or_file,
        *,
        recursive: "r" = False
):
    """
    non-interactive CLI to pretty-plot. generates .png files
    from pretty-plot's default settings, much like when pretty-plot
    is called by asdf.

    all marslab files need SOLAR_ELEVATION, SEQ_ID, and SOL or things
    will not work out.

    param path_or_file: marslab file or directory containing marslab files
    param recursive: runs pplot on all marslab files in directory tree,
        regardless of what specific file you passed it
    """
    # TODO, maybe: merge or something with handle_pretty_plot()
    path = Path(path_or_file)
    plot_files = []
    if recursive:
        tree = OSFS(directory_of(path))
        marslab_files = map(
            tree.getsyspath,
            filter(looks_like_marslab, tree.walk.files())
        )
    elif path.is_dir():
        marslab_files = filter(looks_like_marslab, path.iterdir())
    else:
        marslab_files = [path]
    for marslab_file in marslab_files:
        try:
            marslab = pd.read_csv(marslab_file).replace("-", np.nan)
            titular_plot_target = "unknown target"
            if "NAME" in marslab.columns:
                names = marslab["NAME"].dropna().unique()
                if len(names) > 0:
                    titular_plot_target = names[0]
            plot_fn = str(marslab_file).replace("-marslab.csv", "-pretty-plot.png")
            print("Writing " + plot_fn)
            marslab_spectra = convert_for_plot(str(marslab_file)).replace(
                "-", np.nan
            )
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                pplot.pplot_utils.pretty_plot(
                    marslab_spectra,
                    target_name=titular_plot_target,
                    sol=marslab["SOL"].iloc[0],
                    solar_elevation=marslab["SOLAR_ELEVATION"].iloc[0],
                    seq_id=marslab["SEQ_ID"].iloc[0],
                    plot_fn=plot_fn,
                    underplot=None
                )
        except (KeyError, ValueError) as error:
            print(
                "couldn't plot "
                + str(marslab_file)
                + ": "
                + str(type(error))
                + " "
                + str(error)
            )
