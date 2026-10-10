"""3D board preview: loads the game's skateboard model and renders it (numpy)."""
from __future__ import annotations

import json
import math
import struct
from pathlib import Path
from typing import Optional

from PIL import Image

from .common import XnbError
from .xnb import parse_xnb, read_model_json


# --------------------------------------------------------------------------
#  3D board preview (software renderer, needs numpy)
# --------------------------------------------------------------------------
# Model: Content/Models/Export/Board(.xnb|.gltf) + Board.bin(.xnb). The deck,
# trucks/wheels and screws all sample the board texture with nearest filtering,
# so the four color pixels land exactly where the game puts them.
BOARD_MODEL_DRAW = ("Deck_textured", "Wheels_Retract1", "Wheels_Retract2")


BOARD_MODEL_SCREWS = "Screws"


def find_board_model(board_folder: Optional[Path]) -> Optional[tuple]:
    """(model json path or xnb, buffer path) next to .../Models/Resources/Board."""
    if not board_folder:
        return None
    for base in [Path(board_folder)] + list(Path(board_folder).parents):
        exp = base / "Export" if base.name.lower() == "models" else base / "Models" / "Export"
        for mj in (exp / "Board.xnb", exp / "Board.gltf"):
            if mj.exists():
                for mb in (exp / "Board.bin.xnb", exp / "Board.bin"):
                    if mb.exists():
                        return mj, mb
    return None


def _read_model_buffer(path: Path) -> bytes:
    data = Path(path).read_bytes()
    if data[:3] != b"XNB":
        return data
    info = parse_xnb(data)
    if "ArrayReader" not in info.reader:
        raise XnbError("Board.bin.xnb is not a byte array")
    n, = struct.unpack_from("<i", data, info.content)
    if n < 0 or info.content + 4 + n > len(data):
        raise XnbError("Board.bin.xnb is truncated")
    return data[info.content + 4:info.content + 4 + n]


