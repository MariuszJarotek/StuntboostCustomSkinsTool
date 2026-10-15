"""Text maker: new unit text for the speedometer (CMS.xnb in normal mode, MMS.xnb in precise mode).

The game draws these files white-on-transparent: the bar texture colors the white and the game adds
the black outline itself (SM_OUTLINE in speedmeter.py), so the text is made white, with soft edges,
at the size of the file it replaces.
"""
from __future__ import annotations

import math
from typing import Optional

from .i18n import N_

from PIL import Image, ImageDraw, ImageFont

# label, font files to try (Windows names first; PIL also looks in the Windows fonts folder)
FONTS = [
    ("impact", N_("Impact"), ["impact.ttf", "Impact.ttf", "Anton-Regular.ttf"]),
    ("black", N_("Arial Black"), ["ariblk.ttf", "Arial Black.ttf", "ArchivoBlack-Regular.ttf"]),
    ("bahn", N_("Bahnschrift"), ["bahnschrift.ttf", "Bahnschrift.ttf"]),
    ("segoe", N_("Segoe Black"), ["seguibl.ttf", "Segoe UI Black.ttf"]),
    ("franklin", N_("Franklin Heavy"), ["FRAHV.TTF", "framd.ttf"]),
    ("verdana", N_("Verdana Bold"), ["verdanab.ttf", "Verdana Bold.ttf"]),
    ("mono", N_("Consolas Bold"), ["consolab.ttf", "Consolas Bold.ttf", "DejaVuSansMono-Bold.ttf",
                                   "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf"]),
    ("sans", N_("Sans Bold"), ["arialbd.ttf", "DejaVuSans-Bold.ttf",
                               "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"]),
]

QUICK_TEXTS = ["SPEED", "KM/H", "MPH", "BOOST", "GO!"]

DEFAULT = {"cms": "CM/S", "mms": "MM/S", "font": "impact", "file": None, "slant": 14.0,
           "spacing": 4.0, "size": 92.0, "weight": 0.0, "align": "left"}

_found: dict = {}


def font_path(key: str) -> Optional[str]:
    """The font file for a FONTS key that loads on this PC, or None."""
    if key in _found:
        return _found[key]
    names = next((f for k, _l, f in FONTS if k == key), [])
    hit = None
    for n in names:
        try:
            ImageFont.truetype(n, 20)
            hit = n
            break
        except OSError:
            continue
    _found[key] = hit
    return hit


def available_fonts():
    """The fonts of FONTS that are installed on this PC, as (key, label) pairs for the Text maker."""
    return [(k, label) for k, label, _f in FONTS if font_path(k)]


def _load(state, px):
    """The PIL font for the text maker's state at `px` pixels: the chosen font file, else the chosen built-in font,
    else the first installed one, else Pillow's default font.
    """
    f = state.get("file")
    if f:
        return ImageFont.truetype(str(f), px)
    p = font_path(state.get("font", "impact")) or next((font_path(k) for k, *_r in FONTS if font_path(k)), None)
    if p is None:
        return ImageFont.load_default()
    return ImageFont.truetype(p, px)


def _draw_line(text, font, spacing, weight):
    """Text drawn letter by letter (for the letter spacing), white on transparent, on a big canvas."""
    asc, desc = font.getmetrics()
    widths = [font.getlength(ch) for ch in text]
    W = int(sum(widths) + spacing * max(0, len(text) - 1) + 4 * weight + asc)
    H = int(asc + desc + 4 * weight + 8)
    im = Image.new("L", (max(1, W), max(1, H)), 0)
    d = ImageDraw.Draw(im)
    x = 2 * weight + 4
    for ch, w in zip(text, widths):
        d.text((x, 2 * weight + 4), ch, font=font, fill=255, stroke_width=int(weight), stroke_fill=255)
        x += w + spacing
    return im


def make_text(size, text: str, state: dict) -> Image.Image:
    """White unit text in a transparent image of `size` (the file it replaces)."""
    W, H = size
    st = {**DEFAULT, **state}
    out = Image.new("RGBA", (W, H), (255, 255, 255, 0))
    text = (text or "").strip()
    if not text:
        return out
    scale = 4                                                   # draw big, shrink at the end (smooth edges)
    target_h = max(4, H * st["size"] / 100.0)
    font = _load(st, int(round(target_h * scale * 1.25)))
    mask = _draw_line(text, font, st["spacing"] * scale, st["weight"] * scale)
    box = mask.getbbox()
    if not box:
        return out
    mask = mask.crop(box)
    sl = math.tan(math.radians(st["slant"]))
    if sl:                                                      # lean right, like the game's italic digits
        mw, mh = mask.size
        extra = int(math.ceil(sl * mh))
        # output x samples input x + sl*y - sl*mh: the top row moves right, the bottom stays put
        mask = mask.transform((mw + extra, mh), Image.AFFINE, (1, sl, -sl * mh, 0, 1, 0), resample=Image.BICUBIC)
        mask = mask.crop(mask.getbbox() or (0, 0, 1, 1))
    pad = 2
    k = min((target_h - 0) / mask.height, (W - 2 * pad) / mask.width, (H - 2 * pad) / mask.height)
    nw, nh = max(1, int(round(mask.width * k))), max(1, int(round(mask.height * k)))
    small = mask.resize((nw, nh), Image.LANCZOS)
    if st["align"] == "center":
        x = (W - nw) // 2
    elif st["align"] == "right":
        x = W - pad - nw
    else:
        x = pad
    y = (H - nh) // 2
    out.paste(Image.new("RGBA", (nw, nh), (255, 255, 255, 255)), (x, y), small)
    return out

