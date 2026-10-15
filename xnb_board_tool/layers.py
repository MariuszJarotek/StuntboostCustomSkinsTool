"""Decorating: stickers / images as layers on a base texture, composed into a board texture.

A decoration can be kept editable after saving: the base, every layer's image and its
placement are stored in _board_defaults/decor/<board file>/ together with the hash of the
texture that was written. When the texture still matches that hash, the layers come back.
"""
from __future__ import annotations

from .i18n import N_

import dataclasses
import functools
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
from .effects import (FINISH_FX, STICKER_FX, apply_sticker_fx, color_key, fx_active, fx_key, recolor,
                      sticker_margin)
from .imageops import Adjust, adjust_base_scale, render_adjusted

PROJECT_VERSION = 1
MAX_LAYERS = 200


MIRRORS = (("", N_("Off")), ("ends", N_("Nose & tail")), ("sides", N_("Both sides")))


class Layer:
    """One placed image. Its rendered pixels (with its colour changes and effects) are kept only
    for the rectangle it covers (not the whole board), cached until its placement changes. While
    it is dragged the cached rendering is just moved, so effects cost nothing extra during a drag.

    mirror: '' (off), 'ends' (a copy turned 180 degrees around the deck's centre: nose <-> tail)
    or 'sides' (a copy mirrored across the deck's long axis). The copy is rendered like the layer
    itself (not a flipped picture), so its shadow falls the same way.
    gen: the settings a text or shape layer was made from (so it can be edited), or None."""
    _ids = 0

    def __init__(self, src: Image.Image, name: str, adj: Adjust, opacity: float = 1.0, visible: bool = True,
                 fx: Optional[dict] = None, color: Optional[dict] = None, mirror: str = "",
                 gen: Optional[dict] = None):
        """A sticker, image, text or shape on the board: the source image and its placement (Adjust), opacity,
        visibility, effects, recolour, mirroring and, for generated layers, the settings that draw it.
        """
        Layer._ids += 1
        self.id = Layer._ids
        self.src = src if src.mode == "RGBA" else src.convert("RGBA")
        self.name, self.adj, self.opacity, self.visible = name, adj, float(opacity), bool(visible)
        self.fx: dict = dict(fx or {})        # sticker effects: {'shadow': 0..1, ..., 'seed': int}
        self.color: dict = dict(color or {})  # recolour: {'hue': deg, 'sat': 0..2, 'tint': rgb, 'tint_s': 0..1}
        self.mirror = mirror if mirror in ("ends", "sides") else ""
        self.gen = dict(gen) if gen else None
        self._key = self._img = self._box = None
        self._pieces: dict = {}               # 'main' / 'mirror' -> (key, high quality, cx, cy, image, box)
        self._cache: dict = {}
        self.thumb = None                     # GUI thumbnail (PhotoImage), owned by the GUI

    def set_src(self, src: Image.Image):
        """New image (an edited text or shape layer)."""
        self.src = src if src.mode == "RGBA" else src.convert("RGBA")
        self.drop_cache()

    def key(self):
        """Everything that changes how the layer looks, as one hashable value (used to know when a cached render is
        still valid).
        """
        return (self.id, dataclasses.astuple(self.adj), self.opacity, self.visible, fx_key(self.fx),
                color_key(self.color), self.mirror, id(self.src))

    def _piece_key(self, a, W, H):            # everything but the position
        """Like key() but without the position, so a moved layer can reuse its rendered image."""
        return (a.mode, a.zoom, a.angle, a.flip_h, a.flip_v, a.bg, self.opacity, fx_key(self.fx),
                color_key(self.color), id(self.src), W, H)

    def _adjs(self, W, H):
        """(tag, placement) of every copy that is drawn."""
        out = [("main", self.adj)]
        if self.mirror:
            a = self.adj
            cx, cy = self.center(W, H)
            if self.mirror == "ends":
                m = dataclasses.replace(a, cx=W - cx, cy=H - cy, angle=(a.angle + 180) % 360)
            else:
                m = dataclasses.replace(a, cx=cx, cy=H - cy, angle=(-a.angle) % 360, flip_v=not a.flip_v)
            out.append(("mirror", m))
        return out

    def _render_piece(self, tag, a, W, H, fast):
        """(image, box) of one copy with its colour and effects, box in texture pixels (may reach past
        the texture). Fast renders reuse the last one moved to the new position when only the
        position changed."""
        cx = W / 2 if a.cx is None else a.cx
        cy = H / 2 if a.cy is None else a.cy
        sk = self._piece_key(a, W, H)
        f = self._pieces.get(tag)
        if f is not None and f[0] == sk:
            if (f[2], f[3]) == (cx, cy) and (f[1] or fast):
                return f[4], f[5]
            if fast and f[4] is not None:
                dx, dy = int(round(cx - f[2])), int(round(cy - f[3]))
                box = (f[5][0] + dx, f[5][1] + dy, f[5][2] + dx, f[5][3] + dy)
                need = _clip(self._outer_box_for(a, W, H), (0, 0, W, H))
                # the outer box has 2 px of empty room, so a 1-2 px shortfall from rounding is fine
                if need is None or (box[0] <= need[0] + 2 and box[1] <= need[1] + 2
                                    and box[2] >= need[2] - 2 and box[3] >= need[3] - 2):
                    return f[4], box
        m = sticker_margin(self.fx, H)
        lim = (-(m + 64), -(m + 64), W + m + 64, H + m + 64)       # far enough past the edges
        box = _clip(self._outer_box_for(a, W, H), lim)
        img = None
        if box is not None:
            img = render_adjusted(self.src, W, H, a, cache=self._cache, box=box,
                                  resample=Image.BILINEAR if fast else Image.BICUBIC)
            if color_key(self.color):
                img = recolor(img, self.color)
            if fx_active(self.fx):
                img = apply_sticker_fx(img, self.fx, H)
            if self.opacity < 1:
                img.putalpha(img.getchannel("A").point(lambda v, o=self.opacity: int(v * o)))
        self._pieces[tag] = (sk, not fast, cx, cy, img, box)
        return img, box

    def _render_all(self, W, H, fast):
        """[(image, box)] of the copies that are drawn, the mirrored copy first (under the layer)."""
        if not self.mirror:
            self._pieces.pop("mirror", None)
        out = []
        for tag, a in reversed(self._adjs(W, H)):
            img, box = self._render_piece(tag, a, W, H, fast)
            if img is not None:
                out.append((img, box))
        return out

    def render(self, W, H, fast=False):
        """(image, box): the layer rendered inside its own rectangle box = (x0, y0, x1, y1) of the
        W x H texture, or (None, None) when it lies completely outside."""
        k = (self.key(), W, H)
        if self._key == k:
            return self._img, self._box
        pieces = self._render_all(W, H, fast)
        box = None
        for _img, b in pieces:
            box = _union(box, _clip(b, (0, 0, W, H)))
        img = None
        if box is not None:
            if len(pieces) == 1 and pieces[0][1] == box:
                img = pieces[0][0]
            else:
                img = self._compose_pieces(pieces, box)
        self._img, self._box, self._key = img, box, (None if fast else k)
        return img, box

    @staticmethod
    def _compose_pieces(pieces, box):
        """Pastes rendered pieces (the layer and its mirrored copies) into one image covering `box`."""
        out = Image.new("RGBA", (max(1, box[2] - box[0]), max(1, box[3] - box[1])), (0, 0, 0, 0))
        for full, fbox in pieces:
            ov = _clip(fbox, box)
            if ov is not None:
                out.alpha_composite(full, dest=(ov[0] - box[0], ov[1] - box[1]),
                                    source=(ov[0] - fbox[0], ov[1] - fbox[1], ov[2] - fbox[0], ov[3] - fbox[1]))
        return out

    def render_box(self, W, H, box, fast=False) -> Image.Image:
        """Only the part of the layer inside box (x0, y0, x1, y1)."""
        return self._compose_pieces(self._render_all(W, H, fast), box)

    def drop_cache(self):
        """Frees the rendered pixels (they are made again when needed)."""
        self._key = self._img = self._box = None
        self._pieces = {}
        self._cache = {}

    def _outer_box_for(self, a, W, H):
        """Unclipped integer box around one copy and its effects."""
        pts = self.corners_for(a, W, H)
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        m = sticker_margin(self.fx, H) + 2
        return (int(math.floor(min(xs))) - m, int(math.floor(min(ys))) - m,
                int(math.ceil(max(xs))) + m, int(math.ceil(max(ys))) + m)

    def bbox(self, W, H, pad=0):
        """Integer box (x0, y0, x1, y1) around the layer, its copy and effects, clipped to the texture;
        None if outside."""
        box = None
        for _tag, a in self._adjs(W, H):
            x0, y0, x1, y1 = self._outer_box_for(a, W, H)
            box = _union(box, _clip((x0 - pad, y0 - pad, x1 + pad, y1 + pad), (0, 0, W, H)))
        return box

    def bboxes(self, W, H, pad=0) -> list:
        """One clipped box per copy (the layer, then its mirror copy); copies outside are left out."""
        out = []
        for _tag, a in self._adjs(W, H):
            x0, y0, x1, y1 = self._outer_box_for(a, W, H)
            b = _clip((x0 - pad, y0 - pad, x1 + pad, y1 + pad), (0, 0, W, H))
            if b is not None:
                out.append(b)
        return out

    def hit(self, x, y) -> bool:
        """True when board point (x, y) is on a visible, non-transparent pixel of the layer (for clicking
        stickers).
        """
        if not self.visible or self._img is None:
            return False
        x0, y0, x1, y1 = self._box
        x, y = int(x), int(y)
        return x0 <= x < x1 and y0 <= y < y1 and self._img.getpixel((x - x0, y - y0))[3] > 24

    def hit_part(self, x, y) -> Optional[str]:
        """'main' or 'mirror': which copy is at texture point (x, y), or None."""
        x, y = int(x), int(y)
        for tag in ("main", "mirror"):
            f = self._pieces.get(tag)
            if f is None or f[4] is None:
                continue
            x0, y0, x1, y1 = f[5]
            if x0 <= x < x1 and y0 <= y < y1 and f[4].getpixel((x - x0, y - y0))[3] > 24:
                return tag
        return None

    def center(self, W, H):
        """Where the layer's centre is on a W x H board (the middle when it was never moved)."""
        return (W / 2 if self.adj.cx is None else self.adj.cx, H / 2 if self.adj.cy is None else self.adj.cy)

    def corners_for(self, a, W, H, k=1.0):
        """The 4 corners of a copy placed with `a`, in texture pixels (times k)."""
        bw, bh = self.src.size
        sx, sy = adjust_base_scale(bw, bh, W, H, a)
        sx, sy = sx * a.zoom, sy * a.zoom
        cx = W / 2 if a.cx is None else a.cx
        cy = H / 2 if a.cy is None else a.cy
        t = math.radians(a.angle)
        c, s = math.cos(t), math.sin(t)
        pts = []
        for ux, uy in ((-bw / 2, -bh / 2), (bw / 2, -bh / 2), (bw / 2, bh / 2), (-bw / 2, bh / 2)):
            x, y = ux * sx, uy * sy
            pts.append(((cx + x * c - y * s) * k, (cy + x * s + y * c) * k))
        return pts

    def corners(self, W, H, k=1.0):
        """The layer's 4 corners in texture pixels (times k)."""
        return self.corners_for(self.adj, W, H, k)

    def all_corners(self, W, H, k=1.0):
        """Corners of every copy that is drawn (for outlines)."""
        return [self.corners_for(a, W, H, k) for _tag, a in self._adjs(W, H)]

    def snapshot(self):
        """Everything needed to undo a change to this layer, as a tuple restore() takes back."""
        return (self, dataclasses.replace(self.adj), self.opacity, self.visible, self.name, dict(self.fx),
                dict(self.color), self.mirror, self.src, dict(self.gen) if self.gen else None)

    def restore(self, snap):
        """Puts the layer back to a snapshot() (undo / redo)."""
        _L, adj, op, vis, name, fx, color, mirror, src, gen = snap
        self.adj, self.opacity, self.visible, self.name = dataclasses.replace(adj), op, vis, name
        self.fx, self.color, self.mirror = dict(fx), dict(color), mirror
        self.gen = dict(gen) if gen else None
        if src is not self.src:
            self.set_src(src)


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


