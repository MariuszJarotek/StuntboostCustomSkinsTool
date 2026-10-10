"""Decorating: stickers / images as layers on a base texture, composed into a board texture.

A decoration can be kept editable after saving: the base, every layer's image and its
placement are stored in _board_defaults/decor/<board file>/ together with the hash of the
texture that was written. When the texture still matches that hash, the layers come back.
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
import math
import shutil
import time
from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw

from .boards import apply_palette
from .common import atomic_write
from .defaults import DEF_DIR, pixel_hash
from .imageops import Adjust, adjust_base_scale, render_adjusted

PROJECT_VERSION = 1
MAX_LAYERS = 200


class Layer:
    """One placed image. Its rendered pixels are kept only for the rectangle it covers (not the
    whole board), cached until its placement changes."""
    _ids = 0

    def __init__(self, src: Image.Image, name: str, adj: Adjust, opacity: float = 1.0, visible: bool = True):
        Layer._ids += 1
        self.id = Layer._ids
        self.src = src if src.mode == "RGBA" else src.convert("RGBA")
        self.name, self.adj, self.opacity, self.visible = name, adj, float(opacity), bool(visible)
        self._key = self._img = self._box = None
        self._cache: dict = {}
        self.thumb = None                     # GUI thumbnail (PhotoImage), owned by the GUI

    def key(self):
        return (self.id, dataclasses.astuple(self.adj), self.opacity, self.visible)

    def render(self, W, H, fast=False):
        """(image, box): the layer rendered inside its own rectangle box = (x0, y0, x1, y1) of the
        W x H texture, or (None, None) when it lies completely outside."""
        k = (self.key(), W, H)
        if self._key == k:
            return self._img, self._box
        box = self.bbox(W, H)
        img = self.render_box(W, H, box, fast) if box else None
        self._img, self._box, self._key = img, box, (None if fast else k)
        return img, box

    def render_box(self, W, H, box, fast=False) -> Image.Image:
        """Only the part of the layer inside box (x0, y0, x1, y1)."""
        img = render_adjusted(self.src, W, H, self.adj, cache=self._cache, box=box,
                              resample=Image.BILINEAR if fast else Image.BICUBIC)
        if self.opacity < 1:
            img.putalpha(img.split()[3].point(lambda v, o=self.opacity: int(v * o)))
        return img

    def drop_cache(self):
        """Frees the rendered pixels (they are made again when needed)."""
        self._key = self._img = self._box = None
        self._cache = {}

    def bbox(self, W, H, pad=0):
        """Integer box (x0, y0, x1, y1) around the layer, clipped to the texture; None if outside."""
        pts = self.corners(W, H)
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        x0, y0 = max(0, int(math.floor(min(xs))) - pad - 2), max(0, int(math.floor(min(ys))) - pad - 2)
        x1, y1 = min(W, int(math.ceil(max(xs))) + pad + 2), min(H, int(math.ceil(max(ys))) + pad + 2)
        return (x0, y0, x1, y1) if x1 > x0 and y1 > y0 else None

    def hit(self, x, y) -> bool:
        if not self.visible or self._img is None:
            return False
        x0, y0, x1, y1 = self._box
        x, y = int(x), int(y)
        return x0 <= x < x1 and y0 <= y < y1 and self._img.getpixel((x - x0, y - y0))[3] > 24

    def center(self, W, H):
        return (W / 2 if self.adj.cx is None else self.adj.cx, H / 2 if self.adj.cy is None else self.adj.cy)

    def corners(self, W, H, k=1.0):
        """The layer's 4 corners in texture pixels (times k)."""
        bw, bh = self.src.size
        sx, sy = adjust_base_scale(bw, bh, W, H, self.adj)
        sx, sy = sx * self.adj.zoom, sy * self.adj.zoom
        cx, cy = self.center(W, H)
        t = math.radians(self.adj.angle)
        c, s = math.cos(t), math.sin(t)
        pts = []
        for ux, uy in ((-bw / 2, -bh / 2), (bw / 2, -bh / 2), (bw / 2, bh / 2), (-bw / 2, bh / 2)):
            x, y = ux * sx, uy * sy
            pts.append(((cx + x * c - y * s) * k, (cy + x * s + y * c) * k))
        return pts

    def snapshot(self):
        return (self, dataclasses.replace(self.adj), self.opacity, self.visible, self.name)


