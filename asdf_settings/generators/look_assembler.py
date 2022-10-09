from copy import deepcopy
from typing import Mapping

from marslab.spectops import SPECTOP_NAMES

from .. import rapidlooks
from ..rapidlooks import CATEGORIES, CROP_SETTINGS, LOOK_GENERATORS


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


def glom_instruction(inst, part):
    inst = part | inst
    for k in part.keys():
        if not isinstance(part[k], Mapping):
            continue
        if k == "params":
            inst["params"] = inst.get("params", {}) | part[k]
            continue
        if (new_params := part[k].get("params")) is None:
            continue
        inst[k]["params"] = inst[k].get("params", {}) | new_params
    return inst


def edit_looks(looks, defaults, settings, look_filter):
    new_looks = []
    for look in looks:
        if not look_filter(look):
            continue
        new_look = defaults | deepcopy(look)
        if "suffix" in settings.keys():
            new_look["name"] = f"{new_look['name']} {settings['suffix']}"
        new_looks.append(glom_instruction(new_look, settings))
    return new_looks


def make_modified_bandmap_looks(looks, defaults, settings):
    return edit_looks(
        looks, defaults, settings, lambda l: l['look'] in SPECTOP_NAMES
    )


def make_modified_stretchy_looks(looks, defaults, settings):
    return edit_looks(
        looks, defaults, settings, lambda l: l['look'] == 'dcs'
    )


GENERATED_LOOK_DISPATCH = {
    "bandmap": make_recolored_bandmap_looks,
    "modified_bandmap": make_modified_bandmap_looks,
    "modified_stretchy": make_modified_stretchy_looks
}

# assemble explicitly-defined looks from individual definitions
# + defaults
RAPIDLOOKS = []
for category in CATEGORIES:
    cat_looks = getattr(rapidlooks, category)
    cat_defaults = getattr(rapidlooks, category + "_DEFAULTS")
    for cat_look in cat_looks:
        instruction = cat_defaults | cat_look
        RAPIDLOOKS.append(instruction)


GENERATED_INSTRUCTIONS = []

# assemble procedurally generated looks
for category, look_listing in LOOK_GENERATORS.items():
    assembly_function = GENERATED_LOOK_DISPATCH[category]
    category_defaults = getattr(rapidlooks, category.upper() + "_DEFAULTS")
    for gen_look in look_listing:
        GENERATED_INSTRUCTIONS += assembly_function(
            RAPIDLOOKS, category_defaults, gen_look
        )
    RAPIDLOOKS += GENERATED_INSTRUCTIONS


for look_inst in RAPIDLOOKS:
    # add crop settings
    look_inst |= CROP_SETTINGS
    # insert band names, cmap names, op names as required
    look_inst["name"] = insert_name_elements(look_inst)
# deepcopy everything to ensure that later mutation
# does not result in undesirably shared state
RAPIDLOOKS = [deepcopy(look_inst) for look_inst in RAPIDLOOKS]
