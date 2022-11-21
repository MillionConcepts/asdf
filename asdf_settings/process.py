"""
thread count specifications for various parts of the pipeline. the same
settings will not be optimal across environments.
"""

THREADS = {
    'save': 5,
    'look': 5,
    'upload': 3
}