def sticker_adjust(src: Image.Image, W: int, H: int, at=None) -> Adjust:
    """Placement for a new sticker: about half the deck height, centered at `at`."""
    adj = Adjust(mode="fit")
    bw, bh = src.size
    k = min(W / bw, H / bh)
    adj.zoom = min(1.0, 0.5 * H / (bh * k), 0.3 * W / (bw * k))
    cx, cy = at if at is not None else (W / 2, H / 2)
    adj.cx, adj.cy = float(cx), float(cy)
    return adj


def new_image_adjust(src: Image.Image, W: int, H: int, at=None) -> Adjust:
    """Board-shaped images (wide) cover the whole deck; anything else becomes a sticker."""
    if src.width / max(1, src.height) >= 2.5:
        return Adjust(mode="fill")
    return sticker_adjust(src, W, H, at)


def _union(a, b):
    if a is None:
        return b
    if b is None:
        return a
    return (min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3]))


def _paint(dst: Image.Image, L: Layer, W: int, H: int, region=None):
    """Composites layer L onto dst (in place). dst covers `region` of the texture, or all of it."""
    part, box = L.render(W, H)
    if part is None:
        return
    if region is None:
        dst.alpha_composite(part, dest=box[:2])
        return
    x0, y0 = max(box[0], region[0]), max(box[1], region[1])
    x1, y1 = min(box[2], region[2]), min(box[3], region[3])
    if x1 > x0 and y1 > y0:
        dst.alpha_composite(part, dest=(x0 - region[0], y0 - region[1]),
                            source=(x0 - box[0], y0 - box[1], x1 - box[0], y1 - box[1]))


def _put_palette(img: Image.Image, pal):
    for x, c in enumerate(pal[:min(len(pal), img.width)]):
        img.putpixel((x, 0), (int(c[0]), int(c[1]), int(c[2]), 255))


class Composer:
    """Base + layers + board colors -> texture. The layers below the selected one are cached
    as one image, so moving one sticker only re-renders that sticker - and while it is being
    dragged (fast=True), only inside the rectangle it moved through (last_region tells which)."""

    PAD = 6                         # room for the selection outline around a layer

    def __init__(self):
        self.invalidate()

    def invalidate(self):
        self._below = None
        self._work = None
        self._state = None
        self._sel_box = None
        self.last_region = None

    def compose(self, base: Image.Image, layers, sel, pal, fast=False) -> Image.Image:
        W, H = base.size
        vis = [L for L in layers if L.visible]
        s = sel if sel in vis else None
        others = tuple(L.key() for L in vis if L is not s)
        state = (id(base), base.size, s, tuple(map(tuple, pal)) if pal else None, others)
        self.last_region = None
        if fast and s is not None and self._work is not None and state == self._state and self._below is not None:
            box = s.bbox(W, H, self.PAD)
            region = _union(self._sel_box, box)
            if region is None:
                return self._work
            img = self._below[1].crop(region)
            img.alpha_composite(s.render_box(W, H, region, fast=True))
            for L in vis[vis.index(s) + 1:]:
                _paint(img, L, W, H, region)
            self._work.paste(img, region[:2])
            if pal and region[1] == 0 and region[0] < len(pal):
                _put_palette(self._work, pal)
            self._sel_box = box
            self.last_region = region
            return self._work
        work = self._compose_full(base, vis, s, pal, fast)
        self._work, self._state = work, state
        self._sel_box = s.bbox(W, H, self.PAD) if s is not None else None
        return work

    def _compose_full(self, base, vis, s, pal, fast):
        W, H = base.size
        i = vis.index(s) if s else len(vis)
        below_key = (id(base),) + tuple(L.key() for L in vis[:i])
        if self._below is None or self._below[0] != below_key:
            img = base.copy()
            for L in vis[:i]:
                _paint(img, L, W, H)
            self._below = (below_key, img)
        img = self._below[1].copy()
        if s is not None:
            part, box = s.render(W, H, fast)
            if part is not None:
                img.alpha_composite(part, dest=box[:2])
            for L in vis[i + 1:]:
                _paint(img, L, W, H)
        if pal:
            _put_palette(img, pal)
        return img


