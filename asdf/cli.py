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
from cytoolz.curried import keyfilter
from rich.rule import Rule

import asdf.settings as settings
from asdf.asdf_utils import catch_interaction, null_marslab_data_section
from asdf.chatter import (
    input_roi_metadata,
    find_and_offer_observations,
    handle_map_checks,
    collect_dispersed_metadata,
    save_looks,
    pretty_plot_bandset,
    setup_reprocess,
    fdsa_insert,
)
from asdf.pretty import name_prompt
from asdf.format import (
    make_rapidlook_thumbnails,
    handle_abbreviation,
    make_asdf_outpath,
)
from asdf.console import ASDF_CONSOLE, ASDF_PROGRESS, ASDF_RPH, aprint
from asdf.network import upload_asdf_analysis
from asdf.zcam_bandset import ZcamBandSet
from marslab.compat.mertools import merspect_to_marslab


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
    recreate_from=None,
    save_plain_images=False
):
    """
    body component of the asdf command line function -- can be called multiple
    times from asdf_hello in some cases.
    """

    # do we have an roi file? if so, turn passed string into a Path
    roi_path = Path(roi_path) if roi_path else None
    # ok? great. initialize BandSet object from these paths
    console.print(Rule(" gathering metadata "))
    if recreate_from:
        prototype = pd.read_csv(recreate_from)
        console.print(
            "[italic hot_pink]... fdsa: loaded prototype marslab file ..."
        )
    else:
        prototype = None
    console.print("... scraping image file headers ...")
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
    console.print(
        "[bold white]NOTE: files will be written to {}".format(str(outpath))
    )
    # get observation name
    if prototype is not None:
        aprint(
            "[hot_pink italic]fdsa: observation is named "
            + prototype["NAME"].iloc[0]
        )
        bandset.metadata["NAME"] = prototype["NAME"].iloc[0]
        if prototype["ANALYSIS_NAME"].iloc[0] != "-":
            aprint(
                "[hot_pink italic]fdsa: ROI set / analysis name is "
                + prototype["ANALYSIS_NAME"].iloc[0]
            )
            bandset.suffix = "-" + prototype["ANALYSIS_NAME"].iloc[0]
            bandset.metadata["ANALYSIS_NAME"] = prototype["ANALYSIS_NAME"]
    else:
        bandset.metadata["NAME"] = ci(name_prompt)

    # do nothing if we are neither producing rapidlooks nor counting ROIs.
    # otherwise, preload images to share I/O and for convenience.
    # this is wasteful in the case if are images that are used
    # by no rapidlook or ROI (but not very wasteful, and this is rare).
    if not we_do_not_have_rois or not skip_rapidlooks:
        console.print(Rule(" loading images "))
        with console.status("", spinner="star"):
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                bandset.load("all")
    mpl.use("agg")
    console.print(Rule(" looking for pixel flag maps "))
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        with console.status("... handling flagmaps ...", spinner="star"):
            handle_map_checks(bandset)
    # handle ROI file conversion, ROI counting, user input per-ROI metadata
    roi_fits_fn = None
    if we_do_not_have_rois:
        marslab_data = null_marslab_data_section()
    else:
        console.print(Rule(" gathering ROI data "))
        # suffix goes on this filename as it is 'analysis' - specific
        # did we get a ROI file path? convert it if it's SEL, save to
        # .fits, load it; if it's already FITS, load it
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
            console.print("... converting MERspect output ...")
            marslab_data = merspect_to_marslab(merspect, write=False)
            marslab_data["ROI_SOURCE"] = "[merspect] " + Path(merspect).name
        if marslab_data is None:
            console.print(
                "something has gone wrong in loading ROI data.",
                style="red bold",
            )
        if prototype is None:
            # prompt users for info on each ROI
            marslab_data = input_roi_metadata(marslab_data, ci)
        else:
            aprint(
                "[hot_pink italic]... fdsa: populating ROI metadata from"
                " prototype ..."
            )
            marslab_data = fdsa_insert(marslab_data, prototype)
    console.print(Rule(" writing data files "))
    if we_do_not_have_rois:
        console.print(
            "[dark_orange]No ROI file passed; using null values for data."
        )
    # add location -- TODO: lookup table once we have more than one
    marslab_data["LOCATION"] = "Octavia E. Butler Landing"
    bandset.counts = marslab_data
    # glom all the data and metadata together into our three output formats;
    bandset.format_metadata()
    # write the compact and extended versions, save the summary in memory
    bandset.write_data_files(outpath, verbose=True)
    # set up thumbnail cache
    thumbnail_staging = {}
    pick_thumbs = keyfilter(
        partial(contains, settings.rapidlooks.THUMBNAIL_THESE)
    )
    # image-saving closure
    save_images = partial(
        save_looks,
        bandset,
        outpath,
        threads=bandset.threads.get("save"),
        plain=save_plain_images
    )
    # generate rapidlooks
    if skip_rapidlooks:
        console.print(
            "[dark_orange]skip-rapidlooks flag active, skipping "
            "rapidlook generation"
        )
    else:
        console.print(Rule(" generating rapidlooks "))
        with ASDF_PROGRESS as prog:
            ASDF_RPH.task_id = prog.add_task(
                "",
                total=len(settings.rapidlooks.DEFAULT_RAPIDLOOKS),
            )
            # suppressing irrelevant warnings from numpy about divides-by-zero
            # and matplotlib about opening a bunch of figures
            # settings.rapidlooks.DEFAULT_RAPIDLOOKS = {
            #     thing: other for thing, other in settings.rapidlooks.DEFAULT_RAPIDLOOKS.items() if thing == 'BD529'
            # }
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                bandset.make_look_set(settings.rapidlooks.DEFAULT_RAPIDLOOKS)
            prog.remove_task(ASDF_RPH.task_id)

        console.print(Rule(" saving rapidlooks "))
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

    # handle metadata and thumbnail uploads
    if upload is True:
        aprint(Rule(" uploading asdf outputs "))
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
    noninteractive_all: "na" = False,
    debug: "d" = False,
    keep_broadband: "kb" = False,
    keep_caltarget: "kg" = False,
    keep_thumbnails: "kt" = False,
    recursive=False,
    product_type: "t" = "",
    seq_id: "i" = "",
    sol: "l" = "",
    dump_paths: "dp" = "",
    save_plain_images = False
):
    """
    processes and archives everything

    :param path: path to one file from the observation you want to archive, or
        a root_dir containing files from one or more observations
    :param roi_path: path to a SEL or Marslab ROI file containing ROIs
        corresponding to these images (optional)
    :param upload: upload metadata to google drive
    :param output: output path; default is "output/$username/$sol"
    :param abbreviate: pass abbreviated version of iof location:
        sol,(optional) seq_id,(optional) root root_dir code, (optional)
        product type
        examples: (1) 36,03107,scratch,iof (2) 36,03107
    :param skip_rapidlooks: don't write default rapidlooks
    :param suffix: add suffix for this analysis/group of ROIs to data,
        metadata, and context image outputs (e.g. "rocks" or "soils")
    :param merspect: take data from passed merspect file
    :param noninteractive: run automatically; collect nothing from user
    :param noninteractive_all: run automatically on all detected sequences;
            collect nothing from user
    :param debug: turn debug mode on
    :param keep_broadband: include frames from broadband-only sequences in
        searches
    :param keep_caltarget: include frames from apparent caltarget observations
        in searches
    :param recursive: search all directories under the chosen path
    :param product_type: filter files for a particular product type
    :param dump_paths: dump paths and quit after producing file list
    :param keep_thumbnails: include thumbnails in searches
    :param sol: target sol for search (useful for recursive search)
    :param seq_id: target seq_id for search (useful for recursive search)
    :param save_plain_images: save images without labels or borders

    """
    # find all associated files and ask the user about them
    console = ASDF_CONSOLE

    if noninteractive_all:
        noninteractive = "all"
    if abbreviate:
        directory, sol, seq_id = handle_abbreviation(*path.split(","))
        explicit_path = None
    else:
        directory = None
        sol = sol
        if seq_id:
            seq_id = "ZCAM" + str(seq_id)
        explicit_path = path
    observation, is_multiple = find_and_offer_observations(
        root_dir=directory,
        explicit_path=explicit_path,
        target_sol=sol,
        target_seq_id=seq_id,
        noninteractive=noninteractive,
        keep_broadband=keep_broadband,
        keep_caltarget=keep_caltarget,
        keep_thumbnails=keep_thumbnails,
        recursive=recursive,
        target_product_type=product_type,
    )
    if observation is None:
        return
    if dump_paths:
        console.print("... dump_paths set, writing paths and exiting ...")
        with open(dump_paths, "a+") as file:
            if is_multiple:
                for obs in observation:
                    for path in obs["PATH"].values:
                        file.write(path + "\n")
                    file.write("\n\n")
            else:
                for path in observation["PATH"].values:
                    file.write(path + "\n")
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
            save_plain_images=save_plain_images
        )
    # TODO: yuck.
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
            save_plain_images=save_plain_images
        )


