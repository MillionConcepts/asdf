"""user-facing asdf CLI script"""

from clize import run

from asdf.console import ASDF_CONSOLE, ASDFLOG, ASDF_RPH

# tell clize to handle command line call
if __name__ == "__main__":
    with ASDF_CONSOLE.status("... initializing ...", spinner="star"):
        import time
        import asdf.cli
        import logging
        from marslab.imgops.bandset import log as bandlog
        for log in (bandlog, ASDFLOG):
            log.setLevel(logging.INFO)
            log.addHandler(ASDF_RPH)
    run(asdf.cli.asdf_hello)