def with_outline(work: Image.Image, layer: Optional[Layer], color, pal) -> Image.Image:
    """Copy of the texture with the selected layer's outline drawn in (for the 3D view only)."""
    if layer is None or not layer.visible:
        return work
    W, H = work.size
    out = work.copy()
    pts = layer.corners(W, H)
    ImageDraw.Draw(out).line(pts + [pts[0]], fill=tuple(color[:3]) + (255,), width=max(3, W // 400))
    return apply_palette(out, pal) if pal else out


# ---------------------------------------------------------------- editable project files
def project_dir(texture_path: Path) -> Path:
    return Path(texture_path).parent / DEF_DIR / "decor" / Path(texture_path).name


def save_project(texture_path: Path, base: Image.Image, base_key: str, tint, tint_strength: float,
                 layers, result: Image.Image) -> Path:
    """Stores the decoration next to the board so it can be edited again later."""
    d = project_dir(texture_path)
    tmp = d.with_name(d.name + ".tmp")
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    base.save(tmp / "base.png")
    files, entries = {}, []
    for L in layers:
        h = hashlib.sha1(L.src.tobytes() + str(L.src.size).encode()).hexdigest()[:16]
        if h not in files:
            files[h] = f"img_{h}.png"
            L.src.save(tmp / files[h])
        entries.append({"name": L.name, "image": files[h], "adjust": dataclasses.asdict(L.adj),
                        "opacity": L.opacity, "visible": L.visible})
    meta = {"version": PROJECT_VERSION, "saved_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "base": base_key, "tint": list(tint[:3]) if tint else None, "tint_strength": tint_strength,
            "size": list(base.size), "result_sha256": pixel_hash(result), "layers": entries}
    atomic_write(tmp / "project.json", json.dumps(meta, indent=1).encode("utf-8"))
    shutil.rmtree(d, ignore_errors=True)
    tmp.rename(d)
    return d


def _num(v, lo=-1e6, hi=1e6, default=0.0):
    try:
        v = float(v)
    except (TypeError, ValueError):
        return default
    return v if math.isfinite(v) and lo <= v <= hi else default


def load_project(texture_path: Path, current: Image.Image) -> Optional[dict]:
    """The stored decoration if it still belongs to the texture as it is now, else None.
    Returns {'base', 'base_key', 'tint', 'tint_strength', 'layers', 'saved_at'}."""
    d = project_dir(texture_path)
    try:
        meta = json.loads((d / "project.json").read_text("utf-8"))
        if meta.get("version") != PROJECT_VERSION or meta.get("result_sha256") != pixel_hash(current):
            return None
        base = Image.open(d / "base.png")
        base.load()
        base = base.convert("RGBA")
        if base.size != current.size:
            return None
        layers, imgs = [], {}
        for e in meta.get("layers", [])[:MAX_LAYERS]:
            name = Path(str(e.get("image", ""))).name          # never leave the folder
            if name not in imgs:
                im = Image.open(d / name)
                im.load()
                imgs[name] = im.convert("RGBA")
            a = e.get("adjust", {})
            adj = Adjust(mode=a.get("mode") if a.get("mode") in ("fill", "fit", "stretch") else "fit",
                         zoom=_num(a.get("zoom"), 0.001, 100, 1.0), angle=_num(a.get("angle"), -1e4, 1e4),
                         flip_h=bool(a.get("flip_h")), flip_v=bool(a.get("flip_v")),
                         cx=None if a.get("cx") is None else _num(a.get("cx")),
                         cy=None if a.get("cy") is None else _num(a.get("cy")))
            layers.append(Layer(imgs[name], str(e.get("name", "layer"))[:60], adj,
                                _num(e.get("opacity"), 0, 1, 1.0), bool(e.get("visible", True))))
        tint = meta.get("tint")
        tint = tuple(int(_num(c, 0, 255)) for c in tint[:3]) if isinstance(tint, list) and len(tint) >= 3 else None
        return {"base": base, "base_key": str(meta.get("base") or "original"), "tint": tint,
                "tint_strength": _num(meta.get("tint_strength"), 0, 1), "layers": layers,
                "saved_at": str(meta.get("saved_at", ""))}
    except Exception:
        return None


def has_project(texture_path: Path) -> bool:
    return (project_dir(texture_path) / "project.json").exists()


def drop_project(texture_path: Path):
    shutil.rmtree(project_dir(texture_path), ignore_errors=True)
