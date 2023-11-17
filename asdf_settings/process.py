"""
thread count specifications for various parts of the pipeline. the same
settings will not be optimal across environments.
"""

THREADS = {
    'save': None,
    'look': None,
    'upload': 4,
    'mosaic_gen': 6,
    'mosaic_save': None,
    'mosaic_look': None
}
