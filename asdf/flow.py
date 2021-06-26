"""
top-level handler loops for asdf / fdsa
"""
import os
import warnings
from functools import partial
from operator import contains
from pathlib import Path

import matplotlib as mpl
import pandas as pd
from marslab.compat.mertools import merspect_to_marslab
from marslab.imgops.imgutils import mapfilter
from cytoolz.curried import keyfilter
from rich.rule import Rule

import asdf_settings as settings
from asdf.asdf_utils import (
    catch_interaction,
    null_marslab_data_section,
)
from asdf.chatter import (
    input_roi_metadata,
    handle_map_checks,
    collect_dispersed_metadata,
    save_looks,
    pretty_plot_bandset,
    fdsa_insert,
    complain_about_pixmap_counts,
)
from asdf.pretty import name_prompt
from asdf.format import (
    make_rapidlook_thumbnails,
    make_asdf_outpath,
    compile_looks,
    add_image_hashes,
)
from asdf.console import ASDF_CONSOLE, ASDF_PROGRESS, ASDF_RPH, aprint
from asdf.network import upload_asdf_analysis
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
    save_plain_images=False,
    recreate_from=None,
):
    """
    body component of the asdf command line function -- can be called multiple
    times from asdf_hello in some cases.
    """

    # do we have an roi file? if so, turn passed string into a Path
    roi_path = Path(roi_path) if roi_path else None
    # ok? great. initialize BandSet object from these paths
    aprint(Rule(" gathering metadata "))
    if recreate_from:
        prototype = pd.read_csv(recreate_from)
        aprint("[italic hot_pink]... fdsa: loaded prototype marslab file ...")
    else:
        prototype = None
    aprint("... scraping image file headers ...")
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

    # tell user where we're putting stuff
    aprint(
        "[bold green]NOTE: files will be written to {}".format(str(outpath))
    )
    # get observation name
    if prototype is not None:
        aprint(
            "[hot_pink italic]fdsa: observation is named "
            + str(prototype["NAME"].iloc[0])
        )
        bandset.metadata["NAME"] = prototype["NAME"].iloc[0]
        if "ANALYSIS_NAME" in prototype.columns:
            if prototype["ANALYSIS_NAME"].iloc[0] != "-":
                aprint(
                    "[hot_pink italic]fdsa: ROI set / analysis name is "
                    + str(prototype["ANALYSIS_NAME"].iloc[0])
                )
                bandset.suffix = "-" + prototype["ANALYSIS_NAME"].iloc[0]
                bandset.metadata["ANALYSIS_NAME"] = prototype["ANALYSIS_NAME"]
    else:
        bandset.metadata["NAME"] = ci(name_prompt)

    # do nothing if we are doing none of uploading, saving rapidlooks,
    # or counting ROIs. otherwise, preload images to share I/O and for
    # convenience. this is wasteful in the case that they are are images
    # that are used by no rapidlook or ROI (but not very wasteful).
    if (not we_do_not_have_rois) or (not skip_rapidlooks) or upload:
        aprint(Rule(" loading images "))
        with console.status("", spinner="star"):
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                bandset.load("all")
                aprint("... generating image checksums ...")
                # TODO: make this more efficient with callbacks in the load
                # functions or explicitly passing filelikes or something
                add_image_hashes(bandset)
    # set up thumbnail cache
    thumbnail_staging = {}
    pick_thumbs = keyfilter(partial(contains, settings.rapidlooks.THUMBNAILS))

    mpl.use("agg")
    aprint(Rule(" looking for pixel flag maps "))
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        with console.status("... handling flagmaps ...", spinner="star"):
            handle_map_checks(bandset)
    # handle ROI file conversion, ROI counting, user input per-ROI metadata
    roi_fits_fn = None
    if we_do_not_have_rois:
        marslab_data = null_marslab_data_section()
    else:
        aprint(Rule(" gathering ROI data "))
        # suffix goes on this filename as it is 'analysis' - specific
        # did we get a ROI file path? convert it if it's SEL, save to
        # .fits, load it; if it's already FITS, load it
        roi_fits_fn = bandset.load_rois(
            bandset.name + bandset.suffix, outpath, convert=True
        )
        if merspect is None:
            aprint("... counting ROIs ...")
            marslab_data = bandset.count_rois()
            marslab_data["ROI_SOURCE"] = Path(roi_fits_fn).name
        else:
            # TODO, maybe: remove this functionality
            # allow user to override counting behavior with a MERspect file
            # TODO, maybe: basic check to make sure file matches pointing
            aprint("... converting MERspect output ...")
            marslab_data = merspect_to_marslab(merspect, write=False)
            marslab_data["ROI_SOURCE"] = "[merspect] " + Path(merspect).name
        if marslab_data is None:
            aprint(
                "something has gone wrong in loading ROI data.",
                style="red bold",
            )
        if bandset.pixmaps:
            aprint("... counting ROIs on pixel flag maps ...")
            bandset.count_pixmaps()
            complain_about_pixmap_counts(bandset.pixmap_counts)
        if prototype is None:
            # prompt users for info on each ROI
            marslab_data = input_roi_metadata(marslab_data, ci)
        else:
            aprint(
                "[hot_pink italic]... fdsa: populating ROI metadata from"
                " prototype ..."
            )
            marslab_data = fdsa_insert(marslab_data, prototype)
    aprint(Rule(" writing data files "))
    if we_do_not_have_rois:
        aprint("[dark_orange]No ROI file passed; using null values for data.")
    # add location from lookup table and sol
    marslab_data["LOCATION"] = "Unknown"
    for last_sol, location_name in settings.metadata.LOCATION_TABLE.items():
        if last_sol > int(bandset.metadata["SOL"].iloc[0]):
            marslab_data["LOCATION"] = location_name
            break
    bandset.counts = marslab_data
    # glom all the data and metadata together into our three output formats
    bandset.format_metadata()
    # write the compact and extended versions, save the summary in memory
    bandset.write_data_files(outpath, verbose=True)

    # image-saving closure
    save_images = partial(
        save_looks,
        bandset,
        outpath,
        threads=bandset.threads.get("save"),
        plain=save_plain_images,
    )
    # generate rapidlooks
    if skip_rapidlooks and not upload:
        aprint(
            "[dark_orange]skip-rapidlooks flag active; skipping "
            "rapidlook generation"
        )
    else:
        aprint(Rule(" generating rapidlooks "))
        look_instructions = compile_looks()
        if skip_rapidlooks and upload:
            aprint(
                "[dark_orange]skip-rapidlooks flag active; generating only "
                "rapidlooks required for uploaded thumbnails"
            )
            look_instructions = mapfilter(
                partial(contains, settings.rapidlooks.THUMBNAILS),
                "name",
                look_instructions,
            )
        with ASDF_PROGRESS as prog:
            ASDF_RPH.task_id = prog.add_task(
                "",
                total=len(look_instructions),
            )
            # suppressing irrelevant warnings from numpy about divides-by-zero
            # and matplotlib about opening a bunch of figures
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                bandset.make_look_set(look_instructions)
            prog.remove_task(ASDF_RPH.task_id)

        aprint(Rule(" saving rapidlooks "))
        with ASDF_PROGRESS as prog:
            ASDF_RPH.task_id = prog.add_task(
                "",
                total=len(bandset.looks),
            )
            save_images(prefix=bandset.name)
            prog.remove_task(ASDF_RPH.task_id)
        # keep images that are to be thumbnailed for upload, discard those
        # that are not; waste not memory, want not memory
        thumbnail_staging |= pick_thumbs(bandset.looks)
        bandset.purge("looks")

    # make context images and write them out
    if bandset.rois or bandset.pixmaps:
        aprint(Rule(" making context images "))
        # remove save threading b/c max 4 images and pointless
        with ASDF_CONSOLE.status("... processing context ...", spinner="star"):
            bandset.threads = {}
            bandset.make_context_images(verbose=True)
            save_images = partial(save_images, threads=None)
            save_images(prefix=bandset.name + bandset.suffix)
            thumbnail_staging |= pick_thumbs(bandset.looks)
    bandset.purge()
    aprint("\n")

    # pretty-plot data if we've got it
    if not we_do_not_have_rois:
        pretty_plot_bandset(bandset, outpath)

    # handle metadata and thumbnail uploads
    if upload is True:
        aprint(Rule(" uploading asdf outputs "))
        thumbnails = make_rapidlook_thumbnails(
            thumbnail_staging, settings.rapidlooks.THUMBNAIL_SIZE
        )
        upload_asdf_analysis(bandset, thumbnails, roi_fits_fn, debug)

    aprint("\n:star: ... all done ... :star:", style="bold orchid1")
