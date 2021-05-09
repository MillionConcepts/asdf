import cv2
import numpy as np
from matplotlib.colors import ListedColormap
from matplotlib import cm
import matplotlib.font_manager as mplf
from scipy.ndimage import gaussian_filter

from marslab.compat.xcam import (
    NARROWBAND_TO_BAYER,
    TREAT_AS_BAYER_OPAQUE,
)
from marslab.imgops import RGGB_PATTERN, norm_clip, normalize_range


def cast_bilateral(array, *args, **kwargs):
    # downsample float64 images for bilateralFilter
    if array.dtype == np.float64:
        return cv2.bilateralFilter(array.astype(np.float32), *args, **kwargs)
    return cv2.bilateralFilter(array, *args, **kwargs)


# TODO: clean this up
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
    vals = np.full((7, 4), transparent)
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


SPECTRAL_RAPIDLOOK_OPTIONS = {
    "special_constants": [0],
    "clip": {"function": norm_clip},
    "image_filter": {"function": gaussian_filter, "params": {"sigma": 2}},
    "mpl_options": {"cmap": make_orange_teal_cmap(), "tick_fp": TICK_FONT},
}
SMEAR_SPECTRAL_RAPIDLOOK_OPTIONS = {
    "special_constants": [0],
    "clip": {"function": norm_clip},
    "prefilter": {"function": gaussian_filter, "params": {"sigma": 3}},
    "mpl_options": {"cmap": make_orange_teal_cmap(), "tick_fp": TICK_FONT},
}

WINTER_SPECTRAL_RAPIDLOOK_OPTIONS = {
    "special_constants": [0],
    "clip": {"function": norm_clip},
    "image_filter": {"function": gaussian_filter, "params": {"sigma": 2}},
    "mpl_options": {"cmap": cm.get_cmap("winter"), "tick_fp": TICK_FONT},
}

ENHANCED_RAPIDLOOK_OPTIONS = {
    "special_constants": [0],
    "normalize": (0, 1, 1, 1),
    "render_mpl": True,
}

STRETCHY_RAPIDLOOK_OPTIONS = {
    "special_constants": [0],
    "contrast_stretch": 1,
    "render_mpl": True,
}

OVERLAY_RAPIDLOOK_OPTIONS = {
    "special_constants": [0],
    "clip": {"function": norm_clip},
    "prefilter": {
        "function": cast_bilateral,
        "params": {"d": 20, "sigmaColor": 5, "sigmaSpace": 10},
    },
}

ACCENT_RAPIDLOOK_OPTIONS = {
    "special_constants": [0],
    "clip": {"function": norm_clip},
    "prefilter": {
        "function": cast_bilateral,
        "params": {"d": 15, "sigmaColor": 3, "sigmaSpace": 7},
    },
}

AQUA_PINK_ACCENT_OPTIONS = {
    "options": {
        "mpl_options": {"tick_fp": TICK_FONT},
        "overlay_opacity": 0.3,
        "overlay_cmap": make_aqua_pink_accent(),
        "base_cmap": cm.get_cmap("Greys_r"),
    }
}


DEFAULT_PREPROCESS_OPTIONS = {
    "crop_bounds": (25, 25, 11, 11),
    "debayer": {
        "pattern": RGGB_PATTERN,
        "mapping": NARROWBAND_TO_BAYER["ZCAM"],
        "eschew_filters": TREAT_AS_BAYER_OPAQUE["ZCAM"],
    },
}