def _quat_mat(q):
    x, y, z, w = q
    return [[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
            [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
            [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]]


def load_board_model(model_path: Path, buffer_path: Path) -> dict:
    """{'parts': {name: (positions Nx3, uv Nx2, tris Mx3)}} in world space."""
    import numpy as np
    model_path = Path(model_path)
    if model_path.suffix.lower() == ".xnb":
        g = read_model_json(model_path)
    else:
        g = json.loads(model_path.read_text("utf-8"))
    buf = _read_model_buffer(buffer_path)

    def acc(i):
        a = g["accessors"][i]
        v = g["bufferViews"][a["bufferView"]]
        dt = {5126: np.float32, 5123: np.uint16, 5125: np.uint32, 5121: np.uint8}[a["componentType"]]
        n = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4}[a["type"]]
        off = v.get("byteOffset", 0) + a.get("byteOffset", 0)
        if off + a["count"] * n * np.dtype(dt).itemsize > len(buf):
            raise XnbError("Board.bin is smaller than the model expects")
        arr = np.frombuffer(buf, dt, a["count"] * n, off)
        return arr.reshape(a["count"], n) if n > 1 else arr

    nodes = g["nodes"]
    parts = {}

    def visit(i, mat):
        nd = nodes[i]
        m = np.eye(4)
        if "matrix" in nd:
            m = np.array(nd["matrix"], dtype=float).reshape(4, 4).T
        else:
            s = np.diag(list(nd.get("scale", [1, 1, 1])) + [1])
            r = np.eye(4)
            r[:3, :3] = _quat_mat(nd.get("rotation", [0, 0, 0, 1]))
            t = np.eye(4)
            t[:3, 3] = nd.get("translation", [0, 0, 0])
            m = t @ r @ s
        m = mat @ m
        name = nd.get("name", "")
        if "mesh" in nd and name in BOARD_MODEL_DRAW + (BOARD_MODEL_SCREWS,):
            pr = g["meshes"][nd["mesh"]]["primitives"][0]
            at = pr["attributes"]
            pos = acc(at["POSITION"]).astype(np.float64)
            pos = (np.c_[pos, np.ones(len(pos))] @ m.T)[:, :3]
            uv = acc(at["TEXCOORD_0"]).astype(np.float64)
            tris = acc(pr["indices"]).astype(np.int64).reshape(-1, 3)
            parts[name] = (pos, uv, tris)
        for c in nd.get("children", []):
            visit(c, m)
    for i in g["scenes"][g.get("scene", 0)]["nodes"]:
        visit(i, np.eye(4))
    if "Deck_textured" not in parts:
        raise XnbError("the model has no Deck_textured part")
    return {"parts": parts}


def _board_scene(model: dict, screws: bool) -> dict:
    """Concatenated, cached geometry for one screws setting."""
    import numpy as np
    key = "_scene_screws" if screws else "_scene_noscrews"
    sc = model.get(key)
    if sc is not None:
        return sc
    names = [n for n in BOARD_MODEL_DRAW if n in model["parts"]]
    if screws and BOARD_MODEL_SCREWS in model["parts"]:
        names.append(BOARD_MODEL_SCREWS)
    P, UV, T, OID, CULL, SCREW = [], [], [], [], [], []
    base = 0
    for k, n in enumerate(names):
        pos, uv, tris = model["parts"][n]
        P.append(pos)
        UV.append(uv)
        T.append(tris + base)
        OID.append(np.full(len(tris), k + 1, np.int32))
        CULL.append(np.full(len(tris), n == "Deck_textured"))      # the deck is a closed solid
        SCREW.append(np.full(len(tris), n == BOARD_MODEL_SCREWS))
        base += len(pos)
    P = np.vstack(P)
    T = np.vstack(T)
    a, b, c = P[T[:, 0]], P[T[:, 1]], P[T[:, 2]]
    nrm = np.cross(b - a, c - a)
    nrm /= np.maximum(np.linalg.norm(nrm, axis=1, keepdims=True), 1e-12)
    sc = {
        "P": P, "T": T, "UVt": np.vstack(UV)[T].astype(np.float32), "OID": np.concatenate(OID),
        "UVc": None, "cull": np.concatenate(CULL), "screw": np.concatenate(SCREW), "nrm": nrm,
        "cent": (a + b + c) / 3, "center": (P.min(0) + P.max(0)) / 2,
        "radius": float(np.linalg.norm(P.max(0) - P.min(0)) / 2),
    }
    sc["UVc"] = [np.ascontiguousarray(sc["UVt"][:, k, c]) for c in (0, 1) for k in range(3)]
    model[key] = sc
    return sc


def _prepare(model: dict, yaw: float, pitch: float, zoom: float, W: int, H: int, screws: bool) -> dict:
    """Camera, lighting and culling for one view: everything both renderers (CPU and GPU) share,
    so they draw exactly the same triangles with the same shading."""
    import numpy as np
    sc = _board_scene(model, screws)
    P, T, radius = sc["P"], sc["T"], sc["radius"]

    cy, sy = math.cos(math.radians(yaw)), math.sin(math.radians(yaw))
    cp, sp = math.cos(math.radians(pitch)), math.sin(math.radians(pitch))
    R = np.array([[1, 0, 0], [0, cp, -sp], [0, sp, cp]]) @ np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]])
    fov = math.radians(30)
    dist = radius / math.sin(fov / 2) * 0.72 / max(0.2, zoom)
    V = (P - sc["center"]) @ R.T
    depth_v = dist - V[:, 2]
    f = (min(W, H) / 2) / math.tan(fov / 2)
    sxv = (W / 2 + f * V[:, 0] / depth_v).astype(np.float32)
    syv = (H / 2 - f * V[:, 1] / depth_v).astype(np.float32)
    # center what is actually visible (perspective shifts the 3D center a little toward the
    # nearer end), so the board always sits in the middle of the frame
    sxv += np.float32(W / 2 - (float(sxv.min()) + float(sxv.max())) / 2)
    syv += np.float32(H / 2 - (float(syv.min()) + float(syv.max())) / 2)

    # lighting + culling with cached model-space normals
    nrm = sc["nrm"] @ R.T
    view = np.array([0, 0, dist]) - (sc["cent"] - sc["center"]) @ R.T
    facing = np.einsum("ij,ij->i", nrm, view) > 0
    nrm = np.where(facing[:, None], nrm, -nrm)                    # double-sided lighting
    light = np.array([-0.35, 0.65, 0.68])
    light /= np.linalg.norm(light)
    shade = (0.62 + 0.38 * np.clip(nrm @ light, 0, 1)).astype(np.float32)

    X, Y, D = sxv[T], syv[T], depth_v[T].astype(np.float32)
    area = (X[:, 1] - X[:, 0]) * (Y[:, 2] - Y[:, 0]) - (X[:, 2] - X[:, 0]) * (Y[:, 1] - Y[:, 0])
    bx0 = np.maximum(np.floor(X.min(1)), 0).astype(np.int32)
    bx1 = np.minimum(np.ceil(X.max(1)), W - 1).astype(np.int32)
    by0 = np.maximum(np.floor(Y.min(1)), 0).astype(np.int32)
    by1 = np.minimum(np.ceil(Y.max(1)), H - 1).astype(np.int32)
    ok = (np.abs(area) > 1e-6) & (bx1 >= bx0) & (by1 >= by0) & (D.min(1) > 0)
    ok &= facing | ~sc["cull"]
    return {"sc": sc, "radius": radius, "shade": shade, "X": X, "Y": Y, "D": D, "area": area,
            "bx0": bx0, "bx1": bx1, "by0": by0, "by1": by1, "idx": np.nonzero(ok)[0]}


