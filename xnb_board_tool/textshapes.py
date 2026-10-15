"""Text and simple-shape layers: images made from settings, so they can be edited later.

Text uses the fonts installed on the PC (Windows: C:\\Windows\\Fonts and the user's fonts
folder), with Pillow's built-in font as a fallback. Shapes are drawn in code.
A layer keeps its settings in Layer.gen: {'kind': 'text', ...} or {'kind': 'shape', ...}.
"""
from __future__ import annotations

from .i18n import N_, _

import math
import os
import sys
import threading
from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw, ImageFont

FONT_EXT = (".ttf", ".otf", ".ttc")
PREFERRED = ("Impact Regular", "Arial Black Regular", "Arial Bold", "Segoe UI Black", "Bahnschrift Bold",
             "Verdana Bold", "DejaVu Sans Bold", "Liberation Sans Bold")
BUILTIN_FONT = "Built-in (Aileron)"

_fonts: Optional[dict] = None
_lock = threading.Lock()


def font_dirs() -> list:
    """The folders the installed fonts live in on this system (Windows, macOS or Linux), user fonts included."""
    dirs = []
    if sys.platform == "win32":
        win = os.environ.get("WINDIR", r"C:\\Windows")
        dirs.append(Path(win) / "Fonts")
        la = os.environ.get("LOCALAPPDATA")
        if la:
            dirs.append(Path(la) / "Microsoft" / "Windows" / "Fonts")
    elif sys.platform == "darwin":
        dirs += [Path("/System/Library/Fonts"), Path("/Library/Fonts"), Path.home() / "Library" / "Fonts"]
    else:
        dirs += [Path("/usr/share/fonts"), Path("/usr/local/share/fonts"), Path.home() / ".fonts",
                 Path.home() / ".local" / "share" / "fonts"]
    return [d for d in dirs if d.is_dir()]


def fonts() -> dict:
    """{'Family Style': path} of the installed fonts (scanned once, ~1 s on a typical PC)."""
    global _fonts
    with _lock:
        if _fonts is not None:
            return _fonts
        found = {}
        for d in font_dirs():
            for p in sorted(d.rglob("*")):
                if p.suffix.lower() not in FONT_EXT or not p.is_file():
                    continue
                try:
                    fam, style = ImageFont.truetype(str(p), 12).getname()
                except Exception:
                    continue
                if not fam:
                    continue
                name = f"{fam} {style}".strip() if style else fam
                found.setdefault(name, str(p))
        _fonts = dict(sorted(found.items(), key=lambda kv: kv[0].lower()))
        return _fonts


def font_names() -> list:
    """Every font the text layers offer: the built-in one first, then the installed fonts."""
    return [BUILTIN_FONT] + list(fonts())


def default_font() -> str:
    """The font a new text layer starts with: a preferred bold display font when installed, else any bold or black
    font, else the first font found.
    """
    f = fonts()
    for n in PREFERRED:
        if n in f:
            return n
    bold = [n for n in f if "bold" in n.lower() or "black" in n.lower()]
    return bold[0] if bold else (next(iter(f)) if f else BUILTIN_FONT)


def _font(name: str, size: int):
    """A PIL font by name at `size` pixels; falls back to Pillow's scalable default font (or its small bitmap font
    on old Pillow).
    """
    path = fonts().get(name)
    if path:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            pass
    try:
        return ImageFont.load_default(size=size)        # Pillow 10.1+: a real, scalable font
    except TypeError:
        return ImageFont.load_default()


def default_text() -> dict:
    """The settings of a new text layer ('SKATE' in white with a dark outline)."""
    return {"kind": "text", "text": "SKATE", "font": default_font(), "color": [255, 255, 255],
            "outline": [20, 20, 22], "outline_w": 0.06, "spacing": 0.0}


def render_text(g: dict) -> Image.Image:
    """The text as an RGBA image, cropped tight (a little room for the outline)."""
    text = str(g.get("text") or " ")[:200]
    size = 220
    font = _font(str(g.get("font") or BUILTIN_FONT), size)
    ow = max(0, int(round(float(g.get("outline_w", 0.0)) * size)))
    fill = tuple(int(c) for c in (g.get("color") or (255, 255, 255))[:3]) + (255,)
    stroke = tuple(int(c) for c in (g.get("outline") or (0, 0, 0))[:3]) + (255,)
    tmp = ImageDraw.Draw(Image.new("RGBA", (8, 8)))
    sp = int(round(float(g.get("spacing", 0.0)) * size))
    box = [int(math.floor(v)) if i < 2 else int(math.ceil(v)) for i, v in
           enumerate(tmp.multiline_textbbox((0, 0), text, font=font, stroke_width=ow, align="center", spacing=sp))]
    pad = 6 + ow
    w, h = box[2] - box[0] + 2 * pad, box[3] - box[1] + 2 * pad
    img = Image.new("RGBA", (max(8, w), max(8, h)), (0, 0, 0, 0))
    ImageDraw.Draw(img).multiline_text((pad - box[0], pad - box[1]), text, font=font, fill=fill,
                                       stroke_width=ow, stroke_fill=stroke, align="center", spacing=sp)
    bb = img.getchannel("A").getbbox()
    if bb:
        img = img.crop((max(0, bb[0] - 4), max(0, bb[1] - 4), min(img.width, bb[2] + 4), min(img.height, bb[3] + 4)))
    return img


