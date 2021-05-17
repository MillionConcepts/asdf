from copy import deepcopy

import cv2
import matplotlib.font_manager as mplf
import numpy as np
from cytoolz.functoolz import curry
from matplotlib import cm
from matplotlib.colors import ListedColormap
from scipy.ndimage import gaussian_filter



# TODO: clean this up
from marslab.imgops.imgutils import std_clip, normalize_range, split_filter
from marslab.imgops.render import colormapped_plot, simple_mpl_figure


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
    return ListedColormap(vals)


def make_aqua_pink_accent():
    aqua = (0, 1, 1, 1)
    pink = (1, 0, 1, 1)
    transparent = (0.5, 0.5, 0.5, 0)
    vals = np.full((10, 4), transparent)
    for channel in range(3):
        vals[:, channel][0] = aqua[channel]
        vals[:, channel][-1] = pink[channel]
    return ListedColormap(vals)


TITLE_FONT = mplf.FontProperties(
    fname="static/fonts/TitilliumWeb-Light.ttf", size=10
)
TICK_FONT = mplf.FontProperties(
    fname="static/fonts/TitilliumWeb-Light.ttf", size=6
)
ROI_FONT = mplf.FontProperties(
    fname="static/fonts/TitilliumWeb-Light.ttf", size=5
)


SPECTRAL_DEFAULTS = {
    "params": {"special_constants": [0]},
    "limiter": {"function": std_clip},
    "postfilter": {"function": gaussian_filter, "params": {"sigma": 2}},
    "plotter": {
        "function": colormapped_plot,
        "params": {
            "cmap": make_orange_teal_cmap(),
            "colorbar_fp": TICK_FONT,
            "render_colorbar": True,
        },
    },
}

STRETCHY_DEFAULTS = {
    "params": {"special_constants": [0], "contrast_stretch": 1},
    "plotter": {"function": simple_mpl_figure},
}
ENHANCED_DEFAULTS = {
    "look": "composite",
    "prefilter": {
        "function": normalize_range,
        "params": {"cheat_low": 1.5, "cheat_high": 1},
    },
    "params": {"special_constants": [0], "normalize": False},
    "plotter": {"function": simple_mpl_figure},
}

TRUE_DEFAULTS = {
    "look": "composite",
    "params": {"special_constants": [0], "normalize": (0, 1, 0.1, 0.1)},
    "plotter": {"function": simple_mpl_figure},
}


# noinspection PyTypeChecker
DEFAULT_RAPIDLOOKS = {
    "BD529": SPECTRAL_DEFAULTS
    | {
        "look": "band_depth",
        "bands": ("L6", "L4", "L5"),
    },
    "BD866": SPECTRAL_DEFAULTS
    | {
        "look": "band_depth",
        "bands": ("R1", "R4", "R2"),
    },
    "BD678": SPECTRAL_DEFAULTS
    | {
        "look": "band_depth",
        "bands": ("L4", "L2", "L3"),
    },
    "S56": SPECTRAL_DEFAULTS
    | {
        "look": "slope",
        "bands": ("R5", "R6"),
    },
    "S16": SPECTRAL_DEFAULTS
    | {
        "look": "slope",
        "bands": ("R1", "R6"),
    },
    "enhanced color": ENHANCED_DEFAULTS
    | {"name": "enhanced color", "bands": ("L2", "L5", "L6")},
    "L0 enhanced color": ENHANCED_DEFAULTS
    | {"name": "enhanced color", "bands": ("L0R", "L0G", "L0B")},
    "R0 enhanced color": ENHANCED_DEFAULTS
    | {"name": "enhanced color", "bands": ("R0R", "R0G", "R0B")},
    "L0 true color": TRUE_DEFAULTS
    | {
        "name": "true color",
        "bands": ("L0R", "L0G", "L0B"),
    },
    "R0 true color": TRUE_DEFAULTS
    | {
        "name": "true color",
        "bands": ("R0R", "R0G", "R0B"),
    },
    "dcs": STRETCHY_DEFAULTS
    | {"look": "dcs", "name": "dcs", "bands": ("L2", "L5", "L6")},
    "R0 dcs": STRETCHY_DEFAULTS
    | {"look": "dcs", "name": "dcs", "bands": ("R0R", "R0G", "R0B")},
    "L0 dcs": STRETCHY_DEFAULTS
    | {"look": "dcs", "name": "dcs", "bands": ("L0R", "L0G", "L0B")},
    "IR dcs": STRETCHY_DEFAULTS
    | {"look": "dcs", "name": "dcs", "bands": ("R6", "R3", "R1")},
}

# ###########################################################3
# section to procedurally generate additional looks
# ######################################################

GENERATED_LOOKS = {}

normed_dcs_looks = {}
for look_name, look in DEFAULT_RAPIDLOOKS.items():
    if look["look"] != "dcs":
        continue
    if "R6" in look["bands"]:
        continue
    normed_look = deepcopy(look)
    normed_look["name"] = "normed " + look["name"]
    # noinspection PyTypeChecker
    normed_look["prefilter"] = {
        "function": normalize_range,
        "params": {"cheat_low": 1, "cheat_high": 1},
    }
    normed_dcs_looks["normed " + look_name] = normed_look
GENERATED_LOOKS |= normed_dcs_looks

