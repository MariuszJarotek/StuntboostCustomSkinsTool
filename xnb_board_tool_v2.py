#!/usr/bin/env python3
"""
XNB Board Texture Tool  (v2 - redesigned dark UI)
=================================================
Scans a content folder for boards (GLTF model .xnb files wrapped by
BytingPipeline.GLTFReader, or <name>.xnb + <name>Thumbnail.xnb pairs), finds
each board's texture and thumbnail, shows them, and lets you replace either one
with any normal image (PNG/JPG/BMP/TGA/GIF/WEBP).

Usage:
    pip install pillow
    pip install tkinterdnd2      # optional: drag & drop images onto the previews
    python xnb_board_tool_v2.py [content_folder]

What's new in v2:
  * Dark UI. Previews keep the real aspect ratio of the image (wide strips stay wide).
  * Board list with a mini preview and a status marker per board:
        green dot = matches default, amber square = modified, outlined ring = no default.
    Statuses are computed in the background; pixel hashes are cached in
    _board_defaults/_hash_cache.json so later launches are fast.
  * Filter box, previous / next buttons, summary in the footer.
  * "Generate from texture": rebuilds the thumbnail by downscaling the board texture.
  * Adjust image: every new image (picked or dropped) opens an editor first - drag to
    position, scroll/slider to zoom, Fill / Fit / Stretch, rotate (90 deg steps or any
    angle), flip, and a color or transparency for uncovered areas. The result always
    has the texture's exact size.
  * Board colors: the first 4 pixels of the texture's top row are the board's
    border (x=0), under (x=1), wheels (x=2) and truck (x=3) colors. Pick them with a
    color picker or type #rrggbb / r,g,b, then 'Apply colors to texture'.
    Copy / Paste moves a color set between boards, and by default the colors are
    kept when you replace the texture with a new image.
  * Drag & drop an image onto a preview to replace it (needs tkinterdnd2).
  * Ctrl+O opens a folder; Ctrl+Left / Ctrl+Right step through boards.

Unchanged from v1 (same file formats and folders):
  * Supports BytingPipeline.QoiReader images (QOI inside XNB) and MonoGame Texture2D.
  * Texture2D replacements are written as RGBA8 with the original mip count.
  * Alpha is re-premultiplied only if the original texture looked premultiplied.
  * A one-time backup  <file>.xnb.bak  is written before the first overwrite.
  * Defaults are snapshots in a _board_defaults folder; 'Revert to default' restores them.
  * Compressed XNBs (LZX/LZ4 flag) are not supported.
"""
from __future__ import annotations

import datetime
import hashlib
import io
import json
import math
import os
import queue
import re
import struct
import sys
import threading
import urllib.parse
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from PIL import Image, ImageChops, ImageDraw

# --------------------------------------------------------------------------
#  XNB parsing / writing (no GUI dependencies)
# --------------------------------------------------------------------------
class XnbError(Exception):
    pass


SURFACE_NAMES = {0: "Color (RGBA8)", 4: "DXT1", 5: "DXT3", 6: "DXT5"}
FOURCC = {4: b"DXT1", 5: b"DXT3", 6: b"DXT5"}


def read7(data: bytes, p: int):
    result = shift = 0
    while True:
        b = data[p]
        p += 1
        result |= (b & 0x7F) << shift
        if not b & 0x80:
            return result, p
        shift += 7


def read_str(data: bytes, p: int):
    n, p = read7(data, p)
    return data[p:p + n].decode("utf-8"), p + n


@dataclass
class XnbInfo:
    reader: str      # type reader of the primary asset
    content: int     # offset where the asset's own data begins
    version: int
    flags: int


def parse_xnb(data: bytes) -> XnbInfo:
    try:
        if data[:3] != b"XNB":
            raise XnbError("not an XNB file")
        version, flags = data[4], data[5]
        if flags & 0xC0:
            raise XnbError("compressed XNB files are not supported")
        p = 10
        count, p = read7(data, p)
        readers = []
        for _ in range(count):
            name, p = read_str(data, p)
            p += 4  # reader version
            readers.append(name)
        _shared, p = read7(data, p)
        tid, p = read7(data, p)
        if tid == 0 or tid > len(readers):
            raise XnbError("primary asset is null")
        return XnbInfo(readers[tid - 1], p, version, flags)
    except (IndexError, struct.error) as e:
        raise XnbError(f"truncated or malformed XNB ({e})")


def peek_kind(path: Path) -> str:
    """'texture', 'model' or 'other' - reads only the file header."""
    with open(path, "rb") as f:
        head = f.read(8192)
    info = parse_xnb(head)
    if "Texture2DReader" in info.reader or "QoiReader" in info.reader:
        return "texture"
    if "GLTFReader" in info.reader:
        return "model"
    return "other"



# ---- Safety limits & safe writing ----
# A damaged or hostile .xnb could claim absurd sizes; reject them instead of trying to
# allocate gigabytes of memory (which could freeze the PC).
MAX_DIM = 16384                 # largest width/height accepted
MAX_PIXELS = 64 * 1024 * 1024   # 64 Mpx = 256 MB as RGBA


def check_size(w: int, h: int) -> None:
    if w <= 0 or h <= 0 or w > MAX_DIM or h > MAX_DIM or w * h > MAX_PIXELS:
        raise XnbError(f"image size {w}x{h} is outside the supported range")


