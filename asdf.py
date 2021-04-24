"""
user-facing wrapper script and helper functions for asdf pipeline
"""
from pathlib import Path
from typing import Optional

import PIL
import numpy as np
import pandas as pd
from astropy.io import fits
from clize import run, UserError

from asdf.scrape import (
    find_iof_siblings,
    bulk_scrape_metadata,
    make_pointing_name,
)
from asdf.structure import DEFAULT_SPECTRAL_RAPIDLOOKS
from marslab.compat.mertools import sel_to_roi, is_sel_file
from marslab.compat.xcam import make_xcam_filter_dict
from marslab.imgops import pixel_counts_from_rois, rapidlooks_from_pointing
from marslab.marslab_utils import mockup


def make_output_path(output, roi_path):
    if output != "":
        output_path = Path(output)
    else:
        if roi_path.name != "":
            output_path = roi_path.parent
        else:
            output_path = Path(".")
    return output_path


def assemble_marslab_data_section(pointing_df, roi_fits):
    rows = []
    for ix, iof in pointing_df.iterrows():
        row = {}
        counts = mockup(pixel_counts_from_rois)(iof["PATH"], roi_fits)
        row[iof["FILTER"]] = counts["MEAN"]
        row[iof["FILTER"] + "_ERR"] = counts["err"]
        row["COLOR"] = counts["NAME"]
        rows.append(row)
    return pd.DataFrame(rows)


def add_pointing_name_to_roi(pointing_name, roi_fits):
    """just put the pointing name in the roi metadata"""
    for hdu in roi_fits:
        hdu.header['IMAGEREF'] = pointing_name
    return roi_fits

# TODO, maybe: we could add verification to each input step that could be
#  disabled with a switch


def get_and_offer_pointing(iof_path):
    try:
        pointing = pd.DataFrame(find_iof_siblings(iof_path)).sort_values(
            by="filter"
        )
    except (ValueError, FileNotFoundError) as err:
        raise UserError(err)
    print("Found the following IOFs associated with this pointing:")
    for filt, path in zip(pointing["filter"], pointing["path"]):
        print(filt, "    ", Path(path).name)
    ok_input = False
    while ok_input is not True:
        ok_input = input("Does this look right? (Y/N) ")
        if ok_input.lower() == "n":
            raise UserError("halting due to user rejection of file list")
        elif ok_input.lower() == "y":
            ok_input = True
    return pointing


def generic_metadata_prompt(field_name) -> str:
    """extremely generic metadata input with no error checking or anything"""
    return input(
        "Please enter the name of the {} associated with this image "
        "sequence or ROI. (press Enter to skip)".format(field_name.lower())
    )


def float_prompt() -> str:
    value = ""
    while value.upper() not in ("Y", "N"):
        value = input("is the feature associated with this ROI a float? (Y/N)")
    return value.upper()


def dispatched_metadata_prompt(field_name: str) -> str:
    """
    ask user for the value of a metadata field. calls specific functions as
    necessary to provide sensical and grammatically correct prompts
    """
    if field_name.lower() == "float":
        return float_prompt()
    # etc., etc., etc.
    return generic_metadata_prompt(field_name)


def ask_user_about_roi(fixed_target=None) -> dict:
    roi_metadata = {}
    metadata_fields = ["FLOAT", "FEATURE", "FORMATION", "MEMBER"]
    if fixed_target is None:
        metadata_fields.append("TARGET")
    else:
        roi_metadata["TARGET"] = fixed_target
    for field in metadata_fields:
        roi_metadata[field] = dispatched_metadata_prompt(field)
    return roi_metadata


def generate_default_rapidlooks(pointing, output_path):
    default_rapidlooks = rapidlooks_from_pointing(
        pointing,
        [look["spectop"] for look in DEFAULT_SPECTRAL_RAPIDLOOKS.values()],
        [look["filters"] for look in DEFAULT_SPECTRAL_RAPIDLOOKS.values()],
        make_xcam_filter_dict("ZCAM"),
        "ZCAM",
        special_constants=(0, 32767)
    )
    pointing_name = make_pointing_name(pointing)
    for look_name, image in default_rapidlooks.items():
        filename = pointing_name + "_" + look_name + ".png"
        print("writing " + filename)
        PIL.Image.fromarray(image.astype(np.uint8)).save(
            Path(output_path, filename)
        )


