"""
script for asdf pipeline
"""
import os
import warnings
from functools import partial
from operator import contains
from pathlib import Path

from cytoolz.curried import keyfilter
from marslab.compat.mertools import merspect_to_marslab

import asdf.settings as settings
from asdf.asdf_utils import catch_interaction, null_marslab_data_section
from asdf.chatter import get_pointing_wrapper, name_prompt, input_roi_metadata
from asdf.network import upload_asdf_analysis
from asdf.pipeline import (
    pretty_plot_bandset,
    make_rapidlook_thumbnails,
    handle_abbreviation,
    make_asdf_outpath,
    collect_dispersed_metadata,
    save_looks,
)
from asdf.zcam_bandset import ZcamBandSet


# NOTE: ignore any complaints from static analyzers about parameter annotations
# for the following function. They are not malformed type hints, but
# instructions to clize to create single-letter aliases for parameters in the
# CLI. (--output, -o; etc.)
def asdf(
    iof,
    roi=None,
    *,
    output: "o" = None,
    upload=False,
    abbreviate: "a" = False,
    skip_rapidlooks: "r" = False,
    suffix: "s" = "",
    merspect: "m" = None,
    noninteractive: "n" = False,
    binocular: "b" = True,
    debug: "d" = False
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
    :param skip_rapidlooks: don't write default rapidlooks
    :param suffix: add suffix for this analysis/group of ROIs to data,
        metadata, and context image outputs (e.g. "rocks" or "soils")
    :param merspect: take data from passed merspect file
    :param noninteractive: run automatically; collect nothing from user
    :param binocular: assume images with distinct RMS can belong to the same
        pointing until proven otherwise
    :param debug: turn debug mode on
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
        pointing = get_pointing_wrapper(
            Path(iof), noninteractive, binocular, debug
        )
    # do we have an roi file? if so, turn passed string into a Path
    roi_path = None
    if roi is not None:
        roi_path = Path(roi)

    # ok? great. initialize BandSet object from these paths
    print("... scraping default metadata ...")
    bandset = ZcamBandSet(
        pointing, roi_path, suffix, threads=settings.process.THREADS
    )
    bandset.metadata["CREATOR"] = os.getlogin()

    # where are we locally writing files? by default, directories separated
    # by user and sol.
    outpath = make_asdf_outpath(output, bandset)

    # dial out to other directories / servers for metadata that can't be
    # found in or derived from file headers
    bandset.metadata = collect_dispersed_metadata(bandset.metadata)

    # do we have any ROIs? maybe not? there are lots of things we don't
    # do if we haven't been passed an ROI file.
    we_do_not_have_rois = (roi_path is None) and (merspect is None)

    # wrapper that suppresses input calls in non-interactive mode
    ci = partial(catch_interaction, noninteractive)

    # ask for observation name
    bandset.metadata["NAME"] = ci(name_prompt)

    # do nothing if we are neither producing rapidlooks nor counting ROIs.
    # otherwise, preload images to share I/O and for convenience.
    # this is wasteful in the case if are images that are used
    # by no rapidlook or ROI (but not very wasteful, and this is rare).
    if (we_do_not_have_rois is False) or (not skip_rapidlooks):
        print("... loading images ...")
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            bandset.load("all")

    # handle ROI file conversion, ROI counting, user input per-ROI metadata

    # did we get a ROI file path? convert it if it's SEL, save to
    # .fits, load it; if it's already FITS, load it
    roi_fits_fn = None
    if we_do_not_have_rois is False:
        # suffix goes on this filename as it is 'analysis' - specific
        roi_fits_fn = bandset.load_rois(
            bandset.name + bandset.suffix, outpath, convert=True
        )
        if merspect is None:
            marslab_data = bandset.count_rois()
            marslab_data["ROI_SOURCE"] = Path(roi_fits_fn).name
        else:
            # allow user to override counting behavior with a MERspect file
            # TODO, maybe: basic check to make sure file matches pointing
            marslab_data = merspect_to_marslab(merspect, write=False)
            marslab_data["ROI_SOURCE"] = "[merspect] " + Path(merspect).name
        assert (
            marslab_data is not None
        ), "something has gone wrong in loading ROI data."
        # prompt users for info on each ROI
        marslab_data = input_roi_metadata(marslab_data, ci)
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
    # TODO: maybe do something fancier with a method on the bandset?  or not.
    pick_thumbs = keyfilter(
        partial(contains, settings.rapidlooks.THUMBNAIL_THESE_RAPIDLOOKS)
    )
    # image-saving closure
    save_images = partial(
        save_looks,
        bandset,
        outpath,
        threads=bandset.threads.get("save"),
        verbose=True,
    )
    # generate rapidlooks
    if not skip_rapidlooks:
        print("... generating rapidlooks ...")
        # suppressing irrelevant warnings from numpy about divides-by-zero
        # and matplotlib about opening a bunch of figures
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            bandset.make_look_set(settings.rapidlooks.DEFAULT_RAPIDLOOKS)
        save_images(prefix=bandset.name)
        # keep images that are to be thumbnailed for upload, discard those
        # that are not; waste not memory, want not memory
        thumbnail_staging |= pick_thumbs(bandset.looks)
        bandset.purge("looks")

    # make context images and write them out
    if bandset.rois:
        bandset.make_context_images()
        save_images(prefix=bandset.name + bandset.suffix)
        thumbnail_staging |= pick_thumbs(bandset.looks)
    bandset.purge()
    # handle metadata and thumbnail uploads
    if upload is True:
        thumbnails = make_rapidlook_thumbnails(
            thumbnail_staging, settings.rapidlooks.THUMBNAIL_SIZE
        )
        upload_asdf_analysis(bandset, thumbnails, roi_fits_fn, debug)

    # pretty-plot data if we've got it; just quit if we don't
    if we_do_not_have_rois:
        print("... all done ...")
        return

    pretty_plot_bandset(bandset, outpath)

    print("... all done ...")
