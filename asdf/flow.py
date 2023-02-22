"""
top-level handler loop for asdf / fdsa
"""
import getpass
import shutil
import zlib
from functools import partial
from operator import contains
import os
from pathlib import Path
import warnings

from dustgoggles.func import catch_interaction
import matplotlib.figure

from asdf_settings.process import THREADS
from marslab.compat.mertools import merspect_to_marslab
from marslab.imgops.imgutils import mapfilter
import matplotlib as mpl
import pandas as pd
from rich.rule import Rule

from asdf.asdf_utils import null_marslab_data_section
from asdf.chatter import (
    input_roi_metadata,
    handle_map_checks,
    collect_dispersed_metadata,
    save_looks,
    pretty_plot_bandset,
    fdsa_insert,
    complain_about_pixmap_counts, check_mosaic_paths,
)
from asdf.console import ASDF_CONSOLE, ASDF_PROGRESS, ASDF_RPH, aprint
from asdf.format import (
    make_rapidlook_thumbnails,
    make_asdf_outpath,
    compile_looks,
    add_image_hashes,
)
from asdf.network import upload_asdf_analysis, upload_mosaic
from asdf.pretty import name_prompt
from asdf.zcam_bandset import ZcamBandSet
from asdf_settings import process, metadata as metadata_settings, rapidlooks
from asdf_settings.sources import USE_PUBLIC_WAYPOINTS


def pick_thumbs(rapids):
    """
    keep images that are to be thumbnailed for upload, discard those that are
    not. waste not memory, want not memory.
    """
    cache = {}
    # this convoluted-looking selector is to avoid getting figures
    # we want to thumbnail mutated during annotation
    for name, look in rapids.items():
        if name not in rapidlooks.THUMBNAILS:
            continue
        if isinstance(look, matplotlib.figure.Figure):
            from marslab.imgops.pltutils import get_mpl_image

            cache[name] = get_mpl_image(look).convert("RGB")
        else:
            cache[name] = look
    return cache


def generate_locator_images(bandsets, temp_path):
    locator_tiffs = []



