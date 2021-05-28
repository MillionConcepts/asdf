"""
this module holds functions for procedurally-generated sections of settings
files, basically to enhance their readability. it specifically holds
"""
from copy import deepcopy
from itertools import chain

import cv2
import numpy as np
from cytoolz.functoolz import curry
from matplotlib.cm import register_cmap
from matplotlib.colors import ListedColormap
from scipy.ndimage import gaussian_filter

from marslab.compat.xcam import make_xcam_filter_dict
from marslab.imgops.imgutils import split_filter

FILTER_DATA_COLUMNS = tuple(
    chain.from_iterable(
        [
            (filt, filt + "_ERR")
            for filt in make_xcam_filter_dict("ZCAM").keys()
        ]
    )
)


# default smoothing: applies gaussian kernel to each channel of an image
# individually
smoother = split_filter(curry(gaussian_filter), axis=0)


def make_orange_teal_cmap():
    teal = (98, 252, 232)
    orange = (255, 151, 41)
    half_len = 256
    vals = np.ones((half_len * 2, 4))
    vals[0:half_len, 0] = np.linspace(orange[0] / half_len, 0, half_len)
    vals[0:half_len, 1] = np.linspace(orange[1] / half_len, 0, half_len)
    vals[0:half_len, 2] = np.linspace(orange[2] / half_len, 0, half_len)
    vals[half_len:, 0] = np.linspace(0, teal[0] / half_len, half_len)
    vals[half_len:, 1] = np.linspace(0, teal[1] / half_len, half_len)
    vals[half_len:, 2] = np.linspace(0, teal[2] / half_len, half_len)
    return ListedColormap(vals, name="orange_teal")


# TODO: clean this up
def make_aqua_pink_accent_cmap():
    aqua = (0, 1, 1, 1)
    pink = (1, 0, 1, 1)
    transparent = (0.5, 0.5, 0.5, 0)
    vals = np.full((10, 4), transparent)
    for channel in range(3):
        vals[:, channel][0] = aqua[channel]
        vals[:, channel][-1] = pink[channel]
    return ListedColormap(vals, name="aqua_pink")


register_cmap(cmap=make_aqua_pink_accent_cmap())
register_cmap(cmap=make_orange_teal_cmap())


def make_bilateralfilter(d, sigmaColor, sigmaSpace):
    """
    cv2.bilateralFilter has under-the-hood dispatch resolution
    that chokes on the gradual partial evaluation we use later
    in the pipeline, so we pre-bind arguments to it here in a closure.
    """
    def do_bilateralfilter(array):
        return cv2.bilateralFilter(
            array, d=d, sigmaColor=sigmaColor, sigmaSpace=sigmaSpace
        )

    return do_bilateralfilter


