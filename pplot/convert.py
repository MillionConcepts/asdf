# Functions for the conversion of data and metadata formats
# TODO: we should decide how and if to conglomerate this with stuff in
#  marslab.compat -- michael

import pandas as pd
import numpy as np


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
        marslab_data = pd.read_csv(fn, index_col=None, na_values="-")
        data = pd.concat([data, marslab_data], ignore_index=True)
    data = scale_eyes(data, method=scale_method)
    data.replace(np.nan, "-", inplace=True)
    return data
