"""generic utility-type functions for asdf"""
import gc
import string
import random
from collections import Mapping
from typing import Sequence

import numpy as np
from matplotlib.figure import Figure
import matplotlib.pyplot as plt


def pass_parameters(func, *args, **kwargs):
    return func(*args, **kwargs)


def catch_interaction(noninteractive, func, *args, **kwargs):
    if noninteractive:
        return "-"
    return func(*args, **kwargs)


def obfuscated_name():
    return "".join(random.choices(string.ascii_letters + string.digits, k=26))


def itemize_numpy(obj):
    """
    convert objects of numpy dtypes to python scalars. in this context,
    primarily for json serialization.
    """
    if isinstance(obj, np.generic):
        return obj.item()
    return obj


def close_fig(thing):
    if isinstance(thing, Figure):
        plt.close(thing)


def absolutely_destroy(thing):
    if isinstance(thing, Mapping):
        keys = list(thing.keys())
        for key in keys:
            del(thing[key])
    elif isinstance(thing, Sequence):
        for _ in thing:
            del _
    else:
        del thing
    plt.close('all')
    gc.collect()
