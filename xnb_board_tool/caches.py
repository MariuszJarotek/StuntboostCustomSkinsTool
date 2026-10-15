"""In-memory texture cache and the on-disk gallery card cache."""
from __future__ import annotations

import hashlib
import io
import json
import os
import threading
from pathlib import Path
from typing import Optional

from PIL import Image

from .common import _norm, atomic_write
from .xnb import TexData, load_texture


class TextureCache:
    """Recently decoded textures (thread-safe LRU), keyed by path and checked against the
    file's size + modification time, so a changed file is always decoded again."""

    def __init__(self, size: int = 12, max_bytes: int = 24 << 20, keep: int = 2):
        # bounded by memory, not only by count: 12 full boards would be ~40 MB, while small
        # thumbnails cost almost nothing; the newest `keep` entries always stay
        """A cache of decoded textures limited both by count (`size`) and by memory (`max_bytes`); the newest
        `keep` entries always stay even when they are big.
        """
        self.size, self.max_bytes, self.keep = size, max_bytes, keep
        self.lock = threading.Lock()
        self.data: "dict[str, tuple]" = {}
        self.order: list = []

    @staticmethod
    def _sig(path):
        """A file's signature (size, modification time): a changed file no longer matches its cached entry."""
        st = os.stat(path)
        return (st.st_size, st.st_mtime_ns)

    def get(self, path) -> Optional[TexData]:
        """The cached TexData of a file, or None when it is not cached or the file has changed since. A hit moves
        the entry to the newest end.
        """
        if not path:
            return None
        key = _norm(path)
        try:
            sig = self._sig(path)
        except OSError:
            return None
        with self.lock:
            e = self.data.get(key)
            if e is None or e[0] != sig:
                return None
            if key in self.order:
                self.order.remove(key)
            self.order.append(key)
            return e[1]

    def load(self, path) -> TexData:
        """Cached texture, or decode it (and remember it)."""
        t = self.get(path)
        if t is not None:
            return t
        sig = self._sig(path)
        t = load_texture(path)
        self.put(path, t, sig)
        return t

    def put(self, path, tex: TexData, sig=None):
        """Caches a decoded texture (with the file's signature, or the given one), then drops the oldest entries
        until the count and memory limits are met.
        """
        key = _norm(path)
        try:
            sig = sig or self._sig(path)
        except OSError:
            return
        with self.lock:
            self.data[key] = (sig, tex)
            if key in self.order:
                self.order.remove(key)
            self.order.append(key)
            while len(self.order) > self.size:
                self.data.pop(self.order.pop(0), None)
            while len(self.order) > self.keep and self.bytes_used() > self.max_bytes:
                self.data.pop(self.order.pop(0), None)

    def bytes_used(self) -> int:
        """Pixels held (4 bytes each), for the memory limit. Call with the lock held."""
        return sum(t.width * t.height * 4 for _s, t in self.data.values())

    def remember_saved(self, path, old: TexData, img: Image.Image):
        """After a texture was written: keep the pixels we just wrote instead of decoding the file
        again. Only for QOI textures (lossless, so the file decodes to exactly these pixels);
        anything else is dropped and decoded on the next use."""
        if old is not None and old.codec == "qoi":
            im = img.convert("RGBA")
            if im is img:
                im = img.copy()                       # never share a buffer that may be edited later
            self.put(path, TexData(im, old.fmt, im.width, im.height, old.levels, False, "qoi"))
        else:
            self.invalidate(path)

    def invalidate(self, path):
        """Forgets the cached texture of a file (after the tool wrote it)."""
        if path:
            with self.lock:
                self.data.pop(_norm(path), None)


TEXCACHE = TextureCache()


def user_cache_dir(folder: Path) -> Path:
    """Per-folder cache location outside the game folder (gallery card images etc.)."""
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    tag = hashlib.sha1(_norm(folder).encode("utf-8")).hexdigest()[:16]
    return Path(base) / "XNB Board Tool" / "cache" / tag


class CardCache:
    """Gallery card images and board colors stored on disk, so the gallery appears immediately
    on later launches. Entries are reused only while the source files are unchanged."""
    VERSION = 1

    def __init__(self):
        """An empty card cache, not yet attached to a content folder."""
        self.lock = threading.Lock()
        self.dir: Optional[Path] = None
        self.index: dict = {}
        self.dirty = False

    def attach(self, folder: Path):
        """Uses the on-disk card cache of a content folder (in the user's cache folder) and loads its index; an
        index from another cache version is ignored.
        """
        self.dir = user_cache_dir(folder)
        self.index, self.dirty = {}, False
        try:
            data = json.loads((self.dir / "index.json").read_text("utf-8"))
            if data.get("v") == self.VERSION:
                self.index = data.get("boards", {})
        except Exception:
            self.index = {}

    @staticmethod
    def sig(path):
        """A source file's signature as stored in the index ([size, mtime]), or None when the file is missing.
        """
        if not path:
            return None
        try:
            st = os.stat(path)
            return [st.st_size, st.st_mtime_ns]
        except OSError:
            return None

    def card(self, name: str, src_sig) -> Optional[Image.Image]:
        """The cached card image (the deck picture used on the Wall) of a board, if it was made from the current
        version of its source file; else None.
        """
        with self.lock:
            e = self.index.get(name)
        if not e or src_sig is None or e.get("src") != src_sig or not self.dir:
            return None
        try:
            im = Image.open(self.dir / f"card_{name}.png")
            im.load()
            return im.convert("RGBA")
        except Exception:
            return None

    def palette(self, name: str, tex_sig) -> Optional[list]:
        """The cached four deck colours of a board, if they were read from the current version of its texture; else
        None.
        """
        with self.lock:
            e = self.index.get(name)
        if not e or tex_sig is None or e.get("tex") != tex_sig or not e.get("pal"):
            return None
        return [tuple(c) for c in e["pal"]]

    def store(self, name: str, src_sig=None, card: Optional[Image.Image] = None, tex_sig=None, pal=None):
        """Remembers a board's card image (written as card_<name>.png) and/or its colours, each with the signature
        of the file it came from.
        """
        if not self.dir:
            return
        with self.lock:
            e = dict(self.index.get(name, {}))
        if card is not None and src_sig is not None:
            try:
                self.dir.mkdir(parents=True, exist_ok=True)
                buf = io.BytesIO()
                card.save(buf, "PNG", compress_level=3)
                atomic_write(self.dir / f"card_{name}.png", buf.getvalue())
                e["src"] = src_sig
            except Exception:
                return
        if pal is not None and tex_sig is not None:
            e["tex"], e["pal"] = tex_sig, [list(c[:3]) for c in pal]
        with self.lock:
            self.index[name] = e
            self.dirty = True

    def save(self):
        """Writes the index when something changed (atomically; errors are ignored)."""
        if not self.dir or not self.dirty:
            return
        try:
            self.dir.mkdir(parents=True, exist_ok=True)
            with self.lock:
                text = json.dumps({"v": self.VERSION, "boards": self.index})
                self.dirty = False
            atomic_write(self.dir / "index.json", text.encode("utf-8"))
        except Exception:
            pass
