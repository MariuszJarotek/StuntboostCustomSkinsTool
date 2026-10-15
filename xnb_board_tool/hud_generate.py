"""Generate bar texture: a new Texture.xnb for the speedometer, made from a few choices.

How the game uses the texture (see speedmeter.py): every bright part of the HUD is white in its own
file and shows this texture through it. Only rows 68-154 are seen. The bar's tip shows texture column
370 + 0.7 * bar length (the texture scrolls 0.3 px per bar pixel, up to 930 px at 3100 px = 75.6 cm/s);
past the edges the game mirrors the texture. So a column of the texture belongs to one speed, and a
style that changes along the columns changes with the speed.
"""
from __future__ import annotations

import colorsys
import math

from .i18n import N_

from PIL import Image, ImageChops, ImageDraw

from .speedmeter import SM_PX_PER_CMS

USED_ROWS = (68, 154)

# key, name, uses colors (how many), uses the size slider, short help
STYLES = [
    ("solid", N_("Solid"), 1, False, N_("One color everywhere")),
    ("gradient", N_("Gradient"), 3, False, N_("Colors run from slow to fast: the bar's tip shows the speed")),
    ("zones", N_("Speed zones"), 3, False, N_("Hard color steps at two speeds, like a rev counter")),
    ("stripes", N_("Chevrons"), 2, True, N_("Arrow stripes pointing forward (the game mirrors the lower half of the bar)")),
    ("checker", N_("Checker"), 2, True, N_("Squares in two colors")),
    ("carbon", N_("Carbon"), 2, True, N_("A woven carbon-fibre look")),
    ("rainbow", N_("Rainbow"), 0, False, N_("Every color, from slow to fast")),
    ("deck", N_("Deck art"), 0, True, N_("The artwork of the deck selected on the Decks tab, repeated along the bar")),
]
STYLE_KEYS = [s[0] for s in STYLES]

DEFAULT = {"style": "gradient", "colors": [(60, 220, 90), (255, 196, 0), (255, 64, 32)],
           "size": 60, "full": 75.0, "zone1": 25.0, "zone2": 50.0, "shine": True}


def tip_column(cms: float) -> float:
    """Texture column at the bar's tip at a speed (cm/s)."""
    px = SM_PX_PER_CMS * max(0.0, cms)
    return 370 + 0.7 * px if px < 3100 else px - 560


def _lerp(a, b, f):
    """Linear mix of two RGB colours: f = 0 gives a, f = 1 gives b."""
    return tuple(int(round(x + (y - x) * f)) for x, y in zip(a, b))


def _ramp_colors(stops, t):
    """The colour at position t (0-1) of a ramp through the given stops."""
    n = len(stops) - 1
    if n <= 0:
        return tuple(stops[0])
    t = min(1.0, max(0.0, t)) * n
    i = min(n - 1, int(t))
    return _lerp(stops[i], stops[i + 1], t - i)


def _columns(W, H, color_at):
    """An image whose color depends only on the column: color_at(u) -> rgb, sampled every 2 px."""
    row = Image.new("RGB", (W, 1))
    row.putdata([color_at(u) for u in range(W)])
    return row.resize((W, H), Image.NEAREST)


def _shine(img: Image.Image) -> Image.Image:
    """A rounded, lit look: a bright line along the bar's middle, darker towards its edges."""
    W, H = img.size
    r0, r1 = USED_ROWS[0], min(USED_ROWS[1], H)
    mul, add = Image.new("L", (1, H)), Image.new("L", (1, H))
    for y in range(H):
        v = min(1.0, max(0.0, (y - r0) / max(1, r1 - r0)))
        # the bar shows rows ~86-154 in its upper half and the same rows mirrored below, so row 154
        # is the bar's middle: brightest there (a round tube), darker towards both edges
        k = 0.66 + 0.34 * v + 0.38 * math.exp(-((v - 0.82) / 0.1) ** 2)
        mul.putpixel((0, y), int(round(255 * min(1.0, k))))
        add.putpixel((0, y), int(round(255 * max(0.0, k - 1.0))))
    mul, add = mul.resize((W, H), Image.NEAREST), add.resize((W, H), Image.NEAREST)
    out = ImageChops.multiply(img.convert("RGB"), Image.merge("RGB", (mul, mul, mul)))
    return ImageChops.screen(out, Image.merge("RGB", (add, add, add)))


