import json
import re
import zipfile
from io import BytesIO
from pathlib import Path

import numpy as np
import pandas as pd
from PIL import Image

from asdf.parse import parse_zcam_fn


def parse_dtm_fn(dtm_fn):
    """parse the provip-created dtm filenames"""
    dtm_fn = Path(dtm_fn)
    parsed = parse_zcam_fn(f'{dtm_fn.name[:54]}.IMG')
    for k in ['VERSION', 'PRODUCT_TYPE', 'PRODUCER', 'PATH']:
        parsed[f'SOURCE_{k}'] = parsed.pop(k)
    parsed['EYE'] = parsed['FILTER'][0]
    parts = re.split(r'[_.]', dtm_fn.name)
    parsed['DTM_FRAME_TYPE}'] = parts[6]
    parsed['PRODUCT_TYPE'] = parts[7]
    parsed['NUMBER'] = parts[8]
    parsed['FILE_TYPE'] = parts[9]
    parsed['FILE_NAME'] = dtm_fn.name
    parsed['PATH'] = str(dtm_fn)
    parsed['STEM'] = dtm_fn.stem
    return parsed


def parse_dtm_zip_fn(dtm_zip_fn):
    """parse the provip-created ZIP archive filenames"""
    parts = re.split(r'[-_.]', Path(dtm_zip_fn).name)
    return {
        'SOL': int(parts[1]),
        'SEQ_ID': f'zcam0{parts[2]}',
        'ZOOM': int(parts[3]),
        '???': parts[4],
        'PTYPE': parts[5],
        'NUMBER': parts[6],
        'PATH': dtm_zip_fn
    }


def scan_dtm_zipfile(archive):
    if not isinstance(archive, zipfile.ZipFile):
        archive = zipfile.ZipFile(archive)
    return [
        parse_dtm_fn(info.filename) for info in archive.filelist
    ]


DTM_IMAGE_RECORD_FIELDS = {
    'RMC': (
        'rover_motion_counter_pds3',
        lambda rmc_rec: tuple(v for v in rmc_rec.values())
    ),
    'RSM': ('rover_motion_counter_pds3', lambda rmc_rec: rmc_rec['rsm']),
    'SOL': 'planet_day_number',
    'SEQ_ID': ('sequence_id', str.upper),
    'PAN': 'pan',
    'TILT': 'tilt',
    'MD5': 'file_md5'
}


def parse_dtm_image_rec(image_rec):
    parsed = {}
    for field, spec in DTM_IMAGE_RECORD_FIELDS.items():
        try:
            if isinstance(spec, str):
                parsed[field] = image_rec[spec]
            else:
                parsed[field] = spec[1](image_rec[spec[0]])
        except KeyError:
            parsed[field] = None
    return parsed


# TODO, maybe: parse processing info
def parse_dtm_label(label_json, stem=None):
    """
    parse source file information from a dtm file's detached JSON label
    """
    label = json.loads(label_json)
    source_recs = []
    for image_rec in label['input_images']:
        rec = parse_dtm_image_rec(image_rec)
        source_files = image_rec['original_source_files']
        rec['SOURCE_FILE_NAMES'], rec['SOURCE_MD5'] = [], []
        for source_file in source_files:
            rec['SOURCE_FILE_NAMES'].append(source_file['file_name'])
            rec['SOURCE_MD5'].append(source_file['file_md5'])
        rec['STEM'] = stem
        source_recs.append(rec)
    return source_recs


def open_dtm_zipfile(dtm_zip_path):
    with zipfile.ZipFile(dtm_zip_path) as archive:
        metadata = pd.DataFrame(scan_dtm_zipfile(archive))
        dtm_files = {
            path: archive.read(path) for path in metadata['PATH']
        }
        stems = metadata['STEM'].unique()
        source_metadata = []
        for stem in stems:
            parsed = parse_dtm_label(
                dtm_files[f'{stem}.json'], stem
            )
            metadata.loc[
                metadata['STEM'] == stem, 'RSM'
            ] = min({rec['RSM'] for rec in parsed})
            source_metadata += parsed
        metadata['RSM'] = metadata['RSM'].astype(int)
        metadata['ARCHIVE_PATH'] = str(dtm_zip_path)
        return dtm_files, metadata, pd.DataFrame(source_metadata)


def load_rangemap_from_bytes(dtm_bytes):
    dtm_buffer = BytesIO(dtm_bytes)
    dtm = np.asarray(Image.open(dtm_buffer))
    # special constant in rangemaps appears to be -99999
    return np.ma.masked_where(dtm == -99999, dtm)
