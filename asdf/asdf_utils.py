"""generic utility-type functions for asdf"""

import gc
import random
import string
from pathlib import Path
from typing import Mapping, Sequence

from astropy.io import fits
from marslab.compat.mertools import is_sel_file, sel_to_roi
from matplotlib.figure import Figure
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


def pass_parameters(func, *args, **kwargs):
    return func(*args, **kwargs)


def catch_interaction(noninteractive, func, *args, **kwargs):
    if noninteractive:
        return "-"
    return func(*args, **kwargs)


def obfuscated_name():
    return "".join(random.choices(string.ascii_letters + string.digits, k=26))


def itemize_numpy(obj):
    """
    convert objects of numpy dtypes to python scalars. in this context,
    primarily for json serialization.
    """
    if isinstance(obj, np.generic):
        return obj.item()
    return obj


def close_fig(thing):
    if isinstance(thing, Figure):
        plt.close(thing)


def absolutely_destroy(thing):
    if isinstance(thing, Mapping):
        keys = list(thing.keys())
        for key in keys:
            del(thing[key])
    elif isinstance(thing, Sequence):
        for _ in thing:
            del _
    else:
        del thing
    plt.close('all')
    gc.collect()


def dupe_df_block(dataframe, rows_to_repeat):
    return pd.DataFrame(
        np.repeat(dataframe.values, rows_to_repeat, axis=0),
        columns=dataframe.columns,
    )


def add_ref_to_roi(pointing_name, roi_fits):
    """put ref, e.g. pointing name, in FITS metadata"""
    for hdu in roi_fits:
        hdu.header["IMAGEREF"] = pointing_name
    return roi_fits


def load_roi_file(
        roi_path, title="", outpath=None, extension="-roi.fits",
        convert=True
):
    # if passed ROI file is a SEL, convert to marslab FITS
    if is_sel_file(roi_path):
        roi_fits = sel_to_roi(roi_path, "ZCAM")
    # if it's FITS, just load it
    else:
        roi_fits = fits.open(roi_path)
    # add optional reference (like pointing name)
    roi_fits = add_ref_to_roi(title, roi_fits)
    # optionally resave
    # TODO: should we actually add feature names to the ROI files?
    #  so therefore wait to save until after grilling the user?
    if convert:
        roi_fits_fn = Path(outpath, title + extension)
        roi_fits.writeto(roi_fits_fn, overwrite=True)
    else:
        roi_fits_fn = None
    return roi_fits, str(roi_fits_fn)


def null_marslab_data_section():
    return pd.DataFrame({"COLOR": "-", "INSTRUMENT": "ZCAM"}, index=[0])
