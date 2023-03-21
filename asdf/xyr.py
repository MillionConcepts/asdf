from functools import partial
from pathlib import Path
import warnings

from astropy.io import fits
from cytoolz import groupby, valfilter, valmap
from dustgoggles.func import gmap
from marslab.geom import transform_angle, sph2cart
from marslab.imgops.imgutils import normalize_range, enhance_color
from marslab.imgops.pltutils import despine, remove_ticks, strip_axes
import matplotlib.font_manager as mplf
from matplotlib.lines import Line2D
from more_itertools import chunked, divide
import matplotlib.pyplot as plt
import matplotlib as mpl
import numpy as np
import pandas as pd
import pdr
from scipy.interpolate import griddata
from marslab.imgops.render import colormapped_plot

from asdf_settings.rapidlooks import FONT_PATH
from asdf.console import aprint

mpl.rcParams['image.cmap'] = 'Greys_r'  # necessary?
warnings.simplefilter('ignore', category=RuntimeWarning)  # i love dividing by zero


def open_attached(path):
    return pdr.open(path, label_fn=path, skip_existence_check=True)


def get_cahvore(data: pdr.Data, group="GEOMETRIC_CAMERA_MODEL"):
    block = data.metablock(group)
    components = {'reference_frame': block.get('REFERENCE_COORD_SYSTEM_NAME')}
    for comp_ix, id_ in enumerate(block["MODEL_COMPONENT_ID"]):
        components[id_] = np.array(block[f"MODEL_COMPONENT_{comp_ix + 1}"])
    components['az_fov'] = data.metaget('AZIMUTH_FOV')['value']
    components['el_fov'] = data.metaget('ELEVATION_FOV')['value']
    components['pix_w'] = data.metaget_('LINE_SAMPLES')
    components['pix_h'] = data.metaget_('LINES')
    return components


def derive_cahvore_properties(cahvore):
    for ax in ('H', 'V'):
        cahvore[f'{ax}_image'] = (
            cahvore[ax] - np.dot(cahvore['A'], cahvore[ax]) * cahvore['A']
        )
        cahvore[f'{ax}s'] = np.linalg.norm(np.cross(cahvore['A'], cahvore[ax]))
        cahvore[f'{ax}c'] = np.dot(cahvore['A'], cahvore[ax])
    cahvore['dpp_H'] = cahvore['az_fov'] / cahvore['pix_w']
    cahvore['dpp_V'] = cahvore['el_fov'] / cahvore['pix_h']
    for ax in ('H', 'V', 'A'):
        cahvore[f'{ax}u'] = cahvore[ax]/np.linalg.norm(cahvore[ax])
    return cahvore


def rough_valid_area(xyzmap, cahvor, slop = 0.8):
    relative_position_vecs = (xyzmap - cahvor['C'])
    rel_pos_mag = np.linalg.norm(relative_position_vecs, axis=2)
    rel_pos_u = np.einsum('ijk,ij->ijk', relative_position_vecs, 1 / rel_pos_mag)
    # plt.imshow(rel_pos_u)  # pretty!
    off_comp_h = np.dot(cahvor['Au'] - rel_pos_u, cahvor['Hu'])
    off_comp_v = np.dot(cahvor['Au'] - rel_pos_u, cahvor['Vu'])
    off_h_deg = np.abs(np.degrees(np.arcsin(off_comp_h)))
    off_v_deg = np.abs(np.degrees(np.arcsin(off_comp_v)))
    return np.nonzero(
        np.logical_and(
            off_h_deg < (cahvor['az_fov'] / (2 - slop)),
            off_v_deg < (cahvor['el_fov'] / (2 - slop))
        )
    )


def prune_xyzmap(xyzmap: np.ma.MaskedArray, cahvore: dict, slop: float=0.8):
    indices = rough_valid_area(xyzmap, cahvore, slop=slop)
    xyz = xyzmap[indices]
    assert not xyz.mask.any(), "invalid pixels have entered the xyzmap"
    return xyz.data, indices


