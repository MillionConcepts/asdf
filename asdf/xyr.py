import warnings
from collections import defaultdict
from functools import partial
from itertools import product
from pathlib import Path

import matplotlib as mpl
import matplotlib.font_manager as mplf
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import pdr
from astropy.io import fits
from cytoolz import valmap
from dustgoggles.func import gmap
from matplotlib.lines import Line2D
from more_itertools import chunked
from scipy.interpolate import griddata

from asdf.console import aprint
from asdf_settings.rapidlooks import FONT_PATH
from marslab.geom import transform_angle, sph2cart
from marslab.imgops.imgutils import normalize_range
from marslab.imgops.pltutils import despine, remove_ticks, dpi_from_image
from marslab.imgops.render import colormapped_plot

warnings.simplefilter(
    "ignore", category=RuntimeWarning
)  # i love dividing by zero


def open_attached(path):
    return pdr.open(path, label_fn=path, skip_existence_check=True)


def get_cahvore(data: pdr.Data, group="GEOMETRIC_CAMERA_MODEL"):
    block = data.metablock(group)
    components = {"reference_frame": block.get("REFERENCE_COORD_SYSTEM_NAME")}
    for comp_ix, id_ in enumerate(block["MODEL_COMPONENT_ID"]):
        components[id_] = np.array(block[f"MODEL_COMPONENT_{comp_ix + 1}"])
    components["az_fov"] = data.metaget("AZIMUTH_FOV")["value"]
    components["el_fov"] = data.metaget("ELEVATION_FOV")["value"]
    components["pix_w"] = data.metaget_("LINE_SAMPLES")
    components["pix_h"] = data.metaget_("LINES")
    return components


def derive_cahvore_properties(cahvore):
    for ax in ("H", "V"):
        cahvore[f"{ax}_image"] = (
            cahvore[ax] - np.dot(cahvore["A"], cahvore[ax]) * cahvore["A"]
        )
        cahvore[f"{ax}s"] = np.linalg.norm(np.cross(cahvore["A"], cahvore[ax]))
        cahvore[f"{ax}c"] = np.dot(cahvore["A"], cahvore[ax])
    cahvore["dpp_H"] = cahvore["az_fov"] / cahvore["pix_w"]
    cahvore["dpp_V"] = cahvore["el_fov"] / cahvore["pix_h"]
    for ax in ("H", "V", "A"):
        cahvore[f"{ax}u"] = cahvore[ax] / np.linalg.norm(cahvore[ax])
    return cahvore


def rough_valid_area(xyzmap, cahvor, slop=0.8):
    relative_position_vecs = xyzmap - cahvor["C"]
    rel_pos_mag = np.linalg.norm(relative_position_vecs, axis=2)
    rel_pos_u = np.einsum(
        "ijk,ij->ijk", relative_position_vecs, 1 / rel_pos_mag
    )
    # plt.imshow(rel_pos_u)  # pretty!
    off_comp_h = np.dot(cahvor["Au"] - rel_pos_u, cahvor["Hu"])
    off_comp_v = np.dot(cahvor["Au"] - rel_pos_u, cahvor["Vu"])
    off_h_deg = np.abs(np.degrees(np.arcsin(off_comp_h)))
    off_v_deg = np.abs(np.degrees(np.arcsin(off_comp_v)))
    return np.nonzero(
        np.logical_and(
            off_h_deg < (cahvor["az_fov"] / (2 - slop)),
            off_v_deg < (cahvor["el_fov"] / (2 - slop)),
        )
    )


def prune_xyzmap(xyzmap: np.ma.MaskedArray, cahvore: dict, slop: float = 0.8):
    indices = rough_valid_area(xyzmap, cahvore, slop=slop)
    xyz = xyzmap[indices]
    assert not xyz.mask.any(), "invalid pixels have entered the xyzmap"
    return xyz.data, indices


