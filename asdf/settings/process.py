"""
thread count specifications for various parts of the pipeline. the same
settings will not be optimal across environments.

Notes on this:

If we do start using threading for a bunch of closures, we will have to move
to pathos and assess incurred performance hits (if any) -- although maybe
just dill would do the job?
"""

THREADS = {
    'save': 8
}