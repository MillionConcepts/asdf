"""generic utility-type functions for asdf"""
import io
import os
import shutil
import gzip
import tarfile
from collections import defaultdict
from collections.abc import Collection, Mapping
from copy import copy
from itertools import accumulate, repeat
from operator import add
import random
import string
from pathlib import Path

from cytoolz.dicttoolz import merge
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


def naturals():
    return accumulate(repeat(1), add)


def load_roi_file(
    roi_path,
    title="",
    outpath=".",
    extension="-roi.fits.gz",
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
        if str(roi_path).endswith('.gz'):
            # astropy technically reads this transparently but is slow
            zipfile = gzip.open(roi_path, 'rb')
            fitsbytes = io.BytesIO(zipfile.read())
            roi_fits = fits.open(fitsbytes)
            zipfile.close()
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
        if not Path(outpath).exists():
            os.makedirs(outpath)
        roi_fits_fn = Path(outpath, title + extension)
        if roi_fits.filename():
            if Path(roi_fits_fn).absolute() == Path(roi_fits.filename()):
                roi_fits_fn = Path(str(roi_fits_fn) + ".tmp")
        zipfile = gzip.open(roi_fits_fn, mode='wb')
        roi_fits.writeto(zipfile)
        if roi_fits_fn.suffix == '.tmp':
            roi_fits.close()
            shutil.move(roi_fits_fn, str(roi_fits_fn)[:-4])
            roi_fits_fn = Path(str(roi_fits_fn)[:-4])
            roi_fits = fits.open(roi_fits_fn)
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


class NestingDict(defaultdict):
    """
    shorthand for automatically-nesting dictionary -- i.e.,
    insert a series of keys at any depth into a NestingDict
    and it automatically creates all needed levels above.
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.default_factory = NestingDict

    __repr__ = dict.__repr__


def to_records(nested, accumulated_levels=None, level_names=None):
    level_names = naturals() if level_names is None else iter(level_names)
    records = []
    accumulated_levels = {} if accumulated_levels is None else \
        accumulated_levels
    level_name = next(level_names)
    for category, mapping in nested.items():
        if all([isinstance(value, Mapping) for value in mapping.values()]):
            branch = accumulated_levels.copy()
            branch[level_name] = category
            records += to_records(mapping, branch, copy(level_names))
        else:
            category_dict = accumulated_levels | {level_name: category}
            flat = mapping | category_dict
            records.append(flat)

    return records


def unnest(mapping_mapping):
    unnested = []
    for category, mapping in mapping_mapping.items():
        unnested.append({
            str(category) + "_" + str(key): value for key, value
            in mapping.items()
        })
    return merge(unnested)


# TODO: fully deprecate
def tar_bytes(filename):
    tarbuffer = io.BytesIO()
    fits_tar = tarfile.open(fileobj=tarbuffer, mode="w:gz")
    fits_tar.add(filename, Path(filename).name)
    fits_tar.close()
    tarbuffer.seek(0)
    return tarbuffer