def xyz2ij(xyz, cahvore):
    relative_positions = xyz - cahvore["C"]
    omegas = np.dot(relative_positions, cahvore["O"])
    # component of rel pos vectors along omega axis
    w_omegas = np.einsum(
        "ij,i->ij", np.array([cahvore["O"] for _ in omegas]), omegas
    )
    # subtract out radial distortion
    lambda3s = relative_positions - w_omegas
    # apply polynomial fit using coefficients defined in R component of model
    taus = np.einsum("ij,ij->i", lambda3s, lambda3s) / omegas ** 2
    r1, r2, r3 = cahvore["R"]
    mus = r1 + r2 * taus + r3 * taus ** 2
    pps = np.einsum("ij,i->ij", lambda3s, mus) + xyz
    # fully substract out the radial distortion
    pp_cs = pps - cahvore["C"]
    ppcs_dot_a = np.dot(pp_cs, cahvore["A"])
    ijvec = np.vstack(
        [
            np.dot(pp_cs, cahvore["H"]) / ppcs_dot_a - 1,
            np.dot(pp_cs, cahvore["V"]) / ppcs_dot_a - 1,
        ]
    ).T
    return np.round(ijvec).astype(np.int32)


def select_valid_pixels(ij, cahvore):
    validmask = (
        np.all(ij > 0, axis=1)
        & (ij[:, 0] <= cahvore["pix_w"] - 1)
        & (ij[:, 1] <= cahvore["pix_h"] - 1)
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
        "i": ij[0],
        "j": ij[1],
        "x": xyz[0],
        "y": xyz[1],
        "z": xyz[2],
        "si": indices[1][valid_index],
        "sj": indices[0][valid_index],
    }


def make_incidence_map(uvw, img_data):
    sun_vector = sph2cart(*transform_angle("SITE", "ROVER", "SOLAR", img_data))
    sun_vector = sun_vector / np.linalg.norm(sun_vector)
    deflection = np.dot(
        np.einsum("ijk,ij->ijk", uvw, 1 / np.linalg.norm(uvw, axis=2)),
        sun_vector * -1,
    )
    return np.degrees(np.arccos(deflection))


def make_rangemap(xyz, origin=(0, 0, 0)):
    return np.linalg.norm(xyz - origin, axis=-1)


def filter_navrec(navrec):
    if len(navrec["coords"].get("i", [])) == 0:
        return False
    return True


def pick_biggest_navrec(nav_recs):
    sizes = [len(rec["coords"].get("i", [])) for rec in nav_recs]
    return nav_recs[np.argmax(sizes)]


# TODO: better feedback (progress bars, etc.)
def map_input_spatial_products(xyrs, iof_datas, uvwdir, min_pixel_match=1100):
    nav_recs = []
    aprint(f"loading {len(xyrs)} candidate XYR files")
    for xyr_file in xyrs:
        xyr = open_attached(xyr_file)
        nxyz = np.moveaxis(xyr.get_scaled("IMAGE"), 0, 2)
        aprint(f"loaded {xyr_file.name}")
        if not nxyz.any():
            del xyr.IMAGE
            continue
        nav_recs.append({"xyz": nxyz, "fn": xyr.filename})
    coords = defaultdict(list)
    zcs = {}
    aprint(f"{len(nav_recs)} / {len(xyrs)} contain data")
    for rec, band in product(nav_recs, iof_datas.keys()):
        zc = derive_cahvore_properties(get_cahvore(iof_datas[band]))
        coords[band].append(
            rec | {"coords": select_and_map_coordinates(rec["xyz"], zc)}
        )
        zcs[band] = zc
        aprint(f"mapped {Path(rec['fn']).name} to {band}")
    outrecs = {}
    for band in iof_datas.keys():
        recs = tuple(filter(filter_navrec, coords[band]))
        del coords[band]
        if len(recs) == 0:
            raise ValueError("no match between IOF and available XYRs.")
        # want a cutoff for pathological cases that are just going to map
        # sketchy data in the far corner of a navcam image -- probably like if
        # it's under 1100 pixels, don't use it
        rec = pick_biggest_navrec(recs)
        aprint(f"selected {Path(rec['fn']).name} for {band}")
        del recs
        if len(rec["coords"]["i"]) < min_pixel_match:
            raise ValueError("Best matching XYR has < min_pixel_match.")
        # TODO: make this simultaneous-across-eyes as well (when possible)
        try:
            uvw_file = [
                f
                for f in uvwdir.iterdir()
                if f.name == Path(rec["fn"]).name.replace("XYR", "UVW")
            ][0]
            uvw_data = pdr.read(uvw_file)
            nuvw = np.moveaxis(uvw_data.get_scaled("IMAGE"), 0, 2)
            for ix, comp in enumerate(("u", "v", "w")):
                rec["coords"][comp] = nuvw[
                    rec["coords"]["sj"], rec["coords"]["si"], ix
                ]
                rec["uvw"], rec["uvw_path"] = nuvw, uvw_file
        except (FileNotFoundError, IndexError):
            aprint(f"[bold dark_orange]no UVW file for {Path(rec['fn']).name}")
            rec["uvw"], rec["uvw_path"] = None, None
        outrecs[band] = rec
    return outrecs, zcs