def xyz2ij(xyz, cahvore):
    relative_positions = xyz - cahvore['C']
    omegas = np.dot(relative_positions, cahvore['O'])
    # component of rel pos vectors along omega axis
    w_omegas = np.einsum('ij,i->ij', np.array([cahvore['O'] for _ in omegas]), omegas)
    # subtract out radial distortion
    lambda3s = relative_positions - w_omegas
    # apply polynomial fit using coefficients defined in R component of model
    taus = np.einsum('ij,ij->i', lambda3s, lambda3s) / omegas ** 2
    r1, r2, r3 = cahvore['R']
    mus = r1 + r2 * taus + r3 * taus ** 2
    pps = np.einsum('ij,i->ij', lambda3s, mus) + xyz
    # fully substract out the radial distortion
    pp_cs = pps - cahvore['C']
    ppcs_dot_a = np.dot(pp_cs, cahvore['A'])
    ijvec = np.vstack(
        [
            np.dot(pp_cs, cahvore['H']) / ppcs_dot_a - 1,
            np.dot(pp_cs, cahvore['V']) / ppcs_dot_a - 1,
        ]
    ).T
    return np.round(ijvec).astype(np.int32)


def select_valid_pixels(ij, cahvore):
    validmask = (
        np.all(ij > 0, axis=1)
        & (ij[:, 0] <= cahvore['pix_w'] - 1)
        & (ij[:, 1] <= cahvore['pix_h'] - 1)
    )
    return np.nonzero(validmask)


def select_and_map_coordinates(xyzmap, target_cahvore):
    # optimization step
    xyz_candidates, indices = prune_xyzmap(xyzmap, target_cahvore)
    if xyz_candidates.size == 0:
        return {}
    ij_candidates = xyz2ij(xyz_candidates, target_cahvore)
    valid_index = select_valid_pixels(ij_candidates, target_cahvore)
    ij = ij_candidates[valid_index].T
    xyz = xyz_candidates[valid_index].T
    return {
        'i': ij[0],
        'j': ij[1],
        'x': xyz[0],
        'y': xyz[1],
        'z': xyz[2],
        'si': indices[1][valid_index],
        'sj': indices[0][valid_index]
    }


def make_incidence_map(uvw, img_data):
    sun_vector = sph2cart(*transform_angle('SITE', 'ROVER', 'SOLAR', img_data))
    sun_vector = sun_vector / np.linalg.norm(sun_vector)
    deflection = np.dot(
        np.einsum('ijk,ij->ijk', uvw, 1 / np.linalg.norm(uvw, axis=2)),
        sun_vector * -1
    )
    return np.degrees(np.arccos(deflection))


def make_rangemap(xyz, origin=(0, 0, 0)):
    return np.linalg.norm(xyz - origin, axis=-1)


def filter_navrec(navrec):
    if len(navrec['coords'].get('i', [])) == 0:
        return False
    return True


def pick_biggest_navrec(nav_recs):
    sizes = [
        len(rec['coords'].get('i', [])) for rec in nav_recs
    ]
    return nav_recs[np.argmax(sizes)]


def map_input_spatial_products(xyrs, iof_data, uvwdir, min_matched_pixels=1100):
    zc = derive_cahvore_properties(get_cahvore(iof_data))
    nav_recs = []
    for xyr_file in xyrs:
        xyr = open_attached(xyr_file)
        nxyz = np.moveaxis(xyr.get_scaled('IMAGE'), 0, 2)
        if not nxyz.any():
            continue
        nav_recs.append({'xyz': nxyz, 'fn': xyr.filename})
    for rec in nav_recs:
        rec['coords'] = select_and_map_coordinates(rec['xyz'], zc)
    nav_recs = tuple(filter(filter_navrec, nav_recs))
    if len(nav_recs) == 0:
        raise ValueError("no match between IOF and available XYRs.")
    # want a cutoff for pathological cases that are just going to map sketchy
    # data in the far corner of a navcam image -- probably like if it's under 1100 pixels,
    # don't use it
    rec = pick_biggest_navrec(nav_recs)
    if len(rec['coords']['i']) < min_matched_pixels:
        raise ValueError("Best matching XYR has < min_matched_pixels.")
    try:
        uvw_file = [
            f for f in uvwdir.iterdir()
            if f.name == Path(rec['fn']).name.replace('XYR', 'UVW')
        ][0]
        uvw_data = pdr.read(uvw_file)
        nuvw = np.moveaxis(uvw_data.get_scaled('IMAGE'), 0, 2)
        for ix, comp in enumerate(('u', 'v', 'w')):
            rec['coords'][comp] = nuvw[rec['coords']['sj'], rec['coords']['si'], ix]
        rec['uvw'], rec['uvw_path'] = nuvw, uvw_file
    except (FileNotFoundError, IndexError):
        warnings.warn("no surface normals file available.")
        rec['uvw'], rec['uvw_path'] = None, None
    return rec, zc


