"""The app's logo (amber tile with a skateboard): one drawing for the .exe icon and the window icon."""
from __future__ import annotations

from PIL import Image, ImageDraw

ICON_SIZES = (16, 24, 32, 48, 64, 128, 256)


def draw_icon(size: int = 256) -> Image.Image:
    """The logo as an RGBA image of size x size (drawn at 256 and scaled down)."""
    S = 256
    im = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle([8, 8, S - 8, S - 8], radius=48, fill=(240, 168, 48, 255))
    dark = (20, 21, 24, 255)
    d.rounded_rectangle([44, 92, S - 44, 152], radius=30, outline=dark, width=16)
    for cx in (84, S - 84):
        d.ellipse([cx - 16, 168, cx + 16, 200], fill=dark)
    return im if size == S else im.resize((size, size), Image.LANCZOS)


def save_ico(path) -> None:
    """Multi-size Windows .ico of the logo."""
    draw_icon(256).save(path, sizes=[(s, s) for s in ICON_SIZES])


__all__ = ["draw_icon", "save_ico", "ICON_SIZES"]
