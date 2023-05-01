import re
import textwrap
from functools import partial
from itertools import cycle
from numbers import Integral
from pathlib import Path

import matplotlib.font_manager as mplf
import numpy as np
import pandas as pd
from matplotlib import pyplot as plt

from asdf_settings import rapidlooks
from marslab.compat.mertools import (
    MERSPECT_COLOR_MAPPINGS, WAVELENGTH_TO_FILTER,
)
from marslab.compat.xcam import DERIVED_CAM_DICT
from marslab.imgops.pltutils import despine

f2w = dict((v, [k]) for k, v in WAVELENGTH_TO_FILTER["ZCAM"]["L"].items())
for k, v in WAVELENGTH_TO_FILTER["ZCAM"]["R"].items():
    f2w[v] = [k]
filter_to_wavelength = pd.DataFrame(f2w)

EDGES = ("left", "right", "top", "bottom")


def plot_filter_profiles(ax, datarange, inst="ZCAM"):
    # Underplot the filter profiles
    assert inst in ["ZCAM", "MCAM", "PCAM"]
    p = Path(f"data/{inst.lower()}/filters/")
    for fn in p.glob("*csv"):
        filter_profile = pd.read_csv(fn, header=None)
        if ("R0" in str(fn)) or ("R1" in str(fn)):
            continue
        # The filter responses are on the interval [0,1]. Scale this to the
        # data range.
        scaled_response = (
            filter_profile[1].values * datarange[1] / filter_profile[1].max()
        )
        ix = np.where(
            scaled_response > 0.002
        )  # don't plot effectively zero response
        ax.plot(
            filter_profile[0].values[ix],
            scaled_response[ix],
            f'k{":" if ("L0" in str(fn)) else "--"}',
            alpha=0.07 if ("L0" in str(fn)) else 0.08,
        )


def find_longest_filter(data):
    waves = DERIVED_CAM_DICT["ZCAM"]["filters"]
    extant_waves = [
        (filt, waves.get(filt))
        for filt in data.columns
        if waves.get(filt) is not None
    ]
    max_wave = max([wave[1] for wave in extant_waves])
    return next(
        iter([wave[0] for wave in extant_waves if wave[1] == max_wave])
    )