# ---------------------------------------------------------------- shapes
SHAPES = (
    ("stripes", N_("Racing stripes")), ("stripe", N_("Center stripe")), ("circle", N_("Circle")), ("ring", N_("Ring")),
    ("star", N_("Star")), ("triangle", N_("Triangle")), ("diamond", N_("Diamond")), ("chevron", N_("Chevron")),
    ("bar", N_("Rounded bar")),
)
SHAPE_LABELS = dict(SHAPES)
BOARD_SHAPES = ("stripes", "stripe")            # made to cover the whole board


def default_shape(kind: str) -> dict:
    """The settings of a new shape layer of the given kind (orange)."""
    return {"kind": "shape", "shape": kind, "color": [240, 168, 48]}


def render_shape(g: dict, board_size=(1920, 432)) -> Image.Image:
    """The shape as an RGBA image (drawn 3x larger and reduced: smooth edges). Stripes are made
    in the board's proportions, to cover the whole deck."""
    kind = str(g.get("shape", "circle"))
    col = tuple(int(c) for c in (g.get("color") or (240, 168, 48))[:3]) + (255,)
    ss = 3
    if kind in BOARD_SHAPES:
        W, H = board_size
        w, h = W * ss // 2, H * ss // 2
        im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        if kind == "stripes":
            sw, gap = h * 0.075, h * 0.05
            for y0 in (h / 2 - gap / 2 - sw, h / 2 + gap / 2):
                d.rectangle([0, y0, w, y0 + sw], fill=col)
        else:
            sw = h * 0.16
            d.rectangle([0, h / 2 - sw / 2, w, h / 2 + sw / 2], fill=col)
        return im.resize((w // ss, h // ss), Image.LANCZOS)
    n = 300 * ss
    im = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    c, r = n / 2, n * 0.47
    if kind == "circle":
        d.ellipse([c - r, c - r, c + r, c + r], fill=col)
    elif kind == "ring":
        d.ellipse([c - r, c - r, c + r, c + r], fill=col)
        ri = r * 0.68
        d.ellipse([c - ri, c - ri, c + ri, c + ri], fill=(0, 0, 0, 0))
    elif kind == "star":
        pts = []
        for i in range(10):
            a = -math.pi / 2 + i * math.pi / 5
            rr = r if i % 2 == 0 else r * 0.45
            pts.append((c + rr * math.cos(a), c + r * 0.08 + rr * math.sin(a)))
        d.polygon(pts, fill=col)
    elif kind == "triangle":
        d.polygon([(c, c - r), (c + r * 0.95, c + r * 0.75), (c - r * 0.95, c + r * 0.75)], fill=col)
    elif kind == "diamond":
        d.polygon([(c, c - r), (c + r * 0.7, c), (c, c + r), (c - r * 0.7, c)], fill=col)
    elif kind == "chevron":
        t = r * 0.42
        d.polygon([(c - r, c - r * 0.55), (c - r + t, c - r * 0.55), (c, c + r * 0.15 - t * 0.6),
                   (c + r - t, c - r * 0.55), (c + r, c - r * 0.55), (c, c + r * 0.6)], fill=col)
    else:                                        # rounded bar
        d.rounded_rectangle([c - r, c - r * 0.22, c + r, c + r * 0.22], radius=int(r * 0.22), fill=col)
    im = im.resize((n // ss, n // ss), Image.LANCZOS)
    bb = im.getchannel("A").getbbox()
    return im.crop((max(0, bb[0] - 2), max(0, bb[1] - 2), min(im.width, bb[2] + 2), min(im.height, bb[3] + 2))) if bb else im


def render_gen(g: dict, board_size=(1920, 432)) -> Image.Image:
    """Draws a generated layer (text or shape) to an RGBA image; shapes are sized for the board texture."""
    return render_text(g) if g.get("kind") == "text" else render_shape(g, board_size)


def gen_name(g: dict) -> str:
    """The name a generated layer shows in the layer list: the text in quotes (shortened), or the shape's name.
    """
    if g.get("kind") == "text":
        t = " ".join(str(g.get("text") or "").split())
        return ("\u201c" + (t[:22] + "\u2026" if len(t) > 23 else t) + "\u201d") if t else _("Text")
    return _(SHAPE_LABELS.get(str(g.get("shape")), "Shape"))


__all__ = ["fonts", "font_names", "default_font", "default_text", "render_text", "SHAPES", "SHAPE_LABELS",
           "BOARD_SHAPES", "default_shape", "render_shape", "render_gen", "gen_name", "BUILTIN_FONT"]
