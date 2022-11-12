from asdf.cli_endpoint import asdf_initiate, fdsa_initiate

# from pdr_tests.utilz.dev_utilz import Stopwatch

# watch = Stopwatch()

# LG_delta_HG_280 RSM 340 -- QA issue
fdsa_initiate(
    f'/datascratch/zcam_data/fdsa_hopper/',
    f'/datascratch/zcam_data/products/',
    debug=True,
    marslab_regex='.*SOL0213.*',
    skip_rapidlooks=True,
    skip_pixmaps=True,
    upload=False,
    do_empties="False"
)

# warnings.filterwarnings('error', '.*partition.*')
# watch.click()
# asdf_initiate(
#    '/datascratch/zcam_data/products/0106/iof/',
#    '/datascratch/zcam_data/fdsa_hopper/0106/zcam03153 Hastaa_1of3 RSM 286/data/roi_SOL0106_zcam03153_RSM286.fits.gz',
#    noninteractive=True,
#    # noninteractive_all=True,
#    recursive=False,
#    debug=True,
#    upload=False,
#    skip_pixmaps=True,
#    skip_rapidlooks=True,
#    keep_caltarget=False,
#    keep_broadband=False,
#    # image_regex=".*IOF.*03148.*",
#    #
#    # upload=True
# )
# watch.click()
