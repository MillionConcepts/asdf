# import statements -- don't mess with these
from copy import deepcopy
from pathlib import Path

import matplotlib.font_manager as mplf
from scipy.ndimage import gaussian_filter

from .generators import smoother, make_bilateralfilter
from marslab.imgops.imgutils import std_clip, normalize_range
from marslab.imgops.render import colormapped_plot, simple_figure

# font settings for annotations on rapidlooks -- bear in mind that the
# images are rendered at 275 dpi, so the sizes may be smaller than you
# expect they should be
WORKING = Path(__file__).parent
TITLE_FONT = mplf.FontProperties(
    fname=str(
        Path(
            WORKING, str(Path(WORKING, "static/fonts/TitilliumWeb-Light.ttf"))
        )
    ),
    size=11.2,
)

ANNOTATION_FONT = mplf.FontProperties(
    fname=str(Path(WORKING, "static/fonts/TitilliumWeb-Light.ttf")), size=8.8
)
TICK_FONT = mplf.FontProperties(
    fname=str(Path(WORKING, "static/fonts/TitilliumWeb-Light.ttf")), size=6
)
ROI_FONT = mplf.FontProperties(
    fname=str(Path(WORKING, "static/fonts/TitilliumWeb-Light.ttf")), size=5
)
LEGEND_FONT = mplf.FontProperties(
    fname=str(Path(WORKING, "static/fonts/TitilliumWeb-Light.ttf")), size=7
)

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
    "params": {"special_constants": [0]},
    "limiter": {"function": std_clip},
    "postfilter": {"function": gaussian_filter, "params": {"sigma": 2}},
    "plotter": {
        "function": colormapped_plot,
        "params": {
            "cmap": "orange_teal",
            "colorbar_fp": TICK_FONT,
            "render_colorbar": True,
            "special_constants": [0],
        },
    },
}

# default settings for DCS and similar stretch-centric looks
STRETCHY_DEFAULTS = {
    "name": "dcs {bands}",
    "look": "dcs",
    "params": {"special_constants": [0], "contrast_stretch": 1, "sigma": 0.95},
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
    "params": {"special_constants": [0]},
    "plotter": {"function": simple_figure},
}

# default settings for natural color looks
NATURAL_DEFAULTS = {
    "name": "natural color {bands}",
    "look": "composite",
    "params": {"special_constants": [0]},
    "limiter": {"function": normalize_range, "params": {"stretch": 0.1}},
    "plotter": {"function": simple_figure},
}

# crop dimensions for rapidlooks. a setting of (25, 25, 11, 11)
# effectively crops off the physically-masked "frame" around the detector.
CROP_SETTINGS = {
    "crop": (25, 25, 11, 11),
}

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

# this notifies the look assembler to consider the categories above
# and associate them with their defaults.
CATEGORIES = ["BANDMAP", "ENHANCED", "NATURAL", "STRETCHY"]
#############################################################################
#                 procedurally-generated rapidlooks
#############################################################################

# in general, additional OPTIONS categories should define a "name" key.
# not doing this will tend to cause looks to be clobbered.

MASKED_DEFAULTS = deepcopy(BANDMAP_DEFAULTS)
SHADOWED_OPTIONS = {"premask": {"sigma": (1, 0)}}

# sigma-invariant (non-merspect-style) dcs options
INVARIANT_OPTIONS = {"sigma": None, "contrast_stretch": 1}
# defaults for 'accent' - type looks (currently just the aqua-pink overlays)
ACCENT_DEFAULTS = deepcopy(BANDMAP_DEFAULTS)
ACCENT_DEFAULTS["prefilter"] = {"function": make_bilateralfilter(15, 3, 7)}

# settings for the aqua-pink overlays
AQUA_PINK_OVERLAY_OPTIONS = {
    "params": {
        "mpl_settings": {"colorbar_fp": TICK_FONT},
        "overlay_opacity": 0.3,
        "overlay_cmap": "aqua_pink",
        "base_cmap": "Greys_r",
    },
}

# settings for the red-blue overlays
RED_BLUE_OVERLAY_OPTIONS = {
    "name": "{look} {bands} rb accent",
    "params": {
        "mpl_settings": {"colorbar_fp": TICK_FONT},
        "overlay_opacity": 0.4,
        "overlay_cmap": "red_blue",
        "base_cmap": "Greys_r",
    },
}

# default options for 'heatmap' - type looks -- currently in this file
# only including the rainbow looks
HEATMAP_DEFAULTS = deepcopy(BANDMAP_DEFAULTS)
HEATMAP_DEFAULTS["prefilter"] = {
    # syntax for the bilateral filter is slightly different because of a
    # problem in python-opencv
    "function": make_bilateralfilter(10, 10, 10),
}
HEATMAP_DEFAULTS["postfilter"] = {"function": smoother, "params": {"sigma": 5}}

RAINBOW_OPTIONS = {
    "params": {
        "mpl_settings": {"colorbar_fp": TICK_FONT},
        "overlay_opacity": 0.35,
        "overlay_cmap": "gist_rainbow_r",
        "base_cmap": "Greys_r",
    }
}

# dictionary of all procedural looks to be generated. general syntax is:
# '$CATEGORY_NAME': (options_for_look, options_for_other_look, ...)

LOOK_GENERATORS = {
    "accent": [AQUA_PINK_OVERLAY_OPTIONS, RED_BLUE_OVERLAY_OPTIONS],
    "heatmap": [RAINBOW_OPTIONS],
    "stretchy": [INVARIANT_OPTIONS],
    # recolored bandmaps: just give colormap names
    "bandmap": ["viridis"],
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
    "dcs R0R_R0G_R0B",
)
THUMBNAIL_SIZE = (240, 330)
