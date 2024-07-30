"""generic utility-type functions for asdf"""
from __future__ import annotations

import io
import os
import gzip
import tarfile
import random
import string
from pathlib import Path
from typing import Union, Optional, TYPE_CHECKING
import re

import pandas as pd
from cytoolz import keyfilter
from fs.osfs import OSFS

from asdf.console import aprint

if TYPE_CHECKING:
    from astropy.io.fits.hdu import ImageHDU, HDUList
    import numpy as np

NULL_PATTERN = re.compile(r"(^|,)( +)?(NaN|nan|None)( +)?(?=,)")


def dashwrite(
    df: pd.DataFrame, target: Optional[str] = None
) -> Union[io.BytesIO, str]:
    """
    Write a dataframe to disk or buffer as a CSV file, replacing all nan-like
    values with "-" for easy reading. Returns the write path or the filled
    buffer.
    """
    cols = {}
    for col, item in df.items():
        cols[col] = (
            item
            .astype(str)
            .str.replace("nan|NaN|None|none|(^$)", "-", regex=True)
        )
    df = pd.DataFrame(cols)
    target = target if isinstance(target, str) else io.BytesIO()
    df.to_csv(target, index=None)
    if not isinstance(target, str):
        target.seek(0)
    return target


def obfuscated_name() -> str:
    """
    Generate an obfuscated filename for a thumbnail. Simple security-through-
    obscurity measure for thumbnails intended for embedding in Google Sheets.
    """
    return "".join(random.choices(string.ascii_letters + string.digits, k=26))


def add_ref_to_roi(pointing_name: str, roi_fits: HDUList) -> HDUList:
    """Put ref, e.g. pointing name, in FITS metadata"""
    for hdu in roi_fits:
        hdu.header["IMAGEREF"] = pointing_name
    return roi_fits


def save_roi_file(
    roi_fits: HDUList,
    outpath: str = ".",
    extension: str = ".fits.gz",
    verbose: bool = True
) -> str:
    """
    Save ROIs contained in an astropy HDUList to disk as a marslab ROI file.
    """
    # optionally resave
    # TODO: should we actually add feature names to the ROI files?
    #  so therefore wait to save until after grilling the user?
    # TODO: this whole convert-while-loading logic is convoluted and needs
    #  to be extracted from the loading loop. save and load functions should
    #  be distinct.
    if "IMAGEREF" in roi_fits[0].header.keys():
        title = f"{roi_fits[0].header['IMAGEREF']}"
    else:
        title = "roi"
    if not Path(outpath).exists():
        os.makedirs(outpath)
    roi_fits_fn = Path(outpath, f"{title}{extension}")
    zipfile = gzip.open(roi_fits_fn, mode='wb')
    roi_fits.writeto(zipfile)
    if verbose:
        aprint("wrote " + str(roi_fits_fn))
    return str(roi_fits_fn)


def load_roi_file(
    roi_path: Union[str, Path], title: str = "", verbose: bool = True
) -> HDUList:
    """
    Loads ROIs from a marslab ROI FITS file or a MERSpect .sel file into memory
    as an astropy HDUList.
    """
    from marslab.compat.sel_to_roi import is_sel_file, sel_to_roi

    # TODO: move this chatter elsewhere
    # if passed ROI file is a SEL, convert to marslab FITS
    is_sel = is_sel_file(roi_path)
    if is_sel:
        roi_fits = sel_to_roi(roi_path, "ZCAM")
        if verbose:
            aprint("loaded MERspect .sel file")
    # if it's FITS, just load it
    else:
        from astropy.io import fits

        if str(roi_path).endswith('.gz'):
            # astropy technically reads this transparently but is slow
            zipfile = gzip.open(roi_path, 'rb')
            roi_fits = fits.HDUList.fromstring(zipfile.read())
            zipfile.close()
        else:
            roi_fits = fits.open(roi_path)
        if verbose:
            aprint("loaded marslab ROI FITS file")
    # add optional reference (like analysis name)
    roi_fits = add_ref_to_roi("roi_" + title, roi_fits)
    return roi_fits


def null_marslab_data_section() -> pd.DataFrame:
    """
    Creates a DataFrame suitable for use as the placeholder data section of
    an 'empty' (no ROIs) marslab file.
    """
    return pd.DataFrame({"COLOR": "-", "INSTRUMENT": "ZCAM"}, index=[0])


def dir_fs(path: Union[str, Path]) -> OSFS:
    """
    Produces a pyfilesystem OSFS object rooted at `path` if `path` is a
    directory, and `path`'s containing directory if it is not.
    """
    path = Path(path)
    if not path.is_dir:
        path = path.parent
    return OSFS(str(path))


# TODO: fully deprecate
def tar_bytes(filename: Union[str, Path]) -> io.BytesIO:
    """
    Load a file and write a tarred and gzipped version of it into a buffer.
    """
    tarbuffer = io.BytesIO()
    fits_tar = tarfile.open(fileobj=tarbuffer, mode="w:gz")
    fits_tar.add(filename, Path(filename).name)
    fits_tar.close()
    tarbuffer.seek(0)
    return tarbuffer


def cast_to_reference(
    df: pd.DataFrame, reference: dict[str, Union[str, np.dtype]]
) -> pd.DataFrame:
    """
    Return a version of `df` with any column whose name matches a key of
    `reference` typecast to the corresponding value of `reference`.
    """
    return df.astype(keyfilter(lambda key: key in df.columns, reference))