def _clip(a, b):
    """Intersection of two boxes, or None if they don't overlap."""
    if a is None or b is None:
        return None
    x0, y0, x1, y1 = max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])
    return (x0, y0, x1, y1) if x1 > x0 and y1 > y0 else None


def _union(a, b):
    """The smallest box containing two boxes (x0, y0, x1, y1); either may be None."""
    if a is None:
        return b
    if b is None:
        return a
    return (min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3]))


def _regions(old: list, new: list) -> list:
    """Rectangles to redraw when the copies' boxes go from `old` to `new`: each copy's old and new
    box joined, and rectangles that touch merged (so no pixel is drawn twice)."""
    rs = []
    for i in range(max(len(old), len(new))):
        r = _union(old[i] if i < len(old) else None, new[i] if i < len(new) else None)
        if r is not None:
            rs.append(r)
    merged = True
    while merged and len(rs) > 1:
        merged = False
        for i in range(len(rs)):
            for j in range(i + 1, len(rs)):
                a, b = rs[i], rs[j]
                if a[0] <= b[2] and b[0] <= a[2] and a[1] <= b[3] and b[1] <= a[3]:
                    rs[i] = _union(a, b)
                    del rs[j]
                    merged = True
                    break
            if merged:
                break
    return rs


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
    """Writes the deck colours into the first pixels of the texture's top row, where the game reads them."""
    for x, c in enumerate(pal[:min(len(pal), img.width)]):
        img.putpixel((x, 0), (int(c[0]), int(c[1]), int(c[2]), 255))