def atomic_write(path: Path, data: bytes) -> None:
    """Write via a temp file + rename, so a crash or power loss mid-write never
    leaves a half-written (corrupted) file behind."""
    path = Path(path)
    tmp = path.with_name(path.name + ".tmp-xnbtool")
    try:
        with open(tmp, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass


# ---- QOI codec (pure Python; the game stores board images as QOI inside XNB) ----
def qoi_decode(b: bytes) -> Image.Image:
    if b[:4] != b"qoif":
        raise XnbError("QOI magic not found")
    if len(b) < 14:
        raise XnbError("QOI data is truncated")
    w, h, _ch, _cs = struct.unpack(">IIBB", b[4:14])
    check_size(w, h)
    n = w * h
    if (len(b) - 14) * 62 < n:   # even the best compression (62-pixel runs) can't fit
        raise XnbError("QOI data is truncated")
    px = bytearray(n * 4)
    index = [(0, 0, 0, 0)] * 64
    r = g = bl = 0
    a = 255
    p, i, o = 14, 0, 0
    try:
        while i < n:
            b1 = b[p]
            p += 1
            if b1 == 0xFE:
                r, g, bl = b[p], b[p + 1], b[p + 2]
                p += 3
            elif b1 == 0xFF:
                r, g, bl, a = b[p], b[p + 1], b[p + 2], b[p + 3]
                p += 4
            else:
                t = b1 & 0xC0
                if t == 0x00:
                    r, g, bl, a = index[b1]
                elif t == 0x40:
                    r = (r + ((b1 >> 4) & 3) - 2) & 255
                    g = (g + ((b1 >> 2) & 3) - 2) & 255
                    bl = (bl + (b1 & 3) - 2) & 255
                elif t == 0x80:
                    b2 = b[p]
                    p += 1
                    vg = (b1 & 0x3F) - 32
                    r = (r + vg - 8 + ((b2 >> 4) & 15)) & 255
                    g = (g + vg) & 255
                    bl = (bl + vg - 8 + (b2 & 15)) & 255
                else:
                    run = min((b1 & 0x3F) + 1, n - i)
                    px[o:o + run * 4] = bytes((r, g, bl, a)) * run
                    o += run * 4
                    i += run
                    continue
            index[(r * 3 + g * 5 + bl * 7 + a * 11) & 63] = (r, g, bl, a)
            px[o:o + 4] = bytes((r, g, bl, a))
            o += 4
            i += 1
    except IndexError:
        raise XnbError("QOI data is truncated")
    return Image.frombytes("RGBA", (w, h), bytes(px))


def qoi_encode(img: Image.Image) -> bytes:
    img = img.convert("RGBA")
    w, h = img.size
    out = bytearray(b"qoif" + struct.pack(">IIBB", w, h, 4, 0))
    index = [(0, 0, 0, 0)] * 64
    prev = (0, 0, 0, 255)
    pr, pg, pb, pa = prev
    run = 0
    for px in struct.iter_unpack("4B", img.tobytes()):
        if px == prev:
            run += 1
            if run == 62:
                out.append(0xC0 | 61)
                run = 0
            continue
        if run:
            out.append(0xC0 | (run - 1))
            run = 0
        r, g, b, a = px
        hsh = (r * 3 + g * 5 + b * 7 + a * 11) & 63
        if index[hsh] == px:
            out.append(hsh)
        else:
            index[hsh] = px
            if a == pa:
                dr = ((r - pr + 128) & 255) - 128
                dg = ((g - pg + 128) & 255) - 128
                db = ((b - pb + 128) & 255) - 128
                drg, dbg = dr - dg, db - dg
                if -2 <= dr <= 1 and -2 <= dg <= 1 and -2 <= db <= 1:
                    out.append(0x40 | ((dr + 2) << 4) | ((dg + 2) << 2) | (db + 2))
                elif -32 <= dg <= 31 and -8 <= drg <= 7 and -8 <= dbg <= 7:
                    out += bytes((0x80 | (dg + 32), ((drg + 8) << 4) | (dbg + 8)))
                else:
                    out += bytes((0xFE, r, g, b))
            else:
                out += bytes((0xFF, r, g, b, a))
        prev = px
        pr, pg, pb, pa = px
    if run:
        out.append(0xC0 | (run - 1))
    out += b"\0" * 7 + b"\x01"
    return bytes(out)


@dataclass
class TexData:
    img: Image.Image
    fmt: int
    width: int
    height: int
    levels: int
    premult: bool
    codec: str = "tex2d"   # 'tex2d' (MonoGame Texture2D) or 'qoi' (BytingPipeline.QoiReader)


def _dds(w: int, h: int, fourcc: bytes, raw: bytes) -> bytes:
    return (
        b"DDS " + struct.pack("<7I", 124, 0x81007, h, w, len(raw), 0, 1)
        + b"\0" * 44
        + struct.pack("<2I4s5I", 32, 4, fourcc, 0, 0, 0, 0, 0)
        + struct.pack("<5I", 0x1000, 0, 0, 0, 0)
        + raw
    )


def load_texture(path: Path) -> TexData:
    data = Path(path).read_bytes()
    info = parse_xnb(data)
    if "QoiReader" in info.reader:
        n, = struct.unpack_from("<i", data, info.content)
        start = info.content + 4
        img = qoi_decode(data[start:start + n])
        return TexData(img, -1, img.width, img.height, 1, False, "qoi")
    if "Texture2DReader" not in info.reader:
        raise XnbError(f"unsupported texture type: {info.reader.split(',')[0]}")
    p = info.content
    fmt, w, h, levels = struct.unpack_from("<4i", data, p)
    p += 16
    size, = struct.unpack_from("<i", data, p)
    p += 4
    raw = data[p:p + size]
    check_size(w, h)
    levels = max(1, min(levels, max(w, h).bit_length()))   # a full mip chain at most
    if fmt == 0:
        if len(raw) != w * h * 4:
            raise XnbError("unexpected pixel data size")
        img = Image.frombytes("RGBA", (w, h), raw)
    elif fmt in FOURCC:
        import io
        img = Image.open(io.BytesIO(_dds(w, h, FOURCC[fmt], raw))).convert("RGBA")
    else:
        raise XnbError(f"unsupported surface format {fmt}")
    r, g, b, a = img.split()
    premult = all(ImageChops.subtract(c, a).getextrema()[1] == 0 for c in (r, g, b))
    return TexData(img, fmt, w, h, max(1, levels), premult)


def save_texture(path: Path, new_img: Image.Image, old: TexData) -> None:
    path = Path(path)
    data = path.read_bytes()
    info = parse_xnb(data)
    img = new_img.convert("RGBA")
    check_size(*img.size)
    if old.codec == "qoi":
        qoi = qoi_encode(img)
        out = bytearray(data[:info.content] + struct.pack("<i", len(qoi)) + qoi)
        struct.pack_into("<I", out, 6, len(out))
        bak = path.with_suffix(path.suffix + ".bak")
        if not bak.exists():
            atomic_write(bak, data)
        atomic_write(path, bytes(out))
        return
    if old.premult:
        r, g, b, a = img.split()
        img = Image.merge("RGBA", (ImageChops.multiply(r, a),
                                   ImageChops.multiply(g, a),
                                   ImageChops.multiply(b, a), a))
    W, H = img.size
    check_size(W, H)
    levels = max(1, min(old.levels, max(W, H).bit_length()))
    body = struct.pack("<4i", 0, W, H, levels)
    for i in range(levels):
        w, h = max(1, W >> i), max(1, H >> i)
        level = img if i == 0 else img.resize((w, h), Image.BOX)
        raw = level.tobytes()
        body += struct.pack("<i", len(raw)) + raw
    out = bytearray(data[:info.content] + body)
    struct.pack_into("<I", out, 6, len(out))
    bak = path.with_suffix(path.suffix + ".bak")
    if not bak.exists():
        atomic_write(bak, data)
    atomic_write(path, bytes(out))


def read_model_json(path: Path) -> dict:
    data = Path(path).read_bytes()
    info = parse_xnb(data)
    text, _ = read_str(data, info.content)
    return json.loads(text)



# --------------------------------------------------------------------------
#  Defaults (snapshots you can revert to)
# --------------------------------------------------------------------------
# Stored in a "_board_defaults" folder next to each .xnb, per file:
#   <file>.xnb.json          when it was set, how it is stored, sizes, pixel hash
#   <file>.xnb.default.xnbdef  byte-exact copy of the original XNB        (storage = "xnb")
#   <file>.xnb.default.png     lossless PNG of the image                  (storage = "png")
# Rule: QOI images are stored as PNG when that is at least 15% smaller than the
# XNB (lossless, so reverting reproduces the same pixels). Everything else
# (e.g. DXT / mipmapped Texture2D) is kept as an exact XNB copy.
DEF_DIR = "_board_defaults"
PNG_MAX_RATIO = 0.85


def _def_paths(path: Path):
    d = Path(path).parent / DEF_DIR
    return d, d / (Path(path).name + ".json"), \
        d / (Path(path).name + ".default.png"), d / (Path(path).name + ".default.xnbdef")


def pixel_hash(img: Image.Image) -> str:
    return hashlib.sha256(img.convert("RGBA").tobytes()).hexdigest()


def human_size(n: int) -> str:
    return f"{n / 1048576:.2f} MB" if n >= 1048576 else f"{n / 1024:.0f} KB"


def load_default_meta(path: Path) -> Optional[dict]:
    d, meta_p, png_p, xnb_p = _def_paths(path)
    try:
        meta = json.loads(meta_p.read_text("utf-8"))
        stored = png_p if meta["storage"] == "png" else xnb_p
        return meta if stored.exists() else None
    except Exception:
        return None


def set_default(path: Path, tex: Optional[TexData] = None) -> dict:
    path = Path(path)
    data = path.read_bytes()
    tex = tex or load_texture(path)
    storage, png_bytes = "xnb", None
    if tex.codec == "qoi":
        im = tex.img
        opaque = im.getchannel("A").getextrema()[0] == 255
        buf = io.BytesIO()
        (im.convert("RGB") if opaque else im).save(buf, "PNG", compress_level=6)
        png_bytes = buf.getvalue()
        if len(png_bytes) <= PNG_MAX_RATIO * len(data):
            storage = "png"
    d, meta_p, png_p, xnb_p = _def_paths(path)
    d.mkdir(exist_ok=True)
    for stale in (png_p, xnb_p):
        if stale.exists():
            stale.unlink()
    stored = png_bytes if storage == "png" else data
    atomic_write(png_p if storage == "png" else xnb_p, stored)
    meta = {
        "saved_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "storage": storage,
        "xnb_bytes": len(data),
        "png_bytes": len(png_bytes) if png_bytes else None,
        "stored_bytes": len(stored),
        "width": tex.width, "height": tex.height, "codec": tex.codec,
        "pixel_sha256": pixel_hash(tex.img),
    }
    atomic_write(meta_p, json.dumps(meta, indent=2).encode("utf-8"))
    return meta


def revert_to_default(path: Path) -> dict:
    path = Path(path)
    meta = load_default_meta(path)
    if not meta:
        raise XnbError("no default has been set for this file")
    d, _m, png_p, xnb_p = _def_paths(path)
    if meta["storage"] == "xnb":
        snapshot = xnb_p.read_bytes()
        parse_xnb(snapshot)            # refuse to restore a damaged snapshot
        atomic_write(path, snapshot)
    else:
        img = Image.open(png_p)
        img.load()
        img = img.convert("RGBA")
        save_texture(path, img, TexData(img, -1, img.width, img.height, 1, False, "qoi"))
    return meta


# --------------------------------------------------------------------------
#  Board discovery
# --------------------------------------------------------------------------
@dataclass
class Board:
    name: str
    model: Optional[Path] = None
    texture: Optional[Path] = None
    thumb: Optional[Path] = None


THUMB_RE = re.compile(r"thumb|icon|preview", re.I)


def scan(root: Path) -> list[Board]:
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


# --------------------------------------------------------------------------
#  Board status (matches default / modified / no default), with a hash cache
# --------------------------------------------------------------------------
def _norm(path) -> str:
    return os.path.normcase(os.path.abspath(str(path)))


class HashCache:
    """Remembers pixel hashes by (file size, mtime) so status checks stay fast."""

    def __init__(self):
        self.lock = threading.Lock()
        self.data: dict = {}
        self.file: Optional[Path] = None
        self.dirty = False

    def attach(self, root: Path):
        self.file = Path(root) / DEF_DIR / "_hash_cache.json"
        try:
            self.data = json.loads(self.file.read_text("utf-8"))
        except Exception:
            self.data = {}
        self.dirty = False

    @staticmethod
    def _sig(path):
        st = os.stat(path)
        return [st.st_size, st.st_mtime_ns]

    def get(self, path) -> Optional[str]:
        try:
            sig = self._sig(path)
        except OSError:
            return None
        with self.lock:
            e = self.data.get(_norm(path))
        return e["h"] if e and e.get("sig") == sig else None

    def put(self, path, h: str):
        try:
            sig = self._sig(path)
        except OSError:
            return
        with self.lock:
            self.data[_norm(path)] = {"sig": sig, "h": h}
            self.dirty = True

    def save(self):
        if not self.file or not self.dirty:
            return
        try:
            self.file.parent.mkdir(exist_ok=True)
            with self.lock:
                text = json.dumps(self.data)
                self.dirty = False
            atomic_write(self.file, text.encode("utf-8"))
        except Exception:
            pass


def file_status(path: Optional[Path], cache: HashCache,
                tex: Optional[TexData] = None) -> Optional[str]:
    """'def' (matches default), 'mod' (differs) or 'none' (no default saved)."""
    if not path:
        return None
    meta = load_default_meta(path)
    if not meta:
        return "none"
    _d, _m, _png, xnb_p = _def_paths(path)
    if meta["storage"] == "xnb":
        try:
            return "def" if Path(path).read_bytes() == xnb_p.read_bytes() else "mod"
        except OSError:
            return "mod"
    h = cache.get(path)
    if h is None:
        h = pixel_hash((tex or load_texture(path)).img)
        cache.put(path, h)
    return "def" if h == meta["pixel_sha256"] else "mod"


def board_status(statuses) -> Optional[str]:
    s = [x for x in statuses if x]
    if not s:
        return None
    if "mod" in s:
        return "mod"
    if "none" in s:
        return "none"
    return "def"


# --------------------------------------------------------------------------
#  Image adjustment (position / zoom / rotate / flip) for new images
# --------------------------------------------------------------------------
@dataclass
class Adjust:
    mode: str = "fill"          # 'fill' (cover), 'fit' (contain) or 'stretch'
    zoom: float = 1.0           # multiplier on top of the mode's scale
    angle: float = 0.0          # degrees, clockwise on screen
    flip_h: bool = False
    flip_v: bool = False
    cx: Optional[float] = None  # image center in output pixels (None = centered)
    cy: Optional[float] = None
    bg: Optional[tuple] = None  # RGB fill for uncovered area (None = transparent)


def _trig(angle: float):
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
                    margin: int = 0, resample=Image.BICUBIC, cache: Optional[dict] = None) -> Image.Image:
    """Renders src placed on a W x H canvas according to adj.
    ps = preview scale (1 = final size); margin = extra pixels around the canvas
    (used by the preview to show the parts of the image that will be cut off)."""
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
    m = margin / ps
    coeffs = (c / (sx * ps), s / (sx * ps), bw / 2 + (c * (-m - cx) + s * (-m - cy)) / sx,
              -s / (sy * ps), c / (sy * ps), bh / 2 + (-s * (-m - cx) + c * (-m - cy)) / sy)
    size = (max(1, round(W * ps)) + 2 * margin, max(1, round(H * ps)) + 2 * margin)
    out = base.transform(size, Image.AFFINE, coeffs, resample=resample, fillcolor=(0, 0, 0, 0))
    if adj.bg is not None:
        under = Image.new("RGBA", size, (0, 0, 0, 0))
        ImageDraw.Draw(under).rectangle(
            [margin, margin, size[0] - margin - 1, size[1] - margin - 1], fill=tuple(adj.bg[:3]) + (255,))
        out = Image.alpha_composite(under, out)
    return out


