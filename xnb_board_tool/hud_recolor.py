"""Recolor HUD: new colors for the speedometer's bar texture.

Everything bright in the HUD (bar, blocks, unit text, digits) is white in its own file and gets its
color from the bar texture (Texture.xnb) in the game's shader, so recoloring that one texture
recolors the whole speedometer. The black outline is drawn black by the game and stays black.
"""
from __future__ import annotations

from .i18n import N_

from PIL import Image, ImageChops

# Rows of the bar texture the speedometer actually shows (see SpeedmeterMixin._sm_texture_usage).
USED_ROWS = (68, 154)

# "Along the bar": the bar's leading edge sits at texture column 370 + 0.7 * bar length (the
# texture scrolls 0.3 px per bar pixel), up to the 930 px scroll limit at 3100 px = 75.6 cm/s.
ALONG_FROM, ALONG_TO = 370, 370 + int(0.7 * 3100)

# name, stops (dark -> light), fill
PRESETS = [
    ("fire", N_("Fire"), [(96, 8, 0), (236, 64, 12), (255, 214, 72)], "shade"),
    ("ice", N_("Ice"), [(8, 36, 92), (36, 148, 232), (222, 250, 255)], "shade"),
    ("toxic", N_("Toxic"), [(8, 56, 12), (84, 204, 28), (226, 255, 120)], "shade"),
    ("gold", N_("Gold"), [(72, 40, 0), (204, 142, 20), (255, 236, 150)], "shade"),
    ("violet", N_("Violet"), [(40, 0, 84), (152, 40, 232), (255, 172, 255)], "shade"),
    ("mono", N_("Mono"), [(36, 36, 38), (150, 150, 152), (250, 250, 250)], "shade"),
    ("sunset", N_("Sunset"), [(70, 0, 130), (255, 56, 88), (255, 204, 0)], "along"),
    ("neon", N_("Neon"), [(0, 230, 255), (255, 0, 160), (140, 0, 255)], "along"),
]


def _lut(stops, lo=0, hi=255):
    """3 x 256 lookup tables mapping 0..255 onto the color stops (lo..hi is stretched to the full range)."""
    n = len(stops) - 1
    out = ([], [], [])
    span = max(1, hi - lo)
    for v in range(256):
        t = min(1.0, max(0.0, (v - lo) / span)) * n
        i = min(n - 1, int(t))
        f = t - i
        a, b = stops[i], stops[i + 1]
        for ch in range(3):
            out[ch].append(int(round(a[ch] + (b[ch] - a[ch]) * f)))
    return out


def _used_range(lum: Image.Image):
    """Darkest/brightest shade in the rows the HUD shows (1st/99th percentile, so specks don't count)."""
    h = lum.height
    r0, r1 = min(USED_ROWS[0], h - 1), min(USED_ROWS[1], h)
    hist = lum.crop((0, r0, lum.width, max(r0 + 1, r1))).histogram()
    total = sum(hist)
    acc, lo, hi = 0, 0, 255
    for v, c in enumerate(hist):
        acc += c
        if acc >= total * 0.01:
            lo = v
            break
    acc = 0
    for v in range(255, -1, -1):
        acc += hist[v]
        if acc >= total * 0.01:
            hi = v
            break
    if hi - lo < 24:                     # a flat texture: spread the gradient around its shade
        mid = (lo + hi) // 2
        lo, hi = max(0, mid - 96), min(255, mid + 96)
    return lo, hi


def recolor_shift(img: Image.Image, hue=0.0, sat=1.0, bright=0.0) -> Image.Image:
    """Keeps the pattern: turns the hue by `hue` degrees, scales saturation by `sat` (0..2) and moves
    brightness by `bright` (-1..1: towards black / towards white)."""
    img = img.convert("RGBA")
    a = img.getchannel("A")
    h, s, v = img.convert("RGB").convert("HSV").split()
    dh = int(round(hue / 360.0 * 256)) % 256
    if dh:
        h = h.point(lambda x: (x + dh) % 256)
    if sat != 1.0:
        s = s.point(lambda x: max(0, min(255, int(round(x * sat)))))
    if bright:
        if bright > 0:
            v = v.point(lambda x: int(round(x + (255 - x) * bright)))
        else:
            v = v.point(lambda x: int(round(x * (1 + bright))))
    out = Image.merge("HSV", (h, s, v)).convert("RGB").convert("RGBA")
    if bright > 0:                        # white needs saturation to fall as brightness rises
        out = Image.blend(out, Image.merge("RGB", (v, v, v)).convert("RGBA"), bright * 0.6)
    out.putalpha(a)
    return out


