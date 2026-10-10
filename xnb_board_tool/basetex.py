"""Base textures for decorating a board: built-in patterns (drawn in code) and your own images.

Built-ins are generated at the board texture's size, so they are always sharp. Your own
textures are images in the "textures" folder next to the program, resized to fit.
"""
from __future__ import annotations

import math
import random
from pathlib import Path
from typing import Optional

from PIL import Image, ImageChops, ImageDraw, ImageFilter

from .stickers import STICKER_EXT, _writable_dir, app_dir, images_in

ORIGINAL = "original"               # the board's own art


def _canvas(W, H, c=(14, 14, 16)):
    im = Image.new("RGB", (W, H), c)
    return im, ImageDraw.Draw(im)


def _k(W, H):                       # pattern scale relative to the game's 1920 x 432 boards
    return max(0.1, H / 432.0)


def black(W, H):
    return _canvas(W, H)[0]


def black_stripes(W, H):
    im, d = _canvas(W, H)
    k = _k(W, H)
    step, w = 64 * k, 22 * k
    x = -H
    while x < W:
        d.polygon([(x, H), (x + w, H), (x + w + H * 0.55, 0), (x + H * 0.55, 0)], fill=(40, 40, 44))
        x += step
    return im


def carbon(W, H):
    im, d = _canvas(W, H, (18, 18, 20))
    s = max(4, int(16 * _k(W, H)))
    for y in range(0, H, s):
        for x in range(0, W, s):
            if (x // s + y // s) % 2:
                d.rectangle([x, y, x + s - 1, y + s // 2 - 1], fill=(34, 34, 38))
                d.rectangle([x, y + s // 2, x + s - 1, y + s - 1], fill=(28, 28, 31))
            else:
                d.rectangle([x, y, x + s // 2 - 1, y + s - 1], fill=(24, 24, 27))
                d.rectangle([x + s // 2, y, x + s - 1, y + s - 1], fill=(30, 30, 33))
    return im


def checker(W, H):
    im, d = _canvas(W, H, (240, 240, 240))
    s = max(4, int(72 * _k(W, H)))
    for y in range(0, H, s):
        for x in range(0, W, s):
            if (x // s + y // s) % 2:
                d.rectangle([x, y, x + s - 1, y + s - 1], fill=(18, 18, 18))
    return im


def blueprint(W, H):
    im, d = _canvas(W, H, (16, 18, 24))
    s = max(4, int(48 * _k(W, H)))
    lw = max(1, int(2 * _k(W, H)))
    for x in range(0, W, s):
        d.line([x, 0, x, H], fill=(40, 60, 90), width=lw)
    for y in range(0, H, s):
        d.line([0, y, W, y], fill=(40, 60, 90), width=lw)
    return im


def sunset(W, H):
    im, d = _canvas(W, H)
    a, b, c = (255, 94, 58), (240, 60, 120), (60, 40, 140)
    for x in range(W):
        t = x / max(1, W - 1)
        if t < 0.5:
            col = tuple(int(a[i] + (b[i] - a[i]) * t * 2) for i in range(3))
        else:
            col = tuple(int(b[i] + (c[i] - b[i]) * (t - 0.5) * 2) for i in range(3))
        d.line([x, 0, x, H], fill=col)
    return im


def hazard(W, H):
    im, d = _canvas(W, H, (245, 190, 20))
    k = _k(W, H)
    step, w = 110 * k, 55 * k
    x = -H
    while x < W:
        d.polygon([(x, H), (x + w, H), (x + w + H, 0), (x + H, 0)], fill=(20, 20, 20))
        x += step
    return im


def camo(W, H):
    rnd = random.Random(3)
    im, d = _canvas(W, H, (70, 80, 55))
    k = _k(W, H)
    n = int(70 * (W / max(H, 1)) / (1920.0 / 432.0)) + 10      # same look at any resolution
    for col in ((95, 100, 70), (45, 52, 38), (120, 110, 80), (30, 34, 28)):
        for _ in range(n):
            x, y = rnd.uniform(0, W), rnd.uniform(0, H)
            r = rnd.uniform(30, 90) * k
            pts = [(x + r * math.cos(a) * rnd.uniform(.6, 1.3), y + r * math.sin(a) * rnd.uniform(.6, 1.3))
                   for a in [i * math.pi / 5 for i in range(10)]]
            d.polygon(pts, fill=col)
    return im.filter(ImageFilter.GaussianBlur(max(0.5, 2 * k)))


def grain(W, H):
    noise = Image.effect_noise((W, H), 40).convert("RGB")
    return Image.blend(noise, Image.new("RGB", (W, H), (30, 28, 26)), 0.75)


def flames(W, H):
    im, d = _canvas(W, H)
    k = _k(W, H)
    step = max(10, int(150 * k))
    for x0 in range(0, W, step):
        for col, f in (((220, 60, 20), 1.0), ((255, 150, 30), 0.66), ((255, 225, 80), 0.36)):
            pts = [(x0, H)]
            for i in range(41):
                t = i / 40
                pts.append((x0 + t * step,
                            H - (H * 0.85 * f) * math.sin(math.pi * t) ** 2 * (0.7 + 0.3 * math.sin(7 * t + x0 / k))))
            pts.append((x0 + step, H))
            d.polygon(pts, fill=col)
    return im


BUILTIN = [
    ("black", "Black", black), ("black-stripes", "Black stripes", black_stripes),
    ("carbon", "Carbon", carbon), ("checker", "Checker", checker),
    ("blueprint", "Blueprint grid", blueprint), ("sunset", "Sunset", sunset),
    ("hazard", "Hazard", hazard), ("camo", "Camo", camo), ("grain", "Grain", grain),
    ("flames", "Flames", flames),
]
_BY_KEY = {k: (label, f) for k, label, f in BUILTIN}


def texture_dir() -> Path:
    return _writable_dir(app_dir() / "textures", "textures")


def user_textures() -> list:
    """[(key 'file:<name>', label, path)] for the images in the textures folder."""
    d = texture_dir()
    return [("file:" + p.name, p.stem, p) for p in images_in(d)]


def add_user_textures(files) -> tuple:
    """Copies images into the textures folder. Returns (added, [(file, error)])."""
    d = texture_dir()
    added, errors = 0, []
    for f in files:
        try:
            im = Image.open(f)
            im.load()
            im = im.convert("RGBA")
            if max(im.size) > 4096:
                im.thumbnail((4096, 4096))
            dest = d / f"{Path(f).stem}.png"
            n = 2
            while dest.exists():
                dest, n = d / f"{Path(f).stem}-{n}.png", n + 1
            im.save(dest)
            added += 1
        except Exception as e:
            errors.append((Path(f).name, str(e)))
    return added, errors


def label_of(key: str) -> str:
    if key == ORIGINAL:
        return "Board's own art"
    if key in _BY_KEY:
        return _BY_KEY[key][0]
    if key.startswith("file:"):
        return Path(key[5:]).stem
    return key


def make_base(key: str, W: int, H: int, original: Optional[Image.Image] = None,
              tint=None, strength: float = 0.0) -> Image.Image:
    """RGBA base image of W x H for a base key; tint blends a color over it (strength 0..1)."""
    if key == ORIGINAL or key is None:
        img = (original or Image.new("RGBA", (W, H), (0, 0, 0, 255))).convert("RGBA")
        if img.size != (W, H):
            img = img.resize((W, H), Image.LANCZOS)
    elif key in _BY_KEY:
        img = _BY_KEY[key][1](W, H).convert("RGBA")
    elif key.startswith("file:"):
        p = texture_dir() / Path(key[5:]).name
        src = Image.open(p)
        src.load()
        src = src.convert("RGBA")
        # cover the board, centered (like the "Fill" mode)
        s = max(W / src.width, H / src.height)
        src = src.resize((max(1, round(src.width * s)), max(1, round(src.height * s))), Image.LANCZOS)
        x, y = (src.width - W) // 2, (src.height - H) // 2
        img = Image.new("RGBA", (W, H), (0, 0, 0, 255))
        img.alpha_composite(src.crop((x, y, x + W, y + H)))
    else:
        raise ValueError(f"unknown base texture: {key}")
    if tint is not None and strength > 0:
        col = Image.new("RGBA", (W, H), tuple(int(c) for c in tint[:3]) + (255,))
        # multiply keeps the pattern's light and dark parts, the blend sets how strong it is
        tinted = ImageChops.multiply(img, col) if sum(tint[:3]) < 3 * 250 else col
        lifted = Image.blend(tinted, col, 0.35)
        img = Image.blend(img, lifted, max(0.0, min(1.0, strength)))
    return img


def preview(key: str, W: int = 1920, H: int = 432, mask: Optional[Image.Image] = None,
            size=(240, 54), bg=(26, 28, 32)) -> Image.Image:
    """Small preview in the shape of the deck (mask = deck_top_mask of the texture size).
    Drawn at twice the preview size (not at full texture size), so it takes milliseconds."""
    gw = max(8, size[0] * 2)
    gh = max(4, round(gw * H / max(W, 1)))
    img = make_base(key, gw, gh).convert("RGB")
    if mask is not None:
        img = Image.composite(img, Image.new("RGB", (gw, gh), bg), mask.resize((gw, gh), Image.BILINEAR))
    return img.resize(size, Image.LANCZOS)


__all__ = ["ORIGINAL", "BUILTIN", "make_base", "preview", "label_of", "user_textures",
           "add_user_textures", "texture_dir", "STICKER_EXT"]
