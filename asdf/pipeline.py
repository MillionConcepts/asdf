"""
inline handling functions for the runtime asdf workflow
"""
import datetime as dt
import warnings
from multiprocessing import Pool
from pathlib import Path

import numpy as np
import pandas as pd
from astropy.io import fits
from cytoolz import keyfilter
from marslab.compat.mertools import (
    add_merspect_colors_to_edgemaps,
    is_sel_file,
    sel_to_roi,
)
from marslab.compat.xcam import (
    make_xcam_filter_dict,
    TREAT_AS_BAYER_OPAQUE,
    NARROWBAND_TO_BAYER,
)
from marslab.imgops import (
    draw_edgemaps_on_image,
    make_thumbnail,
    rgb_from_bayer,
    RGGB_PATTERN,
    normalize_range,
    make_roi_edgemaps,
    depth_stack,
)
from marslab.imgops import rapidlooks_from_pointing, read_from_pointing

import asdf
import asdf.settings as settings
import pplot
from asdf.asdf_utils import absolutely_destroy
from asdf.chatter import ask_user_about_roi
from asdf.scrape import (
    make_pointing_name,
    parse_pointing,
    check_and_drop_duplicate_columns,
    dupe_df_block,
    melt_metadata,
)
from pplot.convert import convert_for_plot


def annotate_and_save_rapidlook(
    target_name, look_name, pointing, figure, pointing_name, output_path
):
    title = "\n".join(
        (
            target_name + look_name,
            make_pointing_annotation(pointing),
            settings.rapidlooks.CREDIT_TEXT,
        )
    )
    figure.axes[0].set_xlabel(
        title, loc="center", fontproperties=settings.rapidlooks.TITLE_FONT
    )
    filename = pointing_name + " " + look_name + ".png"
    print("writing " + filename)
    figure.savefig(Path(output_path, filename), dpi=275)
    absolutely_destroy(figure)
    return 0


def generate_default_rapidlooks(
    pointing, output_path, preloaded_images=None, onboard_debayer=False
):
    pp_dict = settings.rapidlooks.DEFAULT_PREPROCESS_OPTIONS.copy()
    if onboard_debayer is True:
        pp_dict.pop("debayer")
    default_rapidlooks = rapidlooks_from_pointing(
        pointing,
        settings.rapidlooks.DEFAULT_RAPIDLOOKS,
        make_xcam_filter_dict("ZCAM"),
        pp_dict,
        preloaded_images,
    )
    pointing_name, target_name = titular_names(pointing)
    pool = Pool(6)
    for look_name, figure in default_rapidlooks.items():
        pool.apply_async(
            annotate_and_save_rapidlook,
            (
                target_name,
                look_name,
                pointing,
                figure,
                pointing_name,
                output_path,
            ),
        )
    pool.close()
    pool.join()
    return default_rapidlooks


def null_marslab_data_section():
    return pd.DataFrame({"COLOR": "-", "INSTRUMENT": "ZCAM"}, index=[0])


def polish_metadata(dataframe, creation_time):
    dataframe["FILE_TIMESTAMP"] = creation_time
    dataframe = check_and_drop_duplicate_columns(dataframe)
    extra_columns = [
        column
        for column in dataframe.columns
        if column not in settings.metadata.COMPACT_ZCAM_MARSLAB_FIELDS
    ]
    ordered_fields = dataframe.reindex(
        settings.metadata.COMPACT_ZCAM_MARSLAB_FIELDS, axis=1
    )
    return pd.concat([ordered_fields, dataframe[extra_columns]], axis=1)


def assemble_marslab_versions(marslab_data, metadata):
    # TODO: messy.
    metadata_block = dupe_df_block(
        melt_metadata(metadata), len(marslab_data.index)
    )
    marslab_extended = pd.concat([metadata_block, marslab_data], axis=1)
    marslab_compact = marslab_data.copy()
    # match other metadata across the file, using values in the chronologically
    # first image of the pointing (will usually be L0, I think, or R0 if there
    # are no left-eye images in the pointing)
    # this might overwrite fields in some cases but they _should_
    # always be identical -- these are our canonical values for the
    # pointing as a whole
    first_metadata = metadata.sort_values(by="SCLK").iloc[0].copy()
    # summary of full pointing for shared workspaces
    # TODO: this may be redundant with index-on-gsheet-columns
    #  behavior. assess whether we ever want to write local summary
    #  metadata, otherwise cut.
    pointing_summary = first_metadata.reindex(
        settings.metadata.SUMMARY_COLUMNS
    ).copy()
    # write canonical pointing-identifying values into all frames
    for field, value in parse_pointing(first_metadata).items():
        marslab_extended[field] = value
        marslab_compact[field] = value
        pointing_summary[field] = value
    # in the compact file, values that may change across various images in the
    # pointing are simply set equal to the value of the chronologically first
    # image
    for field, value in first_metadata.iteritems():
        if field in settings.metadata.COMPACT_ZCAM_MARSLAB_FIELDS:
            marslab_compact[field] = value
    creation_time = dt.datetime.utcnow().isoformat()
    pointing_summary["FILE_TIMESTAMP"] = creation_time
    pointing_summary["NAME"] = marslab_compact["NAME"]
    marslab_extended["ASDF_VERSION"] = asdf.__version__
    return (
        polish_metadata(marslab_compact, creation_time),
        polish_metadata(marslab_extended, creation_time),
        pointing_summary,
    )


