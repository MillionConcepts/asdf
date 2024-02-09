import datetime as dt
from pathlib import Path
from typing import Optional, Literal
import re

from asdf.console import ASDF_CONSOLE, ASDFLOG, ASDF_RPH, aprint


def asdf_initiate(
    path,
    roi_path: Optional[str] = None,
    *,
    output: Optional[str] = None,
    upload: bool = False,
    abbreviate: bool = False,
    skip_rapidlooks: bool = False,
    suffix: str = "",
    noninteractive: bool = False,
    noninteractive_all: bool = False,
    debug: bool = False,
    keep_broadband: bool = False,
    keep_caltarget: bool  = False,
    keep_thumbnails: bool = False,
    mosaic: bool = False,
    merspect: Optional[str] = None,
    recursive: bool = False,
    pathdump: str = "",
    save_plain_images: bool = False,
    image_regex: Optional[str] = None,
    config: Optional[str] = None,
    skip_pixmaps: bool = False,
    skip_errmaps: bool = True,
    seriously_no_images: bool = False,
    reuse_mosaic: bool = False,
    keep_intermediate: bool = False,
    move_existing: bool = False,
    spatial: bool = False
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
        sol, seq_id, (optional) root root_dir code, (optional)
        product type. root_dir defaults to "proj" and product type to "iof".
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
    :param pathdump: dump paths and quit after producing file list
    :param keep_thumbnails: include thumbnails in searches
    :param mosaic: run in mosaic creation mode
    :param save_plain_images: save images without labels or borders
    :param image_regex: only consider images matching this regular expression
    :param config: use the asdf_settings module at the specified path rather
        than the default asdf_settings
    :param skip_pixmaps: don't look for and process pixel flag maps
    :param skip_errmaps: don't look for and process error maps
    :param seriously_no_images: don't generate images. ever. really.
    :param reuse_mosaic: reuse existing intermediate mosaic products if
        present?
    :param keep_intermediate: keep intermediate mosaic files after completion?
    :param move_existing: move existing Google Drive files to an "old"
        subdirectory.
    :param spatial: try to make spatial products?
    """
    # do expensive imports, set up logs, prepend custom settings directory to
    # path if one was passed
    console = ASDF_CONSOLE  # rich.Console object following the asdf styleguide
    with console.status(".. initializing ...", spinner="star"):
        initialize_loggers()
        insert_settings_module_path(config)
        # find all associated files and ask the user about them
        if noninteractive_all:  # run all sequences without user input
            noninteractive = "all"
        if abbreviate:  # construct a path from the abbreviated template
            from asdf.format import parse_abbreviated_inputs

            # TODO: Accept separators other than commas and robustify against
            #  white space.
            directory, seq_id = parse_abbreviated_inputs(*path.split(","))
            explicit_path = None
        else:  # use the path provided, willy-nilly
            directory, seq_id, explicit_path = None, None, path
        from asdf.chatter import find_and_offer_observations

    observation, is_multiple = find_and_offer_observations(
        root_dir=directory,
        explicit_path=explicit_path,
        target_seq_id=seq_id,
        noninteractive=noninteractive,
        keep_broadband=keep_broadband,
        keep_caltarget=keep_caltarget,
        keep_thumbnails=keep_thumbnails,
        recursive=recursive,
        regex_filter=image_regex,
        mosaic=mosaic,
    )
    if observation is None:
        # meaningful log/output for this case was already provided by
        # `find_and_offer_observation`
        return
    if pathdump:
        return perform_path_dump(pathdump, is_multiple, observation)
    asdf_args = (
        roi_path,
        upload,
        output,
        skip_rapidlooks,
        suffix,
        merspect,
        noninteractive,
        debug,
        console,
        mosaic,
        save_plain_images,
        skip_pixmaps,
        skip_errmaps,
        seriously_no_images,
        reuse_mosaic,
        keep_intermediate,
        move_existing,
        spatial
    )
    from asdf.flow import asdf_body

    if is_multiple is not True:
        return asdf_body(observation, *asdf_args)
    for ix, obs in enumerate(observation):
        aprint(
            f"[bold cyan1]... processing observation {ix+1} of "
            f"{len(observation)} ... "
        )
        asdf_body(obs, *asdf_args)


def perform_path_dump(dump_paths, is_multiple, observation):
    aprint("... dump_paths set, writing paths and exiting ...")
    with open(dump_paths, "a+") as file:
        if is_multiple:
            for obs in observation:
                for path in obs["PATH"].values:
                    file.write(path + "\n")
                file.write("\n\n")
        else:
            for path in observation["PATH"].values:
                file.write(path + "\n")


def insert_settings_module_path(config):
    if config is not None:
        import sys
        sys.path.insert(0, str(config))


def initialize_loggers():
    import logging
    from marslab.bandset.bandset import log as bandlog

    for log in (bandlog, ASDFLOG):
        log.setLevel(logging.INFO)
        log.addHandler(ASDF_RPH)


def check_successes(marslab_fn, roi_fn, logfile='logs/asdf.log'):
    with open(logfile) as stream:
        log = stream.readlines()
    successes = [line for line in log if 'successfully processed' in line]
    roi_fn = None if roi_fn is None else Path(roi_fn).name
    marslab_fn = Path(marslab_fn).name
    for success in successes:
        marslab = re.search('marslab.*csv', success).group()
        try:
            roi = (re.search(r'roi.*fits\.gz', success).group())
        except AttributeError:
            roi = None
        if (marslab == marslab_fn) and (roi == roi_fn):
            return True
    return False


def fdsa_initiate(
    marslab_path,
    image_path,
    *,
    output: Optional[str] = None,
    upload: bool = False,
    skip_rapidlooks: bool = False,
    debug: bool = False,
    seq_id: Optional[str] = "",
    sol: Optional[str] = "",
    marslab_regex: Optional[str] = None,
    image_regex: Optional[str] = ".*IOF_N.*",
    config: Optional[str] = None,
    skip_pixmaps: bool = False,
    do_empties: Literal["True", "False", "only"] = "True",
    skip_successes: bool = False,
    seriously_no_images: bool = False,
    move_existing: bool = False,
    spatial: bool = False,
    power_through_errors: bool = False
):
    """reprocesses and archives everything"""
    if (emptyarg := do_empties.title()) in ("True", "False"):
        do_empties = True if emptyarg == "True" else False
    console = ASDF_CONSOLE
    console.style = "FDSA"
    with console.status(
        "[deep_pink2 on black].. gnizilaitini ...", spinner="betaWave"
    ):
        initialize_loggers()
        insert_settings_module_path(config)
        from asdf.flow import asdf_body
    from rich.rule import Rule

    aprint(Rule(" fdsa mode ", style="deep_pink2 blink"), style="FDSA")
    from asdf.chatter import setup_reprocess

    reprocess_pairs, analyses = setup_reprocess(
        marslab_path,
        image_path,
        sol,
        seq_id,
        marslab_regex=marslab_regex,
        image_regex=image_regex,
        do_empties=do_empties
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
                f"\n[deep pink2 bold italic]sorry, something has gone wrong "
                f"matching {analysis['MARSLAB']} to its observation... "
                f":confused_face"
            )
            return
        if skip_successes is True:
            if check_successes(marslab_fn, roi_fn):
                aprint(
                    f"skip_successes = True and "
                    f"{(marslab_fn, roi_fn)} in asdf success log, skipping..."
                )
                continue
        aprint(
            f"\n[bold italic]... fdsa: processing observation {ix + 1} of "
            f"{len(reprocess_pairs)}"
        )
        console.style = "none"
        try:
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
                skip_pixmaps=skip_pixmaps,
                seriously_no_images=seriously_no_images,
                move_existing=move_existing,
                spatial=spatial
            )
            console.style = "FDSA"
            ASDFLOG.info(f"successfully processed {marslab_fn} with {roi_fn}")
        except KeyboardInterrupt:
            console.style = "FDSA"
            ASDFLOG.info(f"stopping on keyboard interrupt")
            raise
        except Exception as ex:
            from dustgoggles.dynamic import exc_report

            message = (
                f"{dt.datetime.now().isoformat()}:\nfailed to process {marslab_fn} "
                f"with {roi_fn}\n{exc_report(ex)}\n\n"
            )
            ASDFLOG.error(message)
            with open("logs/errors.log", "a") as stream:
                stream.write(message)
            if power_through_errors is False:
                raise