def fdsa_hello(
    marslab_path,
    image_path,
    *,
    output: "o" = None,
    upload=False,
    skip_rapidlooks: "r" = False,
    debug: "d" = False,
    seq_id: "i" = "",
    sol: "l" = "",
    marslab_regex: "mr" = None,
    image_regex: "ir" = ".*IOF.*",
):
    """reprocesses and archives everything"""
    console = ASDF_CONSOLE
    console.style = "FDSA"
    aprint(Rule(" fdsa mode ", style="deep_pink2 blink"), style="FDSA")
    reprocess_pairs, analyses = setup_reprocess(
        marslab_path,
        image_path,
        sol,
        seq_id,
        marslab_regex=marslab_regex,
        image_regex=image_regex,
    )
    if reprocess_pairs is None:
        return
    for ix, item in enumerate(reprocess_pairs.items()):
        analysis = analyses.iloc[ix]
        marslab_fn = item[0]
        obs = item[1]
        roi_fn = analysis["ROI"]
        if marslab_fn != analysis["MARSLAB"]:
            aprint(
                "\n[deep_pink2 bold italic]sorry, something has gone wrong "
                "matching {} to its observation. skipping... "
                ":confused_face:".format(analysis["MARSLAB"])
            )
        console.print(
            "\n[bold italic]... fdsa: processing observation {} of {} ...".format(
                str(ix + 1), str(len(reprocess_pairs))
            )
        )
        console.style = "none"
        asdf_body(
            obs,
            roi_fn,
            upload,
            output,
            skip_rapidlooks,
            debug=debug,
            console=console,
            recreate_from=marslab_fn,
            noninteractive=True,
        )
        console.style = "FDSA"