def asdf(
        iof: str,
        roi: Optional[str] = "",
        output: Optional[str] = "",
        copy_target: Optional[bool] = False,
):
    """
    processes and archives everything

    :param iof: path to one iof file from the 'pointing' you want to archive
    :param roi: path to a SEL or Marslab ROI file containing ROIs corresponding
        to these images
    :param output: output path; default is the parent directory of the ROI
        file, or working directory if no ROI file
    :param copy_target: copies 'target' across all ROIs
    """
    iof_path = Path(iof)
    pointing = get_and_offer_pointing(iof_path)
    pointing_name = make_pointing_name(pointing)
    roi_path = Path(roi)
    output_path = make_output_path(output, roi_path)
    print("generating rapidlooks")
    generate_default_rapidlooks(pointing, output_path)
    print("scraping default metadata")
    # note: this is a bit inefficient because we're skimming every file twice,
    # although we're probably talking about an extra 50ms max barring some
    # weird networked filesystem situation
    metadata = pd.DataFrame(bulk_scrape_metadata(pointing["PATH"]))
    # TODO: fields we can't get out of the label or user:
    #  illumination geometry (phase, incidence, emission)
    #  ODOMETRY
    #  TARGET_ELEVATION, ROVER_ELEVATION
    #  LAT, LON
    #  FOCAL_DISTANCE
    #  TAU

    if (roi_path.name == "") or (copy_target is True):
        print(
            "Because there are no ROIs or the user has passed "
            "copy_target=True, a single target name will be associated with "
            "all data from this analysis."
        )
        fixed_target = generic_metadata_prompt("TARGET")
        metadata["TARGET"] = fixed_target
    else:
        fixed_target = None
    if roi_path.name == "":
        print("No ROI file has been passed: saving metadata and exiting.")
        metadata.to_csv(str(output_path) + pointing_name + ".csv", index=False)
        print("Done.")
        return None
    # if passed ROI file is a SEL file, convert to marslab roi FITS and save
    if is_sel_file(roi_path):
        roi_fits = sel_to_roi(roi_path, "ZCAM")
        roi_fits.writeto(output_path, roi_path.stem + "_roi.fits")
    else:
        roi_fits = fits.open(roi_path)
    marslab_data = assemble_marslab_data_section(pointing, roi_fits)
    roi_fits = add_pointing_name_to_roi(pointing_name, roi_fits)
    for region in roi_fits:
        # each region is an HDU. for marslab ROI files generated from MERSpect
        # .sel files, the NAME value will be the MERSpect color name.
        name = region.header["NAME"]
        print("Please enter information about the " + name + " ROI.")
        user_provided_roi_metadata = ask_user_about_roi(fixed_target)
        for field, value in user_provided_roi_metadata.items():
            marslab_data.loc[marslab_data["COLOR"] == name, field] = value
    # match other metadata across the file, using values in the chronologically
    # first image of the pointing (will usually be L0, I think)
    first_metadata = metadata.sort_values(by="SCLK").iloc[0]
    for field, value in first_metadata.iteritems():
        if field in (
                "SITE",
                "DRIVE",
                "L_S",
                "SCLK",
                "SOLAR_ELEVATION",
                "SEQ_ID",
                "SOL",
                "LTST",
        ):
            marslab_data[field] = value
    print("Writing metadata.")
    metadata.to_csv(str(output_path) + pointing_name + ".csv", index=False)
    print("Writing marslab file.")
    marslab_data.to_csv(str(output_path) + pointing_name + "-marslab.csv",
                        index=False)
    print("Done.")


if __name__ == "__main__":
    run(asdf)