BAR_FONT = mplf.FontProperties(
    fname=Path(FONT_PATH, "FiraMono-Medium.ttf"),
    size=12,
)


def prep_scalebar_inputs(xyzm, cahvore):
    axes = {"j": {}, "i": {}}
    min_cover = 0.7
    # 1, 0 axis order because we are _summing along_ that axis
    for axname, ax in zip(("j", "i"), (1, 0)):
        axes[axname]["valid"] = np.nonzero(
            ((~xyzm[:, :, 0].mask).sum(axis=ax) / xyzm.shape[ax]) > min_cover
        )[0]
    axes["j"]["pix"] = cahvore["pix_h"]
    axes["i"]["pix"] = cahvore["pix_w"]
    sb_props = {
        "bar_font": BAR_FONT,
        "bar_color": (0.2, 0.85, 0.95),
        "hor_j_margin": int(axes["j"]["pix"] / 12),
        "vert_j_margin": int(axes["j"]["pix"] / 20),
        "vert_i_margin": int(axes["i"]["pix"] / 20),
        "hor_i_margin": int(axes["i"]["pix"] / 3),
        "n_hor_bars": 6,
        "n_vert_bars": 3,
        "vert_bar_padding": 40,
        "i_window_size": int(axes["i"]["pix"] / 10),
        "j_window_size": int(axes["i"]["pix"] / 20),
        "hor_text_standoff": 13,
        "vert_text_standoff": 18,
        "maxpad_i": 75,
        "maxpad_j": 40
    }
    return axes, sb_props


def draw_scalebars(axes, image, xyzm, sb_props):
    fig, ax = plt.subplots()
    ax.imshow(image / 2, vmax=1)
    j_bar_pos, i_distances = compute_horizontal_scalebars(xyzm, axes, sb_props)
    for bar_pos, distance in zip(j_bar_pos, i_distances):
        draw_horizontal_scalebar(
            ax, bar_pos, distance, axes["i"]["pix"], sb_props
        )
    for side in ("left", "right"):
        result = compute_vertical_scalebars(xyzm, axes, sb_props, side)
        j_bar_pos, i_bar_pos, j_distances, bar_length, vcx = result
        if j_bar_pos is None:
            continue
        for pos, distance in zip(j_bar_pos, j_distances):
            draw_vertical_scalebar(
                ax, pos, i_bar_pos, distance, bar_length, sb_props, side
            )
    despine(ax)
    remove_ticks(ax)
    return fig


def draw_rangemap(maps, iof_data):
    image = normalize_range(iof_data.get_scaled("IMAGE"), (0, 1), 1)
    alpha = 0.6
    image_rgb = np.dstack([image] * 3 + [np.full_like(image, alpha)])
    rangemap = colormapped_plot(
        maps["range"],
        layers=[image_rgb],
        cmap="plasma",
        render_colorbar=True,
        drop_mask=False,
        n_ticks=5,
    )
    return rangemap


class CoverageError(IndexError):
    pass


def draw_range_contours(maps, cahvore, origin="center"):
    xyzm = np.ma.dstack([maps["x"], maps["y"], maps["z"]])
    xyzm[xyzm.mask] = np.nan
    if origin == "center":
        origin = cahvore["C"]
    elif origin == "boresight":
        origin = xyzm[int(cahvore["Vc"]), int(cahvore["Hc"])]
    if np.isnan(origin).any():
        raise CoverageError("No spatial data for requested rangemap origin.")
    rangemap = make_rangemap(xyzm, origin)
    plt.style.use("dark_background")
    rclip = np.clip(
        rangemap, *np.percentile(rangemap[np.isfinite(rangemap)], (0, 99))
    )
    fig, ax = plt.subplots()
    contours = ax.contour(
        np.arange(rclip.shape[1]),
        np.arange(rclip.shape[0]),
        np.flip(rclip, axis=0),
        levels=34,
        linewidths=2,
        cmap="plasma",
    )
    despine(ax)
    remove_ticks(ax)
    plt.colorbar(contours)
    plt.style.use('default')
    return fig