class Composer:
    """Base + layers + board colors -> texture. The layers below the selected one are cached
    as one image, so moving one sticker only re-renders that sticker - and while it is being
    dragged (fast=True), only inside the rectangle it moved through (last_region tells which)."""

    PAD = 6                         # room for the selection outline around a layer

    def __init__(self):
        """A composer with nothing cached yet."""
        self.invalidate()

    def invalidate(self):
        """Drops every cached image, so the next compose() renders everything again."""
        self._below = None
        self._work = None
        self._state = None
        self._sel_box = None
        self.last_region = None
        self.last_regions = None

    def compose(self, base: Image.Image, layers, sel, pal, fast=False, finish=None) -> Image.Image:
        """finish: an effects.Finish for the whole board (applied over the layers), or None."""
        W, H = base.size
        vis = [L for L in layers if L.visible]
        s = sel if sel in vis else None
        others = tuple(L.key() for L in vis if L is not s)
        if finish is not None and finish.identity:
            finish = None
        state = (id(base), base.size, s, tuple(map(tuple, pal)) if pal else None, others,
                 finish.key if finish is not None else None)
        self.last_region = None
        self.last_regions = None
        if fast and s is not None and self._work is not None and state == self._state and self._below is not None:
            boxes = s.bboxes(W, H, self.PAD)
            regions = _regions(self._sel_box or [], boxes)
            if not regions:
                return self._work
            above = vis[vis.index(s) + 1:]
            for region in regions:             # a mirrored layer: two small rectangles, not one long one
                img = self._below[1].crop(region)
                img.alpha_composite(s.render_box(W, H, region, fast=True))
                for L in above:
                    _paint(img, L, W, H, region)
                if finish is not None:
                    img = finish.apply(img, region)
                self._work.paste(img, region[:2])
                if pal and region[1] == 0 and region[0] < len(pal):
                    _put_palette(self._work, pal)
            self._sel_box = boxes
            self.last_regions = regions
            self.last_region = functools.reduce(_union, regions)
            return self._work
        work = self._compose_full(base, vis, s, pal, fast, finish)
        self._work, self._state = work, state
        self._sel_box = s.bboxes(W, H, self.PAD) if s is not None else None
        return work

    def _compose_full(self, base, vis, s, pal, fast, finish=None):
        """Renders the whole texture: the base with the layers below the selected one (cached), the selected layer,
        the layers above it, the board finish and the deck colours.
        """
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
        if finish is not None:
            img = finish.apply(img)
        if pal:
            _put_palette(img, pal)
        return img