def generate(size, state: dict, deck_img=None) -> Image.Image:
    """The new bar texture, size = (W, H) of the current one."""
    W, H = size
    st = {**DEFAULT, **state}
    cols = [tuple(c) for c in st["colors"]]
    style = st["style"]
    span0, span1 = tip_column(0), tip_column(max(5.0, st["full"]))
    if style == "solid":
        img = Image.new("RGB", (W, H), cols[0])
    elif style == "gradient":
        img = _columns(W, H, lambda u: _ramp_colors(cols, (u - span0) / (span1 - span0)))
    elif style == "rainbow":
        def rb(u):
            """Rainbow: the colour at bar position u (red at the start, through the hues, magenta at the end).
            """
            t = min(1.0, max(0.0, (u - span0) / (span1 - span0)))
            return tuple(int(round(c * 255)) for c in colorsys.hsv_to_rgb(0.83 * t, 0.9, 1.0))
        img = _columns(W, H, rb)
    elif style == "zones":
        z1, z2 = sorted((st["zone1"], st["zone2"]))
        b1, b2 = tip_column(z1), tip_column(z2)
        soft = 18

        def zc(u):
            """Speed zones: the colour at bar position u, with hard steps at the two zone borders (softened over a
            few pixels).
            """
            if u < b1 - soft:
                return cols[0]
            if u < b1 + soft:
                return _lerp(cols[0], cols[1], (u - b1 + soft) / (2 * soft))
            if u < b2 - soft:
                return cols[1]
            if u < b2 + soft:
                return _lerp(cols[1], cols[2], (u - b2 + soft) / (2 * soft))
            return cols[2]
        img = _columns(W, H, zc)
    elif style == "stripes":
        img = Image.new("RGB", (W, H), cols[0])
        d = ImageDraw.Draw(img)
        w = max(6, int(st["size"]))
        # leaning back in the texture: the game shows these rows in the bar's upper half and mirrored
        # in its lower half, which turns the stripes into arrows pointing forward
        slant = 0.4 * H
        for x in range(-2 * w, W + int(slant) + 2 * w, 2 * w):
            d.polygon([(x, H), (x + w, H), (x + w - slant, 0), (x - slant, 0)], fill=cols[1])
    elif style == "checker":
        img = Image.new("RGB", (W, H), cols[0])
        d = ImageDraw.Draw(img)
        s = max(6, int(st["size"]) // 2)
        for y in range(0, H, s):
            for x in range((y // s % 2) * s, W, 2 * s):
                d.rectangle([x, y, x + s - 1, y + s - 1], fill=cols[1])
    elif style == "carbon":
        s = max(4, int(st["size"]) // 6)
        tile = Image.new("RGB", (4 * s, 4 * s), cols[0])
        d = ImageDraw.Draw(tile)
        for k in range(4):                  # a 2/2 twill: each thread lit along its length
            for j in range(2):
                x, y = ((k + 2 * j) % 4) * s, k * s
                for i in range(s):
                    d.line([(x, y + i), (x + s - 1, y + i)], fill=_lerp(cols[0], cols[1], 0.35 + 0.65 * math.sin(math.pi * (i + 0.5) / s)))
                x2, y2 = (k * s + 2 * s) % (4 * s), ((k + 1) % 4) * s
                for i in range(s):
                    d.line([(x2 + i, y2), (x2 + i, y2 + s - 1)], fill=_lerp(cols[0], cols[1], 0.15 + 0.45 * math.sin(math.pi * (i + 0.5) / s)))
        img = Image.new("RGB", (W, H))
        for y in range(0, H, tile.height):
            for x in range(0, W, tile.width):
                img.paste(tile, (x, y))
    elif style == "deck":
        if deck_img is None:
            raise ValueError("no deck selected")
        art = deck_img.convert("RGB")
        if art.height > 2:
            art = art.crop((0, 1, art.width, art.height))     # the palette row isn't artwork
        band = USED_ROWS[1] - USED_ROWS[0]
        zoom = max(0.5, min(3.0, st["size"] / 60.0))
        th = max(8, int(round(band * zoom)))
        tw = max(8, int(round(art.width * th / art.height)))
        art = art.resize((tw, th), Image.LANCZOS)
        img = Image.new("RGB", (W, H))
        y0 = USED_ROWS[0] - (th - band) // 2 - th * ((USED_ROWS[0] + th) // th)
        for y in range(y0, H, th):
            for x in range(0, W, tw):
                img.paste(art, (x, y))
    else:
        raise ValueError(f"unknown style {style}")
    if st.get("shine"):
        img = _shine(img)
    return img.convert("RGBA")


def style_swatch(key, size=(64, 14)) -> Image.Image:
    """A small picture of a style for its button."""
    W, H = size
    demo = {"solid": {"colors": [(255, 106, 43)]},
            "gradient": {"colors": [(255, 64, 32), (255, 196, 0), (60, 220, 90)]},
            "zones": {"colors": [(60, 220, 90), (255, 196, 0), (255, 64, 32)]},
            "stripes": {"colors": [(23, 22, 26), (255, 106, 43)], "size": 14},
            "checker": {"colors": [(23, 22, 26), (235, 232, 225)], "size": 14},
            "carbon": {"colors": [(20, 20, 22), (120, 120, 128)], "size": 24},
            "rainbow": {}}
    if key == "deck":
        im = Image.new("RGB", (W, H), (60, 60, 64))
        d = ImageDraw.Draw(im)
        for x in range(0, W, 10):
            d.ellipse([x + 2, 3, x + 8, 9], fill=(255, 106, 43))
        return im
    if key in ("gradient", "zones", "rainbow"):
        big = generate((3699, 154), {"style": key, **demo.get(key, {}), "shine": False})
        u0, u1 = int(tip_column(0)), int(tip_column(75))
        return big.crop((u0, 68, u1, 154)).convert("RGB").resize((W, H), Image.NEAREST)
    big = generate((W * 4, 154), {"style": key, **demo.get(key, {}), "shine": False})
    return big.crop((0, 68, W * 4, 68 + H * 4)).convert("RGB").resize((W, H), Image.LANCZOS)
