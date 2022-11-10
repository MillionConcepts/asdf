"""
thread count specifications for various parts of the pipeline. the same
settings will not be optimal across environments.
"""

THREADS = {
    'save': None,
    'look': None,
    'upload': 3
}
