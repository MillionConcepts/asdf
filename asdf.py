"""user-facing asdf CLI script"""

from clize import run


# tell clize to handle command line call
if __name__ == "__main__":
    import asdf.cli_endpoint
    run(asdf.cli_endpoint.asdf_initiate)