def strip_image(img: Image.Image, w: int = 76, h: int = 18) -> Image.Image:
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
PALETTE_SLOTS = [("border", "Border"), ("under", "Under"), ("wheels", "Wheels"), ("truck", "Truck")]


def read_palette(img: Image.Image) -> Optional[list]:
    if img.width < len(PALETTE_SLOTS) or img.height < 1:
        return None
    img = img.convert("RGBA")
    return [tuple(img.getpixel((x, 0))[:3]) for x in range(len(PALETTE_SLOTS))]


def apply_palette(img: Image.Image, colors) -> Image.Image:
    out = img.convert("RGBA").copy()
    for x, c in enumerate(colors[:min(len(PALETTE_SLOTS), out.width)]):
        out.putpixel((x, 0), (int(c[0]), int(c[1]), int(c[2]), 255))
    return out


def to_hex(c) -> str:
    return "#%02x%02x%02x" % tuple(c[:3])


def parse_color(s: str):
    s = s.strip()
    m = re.fullmatch(r"#?([0-9a-fA-F]{6})", s)
    if m:
        h = m.group(1)
        return tuple(int(h[k:k + 2], 16) for k in (0, 2, 4))
    m = re.fullmatch(r"(\d{1,3})\s*[,; ]\s*(\d{1,3})\s*[,; ]\s*(\d{1,3})", s)
    if m and all(int(v) <= 255 for v in m.groups()):
        return tuple(int(v) for v in m.groups())
    return None


# --------------------------------------------------------------------------
#  GUI
# --------------------------------------------------------------------------
C = {
    "bg": "#141518", "panel": "#1a1c20", "side": "#18191d", "border": "#2a2d33",
    "btn": "#24262b", "btnh": "#2d3036", "btnb": "#353840", "sel": "#2a2d33",
    "text": "#e7e8ea", "muted": "#9aa0a8", "sub": "#b8bcc3", "dis": "#5c6168",
    "accent": "#f0a830", "accenth": "#ffc35c", "green": "#5fbf82",
}
BADGES = {
    "def": ("Matches default", "#7fd49e", "#1f3328"),
    "mod": ("Modified — differs from default", "#ffc35c", "#3a2f1a"),
    "none": ("No default saved", "#b8bcc3", "#24262b"),
    None: ("Checking…", "#9aa0a8", "#24262b"),
}


def _rgb(hex_color: str, a: int = 255):
    h = hex_color.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4)) + (a,)


_checker_cache: dict = {}


def checker(w: int, h: int, cell: int = 8) -> Image.Image:
    key = (w, h)
    im = _checker_cache.get(key)
    if im is None:
        tile = Image.new("RGBA", (cell * 2, cell * 2), (42, 44, 49, 255))
        d = ImageDraw.Draw(tile)
        d.rectangle([cell, 0, cell * 2 - 1, cell - 1], fill=(51, 54, 60, 255))
        d.rectangle([0, cell, cell - 1, cell * 2 - 1], fill=(51, 54, 60, 255))
        im = Image.new("RGBA", (w, h))
        for y in range(0, h, cell * 2):
            for x in range(0, w, cell * 2):
                im.paste(tile, (x, y))
        if len(_checker_cache) > 12:
            _checker_cache.clear()
        _checker_cache[key] = im
    return im


def dark_titlebar(win) -> None:
    if sys.platform != "win32":
        return
    try:
        import ctypes
        win.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(win.winfo_id())
        val = ctypes.c_int(1)
        for attr in (20, 19):
            if ctypes.windll.dwmapi.DwmSetWindowAttribute(
                    hwnd, attr, ctypes.byref(val), ctypes.sizeof(val)) == 0:
                break
    except Exception:
        pass


