"""
thread count specifications for various parts of the pipeline. the same
settings will not be optimal across environments.
"""

THREADS = {
    'save': 4,
    'look': 4,
    'upload': 3
}
