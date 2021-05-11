"""
script for asdf pipeline
"""
import os
import warnings
from functools import partial
from operator import contains
from pathlib import Path

import pandas as pd
from cytoolz.curried import keyfilter
from marslab.compat.mertools import (
    merspect_to_marslab,
)
from marslab.compat.xcam import (
    count_rois_on_xcam_images,
)

from asdf.asdf_utils import (
    catch_interaction,
    absolutely_destroy,
)
from asdf.chatter import (
    you_prompt,
    get_and_offer_pointing,
    generic_metadata_prompt,
)
from asdf.network import upload_metadata
from asdf.pipeline import (
    preload_zcam_iof_images,
    null_marslab_data_section,
    create_marslab_output,
    generate_default_rapidlooks,
    handle_pretty_plot,
    make_rapidlook_thumbnails,
    make_context_images,
    convert_roi_file,
    add_input_roi_metadata,
    handle_abbreviation,
)
from asdf.scrape import (
    bulk_scrape_metadata,
    make_pointing_name,
    add_public_waypoints_to_metadata,
    add_effective_taus,
    add_derived_illumination_geometry,
)
import asdf.settings as settings


# NOTE: ignore any complaints from static analyzers about parameter annotations
# for the following function. They are not malformed type hints, but
# instructions to clize to create single-letter aliases for parameters in the
# CLI. (--output, -o; --upload, -u; etc.)
def asdf(
    iof,
    roi=None,
    *,
    output: "o" = None,
    upload=False,
    abbreviate: "a" = False,
    copy_target: "c" = False,
    skip_rapidlooks: "r" = False,
    merspect: "m" = None,
    noninteractive: "n" = False,
    binocular: "b" = True,
):
    """
    processes and archives everything

    :param iof: path to one iof file from the 'pointing' you want to archive
    :param roi: path to a SEL or Marslab ROI file containing ROIs corresponding
        to these images
    :param upload: upload metadata to google drive
    :param output: output path; default is "output/$username/$sol"
    :param abbreviate: pass abbreviated version of iof location:
        sol,seq_id,(optional) root directory code,(optional) product type
        examples: 36,03107,scratch,iof
                  36,03107
    :param copy_target: copies 'target' across all ROIs
    :param skip_rapidlooks: don't write default rapidlooks
    :param merspect: take data from passed merspect file
    :param noninteractive: run automatically; collect nothing from user
    :param binocular: assume images with distinct RMS can belong to the same
        pointing until proven otherwise
    """
    # wrapper that suppresses input calls in non-interactive mode
    if abbreviate:
        iof_path = handle_abbreviation(*iof.split(","))
    else:
        iof_path = Path(iof)
    # find all associated files and ask the user about them
    pointing = get_and_offer_pointing(iof_path, noninteractive, binocular)
    pointing_name = make_pointing_name(pointing)

    ci = partial(catch_interaction, noninteractive)
    username = ci(you_prompt)

    if roi is None:
        roi_path = Path("")
    else:
        roi_path = Path(roi)
    if output is None:
        outpath = Path(
            "output/", os.getlogin(), format(pointing["SOL"].iloc[0], "0>4")
        )
    else:
        outpath = Path(output)
    os.makedirs(outpath, exist_ok=True)
    no_rois = (roi_path.name == "") and (merspect is None)
    roi_fits = None
    # scrape headers for all desired metadata fields and derive values
    # from them as necessary
    print("... scraping default metadata ...")
    metadata = pd.DataFrame(bulk_scrape_metadata(pointing["PATH"]))
    metadata = add_derived_illumination_geometry(metadata)

    # dial out to other directories / servers for metadata that can't be
    # found in or derived from the header
    if settings.sources.USE_PUBLIC_WAYPOINTS:
        print(
            "... scraping localization information from public "
            "waypoints file ..."
        )
        metadata = add_public_waypoints_to_metadata(metadata)
    if settings.sources.FIND_EFFECTIVE_TAUS:
        metadata = add_effective_taus(metadata)

    # associate a target name
    if no_rois or (copy_target is True):
        print(
            "Note: Because there are no ROIs or the user has passed "
            "copy_target=True, a single target name will be associated with "
            "all data from this analysis."
        )
        fixed_target = ci(generic_metadata_prompt, "NAME")
        metadata["NAME"] = fixed_target
    else:
        fixed_target = None
    metadata["CREATOR"] = username

    # preload images to share I/O and for convenience...this is wasteful in
    # the case that there are images that are used by no rapidlook or ROI
    if (no_rois is False) or (not skip_rapidlooks):
        preloaded_images = preload_zcam_iof_images(pointing)
    else:
        preloaded_images = None

    if not all(metadata["BAYER"] == "RAW_BAYER"):
        onboard_debayer = True
    else:
        # TODO: watch to see if there are in fact cases when some
        #  but not all frames of a sequence are debayered onboard
        onboard_debayer = False
    # handle ROI file conversion, ROI counting, user input per-ROI metadata
    if roi_path.name != "":
        roi_fits, roi_fn = convert_roi_file(pointing_name, roi_path, outpath)
        if merspect is None:
            marslab_data = count_rois_on_xcam_images(
                roi_fits, preloaded_images, "ZCAM", debayer=not onboard_debayer
            )
        else:
            # allow user to override counting behavior with a MERspect file
            # TODO, maybe: basic check to make sure file matches pointing
            roi_fn = None
            marslab_data = merspect_to_marslab(merspect, write=False)
            metadata["ROI_SOURCE"] = "[merspect] " + merspect
        assert (
            marslab_data is not None
        ), "something has gone wrong in loading ROI data."
        marslab_data = add_input_roi_metadata(marslab_data, fixed_target, ci)
    else:
        print("No ROI file has been passed: using null values for data.")
        marslab_data = null_marslab_data_section()
        roi_fn = None

    # glom all the data and metadata together into our three output formats;
    # write the compact and extended versions, save the summary in memory
    summary, metadata_fn, extended_metadata_fn = create_marslab_output(
        marslab_data, metadata, outpath, pointing_name
    )

    # TODO: this is messy
    if "NAME" in summary.keys():
        pointing["NAME"] = summary["NAME"].iloc[0]

    # set up thumbnail cache
    thumbnail_staging = {}
    pick_thumbs = keyfilter(
        partial(contains, settings.rapidlooks.THUMBNAIL_THESE_RAPIDLOOKS)
    )

    # generate rapidlooks
    if not skip_rapidlooks:
        print("... generating rapidlooks ...")
        # suppressing irrelevant warnings from numpy about divides-by-zero
        # and matplotlib about opening a bunch of figures
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            looks = generate_default_rapidlooks(
                pointing, outpath, preloaded_images, onboard_debayer
            )
        # keep images that are to be thumbnailed for upload, discard those
        # that are not; waste not memory, want not memory
        thumbnail_staging |= pick_thumbs(looks)
        absolutely_destroy(looks)

    # make context images and write them out
    if roi_fits is not None:
        context = make_context_images(
            roi_fits, preloaded_images, pointing, outpath, onboard_debayer
        )
        thumbnail_staging |= pick_thumbs(context)
        absolutely_destroy(context)

    # handle metadata and thumbnail uploads
    if upload is True:
        thumbnails = make_rapidlook_thumbnails(
            thumbnail_staging, settings.rapidlooks.THUMBNAIL_SIZE
        )
        upload_metadata(
            summary,
            thumbnails,
            pointing_name,
            metadata_fn,
            extended_metadata_fn,
            roi_fn,
        )
    del thumbnail_staging

    # pretty-plot data if we've got it; just quit if we don't
    if no_rois:
        print("... all done ...")
        return
    handle_pretty_plot(
        Path(outpath, pointing_name + "-marslab.csv"),
        fixed_target,
        outpath,
        pointing_name,
    )
    print("... all done ...")
