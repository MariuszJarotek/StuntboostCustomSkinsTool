#!/usr/bin/env python3
"""Fast tests of the library (no window needed): file formats, stock copies, board colours, languages.

    python tests/test_core.py          plain Python, prints each test
    python -m pytest tests             the same tests with pytest, if you have it

Every test works on a fresh fake game in a temporary folder (tests/fixture.py), never on real game files.
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))

import fixture  # noqa: E402
from PIL import Image, ImageChops  # noqa: E402

from xnb_board_tool import boards, defaults, i18n, qoi, xnb  # noqa: E402


def _same(a: Image.Image, b: Image.Image) -> bool:
    """True when two images have identical RGBA pixels."""
    return a.size == b.size and ImageChops.difference(a.convert("RGBA"), b.convert("RGBA")).getbbox() is None


def _game(tmp: str, n: int = 6) -> Path:
    """A fresh fake board folder with n boards."""
    return fixture.make_boards(Path(tmp) / "Board", n)


def test_qoi_round_trip():
    """QOI encode then decode gives the same pixels (both the built-in codec and the optional package)."""
    im = fixture.board_art(3, 300, 80)
    assert _same(qoi.qoi_decode(qoi.qoi_encode(im)), im)


def test_scan_finds_boards_and_thumbnails():
    """scan() pairs <n>.xnb with <n>Thumbnail.xnb."""
    with tempfile.TemporaryDirectory() as tmp:
        folder = _game(tmp, 6)
        found = boards.scan(folder)
        assert len(found) == 6, [b.name for b in found]
        assert all(b.texture and b.thumb for b in found)


def test_load_and_save_texture():
    """A texture saved with save_texture loads back with the new pixels, keeps its codec and leaves a .bak."""
    with tempfile.TemporaryDirectory() as tmp:
        p = _game(tmp, 2) / "1.xnb"
        old = xnb.load_texture(p)
        assert old.codec == "qoi" and old.img.size == (1920, 432)
        new = Image.new("RGBA", old.img.size, (10, 200, 90, 255))
        xnb.save_texture(p, new, old)
        again = xnb.load_texture(p)
        assert _same(again.img, new) and again.codec == "qoi"
        assert p.with_name(p.name + ".bak").exists(), "the first save keeps a backup"


def test_board_colours():
    """The four board colours are the first four pixels of the top row."""
    with tempfile.TemporaryDirectory() as tmp:
        p = _game(tmp, 2) / "1.xnb"
        pal = boards.read_texture_palette(p)
        assert [tuple(c[:3]) for c in pal] == fixture.PALETTES[1], pal
        img = boards.apply_palette(xnb.load_texture(p).img, [(1, 2, 3)] * 4)
        assert [tuple(c[:3]) for c in boards.read_palette(img)] == [(1, 2, 3)] * 4


def test_stock_copy_and_revert():
    """set_default stores a stock copy; after a change the status is 'mod' and revert brings the pixels back."""
    with tempfile.TemporaryDirectory() as tmp:
        p = _game(tmp, 2) / "1.xnb"
        cache = defaults.HashCache()
        assert defaults.file_status(p, cache) == "none"
        original = xnb.load_texture(p)
        defaults.set_default(p, original)
        assert defaults.file_status(p, cache) == "def"
        xnb.save_texture(p, Image.new("RGBA", original.img.size, (255, 0, 0, 255)), original)
        assert defaults.file_status(p, defaults.HashCache()) == "mod"
        defaults.revert_to_default(p)
        assert _same(xnb.load_texture(p).img, original.img)


def test_plural_rules():
    """Polish has three plural forms (1 / 2-4 / 5+, teens in the third), French treats 0 as singular."""
    pi = i18n._plural_index
    assert [pi("pl", n) for n in (1, 2, 4, 5, 12, 22, 25)] == [0, 1, 1, 2, 2, 1, 2]
    assert [pi("fr", n) for n in (0, 1, 2)] == [0, 0, 1]
    assert [pi("en", n) for n in (0, 1, 2)] == [1, 0, 1]


def test_translations_complete():
    """check_translations.py finds no missing or broken texts in any language."""
    r = subprocess.run([sys.executable, str(ROOT / "check_translations.py")], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout[-2000:]


if __name__ == "__main__":
    failed = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print("ok    ", name)
            except Exception as e:                     # keep going, report every failure
                failed += 1
                print("FAILED", name, "-", type(e).__name__, e)
    print(f"{failed} failed" if failed else "all passed")
    sys.exit(1 if failed else 0)