def _process_mosaic(
    observation,
    roi_path,
    noninteractive,
    upload,
    console,
    save_plain_images,
    skip_rapidlooks,
    reuse_mosaic,
    keep_intermediate,
    debug,
    seriously_no_images
):
    # TODO: take this out
    save_plain_images = True
    if roi_path is not None:
        raise ValueError("Sorry, ROI counting on mosaic is not supported.")
    from asdf.mosaic import (
        make_single_band_mosaics,
        preprocess_mosaic_metadata,
        concatenate_mosaic,
        bounce_mosaic_input_files,
        ZMosaicBandSet,
    )
    from asdf.format import folder_names
    # TODO, maybe: all these preliminaries are utterly superfluous if
    #  reuse_mosaics is True.
    aprint(Rule(" gathering metadata "))
    aprint("... scraping image file headers ...")
    bandsets = [ZcamBandSet(pointing[1]) for pointing in observation]
    # TODO: messy, probably only need to do it for one
    if USE_PUBLIC_WAYPOINTS:
        aprint(
            "... scraping localization information from public waypoints file "
            "..."
        )
    for bandset in bandsets:
        bandset.metadata["CREATOR"] = os.getlogin()
        bandset.metadata = collect_dispersed_metadata(bandset.metadata, True)
    ci = partial(catch_interaction, noninteractive)
    name = ci(name_prompt)
    for bandset in bandsets:
        bandset.metadata["NAME"] = name
    # TODO: fold this business into make_asdf_outpath
    sol_folder_name, obs_folder_name = folder_names(bandsets[0], True)
    outpath = Path(
        "output", getpass.getuser(), sol_folder_name, obs_folder_name
    )
    temp_path = Path(outpath, 'temp')
    temp_path.mkdir(parents=True, exist_ok=True)
    aprint(f"[bold green]NOTE: files will be written to {outpath}")
    # TODO, maybe: add pixmap stuff
    if reuse_mosaic is True:
        mosaic_paths = check_mosaic_paths(bandsets, outpath)
        # meaningful output for this case provided in check_mosaic_paths
        if mosaic_paths is None:
            return
        aprint(
            "[dark_orange]note: --reuse_mosaics passed, using existing "
            "mosaic.fits files"
        )
    else:
        aprint(Rule(" generating intermediate mosaic files "))
        with console.status("", spinner="star"):
            aprint("... converting inputs to TIFF ...")
            tiff_info, locator_info = bounce_mosaic_input_files(
                bandsets, temp_path
            )
            if tiff_info is None:
                # mismatched band availability.
                # useful feedback provided in bounce_mosaic_input_files.
                return
        aprint("... stitching single-band mosaics ...")
        process_info = {}
        with ASDF_PROGRESS as prog:
            ASDF_RPH.task_id = prog.add_task(
                "",
                total=len(bandsets[0].metadata["BAND"].unique()) * 2 + 2,
            )
            for eye in ("L", "R"):
                process_info[eye] = make_single_band_mosaics(
                    eye, tiff_info, locator_info, bandsets
                )
            prog.remove_task(ASDF_RPH.task_id)
        if all(v == (None, None, None) for v in process_info.values()):
            aprint(
                "[bold red] Unable to create mosaics for either eye. "
                "Bailing out."
            )
            if keep_intermediate is False:
                shutil.rmtree(temp_path)
            return
        aprint(Rule("generating multi-band mosaic files"))
        with console.status("", spinner="star"):
            mosaic_metadata = preprocess_mosaic_metadata(bandsets)
            data_dir = Path(outpath, "data")
            data_dir.mkdir(parents=True, exist_ok=True)
            mosaic_paths = {}
            for eye in ("L", "R"):
                if process_info[eye] == (None, None, None):
                    # this indicates a failed projection
                    continue
                mosaic_paths[eye] = concatenate_mosaic(
                    process_info, eye, mosaic_metadata, Path(outpath, "data")
                )
                eye_name = {"L": "left", "R": "right"}[eye]
                aprint(f"wrote {eye_name}-eye mosaic")
    if keep_intermediate is False:
        shutil.rmtree(temp_path)
    mosaic = ZMosaicBandSet(
        tuple(mosaic_paths.values()),
        threads={
            'save': THREADS['mosaic_save'], 'look': THREADS['mosaic_look']
        }
    )
    mosaic.format_metadata()
    thumbnail_staging = {}
    if seriously_no_images:
        aprint(
            "[dark_orange]seriously-no-images flag active; skipping "
            "rapidlook generation"
        )
    elif skip_rapidlooks and not upload:
        aprint(
            "[dark_orange]skip-rapidlooks flag active; skipping "
            "rapidlook generation"
        )
    else:
        aprint(Rule("generating rapidlooks"))
        instructions = compile_looks()
        if skip_rapidlooks and upload:
            aprint(
                "[dark_orange]skip-rapidlooks flag active; generating only "
                "rapidlooks required for uploaded thumbnails"
            )
            instructions = mapfilter(
                partial(contains, rapidlooks.THUMBNAILS), "name", instructions
            )

        for inst in instructions:
            # don't apply default zcam detector frame crop to projected images
            if "crop" in inst.keys():
                del inst['crop']
            # retain mask for outside-projection regions
            if inst['plotter']['function'].__name__ == 'colormapped_plot':
                inst['plotter']['params']['drop_mask'] = False
            # make sky masking algorithm ignore the out-of-projection regions
            if 'mask' in inst.keys():
                for mask_inst in inst['mask']['instructions']:
                    if 'function' not in mask_inst.keys():
                        continue
                    if mask_inst['function'].__name__ != 'skymask':
                        continue
                    mask_inst['params'] |= {
                        'input_mask_dilation': 10, 'respect_mask': True
                    }

        with ASDF_PROGRESS as prog:
            ASDF_RPH.task_id = prog.add_task("", total=len(instructions) + 2)
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", category=RuntimeWarning)
                mosaic.make_look_set(instructions)
                prog.remove_task(ASDF_RPH.task_id)
        aprint(Rule(" saving rapidlooks "))
        save_images = partial(
            save_looks,
            mosaic,
            plain=save_plain_images,
            threads=mosaic.threads['save']
        )
        with ASDF_PROGRESS as prog:
            ASDF_RPH.task_id = prog.add_task("", total=len(mosaic.looks) + 1)
            if upload is True:
                thumbnail_staging |= pick_thumbs(mosaic.looks)
            save_images(outpath=Path(outpath, "browse"), basename=mosaic.name)
            prog.remove_task(ASDF_RPH.task_id)
            mosaic.purge("looks")
    # handle metadata and thumbnail uploads
    if upload is True:
        aprint(Rule(" uploading asdf outputs "))
        thumbnails = make_rapidlook_thumbnails(
            thumbnail_staging, rapidlooks.THUMBNAIL_SIZE
        )
        try:
            upload_mosaic(mosaic, thumbnails, debug)
        except InterruptedError:
            return   # quit at user request due to dupe filenames

    aprint("\n:star: ... all done ... :star:", style="bold orchid1")


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
    mosaic=False,
    save_plain_images=False,
    skip_pixmaps=False,
    skip_errmaps=True,
    seriously_no_images=False,
    reuse_mosaic=False,
    keep_intermediate=False,
    recreate_from=None,
):
    """
    body component of the asdf command line function -- can be called multiple
    times from asdf_initiate in some cases.
    """
    # do we have an roi file? if so, turn passed string into a Path
    roi_path = Path(roi_path) if roi_path else None
    if mosaic is True:
        return _process_mosaic(
            observation,
            roi_path,
            noninteractive,
            upload,
            console,
            save_plain_images,
            skip_rapidlooks,
            reuse_mosaic,
            keep_intermediate,
            debug,
            seriously_no_images
        )
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
        bandset.metadata["CREATOR"] = getpass.getuser()
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
        with console.status(
            "... handling pixel flag maps ...", spinner="star"
        ):
            handle_map_checks(bandset, code="pix_map")
    else:
        aprint(
            "[dark_orange]skip-pixmaps flag active; skipping pixel "
            "flag map handling"
        )

    if skip_errmaps is not True:
        aprint(Rule(" looking for error maps "))
        with console.status("... handling error maps ...", spinner="star"):
            handle_map_checks(bandset, code="iof_err")
    else:
        aprint(
            "[dark_orange]skip-errmaps flag active; skipping error map handling"
        )

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
    # set up thumbnail cache
    thumbnail_staging = {}
    # generate rapidlooks
    if skip_rapidlooks and not upload:
        aprint(
            "[dark_orange]skip-rapidlooks flag active; skipping "
            "rapidlook generation"
        )
    elif seriously_no_images:
        aprint(
            "[dark_orange]seriously-no-images flag active; skipping "
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
                total=len(look_instructions) + 1,
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
                total=len(bandset.looks) + 1,
            )
            if upload:
                thumbnail_staging |= pick_thumbs(bandset.looks)
            save_images(outpath=Path(outpath, "browse"), basename=bandset.name)
            prog.remove_task(ASDF_RPH.task_id)
        bandset.purge("looks")
    # make context images and write them out
    if bandset.rois or bandset.pixmaps:
        if seriously_no_images:
            aprint(
                "[dark_orange]seriously-no-images flag active; skipping "
                "context image generation"
            )
        else:
            aprint(Rule(" making context images "))
            with ASDF_CONSOLE.status(
                "... processing context ...", spinner="star"
            ):
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
        try:
            upload_asdf_analysis(bandset, thumbnails, debug)
        except InterruptedError:
            return   # quit at user request due to dupe filenames

    aprint("\n:star: ... all done ... :star:", style="bold orchid1")