def pretty_plot(
    data,
    scale_method="scale_to_avg",
    plot_fn=None,
    solar_elevation=None,
    units=None,
    plot_width=15,
    plot_height=12,
    bgcolor="white",
    plot_edges=("left", "bottom"),
    underplot="filter",
    sym=None,
):
    # for files where we've replaced nulls with '-' to make people feel better
    data = data.replace("-", None)
    # for many circumstances
    data = data.replace("", None)
    # make sure call kwargs have valid values
    try:
        assert (edge in EDGES for edge in plot_edges)
        assert underplot in [None, "filter", "grid"]
        assert scale_method in ["scale_to_left", "scale_to_avg", None]
    except AssertionError:
        raise TypeError("invalid argument")
    # set up the legend: use FEATURE + FEATURE_SUBTYPE when possible,
    # FEATURE when not, COLOR as a last resort
    roi_labels = {}
    for row_ix, row in data.iterrows():
        if "FEATURE" not in row.keys() or pd.isnull(row["FEATURE"]):
            label = row["COLOR"]
        else:
            label = row["FEATURE"]
            if not pd.isnull(row["FEATURE_SUBTYPE"]):
                label += f" ({row['FEATURE_SUBTYPE']})"
        roi_labels[row_ix] = label
    # adding this to slightly increase robustness
    data = data.drop(columns=data.columns[data.isna().all()])
    # path to file containing referenced font
    titillium = Path(
        Path(__file__).parent.parent, "static/fonts/TitilliumWeb-Light.ttf"
    )
    # can also include other face properties, different fonts, etc.
    label_fp = mplf.FontProperties(fname=titillium, size=26)
    tick_fp = mplf.FontProperties(fname=titillium, size=23)
    legend_fp = mplf.FontProperties(fname=titillium, size=23)
    tick_minor_fp = mplf.FontProperties(fname=titillium, size=12)
    metadata_fp = mplf.FontProperties(fname=titillium, size=22)

    # TODO: Handle the case where solar_elevation is not the same for all of
    #  the spectra in the input marslab file, e.g. a file composited across
    #  observations. Can fix the existence check and make sure solar_elevation
    #  is an np.array but that will create an interface hassle...
    theta_rad = (
        (90 - solar_elevation) * 2 * np.pi / 360
        if solar_elevation is not None
        else 2 * np.pi
    )
    if units is None:
        photometric_scaling = np.cos(theta_rad)
    else:
        photometric_scaling = 1

    if units is None and solar_elevation is None:
        y_axis_units = "IOF"
    else:
        y_axis_units = "Relative Reflectance"

    # Pre-define the plot extents so that they are easy to reuse
    lpad, rpad = (20, 60)
    # add a x-axis buffer for graphical layout reasons.
    datadomain = [400 - lpad, 1100 + rpad]
    # To define the y-axis extent, we add a little margin to the actual
    # min/max data values and then round to the nearest tenth. The ylims
    # will always be even tenths.
    available_bands = [
        k for k in data.keys() if k in DERIVED_CAM_DICT["ZCAM"]["filters"]
    ]
    scale = 1 / photometric_scaling
    max_sig = [data[f] + data[f"{f}_STD"] for f in available_bands]
    min_sig = [data[f] - data[f"{f}_STD"] for f in available_bands]
    datarange = [
        0.85 * scale * np.nanmin(min_sig),
        1.05 * scale * np.nanmax(max_sig),
    ]

    # create the matplotlib figure we will render the plot in
    fig, ax = plt.subplots(
        figsize=(plot_width, plot_height), facecolor=bgcolor
    )
    # Remove the bounding box and fix the domain
    despine(ax)
    ax.set_xlim(datadomain)
    # Set the ticks for the bottom axis
    xtick_pos = np.linspace(datadomain[0] + lpad, datadomain[1] - rpad, 8)
    ax.set_xticks(xtick_pos)
    ax.set_xticklabels(
        xtick_pos.astype(np.int16).tolist(), fontproperties=tick_fp
    )
    ax.set_xlabel("wavelength (nm)", fontproperties=label_fp)
    # Set the minor ticks of the top axis with the bayer filters
    prx = ax.twiny()
    # Remove spines _not_ listed in `plot_edges`
    despine(prx, edges=list(set(EDGES).difference(set(plot_edges))))
    left_bayers = [k for k in data.columns if re.match(r"L0[RGB]$", k)]
    prx_ticks = []
    for filt in left_bayers:
        position = (
            (f2w[filt][0] - datadomain[0]) / (datadomain[1] - datadomain[0])
        )
        if filt.endswith("G"):
            position *= 1.04
        prx_ticks.append(position)
    prx.set_xticks(prx_ticks, minor=True)
    prx.set_xticklabels(
        [f"L0{k[-1]}\nR0{k[-1]}" for k in left_bayers],
        minor=True,
        fontproperties=tick_minor_fp,
    )
    # Set the major ticks of the top axis with the narrowband filters
    # only graph L1 from L1/R1, if it's available
    if "L1" in available_bands:
        narrow = [
            k for k in available_bands if ("0" not in k) and ("R1" not in k)
        ]
    else:
        narrow = [k for k in available_bands if ("0" not in k)]
    prx.set_xticks(
        (filter_to_wavelength[narrow].values[0] - datadomain[0])
        / (datadomain[1] - datadomain[0])
    )
    if ("L1" in available_bands) and ("R1" in available_bands):
        L1_R1_label = "L1\nR1"
    elif "L1" in available_bands:
        L1_R1_label = "L1"
    else:
        L1_R1_label = "R1"
    prx.set_xticklabels(
        [k.replace("L1", L1_R1_label) for k in narrow],
        fontproperties=tick_fp,
    )

    if underplot == "filter":
        plot_filter_profiles(ax, datarange)
    elif underplot == "grid":
        ax.grid(axis="y", alpha=0.2)
        ax.grid(axis="x", alpha=0.2)

    ax.set_ylim(datarange)
    ax.set_ylabel(y_axis_units, fontproperties=label_fp)

    # Set the ticks for the left yaxis
    tenths = np.arange(0, 11, dtype='u1')
    ytick_pos = tenths[
        (tenths <= np.floor(datarange[1] * 10))
        & (tenths >= np.ceil(datarange[0] * 10))
    ]
    ax.set_yticks(ytick_pos / 10)
    ax.set_yticklabels(
        [str(round(t, 1)) for t in ytick_pos / 10], fontproperties=tick_fp,
    )
    ax.tick_params(length=6)

    # Plot the requested lab spectra - dev functionality
    # plot_lab_spectra(ax,minerals=["Pyrrhotite","Magnetite","Ferrosilite"])

    # Plot the observational data
    if sym is None:
        sym = cycle(
            ["s", "o", "D", "p", "^", "v", "P", "X", "*", "d", "H", "8", "h"]
        )
    else:
        sym = iter(sym)
    for i in range(len(data.index)):
        symbol = next(sym)
        # Plot narrowband filters as connected
        notna_narrow = [f for f in narrow if np.isfinite(data.iloc[i][f])]
        markersizes = [
            8 if len(k) == 3 else 13 for k in notna_narrow
        ]  # plot bayers w/ smaller symbols
        ix = np.argsort(filter_to_wavelength[notna_narrow].values[0])
        # plot the errorbars
        ax.errorbar(
            filter_to_wavelength[notna_narrow].values[0][ix],
            data.iloc[i][notna_narrow][ix] / photometric_scaling,
            yerr=data.iloc[i][[f"{f}_STD" for f in notna_narrow]][ix],
            fmt=f"",
            color=MERSPECT_COLOR_MAPPINGS[data["COLOR"].values[i]],
            alpha=0.5,
            capsize=5,
        )

        # plot the line
        ax.errorbar(
            filter_to_wavelength[notna_narrow].values[0][ix],
            data.iloc[i][notna_narrow][ix] / photometric_scaling,
            yerr=data.iloc[i][[f"{f}_STD" for f in notna_narrow]][ix],
            fmt=f"-",
            color=MERSPECT_COLOR_MAPPINGS[data["COLOR"].values[i]],
            markersize=10,
            alpha=0.5,
            linewidth=3,
        )

        # plot the symbols
        ax.scatter(
            filter_to_wavelength[notna_narrow].values[0][ix],
            data.iloc[i][notna_narrow][ix] / photometric_scaling,
            marker=f"{symbol}",
            color=MERSPECT_COLOR_MAPPINGS[data["COLOR"].values[i]],
            edgecolors="k",
            # scatter takes units of pixel**2
            s=np.array(markersizes)[ix] ** 2,
            alpha=0.5,
            label=(
                "\n".join(
                    textwrap.wrap(
                        roi_labels[i],
                        width=20,
                        break_long_words=False,
                    )
                )
            ),
        )

        # Plot bayer separately as smaller markers, w/ left eye filled and
        #  right as outlines
        # TODO: add black outlines to the bayer filters
        for bayer in ["L0R", "L0G", "L0B", "R0R", "R0G", "R0B"]:
            try:
                ax.errorbar(
                    filter_to_wavelength[bayer].values[0],
                    data.iloc[i][bayer] / photometric_scaling,
                    yerr=data.iloc[i][[f"{bayer}_STD"]],
                    fmt=f"{symbol}",
                    color=MERSPECT_COLOR_MAPPINGS[data["COLOR"].values[i]],
                    capsize=5,
                    fillstyle="none" if bayer.startswith("R") else "full",
                    markersize=8,
                    alpha=0.3,
                )
            except KeyError:
                continue  # Missing information for this filter
    ax.set_zorder(1)  # adjust the rendering order of twin axes
    ax.set_frame_on(False)  # make it transparent

    # Reorder according to the longest wavelength filter with data.
    max_filter = find_longest_filter(data)
    handles, labels = ax.get_legend_handles_labels()
    ax.legend(
        np.array(handles)[np.argsort(data[max_filter].values)].tolist()[::-1],
        np.array(labels)[np.argsort(data[max_filter].values)].tolist()[::-1],
        loc=2,
        bbox_to_anchor=[
            (1038 - datadomain[0])
            / (datadomain[1] - datadomain[0]),  # left edge goes at 1038nm
            0.99,
        ],
        labelspacing=0.3,
        borderpad=0.1,
        prop=legend_fp,
        facecolor="white",
        markerscale=0.8,
        handletextpad=0,
        handlelength=3,
    )
    titleprint = partial(
        fig.axes[0].text,
        horizontalalignment="left",
        verticalalignment="center",
        transform=fig.axes[0].transAxes,
        fontproperties=metadata_fp
    )
    # titleprint(s=make_pplot_annotation(data), x=0.458, y=-0.132)
    titleprint(s=make_pplot_annotation(data), x=-0.088, y=-0.1182)

    # titleprint(s=rapidlooks.CREDIT_TEXT, x=0.348, y=-0.177)
    titleprint(
        s=rapidlooks.CREDIT_TEXT.replace("Credit:", ""), x=-0.088, y=-0.1520
    )

    if plot_fn:
        fig.savefig(plot_fn, bbox_inches="tight")


def make_pplot_annotation(data):
    line = data.to_dict('records')[0]
    annotation = ""
    if 'NAME' in line.keys():
        annotation += f'{line["NAME"]}, '
    if 'SOL' in line.keys():
        annotation += f'sol {line["SOL"]}, '
    if 'SEQ_ID' in line.keys():
        annotation += f'zcam{line["SEQ_ID"][4:]}, '
    if 'RSM' in line.keys():
        annotation += f'rsm {line["RSM"]}'
    return annotation