def render_board(model: dict, tex: Image.Image, yaw: float, pitch: float, zoom: float,
                 W: int, H: int, screws: bool = True, outline: bool = True,
                 bg=(20, 21, 24), info: Optional[dict] = None) -> Image.Image:
    """Renders the board. yaw/pitch in degrees (+pitch = from above), zoom 1 = fit.
    If `info` is a dict, it is filled with per-pixel data (which texel and part each screen
    pixel shows), so the same view can be re-textured fast (retexture) and picked (pick_texel).
    Uses the graphics card when it can (see gpu3d.py) and this numpy renderer otherwise."""
    import numpy as np
    # tex: PIL image, or an HxWx3 uint8 array prepared once by the caller (faster)
    texa = tex if isinstance(tex, np.ndarray) else np.asarray(tex.convert("RGB"))
    pre = _prepare(model, yaw, pitch, zoom, W, H, screws)
    if _gpu_on:
        img = _render_gpu(pre, texa, W, H, outline, bg, info)
        if img is not None:
            return img
    return _render_cpu(pre, texa, W, H, outline, bg, info)


def _render_cpu(pre: dict, texa, W: int, H: int, outline: bool, bg, info: Optional[dict]) -> Image.Image:
    """The software (numpy) rasterizer."""
    import numpy as np
    global LAST_RENDERER
    LAST_RENDERER = "cpu"
    sc, radius, shade = pre["sc"], pre["radius"], pre["shade"]
    X, Y, D, area, idx = pre["X"], pre["Y"], pre["D"], pre["area"], pre["idx"]
    bx0, bx1, by0, by1 = pre["bx0"], pre["bx1"], pre["by0"], pre["by1"]
    th, tw = texa.shape[:2]
    # scanline spans: for every row a triangle touches, only the x-range between its edges is
    # tested, instead of its whole bounding box (~5x fewer pixels to test)
    bh = (by1[idx] - by0[idx] + 1).astype(np.int64)
    rtri = np.repeat(idx, bh)
    roff = np.repeat(np.cumsum(bh) - bh, bh)
    ry = (np.repeat(by0[idx], bh) + (np.arange(int(bh.sum()), dtype=np.int64) - roff)).astype(np.int32)
    yc = ry + np.float32(0.5)
    Xr, Yr = X[rtri], Y[rtri]
    xl = np.full(len(rtri), np.inf, np.float32)
    xr = np.full(len(rtri), -np.inf, np.float32)
    for i, j in ((0, 1), (1, 2), (2, 0)):
        ya, yb, xa, xb = Yr[:, i], Yr[:, j], Xr[:, i], Xr[:, j]
        dy = yb - ya
        hit = (yc >= np.minimum(ya, yb)) & (yc <= np.maximum(ya, yb)) & (dy != 0)
        with np.errstate(divide="ignore", invalid="ignore"):
            xe = xa + (yc - ya) * (xb - xa) / np.where(dy != 0, dy, 1)
        xl = np.where(hit, np.minimum(xl, xe), xl)
        xr = np.where(hit, np.maximum(xr, xe), xr)
    flat = ~np.isfinite(xl)                      # row only grazes a vertex / flat edge: whole bbox row
    # pixel centers px + 0.5 inside [xl, xr], with a 0.05 px margin (far more than the inside test's tolerance)
    rx0 = np.where(flat, bx0[rtri], np.ceil(xl - 0.55)).astype(np.float32)
    rx1 = np.where(flat, bx1[rtri], np.floor(xr - 0.45)).astype(np.float32)
    rx0 = np.maximum(np.maximum(rx0, bx0[rtri]), 0).astype(np.int32)
    rx1 = np.minimum(np.minimum(rx1, bx1[rtri]), W - 1).astype(np.int32)
    rcnt = np.maximum(rx1 - rx0 + 1, 0).astype(np.int64)

    # contiguous per-corner columns: gathering these is much faster than slicing X[tri] etc.
    Xc = [np.ascontiguousarray(X[:, k]) for k in range(3)]
    Yc = [np.ascontiguousarray(Y[:, k]) for k in range(3)]
    Dc = [np.ascontiguousarray(D[:, k]) for k in range(3)]
    with np.errstate(divide="ignore"):
        inv_area = (1 / area).astype(np.float32)      # degenerate triangles are skipped above
    zbuf = np.full(H * W, np.inf, np.float32)
    win_pix, win_tri, win_w0, win_w1, win_z = [], [], [], [], []
    # process in chunks of ~1.5M candidate pixels to bound memory
    csum = np.cumsum(rcnt)
    start = 0
    while start < len(rtri):
        end = int(np.searchsorted(csum, (csum[start - 1] if start else 0) + 1_500_000, "right"))
        end = max(end, start + 1)
        cnt = rcnt[start:end]
        tot = int(cnt.sum())
        if tot == 0:
            start = end
            continue
        tri = np.repeat(rtri[start:end], cnt)
        off = np.repeat(np.cumsum(cnt) - cnt, cnt)
        local = np.arange(tot, dtype=np.int64) - off
        px = (np.repeat(rx0[start:end], cnt) + local).astype(np.int32)
        py = np.repeat(ry[start:end], cnt)
        cx, cyy = px + np.float32(0.5), py + np.float32(0.5)
        x0, x1, x2 = Xc[0][tri], Xc[1][tri], Xc[2][tri]
        y0, y1, y2 = Yc[0][tri], Yc[1][tri], Yc[2][tri]
        inv = inv_area[tri]
        w0 = ((x1 - cx) * (y2 - cyy) - (x2 - cx) * (y1 - cyy)) * inv
        w1 = ((x2 - cx) * (y0 - cyy) - (x0 - cx) * (y2 - cyy)) * inv
        m = (w0 >= -1e-5) & (w1 >= -1e-5) & (w0 + w1 <= 1 + 1e-5)
        tri, px, py, w0, w1 = tri[m], px[m], py[m], w0[m], w1[m]
        w2 = 1 - w0 - w1
        dz = 1 / (w0 / Dc[0][tri] + w1 / Dc[1][tri] + w2 / Dc[2][tri])
        dz = (dz - np.where(sc["screw"][tri], radius * 0.004, 0)).astype(np.float32)  # screws sit on the deck
        pix = py * W + px
        np.minimum.at(zbuf, pix, dz)
        win_pix.append(pix)
        win_tri.append(tri)
        win_w0.append(w0)
        win_w1.append(w1)
        win_z.append(dz)
        start = end

    out = np.empty((H * W, 3), np.float32)
    out[:] = bg
    obuf = np.zeros(H * W, np.int32)
    if win_pix:
        pix, tri = np.concatenate(win_pix), np.concatenate(win_tri)
        w0, w1, dz = np.concatenate(win_w0), np.concatenate(win_w1), np.concatenate(win_z)
        keep = dz <= zbuf[pix]
        pix, tri, w0, w1 = pix[keep], tri[keep], w0[keep], w1[keep]
        w2 = 1 - w0 - w1
        a0, a1, a2 = w0 / Dc[0][tri], w1 / Dc[1][tri], w2 / Dc[2][tri]
        s = 1 / (a0 + a1 + a2)
        U = sc["UVc"]
        u = (a0 * U[0][tri] + a1 * U[1][tri] + a2 * U[2][tri]) * s
        v = (a0 * U[3][tri] + a1 * U[4][tri] + a2 * U[5][tri]) * s
        tu = np.clip((u * tw).astype(np.int32), 0, tw - 1)        # nearest, like the game's sampler
        tv = np.clip((v * th).astype(np.int32), 0, th - 1)
        out[pix] = texa[tv, tu] * shade[tri, None]
        obuf[pix] = sc["OID"][tri]
    img = out.reshape(H, W, 3)
    edge = None
    if outline and win_pix:
        # edges only exist next to board pixels: work on the board's bounding box (+1 px)
        full = obuf.reshape(H, W)
        rows, cols = np.nonzero(full.any(1))[0], np.nonzero(full.any(0))[0]
        y0, y1 = max(0, rows[0] - 1), min(H, rows[-1] + 2)
        x0, x1 = max(0, cols[0] - 1), min(W, cols[-1] + 2)
        o = full[y0:y1, x0:x1]
        zz = np.where(np.isfinite(zbuf), zbuf, 1e9).reshape(H, W)[y0:y1, x0:x1]
        thr = radius * 0.06
        edge_full = np.zeros((H, W), bool)
        edge = edge_full[y0:y1, x0:x1]
        for a_, b_ in (((slice(1, None), slice(None)), (slice(None, -1), slice(None))),
                       ((slice(None), slice(1, None)), (slice(None), slice(None, -1))),
                       ((slice(1, None), slice(1, None)), (slice(None, -1), slice(None, -1))),
                       ((slice(1, None), slice(None, -1)), (slice(None, -1), slice(1, None)))):
            e = (o[a_] != o[b_]) | (np.abs(zz[a_] - zz[b_]) > thr)
            e &= (o[a_] > 0) | (o[b_] > 0)
            edge[a_] |= e
            edge[b_] |= e
        edge = edge_full
        img[y0:y1, x0:x1][edge[y0:y1, x0:x1]] *= 0.18
    if info is not None:
        info.clear()
        # compact types: texture coordinates fit 16 bits (textures are at most 16384 px), parts 8 bits
        info.update(W=W, H=H, bg=bg, tex_size=(tw, th), oid=obuf.reshape(H, W).astype(np.uint8), edge=edge,
                    tu_map=np.full(H * W, -1, np.int16), tv_map=np.full(H * W, -1, np.int16))
        if win_pix:
            info.update(pix=pix.astype(np.int32), tu=tu.astype(np.int16), tv=tv.astype(np.int16),
                        shade=shade[tri][:, None])
            info["tu_map"][pix] = tu
            info["tv_map"][pix] = tv
        info["tu_map"] = info["tu_map"].reshape(H, W)
        info["tv_map"] = info["tv_map"].reshape(H, W)
    frame = np.clip(img, 0, 255).astype(np.uint8)
    if info is not None:
        info["frame"] = frame.reshape(-1, 3)            # kept for retexture_region()
    return Image.fromarray(frame, "RGB")