def prep_scalebar_inputs(iof_data, xyzm, cahvore):
    axes = {'j': {}, 'i': {}}
    axes['j']['valid'], axes['i']['valid'] = np.nonzero(~xyzm[:, :, 0].mask)
    for ax, rec in axes.items():
        rec['unique'] = np.unique(rec['valid'])
    axes['j']['pix'] = cahvore['pix_h']
    axes['i']['pix'] = cahvore['pix_w']
    image = normalize_range(iof_data.get_scaled('IMAGE'), (0, 1), 0.1)
    sb_props = {
        "bar_font": mplf.FontProperties(
            fname=Path(FONT_PATH, "FiraMono-Medium.ttf"),
            size=12,
            ),
        "bar_color": (0.2, 0.85, 0.95),
        "hor_j_margin": int(axes['j']['pix'] / 12),
        "vert_j_margin": int(axes['j']['pix'] / 20),
        "vert_i_margin": int(axes['i']['pix'] / 20),
        "hor_i_margin": int(axes['i']['pix'] / 3),
        "n_hor_bars": 6,
        "n_vert_bars": 3,
        "vert_bar_padding": 40,
        "i_window_size": int(axes['i']['pix'] / 10),
        "j_window_size": int(axes['i']['pix'] / 20),
        "hor_text_standoff": 13,
        "vert_text_standoff": 18
        }
    return axes, sb_props


def draw_scalebars(axes, image, xyzm, sb_props):
    j_bar_pos, i_distances = compute_horizontal_scalebars(
        xyzm,
        axes['j']['unique'],
        axes['i']['pix'],
        axes['j']['pix'],
        sb_props
    )
    fig, ax = plt.subplots()
    ax.imshow(image / 2, vmax=1)
    for bar_pos, distance in zip(j_bar_pos, i_distances):
        draw_horizontal_scalebar(
            ax, bar_pos, distance, axes['i']['pix'], sb_props
        )
    for side in ('left', 'right',):
        result = compute_vertical_scalebars(
            xyzm,
            axes['i']['unique'],
            axes['j']['unique'],
            axes['i']['pix'],
            sb_props,
            side,
        )
        j_bar_pos, i_bar_pos, j_distances, bar_length, vcx = result
        for pos, distance in zip(j_bar_pos, j_distances):
            draw_vertical_scalebar(
                ax, pos, i_bar_pos, distance, bar_length, sb_props, side
            )
        despine(ax)
        remove_ticks(ax)
    return fig, ax


def draw_rangemap(maps, iof_data):
    image = normalize_range(iof_data.get_scaled('IMAGE'), (0, 1), 1)
    alpha = 0.6
    image_rgb = np.dstack(
        [image] * 3 + [np.full_like(image, alpha)]
    )
    rangemap = colormapped_plot(
        maps['range'],
        layers=[image_rgb],
        cmap='plasma',
        render_colorbar=True,
        drop_mask=False,
        n_ticks=5
    )
    return rangemap


