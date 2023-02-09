from functools import partial

import pandas as pd
import pdr
from pdr.formats import generic_image_properties

from asdf.parse import parse_pointing
from marslab.bandset import BandSet
from marslab.compat.xcam import DERIVED_CAM_DICT
from marslab.imgops.loaders import pdr_load


def read_zcam_mosaic(self, object_name):
    """pdr.Data.read_image variant for missing metadata in mosaic labels"""
    image_block = self.metablock("IMAGE")
    image_block['BAND_STORAGE_TYPE'] = "BAND_SEQUENTIAL"
    return pdr.Data.read_image(
        self,
        object_name,
        special_properties=generic_image_properties("IMAGE", image_block, self)
    )


def setup_zcam_mosaic_bandset_metadata(metadata):
    if "FILTER" in metadata.columns:
        metadata["BAND"] = metadata["FILTER"]
        metadata.drop("FILTER", axis=1)
    metadata["IX"] = 0
    metadata.index = metadata["BAND"]
    bayer_filter_rows = []
    # mosaics are of course always debayered, so add references to the fact
    # that the L0/R0 images are 3-band
    for eye in ("L", "R"):
        if eye + "0" not in metadata.index:
            continue
        eye_row = metadata.loc[eye + "0"]
        for color, ix in zip(("R", "G", "B"), (0, 1, 2)):
            eye_color_row = eye_row.copy()
            eye_color_row["BAND"] = eye + "0" + color
            eye_color_row["IX"] = ix
            eye_color_row.name = eye + "0" + color
            bayer_filter_rows.append(eye_color_row)
        metadata = metadata.drop(eye_row.name)
    if bayer_filter_rows:
        metadata = pd.concat(
            (metadata, pd.concat(bayer_filter_rows, axis=1).T)
        )
    metadata["WAVELENGTH"] = pd.Series(DERIVED_CAM_DICT["ZCAM"]["filters"])[
        metadata["BAND"]
    ]
    return metadata.reset_index(drop=True)


class ZcamMosaicBandSet(BandSet):
    def __init__(self, files, threads=None):
        super().__init__(
            metadata=files, load_method=pdr_load, threads=threads
        )
        self.metadata = setup_zcam_mosaic_bandset_metadata(files)
        for path in self.metadata["PATH"].unique():
            data = pdr.Data(
                path, label_fn=path, skip_existence_check=True
            )
            data.read_image = partial(read_zcam_mosaic, data)
            self.precached[path] = data
        name_row = files.iloc[0]
        name_fields = [
            "SOL" + str(name_row["SOL"]).zfill(4), name_row["SEQ_ID"]
        ]
        self.name = "_".join(name_fields) + "_mosaic"


