from asdf.console import ASDF_CONSOLE, ASDFLOG, ASDF_RPH, aprint

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
    dump_paths: "dp" = "",
    save_plain_images=False,
    image_regex: "ir" = None,
    config=None
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
    :param save_plain_images: save images without labels or borders

    """
    # do expensive imports, set up logs, prepend custom settings directory to
    # path if one was passed
    console = ASDF_CONSOLE
    with console.status(".. initializing ...", spinner="star"):
        initialize_asdf(config)
        from asdf.flow import asdf_body
    # find all associated files and ask the user about them
    if noninteractive_all:
        noninteractive = "all"
    if abbreviate:
        from asdf.format import handle_abbreviation
        directory, seq_id = handle_abbreviation(*path.split(","))
        explicit_path = None
    else:
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
        target_product_type=product_type,
        regex_filter=image_regex,
    )
    if observation is None:
        return
    if dump_paths:
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
            return
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
        save_plain_images,
    )
    if is_multiple is not True:
        return asdf_body(observation, *asdf_args)
    for ix, obs in enumerate(observation):
        aprint(
            "... processing observation "
            + str(ix + 1)
            + " of "
            + str(len(observation))
            + " ... ",
            style="bold cyan1",
        )
        asdf_body(obs, *asdf_args)


def initialize_asdf(config):
    import logging
    from marslab.imgops.bandset import log as bandlog
    for log in (bandlog, ASDFLOG):
        log.setLevel(logging.INFO)
        log.addHandler(ASDF_RPH)
    if config is not None:
        import sys
        sys.path.insert(0, config)


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
    config=None
):
    """reprocesses and archives everything"""
    console = ASDF_CONSOLE
    console.style = "FDSA"
    with console.status(
        "[deep_pink2 on black].. gnizilaitini ...", spinner="betaWave"
    ):
        initialize_asdf(config)
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
                "\n[deep_pink2 bold italic]sorry, something has gone "
                "wrong "
                "matching {} to its observation... "
                ":confused_face:".format(analysis["MARSLAB"])
            )
            return
        aprint(
            "\n[bold italic]... fdsa: processing observation "
            "{} of {} ...".format(str(ix + 1), str(len(reprocess_pairs)))
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
