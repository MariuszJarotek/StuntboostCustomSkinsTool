"""Default snapshots (save / revert) and the board status (matches default, modified)."""
from __future__ import annotations

from .i18n import _

import datetime
import hashlib
import io
import json
import os
import threading
from pathlib import Path
from typing import Optional

from PIL import Image

from .common import XnbError, _norm, atomic_write
from .xnb import TexData, load_texture, parse_xnb, save_texture


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
    """Where the stock copy of a file lives: (the _board_defaults folder, the metadata .json, the .default.png, the
    .default.xnbdef).
    """
    d = Path(path).parent / DEF_DIR
    return d, d / (Path(path).name + ".json"), \
        d / (Path(path).name + ".default.png"), d / (Path(path).name + ".default.xnbdef")


def pixel_hash(img: Image.Image) -> str:
    """SHA-256 of an image's RGBA pixels: two textures with the same pixels have the same hash whatever their file
    bytes.
    """
    return hashlib.sha256(img.convert("RGBA").tobytes()).hexdigest()


def load_default_meta(path: Path) -> Optional[dict]:
    """The stock metadata of a file (when it was saved, how it is stored, its pixel hash), or None when no stock
    copy exists.
    """
    d, meta_p, png_p, xnb_p = _def_paths(path)
    try:
        meta = json.loads(meta_p.read_text("utf-8"))
        stored = png_p if meta["storage"] == "png" else xnb_p
        return meta if stored.exists() else None
    except Exception:
        return None


def set_default(path: Path, tex: Optional[TexData] = None) -> dict:
    """Saves the file as it is now as its stock copy in _board_defaults: QOI textures as a PNG of their pixels
    when that is not much bigger than the .xnb (PNG_MAX_RATIO), everything else as an exact copy of the .xnb.
    Writes the metadata (date, storage, sizes, pixel hash) next to it and returns it.
    """
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


def load_default_image(path: Path) -> Optional[Image.Image]:
    """The saved default (stock) image of a texture, or None when there is none."""
    meta = load_default_meta(path)
    if not meta:
        return None
    _d, _m, png_p, xnb_p = _def_paths(path)
    if meta["storage"] == "xnb":
        return load_texture(xnb_p).img
    img = Image.open(png_p)
    img.load()
    return img.convert("RGBA")


def revert_to_default(path: Path) -> dict:
    """Puts a file back to its stock copy: the exact saved bytes for .xnb snapshots (checked first), or the stock
    pixels encoded as QOI for PNG copies. Written atomically; returns the stock metadata. Raises XnbError when
    there is no stock copy.
    """
    path = Path(path)
    meta = load_default_meta(path)
    if not meta:
        raise XnbError(_("no default has been set for this file"))
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


class HashCache:
    """Remembers pixel hashes by (file size, mtime) so status checks stay fast."""

    def __init__(self):
        """An empty cache, not yet attached to a folder."""
        self.lock = threading.Lock()
        self.data: dict = {}
        self.file: Optional[Path] = None
        self.dirty = False

    def attach(self, root: Path):
        """Uses the cache file of a content folder (loading what it holds)."""
        self.file = Path(root) / DEF_DIR / "_hash_cache.json"
        try:
            self.data = json.loads(self.file.read_text("utf-8"))
        except Exception:
            self.data = {}
        self.dirty = False

    @staticmethod
    def _sig(path):
        """A file's signature for the cache: its size and modification time."""
        st = os.stat(path)
        return [st.st_size, st.st_mtime_ns]

    def get(self, path) -> Optional[str]:
        """The cached pixel hash of a file, or None when it is unknown or the file has changed since."""
        try:
            sig = self._sig(path)
        except OSError:
            return None
        with self.lock:
            e = self.data.get(_norm(path))
        return e["h"] if e and e.get("sig") == sig else None

    def put(self, path, h: str):
        """Stores a file's pixel hash with its current signature."""
        try:
            sig = self._sig(path)
        except OSError:
            return
        with self.lock:
            self.data[_norm(path)] = {"sig": sig, "h": h}
            self.dirty = True

    def save(self):
        """Writes the cache to disk when something changed (atomically; errors are ignored)."""
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
    """One status for a board from the statuses of its files: 'mod' when any file differs from stock, else 'none'
    when one has no stock, else 'def'; None while unknown.
    """
    s = [x for x in statuses if x]
    if not s:
        return None
    if "mod" in s:
        return "mod"
    if "none" in s:
        return "none"
    return "def"