def draw_range_contours(maps, cahvore, origin='center'):
    xyzm = np.ma.dstack([maps['x'], maps['y'], maps['z']])
    xyzm[xyzm.mask] = np.nan
    if origin == 'center':
        origin = cahvore['C']
    elif origin == 'boresight':
        origin = xyzm[int(cahvore['Vc']), int(cahvore['Hc'])]
    rangemap = make_rangemap(xyzm, origin)
    plt.style.use('dark_background')
    rclip = np.clip(
        rangemap,
        *np.percentile(rangemap[np.isfinite(rangemap)], (0, 99))
    )
    fig, ax = plt.subplots()
    contours = ax.contour(
        np.arange(rclip.shape[1]),
        np.arange(rclip.shape[0]),
        np.flip(rclip, axis=0),
        levels=34,
        linewidths=2,
        cmap='plasma'
    )
    despine(ax)
    remove_ticks(ax)
    plt.colorbar(contours)
    return fig


def make_spatial_maps(coords, iof_data, cahvore):
    # make coordinate mesh
    axes = list(
        filter(lambda a: a in coords, ('x', 'y', 'z', 'u', 'v', 'w', 'si', 'sj'))
    )
    maps = {}
    ji = coords['j'], coords['i']
    iof_shape = gmap(iof_data.metaget_, ('LINES', 'LINE_SAMPLES'))
    for ax in axes:
        mesharray = np.zeros(iof_shape, np.float32)
        mesharray[ji] = coords[ax]
        maps[ax] = mesharray
    for original in ('si', 'sj'):
        mesharray = np.full(iof_shape, 0, np.int32)
        mesharray[ji] = coords[original]
        maps[original] = mesharray
    # make mask of grid positions and arrays of missing positions.
    # we use this to select points to interpolate, and we can also
    # later use this mask to get the original meshes (because the interpolated
    # products retain the original values at those points.)
    maps['meshmask'] = np.full(iof_shape, False)
    maps['meshmask'][ji] = True
    missing_ji = np.nonzero(~maps['meshmask'])
    # interpolate coordinate mesh per axis
    for ax in axes:
        values = maps[ax][ji]
        if not values[np.isfinite(values)].any():
            continue
        interpolated = griddata(ji, values, missing_ji, method='linear')
        gridarray = np.empty(iof_shape, np.float32)
        gridarray[ji] = values
        gridarray[missing_ji] = interpolated
        # just overwrite the 'mesh' values
        maps[ax] = gridarray
    maps['imask'] = ~np.isfinite(maps['x'])
    # make zcam rangemap from xyzmap
    maps['range'] = make_rangemap(
        np.dstack([maps['x'], maps['y'], maps['z']]), cahvore['C']
    ).astype('f4')
    try:
        # make zcam incidence angle map from interpolated uvwmap
        maps['incidence'] = make_incidence_map(
            np.dstack([maps['u'], maps['v'], maps['w']]), iof_data
        ).astype('f4')
    except KeyError:
        # or not
        warnings.warn("no normals available for this region.")
    return maps


def write_space_fits_file(maps, navrec, iof_data, bandset, outpath: Path):
    primary = fits.PrimaryHDU()
    bandset.format_metadata()
    primary.header['IN_XYR'] = Path(navrec['fn']).name
    if navrec['uvw_path'] is not None:
        primary.header['IN_UVW'] = navrec['uvw_path'].name
    else:
        primary.header['IN_UVW'] = None
    primary.header['REF_IOF'] = Path(iof_data.filename).name
    for field in (
        'SOL', 'SITE', 'DRIVE', 'SEQ_ID', 'CTIME', 'ZOOM', 'LTST', 'RSM'
    ):
        primary.header[field] = bandset.summary[field]
    hdus = [primary]
    constructor = partial(fits.CompImageHDU, quantize_method=2)
    #     constructor = fits.ImageHDU
    for ax, im in maps.items():
        if ax in ("meshmask", "imask"):
            # FITS doesn't have a bool dtype
            savearray = im.astype(np.uint8)
        else:
            savearray = im.copy()
            savearray[~np.isfinite(savearray)] = 0
        hdus.append(constructor(savearray, name=ax))
    hdul = fits.HDUList(hdus)
    outpath.mkdir(exist_ok=True, parents=True)
    eye = Path(iof_data.filename).name[1]
    outfile = Path(outpath, f"space_{eye}_{bandset.name}.fits")
    hdul.writeto(outfile, overwrite=True)
    return outfile


