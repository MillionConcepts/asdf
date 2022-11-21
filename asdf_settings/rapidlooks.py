# import statements -- don't mess with these
from copy import deepcopy
from pathlib import Path

import matplotlib.font_manager as mplf
import numpy as np

from marslab.imgops.imgutils import (
    std_clip,
    normalize_range,
    centile_clip,
)
from marslab.imgops.masking import threshold_mask, skymask
from marslab.imgops.render import colormapped_plot, simple_figure
from .generators import glom

# font settings for annotations on rapidlooks -- bear in mind that the
# images are rendered at 275 dpi, so the sizes may be smaller than you
# expect they should be
WORKING_DIRECTORY = Path(__file__).parent
FONT_PATH = glom(WORKING_DIRECTORY.parent, "static/fonts")
TITILLIUM = glom(FONT_PATH, "TitilliumWeb-Light.ttf")
TITLE_FONT = mplf.FontProperties(fname=TITILLIUM, size=11.2)
ANNOTATION_FONT = mplf.FontProperties(fname=TITILLIUM, size=8.8)
TICK_FONT = mplf.FontProperties(fname=TITILLIUM, size=6)
ROI_FONT = mplf.FontProperties(fname=TITILLIUM, size=5)
LEGEND_FONT = mplf.FontProperties(fname=TITILLIUM, size=7)

# positions of image title and remainder of annotation, in
# percentage of plot height -- if you change font size, you
# may need to change these as well
TITLE_POSITION = -0.028
ANNOTATION_POSITION = -0.088

# default settings for band parameter maps
# note: "cmap" defines a colormap used by a rapidlook. "orange_teal",
# "red_blue", and "aqua_pink" are custom asdf/marslab cmaps. others are
# from matplotlib's default library. for a list of built-in matplotlib cmaps,
# see: https://matplotlib.org/stable/gallery/color/colormap_reference.html
# {look} is the name of the look, e.g. "band_depth"; "bands" is the name of
# the filters involved in the look
BANDMAP_DEFAULTS = {
    "name": "{look} {bands}",
    "limiter": {"function": std_clip},
    "plotter": {
        "function": colormapped_plot,
        "params": {
            "cmap": "inferno",
            "colorbar_fp": TICK_FONT,
            "render_colorbar": True,
        },
    },
}

# default settings for DCS and similar stretch-centric looks
STRETCHY_DEFAULTS = {
    "name": "dcs {bands}",
    "look": "dcs",
    "params": {"contrast_stretch": 1},
    "plotter": {"function": simple_figure},
}

# default settings for enhanced color looks
ENHANCED_DEFAULTS = {
    "name": "enhanced color {bands}",
    "look": "composite",
    "prefilter": {
        "function": normalize_range,
        "params": {"stretch": (1.25, 1)},
    },
    "plotter": {"function": simple_figure},
}

# default settings for rgb bandmap looks
RGB_BANDMAP_DEFAULTS = {
    "look": "nested_composite",
    "plotter": {
        "function": simple_figure,
        "params": {"interpolation": "none"},
    },
}

# default settings for natural color looks
NATURAL_DEFAULTS = {
    "name": "natural color {bands}",
    "look": "composite",
    "limiter": {"function": normalize_range, "params": {"stretch": 0.1}},
    "plotter": {"function": simple_figure},
}

# crop dimensions for rapidlooks. a setting of (25, 25, 11, 11)
# effectively crops off the physically-masked "frame" around the detector.
CROP_SETTINGS = {
    "crop": (25, 25, 11, 11),
}

SHADOW_MASK = [
    {
        "function": threshold_mask,
        "params": {"percentiles": (8, 100), "operator": "mean"},
        "colorfill": {"color": 0.45, "mask_alpha": 1},
        "pass": True,
        "send": True,
    },
]

DARK_SHADOW_MASK = [
    {
        "function": threshold_mask,
        "params": {"percentiles": (5, 100), "operator": "and"},
        "pass": True,
        "send": False
    }
]


SKY_MASK = [
    {
        "function": skymask,
        "params": {
            "percentile": 75,
            "edge_params": {'maximum': 5, 'edge_thresholds': (60, 110)},
            "trace_maximum": 5,
            "cutoffs": {'coverage': 0.9, 'extent': 0.015, 'v': 0.9, 'h': 0.3},
        },
        "colorfill": {"color": 0, "mask_alpha": 1},
        "pass": True,
        "send": True
    }
]