def recolor_gradient(img: Image.Image, stops, fill="shade") -> Image.Image:
    """New colors from 2+ stops (dark -> light).
    fill="shade": each pixel takes the stop color of its brightness (the pattern stays visible).
    fill="along": the colors run along the bar, so the bar's tip changes color as the speed rises;
    the texture's own shading is kept on top."""
    img = img.convert("RGBA")
    a = img.getchannel("A")
    lum = img.convert("L")
    lo, hi = _used_range(lum)
    if fill == "along":
        W, H = img.size
        ramp = Image.new("L", (W, 1))
        ramp.putdata([int(round(255 * min(1.0, max(0.0, (x - ALONG_FROM) / (ALONG_TO - ALONG_FROM)))))
                      for x in range(W)])
        r, g, b = _lut(stops)
        color = Image.merge("RGB", (ramp.point(r), ramp.point(g), ramp.point(b))).resize((W, H), Image.NEAREST)
        # shading: the texture's brightness, squeezed to 55..100 % so the colors stay strong
        shade = lum.point(lambda x: int(round(140 + 115 * min(1.0, max(0.0, (x - lo) / max(1, hi - lo))))))
        out = ImageChops.multiply(color, Image.merge("RGB", (shade, shade, shade)))
    else:
        r, g, b = _lut(stops, lo, hi)
        out = Image.merge("RGB", (lum.point(r), lum.point(g), lum.point(b)))
    out = out.convert("RGBA")
    out.putalpha(a)
    return out


def recolor(img: Image.Image, state: dict) -> Image.Image:
    """state: {'method': 'shift'|'colors', 'hue', 'sat', 'bright', 'stops', 'fill'}"""
    if state.get("method") == "colors":
        return recolor_gradient(img, state["stops"], state.get("fill", "shade"))
    return recolor_shift(img, state.get("hue", 0.0), state.get("sat", 1.0), state.get("bright", 0.0))


def is_identity(state: dict) -> bool:
    """True when the recolor settings would leave the texture unchanged (shift mode with no hue, saturation or
    brightness change), so nothing needs to be written.
    """
    return state.get("method") != "colors" and not state.get("hue") and state.get("sat", 1.0) == 1.0 \
        and not state.get("bright")


def deck_colors(img: Image.Image, n=3):
    """The n main colors of a deck's artwork (skips the palette row), dark -> light."""
    art = img.convert("RGB")
    if art.height > 2:
        art = art.crop((0, 1, art.width, art.height))
    small = art.resize((160, 36), Image.BILINEAR)
    q = small.quantize(colors=max(n, 2), method=Image.Quantize.MEDIANCUT)
    pal = q.getpalette()[:3 * max(n, 2)]
    counts = sorted(q.getcolors(), reverse=True)
    cols = [tuple(pal[3 * i:3 * i + 3]) for _c, i in counts][:n]
    while len(cols) < n:
        cols.append(cols[-1] if cols else (128, 128, 128))
    lum = lambda c: 0.299 * c[0] + 0.587 * c[1] + 0.114 * c[2]
    cols = sorted(cols, key=lum)
    if lum(cols[-1]) - lum(cols[0]) < 60:     # a one-color deck: shades of its main color
        main = max(cols, key=lambda c: max(c) - min(c)) if any(max(c) - min(c) > 24 for c in cols) \
            else cols[len(cols) // 2]
        def mix(c, t, k):
            """Mixes colour c towards colour t by k (0 = c, 1 = t)."""
            return tuple(int(round(a + (b - a) * k)) for a, b in zip(c, t))
        if lum(main) < 70:                    # very dark: lift it so the HUD stays readable
            main = mix(main, (255, 255, 255), 0.35)
        cols = [mix(main, (0, 0, 0), 0.55), main, mix(main, (255, 255, 255), 0.55)]
    return cols


def gradient_swatch(stops, size=(64, 14)) -> Image.Image:
    """A small picture of a colour ramp (the preset chips): the stops spread from left to right."""
    W, H = size
    ramp = Image.new("L", (W, 1))
    ramp.putdata([int(round(255 * x / max(1, W - 1))) for x in range(W)])
    r, g, b = _lut(stops)
    return Image.merge("RGB", (ramp.point(r), ramp.point(g), ramp.point(b))).resize((W, H), Image.NEAREST)
