"""
this module is separate from generators so you don't have to import every
imaging thing immediately.
"""
from itertools import chain

from marslab.compat.xcam import make_xcam_filter_dict

FILTER_DATA_COLUMNS = tuple(
    chain.from_iterable(
        [
            (filt, filt + "_ERR")
            for filt in make_xcam_filter_dict("ZCAM").keys()
        ]
    )
)

