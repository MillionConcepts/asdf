"""
Settings for multiple pretty-plot variations.
"""

BASE_PPLOT = {}
NORM_PPLOT = {
    "kwargs": {"normalize": "L2"},
    "suffix": "norm"
}
NORM_OFFSET_PPLOT = {
    "kwargs": {
        "normalize": "L2", "offset": 0.2, "height_sf": 1.5, "width_sf": 0.8
    },
    "suffix": "norm-offset"
}


PRETTY_PLOT_DEFINITIONS = (
    BASE_PPLOT,
    NORM_PPLOT,
    NORM_OFFSET_PPLOT
)