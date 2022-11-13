"""
top-level handler loop for asdf / fdsa
"""
import os
import warnings
import zlib
from functools import partial
from operator import contains
from pathlib import Path

import matplotlib as mpl
import matplotlib.figure
import pandas as pd
from dustgoggles.func import catch_interaction
from rich.rule import Rule

from asdf.asdf_utils import (
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
from asdf.console import ASDF_CONSOLE, ASDF_PROGRESS, ASDF_RPH, aprint
from asdf.format import (
    make_rapidlook_thumbnails,
    make_asdf_outpath,
    compile_looks,
    add_image_hashes,
)
from asdf.network import upload_asdf_analysis
from asdf.pretty import name_prompt
from asdf.zcam_bandset import ZcamBandSet
from asdf_settings import (
    process, metadata as metadata_settings, rapidlooks
)
from marslab.compat.mertools import merspect_to_marslab
from marslab.imgops.imgutils import mapfilter


# TODO: add dry-run options for testing
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
    skip_pixmaps=False,
    skip_errmaps=True,
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
        aprint(
            f"[italic hot_pink]... fdsa: loaded prototype marslab file "
            f"{recreate_from} ..."
        )
    else:
        prototype = pd.DataFrame()
    aprint("... scraping image file headers ...")
    bandset = ZcamBandSet(
        observation, roi_path, suffix, threads=process.THREADS
    )
    if recreate_from and ("CREATOR" in prototype.columns):
        bandset.metadata["CREATOR"] = str(prototype["CREATOR"].iloc[0])
    else:
        bandset.metadata["CREATOR"] = os.getlogin()
    # add (meta)data from rc files
    aprint("... scraping photometric responsivity constant files ...")
    bandset.scrape_rc_files()
    # dial out to other directories / servers for metadata that can't be
    # found in or derived from file headers
    bandset.metadata = collect_dispersed_metadata(bandset.metadata)
    # do we have any ROIs? maybe not? there are lots of things we don't
    # do if we haven't been passed an ROI file.
    we_do_not_have_rois = (roi_path is None) and (merspect is None)

    # wrapper that suppresses input calls in non-interactive mode
    ci = partial(catch_interaction, noninteractive)

    # get observation name
    if recreate_from:
        aprint(
            "[hot_pink italic]fdsa: observation is named "
            + str(prototype["NAME"].iloc[0])
        )
        bandset.metadata["NAME"] = prototype["NAME"].iloc[0]
        if "ANALYSIS_NAME" in prototype.columns:
            analysis = str(prototype["ANALYSIS_NAME"].iloc[0])
            if analysis != "-":
                aprint(
                    f"[hot_pink italic]fdsa: ROI set / analysis name is "
                    f"{analysis}"
                )
                bandset.suffix = f"-{analysis}"
                bandset.metadata["ANALYSIS_NAME"] = analysis
    else:
        bandset.metadata["NAME"] = ci(name_prompt)

    # where are we locally writing files? by default, directories separated
    # by user, sol, name + rsm.
    outpath = make_asdf_outpath(output, bandset)
    # tell user where we're putting stuff
    aprint(f"[bold green]NOTE: files will be written to {outpath}")

    # do nothing if we are doing none of uploading, saving rapidlooks,
    # or counting ROIs. otherwise, preload images to share I/O and for
    # convenience. this is wasteful in the case that they are are images
    # that are used by no rapidlook or ROI (but not very wasteful).
    if (not we_do_not_have_rois) or (not skip_rapidlooks) or upload:
        aprint(Rule(" loading images "))
        with console.status("", spinner="star"):
            bandset.load("all")
            aprint("... generating image checksums ...")
            # TODO: make this more efficient with callbacks in the load
            #  functions or explicitly passing filelikes or something
            add_image_hashes(bandset)
    # much safer and more consistent than any of the GUI backends
    mpl.use("agg")

    if skip_pixmaps is not True:
        aprint(Rule(" looking for pixel flag maps "))
        with console.status("... handling pixel flag maps ...", spinner="star"):
            handle_map_checks(bandset,code='pix_map')
    else:
        aprint(
            "[dark_orange]skip-pixmaps flag active; skipping pixel flag map handling"
        )

    if skip_errmaps is not True:
        aprint(Rule(" looking for error maps "))
        with console.status("... handling error maps ...", spinner="star"):
            handle_map_checks(bandset,code='iof_err')
    else:
        aprint(
            "[dark_orange]skip-errmaps flag active; skipping error map handling"
        )

    if skip_rangemaps is not True:
        aprint(Rule(" looking for error maps "))
        with console.status("... handling error maps ...", spinner="star"):
            handle_map_checks(bandset, code='iof_err')

    # handle ROI file conversion, ROI counting, user input per-ROI metadata
    if we_do_not_have_rois:
        marslab_data = null_marslab_data_section()
    else:
        aprint(Rule(" gathering ROI data "))
        # suffix goes on this filename as it is 'analysis' - specific
        # did we get a ROI file path? convert it if it's SEL, save to
        # .fits, load it; if it's already FITS, load it
        try:
            roi_input_fn = bandset.rois
            bandset.load_rois(
                bandset.name + bandset.suffix, outpath, save=True
            )
        except (zlib.error, AttributeError, OSError) as error:
            aprint(
                f"[red bold]something is wrong with the passed ROI file: "
                f"{error}. Terminating."
            )
            if debug is True:
                raise
            return
        if merspect is None:
            aprint("... counting ROIs ...")
            marslab_data = bandset.count_rois()
            marslab_data["ROI_SOURCE"] = Path(roi_input_fn).name
            if recreate_from and ("ROI_SOURCE" in prototype.columns):
                marslab_data["ORIGINAL_ROI_SOURCE"] = prototype["ROI_SOURCE"]
        else:
            # TODO, maybe: remove this functionality
            #  allow user to override counting behavior with a MERspect file
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
        if not recreate_from:
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
    for last_sol, location_name in metadata_settings.LOCATION_TABLE.items():
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
        threads=bandset.threads.get("save"),
        plain=save_plain_images,
    )
    # keep images that are to be thumbnailed for upload, discard those
    # that are not; waste not memory, want not memory;
    # this convoluted selector is to avoid getting figures
    # we want to thumbnail mutated during annotation

    def pick_thumbs(rapids):
        cache = {}
        for name, look in rapids.items():
            if name not in rapidlooks.THUMBNAILS:
                continue
            if isinstance(look, matplotlib.figure.Figure):
                from marslab.imgops.pltutils import get_mpl_image

                cache[name] = get_mpl_image(look).convert("RGB")
            else:
                cache[name] = look
        return cache

    # set up thumbnail cache
    thumbnail_staging = {}
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
                partial(contains, rapidlooks.THUMBNAILS),
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
            bandset.purge("precached_images")

        aprint(Rule(" saving rapidlooks "))
        with ASDF_PROGRESS as prog:
            ASDF_RPH.task_id = prog.add_task(
                "",
                total=len(bandset.looks),
            )
            if upload:
                thumbnail_staging |= pick_thumbs(bandset.looks)
            save_images(outpath=Path(outpath, "browse"), basename=bandset.name)
            prog.remove_task(ASDF_RPH.task_id)

        bandset.purge("looks")

    # make context images and write them out
    if bandset.rois or bandset.pixmaps:
        aprint(Rule(" making context images "))
        with ASDF_CONSOLE.status("... processing context ...", spinner="star"):
            bandset.make_context_images(verbose=True)
            if not (skip_rapidlooks and not upload):
                thumbnail_staging |= pick_thumbs(bandset.looks)
            save_images(
                outpath=Path(outpath, "data"),
                basename=bandset.name + bandset.suffix,
            )

    bandset.purge()

    # pretty-plot data if we've got it
    if not we_do_not_have_rois:
        pretty_plot_bandset(bandset, Path(outpath, "data"))

    # handle metadata and thumbnail uploads
    if upload is True:
        aprint(Rule(" uploading asdf outputs "))
        thumbnails = make_rapidlook_thumbnails(
            thumbnail_staging, rapidlooks.THUMBNAIL_SIZE
        )
        upload_asdf_analysis(bandset, thumbnails, debug)

    aprint("\n:star: ... all done ... :star:", style="bold orchid1")
