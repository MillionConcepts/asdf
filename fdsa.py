"""user-facing fdsa CLI script"""

import fire


# tell fire to handle command line call
if __name__ == "__main__":
    import asdf.cli_endpoint
    fire.Fire(asdf.cli_endpoint.fdsa_initiate)