# --------------------------------------------------------------------------
#  GPU path (OpenGL 3.3 through ctypes, see gpu3d.py); falls back to the CPU renderer
# --------------------------------------------------------------------------
import os as _os

_ENV_OFF = _os.environ.get("XNB_NO_GPU", "") not in ("", "0")   # escape hatch: XNB_NO_GPU=1
_gpu_on = not _ENV_OFF
_gpu_failed = ""            # why the GPU is not used ('' = not tried yet or working)
LAST_RENDERER = ""          # 'gpu' or 'cpu': which one drew the last frame


def set_gpu_enabled(on: bool, retry: bool = False) -> None:
    """Turns the GPU renderer on or off (the Settings checkbox). retry=True also forgets an
    earlier failure, so the graphics card is tried again."""
    global _gpu_on, _gpu_failed
    if retry and on:
        _gpu_failed = ""
        from . import gpu3d
        gpu3d.clear_crash_marker()
    _gpu_on = bool(on) and not _gpu_failed and not _ENV_OFF


def gpu_active() -> bool:
    """True when frames go to the graphics card (the views then render at full resolution)."""
    return _gpu_on and not _gpu_failed


def gpu_status() -> tuple:
    """(using_gpu, text) for the settings window and the 3D note."""
    if _gpu_failed:
        return False, f"CPU (graphics card not usable: {_gpu_failed})"
    if _ENV_OFF:
        return False, "CPU (GPU turned off by XNB_NO_GPU)"
    if not _gpu_on:
        return False, "CPU (GPU turned off)"
    from . import gpu3d
    r = gpu3d.existing()
    if r is None:
        return True, "GPU (starts with the first 3D frame)"
    return True, f"GPU ({r.name})"