#############################################################################
#                      explicit rapidlook definitions
#############################################################################
# BANDMAP_DEFAULTS are automatically added
# to all these looks -- other useful looks might be "ratio" and "band_avg"
BANDMAP = (
    {"look": "band_depth", "bands": ("L6", "L4", "L5")},
    {"look": "band_depth", "bands": ("R1", "R4", "R2")},
    {"look": "band_depth", "bands": ("L4", "L2", "L3")},
    {"look": "band_depth", "bands": ("R1", "R5", "R3")},
    {"look": "slope", "bands": ("R5", "R6")},
    {"look": "slope", "bands": ("R1", "R6")},
)
# ENHANCED_DEFAULTS are added to these
ENHANCED = (
    {"bands": ("L2", "L5", "L6")},
    {"bands": ("L0R", "L0G", "L0B")},
    {"bands": ("R0R", "R0G", "R0B")},
)
# NATURAL_DEFAULTS are added to these
NATURAL = (
    {"bands": ("L0R", "L0G", "L0B")},
    {"bands": ("R0R", "R0G", "R0B")},
)
# STRETCHY_DEFAULTS are added to these
STRETCHY = (
    {"bands": ("L2", "L5", "L6")},
    {"bands": ("R0R", "R0G", "R0B")},
    {"bands": ("L0R", "L0G", "L0B")},
    {"bands": ("R6", "R3", "R1")},
)
# inline 'shadow mask' for the RGB bandmaps
RGB_BANDMAP_THRESHOLD = [
    {
        "function": threshold_mask,
        "params": {"percentiles": (10, 100)},
        "pass": True,
        "send": False,
    },
]
# RGB_BANDMAP_DEFAULTS are added to these
# noinspection PyTypeChecker
mafic_map = {
        # placing single quotes causes asdf to print the title verbatim
        "name": "'mafic bandmap: R0R/R1 BD910 R1/R5'",
        "params": {
            "norm_kwargs": {"bounds": (0.2, 1)},
            "red": {
                "look": "ratio",
                "mask": {"instructions": RGB_BANDMAP_THRESHOLD + SKY_MASK},
                "bands": ("R0R", "R4"),
                "limiter": {
                    # switch this to a masked-outside thing
                    "function": np.ma.masked_less,
                    "params": {"value": 1, "copy": False},
                },
                "postfilter": {
                    # "function": lambda array: np.zeros(array.shape)
                    "function": centile_clip,
                    "params": {"centiles": (50, 98)},
                },
            },
            # red: pathological? maybe plagioclase?
            # yellow: low-ca pyroxene or olivine
            # green: high-ca pyroxene or olivine
            # cyan/purple: just green and red
            # blue: ?
            "green": {
                "mask": {"instructions": RGB_BANDMAP_THRESHOLD + SKY_MASK},
                "look": "band_depth",
                "bands": ("R1", "R5", "R3"),
                "limiter": {
                    "function": np.ma.masked_outside,
                    "params": {"v1": 0, "v2": 1, "copy": False},
                },
                "postfilter": {
                    # "function": lambda array: np.zeros(array.shape)
                    "function": centile_clip,
                    "params": {"centiles": (10, 98)},
                },
            },
            "blue": {
                "look": "ratio",
                "mask": {"instructions": RGB_BANDMAP_THRESHOLD + SKY_MASK},
                "bands": ("R1", "R5"),
                "limiter": {
                    "function": np.ma.masked_less,
                    "params": {"value": 1.05, "copy": False},
                },
                "postfilter": {
                    # "function": lambda array: np.zeros(array.shape)
                    "function": centile_clip,
                    "params": {"centiles": (10, 98)},
                }
                # postfilter with percentile clip maybe just on the top
            },
        },
    }
mmap_unmasked = deepcopy(mafic_map)
for channel in ("red", "green", "blue"):
    del mmap_unmasked["params"][channel]["mask"]
mmap_unmasked['name'] = "'mafic bandmap: R0R/R1 BD910 R1/R5 um'"
RGB_BANDMAP = [mafic_map, mmap_unmasked]


# this notifies the look assembler to consider the categories above
# and associate them with their defaults.
CATEGORIES = ["BANDMAP", "ENHANCED", "NATURAL", "STRETCHY", "RGB_BANDMAP"]
############################################################################
#                 procedurally-generated rapidlooks
#############################################################################

# in general, additional OPTIONS categories should define a "name" key.
# not doing this will tend to cause looks to be clobbered.

MODIFIED_BANDMAP_DEFAULTS = deepcopy(BANDMAP_DEFAULTS)

MASKED_OPTIONS = {
    "mask": {"instructions": SHADOW_MASK + SKY_MASK}, "suffix": "masked",
    "limiter": {"function": std_clip, "params": {"sigma": 0.9}},
}

MODIFIED_STRETCHY_DEFAULTS = deepcopy(STRETCHY_DEFAULTS)

SKYMASK_DCS_OPTIONS = {
    "mask": {"instructions": SKY_MASK + DARK_SHADOW_MASK}, "suffix": "masked",
}

# dictionary of all procedural looks to be generated. general syntax is:
# '$CATEGORY_NAME': (options_for_look, options_for_other_look, ...)
LOOK_GENERATORS = {
    # recolored bandmaps: just give colormap names
    "bandmap": ["orte"],
    "modified_bandmap": [MASKED_OPTIONS],
    "modified_stretchy": [SKYMASK_DCS_OPTIONS],
}

CREDIT_TEXT = "Credit:NASA/JPL/ASU/MSSS/Cornell/WWU/MC"

# any rapidlook listed here will be turned into a thumbnail and uploaded to S3,
# and will also be linked in the Google Sheet if columns are made for them.
THUMBNAILS = (
    "enhanced color L2_L5_L6",
    "dcs L2_L5_L6",
    "enhanced color R0R_R0G_R0B",
    "context image left",
    "context image right",
    "dcs R6_R3_R1",
)
THUMBNAIL_SIZE = (240, 330)
