"""
settings backend module. assembles groups of similar looks to reduce excessive
wordiness in asdf_settings.rapidlooks
"""
from collections import defaultdict
from copy import deepcopy
from typing import Mapping, Optional, Collection, Callable

from marslab.imgops.look import LookInstruction
from marslab.spectops import SPECTOP_NAMES

from .. import rapidlooks
from ..rapidlooks import CATEGORIES, CROP_SETTINGS, LOOK_GENERATORS


def insert_name_elements(look_instruction: LookInstruction) -> Optional[str]:
    """
    Formats name codes that distinguish members of a group of similar looks --
    the same spectop for different bands, for instance -- and inserts them
    into a look instruction.
    """
    if look_instruction.get("name") is None:
        return
    substitutions = []
    name = look_instruction["name"]
    if "{look}" in name:
        substitutions.append(("{look}", look_instruction.get("look")))
    if "{bands}" in name:
        bands = look_instruction.get("bands")
        if isinstance(look_instruction.get("look"), str):
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


def make_recolored_bandmap_looks(
    bandmap_looks: Collection[LookInstruction], _, cmap: str
) -> list[LookInstruction]:
    """
    Takes a group of bandmap look instructions and generates a group of look
    instructions that make the same bandmap but with a different colormap.
    """
    recolored_bandmaps = []
    for look in bandmap_looks:
        if look["look"] not in SPECTOP_NAMES:
            continue
        recolored_bandmap = deepcopy(look)
        recolored_bandmap["name"] += " {cmap}"

        # noinspection PyTypeChecker
        recolored_bandmap["plotter"]["params"]["cmap"] = cmap
        recolored_bandmaps.append(recolored_bandmap)
    return recolored_bandmaps


# noinspection PyTypedDict
def glom_instruction(inst: LookInstruction, part: Mapping) -> LookInstruction:
    """
    Copies a look instruction and merges a partial look instruction into it.
     """
    new = defaultdict(dict, deepcopy(inst))
    for k in part.keys():
        if not isinstance(part[k], Mapping):
            new[k] = part[k]
            continue
        new[k] |= deepcopy(part[k])
        if (new_inst := part[k].get("instructions")) is not None:
            if k not in inst.keys():
                new[k]["instructions"] = new_inst
            else:
                old = inst[k].get("instructions", []).copy()
                new[k]["instructions"] = old + new_inst
        if k == "params":
            new["params"] = inst.get("params", {}) | part[k]
            continue
        if (new_params := part[k].get("params")) is None:
            continue
        if k not in inst.keys():
            new[k]["params"] = new_params
        else:
            new[k]["params"] = inst[k].get("params", {}) | new_params
    return dict(new)


def edit_looks(
    looks: Collection[LookInstruction],
    defaults: dict,
    settings: Mapping,
    look_filter: Callable[[LookInstruction], bool]
) -> list[LookInstruction]:
    """
    Makes a new version of a group of (possibly incomplete) look instructions,
    building them from `defaults` (which the instructions may overwrite), the
    instructions themselves, and `settings` (which may overwrite
    `defaults` | `instructions`). Ignores any looks that do not match the
    predicate function `look_filter`.
    """
    new_looks = []
    for look in looks:
        if not look_filter(look):
            continue
        new_look = defaults | deepcopy(look)
        if "suffix" in settings.keys():
            new_look["name"] = f"{new_look['name']} {settings['suffix']}"
        new_looks.append(glom_instruction(new_look, settings))
    return new_looks


def make_modified_bandmap_looks(
    looks: Collection[LookInstruction], defaults: dict, settings: dict
) -> list[LookInstruction]:
    """
    Makes edited copies of any 'bandmap' looks in a passed collection of looks.
    """
    return edit_looks(
        looks, defaults, settings, lambda l: l['look'] in SPECTOP_NAMES
    )


def make_modified_stretchy_looks(
    looks: Collection[LookInstruction], defaults: dict, settings: dict
) -> list[LookInstruction]:
    """Makes edited copies of any DCS looks in a passed collection of looks."""
    return edit_looks(
        looks, defaults, settings, lambda l: l['look'] == 'dcs'
    )


GENERATED_LOOK_DISPATCH = {
    "bandmap": make_recolored_bandmap_looks,
    "modified_bandmap": make_modified_bandmap_looks,
    "modified_stretchy": make_modified_stretchy_looks
}
"""mapping of look instruction group names to aggregated generator functions."""

# assemble explicitly-defined looks from individual definitions
# + defaults
RAPIDLOOKS = []
for category in CATEGORIES:
    cat_looks = getattr(rapidlooks, category)
    cat_defaults = getattr(rapidlooks, category + "_DEFAULTS")
    for cat_look in cat_looks:
        instruction = cat_defaults | cat_look
        RAPIDLOOKS.append(instruction)


# assemble procedurally generated looks
# TODO, maybe: something to selectively let generators
#  recursively build on one another
generated_instructions = []
for category, look_listing in LOOK_GENERATORS.items():
    assembly_function = GENERATED_LOOK_DISPATCH[category]
    category_defaults = getattr(rapidlooks, category.upper() + "_DEFAULTS")
    for gen_look in look_listing:
        generated_instructions += assembly_function(
            RAPIDLOOKS, category_defaults, gen_look
        )
RAPIDLOOKS += generated_instructions

for look_inst in RAPIDLOOKS:
    # add crop settings
    look_inst |= CROP_SETTINGS
    # insert band names, cmap names, op names as required
    look_inst["name"] = insert_name_elements(look_inst)
# deepcopy everything to ensure that later mutation
# does not result in undesirably shared state
RAPIDLOOKS: list[LookInstruction] = [
    deepcopy(r) for r in sorted(RAPIDLOOKS, key=lambda i: i['name'])
]
"""
Final assembled list of look instructions to be compiled into Look objects 
during execution of the primary application (see asdf.format.compile_looks).
"""