def verbosely_write_marslab_versions(
    marslab_compact, marslab_extended, output_path, pointing_name
):
    metadata_fn = str(Path(output_path, pointing_name + "-marslab.csv"))
    extended_metadata_fn = str(Path(output_path, pointing_name + "-marslab-extended.csv"))
    print(
        "Writing extended-format marslab file: "
        + extended_metadata_fn
    )
    marslab_extended.fillna("-").to_csv(
        extended_metadata_fn,
        index=False,
    )
    print(
        "Writing compact-format marslab file: "
        + metadata_fn
    )
    marslab_compact.fillna("-").to_csv(
        metadata_fn, index=False
    )
    return metadata_fn, extended_metadata_fn


def read_scaled(pointing, filt):
    # need to scale inside the thread b/c pvl dtypes can't be
    # serialized with vanilla pickle (could use pathos instead, of course)
    data = read_from_pointing(pointing, filt, False)
    if "SCALING_FACTOR" not in data.LABEL["IMAGE"].keys():
        # iof_est / EPO-style float32 IOFs based on RAF-type products
        return data.IMAGE
    # leaving the special constant 0 at 0
    image = data.IMAGE.copy().astype(np.float64)
    scale = data.LABEL["IMAGE"]["SCALING_FACTOR"]
    offset = data.LABEL["IMAGE"]["OFFSET"]
    image[image != 0] *= scale
    image[image != 0] += offset
    return image


def preload_zcam_iof_images(pointing):
    """
    asynchronously load iof images. make RGB-named copies of the L0/R0 images
    to ease treating them as separate frames later in the workflow.
    """
    print("Loading images into memory.")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        pool = Pool(6)
        preloaded_images = {}
        for filt in pointing["FILTER"]:
            preloaded_images[filt] = pool.apply_async(
                read_scaled,
                (pointing, filt),
            )
            # preloaded_images[filt] = read_scaled(pointing, filt)
        pool.close()
        pool.join()
        preloaded_images = {
            filt: result.get() for filt, result in preloaded_images.items()
        }
        for eye in ("L", "R"):
            if eye + "0" not in preloaded_images.keys():
                continue
            # case in which the image was debayered onboard
            elif len(preloaded_images[eye + "0"].shape) == 3:
                for color, band_ix in zip(("R", "G", "B"), (0, 1, 2)):
                    preloaded_images[eye + "0" + color] = preloaded_images[
                        eye + "0"
                    ][band_ix, :, :]
            # case in which it wasn't -- copies of the image for us to debayer later
            else:
                for color in ("R", "G", "B"):
                    preloaded_images[eye + "0" + color] = preloaded_images[
                        eye + "0"
                    ].copy()
    return preloaded_images


def handle_pretty_plot(
    marslab_file_name, fixed_target, outpath, pointing_name
):
    print("pretty-plotting data")
    marslab_file = pd.read_csv(marslab_file_name).replace("-", np.nan)
    if fixed_target is not None:
        titular_plot_target = fixed_target
    else:
        targets = marslab_file["NAME"].dropna().unique()
        if len(targets) > 0:
            titular_plot_target = targets[0]
        else:
            titular_plot_target = "unknown target"
    print("Writing " + str(Path(outpath, pointing_name + "-pretty-plot.png")))
    marslab_spectra = convert_for_plot(str(marslab_file_name)).replace(
        "-", np.nan
    )
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        pplot.pplot_utils.pretty_plot(
            marslab_spectra,
            target_name=titular_plot_target,
            sol=marslab_file["SOL"].iloc[0],
            solar_elevation=marslab_file["SOLAR_ELEVATION"].iloc[0],
            seq_id=marslab_file["SEQ_ID"].iloc[0],
            plot_fn=Path(outpath, pointing_name + "-pretty-plot.png"),
            underplot=None,
        )


def create_marslab_output(marslab_data, metadata, outpath, pointing_name):
    (
        marslab_compact,
        marslab_extended,
        pointing_summary,
    ) = assemble_marslab_versions(marslab_data, metadata)
    metadata_fn, extended_metadata_fn = verbosely_write_marslab_versions(
        marslab_compact, marslab_extended, outpath, pointing_name
    )
    return pointing_summary, metadata_fn, extended_metadata_fn


