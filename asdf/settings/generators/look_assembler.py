from copy import deepcopy

from marslab.spectops import SPECTOP_NAMES

import asdf.settings.rapidlooks
from asdf.settings.rapidlooks import (
    CATEGORIES,
    CROP_SETTINGS,
    LOOK_GENERATORS,
)


def insert_name_elements(look_instruction):
    if look_instruction.get("name") is None:
        return
    substitutions = []
    name = look_instruction["name"]
    if "{look}" in name:
        substitutions.append(("{look}", look_instruction.get("look")))
    if "{bands}" in name:
        bands = look_instruction.get("bands")
        if "band_depth" in look_instruction.get("look"):
            bands = [bands[0], bands[2], bands[1]]
        substitutions.append(("{bands}", "_".join(bands)))
    if "{cmap}" in name:
        substitutions.append(
            ("{cmap}", str(look_instruction["plotter"]["params"].get("cmap")))
        )
    for sub in substitutions:
        name = name.replace(*sub)
    return name


def make_recolored_bandmap_looks(looks, _, cmap: str):
    recolored_bandmaps = []
    for look in looks:
        if look["look"] not in SPECTOP_NAMES:
            continue
        recolored_bandmap = deepcopy(look)
        recolored_bandmap["name"] = "{look} {bands} {cmap}"

        # noinspection PyTypeChecker
        recolored_bandmap["plotter"]["params"]["cmap"] = cmap
        recolored_bandmaps.append(recolored_bandmap)
    return recolored_bandmaps


def make_heatmap_looks(looks, defaults, settings):
    rainbow_looks = []
    for look in looks:
        if look["look"] not in SPECTOP_NAMES:
            continue
        new_look = deepcopy(look)
        new_look |= defaults
        new_look["name"] = "{look} {bands} heatmap"
        new_look.pop("plotter")
        # noinspection PyTypeChecker
        new_look["overlay"] = settings | {"band": look["bands"][0]}
        rainbow_looks.append(new_look)
    return rainbow_looks


def make_dcs_looks(looks, defaults, settings):
    new_looks = []
    for look in looks:
        if look["look"] != "dcs":
            continue
        if "R6" in look["bands"]:
            continue
        new_look = deepcopy(look)
        new_look |= defaults
        new_look["name"] = "invariant dcs {bands}"

        new_look["params"] = new_look["params"] | settings
        new_looks.append(new_look)
    return new_looks


def make_accent_looks(looks, defaults, settings):
    new_looks = []
    for look in looks:
        if look["look"] not in SPECTOP_NAMES:
            continue
        new_look = deepcopy(look)
        new_look |= defaults
        new_look["name"] = "{look} {bands} accent"

        new_look.pop("plotter")
        # noinspection PyTypeChecker
        new_look["overlay"] = settings | {"band": look["bands"][0]}
        new_looks.append(new_look)
    return new_looks


GENERATED_LOOK_DISPATCH = {
    "accent": make_accent_looks,
    "heatmap": make_heatmap_looks,
    "bandmap": make_recolored_bandmap_looks,
    "stretchy": make_dcs_looks,
}

# assemble explicitly-defined looks from individual definitions
# + defaults
ASSEMBLED_INSTRUCTIONS = []
for category in CATEGORIES:
    cat_looks = getattr(asdf.settings.rapidlooks, category)
    cat_defaults = getattr(asdf.settings.rapidlooks, category + "_DEFAULTS")
    for cat_look in cat_looks:
        instruction = cat_defaults | cat_look
        ASSEMBLED_INSTRUCTIONS.append(instruction)


GENERATED_INSTRUCTIONS = []

# assemble procedurally generated looks
for category, look_listing in LOOK_GENERATORS.items():
    assembly_function = GENERATED_LOOK_DISPATCH[category]
    category_defaults = getattr(
        asdf.settings.rapidlooks, category.upper() + "_DEFAULTS"
    )
    for gen_look in look_listing:
        GENERATED_INSTRUCTIONS += assembly_function(
            ASSEMBLED_INSTRUCTIONS, category_defaults, gen_look
        )


RAPIDLOOKS = ASSEMBLED_INSTRUCTIONS + GENERATED_INSTRUCTIONS
for look_inst in RAPIDLOOKS:
    # add crop settings
    look_inst |= CROP_SETTINGS
    # insert band names, cmap names, op names as required
    look_inst["name"] = insert_name_elements(look_inst)
