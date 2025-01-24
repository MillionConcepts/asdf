"""user-facing noninteractive pretty_plot utility"""
import sys


# tell fire to handle command line call
if __name__ == '__main__':
    try:
        import fire
    except ImportError:
        print(
            "'fire' package not found. Did you "
            "forget to activate a virtual environment?"
        )
        sys.exit(1)

    from pretty_plot.cli import do_pplot

    fire.Fire(do_pplot)