sigma_dcs_looks = {}
for look_name, look in DEFAULT_RAPIDLOOKS.items():
    if look["look"] != "dcs":
        continue
    if "R6" in look["bands"]:
        continue
    sigma_look = deepcopy(look)
    sigma_look["name"] = "fixed sigma " + look_name
    sigma_look["params"] = {
        "special_constants": [0],
        "contrast_stretch": 1,
        "sigma": 0.95,
    }
    sigma_dcs_looks["fixed sigma " + look_name] = sigma_look
GENERATED_LOOKS |= sigma_dcs_looks


# smooth_dcs_looks = {}
# smoother = make_multi_channel_filter(curry(gaussian_filter))
# # we're applying these to the procgen dcs also
# for look_name, look in (DEFAULT_RAPIDLOOKS | GENERATED_LOOKS).items():
#     if look["look"] != "dcs":
#         continue
#     smooth_look = deepcopy(look)
#     smooth_look["name"] = "smoothed " + look["name"]
#     # noinspection PyTypeChecker
#     smooth_look["postfilter"] = {
#         "function": smoother, "params": {"sigma": 0.8}
#     }
#     smooth_dcs_looks["smoothed " + look["name"]] = smooth_look
# GENERATED_LOOKS |= smooth_dcs_looks


cubehelix_looks = {}
for look_name, look in DEFAULT_RAPIDLOOKS.items():
    if look["look"] not in ("band_depth", "ratio", "slope"):
        continue
    cubehelix_look = deepcopy(look)
    cubehelix_look["name"] = look["look"] + " cubehelix"
    # noinspection PyTypeChecker
    cubehelix_look["plotter"]["params"]["cmap"] = "cubehelix"
    cubehelix_looks[look_name + " cubehelix"] = cubehelix_look
GENERATED_LOOKS |= cubehelix_looks


# cv2.bilateralFilter is a weird exception to gradual partial evaluation we
# use later in the pipeline -- it has some over-the-hood overload resolution
# that breaks it. so we bind arguments to it here in a closure.


def make_bilateralfilter(d, sigmaColor, sigmaSpace):
    def do_bilateralfilter(array):
        return cv2.bilateralFilter(
            array, d=d, sigmaColor=sigmaColor, sigmaSpace=sigmaSpace
        )

    return do_bilateralfilter


ACCENT_DEFAULTS = deepcopy(SPECTRAL_DEFAULTS)
ACCENT_DEFAULTS["prefilter"] = {"function": make_bilateralfilter(15, 3, 7)}

AQUA_PINK_OVERLAY_DEFAULTS = {
    "params": {
        "mpl_settings": {"colorbar_fp": TICK_FONT},
        "overlay_opacity": 0.3,
        "overlay_cmap": make_aqua_pink_accent(),
        "base_cmap": cm.get_cmap("Greys_r"),
    },
}

accent_looks = {}
for look_name, look in DEFAULT_RAPIDLOOKS.items():
    if look["look"] not in ("band_depth", "ratio", "slope"):
        continue
    new_look = deepcopy(look)
    new_look["name"] = look["look"] + " accent"
    new_look |= ACCENT_DEFAULTS
    # noinspection PyTypeChecker
    new_look["overlay"] = AQUA_PINK_OVERLAY_DEFAULTS | {
        "band": look["bands"][0]
    }
    accent_looks[look_name + " accent"] = new_look
GENERATED_LOOKS |= accent_looks

HEATMAP_DEFAULTS = deepcopy(SPECTRAL_DEFAULTS)
HEATMAP_DEFAULTS["prefilter"] = {
    # "function": make_bilateralfilter(20, 5, 10),
    "function": make_bilateralfilter(10, 10, 10),
}
smoother = split_filter(curry(gaussian_filter), axis=0)

HEATMAP_DEFAULTS["postfilter"] = {
    "function": smoother, "params": {"sigma": 5}
}

RAINBOW_OVERLAY_DEFAULTS = {
    "params": {
        "mpl_settings": {"colorbar_fp": TICK_FONT},
        "overlay_opacity": 0.35,
        "overlay_cmap": "gist_rainbow",
        "base_cmap": "Greys_r",
    }
}
rainbow_looks = {}
for look_name, look in DEFAULT_RAPIDLOOKS.items():
    if look["look"] not in ("band_depth", "ratio", "slope"):
        continue
    new_look = deepcopy(look)
    new_look["name"] = look["look"] + " heatmap"
    new_look |= HEATMAP_DEFAULTS
    # noinspection PyTypeChecker
    new_look["overlay"] = RAINBOW_OVERLAY_DEFAULTS | {"band": look["bands"][0]}
    rainbow_looks[look_name + " heatmap"] = new_look
GENERATED_LOOKS |= rainbow_looks


DEFAULT_RAPIDLOOKS |= GENERATED_LOOKS


# add crop
# TODO: is it gross to do it this way?

DEFAULT_CROP = {
    "crop": (25, 25, 11, 11),
}

for look in DEFAULT_RAPIDLOOKS:
    DEFAULT_RAPIDLOOKS[look] |= DEFAULT_CROP


CREDIT_TEXT = "Credit:NASA/JPL/ASU/MSSS/Cornell/WWU/MC"

THUMBNAIL_THESE_RAPIDLOOKS = (
    "enhanced color L2_L5_L6",
    "dcs L2_L5_L6",
    "enhanced color R0R_R0G_R0B",
    "context image left",
    "context image right",
    "dcs R0R_R0G_R0B",
)
THUMBNAIL_SIZE = (240, 330)
