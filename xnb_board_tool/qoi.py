"""QOI image codec (pure Python, with an optional fast path through the `qoi` package)."""
from __future__ import annotations

import struct

from PIL import Image

from .common import XnbError, check_size


# ---- QOI codec (pure Python; the game stores board images as QOI inside XNB) ----
_QOI_FAST = None      # None = not checked yet, False = unavailable, else the `qoi` module


def _qoi_fast():
    """The optional `qoi` package (C, much faster), only if it decodes exactly like our own
    decoder. Checked once with a test image; any problem means we keep the pure-Python path."""
    global _QOI_FAST
    if _QOI_FAST is None:
        _QOI_FAST = False
        try:
            import numpy as np
            import qoi as qoilib
            test = Image.new("RGBA", (37, 9))
            test.putdata([((x * 7) % 256, (x * 13 + y) % 256, (y * 29) % 256, 255 if x % 5 else 90)
                          for y in range(9) for x in range(37)])
            arr = np.asarray(qoilib.decode(qoi_encode(test)))
            if arr.shape == (9, 37, 4) and arr.dtype == np.uint8 and arr.tobytes() == test.tobytes():
                _QOI_FAST = qoilib
        except Exception:
            _QOI_FAST = False
    return _QOI_FAST or None


def qoi_decode(b: bytes) -> Image.Image:
    """Decodes a QOI image (the format STUNTBOOST stores its textures in) to an RGBA PIL image. Uses the fast `qoi`
    package when it is installed and its result checks out, else the pure-Python decoder below. Raises XnbError
    for data that is not QOI.
    """
    if b[:4] != b"qoif":
        raise XnbError("QOI magic not found")
    fast = _qoi_fast()
    if fast is not None and len(b) >= 14:
        try:
            import numpy as np
            w, h = struct.unpack(">II", b[4:12])
            check_size(w, h)
            arr = np.asarray(fast.decode(bytes(b)))
            if arr.ndim == 3 and arr.shape[:2] == (h, w) and arr.dtype == np.uint8:
                if arr.shape[2] == 3:
                    arr = np.dstack([arr, np.full((h, w), 255, np.uint8)])
                if arr.shape[2] == 4:
                    return Image.fromarray(np.ascontiguousarray(arr), "RGBA")
        except XnbError:
            raise
        except Exception:
            pass                        # fall back to the pure-Python decoder below
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
    """Encodes an image as QOI (RGBA). Uses the fast `qoi` package when installed and only if its output decodes
    back to the exact same pixels; otherwise the pure-Python encoder, which follows the QOI specification.
    """
    img = img.convert("RGBA")
    w, h = img.size
    fast = _qoi_fast()
    if fast is not None and hasattr(fast, "encode"):
        # the `qoi` package is ~40x faster; its result is only used if it is a valid RGBA QOI
        # stream that decodes back to exactly the same pixels
        try:
            import numpy as np
            arr = np.ascontiguousarray(np.asarray(img, dtype=np.uint8))
            data = bytes(fast.encode(arr))
            if data[:4] == b"qoif" and struct.unpack(">II", data[4:12]) == (w, h) and data[12] == 4 \
                    and data[-8:] == b"\x00" * 7 + b"\x01":
                back = np.asarray(fast.decode(data))
                if back.shape == (h, w, 4) and back.dtype == np.uint8 and back.tobytes() == arr.tobytes():
                    return data
        except Exception:
            pass                        # fall back to the pure-Python encoder below
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


def _qoi_first_pixels(b: bytes, count: int) -> list:
    """The first `count` pixels of a QOI image without decoding the rest."""
    if b[:4] != b"qoif":
        raise XnbError("QOI magic not found")
    out, index = [], [(0, 0, 0, 0)] * 64
    r = g = bl = 0
    a = 255
    p = 14
    while len(out) < count:
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
                out.extend([(r, g, bl)] * ((b1 & 0x3F) + 1))
                continue
        index[(r * 3 + g * 5 + bl * 7 + a * 11) & 63] = (r, g, bl, a)
        out.append((r, g, bl))
    return out[:count]