def read_space_fits(path):
    hdul = fits.open(path)
    arrays = {}
    info = hdul.info(output=False)[1:]
    imask_info = next(filter(lambda i: i[1].lower() == "imask", info))
    arrays['imask'] = hdul[imask_info[0]].data.astype(bool)
    for hdu_info in info:
        if (name := hdu_info[1].lower()) == 'imask':
            continue
        array = hdul[hdu_info[0]].data
        if name == 'meshmask':
            arrays[name] = array.astype(bool)
        else:
            arrays[name] = np.ma.masked_array(array, arrays['imask'])
        del array
    return arrays


def make_area_array(maps):
    xyz = np.ma.dstack([maps[ax] for ax in ('x', 'y', 'z')])
    pos_vec_arrays = {
        'ud': np.diff(xyz, axis=0, prepend=xyz[0:1, :, :]),
        'du': np.diff(xyz, axis=0, append=xyz[-2:-1, :, :]),
        'lr': np.diff(xyz, axis=1, prepend=xyz[:, 0:1, :]),
        'rl': np.diff(xyz, axis=1, append=xyz[:, -2:-1, :])
    }
    distance_arrays = valmap(
        lambda a: np.linalg.norm(a, axis=2), pos_vec_arrays
    )
    return (sum(distance_arrays.values()) / 4) ** 2


def draw_area_map(image, area, bounds=(0, 90)):
    """function is not used in main code, but left in for testing purposes"""
    fig, ax = plt.subplots()
    scaled = np.clip(area, *np.percentile(area[np.isfinite(area)], bounds))
    image_rgb = np.dstack([image / 2] * 3 + [np.full_like(image, 0.5)])
    rangemap = colormapped_plot(
        scaled,
        layers=[image_rgb],
        cmap='plasma',
        render_colorbar=True,
        drop_mask=False,
        n_ticks=5
    )
    return fig


def roi_rect(roi, xyz):
    j, i = np.nonzero(roi.data)
    jmin, jmax = np.min(j), np.max(j)
    imin, imax = np.min(i), np.max(i)
    center_i, center_j = int((imin + imax) / 2), int((jmin + jmax) / 2)
    jvec = xyz[jmin, center_i] - xyz[jmax, center_i]
    ivec = xyz[center_j, imin] - xyz[center_j, imax]
    return np.linalg.norm(jvec), np.linalg.norm(ivec)


def compute_roi_dims(rois, xyz, area):
    recs = []
    for name, roi in rois.items():
        color = name.split(" ")[0].lower()
        h, w = roi_rect(roi, xyz)
        rec = {
            'COLOR': color,
            'H': h,
            'W': w,
            'HW': h * w,
            'A': area[np.nonzero(roi.data)].sum()
        }
        recs.append(rec)
    return recs


def compute_horizontal_scalebars(
        xyzm, valid_j, ipix, jpix, sb_props, windowed_distances=True
):
    # TODO: valid_i is not used, was it supposed to be? If not, it should be removed and
    #  signatures updated
    """
    compute image positions and world distances for horizontal
    bars spaced along the j (y) axis, giving distances
    along the i (x) axis
    """
    j_bar_pos = np.linspace(
        sb_props["hor_j_margin"], jpix - sb_props["hor_j_margin"], sb_props["n_hor_bars"]
    ).astype(np.int16)
    j_bar_pos = [
        valid_j[np.abs(valid_j - j_bar_pos[i]).argmin()]
        for i, _ in enumerate(j_bar_pos)
    ]
    i_distances = []
    for bar_pos in j_bar_pos:
        row = xyzm[bar_pos]
        valid_row_ix = np.nonzero(~row.mask.all(axis=1))[0]
        start, stop = valid_row_ix[0], valid_row_ix[-1]
        distance_ratio = (stop - start) / ipix
        if windowed_distances is False:
            distance = np.linalg.norm(row[stop] - row[start])
        else:
            windows = tuple(chunked(valid_row_ix, sb_props["i_window_size"]))
            row_distances = []
            for window in windows:
                row_distances.append(
                    np.linalg.norm(row[
                                       window[0]] - row[window[-1]])
                )
            distance = sum(row_distances)
        i_distances.append(distance / distance_ratio)
    return j_bar_pos, i_distances


