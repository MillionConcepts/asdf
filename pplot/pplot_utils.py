import re
from itertools import cycle
from pathlib import Path
import pandas as pd
import numpy as np
from matplotlib import pyplot as plt
import matplotlib.font_manager as mplf
from marslab.compat.mertools import (
    MERSPECT_COLOR_MAPPINGS,
    WAVELENGTH_TO_FILTER,
)
import textwrap


# Define the inverse operation to map filter designation to center wavelength
# TODO: This should probably live in marslab.compat.mertools
#  [michael]: this is also the purpose of some components of
#  marslab.compat.xcam.make_xcam_filter_dict() and we should discuss how to
#  share functionality
from marslab.compat.xcam import DERIVED_CAM_DICT
from marslab.imgops.pltutils import despine

f2w = dict((v, [k]) for k, v in WAVELENGTH_TO_FILTER["ZCAM"]["L"].items())
for k, v in WAVELENGTH_TO_FILTER["ZCAM"]["R"].items():
    f2w[v] = [k]
filter_to_wavelength = pd.DataFrame(f2w)


def plot_filter_profiles(ax, datarange, inst="ZCAM"):
    # Underplot the filter profiles
    assert inst in ["ZCAM", "MCAM", "PCAM"]
    p = Path(f"data/{inst.lower()}/filters/")
    for fn in p.glob("*csv"):
        filter_profile = pd.read_csv(fn, header=None)
        if ("R0" in str(fn)) or ("R1" in str(fn)):
            continue
        # The filter responses are on the interval [0,1]. Scale this to the data range.
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


