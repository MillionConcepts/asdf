# Functions for the conversion of data and metadata formats
# TODO: we should decide how and if to conglomerate this with stuff in
#  marslab.compat -- michael

import pandas as pd
import numpy as np
from marslab.compat.xcam import WAVELENGTH_TO_FILTER


def scale_eyes(data, method="scale_to_avg"):
    # Accepts a "marslab format" spectra file pandas DataFrame
    # This translation is done _in place_... which is maybe bad...
    #    but will be fine as long as you always restart + rerun
    # TODO: Remove duplicate functionality with marslab.compat.xcam
    if np.isnan(data["L1"].values).any() or np.isnan(data["R1"].values).any():
        # shared filters don't exist
        return data
    if method == "scale_to_left":
        # Scale the Right eye data to the Left eye at 800nm
        for i in range(len(data.index)):
            scale_factor = data.iloc[i]["L1"] / data.iloc[i]["R1"]
            for k in data.keys():
                if (
                    ("R" in k)
                    and (not "STD" in k)
                    and (not "L0" in k)
                    and (not "RMS" in k)
                    and len(k) <= 3
                ):
                    # Scale R to L in place
                    data.iloc[i][k] = data.iloc[i][k] * scale_factor
    elif method == "scale_to_avg":
        for i in range(len(data.index)):
            left_scale = data.iloc[i][["L1", "R1"]].mean() / data.iloc[i]["L1"]
            right_scale = (
                data.iloc[i][["L1", "R1"]].mean() / data.iloc[i]["R1"]
            )
            for k in data.keys():
                if (
                    ("R" in k)
                    and ("STD" not in k)
                    and ("L0" not in k)
                    and ("RSM" not in k)
                    and ("SOL" not in k)
                    and len(k) <= 3
                ):
                    # Scale R to L in place
                    # data.iloc[i][k] = data.iloc[i][k] * right_scale # bad
                    data.loc[i, k] = data.iloc[i][k] * right_scale
                elif (
                    ("L" in k)
                    and ("STD" not in k)
                    and ("R0" not in k)
                    and ("RSM" not in k)
                    and ("SOL" not in k)
                    and len(k) <= 3
                ):
                    # data.iloc[i][k] = data.iloc[i][k] * left_scale # bad
                    data.loc[i, k] = data.iloc[i][k] * left_scale
    return data


def merspect_to_marslab(
    spectra_fn,  # a MERspect exported spectra file, unmodified
    instrument="ZCAM",  # valid options are ZCAM, MCAM
    color_to_feature={},  # a mapping between color names and feature names
):
    csv = pd.read_csv(spectra_fn)
    if not "# Wavelength (nm)" in csv.keys():
        raise IOError("This seems to not be a MERspect formatted file.")
    csv.rename(columns={"# Wavelength (nm)": "Wavelength"}, inplace=True)
    [csv.rename(columns={k: k.strip()}, inplace=True) for k in csv.keys()]
    # We want the columns in order of ascending wavelength, regardless of instrument
    # Columns that don't have corresponding data will just be given values of NaN
    columns = {  # Some of these parameters are only meaningful to WWU Marslab
        "MCAM": [
            "SOL",
            "SEQ_ID",
            "INSTRUMENT",
            "COLOR",
            "FEATURE",
            "FORMATION",
            "MEMBER",
            "FLOAT",
            "L2",
            "L2_ERR",
            "R2",
            "R2_ERR",
            "L0B",
            "L0B_ERR",
            "R0B",
            "R0B_ERR",
            "L1",
            "L1_ERR",
            "R1",
            "R1_ERR",
            "R0G",
            "R0G_ERR",
            "L0G",
            "L0G_ERR",
            "R0R",
            "R0R_ERR",
            "L0R",
            "L0R_ERR",
            "L4",
            "L4_ERR",
            "L3",
            "L3_ERR",
            "R3",
            "R3_ERR",
            "L5",
            "L5_ERR",
            "R4",
            "R4_ERR",
            "R5",
            "R5_ERR",
            "L6",
            "L6_ERR",
            "R6",
            "R6_ERR",
        ],  # Some of these parameters are only meaningful to WWU Marslab
        "ZCAM": [
            "SOL",
            "SEQ_ID",
            "INSTRUMENT",
            "COLOR",
            "FEATURE",
            "FORMATION",
            "MEMBER",
            "FLOAT",
            "L6",
            "L6_ERR",
            "L0B",
            "L0B_ERR",
            "R0B",
            "R0B_ERR",
            "L5",
            "L5_ERR",
            "L0G",
            "L0G_ERR",
            "R0G",
            "R0G_ERR",
            "L4",
            "L4_ERR",
            "L0R",
            "L0R_ERR",
            "R0R",
            "R0R_ERR",
            "L3",
            "L3_ERR",
            "L2",
            "L2_ERR",
            "L1",
            "L1_ERR",
            "R1",
            "R1_ERR",
            "R2",
            "R2_ERR",
            "R3",
            "R3_ERR",
            "R4",
            "R4_ERR",
            "R5",
            "R5_ERR",
            "R6",
            "R6_ERR",
        ],
    }[instrument]
    data = pd.DataFrame(columns=columns)

    # Generate the index column --- 'COLOR'
    colors = [
        " ".join(k.split(" ")[:-2])
        for k in csv.keys()
        if k.endswith("Mean Value")
    ]
    data["COLOR"] = colors
    data = data.set_index("COLOR")

    for color in colors:
        this_color = csv[
            [
                "Eye",
                "Wavelength",
                f"{color} Mean Value",
                f"{color} Standard Deviation",
            ]
        ]
        for i in range(len(this_color)):
            eye = this_color.loc[i]["Eye"].strip()[0]
            wavelength = int(this_color.loc[i]["Wavelength"])
            filt = WAVELENGTH_TO_FILTER["ZCAM"][eye][wavelength]
            data[f"{filt}"].loc[color] = this_color.loc[i][
                f"{color} Mean Value"
            ]
            data[f"{filt}_STD"].loc[color] = this_color.loc[i][
                f"{color} Standard Deviation"
            ]
        # Add in the feature names, if given
        if color in color_to_feature.keys():
            data["FEATURE"].loc[color] = color_to_feature[color]

    data.reset_index(inplace=True)
    data = data[columns]
    return data


def convert_for_plot(
    spectra_fn,
    instrument="ZCAM",
    color_to_feature={},
    scale_method="scale_to_avg",
):
    if spectra_fn.__class__ == str:
        spectra_fn = [spectra_fn]
    data = pd.DataFrame()
    for fn in spectra_fn:
        try:
            # First try to convert MERspect to Marslab format
            marslab_data = merspect_to_marslab(
                fn,
                instrument=instrument,
                color_to_feature=color_to_feature,
            )
        except IOError:
            marslab_data = pd.read_csv(fn, index_col=None, na_values="-")
        data = data.append(marslab_data, ignore_index=True)
    data = scale_eyes(data, method=scale_method)
    data.replace(np.nan, "-", inplace=True)
    return data
