"""generic utility-type functions for asdf"""

from collections.abc import Collection
import random
import string
from pathlib import Path

import numpy as np
import pandas as pd
from astropy.io import fits
from fs.osfs import OSFS

from asdf.console import aprint
from marslab.compat.sel_to_roi import is_sel_file, sel_to_roi


def dashify(df):
    return df.replace("", "-").fillna("-")


def pass_parameters(func, *args, **kwargs):
    return func(*args, **kwargs)


def catch_interaction(noninteractive, func, *args, **kwargs):
    if noninteractive:
        return ""
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
    roi_path,
    title="",
    outpath=".",
    extension="-roi.fits",
    convert=False,
    verbose=True,
):
    # TODO: move this chatter elsewhere
    # if passed ROI file is a SEL, convert to marslab FITS
    if is_sel_file(roi_path):
        roi_fits = sel_to_roi(roi_path, "ZCAM")
        if verbose:
            aprint("loaded MERspect .sel file")
    # if it's FITS, just load it
    else:
        roi_fits = fits.open(roi_path)
        if verbose:
            aprint("loaded marslab ROI FITS file")
    # add optional reference (like pointing name)
    roi_fits = add_ref_to_roi(title, roi_fits)
    # optionally resave
    # TODO: should we actually add feature names to the ROI files?
    #  so therefore wait to save until after grilling the user?
    # TODO: this whole convert-while-loading logic is convoluted and needs
    #  to be extracted from the loading loop. save and load functions should
    #  be distinct.
    if convert:
        roi_fits_fn = Path(outpath, title + extension)
        roi_fits.writeto(roi_fits_fn, overwrite=True)
        if verbose:
            aprint("wrote " + str(roi_fits_fn))
    else:
        roi_fits_fn = None
    # TODO: returning the filename like this is sort of clumsy
    return roi_fits, str(roi_fits_fn)


def null_marslab_data_section():
    return pd.DataFrame({"COLOR": "-", "INSTRUMENT": "ZCAM"}, index=[0])


def check_and_drop_duplicate_columns(dataframe):
    extra_columns = dataframe.columns[dataframe.columns.duplicated()]
    if len(extra_columns) == 0:
        return dataframe
    for column in extra_columns:
        test_equality = (
            dataframe.loc[:, column] == dataframe.loc[:, column].iloc[0, 0]
        )
        assert test_equality.all(axis=None)
    return dataframe.loc[:, ~dataframe.columns.duplicated()]


def extract_constants(df, to_dict=True, drop_constants=False):
    constant_columns = df.nunique() == 1
    constants = df.loc[:, constant_columns]
    variables = df.loc[:, ~constant_columns]
    if to_dict:
        constants = constants.iloc[0].to_dict()
    if drop_constants:
        return constants, variables
    return constants, df


def split_on(
    df: pd.DataFrame, predicate: pd.Series
) -> [pd.DataFrame, pd.DataFrame]:
    return df.loc[predicate], df.loc[~predicate]


def dir_fs(path):
    path = Path(path)
    if not path.is_dir:
        path = path.parent
    return OSFS(str(path))


def listify(thing):
    """Always a list, for things that want lists"""
    if isinstance(thing, Collection):
        if not isinstance(thing, str):
            return list(thing)
    return [thing]


def pdstr(str_method_name, *str_args, **str_kwargs):
    """
    creates a mappable function that accesses .str methods of passed Series
    """
    def replacer(series: pd.Series):
        method = getattr(series.str, str_method_name)
        return method(*str_args, **str_kwargs)

    return replacer
