#!/usr/bin/env python3
"""Builds a fake STUNTBOOST content folder for testing, so nobody needs the game files.

    python tests/fixture.py OUT_FOLDER [--boards N]

It creates the same layout and file formats the game uses:

    OUT_FOLDER/STUNTBOOST/Content/Models/Resources/Board/<n>.xnb            board texture, 1920x432, QOI in XNB
    OUT_FOLDER/STUNTBOOST/Content/Models/Resources/Board/<n>Thumbnail.xnb   board thumbnail, 640x144
    OUT_FOLDER/STUNTBOOST/Content/Textures/HUD/SpeedMeter/*.xnb             the five speedometer textures

Every board gets simple generated art (stripes, bands, dots or waves) and one of five colour sets in the
first four pixels of the top row (border, under, wheels, truck), like the real boards. Board 0 is plain.

There is no 3D model (Content/Models/Export/Board.xnb belongs to the game and is not included), so the 3D
views show "Board model not found". Everything else works.
"""
from __future__ import annotations

import argparse
import math
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent          # the folder with xnb_board_tool/
sys.path.insert(0, str(ROOT))

from PIL import Image, ImageDraw  # noqa: E402

from xnb_board_tool.qoi import qoi_encode  # noqa: E402

READER = "BytingPipeline.QoiReader, BytingPipeline, Version=1.0.0.0, Culture=neutral, PublicKeyToken=null"
PALETTES = [[(198, 86, 0), (17, 17, 17), (255, 229, 209), (102, 102, 102)],
            [(229, 225, 233), (124, 0, 247), (74, 74, 168), (46, 1, 242)],
            [(216, 32, 32), (17, 17, 17), (58, 58, 58), (216, 32, 32)],
            [(43, 108, 255), (255, 210, 63), (255, 74, 28), (27, 27, 27)],
            [(255, 255, 255), (0, 179, 164), (255, 122, 182), (60, 60, 60)]]


def _7bit(n: int) -> bytes:
    """.NET 7-bit encoded integer (used for lengths and counts inside XNB files)."""
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        out.append(b | (0x80 if n else 0))
        if not n:
            return bytes(out)


def xnb_qoi(img: Image.Image) -> bytes:
    """An uncompressed XNB file holding `img` as QOI, read by BytingPipeline.QoiReader (as the game stores
    its board textures)."""
    q = qoi_encode(img)
    name = READER.encode()
    # one type reader (name + version), no shared resources, then object #1 = int32 length + QOI bytes
    body = _7bit(1) + _7bit(len(name)) + name + struct.pack("<i", 0) + _7bit(0) + _7bit(1)
    body += struct.pack("<i", len(q)) + q
    head = b"XNBw" + bytes([5, 0])                      # Windows, XNB version 5, no flags (not compressed)
    return head + struct.pack("<I", len(head) + 4 + len(body)) + body


def _hsv(h: float, s: float, v: float):
    """HSV (0..1) to an RGB tuple (0..255)."""
    i = int(h * 6) % 6
    f = h * 6 - int(h * 6)
    p, q, t = v * (1 - s), v * (1 - f * s), v * (1 - (1 - f) * s)
    r, g, b = [(v, t, p), (q, v, p), (p, v, t), (p, q, v), (t, p, v), (v, p, q)][i]
    return int(r * 255), int(g * 255), int(b * 255)


def board_art(i: int, W: int = 1920, H: int = 432) -> Image.Image:
    """Generated artwork for board `i` (four styles, hue changes per board; board 0 is plain dark grey)."""
    im = Image.new("RGBA", (W, H), (20, 20, 22, 255))
    d = ImageDraw.Draw(im)
    if i == 0:
        return im
    h0 = (i * 0.163) % 1
    style = i % 4
    if style == 0:          # diagonal stripes
        for k in range(-H, W, 90):
            d.polygon([(k, H), (k + 45, H), (k + 45 + H, 0), (k + H, 0)], fill=_hsv(h0, .7, .85))
    elif style == 1:        # gradient bands
        for x in range(0, W, 8):
            t = x / W
            d.rectangle([x, 0, x + 8, H], fill=_hsv((h0 + t * .25) % 1, .65, .35 + .55 * t))
    elif style == 2:        # dots
        im.paste(_hsv(h0, .5, .25), (0, 0, W, H))
        for x in range(60, W, 140):
            for y in range(60, H, 140):
                d.ellipse([x - 40, y - 40, x + 40, y + 40], fill=_hsv((h0 + .5) % 1, .8, .95))
    else:                   # waves
        im.paste(_hsv(h0, .6, .9), (0, 0, W, H))
        for k in range(6):
            pts = [(x, H / 2 + math.sin(x / 120 + k) * 120 + (k - 3) * 30) for x in range(0, W + 20, 20)]
            d.line(pts, fill=_hsv((h0 + .3) % 1, .8, .4), width=22)
    return im


def make_boards(folder: Path, count: int = 24) -> Path:
    """Writes `count` boards (texture + thumbnail) into `folder` and returns it."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    for i in range(count):
        im = board_art(i)
        for k, c in enumerate(PALETTES[i % len(PALETTES)]):
            im.putpixel((k, 0), c + (255,))              # the board colours live in the top-left pixels
        (folder / f"{i}.xnb").write_bytes(xnb_qoi(im))
        (folder / f"{i}Thumbnail.xnb").write_bytes(xnb_qoi(im.resize((640, 144), Image.LANCZOS)))
    return folder


def _slant(w: int, h: int, slope: float = 0.35) -> Image.Image:
    """A white slanted bar like the game's speedometer pieces."""
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    s = int(h * slope)
    ImageDraw.Draw(im).polygon([(s, 0), (w, 0), (w - s, h), (0, h)], fill=(255, 255, 255, 255),
                               outline=(27, 10, 8, 255))
    return im


def make_speedmeter(folder: Path) -> Path:
    """Writes the five speedometer textures (Texture, BarBeginning, Block, CMS, MMS) into `folder`."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    tex = Image.new("RGBA", (3699, 154), (60, 10, 8, 255))
    d = ImageDraw.Draw(tex)
    for x in range(0, 3699, 6):
        t = x / 3699
        d.line([(x, 0), (x, 154)], fill=(int(120 + 120 * (1 - abs(0.5 - t) * 2)), 30, 20, 255), width=6)
    parts = {"Texture": tex, "BarBeginning": _slant(420, 154), "Block": _slant(190, 154),
             "CMS": _slant(240, 64, 0.2), "MMS": _slant(260, 64, 0.2)}
    for k, im in parts.items():
        (folder / f"{k}.xnb").write_bytes(xnb_qoi(im))
    return folder


def make_game(out: Path, boards: int = 24) -> Path:
    """Builds the whole fake game folder under `out` and returns the board folder."""
    content = Path(out) / "STUNTBOOST" / "Content"
    make_speedmeter(content / "Textures" / "HUD" / "SpeedMeter")
    return make_boards(content / "Models" / "Resources" / "Board", boards)


def main() -> None:
    """Command line entry point."""
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("out", type=Path, help="folder to create the fake game in")
    ap.add_argument("--boards", type=int, default=24, help="number of boards (default 24)")
    a = ap.parse_args()
    board_dir = make_game(a.out, a.boards)
    print(f"{a.boards} boards in {board_dir}")


if __name__ == "__main__":
    main()
