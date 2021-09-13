from functools import partial, reduce
from typing import Mapping, Sequence

from marslab import spectops
from marslab.bandset import BandSet
from marslab.imgops.look import Look
import matplotlib as mpl
import matplotlib.colors as mcolors
from matplotlib import pyplot as plt
import matplotlib.figure
from matplotlib.lines import Line2D
import numpy as np

from asdf.format import perfectly_black_rectangular_solid
from asdf_settings.rapidlooks import ANNOTATION_FONT


def evaluate_membership(
    conditions: Sequence[Mapping],
    band_mapping: Mapping[str, np.ndarray],
    wave_mapping: Mapping[str, float],
) -> np.ndarray:
    relation_arrays = []
    for condition in conditions:
        spectop = getattr(spectops, condition["look"])
        images = [band_mapping[band] for band in condition["bands"]]
        wavelengths = [wave_mapping[band] for band in condition["bands"]]
        op_array = spectop(images, None, wavelengths)[0]
        relation_array = np.ones_like(op_array)
        relation_array[op_array > condition["range"][1]] = 0
        relation_array[op_array < condition["range"][0]] = 0
        relation_arrays.append(relation_array)
    # noinspection PyTypeChecker
    return reduce(np.multiply, relation_arrays)


def spectral_classifier(
    images,
    definitions: Mapping[str, Mapping],
    band_names: Sequence[str],
    wave_mapping: Mapping[str, float],
) -> dict[str, np.ndarray]:
    classes = {}
    band_mapping = {
        band_name: image for band_name, image in zip(band_names, images)
    }
    for name, definition in definitions.items():
        classes[name] = evaluate_membership(
            definition["conditions"], band_mapping, wave_mapping
        )
    # TODO: is making this a string array just asking for trouble? maybe just
    #  integers corresponding to each class in order?
    character_length = max(len(name) for name in definitions.keys())
    consolidated = np.full(
        list(classes.values())[0].shape, "", dtype=f"<U{character_length}"
    )
    # noinspection PyTypeChecker
    for name, array in reversed(classes.items()):
        consolidated[np.nonzero(array)] = name
    classes["all"] = consolidated
    return classes


def colorize_class_arrays(
    class_arrays: Mapping[str, np.ndarray], definitions: Mapping[str, Mapping]
) -> dict[str, np.ndarray]:
    cube = perfectly_black_rectangular_solid(
        list(class_arrays.values())[0].shape
    )
    cubes = {}
    for name, array in class_arrays.items():
        if name == "all":
            continue
        class_cube = cube.copy()
        class_color = mpl.colors.to_rgb(definitions[name]["color"])
        class_cube[np.nonzero(array)] = class_color
        cubes[name] = class_cube
    consolidated_cube = cube.copy()
    for name in class_arrays.keys():
        if name == "all":
            continue
        class_color = mpl.colors.to_rgb(definitions[name]["color"])
        consolidated_cube[class_arrays["all"] == name] = class_color
    cubes["all"] = consolidated_cube
    return cubes


def plot_spectral_classes(
    class_arrays: Mapping[str, np.ndarray],
    definitions: Mapping[str, Mapping],
    plot_all: bool = True,
) -> Sequence[matplotlib.figure.Figure]:
    full_legend = []
    for name, definition in definitions.items():
        full_legend.append(
            Line2D([0], [0], color=definition["color"], label=name)
        )
    fig, ax = plt.subplots()
    ax.imshow(class_arrays["all"])
    ax.legend(handles=full_legend, prop=ANNOTATION_FONT)
    figs = [fig]
    if plot_all is not True:
        return figs
    for name, array in class_arrays.items():
        if name == "all":
            continue
        fig, ax = plt.subplots()
        ax.imshow(array)
        legend = [
            Line2D([0], [0], color=definitions[name]["color"], label=name)
        ]
        ax.legend(handles=legend, prop=ANNOTATION_FONT)
        figs.append(fig)
    return figs


def spectral_classifier_look(
    images: Sequence[np.ndarray],
    definitions: Mapping[str, Mapping],
    band_names: Sequence[str],
    wave_mapping: Mapping[str, float],
) -> dict[str, np.ndarray]:
    spectral_classes = spectral_classifier(
        images, definitions, band_names, wave_mapping
    )
    return colorize_class_arrays(spectral_classes, definitions)


# TODO: this either gets rolled into make_look_set...or i decide that
# i want to stop writing special cases in make_look_set and instead
# dispatch to functions like these...idk
def make_classifier_look(
    definitions: Mapping[str, Mapping],
    observation: BandSet,
    crop: bool = True,
    prefilter: bool = None,
    plot: bool = True,
    armed=True,
    plot_all=True,
) -> Look:
    required_bands = set()
    for definition in definitions.values():
        for condition in definition["conditions"]:
            for band in condition["bands"]:
                required_bands.add(band)
    band_mapping = {
        band: observation.get_band(band) for band in required_bands
    }
    wave_mapping = {
        band: observation.wavelength(band)[0] for band in required_bands
    }
    params = {
        "definitions": definitions,
        "band_names": list(band_mapping.keys()),
        "wave_mapping": wave_mapping,
    }
    instruction = {"look": spectral_classifier_look, "params": params}
    if crop is True:
        instruction |= {"crop": (25, 25, 11, 11)}
    if prefilter is not None:
        instruction |= {"prefilter": prefilter}
    if plot is True:
        instruction |= {
            "plotter": {
                "function": plot_spectral_classes,
                "params": {"definitions": definitions, "plot_all": plot_all},
            }
        }
    classifier = Look.compile_from_instruction(instruction)
    if armed is True:
        classifier.execute = partial(classifier.execute, band_mapping.values())
    return classifier
