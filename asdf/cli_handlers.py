"""
inline handling functions for runtime asdf workflow
"""
import os

import warnings
from pathlib import Path

import PIL.Image
from pathos.multiprocessing import ProcessingPool
import matplotlib.figure
from clize import UserError
from cytoolz import valfilter

import asdf.settings as settings
import pplot
from asdf.asdf_utils import dashify
from asdf.chatter import find_and_offer_observations
from asdf.console import ASDF_CONSOLE, ASDFLOG
from asdf.scrape import (
    parse_pointing,
    add_effective_taus,
    add_public_waypoints_to_metadata,
)
from marslab.imgops.pltutils import get_mpl_image, set_label
from marslab.imgops.poolutils import wait_for_it
from marslab.imgops.render import make_thumbnail, simple_mpl_figure
from marslab.imgops.imgutils import absolutely_destroy, eightbit


def collect_dispersed_metadata(metadata):
    """
    handler function for asdf.cli that runs around to several distinct
    sources asking them for additional info prior to ROI evaluation
    """

    if settings.sources.USE_PUBLIC_WAYPOINTS:
        ASDF_CONSOLE.print(
            "... scraping localization information from public "
            "waypoints file ..."
        )
        metadata = add_public_waypoints_to_metadata(metadata)
    if settings.sources.FIND_EFFECTIVE_TAUS:
        metadata = add_effective_taus(metadata)
    return metadata


def make_asdf_outpath(output, bandset):
    """
    where are we locally writing files? by default, directories separated
    by user and sol.
    """
    if output is None:
        outpath = Path(
            "output/",
            os.getlogin(),
            format(bandset.metadata["SOL"].iloc[0], "0>4"),
        )
    else:
        outpath = Path(output)
    os.makedirs(outpath, exist_ok=True)
    return outpath


def make_pointing_annotation(pointing):
    return ", ".join(
        [
            key.lower() + " " + str(value)
            for key, value in parse_pointing(pointing).items()
        ]
    )


def save_plainly(_, look, filename, outpath):
    if isinstance(look, matplotlib.figure.Figure):
        look = get_mpl_image(look)
    image = PIL.Image.fromarray(eightbit(look))
    image.save(Path(outpath, filename))


def annotate_and_save(annotation, look, filename, outpath):
    # TODO: decide if these annotation things should live on zcambandset --
    #  this is not urgent. I think _maybe_ they should be separate.
    if not isinstance(look, matplotlib.figure.Figure):
        look = simple_mpl_figure(look)
    set_label(look, annotation, fontproperties=settings.rapidlooks.TITLE_FONT)
    look.savefig(Path(outpath, filename), dpi=275)
    absolutely_destroy(look)
    return 0


def save_looks(bandset, outpath, prefix=None, threads=None, verbose=False):
    # TODO: decide if this and annotate_and_save_rapidlook() should live on
    #  zcambandset -- this is not urgent.
    if prefix is None:
        prefix = bandset.name
    pool = None
    results = {}
    # TODO: dispatch these cases
    if threads is not None:
        pool = ProcessingPool(threads)
        pool.restart()
    for look_name, look in bandset.looks.items():
        filename = prefix + " " + look_name + ".png"
        annotation = "\n".join(
            (
                look_name,
                make_pointing_annotation(bandset.metadata),
                settings.rapidlooks.CREDIT_TEXT,
            )
        )
        if pool is None:
            annotate_and_save(annotation, look, filename, outpath)
            ASDFLOG.info("wrote " + filename)
            # TODO: add option to _not_ wrap in figures
        else:
            results[filename] = pool.apipe(
                annotate_and_save, annotation, look, filename, outpath
            )
    if pool is not None:
        wait_for_it(pool, results, ASDFLOG, "wrote ")


def handle_abbreviation(
    sol, seq_id, root=None, filetype=None, noninteractive=False
):
    sol_path = format(int(sol), "0>4")
    # default path root and subdirectory, which can be overridden
    if root:
        try:
            path_root = settings.sources.PATH_ABBREVIATIONS[root]
        except KeyError:
            ASDF_CONSOLE.log(
                "sorry, I don't know the abbreviation \""
                + root
                + '".  I know '
                + " ".join(
                    [
                        '"' + key + '",'
                        for key in settings.sources.PATH_ABBREVIATIONS.keys()
                    ]
                ), style = "bold red"
            )
            return None, False
    else:
        path_root = list(settings.sources.PATH_ABBREVIATIONS.values())[0]
    if filetype:
        product_subdirectory = filetype
    else:
        product_subdirectory = settings.sources.DEFAULT_PRODUCT_SUBDIRECTORY
    directory = Path(path_root, sol_path, product_subdirectory)
    seq_id = 'zcam' + str(seq_id)
    return find_and_offer_observations(
        None, directory, sol, seq_id
    )


def make_rapidlook_thumbnails(rapidlooks, size):
    ASDF_CONSOLE.print("... making thumbnails (if necessary) ...")
    thumbnails = {}
    for name, image in rapidlooks.items():
        thumbnails[name] = make_thumbnail(image, size)
    return thumbnails


def pretty_plot_bandset(bandset, outpath):
    ASDF_CONSOLE.print("... pretty-plotting data ...")
    plot_fn = str(
        Path(outpath, bandset.name + bandset.suffix + "-pretty-plot.png")
    )
    ASDF_CONSOLE.print("Writing " + plot_fn)
    from pplot.convert import scale_eyes

    target_name = ""
    if bandset.compact["NAME"].iloc[0]:
        target_name = bandset.compact["NAME"].iloc[0]
    plot_data = scale_eyes(bandset.compact.copy(), method="scale_to_avg")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        pplot.pplot_utils.pretty_plot(
            dashify(plot_data),
            target_name=target_name,
            sol=bandset.compact["SOL"].iloc[0],
            solar_elevation=bandset.compact["SOLAR_ELEVATION"].iloc[0],
            seq_id=bandset.compact["SEQ_ID"].iloc[0],
            plot_fn=plot_fn,
            underplot=None,
        )
