"""Board colour sets picked from the artwork: border, under (bottom), wheels and truck."""
from __future__ import annotations

import colorsys
from typing import Optional

from .i18n import N_

from PIL import Image


def art_colors(img: Image.Image, mask: Optional[Image.Image] = None, n: int = 8) -> list:
    """The artwork's main colours as [(rgb, share)], most common first. Only the part that shows
    on the deck counts when a mask (white = visible) is given."""
    import numpy as np
    small = img.convert("RGB").resize((240, 54), Image.BILINEAR)
    px = np.asarray(small).reshape(-1, 3)
    if mask is not None:
        m = np.asarray(mask.convert("L").resize((240, 54), Image.BILINEAR)).reshape(-1) > 128
        if m.sum() > 200:
            px = px[m]
    q = Image.fromarray(px.reshape(1, -1, 3).astype(np.uint8), "RGB").quantize(colors=n, method=Image.Quantize.MEDIANCUT)
    pal = q.getpalette()[:3 * n]
    counts = np.bincount(np.asarray(q).reshape(-1), minlength=n)[:n]
    total = max(1, int(counts.sum()))
    out = [((pal[3 * i], pal[3 * i + 1], pal[3 * i + 2]), counts[i] / total) for i in range(n) if counts[i]]
    return sorted(out, key=lambda c: -c[1])


def _hsv(c):
    """An RGB colour (0-255) as hue, saturation, value (0-1)."""
    return colorsys.rgb_to_hsv(*(v / 255.0 for v in c[:3]))


def _rgb(h, s, v):
    """Hue, saturation, value (0-1, clamped) back to an RGB tuple (0-255)."""
    return tuple(int(round(x * 255)) for x in colorsys.hsv_to_rgb(h % 1.0, max(0, min(1, s)), max(0, min(1, v))))


def _dist(a, b):
    """Straight-line distance between two RGB colours (0 = the same colour)."""
    return sum((x - y) ** 2 for x, y in zip(a[:3], b[:3])) ** 0.5


def _shade(c, f):
    """f < 1 darker, f > 1 lighter (towards white)."""
    if f <= 1:
        return tuple(int(v * f) for v in c[:3])
    t = min(1.0, f - 1.0)
    return tuple(int(v + (255 - v) * t) for v in c[:3])


def suggestions(img: Image.Image, mask: Optional[Image.Image] = None) -> list:
    """[(name, [border, under, wheels, truck])]: a few colour sets that go with the artwork."""
    cols = art_colors(img, mask)
    if not cols:
        return []
    dominant = cols[0][0]
    by_v = sorted(cols, key=lambda c: _hsv(c[0])[2])
    darkest = next((c[0] for c in by_v if c[1] > 0.02), by_v[0][0])
    lightest = next((c[0] for c in reversed(by_v) if c[1] > 0.02), by_v[-1][0])

    def vivid_score(c):
        """How strong a colour from the artwork is: saturation x brightness, nudged up by how much of the image it
        covers.
        """
        h, s, v = _hsv(c[0])
        return s * v * (c[1] ** 0.25)
    vivid_list = sorted(cols, key=lambda c: -vivid_score(c))
    vivid = vivid_list[0][0]
    vh = _hsv(vivid)[0]
    second = next((c[0] for c in vivid_list[1:]
                   if _hsv(c[0])[1] > 0.25 and min(abs(_hsv(c[0])[0] - vh), 1 - abs(_hsv(c[0])[0] - vh)) > 0.08),
                  _shade(vivid, 0.6))
    if _hsv(vivid)[1] < 0.2:                    # artwork without real colour: make the accent pop
        vivid = _rgb(_hsv(dominant)[0], 0.75, 0.95)
    h, s, v = _hsv(dominant)
    grey = _rgb(h, min(s, 0.08), 0.68)          # a metal truck, very slightly in the art's tone
    sets = [
        (N_("Accent wheels"), [dominant, darkest, vivid, grey]),
        (N_("Two accents"), [lightest if _dist(lightest, vivid) > 60 else dominant, dominant, vivid, second]),
        (N_("Tonal"), [dominant, _shade(dominant, 0.45), _shade(dominant, 1.35), _shade(dominant, 0.7)]),
        (N_("Contrast"), [darkest, darkest, _shade(vivid, 1.25) if _hsv(vivid)[2] < 0.6 else vivid, lightest]),
    ]
    out, seen = [], set()
    for name, cs in sets:
        cs = [tuple(int(v) for v in c[:3]) for c in cs]
        k = tuple(cs)
        if k not in seen:
            seen.add(k)
            out.append((name, cs))
    return out


__all__ = ["art_colors", "suggestions"]