def compute_vertical_scalebars(
        xyzm, valid_i, valid_j, ipix, sb_props, side='left'
):
    # TODO: jpix is not used, was it supposed to be? If not, it should be removed and
    #  signatures updated
    """
    compute image positions and world distances for vertical+
    bars spaced along the j (y) axis, giving distances
    along the j (y) axis
    """
    bar_length = (
                         (valid_j.max() - valid_j.min())
                         - 2 * sb_props["vert_j_margin"]
                         - sb_props["vert_bar_padding"] * sb_props["n_vert_bars"]
                 ) / sb_props["n_vert_bars"]
    j_bar_pos = [
        valid_j.min()
        + sb_props["vert_j_margin"]
        + i * sb_props["vert_bar_padding"]
        + i * bar_length
        + sb_props["vert_bar_padding"] / 2
        for i in range(sb_props["n_vert_bars"])
    ]
    if side == 'left':
        i_bar_pos = sb_props["vert_i_margin"]
    else:
        i_bar_pos = ipix - sb_props["vert_i_margin"]
    real_i_bar_pos = [valid_i[np.abs(valid_i - i_bar_pos).argmin()]]
    col = xyzm[:, real_i_bar_pos]
    valid_col_ix = np.unique(np.nonzero(~col.mask.all(axis=1))[0])
    j_distances = []
    for pos in j_bar_pos:
        start_ix = np.argmin(np.abs(valid_col_ix - pos))
        stop_ix = np.argmin(np.abs(valid_col_ix - (pos + bar_length)))
        start = valid_col_ix[start_ix]
        stop = valid_col_ix[stop_ix]
        distance_ratio = (stop_ix - start_ix) / bar_length
        distance = np.linalg.norm(
            xyzm[start, real_i_bar_pos] - xyzm[stop, real_i_bar_pos]
        )
        j_distances.append(distance / distance_ratio)
    return j_bar_pos, i_bar_pos, j_distances, bar_length, valid_col_ix


def lformat(length, digits=1):
    if length < 1:
        length, units = length * 100, "cm"
    else:
        units = "m"
    return f"{str(round(length, digits))}{units}"


def draw_horizontal_scalebar(ax, bar_pos, distance, ipix, sb_props):
    distance_ratio = (ipix - 2 * sb_props["hor_i_margin"]) / ipix
    line = Line2D(
        [sb_props["hor_i_margin"], ipix - sb_props["hor_i_margin"]],
        [bar_pos, bar_pos],
        marker='|',
        markersize=15,
        markeredgewidth=3,
        lw=3,
        c=sb_props["bar_color"]
    )
    ax.add_artist(line)
    ax.annotate(
        lformat(distance * distance_ratio),
        (int(ipix / 2), bar_pos - sb_props["hor_text_standoff"]),
        ha='center',
        fontproperties=sb_props["bar_font"],
        color=sb_props["bar_color"]
    )
    return ax


def draw_vertical_scalebar(
        ax, j_bar_pos, i_bar_pos, distance, bar_length, sb_props, side='left'
):
    line = Line2D(
        [i_bar_pos, i_bar_pos],
        [j_bar_pos, j_bar_pos + bar_length],
        marker='_',
        markersize=15,
        markeredgewidth=3,
        lw=3,
        c=sb_props["bar_color"]
    )
    ax.add_artist(line)
    if side == 'left':
        standoff = sb_props["vert_text_standoff"]
    else:
        # ??
        standoff = -5 * sb_props["vert_text_standoff"]
    ax.annotate(
        lformat(distance),
        (i_bar_pos + standoff, j_bar_pos + bar_length / 2),
        va='center',
        fontproperties=sb_props["bar_font"],
        color=sb_props["bar_color"],
        rotation=90
    )
    return ax


def draw_incidence_map(incidence):
    fig, ax = plt.subplots()
    imap = ax.imshow(incidence)
    plt.colorbar(imap)
    despine(ax)
    remove_ticks(ax)
    return fig


def no_spatial_data():
    aprint(
        f"[bold dark orange]No reduced spatial products available, skipping "
        f"spatial processing."
    )