# noinspection PyTypeChecker
DEFAULT_RAPIDLOOKS = {
    "BD529": {
        "operation": "band_depth",
        "filters": ("L6", "L4", "L5"),
        "options": SPECTRAL_RAPIDLOOK_OPTIONS,
    },
    "BD866": {
        "operation": "band_depth",
        "filters": ("R1", "R4", "R2"),
        "options": SPECTRAL_RAPIDLOOK_OPTIONS,
    },
    "BD678": {
        "operation": "band_depth",
        "filters": ("L4", "L2", "L3"),
        "options": SPECTRAL_RAPIDLOOK_OPTIONS,
    },
    "S56": {
        "operation": "slope",
        "filters": ("R5", "R6"),
        "options": SPECTRAL_RAPIDLOOK_OPTIONS,
    },
    "S16": {
        "operation": "slope",
        "filters": ("R1", "R6"),
        "options": SPECTRAL_RAPIDLOOK_OPTIONS,
    },
    "enhanced color": {
        "operation": "enhanced color",
        "filters": ("L2", "L5", "L6"),
        "options": {
            "special_constants": [0],
            "normalize": False,
            "render_mpl": True,
            "prefilter": {
                "function": normalize_range,
                "params": {"cheat_low": 2, "cheat_high": 1},
            },
        },
    },
    "L0 enhanced color": {
        "operation": "enhanced color",
        "filters": ("L0R", "L0G", "L0B"),
        "options": {
            "special_constants": [0],
            "normalize": False,
            "render_mpl": True,
            "prefilter": {
                "function": normalize_range,
                "params": {"cheat_low": 1, "cheat_high": 1},
            },
        },
    },
    "R0 enhanced color": {
        "operation": "enhanced color",
        "filters": ("R0R", "R0G", "R0B"),
        "options": {
            "special_constants": [0],
            "normalize": False,
            "render_mpl": True,
            "prefilter": {
                "function": normalize_range,
                "params": {"cheat_low": 1, "cheat_high": 1},
            },
        },
    },
    "dcs": {
        "operation": "dcs",
        "filters": ("L2", "L5", "L6"),
        "options": STRETCHY_RAPIDLOOK_OPTIONS,
    },
    "R0 dcs": {
        "operation": "dcs",
        "filters": ("R0R", "R0G", "R0B"),
        "options": STRETCHY_RAPIDLOOK_OPTIONS,
    },
    "L0 dcs": {
        "operation": "dcs",
        "filters": ("L0R", "L0G", "L0B"),
        "options": STRETCHY_RAPIDLOOK_OPTIONS,
    },
    "3dg_dcs": {
        "operation": "dcs",
        "name": "3dg dcs",
        "filters": ("L2", "L5", "L6"),
        "options": STRETCHY_RAPIDLOOK_OPTIONS
        | {
            "image_filter": {
                "function": gaussian_filter,
                "params": {"sigma": 1},
            }
        },
    },
    "IR_dcs": {
        "operation": "dcs",
        "name": "IR dcs",
        "filters": ("R6", "R3", "R1"),
        "options": STRETCHY_RAPIDLOOK_OPTIONS | {"contrast_stretch": 2},
    },
    "3dg_IR_dcs": {
        "operation": "dcs",
        "name": "3dg IR dcs",
        "filters": ("R6", "R3", "R1"),
        "options": STRETCHY_RAPIDLOOK_OPTIONS
        | {
            "contrast_stretch": 2,
            "image_filter": {
                "function": gaussian_filter,
                "params": {"sigma": 1},
            },
        },
    },
}
CREDIT_TEXT = "Credit:NASA/JPL/ASU/MSSS/Cornell/WWU/MC"

# noinspection PyTypeChecker

THUMBNAIL_THESE_RAPIDLOOKS = (
    "enhanced color L2_L5_L6",
    "dcs L2_L5_L6",
    "enhanced color R0R_R0G_R0B",
    "context image left",
    "context image right",
    "dcs R0R_R0G_R0B",
)
THUMBNAIL_SIZE = (240, 330)

winter_looks = {}
for look_name, look in DEFAULT_RAPIDLOOKS.items():
    if look["options"] == SPECTRAL_RAPIDLOOK_OPTIONS:
        winter_look = look.copy()
        winter_look["name"] = look["operation"] + " winter"
        winter_look["options"] = WINTER_SPECTRAL_RAPIDLOOK_OPTIONS
        winter_looks[look_name + " winter"] = winter_look
DEFAULT_RAPIDLOOKS |= winter_looks


overlay_looks = {}
for look_name, look in DEFAULT_RAPIDLOOKS.items():
    if look["options"] == SPECTRAL_RAPIDLOOK_OPTIONS:
        new_look = look.copy()
        new_look["name"] = look["operation"] + " accent"
        new_look["options"] = ACCENT_RAPIDLOOK_OPTIONS
        eye = look["filters"][0][0]
        # noinspection PyTypeChecker
        new_look["overlay"] = AQUA_PINK_ACCENT_OPTIONS | {"filter": eye + "0R"}
        overlay_looks[look_name + " overlay"] = new_look
DEFAULT_RAPIDLOOKS |= overlay_looks

RAINBOW_OVERLAY_OPTIONS = {
    "options": {
        "mpl_options": {"tick_fp": TICK_FONT},
        "overlay_opacity": 0.25,
        "overlay_cmap": cm.get_cmap("jet"),
        "base_cmap": cm.get_cmap("Greys_r"),
    }
}

rainbow_overlay_looks = {}
for look_name, look in DEFAULT_RAPIDLOOKS.items():
    if look["options"] == SPECTRAL_RAPIDLOOK_OPTIONS:
        new_look = look.copy()
        new_look["name"] = look["operation"] + " rainbow overlay"
        new_look["options"] = OVERLAY_RAPIDLOOK_OPTIONS
        eye = look["filters"][0][0]
        # noinspection PyTypeChecker
        new_look["overlay"] = RAINBOW_OVERLAY_OPTIONS | {"filter": eye + "0R"}
        rainbow_overlay_looks[look_name + " rainbow overlay"] = new_look
DEFAULT_RAPIDLOOKS |= rainbow_overlay_looks


# TODO: troubleshoot make_three_channel_filter
# smooth_dcs_looks = {}
# for look_name, look in DEFAULT_RAPIDLOOKS.items():
#     if look["options"] == STRETCHY_RAPIDLOOK_OPTIONS:
#         new_look = look.copy()
#         new_look["name"] = look["operation"] + " smooth"
#         new_look["options"]["image_filter"] = {
#                     "function": make_three_channel_filter(gaussian_filter),
#                     "params": {"sigma": 1},
#                 }
#         smooth_dcs_looks[look_name + " smooth"] = new_look
# DEFAULT_RAPIDLOOKS |= smooth_dcs_looks
