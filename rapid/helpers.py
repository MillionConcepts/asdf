import warnings

import numpy as np
from rasterio.errors import NotGeoreferencedWarning

from asdf.scan import find_obs_pixmaps, cluster_observations, scan_zcam_files
from asdf.zcam_bandset import ZcamBandSet

warnings.filterwarnings("ignore", category=NotGeoreferencedWarning)
np.seterr(divide='ignore', invalid='ignore')


def get_zcam_bandset(image_path, roi_path=None, use_pixmaps=True):
    observations = scan_zcam_files(image_path)
    observation = list(cluster_observations(observations)[0].values())[0]
    zband = ZcamBandSet(observation)
    if use_pixmaps is True:
        pixes = find_obs_pixmaps(zband.metadata['PATH'])[0]
        zband.associate_pixmaps(pixes)
        zband.load_pixmaps()
    zband.load('all')
    zband.bulk_debayer('all')
    if roi_path is not None:
        zband.rois = roi_path
        zband.load_rois()
        zband.count_rois()
    if (roi_path is not None) and (use_pixmaps is True):
        zband.count_pixmaps()
    zband.format_metadata()
    return zband


