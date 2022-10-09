
# def make_heatmap_looks(looks, defaults, settings):
#     rainbow_looks = []
#     for look in looks:
#         if look["look"] not in SPECTOP_NAMES:
#             continue
#         new_look = deepcopy(look)
#         new_look |= defaults
#         new_look["name"] = "{look} {bands} heatmap"
#         new_look.pop("plotter")
#         # noinspection PyTypeChecker
#         new_look["overlay"] = settings | {"band": look["bands"][0]}
#         rainbow_looks.append(new_look)
#     return rainbow_looks
#
#
# def make_dcs_looks(looks, defaults, settings):
#     new_looks = []
#     for look in looks:
#         if look["look"] != "dcs":
#             continue
#         if "R6" in look["bands"]:
#             continue
#         new_look = deepcopy(look)
#         new_look |= defaults
#         new_look["name"] = "invariant dcs {bands}"
#         new_look["params"] = new_look["params"] | settings
#         new_looks.append(new_look)
#     return new_looks
#
#
# def make_accent_looks(looks, defaults, settings):
#     new_looks = []
#     for look in looks:
#         if look["look"] not in SPECTOP_NAMES:
#             continue
#         new_look = deepcopy(look)
#         new_look |= defaults
#         if "name" in settings.keys():
#             new_look["name"] = settings["name"]
#         else:
#             new_look["name"] = "{look} {bands} accent"
#         new_look.pop("plotter")
#         # noinspection PyTypeChecker
#         new_look["overlay"] = settings | {"band": look["bands"][0]}
#         new_looks.append(new_look)
#     return new_looks