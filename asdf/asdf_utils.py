"""generic utility-type functions for asdf"""
import io
import os
import gzip
import tarfile
import random
import string
from pathlib import Path
from typing import Union

import pandas as pd
from cytoolz import keyfilter
from fs.osfs import OSFS

from asdf.console import aprint


def dashwrite(df, target: Union[io.BufferedIOBase, str]):
    buf = io.BytesIO() if isinstance(target, str) else target
    df.astype('str').replace('', '-').to_csv(buf, index=None)
    buf.seek(0)
    if isinstance(target, str):
        with open(target, "wb") as stream:
            stream.write(buf.read().replace(b'NaN', b'-'))
    buf.seek(0)
    return buf


def obfuscated_name():
    return "".join(random.choices(string.ascii_letters + string.digits, k=26))


def add_ref_to_roi(pointing_name, roi_fits):
    """put ref, e.g. pointing name, in FITS metadata"""
    for hdu in roi_fits:
        hdu.header["IMAGEREF"] = pointing_name
    return roi_fits


def save_roi_file(roi_fits, outpath=".", extension=".fits.gz", verbose=True):
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


def load_roi_file(roi_path, title="", verbose=True):
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


def null_marslab_data_section():
    return pd.DataFrame({"COLOR": "-", "INSTRUMENT": "ZCAM"}, index=[0])


def dir_fs(path: Union[str, Path]) -> OSFS:
    path = Path(path)
    if not path.is_dir:
        path = path.parent
    return OSFS(str(path))


# TODO: fully deprecate
def tar_bytes(filename):
    tarbuffer = io.BytesIO()
    fits_tar = tarfile.open(fileobj=tarbuffer, mode="w:gz")
    fits_tar.add(filename, Path(filename).name)
    fits_tar.close()
    tarbuffer.seek(0)
    return tarbuffer


def cast_to_reference(df, reference):
    return df.astype(keyfilter(lambda key: key in df.columns, reference))