def _render_gpu(pre: dict, texa, W: int, H: int, outline: bool, bg, info: Optional[dict]):
    """Renders on the graphics card; returns None (and stays on the CPU from then on) if anything
    about the GPU does not work."""
    import numpy as np
    global _gpu_on, _gpu_failed, LAST_RENDERER
    try:
        from . import gpu3d
        r = gpu3d.get()
        sc, idx, radius = pre["sc"], pre["idx"], pre["radius"]
        n = len(idx)
        verts = np.empty((n, 3, 8), np.float32)
        verts[:, :, 0] = pre["X"][idx]
        verts[:, :, 1] = pre["Y"][idx]
        verts[:, :, 2] = pre["D"][idx]
        verts[:, :, 3:5] = sc["UVt"][idx]
        verts[:, :, 5] = pre["shade"][idx, None]
        verts[:, :, 6] = sc["OID"][idx, None]
        verts[:, :, 7] = np.where(sc["screw"][idx], radius * 0.004, 0.0)[:, None]  # screws sit on the deck
        if n:
            near = float(pre["D"][idx].min()) - radius * 0.02
            far = float(pre["D"][idx].max()) + radius * 0.02
        else:
            near, far = 0.0, 1.0
        out = r.render(verts.reshape(-1, 8), np.ascontiguousarray(texa, np.uint8), W, H,
                       tuple(float(c) for c in bg[:3]), outline, radius * 0.06, near, far,
                       info is not None)
    except Exception as e:                      # driver problem, no OpenGL 3.3, ...: CPU from now on
        _gpu_failed = (str(e) or e.__class__.__name__).splitlines()[0][:160]
        _gpu_on = False
        return None
    LAST_RENDERER = "gpu"
    frame = out["frame"]
    if info is not None:
        th, tw = texa.shape[:2]
        oid = out["oid"]
        info.clear()
        # the per-board-pixel lists (pix, tu, tv, shade) are only built if the frame is
        # recolored later (_pixel_lists), which most frames never are
        info.update(W=W, H=H, bg=bg, tex_size=(tw, th), oid=oid,
                    tu_map=np.ascontiguousarray(out["texel"][:, :, 0]),
                    tv_map=np.ascontiguousarray(out["texel"][:, :, 1]),
                    shade_map=out["shade"])
        info["edge"] = out["edge"] if (outline and oid.any()) else None
        info["frame"] = frame.reshape(-1, 3)
    return Image.fromarray(frame, "RGB")


