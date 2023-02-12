import re
from pathlib import Path

from asdf.console import ASDF_CONSOLE, ASDFLOG, ASDF_RPH, aprint


# NOTE: ignore any complaints from static analyzers about parameter annotations
# for the following function. THEY ARE NOT MALFORMED TYPE HINTS, but
# instructions to clize to create single-letter aliases for parameters in the
# CLI. (--output, -o; etc.)
def asdf_initiate(
    path,
    roi_path=None,
    *,
    output: "o" = None,
    upload=False,
    abbreviate: "a" = False,
    skip_rapidlooks: "r" = False,
    suffix: "s" = "",
    noninteractive: "n" = False,
    noninteractive_all: "na" = False,
    debug: "d" = False,
    keep_broadband: "kb" = False,
    keep_caltarget: "kg" = False,
    keep_thumbnails: "kt" = False,
    mosaic: "m"=False,
    merspect: "mer" = None,
    recursive: "v"=False,
    dump_paths: "dp" = "",
    save_plain_images=False,
    image_regex: "ir" = None,
    config=None,
    skip_pixmaps: "sp" = False,
    skip_errmaps: "se" = True,
    seriously_no_images: "sn" = False
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
    :param dump_paths: dump paths and quit after producing file list
    :param keep_thumbnails: include thumbnails in searches
    :param mosaic: run in mosaic creation mode
    :param save_plain_images: save images without labels or borders
    :param image_regex: only consider images matching this regular expression
    :param config: use the asdf_settings module at the specified path rather
        than the default asdf_settings
    :param skip_pixmaps: don't look for and process pixel flag maps
    :param skip_errmaps: don't look for and process error maps
    :param seriously_no_images: don't generate images. ever. really.
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
        directory = None
        seq_id = None
        explicit_path = path
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
        mosaic=mosaic
    )
    if observation is None:
        # meaningful log/output for this case was already provided by
        # `find_and_offer_observation`
        return
    if dump_paths:
        return perform_path_dump(dump_paths, is_multiple, observation)
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
        seriously_no_images
    )
    from asdf.flow import asdf_body

    if is_multiple is not True:
        return asdf_body(observation, *asdf_args)
    for ix, obs in enumerate(observation):
        aprint(
            f"[bold cyan1]... processing observation {ix+1} of {len(observation)} ... "
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
    marslab_fn, roi_fn = map(lambda p: Path(p).name, (marslab_fn, roi_fn))
    for success in successes:
        marslab, roi = (
            re.search('marslab.*csv', success).group(),
            re.search(r'roi.*fits\.gz', success).group()
        )
        if (marslab == marslab_fn) and (roi == roi_fn):
            return True
    return False


def fdsa_initiate(
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
    image_regex: "ir" = ".*IOF_N.*",
    config=None,
    skip_pixmaps: "sp" = False,
    do_empties: "de" = "True",
    skip_successes: "ss" = "False",
    seriously_no_images: "sn" = False
):
    """reprocesses and archives everything"""
    if (argument := do_empties.title()) in ("True", "False"):
        do_empties = True if argument == "True" else False
    if (argument := skip_successes.title()) in ("True", "False"):
        skip_successes = True if argument == "True" else False
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
            seriously_no_images=seriously_no_images
        )
        console.style = "FDSA"
        ASDFLOG.info(f"successfully processed {marslab_fn} with {roi_fn}")