def plot_lab_spectra(ax, minerals=[]):
    # Define the right axis for the lab data labels
    pry = ax.twinx()
    despine(pry)  # remove the bounding box
    pry.set_yticks([])  # wipe auto-ticks or they stick around
    pry.set_ylim(ax.get_ylim())

    # Plot the requested lab spectra
    s = {}
    _ = [s.update(lab_spectra[k]) for k in lab_spectra.keys()]
    ticks, labels = [], []
    for i, m in enumerate(minerals):
        data = pd.read_csv(
            s[m], skiprows=17
        )  # pd.read_csv(s[m],names=['Wavelength','Response'])
        data_inplot = data.loc[data["Wavelength"] >= pry.get_xlim()[0]].loc[
            data["Wavelength"] < pry.get_xlim()[1]
        ]
        ylim = (pry.get_ylim()[0] + 0.1, ax.get_ylim()[1] - 0.1)
        data_scaled = (
            data_inplot["Response"] - np.min(data_inplot["Response"])
        ) * np.diff(ylim) / (
            np.max(data_inplot["Response"]) - np.min(data_inplot["Response"])
        ) + ylim[
            0
        ]
        pry.plot(
            data_inplot["Wavelength"],
            # data_scaled,
            data_inplot["Response"],
            "k",
            alpha=0.7,
            linewidth=2,
        )
        ticks += [data_inplot["Response"].values[-1]]
        labels += [m.replace(" ", "\n")]
    pry.set_yticks(ticks)
    pry.set_yticklabels(labels, fontproperties=legend_fp)


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
    sol="NNN",
    seq_id="Unk. SEQ_ID",
    target_name="Unk. TARGET",
    credit="Credit:NASA/JPL/ASU/MSSS/Cornell/WWU/MC",
    sym=None,
):
    from numbers import Integral
    annotation_parts = []
    if isinstance(sol, (str, Integral)):
        if sol:
            annotation_parts.append(f"Sol{str(sol).zfill(3)}")
    if isinstance(seq_id, str, ):
        if seq_id:
            annotation_parts.append(seq_id)
    if not (target_name.strip().strip("-") == ""):
        annotation_parts.append(target_name)
    annotation_string = " : ".join(annotation_parts)
    assert (
        edge in ["left", "right", "top", "bottom"] for edge in plot_edges
    )  # Tests that the variable has a valid value
    assert underplot in [
        None,
        "filter",
        "grid",
    ]  # Tests that the variable has a valid value
    assert scale_method in [
        "scale_to_left",
        "scale_to_avg",
        None,
    ]  # Tests that the variable has a valid value
    # Remap the colors to feature names; add morphology / soil location when
    # available
    roi_labels = {}
    for row_ix, row in data.iterrows():
        if pd.isnull(row["FEATURE"]) or (row["FEATURE"] == "-"):
            label = row["COLOR"]
        else:
            label = row["FEATURE"]
            if (
                (label == "rock")
                and not pd.isnull(row["MORPHOLOGY"])
                and (row["MORPHOLOGY"] != "-")
            ):
                label += f" ({row['MORPHOLOGY']})"
            elif (
                (label == "soil")
                and not pd.isnull(row["SOIL_LOCATION"])
                and (row["SOIL_LOCATION"] != "-")
            ):
                label += f" ({row['SOIL_LOCATION']})"
        roi_labels[row_ix] = label
    # adding this to slightly increase robustness
    for k in data.keys():
        if (data[k] == "-").all():
            data = data.drop(k, axis=1)
    # path to file containing referenced font
    titillium = Path(
        Path(__file__).parent.parent, "static/fonts/TitilliumWeb-Light.ttf"
    )
    # can also include other face properties, different fonts, etc.
    # TODO: possibly allow these to reference asdf_settings, or expose ability
    #  to pass these fontproperties as a dict
    label_fp = mplf.FontProperties(fname=titillium, size=20.5)
    title_fp = mplf.FontProperties(fname=titillium, size=18)  # TODO: not used
    tick_fp = mplf.FontProperties(fname=titillium, size=15)
    legend_fp = mplf.FontProperties(fname=titillium, size=14)
    tick_minor_fp = mplf.FontProperties(fname=titillium, size=11)
    citation_fp = mplf.FontProperties(fname=titillium, size=12)
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
        y_axis_units = "R* = IOF/cos(" r"$\theta$)"

    # Pre-define the plot extents so that they are easy to reuse
    lpad, rpad = (
        20,
        60,
    )  # Creates a x-axis buffer for graphical layout reasons.
    datadomain = [400 - lpad, 1100 + rpad]
    # To define the y-axis extent, we add a little margin to the actual
    # min/max data values and then round to the nearest tenth. The ylims
    # will always be even tenths.
    available_filters = [
        k for k in data.keys() if k in DERIVED_CAM_DICT["ZCAM"]["filters"]
    ]
    scale = 10 / photometric_scaling
    datarange = [
        np.floor(0.25 * scale * np.nanmin(data[available_filters].values))
        / 10,
        np.ceil(1.05 * scale * np.nanmax(data[available_filters].values)) / 10,
    ]

    fig, ax = plt.subplots(
        figsize=(plot_width, plot_height), facecolor=bgcolor
    )

    # Remove the bounding box
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
    #                  Remove spines _not_ listed in `plot_edges`
    despine(
        prx,
        edges=[
            d
            for d in ["left", "right", "top", "bottom"]
            if d not in plot_edges
        ],
    )
    prx.set_xticks([])  # wipe auto-ticks or they stick around

    left_bayers = [k for k in data.keys() if re.match(r"L0[RGB]$", k)]
    prx.set_xticks(
        (filter_to_wavelength[left_bayers].values[0] - datadomain[0])
        / (datadomain[1] - datadomain[0]),
        minor=True,
    )
    prx.set_xticklabels(
        [f"L0{k[-1]}\nR0{k[-1]}" for k in left_bayers],
        minor=True,
        fontproperties=tick_minor_fp,
    )
    # Set the major ticks of the top axis with the narrowband filters
    # only graph L1 from L1/R1, if it's available
    if "L1" in available_filters:
        narrowband = [
            k for k in available_filters if ("0" not in k) and ("R1" not in k)
        ]
    else:
        narrowband = [k for k in available_filters if ("0" not in k)]
    prx.set_xticks(
        (filter_to_wavelength[narrowband].values[0] - datadomain[0])
        / (datadomain[1] - datadomain[0])
    )
    if ("L1" in available_filters) and ("R1" in available_filters):
        L1_R1_label = "L1\nR1"
    elif "L1" in available_filters:
        L1_R1_label = "L1"
    else:
        L1_R1_label = "R1"
    prx.set_xticklabels(
        [k.replace("L1", L1_R1_label) for k in narrowband],
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
    ytick_pos = np.linspace(
        datarange[0],
        datarange[1],
        int(1 + (datarange[1] - datarange[0]) / 0.1),
    )
    ax.set_yticks(ytick_pos)
    ax.set_yticklabels(
        np.round(ytick_pos, 1),
        fontproperties=tick_fp,
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
        notna_narrowband = [
            f for f in narrowband if np.isfinite(data.iloc[i][f])
        ]
        markersizes = [
            8 if len(k) == 3 else 13 for k in notna_narrowband
        ]  # plot bayers w/ smaller symbols
        ix = np.argsort(filter_to_wavelength[notna_narrowband].values[0])
        # plot the errorbars
        ax.errorbar(
            filter_to_wavelength[notna_narrowband].values[0][ix],
            data.iloc[i][notna_narrowband][ix] / photometric_scaling,
            yerr=data.iloc[i][[f"{f}_STD" for f in notna_narrowband]][ix],
            fmt=f"",
            color=MERSPECT_COLOR_MAPPINGS[data["COLOR"].values[i]],
            alpha=0.5,
            capsize=5,
        )

        # plot the line
        ax.errorbar(
            filter_to_wavelength[notna_narrowband].values[0][ix],
            data.iloc[i][notna_narrowband][ix] / photometric_scaling,
            yerr=data.iloc[i][[f"{f}_STD" for f in notna_narrowband]][ix],
            fmt=f"-",
            color=MERSPECT_COLOR_MAPPINGS[data["COLOR"].values[i]],
            markersize=10,
            alpha=0.5,
            linewidth=3,
        )

        # plot the symbols
        ax.scatter(
            filter_to_wavelength[notna_narrowband].values[0][ix],
            data.iloc[i][notna_narrowband][ix] / photometric_scaling,
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
        borderpad=0.3,
        prop=legend_fp,
        facecolor="white",
        markerscale=0.8,
        handletextpad=0.1,
        handlelength=3,
    )

    # Add an annotation to define the observation
    ax.annotate(
        annotation_string,
        xy=(0, 0),
        xycoords="axes fraction",
        xytext=(5, 5),
        textcoords="offset pixels",
        horizontalalignment="left",
        verticalalignment="bottom",
        fontproperties=metadata_fp,
    )

    # Add the citation string w/ information about scaling
    ax.annotate(
        {
            "scale_to_avg": f"All filters scaled to average at 800nm",
            "scale_to_left": f"Right filter scaled to left at 800nm",
            None: "",
        }[scale_method]
        + "\n"
        + credit,
        xy=(1, 0),
        xycoords="axes fraction",
        xytext=(-5, 5),
        textcoords="offset pixels",
        horizontalalignment="right",
        verticalalignment="bottom",
        fontproperties=citation_fp,
    )

    if plot_fn:

        fig.savefig(plot_fn)
