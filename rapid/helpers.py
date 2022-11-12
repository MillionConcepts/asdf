import warnings

import numpy as np
from rasterio.errors import NotGeoreferencedWarning

from asdf.scan import find_obs_metamaps, cluster_observations, scan_zcam_files
from asdf.zcam_bandset import ZcamBandSet

warnings.filterwarnings("ignore", category=NotGeoreferencedWarning)
np.seterr(divide="ignore", invalid="ignore")


def get_zcam_bandset(
    image_path,
    roi_path=None,
    rsm=None,
    seq_id=None,
    observation_ix=0,
    use_pixmaps=True,
    keep_caltarget=False,
    use_errmaps=True,
    load=True
):
    observations = scan_zcam_files(image_path)
    if seq_id is not None:
        observations = observations.loc[
            observations['SEQ_ID'].str.lower().str.contains(str(seq_id).lower())
        ]
    clusters = cluster_observations(
        observations, keep_caltarget=keep_caltarget
    )[0]
    if rsm is not None:
        clusters = {k: v for k, v in clusters.items() if rsm in v['RSM'].tolist()}
    observation = list(clusters.values())[observation_ix]
    zband = ZcamBandSet(observation)
    if use_pixmaps is True:
        pixes = find_obs_metamaps(zband.metadata["PATH"], code="pix_map")[0]
        if pixes:
            zband.associate_metamaps(pixes, code='pix_map')
            zband.load_metamaps(code="pix_map")
    if use_errmaps is True:
        errors = find_obs_metamaps(zband.metadata["PATH"], code="iof_err")[0]
        if errors:
            zband.associate_metamaps(errors, code='iof_err')
            zband.load_metamaps(code="iof_err")
    if load is True:
        zband.load("all")
        zband.bulk_debayer("all")
    if roi_path is not None:
        zband.rois = roi_path
        zband.load_rois()
        zband.count_rois()
    if (roi_path is not None) and (use_pixmaps is True):
        zband.count_pixmaps()
    zband.format_metadata()
    return zband