def make_spatial_maps(coords, iof_data, cahvore):
    # make coordinate mesh
    axnames = ("x", "y", "z", "u", "v", "w", "si", "sj")
    axes = list(filter(lambda a: a in coords, axnames))
    maps = {}
    ji = coords["j"], coords["i"]
    iof_shape = gmap(iof_data.metaget_, ("LINES", "LINE_SAMPLES"))
    for ax in axes:
        mesharray = np.zeros(iof_shape, np.float32)
        mesharray[ji] = coords[ax]
        maps[ax] = mesharray
    for original in ("si", "sj"):
        mesharray = np.full(iof_shape, 0, np.int32)
        mesharray[ji] = coords[original]
        maps[original] = mesharray
    # make mask of grid positions and arrays of missing positions.
    # we use this to select points to interpolate, and we can also
    # later use this mask to get the original meshes (because the interpolated
    # products retain the original values at those points.)
    maps["meshmask"] = np.full(iof_shape, False)
    maps["meshmask"][ji] = True
    missing_ji = np.nonzero(~maps["meshmask"])
    # interpolate coordinate mesh per axis
    for ax in axes:
        values = maps[ax][ji]
        if not values[np.isfinite(values)].any():
            continue
        interpolated = griddata(ji, values, missing_ji, method="linear")
        gridarray = np.empty(iof_shape, np.float32)
        gridarray[ji] = values
        gridarray[missing_ji] = interpolated
        # just overwrite the 'mesh' values
        maps[ax] = gridarray
    maps["imask"] = ~np.isfinite(maps["x"])
    # make zcam rangemap from xyzmap
    maps["range"] = make_rangemap(
        np.dstack([maps["x"], maps["y"], maps["z"]]), cahvore["C"]
    ).astype("f4")
    try:
        # make zcam incidence angle map from interpolated uvwmap
        maps["incidence"] = make_incidence_map(
            np.dstack([maps["u"], maps["v"], maps["w"]]), iof_data
        ).astype("f4")
    except KeyError:
        # or not
        aprint(f"[bold dark_orange] no normals available for this region.")
    return maps


def write_space_fits_file(maps, navrec, iof_data, bandset, outpath: Path):
    primary = fits.PrimaryHDU()
    bandset.format_metadata()
    primary.header["IN_XYR"] = Path(navrec["fn"]).name
    if navrec["uvw_path"] is not None:
        primary.header["IN_UVW"] = navrec["uvw_path"].name
    else:
        primary.header["IN_UVW"] = None
    primary.header["REF_IOF"] = Path(iof_data.filename).name
    refs = ("SOL", "SITE", "DRIVE", "SEQ_ID", "CTIME", "ZOOM", "LTST", "RSM")
    for field in refs:
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
    arrays["imask"] = hdul[imask_info[0]].data.astype(bool)
    for hdu_info in info:
        if (name := hdu_info[1].lower()) == "imask":
            continue
        array = hdul[hdu_info[0]].data
        if name == "meshmask":
            arrays[name] = array.astype(bool)
        else:
            arrays[name] = np.ma.masked_array(array, arrays["imask"])
        del array
    return arrays


def make_area_array(maps):
    xyz = np.ma.dstack([maps[ax] for ax in ("x", "y", "z")])
    pos_vec_arrays = {
        "ud": np.diff(xyz, axis=0, prepend=xyz[0:1, :, :]),
        "du": np.diff(xyz, axis=0, append=xyz[-2:-1, :, :]),
        "lr": np.diff(xyz, axis=1, prepend=xyz[:, 0:1, :]),
        "rl": np.diff(xyz, axis=1, append=xyz[:, -2:-1, :]),
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
    return fig, colormapped_plot(
        scaled,
        layers=[image_rgb],
        cmap="plasma",
        render_colorbar=True,
        drop_mask=False,
        n_ticks=5,
    )


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
            "COLOR": color,
            "H": h,
            "W": w,
            "HW": h * w,
            "A": area[np.nonzero(roi.data)].sum(),
        }
        recs.append(rec)
    return recs


