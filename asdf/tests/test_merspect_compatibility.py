"""
TODO: some version of this functionality should also go in _marslab_, but I
 think all our extant .sel files are covered by Team Guidelines. Let's get
 some released, or make a decent set of fake ones, and also include a
 similar test in _marslab_.
"""
import os
from pathlib import Path

from astropy.io import fits
import numpy as np
import pytest
from scipy.io import readsav

from asdf.asdf_utils import load_roi_file
from marslab.compat.mertools import MERSPECT_M20_COLOR_MAPPINGS

roi_paths = {path.name: path for path in Path("data/sels").iterdir()}

COLOR_TO_VALUE = {
    color: ix + 1 for ix, color in enumerate(MERSPECT_M20_COLOR_MAPPINGS)
}


@pytest.mark.parametrize("_,roi_path", roi_paths.items())
def test_roi_sel_roundtrip(_, roi_path):
    """
    very simple test: make sure we can open a MERSpect .sel, write it out,
    and read it back in; and also, that when we do so, each HDU matches the
    expected "color index" of matching spatial indices in the
    corresponding-eye array in the .sel
    """
    sav = readsav(str(roi_path))
    sav_arrays = {
        "left": np.flipud(sav["lseltemp"]),
        "right": np.flipud(sav["rseltemp"]),
    }
    load_roi_file(roi_path, title="tmp", outpath=".", convert=True)
    roi_fits = fits.open("roi_tmp.fits.gz")
    for roi in roi_fits:
        eye = roi.header["EYE"]
        color_ix = COLOR_TO_VALUE[roi.header["NAME"]]
        roi_pixels = np.nonzero(roi.data)
        assert np.all(sav_arrays[eye][roi_pixels] == color_ix)
    os.unlink("roi_tmp.fits.gz")
