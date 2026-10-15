"""Reading and writing MonoGame XNB files (Texture2D, QOI-in-XNB, GLTF model JSON)."""
from __future__ import annotations

from .i18n import _

import json
import struct
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageChops

from .common import XnbError, atomic_write, check_size
from .qoi import qoi_decode, qoi_encode


SURFACE_NAMES = {0: "Color (RGBA8)", 4: "DXT1", 5: "DXT3", 6: "DXT5"}


FOURCC = {4: b"DXT1", 5: b"DXT3", 6: b"DXT5"}


def read7(data: bytes, p: int):
    """Reads a 7-bit encoded integer (the .NET variable-length format XNB uses for counts and string lengths) at
    offset p. Returns (value, offset after it).
    """
    result = shift = 0
    while True:
        b = data[p]
        p += 1
        result |= (b & 0x7F) << shift
        if not b & 0x80:
            return result, p
        shift += 7


def read_str(data: bytes, p: int):
    """Reads a length-prefixed UTF-8 string at offset p. Returns (text, offset after it)."""
    n, p = read7(data, p)
    return data[p:p + n].decode("utf-8"), p + n


@dataclass
class XnbInfo:
    """What parse_xnb finds in an XNB header: the type reader of the main asset, where its data starts, the format
    version and the flags.
    """
    reader: str      # type reader of the primary asset
    content: int     # offset where the asset's own data begins
    version: int
    flags: int


def parse_xnb(data: bytes) -> XnbInfo:
    """Reads an XNB file's header and type-reader list. Raises XnbError (in plain words) for files that are not
    XNB, compressed, or damaged.
    """
    try:
        if data[:3] != b"XNB":
            raise XnbError(_("not an XNB file"))
        version, flags = data[4], data[5]
        if flags & 0xC0:
            raise XnbError(_("compressed XNB files are not supported"))
        p = 10
        count, p = read7(data, p)
        readers = []
        for _i in range(count):
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


@dataclass
class TexData:
    """A decoded texture and how it was stored, so it can be written back the same way: the image, the surface
    format, size, mip levels, whether alpha was premultiplied and the codec ('tex2d' for MonoGame Texture2D,
    'qoi' for STUNTBOOST's QoiReader).
    """
    img: Image.Image
    fmt: int
    width: int
    height: int
    levels: int
    premult: bool
    codec: str = "tex2d"   # 'tex2d' (MonoGame Texture2D) or 'qoi' (BytingPipeline.QoiReader)


def _dds(w: int, h: int, fourcc: bytes, raw: bytes) -> bytes:
    """Wraps raw DXT/BC data in a minimal DDS header so Pillow can decode it."""
    return (
        b"DDS " + struct.pack("<7I", 124, 0x81007, h, w, len(raw), 0, 1)
        + b"\0" * 44
        + struct.pack("<2I4s5I", 32, 4, fourcc, 0, 0, 0, 0, 0)
        + struct.pack("<5I", 0x1000, 0, 0, 0, 0)
        + raw
    )


def load_texture(path: Path) -> TexData:
    """Reads a texture .xnb (MonoGame Texture2D in the usual formats, or a QOI texture) into TexData. Raises
    XnbError for anything else.
    """
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
    if premult and a.getextrema()[0] < 255:
        # show / export / edit with normal (straight) alpha; save_texture premultiplies again
        img = Image.frombytes("RGBa", img.size, img.tobytes()).convert("RGBA")
    return TexData(img, fmt, w, h, max(1, levels), premult)


def save_texture(path: Path, new_img: Image.Image, old: TexData) -> None:
    """Writes a new image into an existing texture .xnb, keeping its header and codec: QOI textures get the new
    image as QOI; Texture2D ones are written as uncompressed Color (RGBA) with the same number of mip levels
    (premultiplied again when the original was). The first time a file is written a .bak copy of the original
    is kept; every write is atomic, so a crash never leaves half a file.
    """
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
    """The JSON text a GLTF model .xnb carries (BytingPipeline.GLTFReader), parsed. Used to find which texture a
    board model uses.
    """
    data = Path(path).read_bytes()
    info = parse_xnb(data)
    text, _unused = read_str(data, info.content)
    return json.loads(text)
