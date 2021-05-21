"""
high-level handling script for asdf cli workflow
"""
import os
import warnings
from functools import partial
from operator import contains
from pathlib import Path

from cytoolz.curried import keyfilter
import matplotlib as mpl
from marslab.compat.mertools import merspect_to_marslab
from rich.rule import Rule

import asdf.settings as settings
from asdf.asdf_utils import catch_interaction, null_marslab_data_section
from asdf.chatter import wrapped_obs_get, name_prompt, input_roi_metadata
from asdf.console import ASDF_CONSOLE, ASDF_PROGRESS, ASDF_RPH
from asdf.network import upload_asdf_analysis
from asdf.cli_handlers import (
    pretty_plot_bandset,
    make_rapidlook_thumbnails,
    handle_abbreviation,
    make_asdf_outpath,
    collect_dispersed_metadata,
    save_looks,
)
from asdf.zcam_bandset import ZcamBandSet


def asdf_body(
    observation,
    roi_path=None,
    upload=False,
    output=None,
    skip_rapidlooks=False,
    suffix="",
    merspect=None,
    noninteractive=False,
    debug=False,
    console=None,
):
    """
    body component of the asdf command line function -- can be called multiple
    times from asdf_hello in some cases.
    """
    # do we have an roi file? if so, turn passed string into a Path
    if roi_path:
        roi_path = Path(roi_path)
    else:
        roi_path = None
    # ok? great. initialize BandSet object from these paths
    console.print(Rule(" gathering metadata "))
    console.print("... scraping file headers ...")
    bandset = ZcamBandSet(
        observation, roi_path, suffix, threads=settings.process.THREADS
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
    console.print(Rule(" loading images "))
    if (we_do_not_have_rois is False) or (not skip_rapidlooks):
        with console.status("", spinner="star"):
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                bandset.load("all")
    mpl.use("agg")
    # handle ROI file conversion, ROI counting, user input per-ROI metadata

    # did we get a ROI file path? convert it if it's SEL, save to
    # .fits, load it; if it's already FITS, load it
    roi_fits_fn = None
    if we_do_not_have_rois is False:
        console.print(Rule(" gathering ROI data "))
        # suffix goes on this filename as it is 'analysis' - specific
        roi_fits_fn = bandset.load_rois(
            bandset.name + bandset.suffix, outpath, convert=True
        )
        if merspect is None:
            console.print("... counting ROIs ...")
            marslab_data = bandset.count_rois()
            marslab_data["ROI_SOURCE"] = Path(roi_fits_fn).name
        else:
            # allow user to override counting behavior with a MERspect file
            # TODO, maybe: basic check to make sure file matches pointing
            marslab_data = merspect_to_marslab(merspect, write=False)
            marslab_data["ROI_SOURCE"] = "[merspect] " + Path(merspect).name
        if marslab_data is None:
            console.print(
                "something has gone wrong in loading ROI data, bailing out.",
                style="red bold",
            )
        # prompt users for info on each ROI
        marslab_data = input_roi_metadata(marslab_data, ci)
    else:
        console.print(
            "No ROI file passed; using null values for data.",
            style="dark_orange"
        )
        marslab_data = null_marslab_data_section()
    console.print(Rule(" writing data files "))
    bandset.counts = marslab_data
    # glom all the data and metadata together into our three output formats;
    bandset.format_metadata()
    # write the compact and extended versions, save the summary in memory
    bandset.write_data_files(outpath, verbose=True)
    # set up thumbnail cache
    thumbnail_staging = {}
    # TODO: maybe do something fancier with a method on the bandset?  or not.
    pick_thumbs = keyfilter(
        partial(contains, settings.rapidlooks.THUMBNAIL_THESE)
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
        console.print(Rule(" generating rapidlooks "))
        with ASDF_PROGRESS as prog:
            ASDF_RPH.task_id = prog.add_task(
                "",
                total=len(settings.rapidlooks.DEFAULT_RAPIDLOOKS),
            )
            # suppressing irrelevant warnings from numpy about divides-by-zero
            # and matplotlib about opening a bunch of figures
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                bandset.make_look_set(settings.rapidlooks.DEFAULT_RAPIDLOOKS)
            prog.remove_task(ASDF_RPH.task_id)

        console.print(Rule(" saving rapidlooks "))
        with ASDF_PROGRESS as prog:
            ASDF_RPH.task_id = prog.add_task(
                "",
                total=len(settings.rapidlooks.DEFAULT_RAPIDLOOKS),
            )
            save_images(prefix=bandset.name)
            prog.remove_task(ASDF_RPH.task_id)
        # keep images that are to be thumbnailed for upload, discard those
        # that are not; waste not memory, want not memory
        thumbnail_staging |= pick_thumbs(bandset.looks)
        bandset.purge("looks")

    # make context images and write them out
    if bandset.rois:
        ASDF_CONSOLE.print(Rule(" making ROI context images "))
        save_images = partial(save_images, threads=None)
        bandset.make_context_images(verbose=True)
        save_images(prefix=bandset.name + bandset.suffix)
        thumbnail_staging |= pick_thumbs(bandset.looks)
    bandset.purge()

    # handle metadata and thumbnail uploads
    if upload is True:
        ASDF_CONSOLE.print(Rule(" uploading asdf outputs "))
        thumbnails = make_rapidlook_thumbnails(
            thumbnail_staging, settings.rapidlooks.THUMBNAIL_SIZE
        )
        upload_asdf_analysis(bandset, thumbnails, roi_fits_fn, debug)

    # pretty-plot data if we've got it; just quit if we don't
    if we_do_not_have_rois:
        console.print("\n:star: ... all done ... :star:", style="bold orchid1")
        return

    pretty_plot_bandset(bandset, outpath)

    console.print("\n:star: ... all done ... :star:", style="bold orchid1")


# NOTE: ignore any complaints from static analyzers about parameter annotations
# for the following function. They are not malformed type hints, but
# instructions to clize to create single-letter aliases for parameters in the
# CLI. (--output, -o; etc.)
def asdf_hello(
    path,
    roi_path=None,
    *,
    output: "o" = None,
    upload=False,
    abbreviate: "a" = False,
    skip_rapidlooks: "r" = False,
    suffix: "s" = "",
    merspect: "m" = None,
    noninteractive: "n" = False,
    debug: "d" = False,
    keep_broadband: "b" = False,
    keep_caltarget: "g" = False
):
    """
    processes and archives everything

    :param path: path to one file from the observation you want to archive, or
        a directory containing files from one or more observations
    :param roi_path: path to a SEL or Marslab ROI file containing ROIs corresponding
        to these images (optional)
    :param upload: upload metadata to google drive
    :param output: output path; default is "output/$username/$sol"
    :param abbreviate: pass abbreviated version of iof location:
        sol,(optional) seq_id,(optional) root directory code, (optional) product type
        examples: (1) 36,03107,scratch,iof (2) 36,03107
    :param skip_rapidlooks: don't write default rapidlooks
    :param suffix: add suffix for this analysis/group of ROIs to data,
        metadata, and context image outputs (e.g. "rocks" or "soils")
    :param merspect: take data from passed merspect file
    :param noninteractive: run automatically; collect nothing from user
    :param debug: turn debug mode on
    :param keep_broadband: include frames from broadband-only sequences in
        searches
    :param keep_caltarget: include frames from apparent caltarget observations
        in searches

    """
    # find all associated files and ask the user about them
    console = ASDF_CONSOLE

    if abbreviate:
        observation, is_multiple = handle_abbreviation(
            *path.split(","),
            noninteractive=noninteractive,
            debug=debug,
            keep_broadband=keep_broadband,
            keep_caltarget=keep_caltarget
        )
    else:
        observation, is_multiple = wrapped_obs_get(
            Path(path), noninteractive, debug, keep_broadband, keep_caltarget=keep_caltarget
        )
    if observation is None:
        return
    if is_multiple is not True:
        return asdf_body(
            observation,
            roi_path,
            upload,
            output,
            skip_rapidlooks,
            suffix,
            merspect,
            noninteractive,
            debug,
            console,
        )
    for ix, obs in enumerate(observation):
        console.print(
            "... processing observation "
            + str(ix + 1)
            + " of "
            + str(len(observation))
            + " ... ",
            style="bold cyan1",
        )
        asdf_body(
            obs,
            roi_path,
            upload,
            output,
            skip_rapidlooks,
            suffix,
            merspect,
            noninteractive,
            debug,
            console,
        )