def with_outline(work: Image.Image, layer: Optional[Layer], color, pal) -> Image.Image:
    """Copy of the texture with the selected layer's outline drawn in (for the 3D view only)."""
    if layer is None or not layer.visible:
        return work
    W, H = work.size
    out = work.copy()
    d = ImageDraw.Draw(out)
    for pts in layer.all_corners(W, H):
        d.line(pts + [pts[0]], fill=tuple(color[:3]) + (255,), width=max(3, W // 400))
    return apply_palette(out, pal) if pal else out


# ---------------------------------------------------------------- editable project files
def project_dir(texture_path: Path) -> Path:
    """Where a texture's decorating project (layers that stay editable) is saved: _board_defaults/decor/<texture
    file name>.
    """
    return Path(texture_path).parent / DEF_DIR / "decor" / Path(texture_path).name


def save_project(texture_path: Path, base: Image.Image, base_key: str, tint, tint_strength: float,
                 layers, result: Image.Image, finish: Optional[dict] = None) -> Path:
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
                        "opacity": L.opacity, "visible": L.visible,
                        "fx": {k: v for k, v in L.fx.items() if v},
                        "color": L.color if color_key(L.color) else {}, "mirror": L.mirror,
                        "gen": L.gen})
    meta = {"version": PROJECT_VERSION, "saved_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "base": base_key, "tint": list(tint[:3]) if tint else None, "tint_strength": tint_strength,
            "size": list(base.size), "result_sha256": pixel_hash(result), "layers": entries,
            "finish": {k: v for k, v in (finish or {}).items() if v}}
    atomic_write(tmp / "project.json", json.dumps(meta, indent=1).encode("utf-8"))
    shutil.rmtree(d, ignore_errors=True)
    tmp.rename(d)
    return d