def add_pointing_name_to_roi(pointing_name, roi_fits):
    """just put the pointing name in the roi metadata"""
    for hdu in roi_fits:
        hdu.header["IMAGEREF"] = pointing_name
    return roi_fits


def xlabel_figure(fig, text, fontproperties):
    fig.axes[0].set_xlabel(
        xlabel=text, loc="center", fontproperties=fontproperties
    )


def make_pointing_annotation(pointing):
    return ", ".join(
        [
            key.lower() + " " + str(value)
            for key, value in parse_pointing(pointing).items()
        ]
    )


def convert_roi_file(
    pointing_name,
    roi_path,
    outpath=None,
):
    # if passed ROI file is a SEL, convert to marslab FITS and save
    if is_sel_file(roi_path):
        roi_fits = sel_to_roi(roi_path, "ZCAM")
    else:
        roi_fits = fits.open(roi_path)
    roi_fits = add_pointing_name_to_roi(pointing_name, roi_fits)
    # TODO: should we actually add feature names to the ROI files?
    #  so therefore wait to save until after grilling the user?
    roi_fits.writeto(
        Path(outpath, pointing_name + "-roi.fits"), overwrite=True
    )
    return roi_fits, str(roi_path)


def add_input_roi_metadata(marslab_data, fixed_target, ci):
    for region in marslab_data["COLOR"]:
        ci(print, "Please enter information about the " + region + " ROI.")
        user_provided_roi_metadata = ask_user_about_roi(
            fixed_target, region, ci
        )
        for field, value in user_provided_roi_metadata.items():
            marslab_data.loc[marslab_data["COLOR"] == region, field] = value
    return marslab_data


def titular_names(pointing):
    pointing_name = make_pointing_name(pointing)
    if "NAME" in pointing.keys():
        target_name = pointing["NAME"].iloc[0] + " "
    else:
        target_name = ""
    return pointing_name, target_name


def write_context_image(
    preloaded_images, edgemaps, eye, pointing, outpath, onboard_debayer=False
):
    if eye[0].upper() + "0" in preloaded_images.keys():
        if onboard_debayer is False:
            base_image = rgb_from_bayer(
                preloaded_images[eye[0].upper() + "0"], RGGB_PATTERN
            )
        else:
            base_image = normalize_range(
                preloaded_images[eye[0].upper() + "0"], 0, 1
            )
    else:
        filt, image = list(
            keyfilter(
                lambda key: eye[0].upper() in key, preloaded_images
            ).items()
        )[0]
        if filt in TREAT_AS_BAYER_OPAQUE["ZCAM"]:
            base_image = normalize_range(image)
            base_image = depth_stack((base_image, base_image, base_image))
        else:
            pixel = NARROWBAND_TO_BAYER["ZCAM"][filt]
            base_image = rgb_from_bayer(
                image, RGGB_PATTERN, (pixel, pixel, pixel)
            )
    eye_edgemaps = {
        key: value for key, value in edgemaps.items() if eye in key
    }
    context_image = draw_edgemaps_on_image(base_image, eye_edgemaps, width=0.1)
    pointing_name, target_name = titular_names(pointing)
    title = "\n".join(
        (
            target_name + eye + " ROI context image",
            make_pointing_annotation(pointing),
            settings.rapidlooks.CREDIT_TEXT,
        )
    )
    context_image.axes[0].set_xlabel(
        title, loc="center", fontproperties=settings.rapidlooks.TITLE_FONT
    )
    print(
        "writing "
        + str(Path(outpath, pointing_name + "-context-" + eye + ".png"))
    )
    context_image.savefig(
        Path(outpath, pointing_name + "-context-" + eye + ".png"),
        dpi=240,
    )
    return context_image


def make_rapidlook_thumbnails(rapidlooks, size):
    print("making thumbnails (if necessary).")
    thumbnails = {}
    for name, image in rapidlooks.items():
        thumbnails[name] = make_thumbnail(image, size)
    return thumbnails


def make_context_images(
    roi_fits, preloaded_images, pointing, outpath, onboard_debayer=False
):
    context_images = {}
    print("... making ROI context images ...")
    edgemaps = make_roi_edgemaps(roi_fits, calculate_centers=False)
    edgemaps = add_merspect_colors_to_edgemaps(edgemaps)
    for eye in ("left", "right"):
        eye_image = write_context_image(
            preloaded_images, edgemaps, eye, pointing, outpath, onboard_debayer
        )
        if eye_image:
            context_images["context image " + eye] = eye_image
    return context_images
