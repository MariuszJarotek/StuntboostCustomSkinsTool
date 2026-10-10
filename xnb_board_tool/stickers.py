"""Sticker packs on disk: every folder inside the stickers folder is a pack.

Images directly in the stickers folder form the "Unsorted" pack. Packs can be exported and
imported as .zip files; imports only keep images, re-saved as PNG.
"""
from __future__ import annotations

import io
import shutil
import sys
import zipfile
from pathlib import Path
from typing import Optional

from PIL import Image

STICKER_EXT = {".png", ".webp", ".jpg", ".jpeg", ".gif", ".bmp", ".tga"}
MAX_SIDE = 1024                     # stickers are stored at most this large
ZIP_MAX_FILES, ZIP_MAX_ONE, ZIP_MAX_ALL = 500, 25 << 20, 300 << 20


def app_dir() -> Path:
    """Folder of the program: next to the .exe when frozen, else next to the launcher script."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def assets_dir() -> Path:
    """Built-in assets shipped inside the package (works from source and from a PyInstaller build)."""
    base = Path(getattr(sys, "_MEIPASS", "")) / "xnb_board_tool" if getattr(sys, "frozen", False) else None
    if base is not None and (base / "assets").is_dir():
        return base / "assets"
    return Path(__file__).resolve().parent / "assets"


def _writable_dir(preferred: Path, fallback_name: str) -> Path:
    try:
        preferred.mkdir(parents=True, exist_ok=True)
        probe = preferred / ".write_test"
        probe.write_bytes(b"")
        probe.unlink()
        return preferred
    except OSError:
        from .settings import settings_path
        d = settings_path().parent / fallback_name
        d.mkdir(parents=True, exist_ok=True)
        return d


def clean_name(name: str, limit: int = 40) -> str:
    """A safe file / folder name: letters, digits and a few punctuation marks."""
    name = "".join(ch for ch in (name or "") if ch.isalnum() or ch in " -_.()&!'").strip(" .")
    return name[:limit]


def images_in(folder: Path) -> list:
    try:
        return sorted((p for p in Path(folder).iterdir() if p.is_file() and p.suffix.lower() in STICKER_EXT
                       and not p.name.startswith(".")), key=lambda p: p.stem.lower())
    except OSError:
        return []


def _unique(path: Path) -> Path:
    if not path.exists():
        return path
    n = 2
    while True:
        cand = path.with_name(f"{path.stem}-{n}{path.suffix}") if path.suffix else \
            path.with_name(f"{path.name} {n}")
        if not cand.exists():
            return cand
        n += 1


def _save_png(im: Image.Image, folder: Path, stem: str) -> Path:
    im = im.convert("RGBA")
    im.thumbnail((MAX_SIDE, MAX_SIDE))
    dest = _unique(Path(folder) / f"{clean_name(stem) or 'sticker'}.png")
    im.save(dest)
    return dest


class StickerLibrary:
    LOOSE = ""                      # key of the "Unsorted" pack (images directly in the folder)

    def __init__(self, root: Optional[Path] = None):
        self.root = Path(root) if root else _writable_dir(app_dir() / "stickers", "stickers")
        self.seed()

    def seed(self):
        """Adds the built-in Starter pack the first time (or when it was deleted and nothing else exists)."""
        src = assets_dir() / "stickers"
        if not src.is_dir():
            return
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            if any(self.root.iterdir()):
                return
            for pack in src.iterdir():
                if pack.is_dir():
                    shutil.copytree(pack, self.root / pack.name, dirs_exist_ok=True)
        except OSError:
            pass

    # ---- packs ----
    def packs(self) -> list:
        """[(key, folder, label)]: 'Unsorted' when it has images, then one entry per subfolder."""
        out = []
        if not self.root.is_dir():
            return out
        if images_in(self.root):
            out.append((self.LOOSE, self.root, "Unsorted"))
        try:
            dirs = sorted((d for d in self.root.iterdir() if d.is_dir() and not d.name.startswith((".", "_"))),
                          key=lambda d: d.name.lower())
        except OSError:
            dirs = []
        out += [(d.name, d, d.name) for d in dirs]
        return out

    def pack_dir(self, key: str) -> Path:
        return self.root if key == self.LOOSE else self.root / key

    def new_pack(self, name: str) -> str:
        name = clean_name(name)
        if not name:
            raise ValueError("Use letters, numbers, spaces, - or _ in the name.")
        d = _unique(self.root / name)
        d.mkdir(parents=True)
        return d.name

    def ensure_pack(self, name: str) -> str:
        d = self.root / clean_name(name)
        d.mkdir(parents=True, exist_ok=True)
        return d.name

    def rename_pack(self, key: str, name: str) -> str:
        name = clean_name(name)
        if not name:
            raise ValueError("Use letters, numbers, spaces, - or _ in the name.")
        if name == key:
            return key
        new = _unique(self.root / name)
        (self.root / key).rename(new)
        return new.name

    def delete_pack(self, key: str):
        """Deletes the pack's images and its folder (only if nothing else is left in it)."""
        d = self.pack_dir(key)
        for p in images_in(d):
            p.unlink()
        if key != self.LOOSE:
            d.rmdir()

    def export_pack(self, key: str, zip_path: Path) -> int:
        label = "Unsorted" if key == self.LOOSE else key
        imgs = images_in(self.pack_dir(key))
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
            for p in imgs:
                z.write(p, f"{label}/{p.name}")
        return len(imgs)

    def import_zip(self, zip_path: Path) -> tuple:
        """Imports a .zip pack. Only images are kept, decoded and re-saved as PNG, so nothing else
        in the file is used. Returns (pack key, number of stickers)."""
        with zipfile.ZipFile(zip_path) as z:
            items = [i for i in z.infolist() if not i.is_dir()
                     and Path(i.filename).suffix.lower() in STICKER_EXT
                     and not Path(i.filename).name.startswith(".")]
            if not items:
                raise ValueError("No images were found in that .zip file.")
            if len(items) > ZIP_MAX_FILES or sum(i.file_size for i in items) > ZIP_MAX_ALL \
                    or any(i.file_size > ZIP_MAX_ONE for i in items):
                raise ValueError("That .zip is too large for a sticker pack.")
            tops = {Path(i.filename).parts[0] for i in items if len(Path(i.filename).parts) > 1}
            name = clean_name(tops.pop() if len(tops) == 1 else Path(zip_path).stem) or "Imported"
            d = _unique(self.root / name)
            d.mkdir(parents=True)
            n = 0
            for i in items:
                try:
                    im = Image.open(io.BytesIO(z.read(i)))
                    im.load()
                    _save_png(im, d, Path(i.filename).stem)
                    n += 1
                except Exception:
                    continue
        return d.name, n

    def import_images(self, files, key: str) -> tuple:
        """Copies images into a pack (as PNG). Returns (added, [(file, error)])."""
        d = self.pack_dir(key)
        d.mkdir(parents=True, exist_ok=True)
        added, errors = 0, []
        for f in files:
            try:
                im = Image.open(f)
                im.load()
                _save_png(im, d, Path(f).stem)
                added += 1
            except Exception as e:
                errors.append((Path(f).name, str(e)))
        return added, errors

    def move(self, p: Path, dest_dir: Path) -> Path:
        dest = _unique(Path(dest_dir) / p.name)
        p.rename(dest)
        return dest

    def remove(self, p: Path):
        """Deletes one sticker file, only if it lives in the library."""
        root = self.root.resolve()
        parent = Path(p).resolve().parent
        if parent == root or parent.parent == root:
            Path(p).unlink()
        else:
            raise ValueError("That file is not in the sticker library.")