def no_ncam_match():
    aprint(
        f"[bold dark orange]No NCAM XYRs loaded, skipping "
        f"reduced spatial product generation."
    )


# TODO: feedback about product generation
# TODO: turn these into Looks to dynamically control product generation
def make_spatial_products(
    bandset,
    outpath=".",
    ref_bands=("L1", "R1"),
    write_images=True,
    calc_rois=True,
    dpi=340
):
    if write_images is True:
        bandset.load(ref_bands)
        bandset.bulk_debayer(ref_bands)
    dims = {}
    for ref_band in ref_bands:
        try:
            maps = read_space_fits(
                Path(outpath, f"data/space_{ref_band[0]}_{bandset.name}.fits")
            )
        except FileNotFoundError:
            # TODO, maybe: check the other eye anyway? This would be important
            #  in a case with only right-eye data, but we should ideally handle
            #  that by modifying the ref_bands argument.
            return no_spatial_data()
        eye = {'L': 'LEFT', 'R': 'RIGHT'}[ref_band[0]]
        xyzm = np.ma.dstack([maps['x'], maps['y'], maps['z']])
        if calc_rois and bandset.rois:
            maps['area'] = make_area_array(maps)
            rois = {r.name: r for r in bandset.rois if r.name.endswith(eye)}
            roi_dims = pd.DataFrame(compute_roi_dims(rois, xyzm, maps['area']))
            roi_dims.columns = [
                c if c == 'COLOR' else f"{eye}_{c}" for c in roi_dims.columns
            ]
            dims[eye] = roi_dims
        if write_images is False:
            continue
        iof_data = bandset.fetch_precached(ref_band)
        cahvore = derive_cahvore_properties(get_cahvore(iof_data))
        image = normalize_range(bandset.get_band(ref_band), (0, 1), 0.1)
        axes, sb_props = prep_scalebar_inputs(iof_data, xyzm, cahvore)
        scalefig, scaleax = draw_scalebars(axes, image, xyzm, sb_props)
        rangefig = draw_rangemap(maps, iof_data)
        center_contour = draw_range_contours(maps, cahvore)
        boresight_contour = draw_range_contours(maps, cahvore, 'boresight')
        eyepre = eye.lower()[0]
        browsepath = Path(outpath, "browse")
        browsepath.mkdir(exist_ok=True, parents=True)
        if "incidence" not in maps.keys():
            aprint(
                f"[bold dark orange]Missing data; skipping photometry maps."
            )
        else:
            ifig = draw_incidence_map(maps['incidence'])
            ifig.tight_layout()
            ifig.savefig(
                browsepath / f"incidence_{eyepre}_{bandset.name}.png", dpi=dpi
            )
        for fig in (scalefig, rangefig, center_contour, boresight_contour):
            fig.tight_layout()
        scalefig.savefig(
            browsepath / f"scalebar_{eyepre}_{bandset.name}.png", dpi=dpi
        )
        rangefig.savefig(
            browsepath / f"rangemap_{eyepre}_{bandset.name}.png", dpi=dpi
        )
        center_contour.savefig(
            browsepath / f"camera_contour_{eyepre}_{bandset.name}.png", dpi=dpi
        )
        boresight_contour.savefig(
            browsepath / f"boresight_contour_{eyepre}_{bandset.name}.png",
            dpi=dpi
        )
        plt.close('all')
    if dims != {}:
        dims = pd.merge(*tuple(dims.values()), on='COLOR')
    return dims


def make_space_fits(bandset, ref_bands, outpath):
    if bandset.xyrs is None:
        return no_ncam_match()
    uvwdir = bandset.xyrs[0].parents[1] / 'nuvw'
    outfiles = []
    for ref_band in ref_bands:
        iof_data = bandset.fetch_precached(ref_band)
        navrec, cahvore = map_input_spatial_products(
            bandset.xyrs, iof_data, uvwdir
        )
        maps = make_spatial_maps(navrec['coords'], iof_data, cahvore)
        outfile = write_space_fits_file(
            maps, navrec, iof_data, bandset, Path(outpath, "data")
        )
        outfiles.append(outfile)
    return outfiles