def _num(v, lo=-1e6, hi=1e6, default=0.0):
    """A number read from a project file, made safe: not finite, out of [lo, hi] or not a number gives `default`.
    """
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
                                _num(e.get("opacity"), 0, 1, 1.0), bool(e.get("visible", True)),
                                _read_fx(e.get("fx"), STICKER_FX), _read_color(e.get("color")),
                                str(e.get("mirror") or ""), _read_gen(e.get("gen"))))
        tint = meta.get("tint")
        tint = tuple(int(_num(c, 0, 255)) for c in tint[:3]) if isinstance(tint, list) and len(tint) >= 3 else None
        return {"base": base, "base_key": str(meta.get("base") or "original"), "tint": tint,
                "tint_strength": _num(meta.get("tint_strength"), 0, 1), "layers": layers,
                "finish": _read_fx(meta.get("finish"), FINISH_FX),
                "saved_at": str(meta.get("saved_at", ""))}
    except Exception:
        return None


def _read_fx(d, known) -> dict:
    """Effect strengths from a project file: only known effects, 0..1, plus an integer seed."""
    out = {}
    if isinstance(d, dict):
        for k, _label, _help in known:
            v = _num(d.get(k), 0, 1)
            if v:
                out[k] = v
        if out and isinstance(d.get("seed"), int):
            out["seed"] = int(d["seed"]) & 0x7FFFFFFF
    return out


def _read_color(d) -> dict:
    """A layer's recolour settings read from a project file, with every value checked; {} when nothing is set.
    """
    if not isinstance(d, dict):
        return {}
    out = {"hue": _num(d.get("hue"), -180, 180), "sat": _num(d.get("sat"), 0, 2, 1.0),
           "tint_s": _num(d.get("tint_s"), 0, 1)}
    t = d.get("tint")
    if isinstance(t, list) and len(t) >= 3:
        out["tint"] = [int(_num(v, 0, 255)) for v in t[:3]]
    return out if color_key(out) else {}


def _read_gen(d) -> Optional[dict]:
    """Settings of a text / shape layer (only plain values of the known kinds)."""
    if not isinstance(d, dict) or d.get("kind") not in ("text", "shape"):
        return None
    out = {}
    for k, v in d.items():
        if isinstance(v, str):
            out[str(k)[:40]] = v[:400]
        elif isinstance(v, bool) or isinstance(v, (int, float)) and math.isfinite(float(v)):
            out[str(k)[:40]] = v
        elif isinstance(v, list) and len(v) <= 4 and all(isinstance(c, (int, float)) for c in v):
            out[str(k)[:40]] = [int(_num(c, 0, 255)) for c in v]
    return out


def drop_project(texture_path: Path):
    """Deletes a texture's saved decorating project."""
    shutil.rmtree(project_dir(texture_path), ignore_errors=True)
