"""Finding boards in a content folder, and the 4 board-color pixels."""
from __future__ import annotations

from .i18n import N_, _

import os
import re
import struct
import urllib.parse
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from PIL import Image

from .qoi import _qoi_first_pixels
from .xnb import parse_xnb, peek_kind, read_model_json


# --------------------------------------------------------------------------
#  Board discovery
# --------------------------------------------------------------------------
@dataclass
class Board:
    """One deck of the game: its name and the files that make it - the 3D model (when the folder has models), the
    texture (the artwork) and the thumbnail shown in the board shop. Any of the files may be missing.
    """
    name: str
    model: Optional[Path] = None
    texture: Optional[Path] = None
    thumb: Optional[Path] = None


THUMB_RE = re.compile(r"thumb|icon|preview", re.I)


def scan(root: Path) -> list[Board]:
    """Finds every board under a content folder (every .xnb is peeked at; other files are skipped).

    1. Pairs: '<name>.xnb' + '<name>Thumbnail.xnb' in the same folder make one board (the STUNTBOOST layout);
       when any pair is found, only pairs are returned, sorted with numbers in numeric order.
    2. Otherwise each GLTF model is a board: its texture is the image its JSON names (else the first
       non-thumbnail texture next to it) and its thumbnail a '...thumb...' texture nearby.
    3. Otherwise one board per folder of textures.
    """
    root = Path(root).resolve()
    models, textures = [], []
    for p in sorted(root.rglob("*.xnb")):
        try:
            kind = peek_kind(p)
        except Exception:
            continue
        if kind == "model":
            models.append(p)
        elif kind == "texture":
            textures.append(p)
    by_lower = {str(t).lower(): t for t in textures}
    boards: list[Board] = []

    # Pair mode: "<name>.xnb" + "<name>Thumbnail.xnb" in the same folder = one board
    pair_re = re.compile(r"^(.*?)[ _-]?(thumbnail|thumb)$", re.I)
    for t in textures:
        m = pair_re.match(t.stem)
        if m:
            main = t.with_name(m.group(1) + ".xnb")
            if str(main).lower() in by_lower:
                boards.append(Board(m.group(1), texture=by_lower[str(main).lower()], thumb=t))
    if boards:
        boards.sort(key=lambda b: [int(x) if x.isdigit() else x.lower()
                                   for x in re.split(r"(\d+)", str(b.texture))])
        return boards

    for m in models:
        b = Board(m.stem, model=m)
        try:
            for im in read_model_json(m).get("images", []):
                uri = im.get("uri") or ""
                if not uri or uri.startswith("data:"):
                    continue
                cand = os.path.normpath(m.parent / urllib.parse.unquote(uri))
                cand = str(Path(cand).with_suffix(".xnb")).lower()
                if cand in by_lower:
                    b.texture = by_lower[cand]
                    break
        except Exception:
            pass
        if not b.texture:
            for t in textures:
                if t.parent == m.parent and not THUMB_RE.search(t.name):
                    b.texture = t
                    break
        dirs = {m.parent} | ({b.texture.parent} if b.texture else set())
        for t in textures:
            if t == b.texture or not THUMB_RE.search(t.name):
                continue
            if t.parent in dirs or m.stem.lower() in str(t.relative_to(root)).lower():
                b.thumb = t
                break
        boards.append(b)

    if not boards:  # no GLTF models: one "board" per folder containing textures
        folders: dict[Path, list[Path]] = {}
        for t in textures:
            folders.setdefault(t.parent, []).append(t)
        for folder, files in folders.items():
            b = Board(folder.name or str(folder))
            for t in files:
                if THUMB_RE.search(t.name):
                    b.thumb = b.thumb or t
                else:
                    b.texture = b.texture or t
            boards.append(b)
    return boards


def strip_image(img: Image.Image, w: int = 76, h: int = 18) -> Image.Image:
    """A small landscape preview of a texture (the list rows), the image fitted into w x h on a dark background.
    """
    out = Image.new("RGBA", (w, h), (42, 44, 49, 255))
    s = min(w / img.width, h / img.height)
    nw, nh = max(1, round(img.width * s)), max(1, round(img.height * s))
    small = img.convert("RGBA").resize((nw, nh), Image.BOX)
    out.alpha_composite(small, ((w - nw) // 2, (h - nh) // 2))
    return out


# --------------------------------------------------------------------------
#  Board colors: the first 4 pixels of the texture's top row are a palette
#    (x=0, y=0) border   (x=1, y=0) under   (x=2, y=0) wheels   (x=3, y=0) truck
# --------------------------------------------------------------------------
PALETTE_SLOTS = [("border", N_("Border")), ("under", N_("Under")), ("wheels", N_("Wheels")), ("truck", N_("Truck"))]


def read_palette(img: Image.Image) -> Optional[list]:
    """The deck's four colours (border, under, wheels, truck): the first pixels of the texture's top row, where the
    game reads them. None for a too small image.
    """
    if img.width < len(PALETTE_SLOTS) or img.height < 1:
        return None
    img = img.convert("RGBA")
    return [tuple(img.getpixel((x, 0))[:3]) for x in range(len(PALETTE_SLOTS))]


def apply_palette(img: Image.Image, colors) -> Image.Image:
    """A copy of the texture with the four deck colours written into the first pixels of its top row."""
    out = img.convert("RGBA").copy()
    for x, c in enumerate(colors[:min(len(PALETTE_SLOTS), out.width)]):
        out.putpixel((x, 0), (int(c[0]), int(c[1]), int(c[2]), 255))
    return out


def to_hex(c) -> str:
    """An RGB colour as '#rrggbb'."""
    return "#%02x%02x%02x" % tuple(c[:3])


def parse_color(s: str):
    """Reads a colour typed by the user: '#rrggbb', 'rrggbb' or 'r, g, b'. Returns an RGB tuple or None."""
    s = s.strip()
    m = re.fullmatch(r"#?([0-9a-fA-F]{6})", s)
    if m:
        h = m.group(1)
        return tuple(int(h[k:k + 2], 16) for k in (0, 2, 4))
    m = re.fullmatch(r"(\d{1,3})\s*[,; ]\s*(\d{1,3})\s*[,; ]\s*(\d{1,3})", s)
    if m and all(int(v) <= 255 for v in m.groups()):
        return tuple(int(v) for v in m.groups())
    return None


def read_texture_palette(path) -> Optional[list]:
    """The 4 board-color pixels of a texture .xnb, read quickly (no full decode)."""
    try:
        data = Path(path).read_bytes()
        info = parse_xnb(data)
        if "QoiReader" in info.reader:
            return _qoi_first_pixels(data[info.content + 4:], len(PALETTE_SLOTS))
        if "Texture2DReader" in info.reader:
            fmt, w, h, _lv = struct.unpack_from("<4i", data, info.content)
            if fmt == 0 and w >= len(PALETTE_SLOTS):
                raw = data[info.content + 20:info.content + 20 + 4 * len(PALETTE_SLOTS)]
                return [tuple(raw[k * 4:k * 4 + 3]) for k in range(len(PALETTE_SLOTS))]
    except Exception:
        pass
    return None