def run_gui(start_folder: Optional[str]) -> None:
    import tkinter as tk
    import tkinter.font as tkfont
    from tkinter import ttk, filedialog, messagebox, colorchooser
    from PIL import ImageTk
    try:
        from tkinterdnd2 import TkinterDnD, DND_FILES
    except Exception:
        TkinterDnD, DND_FILES = None, None

    root = TkinterDnD.Tk() if TkinterDnD else tk.Tk()
    fams = set(tkfont.families(root))

    def pick(*names):
        return next((n for n in names if n in fams), "TkDefaultFont")

    SANS = pick("IBM Plex Sans", "Segoe UI", "Helvetica Neue", "DejaVu Sans")
    MONO = pick("IBM Plex Mono", "Cascadia Mono", "Consolas", "DejaVu Sans Mono", "Courier New")
    F = {
        "body": (SANS, 10), "small": (SANS, 9), "bold": (SANS, 10, "bold"),
        "smallbold": (SANS, 9, "bold"), "h1": (SANS, 18, "bold"), "h2": (SANS, 10, "bold"),
        "title": (SANS, 11, "bold"), "mono": (MONO, 9), "monolist": (MONO, 10),
    }

    # ---------------- small widget helpers ----------------
    def button(parent, text, cmd, kind="secondary", **kw):
        pbg = parent.cget("bg")
        if kind == "primary":
            bg, fg, hov, bd, font = C["accent"], "#141518", C["accenth"], C["accent"], F["bold"]
        elif kind == "ghost":
            bg, fg, hov, bd, font = pbg, C["sub"], C["btn"], pbg, F["body"]
        else:
            bg, fg, hov, bd, font = C["btn"], C["text"], C["btnh"], C["btnb"], F["body"]
        b = tk.Button(parent, text=text, command=cmd, bg=bg, fg=fg, activebackground=hov,
                      activeforeground=fg, disabledforeground=C["dis"], relief="flat", bd=0,
                      highlightthickness=1, highlightbackground=bd, highlightcolor=bd,
                      padx=14, pady=7, cursor="hand2", font=font, **kw)
        b.bind("<Enter>", lambda e: str(b["state"]) != "disabled" and b.config(bg=hov))
        b.bind("<Leave>", lambda e: b.config(bg=bg))
        return b

    def card(parent):
        return tk.Frame(parent, bg=C["panel"], highlightthickness=1,
                        highlightbackground=C["border"])

    def hline(parent, color=None):
        return tk.Frame(parent, bg=color or C["border"], height=1)

    def label(parent, text="", font="body", fg="text", **kw):
        return tk.Label(parent, text=text, font=F[font], fg=C.get(fg, fg),
                        bg=kw.pop("bg", parent.cget("bg")), **kw)

    def set_state(widgets, enabled):
        for w in widgets:
            w.config(state="normal" if enabled else "disabled",
                     cursor="hand2" if enabled else "arrow")

    # ---------------- preview canvas ----------------
    class Preview(tk.Canvas):
        HL = 1

        def __init__(self, master, aspect, max_h, on_drop=None):
            super().__init__(master, bg=C["btn"], bd=0, height=80, highlightthickness=self.HL,
                             highlightbackground=C["border"])
            self.img: Optional[Image.Image] = None
            self.aspect, self.max_h, self.message = aspect, max_h, ""
            self._photo, self._job, self._wh = None, None, None
            self.bind("<Configure>", lambda e: self._schedule())
            if on_drop and TkinterDnD:
                self.drop_target_register(DND_FILES)
                self.dnd_bind("<<DropEnter>>", lambda e: self._hl(True) or e.action)
                self.dnd_bind("<<DropLeave>>", lambda e: self._hl(False) or e.action)

                def dropped(e):
                    self._hl(False)
                    files = self.tk.splitlist(e.data)
                    if files:
                        self.after(10, lambda: on_drop(files[0]))
                    return e.action
                self.dnd_bind("<<Drop>>", dropped)

        def _hl(self, on):
            self.config(highlightbackground=C["accent"] if on else C["border"])

        def set_image(self, img, message=""):
            self.img, self.message = img, message
            if img is not None:
                self.aspect = img.height / max(1, img.width)
            self._wh = None
            self._schedule()

        def _schedule(self):
            if self._job:
                self.after_cancel(self._job)
            self._job = self.after(60, self._redraw)

        def _redraw(self):
            self._job = None
            W = self.winfo_width() - 2 * self.HL
            if W < 10:
                return
            H = max(40, min(round(W * self.aspect), self.max_h))
            if int(float(self.cget("height"))) != H:
                self.configure(height=H)
            if self._wh == (W, H, id(self.img)):
                return
            self._wh = (W, H, id(self.img))
            self.delete("all")
            o = self.HL
            if self.img is None:
                self.create_text(o + W // 2, o + H // 2, text=self.message or "No image",
                                 fill=C["muted"], font=F["body"])
                return
            img = self.img
            s = min(W / img.width, H / img.height)
            nw, nh = max(1, round(img.width * s)), max(1, round(img.height * s))
            res = Image.LANCZOS if s < 1 else Image.NEAREST
            shown = Image.alpha_composite(checker(nw, nh), img.resize((nw, nh), res))
            self._photo = ImageTk.PhotoImage(shown)
            self.create_image(o + (W - nw) // 2, o + (H - nh) // 2, anchor="nw", image=self._photo)

    # ---------------- scrollable area ----------------
    class Scroll(tk.Frame):
        def __init__(self, master):
            super().__init__(master, bg=C["bg"])
            self.canvas = tk.Canvas(self, bg=C["bg"], highlightthickness=0, bd=0)
            sb = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
            self.inner = tk.Frame(self.canvas, bg=C["bg"])
            win = self.canvas.create_window(0, 0, window=self.inner, anchor="nw")
            self.canvas.configure(yscrollcommand=sb.set)
            sb.pack(side="right", fill="y")
            self.canvas.pack(side="left", fill="both", expand=True)
            self.inner.bind("<Configure>", lambda e: self.canvas.configure(
                scrollregion=self.canvas.bbox("all")))
            self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(win, width=e.width))
            root.bind_all("<MouseWheel>", self._wheel, add="+")
            root.bind_all("<Button-4>", lambda e: self._wheel(e, -1), add="+")
            root.bind_all("<Button-5>", lambda e: self._wheel(e, 1), add="+")

        def _wheel(self, e, direction=None):
            w = root.winfo_containing(e.x_root, e.y_root)
            if w is None or not str(w).startswith(str(self.canvas)):
                return
            if self.inner.winfo_height() <= self.canvas.winfo_height():
                return
            if direction is None:
                direction = -1 if e.delta > 0 else 1
            self.canvas.yview_scroll(direction * 3, "units")

    # ---------------- adjust-image dialog ----------------
    class AdjustDialog(tk.Toplevel):
        """Position / zoom / rotate / flip a new image before it replaces a texture.
        After wait_window(), .result is the final W x H image, or None if cancelled."""
        M = 36   # margin (preview px) that shows the parts that will be cut off

        def __init__(self, master, img, W, H, title):
            super().__init__(master, bg=C["panel"])
            self.withdraw()
            self.title(title)
            self.transient(master)
            self.resizable(False, False)
            self.src, self.W, self.H = img.convert("RGBA"), W, H
            self.adj = Adjust()
            self.result = None
            self._cache, self._photo, self._drag, self._job = {}, None, None, None
            self._quiet = False
            sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
            maxw = min(1100, int(sw * 0.8)) - 2 * self.M
            maxh = min(460, int(sh * 0.45))
            self.ps = min(maxw / W, maxh / H)
            self.pw, self.ph = max(1, round(W * self.ps)), max(1, round(H * self.ps))

            body = tk.Frame(self, bg=C["panel"])
            body.pack(padx=20, pady=16)
            top = tk.Frame(body, bg=C["panel"])
            top.pack(fill="x")
            label(top, "Adjust image", "title").pack(side="left")
            self.info = label(top, "", "small", "muted")
            self.info.pack(side="right")
            self.canvas = tk.Canvas(body, width=self.pw + 2 * self.M, height=self.ph + 2 * self.M,
                                    bg=C["bg"], highlightthickness=0, cursor="fleur")
            self.canvas.pack(pady=(10, 4))
            label(body, "Drag to move  ·  scroll to zoom  ·  double-click to reset  "
                        "·  arrows nudge (Shift = 10 px)  ·  dimmed area will be cut off",
                  "small", "muted").pack(anchor="w")

            def seg(parent, text, value, var, cmd):
                return tk.Radiobutton(parent, text=text, value=value, variable=var, command=cmd,
                                      indicatoron=False, bg=C["btn"], fg=C["text"],
                                      selectcolor="#4a3a1c", activebackground=C["btnh"],
                                      activeforeground=C["text"], relief="flat", bd=0,
                                      highlightthickness=1, highlightbackground=C["btnb"],
                                      padx=12, pady=6, font=F["body"], cursor="hand2")

            def toggle(parent, text, var, cmd):
                return tk.Checkbutton(parent, text=text, variable=var, command=cmd,
                                      indicatoron=False, bg=C["btn"], fg=C["text"],
                                      selectcolor="#4a3a1c", activebackground=C["btnh"],
                                      activeforeground=C["text"], relief="flat", bd=0,
                                      highlightthickness=1, highlightbackground=C["btnb"],
                                      padx=12, pady=6, font=F["body"], cursor="hand2")

            def slider(parent, lo, hi, cmd, length=220):
                return tk.Scale(parent, from_=lo, to=hi, orient="horizontal", length=length,
                                showvalue=False, command=cmd, bg=C["panel"], troughcolor=C["btn"],
                                activebackground=C["accent"], highlightthickness=0, bd=0,
                                sliderrelief="flat", sliderlength=16, width=10, resolution=1)

            # row 1: size mode + zoom
            r1 = tk.Frame(body, bg=C["panel"])
            r1.pack(fill="x", pady=(14, 0))
            label(r1, "Size", "small", "muted", width=7, anchor="w").pack(side="left")
            self.mode_var = tk.StringVar(value="fill")
            for text, val in (("Fill", "fill"), ("Fit", "fit"), ("Stretch", "stretch")):
                seg(r1, text, val, self.mode_var, self._on_mode).pack(side="left", padx=(0, 4))
            self.zoom_lbl = label(r1, "100%", "mono", "sub", width=6, anchor="e")
            self.zoom_lbl.pack(side="right")
            self.zoom_scale = slider(r1, -200, 300, self._on_zoom_slider)
            self.zoom_scale.pack(side="right", padx=(8, 6))
            label(r1, "Zoom", "small", "muted").pack(side="right")

            # row 2: rotate + flip
            r2 = tk.Frame(body, bg=C["panel"])
            r2.pack(fill="x", pady=(10, 0))
            label(r2, "Rotate", "small", "muted", width=7, anchor="w").pack(side="left")
            button(r2, "⟲ 90°", lambda: self._rot90(-90)).pack(side="left")
            button(r2, "⟳ 90°", lambda: self._rot90(90)).pack(side="left", padx=(4, 0))
            self.fh_var, self.fv_var = tk.BooleanVar(), tk.BooleanVar()
            toggle(r2, "Flip ↔", self.fh_var, self._on_flip).pack(side="left", padx=(16, 4))
            toggle(r2, "Flip ↕", self.fv_var, self._on_flip).pack(side="left")
            self.angle_lbl = label(r2, "0°", "mono", "sub", width=6, anchor="e")
            self.angle_lbl.pack(side="right")
            self.angle_scale = slider(r2, -180, 180, self._on_angle_slider)
            self.angle_scale.pack(side="right", padx=(8, 6))
            label(r2, "Angle", "small", "muted").pack(side="right")

            # row 3: background + buttons
            r3 = tk.Frame(body, bg=C["panel"])
            r3.pack(fill="x", pady=(16, 0))
            label(r3, "Empty area", "small", "muted").pack(side="left", padx=(0, 8))
            self.bg_sw = tk.Canvas(r3, width=26, height=26, highlightthickness=1,
                                   highlightbackground=C["btnb"], bg=C["btn"], cursor="hand2")
            self.bg_sw.pack(side="left")
            self.bg_sw.bind("<Button-1>", lambda e: self._pick_bg())
            button(r3, "Color…", self._pick_bg, "ghost").pack(side="left", padx=(6, 0))
            button(r3, "Transparent", self._clear_bg, "ghost").pack(side="left")
            button(r3, "Apply", self._apply, "primary").pack(side="right")
            button(r3, "Cancel", self._cancel).pack(side="right", padx=(0, 8))
            button(r3, "Reset", self._reset, "ghost").pack(side="right", padx=(0, 8))

            c = self.canvas
            c.bind("<ButtonPress-1>", self._press)
            c.bind("<B1-Motion>", self._motion)
            c.bind("<ButtonRelease-1>", lambda e: setattr(self, "_drag", None))
            c.bind("<Double-Button-1>", lambda e: self._reset_view())
            c.bind("<MouseWheel>", lambda e: self._wheel(e, 1 if e.delta > 0 else -1))
            c.bind("<Button-4>", lambda e: self._wheel(e, 1))
            c.bind("<Button-5>", lambda e: self._wheel(e, -1))
            for key, d in (("Left", (-1, 0)), ("Right", (1, 0)), ("Up", (0, -1)), ("Down", (0, 1))):
                self.bind(f"<{key}>", lambda e, d=d: self._nudge(*d, 1))
                self.bind(f"<Shift-{key}>", lambda e, d=d: self._nudge(*d, 10))
            self.bind("<plus>", lambda e: self._zoom_by(1.1))
            self.bind("<equal>", lambda e: self._zoom_by(1.1))
            self.bind("<minus>", lambda e: self._zoom_by(1 / 1.1))
            self.bind("<r>", lambda e: self._rot90(90))
            self.bind("<Return>", lambda e: self._apply())
            self.bind("<Escape>", lambda e: self._cancel())
            self.protocol("WM_DELETE_WINDOW", self._cancel)

            self._sync()
            self.update_idletasks()
            x = master.winfo_rootx() + (master.winfo_width() - self.winfo_reqwidth()) // 2
            y = master.winfo_rooty() + (master.winfo_height() - self.winfo_reqheight()) // 3
            self.geometry(f"+{max(0, x)}+{max(0, y)}")
            self.deiconify()
            dark_titlebar(self)
            self.grab_set()
            self.focus_set()

        # --- state helpers ---
        def _center(self):
            a = self.adj
            return (self.W / 2 if a.cx is None else a.cx, self.H / 2 if a.cy is None else a.cy)

        def _sync(self):
            """Push self.adj into the widgets (without feedback loops) and redraw."""
            a = self.adj
            self._quiet = True
            self.mode_var.set(a.mode)
            self.zoom_scale.set(round(math.log2(max(1e-6, a.zoom)) * 100))
            self.angle_scale.set(round(a.angle))
            self.fh_var.set(a.flip_h)
            self.fv_var.set(a.flip_v)
            self._quiet = False
            self.zoom_lbl.config(text=f"{a.zoom * 100:.0f}%")
            self.angle_lbl.config(text=f"{a.angle:.0f}°")
            self.bg_sw.delete("all")
            if a.bg is None:
                for i in range(0, 26, 6):
                    for j in range(0, 26, 6):
                        if (i + j) // 6 % 2:
                            self.bg_sw.create_rectangle(i, j, i + 6, j + 6, fill=C["btnb"], outline="")
            else:
                self.bg_sw.create_rectangle(0, 0, 27, 27, fill=to_hex(a.bg), outline="")
            self._schedule()

        def _schedule(self):
            if self._job is None:
                self._job = self.after(15, self._render)

        def _render(self):
            self._job = None
            out = render_adjusted(self.src, self.W, self.H, self.adj, ps=self.ps, margin=self.M,
                                  resample=Image.BILINEAR, cache=self._cache)
            Wp, Hp = out.size
            M = self.M
            shown = checker(Wp, Hp).copy()
            shown.alpha_composite(out)
            veil = Image.new("RGBA", (Wp, Hp), (14, 15, 18, 175))
            ImageDraw.Draw(veil).rectangle([M, M, M + self.pw - 1, M + self.ph - 1], fill=(0, 0, 0, 0))
            shown.alpha_composite(veil)
            self._photo = ImageTk.PhotoImage(shown)
            c = self.canvas
            c.delete("all")
            c.create_image(0, 0, anchor="nw", image=self._photo)
            c.create_rectangle(M - 1, M - 1, M + self.pw, M + self.ph, outline=C["accent"])
            sx, sy = self.src.size
            self.info.config(text=f"image {sx}×{sy}  →  output {self.W}×{self.H}")

        # --- events ---
        def _on_mode(self):
            if self._quiet:
                return
            self.adj.mode = self.mode_var.get()
            self.adj.zoom, self.adj.cx, self.adj.cy = 1.0, None, None
            self._sync()

        def _on_zoom_slider(self, v):
            if self._quiet:
                return
            self._set_zoom(2 ** (float(v) / 100))

        def _set_zoom(self, z, anchor=None):
            z = max(0.25, min(8.0, z))
            a = self.adj
            if anchor is not None:
                cx, cy = self._center()
                f = z / a.zoom
                a.cx, a.cy = anchor[0] - (anchor[0] - cx) * f, anchor[1] - (anchor[1] - cy) * f
            a.zoom = z
            self._sync()

        def _zoom_by(self, f):
            self._set_zoom(self.adj.zoom * f)

        def _wheel(self, e, d):
            anchor = ((e.x - self.M) / self.ps, (e.y - self.M) / self.ps)
            self._set_zoom(self.adj.zoom * (1.1 if d > 0 else 1 / 1.1), anchor)

        def _on_angle_slider(self, v):
            if self._quiet:
                return
            self.adj.angle = float(v)
            self._sync()

        def _rot90(self, d):
            self.adj.angle = (self.adj.angle + d + 180) % 360 - 180
            self._sync()

        def _on_flip(self):
            if self._quiet:
                return
            self.adj.flip_h, self.adj.flip_v = self.fh_var.get(), self.fv_var.get()
            self._sync()

        def _press(self, e):
            self.canvas.focus_set()
            self._drag = (e.x, e.y) + self._center()

        def _motion(self, e):
            if not self._drag:
                return
            x0, y0, cx0, cy0 = self._drag
            self.adj.cx = cx0 + (e.x - x0) / self.ps
            self.adj.cy = cy0 + (e.y - y0) / self.ps
            self._schedule()

        def _nudge(self, dx, dy, step):
            cx, cy = self._center()
            self.adj.cx, self.adj.cy = cx + dx * step, cy + dy * step
            self._schedule()

        def _pick_bg(self):
            cur = to_hex(self.adj.bg) if self.adj.bg else "#000000"
            rgb, _h = colorchooser.askcolor(color=cur, parent=self, title="Color for the empty area")
            if rgb:
                self.adj.bg = tuple(int(round(v)) for v in rgb[:3])
                self._sync()

        def _clear_bg(self):
            self.adj.bg = None
            self._sync()

        def _reset_view(self):
            a = self.adj
            a.zoom, a.cx, a.cy = 1.0, None, None
            self._sync()

        def _reset(self):
            self.adj = Adjust(bg=self.adj.bg)
            self._sync()

        def _apply(self):
            self.config(cursor="watch")
            self.update_idletasks()
            try:
                self.result = render_adjusted(self.src, self.W, self.H, self.adj)
            finally:
                self.config(cursor="")
            self.grab_release()
            self.destroy()

        def _cancel(self):
            self.result = None
            self.grab_release()
            self.destroy()

    # ---------------- the application ----------------
    class App:
        def __init__(self):
            root.title("XNB Board Texture Tool")
            root.geometry("1280x880")
            root.minsize(940, 620)
            root.configure(bg=C["bg"])
            self.folder: Optional[Path] = None
            self.path_full = "No folder loaded"
            self.boards: list[Board] = []
            self.status: dict[int, Optional[str]] = {}
            self.locked: set[int] = set()       # statuses computed on the UI thread
            self.strip_pil: dict[int, Image.Image] = {}
            self.row_imgs: dict[int, object] = {}
            self.sel: Optional[int] = None
            self.custom = False                 # texture panel shows a hand-picked .xnb
            self.tex_path = self.thumb_path = None
            self.tex = self.thumb = None
            self.tex_err = self.thumb_err = ""
            self.pal_orig = self.pal = None     # board colors: as stored / as edited
            self.clip = None                    # copied board colors
            self._pal_for = None                # texture path the edited colors belong to
            self.cache = HashCache()
            self.gen, self.pending = 0, 0
            self.q: queue.Queue = queue.Queue()
            self._syncing = False
            self._style()
            self._build()
            root.protocol("WM_DELETE_WINDOW", self.close)
            root.bind("<Control-o>", lambda e: self.open_folder())
            root.bind("<Control-Left>", lambda e: self.step(-1))
            root.bind("<Control-Right>", lambda e: self.step(1))
            root.after(60, self._poll)
            dark_titlebar(root)
            self._refresh_panels()
            if start_folder:
                root.after(50, lambda: self.load(Path(start_folder)))
            else:
                root.after(250, self.open_folder)

        # ---------- styling ----------
        def _style(self):
            st = ttk.Style(root)
            st.theme_use("clam")
            st.configure("Boards.Treeview", background=C["side"], fieldbackground=C["side"],
                         foreground=C["text"], borderwidth=0, rowheight=32, font=F["monolist"],
                         indent=0)
            st.layout("Boards.Treeview", [("Treeview.treearea", {"sticky": "nswe"})])
            st.layout("Boards.Treeview.Item", [("Treeitem.padding", {"sticky": "nswe", "children": [
                ("Treeitem.image", {"side": "left", "sticky": ""}),
                ("Treeitem.text", {"side": "left", "sticky": ""})]})])
            st.map("Boards.Treeview", background=[("selected", C["sel"])],
                   foreground=[("selected", C["text"])])
            st.configure("Vertical.TScrollbar", background=C["btn"], troughcolor=C["side"],
                         bordercolor=C["side"], arrowcolor=C["muted"], lightcolor=C["btn"],
                         darkcolor=C["btn"], gripcount=0, arrowsize=12)
            st.map("Vertical.TScrollbar", background=[("active", C["btnh"])])

        # ---------- layout ----------
        def _build(self):
            # header
            hdr = tk.Frame(root, bg=C["panel"])
            hdr.pack(fill="x")
            hline(root).pack(fill="x")
            row = tk.Frame(hdr, bg=C["panel"])
            row.pack(fill="x", padx=16, pady=10)
            logo = tk.Canvas(row, width=28, height=28, bg=C["panel"], highlightthickness=0)
            logo.create_rectangle(0, 0, 28, 28, fill=C["accent"], outline=C["accent"])
            logo.create_rectangle(6, 9, 22, 17, outline=C["bg"], width=2)
            logo.create_oval(8, 19, 12, 23, fill=C["bg"], outline="")
            logo.create_oval(16, 19, 20, 23, fill=C["bg"], outline="")
            logo.pack(side="left")
            label(row, "Board Texture Tool", "title").pack(side="left", padx=(10, 18))
            self.btn_saveall = button(row, "Save all as defaults", self.save_all_defaults)
            self.btn_saveall.pack(side="right", padx=(12, 0))
            box = tk.Frame(row, bg=C["bg"], highlightthickness=1, highlightbackground=C["border"])
            box.pack(side="left", fill="x", expand=True)
            ic = tk.Canvas(box, width=16, height=14, bg=C["bg"], highlightthickness=0)
            ic.create_polygon(1, 2, 6, 2, 8, 4, 15, 4, 15, 13, 1, 13, outline=C["muted"],
                              fill="", width=1.5)
            ic.pack(side="left", padx=(10, 0))
            button(box, "Change…", self.open_folder).pack(side="right", padx=4, pady=4)
            self.path_lbl = label(box, self.path_full, "mono", "sub", anchor="w", width=1)
            self.path_lbl.pack(side="left", fill="x", expand=True, padx=8)
            self.path_lbl.bind("<Configure>", self._fit_path)

            # footer (packed before the body so it stays visible)
            foot = tk.Frame(root, bg=C["panel"])
            foot.pack(side="bottom", fill="x")
            hline(root).pack(side="bottom", fill="x")
            self.status_var = tk.StringVar(value="Open a content folder to begin.")
            tk.Label(foot, textvariable=self.status_var, font=F["small"], fg=C["muted"],
                     bg=C["panel"], anchor="w").pack(side="left", padx=16, pady=6)
            self.summary_lbl = label(foot, "", "small", "muted")
            self.summary_lbl.pack(side="right", padx=16)

            body = tk.Frame(root, bg=C["bg"])
            body.pack(fill="both", expand=True)
            self._build_sidebar(body)
            hline(body).pack(side="left", fill="y")
            body.winfo_children()[-1].config(width=1)
            self.scroll = Scroll(body)
            self.scroll.pack(side="left", fill="both", expand=True)
            self._build_main(self.scroll.inner)

        def _build_sidebar(self, body):
            side = tk.Frame(body, bg=C["side"], width=290)
            side.pack(side="left", fill="y")
            side.pack_propagate(False)
            top = tk.Frame(side, bg=C["side"])
            top.pack(fill="x", padx=14, pady=(14, 8))
            r = tk.Frame(top, bg=C["side"])
            r.pack(fill="x")
            label(r, "Boards", "bold").pack(side="left")
            self.count_lbl = label(r, "", "small", "muted")
            self.count_lbl.pack(side="right")
            sbox = tk.Frame(top, bg=C["bg"], highlightthickness=1, highlightbackground=C["border"])
            sbox.pack(fill="x", pady=(10, 8))
            ic = tk.Canvas(sbox, width=14, height=14, bg=C["bg"], highlightthickness=0)
            ic.create_oval(1, 1, 10, 10, outline=C["muted"], width=1.6)
            ic.create_line(9, 9, 13, 13, fill=C["muted"], width=1.6)
            ic.pack(side="left", padx=(10, 0))
            self.filter_var = tk.StringVar()
            self.filter = tk.Entry(sbox, textvariable=self.filter_var, bg=C["bg"], fg=C["text"],
                                   insertbackground=C["text"], relief="flat", bd=0,
                                   font=F["body"], highlightthickness=0)
            self.filter.pack(side="left", fill="x", expand=True, padx=8, ipady=7)
            self._placeholder = True
            self.filter.insert(0, "Filter boards…")
            self.filter.config(fg=C["muted"])
            self.filter.bind("<FocusIn>", self._filter_focus_in)
            self.filter.bind("<FocusOut>", self._filter_focus_out)
            self.filter.bind("<Return>", self._filter_enter)
            self.filter.bind("<Escape>", lambda e: self.filter_var.set(""))
            self.filter_var.trace_add("write", lambda *a: self._fill_list())
            leg = tk.Frame(top, bg=C["side"])
            leg.pack(fill="x")
            for kind, text in (("def", "Default"), ("mod", "Modified"), ("none", "No default")):
                c = tk.Canvas(leg, width=10, height=10, bg=C["side"], highlightthickness=0)
                if kind == "def":
                    c.create_oval(1, 1, 9, 9, fill=C["green"], outline="")
                elif kind == "mod":
                    c.create_rectangle(1, 1, 9, 9, fill=C["accent"], outline="")
                else:
                    c.create_oval(1, 1, 9, 9, outline=C["muted"], width=1.5)
                c.pack(side="left")
                label(leg, text, "small", "muted").pack(side="left", padx=(4, 12))
            lst = tk.Frame(side, bg=C["side"])
            lst.pack(fill="both", expand=True, padx=(8, 0), pady=(0, 10))
            self.tree = ttk.Treeview(lst, show="tree", style="Boards.Treeview", selectmode="browse")
            self.tree.column("#0", stretch=True)
            sb = ttk.Scrollbar(lst, orient="vertical", command=self.tree.yview)
            self.tree.configure(yscrollcommand=sb.set)
            sb.pack(side="right", fill="y")
            self.tree.pack(side="left", fill="both", expand=True)
            self.tree.bind("<<TreeviewSelect>>", self._on_tree_select)

        def _build_main(self, parent):
            m = tk.Frame(parent, bg=C["bg"])
            m.pack(fill="both", expand=True, padx=28, pady=22)

            # title row
            tr = tk.Frame(m, bg=C["bg"])
            tr.pack(fill="x")
            self.title_lbl = label(tr, "No board selected", "h1")
            self.title_lbl.pack(side="left")
            self.badge = tk.Label(tr, font=F["smallbold"], padx=10, pady=3)
            self.badge.pack(side="left", padx=14)
            self.btn_next = button(tr, "›", lambda: self.step(1), width=2)
            self.btn_next.pack(side="right")
            self.btn_prev = button(tr, "‹", lambda: self.step(-1), width=2)
            self.btn_prev.pack(side="right", padx=6)

            # texture card
            tc = card(m)
            tc.pack(fill="x", pady=(18, 0))
            head = tk.Frame(tc, bg=C["panel"])
            head.pack(fill="x", padx=16, pady=10)
            label(head, "Board texture", "h2").pack(side="left")
            self.tex_file = label(head, "", "mono", "muted")
            self.tex_file.pack(side="left", padx=10)
            self.tex_chips = tk.Frame(head, bg=C["panel"])
            self.tex_chips.pack(side="right")
            hline(tc).pack(fill="x")
            self.tex_prev = Preview(tc, 432 / 1920, 460,
                                    on_drop=lambda f: self.replace("tex", f))
            self.tex_prev.pack(fill="x", padx=16, pady=16)
            act = tk.Frame(tc, bg=C["panel"])
            act.pack(fill="x", padx=16, pady=(0, 16))
            self.b_tex_replace = button(act, "↑  Replace image…",
                                        lambda: self.replace("tex"), "primary")
            self.b_tex_replace.pack(side="left")
            self.b_tex_export = button(act, "Export PNG…", lambda: self.export("tex"))
            self.b_tex_export.pack(side="left", padx=(8, 0))
            self.b_tex_revert = button(act, "Revert to default", lambda: self.revert("tex"))
            self.b_tex_revert.pack(side="left", padx=(8, 0))
            button(act, "Open other .xnb…", self.open_other, "ghost").pack(side="right")
            self.b_tex_setdef = button(act, "Set current as default",
                                       lambda: self.set_default("tex"), "ghost")
            self.b_tex_setdef.pack(side="right")

            # board colors card (first 4 pixels of the texture's top row)
            pc = card(m)
            pc.pack(fill="x", pady=(20, 0))
            head = tk.Frame(pc, bg=C["panel"])
            head.pack(fill="x", padx=16, pady=10)
            label(head, "Board colors", "h2").pack(side="left")
            label(head, "first 4 pixels of the texture's top row", "small", "muted").pack(
                side="left", padx=10)
            self.pal_state = label(head, "", "small", "muted")
            self.pal_state.pack(side="right")
            hline(pc).pack(fill="x")
            slots = tk.Frame(pc, bg=C["panel"])
            slots.pack(fill="x", padx=16, pady=(14, 4))
            self.pal_widgets = []
            for i, (_key, name) in enumerate(PALETTE_SLOTS):
                slots.columnconfigure(i, weight=1, uniform="p")
                cell = tk.Frame(slots, bg=C["panel"])
                cell.grid(row=0, column=i, sticky="w")
                sw = tk.Canvas(cell, width=60, height=44, bg=C["btn"], highlightthickness=1,
                               highlightbackground=C["btnb"], cursor="hand2")
                sw.grid(row=0, column=0, rowspan=3, padx=(0, 10))
                sw.bind("<Button-1>", lambda e, i=i: self.pick_color(i))
                label(cell, f"{name}", "bold").grid(row=0, column=1, sticky="w")
                var = tk.StringVar()
                ent = tk.Entry(cell, textvariable=var, width=9, bg=C["bg"], fg=C["text"],
                               insertbackground=C["text"], relief="flat", bd=0, font=F["mono"],
                               highlightthickness=1, highlightbackground=C["border"],
                               highlightcolor=C["accent"], disabledbackground=C["panel"])
                ent.grid(row=1, column=1, sticky="w", ipady=3, pady=(2, 0))
                ent.bind("<Return>", lambda e, i=i: self.commit_color(i))
                ent.bind("<FocusOut>", lambda e, i=i: self.commit_color(i))
                was = label(cell, "", "small", "muted")
                was.grid(row=2, column=1, sticky="w")
                self.pal_widgets.append((sw, var, ent, was))
            pact = tk.Frame(pc, bg=C["panel"])
            pact.pack(fill="x", padx=16, pady=(8, 16))
            self.b_pal_apply = button(pact, "Apply colors to texture", self.apply_colors, "primary")
            self.b_pal_apply.pack(side="left")
            self.b_pal_reset = button(pact, "Reset", self.reset_colors)
            self.b_pal_reset.pack(side="left", padx=(8, 0))
            self.b_pal_copy = button(pact, "Copy", self.copy_colors, "ghost")
            self.b_pal_copy.pack(side="left", padx=(8, 0))
            self.b_pal_paste = button(pact, "Paste", self.paste_colors, "ghost")
            self.b_pal_paste.pack(side="left")
            self.keep_pal = tk.BooleanVar(value=True)
            tk.Checkbutton(pact, text="Keep these colors when replacing the texture image",
                           variable=self.keep_pal, bg=C["panel"], fg=C["sub"],
                           activebackground=C["panel"], activeforeground=C["text"],
                           selectcolor=C["bg"], font=F["small"], bd=0, highlightthickness=0,
                           cursor="hand2").pack(side="right")

            # lower row: thumbnail + default snapshot
            low = tk.Frame(m, bg=C["bg"])
            low.pack(fill="x", pady=(20, 0))
            low.columnconfigure(0, weight=1, uniform="c")
            low.columnconfigure(1, weight=1, uniform="c")

            th = card(low)
            th.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
            head = tk.Frame(th, bg=C["panel"])
            head.pack(fill="x", padx=16, pady=10)
            label(head, "Thumbnail", "h2").pack(side="left")
            self.thumb_file = label(head, "", "mono", "muted")
            self.thumb_file.pack(side="left", padx=10)
            self.thumb_chips = tk.Frame(head, bg=C["panel"])
            self.thumb_chips.pack(side="right")
            hline(th).pack(fill="x")
            self.thumb_prev = Preview(th, 144 / 640, 260,
                                      on_drop=lambda f: self.replace("thumb", f))
            self.thumb_prev.pack(fill="x", padx=16, pady=(16, 12))
            a1 = tk.Frame(th, bg=C["panel"])
            a1.pack(fill="x", padx=16)
            self.b_th_replace = button(a1, "Replace…", lambda: self.replace("thumb"))
            self.b_th_replace.pack(side="left")
            self.b_th_gen = button(a1, "Generate from texture", self.generate_thumb)
            self.b_th_gen.pack(side="left", padx=(8, 0))
            self.b_th_export = button(a1, "Export PNG…", lambda: self.export("thumb"))
            self.b_th_export.pack(side="left", padx=(8, 0))
            a2 = tk.Frame(th, bg=C["panel"])
            a2.pack(fill="x", padx=16, pady=(8, 16))
            self.b_th_revert = button(a2, "Revert to default", lambda: self.revert("thumb"))
            self.b_th_revert.pack(side="left")
            self.b_th_setdef = button(a2, "Set current as default",
                                      lambda: self.set_default("thumb"), "ghost")
            self.b_th_setdef.pack(side="left", padx=(8, 0))

            dc = card(low)
            dc.grid(row=0, column=1, sticky="nsew", padx=(10, 0))
            inner = tk.Frame(dc, bg=C["panel"])
            inner.pack(fill="both", expand=True, padx=16, pady=14)
            label(inner, "Default snapshot", "h2").pack(anchor="w")
            grid = tk.Frame(inner, bg=C["panel"])
            grid.pack(fill="x", pady=(12, 0))
            grid.columnconfigure(0, weight=1, uniform="d")
            grid.columnconfigure(1, weight=1, uniform="d")
            self.def_vals = {}
            for i, (key, cap) in enumerate((("saved", "Saved"), ("tex", "Texture stored as"),
                                            ("thumb", "Thumbnail stored as"),
                                            ("bak", "Backup (.bak)"))):
                cell = tk.Frame(grid, bg=C["panel"])
                cell.grid(row=i // 2, column=i % 2, sticky="w", pady=(0, 12))
                label(cell, cap, "small", "muted").pack(anchor="w")
                v = label(cell, "—", "mono" if key == "saved" else "body")
                v.pack(anchor="w")
                self.def_vals[key] = v
            note = tk.Label(inner, bg=C["bg"], fg=C["sub"], font=F["small"], justify="left",
                            anchor="w", padx=12, pady=10, wraplength=380,
                            text="Defaults live in _board_defaults next to the board files. "
                                 "Revert restores the saved pixels exactly.")
            note.pack(fill="x", side="bottom")
            note.bind("<Configure>", lambda e: note.config(wraplength=max(120, e.width - 24)))
            hint = ("Tip: drag an image onto a preview to replace it." if TkinterDnD else
                    "Tip: pip install tkinterdnd2 to drag images onto the previews.")
            label(inner, hint, "small", "muted", anchor="w", justify="left").pack(
                fill="x", side="bottom", pady=(0, 8))

        # ---------- helpers ----------
        def set_status(self, text):
            self.status_var.set(text)

        def busy(self, on):
            root.config(cursor="watch" if on else "")
            root.update_idletasks()

        def _fit_path(self, _e=None):
            full = self.path_full
            font = tkfont.Font(root=root, font=F["mono"])
            avail = self.path_lbl.winfo_width() - 6
            if avail < 30 or font.measure(full) <= avail:
                self.path_lbl.config(text=full)
                return
            s = full
            while s and font.measure("…" + s) > avail:
                s = s[max(1, len(s) // 40):]
            self.path_lbl.config(text="…" + s)

        def _filter_focus_in(self, _e):
            if self._placeholder:
                self._placeholder = False
                self.filter.delete(0, "end")
                self.filter.config(fg=C["text"])

        def _filter_focus_out(self, _e):
            if not self.filter_var.get():
                self._placeholder = True
                self.filter.insert(0, "Filter boards…")
                self.filter.config(fg=C["muted"])

        def _filter_text(self):
            return "" if self._placeholder else self.filter_var.get().strip().lower()

        def _filter_enter(self, _e):
            kids = self.tree.get_children()
            if kids:
                self.select(int(kids[0]))

        def _row_image(self, i):
            im = Image.new("RGBA", (104, 24), (0, 0, 0, 0))
            d = ImageDraw.Draw(im)
            st = self.status.get(i)
            if st == "def":
                d.ellipse([3, 8, 11, 16], fill=_rgb(C["green"]))
            elif st == "mod":
                d.rectangle([3, 8, 11, 16], fill=_rgb(C["accent"]))
            elif st == "none":
                d.ellipse([3, 8, 11, 16], outline=_rgb(C["muted"]), width=2)
            else:
                d.ellipse([5, 10, 9, 14], fill=(74, 78, 86, 255))
            strip = self.strip_pil.get(i)
            if strip is None:
                d.rectangle([20, 3, 95, 20], fill=(42, 44, 49, 255))
            else:
                im.paste(strip, (20, 3))
            ph = ImageTk.PhotoImage(im)
            self.row_imgs[i] = ph
            return ph

        def _refresh_row(self, i):
            if self.tree.exists(str(i)):
                self.tree.item(str(i), image=self._row_image(i))

        def _fill_list(self):
            if not hasattr(self, "tree"):
                return
            q = self._filter_text()
            self._syncing = True
            self.tree.delete(*self.tree.get_children())
            shown = 0
            for i, b in enumerate(self.boards):
                if q and q not in b.name.lower():
                    continue
                self.tree.insert("", "end", iid=str(i), text=f"  {b.name}",
                                 image=self._row_image(i))
                shown += 1
            n = len(self.boards)
            self.count_lbl.config(text=f"{n} found" if shown == n else f"{shown} of {n}")
            if self.sel is not None and self.tree.exists(str(self.sel)) and not self.custom:
                self.tree.selection_set(str(self.sel))
                self.tree.see(str(self.sel))
            self._syncing = False

        def _on_tree_select(self, _e=None):
            if self._syncing:
                return
            s = self.tree.selection()
            if s and (int(s[0]) != self.sel or self.custom):
                self.select(int(s[0]))

        def _update_summary(self):
            n = len(self.boards)
            if not n:
                self.summary_lbl.config(text="")
                return
            vals = [self.status.get(i) for i in range(n)]
            text = (f"{n} boards · {vals.count('mod')} modified · "
                    f"{vals.count('none')} without default")
            if self.pending:
                text += f" · checking {n - self.pending}/{n}…"
            self.summary_lbl.config(text=text)

        # ---------- loading ----------
        def open_folder(self):
            d = filedialog.askdirectory(title="Select content folder")
            if d:
                self.load(Path(d))

        def load(self, folder: Path):
            self.busy(True)
            try:
                boards = scan(folder)
            except Exception as e:
                messagebox.showerror("Cannot scan folder", str(e))
                return
            finally:
                self.busy(False)
            self.cache.save()
            self.folder = Path(folder).resolve()
            self.cache.attach(self.folder)
            self.boards = boards
            self.status, self.locked, self.strip_pil, self.row_imgs = {}, set(), {}, {}
            self.sel, self.custom = None, False
            self.path_full = str(self.folder)
            self._fit_path()
            self._fill_list()
            self.set_status(f"{len(boards)} board(s) found in {self.folder.name}")
            if boards:
                self.select(0)
            else:
                self.tex_path = self.thumb_path = self.tex = self.thumb = None
                self._refresh_panels()
            self._start_worker()

        def _start_worker(self):
            self.gen += 1
            gen, boards, cache, q = self.gen, list(self.boards), self.cache, self.q
            have_strip = set(self.strip_pil)
            self.pending = len(boards)
            self._update_summary()

            def work():
                for i, b in enumerate(boards):
                    if gen != self.gen:
                        return
                    strip, src_tex, sts = None, None, []
                    src = b.thumb or b.texture
                    try:
                        if src and (i not in have_strip or b.thumb):
                            src_tex = load_texture(src)
                            if i not in have_strip:
                                strip = strip_image(src_tex.img)
                    except Exception:
                        src_tex = None
                    for p in (b.texture, b.thumb):
                        try:
                            sts.append(file_status(p, cache, src_tex if p == src else None))
                        except Exception:
                            pass
                    q.put((gen, i, strip, board_status(sts)))
                q.put((gen, "done", None, None))

            threading.Thread(target=work, daemon=True).start()

        def _poll(self):
            try:
                while True:
                    gen, i, strip, st = self.q.get_nowait()
                    if gen != self.gen:
                        continue
                    if i == "done":
                        self.pending = 0
                        self.cache.save()
                    else:
                        self.pending = max(0, self.pending - 1)
                        if strip is not None:
                            self.strip_pil[i] = strip
                        if i not in self.locked:
                            self.status[i] = st
                        self._refresh_row(i)
                    self._update_summary()
            except queue.Empty:
                pass
            root.after(60, self._poll)

        def select(self, i: int):
            if not (0 <= i < len(self.boards)):
                return
            self.sel, self.custom = i, False
            b = self.boards[i]
            self.tex_path, self.thumb_path = b.texture, b.thumb
            if self.tree.exists(str(i)):
                self._syncing = True
                self.tree.selection_set(str(i))
                self.tree.see(str(i))
                self._syncing = False
            self._load_current()

        def step(self, d: int):
            kids = list(self.tree.get_children())
            if not kids:
                return
            cur = str(self.sel)
            if cur not in kids:
                return self.select(int(kids[0]))
            j = kids.index(cur) + d
            if 0 <= j < len(kids):
                self.select(int(kids[j]))

        def _load(self, path):
            if not path:
                return None, ""
            try:
                return load_texture(path), ""
            except Exception as e:
                return None, str(e)

        def _load_current(self):
            self.busy(True)
            try:
                self.tex, self.tex_err = self._load(self.tex_path)
                self.thumb, self.thumb_err = self._load(self.thumb_path)
                if not self.custom and self.sel is not None:
                    sts = []
                    for p, t in ((self.tex_path, self.tex), (self.thumb_path, self.thumb)):
                        try:
                            sts.append(file_status(p, self.cache, t))
                        except Exception:
                            pass
                    self.status[self.sel] = board_status(sts)
                    self.locked.add(self.sel)
                    src = self.thumb or self.tex
                    if src:
                        self.strip_pil[self.sel] = strip_image(src.img)
                    self._refresh_row(self.sel)
                    self._update_summary()
            finally:
                self.busy(False)
            self._refresh_panels()

        # ---------- panel refresh ----------
        def _chips(self, frame, tex, path):
            for w in frame.winfo_children():
                w.destroy()
            if not tex:
                return
            fmt = "QOI" if tex.codec == "qoi" else \
                f"{SURFACE_NAMES.get(tex.fmt, tex.fmt)} · {tex.levels} mip"
            meta = load_default_meta(path)
            items = [f"{tex.width} × {tex.height}", fmt]
            items.append(f"Default · {'PNG' if meta['storage'] == 'png' else 'XNB'} "
                         f"{human_size(meta['stored_bytes'])}" if meta else "No default")
            for t in items:
                tk.Label(frame, text=t, font=F["small"], fg=C["sub"], bg=C["btn"],
                         padx=8, pady=2).pack(side="left", padx=(6, 0))

        def _refresh_panels(self):
            has_tex, has_th = self.tex is not None, self.thumb is not None
            if self.custom and self.tex_path:
                self.title_lbl.config(text=f"File {self.tex_path.stem}")
                try:
                    st = file_status(self.tex_path, self.cache, self.tex) if has_tex else None
                except Exception:
                    st = None
            elif self.sel is not None:
                self.title_lbl.config(text=f"Board {self.boards[self.sel].name}")
                st = self.status.get(self.sel)
            else:
                self.title_lbl.config(text="No board selected")
                st = "hide"
            if st == "hide":
                self.badge.pack_forget()
            else:
                text, fg, bg = BADGES.get(st, BADGES[None])
                self.badge.config(text=text, fg=fg, bg=bg)
                self.badge.pack(side="left", padx=14)
            set_state([self.btn_prev, self.btn_next], bool(self.boards))

            self.tex_file.config(text=self.tex_path.name if self.tex_path else "")
            self.thumb_file.config(text=self.thumb_path.name if self.thumb_path else "")
            self._chips(self.tex_chips, self.tex, self.tex_path)
            self._chips(self.thumb_chips, self.thumb, self.thumb_path)

            def msg(path, err):
                if not path:
                    return "Not found — use Open other .xnb…" if self.boards else \
                        "Open a content folder to begin"
                return f"Cannot read: {err}"
            self.tex_prev.set_image(self.tex.img if has_tex else None, msg(self.tex_path, self.tex_err))
            self.thumb_prev.set_image(self.thumb.img if has_th else None,
                                      msg(self.thumb_path, self.thumb_err))

            tmeta = load_default_meta(self.tex_path) if self.tex_path else None
            hmeta = load_default_meta(self.thumb_path) if self.thumb_path else None
            set_state([self.b_tex_replace, self.b_tex_export, self.b_tex_setdef], has_tex)
            set_state([self.b_tex_revert], bool(tmeta))
            set_state([self.b_th_replace, self.b_th_export, self.b_th_setdef], has_th)
            set_state([self.b_th_gen], has_th and has_tex)
            set_state([self.b_th_revert], bool(hmeta))
            set_state([self.btn_saveall], bool(self.boards))

            def stored(meta):
                if not meta:
                    return "Not saved"
                kind = "PNG" if meta["storage"] == "png" else "XNB copy"
                return f"{kind} · {human_size(meta['stored_bytes'])}"
            saved = (tmeta or hmeta or {}).get("saved_at", "—")
            self.def_vals["saved"].config(text=saved[:16] if saved != "—" else saved)
            self.def_vals["tex"].config(text=stored(tmeta))
            self.def_vals["thumb"].config(text=stored(hmeta))

            def bak(p):
                return bool(p) and p.with_suffix(p.suffix + ".bak").exists()
            b1, b2 = bak(self.tex_path), bak(self.thumb_path)
            self.def_vals["bak"].config(text="Texture + thumbnail" if b1 and b2 else
                                        "Texture only" if b1 else "Thumbnail only" if b2 else
                                        "None yet")
            self._refresh_palette()

        # ---------- board colors ----------
        def _refresh_palette(self):
            self.pal_orig = read_palette(self.tex.img) if self.tex is not None else None
            if self.pal_orig is None:
                self.pal, self._pal_for = None, None
            elif self.pal is None or self._pal_for != self.tex_path:
                self.pal, self._pal_for = list(self.pal_orig), self.tex_path
            self._draw_palette()

        def _pal_changed(self):
            if not self.pal or not self.pal_orig:
                return []
            return [i for i in range(len(PALETTE_SLOTS)) if tuple(self.pal[i]) != tuple(self.pal_orig[i])]

        def _draw_palette(self):
            ok = self.pal is not None
            changed = self._pal_changed()
            for i, (sw, var, ent, was) in enumerate(self.pal_widgets):
                sw.delete("all")
                if not ok:
                    sw.config(cursor="arrow")
                    sw.create_line(4, 40, 56, 4, fill=C["dis"])
                    var.set("")
                    ent.config(state="disabled")
                    was.config(text="")
                    continue
                sw.config(cursor="hand2")
                ent.config(state="normal")
                sw.create_rectangle(0, 0, 64, 48, fill=to_hex(self.pal[i]), outline="")
                if i in changed:
                    # bottom-right corner shows the color currently in the file
                    sw.create_polygon(62, 18, 62, 46, 30, 46, fill=to_hex(self.pal_orig[i]),
                                      outline="")
                    was.config(text=f"was {to_hex(self.pal_orig[i])}", fg=C["accenth"])
                else:
                    was.config(text="", fg=C["muted"])
                try:
                    editing = root.focus_get() is ent
                except Exception:
                    editing = False
                if not editing:
                    var.set(to_hex(self.pal[i]))
            if not ok:
                self.pal_state.config(
                    text="no texture loaded" if self.tex is None else "texture too small",
                    fg=C["muted"])
            elif changed:
                self.pal_state.config(text=f"{len(changed)} changed — not applied yet",
                                      fg=C["accenth"])
            else:
                self.pal_state.config(text="matches the texture", fg=C["muted"])
            set_state([self.b_pal_apply, self.b_pal_reset], ok and bool(changed))
            set_state([self.b_pal_copy], ok)
            set_state([self.b_pal_paste], ok)

        def pick_color(self, i):
            if self.pal is None:
                return
            name = PALETTE_SLOTS[i][1]
            rgb, _hex = colorchooser.askcolor(color=to_hex(self.pal[i]), parent=root,
                                              title=f"{name} color")
            if rgb:
                self.pal[i] = tuple(int(round(v)) for v in rgb[:3])
                self._draw_palette()

        def commit_color(self, i):
            if self.pal is None:
                return
            var = self.pal_widgets[i][1]
            c = parse_color(var.get())
            if c is None:
                if var.get().strip():
                    self.set_status(f"'{var.get().strip()}' is not a color — use #rrggbb or r,g,b")
                var.set(to_hex(self.pal[i]))
                return
            self.pal[i] = c
            var.set(to_hex(c))
            self._draw_palette()

        def reset_colors(self):
            if self.pal_orig:
                self.pal = list(self.pal_orig)
                self._draw_palette()

        def copy_colors(self):
            if not self.pal:
                return
            self.clip = list(self.pal)
            text = ", ".join(to_hex(c) for c in self.pal)
            root.clipboard_clear()
            root.clipboard_append(text)
            self.set_status(f"Copied board colors: {text}")

        def paste_colors(self):
            if self.pal is None:
                return
            found = None
            try:
                text = root.clipboard_get()
                hexes = re.findall(r"#?([0-9a-fA-F]{6})\b", text)
                if len(hexes) >= len(PALETTE_SLOTS):
                    found = [parse_color(h) for h in hexes[:len(PALETTE_SLOTS)]]
            except Exception:
                pass
            found = found or (list(self.clip) if self.clip else None)
            if not found:
                self.set_status("Nothing to paste — copy 4 colors first (e.g. from another board)")
                return
            self.pal = list(found)
            self._draw_palette()
            self.set_status("Pasted board colors — click Apply to write them into the texture")

        def apply_colors(self):
            changed = self._pal_changed()
            if not (self.tex and changed):
                return
            names = ", ".join(PALETTE_SLOTS[i][1].lower() for i in changed)
            new = apply_palette(self.tex.img, self.pal)
            self._write(self.tex_path, self.tex, new,
                        f"Applied board colors ({names}) to {self.tex_path.name}")

        # ---------- actions ----------
        def _which(self, which):
            return (self.tex_path, self.tex) if which == "tex" else (self.thumb_path, self.thumb)

        def _write(self, path, tex, new_img, done_msg):
            if not load_default_meta(path) and messagebox.askyesno(
                    "Save default first?",
                    f"No default is saved for {path.name} yet.\n\n"
                    "Save the current image as the default before replacing it?"):
                try:
                    set_default(path, tex)
                except Exception as e:
                    messagebox.showerror("Cannot set default", str(e))
                    return
            self.busy(True)
            try:
                save_texture(path, new_img, tex)
            except Exception as e:
                messagebox.showerror("Save failed", str(e))
                return
            finally:
                self.busy(False)
            self._load_current()
            self.set_status(done_msg)

        def replace(self, which, file=None):
            path, tex = self._which(which)
            if not tex:
                return
            if file is None:
                file = filedialog.askopenfilename(filetypes=[
                    ("Images", "*.png *.jpg *.jpeg *.bmp *.tga *.gif *.webp"), ("All", "*.*")])
                if not file:
                    return
            try:
                new = Image.open(file)
                new.load()
                new = new.convert("RGBA")
            except Exception as e:
                messagebox.showerror("Cannot open image", str(e))
                return
            # let the user position / zoom / rotate / flip the new image; the result
            # always has exactly the original size (the game expects it)
            dlg = AdjustDialog(root, new, tex.width, tex.height,
                               f"Adjust image — {path.name} ({tex.width}×{tex.height})")
            root.wait_window(dlg)
            if dlg.result is None:
                self.set_status("Replace cancelled")
                return
            new = dlg.result
            if new.size != (tex.width, tex.height):
                new = new.resize((tex.width, tex.height), Image.LANCZOS)
            extra = ""
            if which == "tex" and self.keep_pal.get() and self.pal and new.width >= len(PALETTE_SLOTS):
                new = apply_palette(new, self.pal)
                extra += ", board colors kept"
            self._write(path, tex, new,
                        f"Replaced {path.name} with {Path(file).name}{extra} (backup: {path.name}.bak)")

        def generate_thumb(self):
            if not (self.tex and self.thumb):
                return
            w, h = self.thumb.width, self.thumb.height
            if not messagebox.askyesno(
                    "Generate thumbnail",
                    f"Replace {self.thumb_path.name} with a {w}×{h} downscale "
                    "of the board texture?"):
                return
            new = self.tex.img.resize((w, h), Image.LANCZOS)
            self._write(self.thumb_path, self.thumb, new,
                        f"Thumbnail regenerated from {self.tex_path.name}")

        def export(self, which):
            path, tex = self._which(which)
            if not tex:
                return
            f = filedialog.asksaveasfilename(defaultextension=".png",
                                             initialfile=path.stem + ".png",
                                             filetypes=[("PNG", "*.png")])
            if f:
                tex.img.save(f)
                self.set_status(f"Exported {f}")

        def set_default(self, which):
            path, tex = self._which(which)
            if not tex:
                return
            old = load_default_meta(path)
            if old and not messagebox.askyesno(
                    "Overwrite default?",
                    f"A default for {path.name} was already set on {old['saved_at']}.\n\n"
                    "Replace it with the current image?"):
                return
            self.busy(True)
            try:
                meta = set_default(path, tex)
                self.cache.put(path, meta["pixel_sha256"])
            except Exception as e:
                messagebox.showerror("Cannot set default", str(e))
                return
            finally:
                self.busy(False)
            self._load_current()
            self.set_status(f"Default set for {path.name}: stored as {meta['storage'].upper()}, "
                            f"{human_size(meta['stored_bytes'])}")

        def revert(self, which):
            path, _tex = self._which(which)
            meta = load_default_meta(path) if path else None
            if not meta or not messagebox.askyesno(
                    "Revert to default",
                    f"Replace {path.name} with the default set on {meta['saved_at']}?\n\n"
                    "Your current version will be overwritten."):
                return
            if which == "tex":
                self.pal = None            # show the reverted file's colors, drop unapplied edits
            self.busy(True)
            try:
                revert_to_default(path)
            except Exception as e:
                messagebox.showerror("Revert failed", str(e))
                return
            finally:
                self.busy(False)
            self._load_current()
            self.set_status(f"Reverted {path.name} to the default from {meta['saved_at']}")

        def open_other(self):
            f = filedialog.askopenfilename(filetypes=[("XNB texture", "*.xnb")])
            if not f:
                return
            self.custom = True
            self.tex_path, self.thumb_path = Path(f), None
            self._syncing = True
            self.tree.selection_remove(*self.tree.selection())
            self._syncing = False
            self._load_current()
            self.set_status(f"Opened {Path(f).name}")

        def save_all_defaults(self):
            files = [p for b in self.boards for p in (b.texture, b.thumb) if p]
            todo = [p for p in files if not load_default_meta(p)]
            if not files:
                return
            if not todo:
                messagebox.showinfo("Defaults", "Every texture and thumbnail already has a default.")
                return
            if not messagebox.askyesno(
                    "Save all as defaults",
                    f"Save the CURRENT images of {len(todo)} file(s) as their defaults?\n"
                    f"({len(files) - len(todo)} file(s) that already have a default are skipped.)"):
                return
            root.config(cursor="watch")
            errors = []
            for i, p in enumerate(todo, 1):
                self.set_status(f"Saving defaults… {i}/{len(todo)}  {p.name}")
                root.update()
                try:
                    meta = set_default(p)
                    self.cache.put(p, meta["pixel_sha256"])
                except Exception as e:
                    errors.append(f"{p.name}: {e}")
            root.config(cursor="")
            self.cache.save()
            self.locked.clear()
            if self.sel is not None and not self.custom:
                self._load_current()
            else:
                self._refresh_panels()
            self._start_worker()
            self.set_status(f"Defaults saved for {len(todo) - len(errors)} file(s)"
                            + (f", {len(errors)} failed" if errors else ""))
            if errors:
                messagebox.showwarning("Some defaults failed", "\n".join(errors[:15]))

        def close(self):
            self.gen += 1
            self.cache.save()
            root.destroy()

    App()
    root.mainloop()


if __name__ == "__main__":
    run_gui(sys.argv[1] if len(sys.argv) > 1 else None)
