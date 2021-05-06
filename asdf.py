"""
user-facing wrapper script and helper functions for asdf pipeline
"""
import warnings
from functools import partial
from operator import contains
from pathlib import Path

import pandas as pd
from astropy.io import fits
from clize import run
from cytoolz.curried import keyfilter
from marslab.compat.mertools import (
    sel_to_roi,
    is_sel_file,
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
    ask_user_about_roi,
)
from asdf.network import upload_metadata
from asdf.pipeline import (
    preload_zcam_iof_images,
    add_pointing_name_to_roi,
    null_marslab_data_section,
    create_marslab_output,
    generate_default_rapidlooks,
    handle_pretty_plot,
    make_rapidlook_thumbnails,
    make_context_images,
)
from asdf.scrape import (
    bulk_scrape_metadata,
    make_pointing_name,
    add_public_waypoints_to_metadata,
    add_effective_taus,
    add_derived_illumination_geometry,
)
from asdf.settings.rapidlooks import (
    THUMBNAIL_THESE_RAPIDLOOKS,
    THUMBNAIL_SIZE,
)
from asdf.settings.sources import (
    USE_PUBLIC_WAYPOINTS,
    FIND_EFFECTIVE_TAUS,
)


def asdf(
    iof: str,
    roi: str = "",
    output: str = "",
    *,
    copy_target: bool = False,
    skip_rapidlooks: bool = False,
    upload: bool = False,
    merspect: str = None,
    noninteractive: bool = False,
    binocular=True
):
    """
    processes and archives everything

    :param iof: path to one iof file from the 'pointing' you want to archive
    :param roi: path to a SEL or Marslab ROI file containing ROIs corresponding
        to these images
    :param output: output path; default is the parent directory of the ROI
        file, or working directory if no ROI file
    :param copy_target: copies 'target' across all ROIs
    :param skip_rapidlooks: don't write default rapidlooks
    :param upload: upload metadata to google drive
    :param merspect: take data from passed merspect file
    :param noninteractive: run automatically; collect nothing from user
    :param binocular: assume images with distinct RMS can belong to the same
        pointing until proven otherwise
    """
    # wrapper that suppresses input calls in non-interactive mode
    ci = partial(catch_interaction, noninteractive)
    username = ci(you_prompt)
    iof_path = Path(iof)
    # find all associated files and ask the user about them
    pointing = get_and_offer_pointing(iof_path, noninteractive, binocular)
    pointing_name = make_pointing_name(pointing)
    roi_path = Path(roi)
    if output != "":
        outpath = Path(output)
    else:
        outpath = Path(".")
    no_rois = (roi_path.name == "") and (merspect is None)
    roi_fits = None
    print("... scraping default metadata ...")
    # note: this is a bit inefficient because we're skimming every file twice,
    # although we're probably talking about an extra 50ms max barring some
    # weird networked filesystem situation
    metadata = pd.DataFrame(bulk_scrape_metadata(pointing["PATH"]))
    metadata = add_derived_illumination_geometry(metadata)
    metadata["CREATOR"] = username
    if USE_PUBLIC_WAYPOINTS:
        print(
            "... scraping localization information from public "
            "waypoints file ..."
        )
        metadata = add_public_waypoints_to_metadata(metadata)
    if FIND_EFFECTIVE_TAUS:
        metadata = add_effective_taus(metadata)
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
    if (no_rois is False) or (not skip_rapidlooks):
        # preload images to share I/O and for convenience...this is a little
        # wasteful in the specific case that there's some images that are
        # involved in no rapidlook or ROI
        preloaded_images = preload_zcam_iof_images(pointing)
    else:
        preloaded_images = None
    if not no_rois:
        # TODO: break this into a handler in asdf.pipeline
        marslab_data = None
        if merspect is not None:
            # allow user to override counting behavior with a MERspect file
            # TODO, maybe: basic check to make sure file matches pointing
            marslab_data = merspect_to_marslab(merspect, write=False)
            metadata["ROI_SOURCE"] = "[merspect] " + merspect
        if roi_path.name != "":
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
            metadata["ROI_SOURCE"] = roi_path.name
            if merspect is None:
                marslab_data = count_rois_on_xcam_images(
                    roi_fits, preloaded_images, "ZCAM"
                )
        assert (
            marslab_data is not None
        ), "something has gone wrong in loading ROI data."
        for region in marslab_data["COLOR"]:
            if not noninteractive:
                print("Please enter information about the " + region + " ROI.")
            user_provided_roi_metadata = ask_user_about_roi(
                fixed_target, region, ci
            )
            for field, value in user_provided_roi_metadata.items():
                marslab_data.loc[
                    marslab_data["COLOR"] == region, field
                ] = value
    else:
        print("No ROI file has been passed: using null values for data.")
        marslab_data = null_marslab_data_section()
    summary = create_marslab_output(
        marslab_data, metadata, outpath, pointing_name
    )
    if "NAME" in summary.keys():
        pointing["NAME"] = summary["NAME"].iloc[0]

    thumbnail_staging = {}
    pick_thumbs = keyfilter(partial(contains, THUMBNAIL_THESE_RAPIDLOOKS))
    if not skip_rapidlooks:
        print("... generating rapidlooks ...")
        # suppressing irrelevant warnings from numpy about divides-by-zero
        # and matplotlib about opening a bunch of figures
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            looks = generate_default_rapidlooks(
                pointing, outpath, preloaded_images
            )
        # keep images that are to be thumbnailed for upload, discard those
        # that are not; waste not memory, want not memory
        thumbnail_staging |= pick_thumbs(looks)
        absolutely_destroy(looks)

    if roi_fits is not None:
        # make context images; write them out; stick them in the generated
        # images dictionary for thumbnailing in the next step
        context = make_context_images(
            roi_fits, preloaded_images, pointing, outpath
        )
        thumbnail_staging |= pick_thumbs(context)
        absolutely_destroy(context)
    if upload is True:
        thumbnails = make_rapidlook_thumbnails(
            thumbnail_staging, THUMBNAIL_THESE_RAPIDLOOKS, THUMBNAIL_SIZE
        )
        upload_metadata(summary, thumbnails, pointing_name)
    del thumbnail_staging
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


if __name__ == "__main__":
    run(asdf)

