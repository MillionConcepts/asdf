"""
script for asdf pipeline
"""
import os
import warnings
from functools import partial
from operator import contains
from pathlib import Path

from cytoolz.curried import keyfilter

import asdf.settings as settings
from asdf.asdf_utils import (
    catch_interaction,
    absolutely_destroy, null_marslab_data_section,
)
from asdf.chatter import (
    get_and_offer_pointing,
    generic_metadata_prompt,
)
from asdf.network import upload_metadata
from asdf.pipeline import (
    handle_pretty_plot,
    make_rapidlook_thumbnails,
    make_context_images,
    add_input_roi_metadata,
    handle_abbreviation, make_asdf_outpath, collect_dispersed_metadata,
)
from asdf.settings.rapidlooks import DEFAULT_RAPIDLOOKS
from asdf.zcam_bandset import ZcamBandSet
from marslab.compat.mertools import (
    merspect_to_marslab,
)


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
    suffix: "s" = "",
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
    :param suffix: add suffix for this analysis/group of ROIs to data,
        metadata, and context image outputs (e.g. "rocks" or "soils")
    :param merspect: take data from passed merspect file
    :param noninteractive: run automatically; collect nothing from user
    :param binocular: assume images with distinct RMS can belong to the same
        pointing until proven otherwise
    """
    # find all associated files and ask the user about them
    # TODO: it would be possible to set this up to import gradually
    #  in order to speed time-to-execute, and, in particular, not use
    #  pandas for this first step, for more buttery initial execution.
    #  this may not be worth it.
    if abbreviate:
        pointing = handle_abbreviation(
            *iof.split(","), noninteractive=noninteractive, binocular=binocular
        )
    else:
        pointing = get_and_offer_pointing(Path(iof), noninteractive, binocular)
    # where is the roi file?
    if roi is None:
        roi_path = Path("")
    else:
        roi_path = Path(roi)

    # ok? great. initialize BandSet object from these paths
    print("... scraping default metadata ...")
    bandset = ZcamBandSet(pointing, roi_path)
    bandset.metadata['CREATOR'] = os.getlogin()

    # where are we locally writing files? by default, directories separated
    # by user and sol.
    outpath = make_asdf_outpath(output, bandset)

    # dial out to other directories / servers for metadata that can't be
    # found in or derived from file headers
    bandset.metadata = collect_dispersed_metadata(bandset.metadata)

    # do we have any ROIs? maybe not? there are lots of things we don't
    # do if we haven't been passed an ROI file.
    we_do_not_have_rois = (roi_path.name == "") and (merspect is None)

    # wrapper that suppresses input calls in non-interactive mode
    ci = partial(catch_interaction, noninteractive)

    # ask for a target name if we have a single name for the whole pointing
    if we_do_not_have_rois or (copy_target is True):
        print(
            "Note: Because there are no ROIs or the user has passed "
            "--copy-target / -c, a single target name will be associated with "
            "all data from this analysis."
        )
        fixed_target = ci(generic_metadata_prompt, "NAME")
        bandset.metadata["NAME"] = fixed_target
    else:
        fixed_target = None

    # do nothing if we are neither producing rapidlooks nor counting ROIs.
    # otherwise, preload images to share I/O and for convenience.
    # this is wasteful in the case if are images that are used
    # by no rapidlook or ROI (but not very wasteful, and this is rare).
    if (we_do_not_have_rois is False) or (not skip_rapidlooks):
        bandset.load('all')

    # handle ROI file conversion, ROI counting, user input per-ROI metadata

    # did we get a ROI file path? convert it if it's SEL, save to
    # .fits, load it; if it's already FITS, load it
    roi_fits_fn = None
    if bandset.rois:
        # suffix goes on this filename as it is 'analysis' - specific
        roi_fits_fn = bandset.load_rois(
            bandset.name + bandset.suffix, outpath, convert=True
        )
        if merspect is None:
            marslab_data = bandset.count_rois()
            marslab_data["ROI_SOURCE"] = roi_fits_fn
        else:
            # allow user to override counting behavior with a MERspect file
            # TODO, maybe: basic check to make sure file matches pointing
            marslab_data = merspect_to_marslab(merspect, write=False)
            marslab_data["ROI_SOURCE"] = "[merspect] " + merspect
        assert (
            marslab_data is not None
        ), "something has gone wrong in loading ROI data."
        marslab_data = add_input_roi_metadata(marslab_data, fixed_target, ci)
    else:
        print("No ROI file has been passed: using null values for data.")
        marslab_data = null_marslab_data_section()
    bandset.counts = marslab_data
    # glom all the data and metadata together into our three output formats;
    bandset.format_metadata()
    # write the compact and extended versions, save the summary in memory
    bandset.write_data_files(outpath, verbose=True)
    # set up thumbnail cache
    thumbnail_staging = {}
    # TODO: maybe do something fancier with a method on the bandset?
    #   or not.
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
            bandset.make_look_set(DEFAULT_RAPIDLOOKS)
        # keep images that are to be thumbnailed for upload, discard those
        # that are not; waste not memory, want not memory
        thumbnail_staging |= pick_thumbs(bandset.looks)
        absolutely_destroy(bandset.looks)
        bandset.looks = {}

    # make context images and write them out
    if bandset.rois:
        bandset.make_context_images()

    if roi_fits is not None:
        context = make_context_images(
            roi_fits,
            preloaded_images,
            pointing,
            outpath,
            onboard_debayer,
            suffix,
        )
        thumbnail_staging |= pick_thumbs(bandset.looks)
        absolutely_destroy(bandset.looks)
        bandset.looks = {}

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
        metadata_fn, fixed_target, outpath, pointing_name, suffix
    )
    print("... all done ...")