def _pixel_lists(info: dict) -> None:
    """Board pixels as flat lists (pix, tu, tv, shade). The CPU renderer makes them directly;
    after a GPU frame they are built from the per-pixel maps the first time they are needed."""
    import numpy as np
    if "pix" in info or "shade_map" not in info:
        return
    pix = np.flatnonzero(info["oid"].ravel()).astype(np.int32)
    if len(pix):
        info.update(pix=pix, tu=info["tu_map"].ravel()[pix], tv=info["tv_map"].ravel()[pix],
                    shade=info["shade_map"].ravel()[pix][:, None])
    del info["shade_map"]


def retexture(info: dict, tex) -> Image.Image:
    """Redraws the last render_board() view with a different texture of the same size,
    without rasterizing again (a few milliseconds instead of a full render)."""
    import numpy as np
    _pixel_lists(info)
    texa = tex if isinstance(tex, np.ndarray) else np.asarray(tex.convert("RGB"))
    W, H = info["W"], info["H"]
    out = np.empty((H * W, 3), np.float32)
    out[:] = info["bg"]
    if "pix" in info:
        th, tw = texa.shape[:2]
        tu, tv = info["tu"], info["tv"]
        if (tw, th) != info["tex_size"]:          # same UVs, other resolution
            tu = np.clip(tu.astype(np.int32) * tw // info["tex_size"][0], 0, tw - 1)
            tv = np.clip(tv.astype(np.int32) * th // info["tex_size"][1], 0, th - 1)
        out[info["pix"]] = texa[tv, tu] * info["shade"]
    img = out.reshape(H, W, 3)
    if info.get("edge") is not None:
        img[info["edge"]] *= 0.18
    frame = np.clip(img, 0, 255).astype(np.uint8)
    info["frame"] = frame.reshape(-1, 3)
    return Image.fromarray(frame, "RGB")


def retexture_region(info: dict, tex, box) -> Image.Image:
    """Like retexture(), but only screen pixels showing texture pixels inside box (x0, y0, x1, y1)
    are recolored; the rest is reused from the last frame. Much faster for a small change."""
    import numpy as np
    texa = tex if isinstance(tex, np.ndarray) else np.asarray(tex.convert("RGB"))
    _pixel_lists(info)
    info.pop("changed_box", None)                       # only set when just a rectangle changed
    if info.get("frame") is None or "pix" not in info or (texa.shape[1], texa.shape[0]) != info["tex_size"]:
        return retexture(info, texa)
    W, H = info["W"], info["H"]
    frame = info["frame"]
    x0, y0, x1, y1 = box
    tu, tv = info["tu"], info["tv"]
    sel = np.nonzero((tu >= x0) & (tu < x1) & (tv >= y0) & (tv < y1))[0]
    info["changed_box"] = (0, 0, 0, 0)                  # screen rectangle that changed (for display)
    if len(sel):
        sp = info["pix"][sel]
        ys, xs = sp // W, sp % W
        info["changed_box"] = (int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1)
        vals = texa[tv[sel], tu[sel]] * info["shade"][sel]
        if info.get("edge") is not None:
            ep = info.get("edge_pix")
            if ep is None:
                ep = info["edge_pix"] = info["edge"].ravel()[info["pix"]]
            vals[ep[sel]] *= 0.18
        frame[info["pix"][sel]] = np.clip(vals, 0, 255).astype(np.uint8)
    return Image.fromarray(frame.reshape(H, W, 3), "RGB")


def pick_texel(info: dict, x: int, y: int, radius: int = 0):
    """(tu, tv) of the texture pixel shown at screen pixel (x, y), or None for background.
    With radius > 0 the nearest board pixel within that distance is used."""
    W, H = info.get("W", 0), info.get("H", 0)
    best = None
    for r in range(radius + 1):
        for dy in range(-r, r + 1):
            for dx in range(-r, r + 1):
                if max(abs(dx), abs(dy)) != r:
                    continue
                xx, yy = x + dx, y + dy
                if 0 <= xx < W and 0 <= yy < H and info["tu_map"][yy, xx] >= 0:
                    d = dx * dx + dy * dy
                    if best is None or d < best[0]:
                        best = (d, int(info["tu_map"][yy, xx]), int(info["tv_map"][yy, xx]))
        if best:
            return best[1], best[2]
    return None


def deck_top_mask(model: dict, W: int, H: int) -> Image.Image:
    """'L' mask (W x H texture pixels) of the texture area that shows on the top of the deck."""
    import numpy as np
    from PIL import ImageDraw
    pos, uv, tris = model["parts"]["Deck_textured"]
    a, b, c = pos[tris[:, 0]], pos[tris[:, 1]], pos[tris[:, 2]]
    n = np.cross(b - a, c - a)
    up = n[:, 1] / np.maximum(np.linalg.norm(n, axis=1), 1e-12) > 0.5
    m = Image.new("L", (W, H), 0)
    d = ImageDraw.Draw(m)
    for t in tris[up]:
        d.polygon([(float(uv[i, 0] * W), float(uv[i, 1] * H)) for i in t], fill=255)
    return m
