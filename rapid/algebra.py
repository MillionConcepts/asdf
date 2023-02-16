from functools import partial
from inspect import getfullargspec
from typing import Mapping, Sequence

from marslab import spectops
from marslab.bandset import BandSet
from marslab.imgops.look import Look
from matplotlib import pyplot as plt
from matplotlib.lines import Line2D
import matplotlib as mpl
import matplotlib.colors as mcolors
import matplotlib.figure
import numpy as np
import sympy as sp

from asdf.format import perfectly_black_rectangular_solid


def symbol_strings(expression):
    """
    returns dict of string:symbol for free symbols in sympy expression.
    this is useful for substituting into expressions that may not share
    a common symbol namespace.
    """
    return dict(
        zip(list(map(str, expression.free_symbols)), expression.free_symbols)
    )


def lambdify_expressions(expression_mapping):
    return {
        name: sp.lambdify(
            list(symbol_strings(expression).values()),
            expression,
            modules="numpy",
        )
        for name, expression in expression_mapping.items()
    }


def starmap_matching(function_mapping, object_mapping):
    # i consider a dictionary comprehension unreadable here
    evaluated_functions = {}
    for name, func in function_mapping.items():
        # TODO: this skips kwonlyargs, use inspect.signature
        relevant_objects = {
            name: obj
            for name, obj in object_mapping.items()
            if name in getfullargspec(func).args
        }
        evaluated_functions[name] = func(**relevant_objects)
    return evaluated_functions


def relevant_reflectance_values(observation, definitions):
    required_bands = set()
    for definition in definitions.values():
        for band in definition["bands"]:
            required_bands.add(band)
    bands = {band: observation.get_band(band) for band in required_bands}
    wavelengths = {
        band: observation.wavelength(band)[0] for band in required_bands
    }
    return bands, wavelengths


def evaluate_parameter(definition, images, wavelengths):
    spectop = getattr(spectops, definition["op"])
    reflectance = [images[band] for band in definition["bands"]]
    wavelengths = [wavelengths[band] for band in definition["bands"]]
    return spectop(reflectance, None, wavelengths)[0]


def evaluate_all_parameters(definitions, images, wavelengths):
    return {
        name: evaluate_parameter(definition, images, wavelengths)
        for name, definition in definitions.items()
    }


def evaluate_spectral_functions(
    functions, param_definitions, images, wavelengths
):
    parameters = evaluate_all_parameters(
        param_definitions, images, wavelengths
    )
    return starmap_matching(functions, parameters)


def classify_pixels(class_definitions, param_definitions, images, wavelengths):
    spectral_functions = lambdify_expressions(
        {
            name: sp.sympify(spectral_class["definition"])
            for name, spectral_class in class_definitions.items()
        }
    )
    classes = evaluate_spectral_functions(
        spectral_functions, param_definitions, images, wavelengths
    )
    character_length = max(len(name) for name in classes.keys())
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
    arrays: Mapping[str, np.ndarray],
    definitions: Mapping[str, Mapping],
    fontproperties,
    plot_all: bool = True,
) -> Sequence[matplotlib.figure.Figure]:
    full_legend = []
    for name, definition in definitions.items():
        full_legend.append(
            Line2D([0], [0], color=definition["color"], label=name)
        )
    fig, ax = plt.subplots()
    ax.imshow(arrays["all"])
    ax.legend(handles=full_legend, prop=fontproperties)
    figs = [fig]
    if plot_all is not True:
        return figs
    for name, array in arrays.items():
        if name == "all":
            continue
        fig, ax = plt.subplots()
        ax.imshow(array)
        legend = [
            Line2D([0], [0], color=definitions[name]["color"], label=name)
        ]
        ax.legend(handles=legend, prop=fontproperties)
        figs.append(fig)
    return figs


def spectral_classifier_look(
    images: Mapping[str, np.ndarray],
    band_names: Sequence[str],
    wavelengths: Mapping[str, float],
    class_definitions: Mapping[str, Mapping],
    param_definitions: Mapping[str, Mapping],
) -> dict[str, np.ndarray]:
    images = {
        band_name: image for band_name, image in zip(band_names, images)
    }
    spectral_classes = classify_pixels(
        class_definitions, param_definitions, images, wavelengths
    )

    return colorize_class_arrays(spectral_classes, class_definitions)


# TODO: this either gets rolled into make_look_set...or i decide that
# i want to stop writing special cases in make_look_set and instead
# dispatch to functions like these...idk
def make_classifier_look(
    observation: BandSet,
    class_definitions: Mapping[str, Mapping],
    param_definitions: Mapping[str, Mapping],
    fontproperties,
    crop: bool = True,
    prefilter: Mapping = None,
    plot: bool = True,
    plot_all=True,
    armed=True
) -> Look:
    images, wavelengths = relevant_reflectance_values(
        observation, param_definitions
    )
    params = {
        "band_names": list(images.keys()),
        "param_definitions": param_definitions,
        "class_definitions": class_definitions,
        "wavelengths": wavelengths,
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
                "params": {
                    "definitions": class_definitions,
                    "plot_all": plot_all,
                    "fontproperties": fontproperties,
                },
            }
        }
    classifier = Look.compile_from_instruction(instruction)
    if armed:
        classifier.execute = partial(classifier.execute, list(images.values()))
    return classifier
