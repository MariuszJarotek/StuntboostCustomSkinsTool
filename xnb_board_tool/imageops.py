"""Positioning / zooming / rotating / flipping a new image before it replaces a texture."""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

from PIL import Image, ImageDraw


# --------------------------------------------------------------------------
#  Image adjustment (position / zoom / rotate / flip) for new images
# --------------------------------------------------------------------------
@dataclass
class Adjust:
    """How a new image is placed on a texture (what the Adjust window edits): the fit mode, extra zoom, rotation,
    flips, where the image's centre sits and an optional fill colour for the uncovered area.
    """
    mode: str = "fill"          # 'fill' (cover), 'fit' (contain) or 'stretch'
    zoom: float = 1.0           # multiplier on top of the mode's scale
    angle: float = 0.0          # degrees, clockwise on screen
    flip_h: bool = False
    flip_v: bool = False
    cx: Optional[float] = None  # image center in output pixels (None = centered)
    cy: Optional[float] = None
    bg: Optional[tuple] = None  # RGB fill for uncovered area (None = transparent)


def _trig(angle: float):
    """cos and sin of an angle in degrees, exact for multiples of 90 so straight images stay pixel-perfect."""
    a = angle % 360
    if a % 90 == 0:             # exact for right angles (no 1e-17 drift)
        return {0: (1, 0), 90: (0, 1), 180: (-1, 0), 270: (0, -1)}[int(a)]
    t = math.radians(a)
    return math.cos(t), math.sin(t)


def adjust_base_scale(bw: int, bh: int, W: int, H: int, adj: Adjust):
    """Output pixels per source pixel along the image's own x and y axes."""
    if adj.mode == "stretch":
        quarter = int(round(adj.angle / 90.0)) % 2      # stretch to the nearest right angle
        return (H / bw, W / bh) if quarter else (W / bw, H / bh)
    c, s = _trig(adj.angle)
    rw, rh = abs(bw * c) + abs(bh * s), abs(bw * s) + abs(bh * c)   # rotated bounding box
    k = max(W / rw, H / rh) if adj.mode == "fill" else min(W / rw, H / rh)
    return k, k


def render_adjusted(src: Image.Image, W: int, H: int, adj: Adjust, ps: float = 1.0,
                    margin: int = 0, resample=Image.BICUBIC, cache: Optional[dict] = None,
                    box=None) -> Image.Image:
    """Renders src placed on a W x H canvas according to adj.
    ps = preview scale (1 = final size); margin = extra pixels around the canvas
    (used by the preview to show the parts of the image that will be cut off).
    box = (x0, y0, x1, y1): render only that part of the W x H canvas (ps 1, no margin), e.g. the
    area a sticker covers; the result equals render_adjusted(...).crop(box)."""
    src = src.convert("RGBA")
    bw0, bh0 = src.size
    bsx, bsy = adjust_base_scale(bw0, bh0, W, H, adj)
    sx, sy = bsx * adj.zoom, bsy * adj.zoom
    # When shrinking a lot, pre-reduce the source so the result stays smooth (no aliasing)
    k = int(1.0 / max(1e-9, min(sx, sy) * ps))
    k = max(1, min(k, max(1, min(bw0, bh0) // 2)))
    key = (adj.flip_h, adj.flip_v, k)
    base = cache.get(key) if cache is not None else None
    if base is None:
        base = src
        if adj.flip_h:
            base = base.transpose(Image.FLIP_LEFT_RIGHT)
        if adj.flip_v:
            base = base.transpose(Image.FLIP_TOP_BOTTOM)
        if k > 1:
            base = base.reduce(k)
        if cache is not None:
            if len(cache) > 8:
                cache.clear()
            cache[key] = base
    if k > 1:
        sx, sy = sx * bw0 / base.width, sy * bh0 / base.height
    bw, bh = base.size
    cx = W / 2 if adj.cx is None else adj.cx
    cy = H / 2 if adj.cy is None else adj.cy
    c, s = _trig(adj.angle)
    # output pixel (x, y) -> canvas point t = ((x - margin) / ps, (y - margin) / ps)
    # source point u = center + diag(1/sx, 1/sy) * R(-angle) * (t - c)
    if box is not None:
        ps, margin = 1.0, 0
        mx, my = -float(box[0]), -float(box[1])
        size = (max(1, box[2] - box[0]), max(1, box[3] - box[1]))
    else:
        mx = my = margin / ps
        size = (max(1, round(W * ps)) + 2 * margin, max(1, round(H * ps)) + 2 * margin)
    coeffs = (c / (sx * ps), s / (sx * ps), bw / 2 + (c * (-mx - cx) + s * (-my - cy)) / sx,
              -s / (sy * ps), c / (sy * ps), bh / 2 + (-s * (-mx - cx) + c * (-my - cy)) / sy)
    out = base.transform(size, Image.AFFINE, coeffs, resample=resample, fillcolor=(0, 0, 0, 0))
    if adj.bg is not None and box is None:
        under = Image.new("RGBA", size, (0, 0, 0, 0))
        ImageDraw.Draw(under).rectangle(
            [margin, margin, size[0] - margin - 1, size[1] - margin - 1], fill=tuple(adj.bg[:3]) + (255,))
        out = Image.alpha_composite(under, out)
    return out