def compute_horizontal_scalebars(xyzm, axes, sb_props, window_distance=True):
    """
    compute image positions and world distances for horizontal bars spaced
    along the j (y) axis, giving distances along the i (x) axis
    """
    if len(axes["j"]["valid"]) == 0:
        return [], []
    j_bar_pos = np.linspace(
        sb_props["hor_j_margin"],
        axes["j"]["pix"] - sb_props["hor_j_margin"],
        sb_props["n_hor_bars"],
    ).astype(np.int16)
    real_j_bar_pos, output_j_bar_pos = [], []
    for pos in j_bar_pos:
        real_pos = axes["j"]["valid"][
            np.abs(axes["j"]["valid"] - pos).argmin()
        ]
        if np.abs(pos - real_pos) > sb_props["maxpad_j"]:
            continue
        if real_pos in real_j_bar_pos:
            continue
        real_j_bar_pos.append(real_pos)
        output_j_bar_pos.append(pos)
    i_distances = []
    for pos in real_j_bar_pos:
        row = xyzm[pos]
        valid_row_ix = np.nonzero(~row.mask.all(axis=1))[0]
        start, stop = valid_row_ix[0], valid_row_ix[-1]
        distance_ratio = (stop - start) / axes["i"]["pix"]
        if window_distance is False:
            distance = np.linalg.norm(row[stop] - row[start])
        else:
            windows = tuple(chunked(valid_row_ix, sb_props["i_window_size"]))
            row_distances = []
            for window in windows:
                row_distances.append(
                    np.linalg.norm(row[window[0]] - row[window[-1]])
                )
            distance = sum(row_distances)
        i_distances.append(distance / distance_ratio)
    return output_j_bar_pos, i_distances


def compute_vertical_scalebars(xyzm, axes, sb_props, side="left"):
    """
    compute image positions and world distances for vertical bars spaced along
    the j (y) axis, giving distances along the j (y) axis
    """
    if len(axes['i']['valid']) == 0:
        return None, None, None, None, None
    if side == "left":
        i_bar_pos = sb_props["vert_i_margin"]
    else:
        i_bar_pos = axes["i"]["pix"] - sb_props["vert_i_margin"]
    real_i_bar_pos = axes["i"]["valid"][
        np.abs((axes["i"]["valid"] - i_bar_pos)).argmin()
    ]
    if np.abs(real_i_bar_pos - i_bar_pos) > sb_props["maxpad_i"]:
        return None, None, None, None, None
    valid_j = np.nonzero(~xyzm[:, :, 0][:, real_i_bar_pos].mask)[0]
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
        marker="|",
        markersize=15,
        markeredgewidth=3,
        lw=3,
        c=sb_props["bar_color"],
    )
    ax.add_artist(line)
    ax.annotate(
        lformat(distance * distance_ratio),
        (int(ipix / 2), bar_pos - sb_props["hor_text_standoff"]),
        ha="center",
        fontproperties=sb_props["bar_font"],
        color=sb_props["bar_color"],
    )
    return ax


def draw_vertical_scalebar(
    ax, j_bar_pos, i_bar_pos, distance, bar_length, sb_props, side="left"
):
    line = Line2D(
        [i_bar_pos, i_bar_pos],
        [j_bar_pos, j_bar_pos + bar_length],
        marker="_",
        markersize=15,
        markeredgewidth=3,
        lw=3,
        c=sb_props["bar_color"],
    )
    ax.add_artist(line)
    if side == "left":
        standoff = sb_props["vert_text_standoff"]
    else:
        # ??
        standoff = -5 * sb_props["vert_text_standoff"]
    ax.annotate(
        lformat(distance),
        (i_bar_pos + standoff, j_bar_pos + bar_length / 2),
        va="center",
        fontproperties=sb_props["bar_font"],
        color=sb_props["bar_color"],
        rotation=90,
    )
    return ax


def draw_incidence_map(incidence):
    fig, ax = plt.subplots()
    imap = ax.imshow(incidence, cmap='Greys_r')
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


# TODO: more feedback about product generation
# TODO: turn figure funcs into Looks to dynamically control product generation
def make_spatial_products(
    bandset,
    outpath=".",
    ref_bands=("L1", "R1"),
    write_images=True,
    calc_rois=True,
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
            # TODO, maybe: check the other eye anyway? This would be
            #  especially important in a case with only right-eye data,
            #  (but we should really handle that with the ref_bands argument).
            return no_spatial_data()
        eye = {"L": "LEFT", "R": "RIGHT"}[ref_band[0]]
        xyzm = np.ma.dstack([maps["x"], maps["y"], maps["z"]])
        if calc_rois and bandset.rois:
            # TODO, maybe: generate this along with space fits files instead?
            maps["area"] = make_area_array(maps)
            rois = {r.name: r for r in bandset.rois if r.name.endswith(eye)}
            roi_dims = pd.DataFrame(compute_roi_dims(rois, xyzm, maps["area"]))
            roi_dims.columns = [
                c if c == "COLOR" else f"{eye}_{c}" for c in roi_dims.columns
            ]
            dims[eye] = roi_dims
        if write_images is False:
            continue
        # try:
        write_spatial_images(bandset, eye, maps, outpath, ref_band, xyzm)
        # except KeyboardInterrupt:
        #     raise
        # except Exception as ex:
        #     aprint(f"couldn't write images for {eye}: {type(ex)},{ex}")
        # finally:
        #     plt.close("all")  # in case rendering crashed somewhere unexpected
    if dims != {}:
        dims = pd.merge(*tuple(dims.values()), on="COLOR")
    return dims


def write_spatial_images(bandset, eye, maps, outpath, ref_band, xyzm):
    iof_data = bandset.fetch_precached(ref_band)
    cahvore = derive_cahvore_properties(get_cahvore(iof_data))
    image = normalize_range(bandset.get_band(ref_band), (0, 1), 0.1)
    axes, sb_props = prep_scalebar_inputs(xyzm, cahvore)
    # TODO: make these into Looks
    mpl.use("agg")
    scalefig = draw_scalebars(axes, image, xyzm, sb_props)
    rangefig = draw_rangemap(maps, iof_data)
    figs = [scalefig, rangefig]
    names = ["scalebar", "rangemap"]
    for origin, name in zip(("center", "boresight"), ("camera", "boresight")):
        try:
            figs.append(draw_range_contours(maps, cahvore, origin))
            names.append(name)
        except CoverageError:
            aprint(f"[bold dark_orange]no data for {origin}, skipping contour")
    # TODO: emission and phase maps
    if "incidence" not in maps.keys():
        aprint(f"[bold dark_orange]No normals; skipping photometry maps.")
    else:
        figs.append(draw_incidence_map(maps["incidence"]))
        names.append("incidence")
    eyepre = eye.lower()[0]
    browsepath = Path(outpath, "browse")
    browsepath.mkdir(exist_ok=True, parents=True)
    dpi = dpi_from_image(scalefig)
    savekwargs = {"dpi": dpi, "bbox_inches": "tight", "pad_inches": 0}
    for fig, name in zip(figs, names):
        fig.tight_layout()
        fig.savefig(
            browsepath / f"{name}_{eyepre}_{bandset.name}.png", **savekwargs
        )
        plt.close(fig)


def make_space_fits(bandset, ref_bands, outpath):
    if bandset.xyrs is None:
        return no_ncam_match()
    uvwdir = bandset.xyrs[0].parents[1] / "nuvw"
    outfiles = []
    iof_datas = {
        ref_band: bandset.fetch_precached(ref_band) for ref_band in ref_bands
    }
    navrecs, cahvores = map_input_spatial_products(
        bandset.xyrs, iof_datas, uvwdir
    )
    for ref_band, iof_data in iof_datas.items():
        coords, zc = navrecs[ref_band]["coords"], cahvores[ref_band]
        maps = make_spatial_maps(coords, iof_data, zc)
        outfile = write_space_fits_file(
            maps, navrecs[ref_band], iof_data, bandset, Path(outpath, "data")
        )
        outfiles.append(outfile)
    return outfiles
