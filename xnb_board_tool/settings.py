"""Themes, layouts and the user settings file."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from PIL import Image, ImageDraw

from .common import atomic_write


# --------------------------------------------------------------------------
#  GUI
# --------------------------------------------------------------------------
THEMES = {
    "dark": {
        "bg": "#141518", "panel": "#1a1c20", "side": "#18191d", "border": "#2a2d33",
        "btn": "#24262b", "btnh": "#2d3036", "btnb": "#353840", "sel": "#2a2d33",
        "text": "#e7e8ea", "muted": "#9aa0a8", "sub": "#b8bcc3", "dis": "#5c6168",
        "accent": "#f0a830", "accenth": "#ffc35c", "green": "#5fbf82", "onaccent": "#141518",
        "selfill": "#4a3a1c", "warn": "#ffc35c", "warnbg": "#3a2f1a", "okfg": "#7fd49e",
        "okbg": "#1f3328", "chk1": "#2a2c31", "chk2": "#33363c", "dark": True,
    },
    "light": {
        "bg": "#eceef2", "panel": "#ffffff", "side": "#f6f7f9", "border": "#d9dce2",
        "btn": "#f1f3f6", "btnh": "#e4e7ec", "btnb": "#c9cdd5", "sel": "#dfe6f3",
        "text": "#16181d", "muted": "#5c6370", "sub": "#3f4550", "dis": "#a3a9b3",
        "accent": "#f0a830", "accenth": "#f6bd56", "green": "#2e9d5b", "onaccent": "#141518",
        "selfill": "#ffe2a8", "warn": "#9a5b00", "warnbg": "#fff1d6", "okfg": "#1f7a45",
        "okbg": "#dff3e6", "chk1": "#e6e8ec", "chk2": "#d5d9df", "dark": False,
    },
}


LAYOUTS = {
    "studio": ("Studio", "Big 3D preview in the middle. Board list on the left, colors, thumbnail "
                         "and defaults in an inspector on the right."),
    "gallery": ("Gallery", "Every board as a card with its 4 colors. The selected board opens in an "
                           "editor drawer on the right."),
    "classic": ("Classic", "The original layout: texture and 3D side by side, colors below, "
                           "thumbnail and defaults at the bottom."),
}


C: dict = {}


BADGES: dict = {}


SETTINGS = {"layout": "studio", "theme": "dark", "gallery_cols": "auto", "gpu3d": True}


GALLERY_COLS = ("auto", "2", "3", "4", "5", "6")


def set_theme(name: str) -> None:
    C.clear()
    C.update(THEMES.get(name, THEMES["dark"]))
    BADGES.clear()
    BADGES.update({
        "def": ("Matches default", C["okfg"], C["okbg"]),
        "mod": ("Modified \u2014 differs from default", C["warn"], C["warnbg"]),
        "none": ("No default saved", C["sub"], C["btn"]),
        None: ("Checking\u2026", C["muted"], C["btn"]),
    })
    _checker_cache.clear()


def settings_path() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home() / ".config")
    return Path(base) / "XNB Board Tool" / "settings.json"


def load_settings() -> dict:
    out = {"layout": "studio", "theme": "dark", "gallery_cols": "auto", "gpu3d": True}
    try:
        data = json.loads(settings_path().read_text("utf-8"))
        if data.get("layout") in LAYOUTS:
            out["layout"] = data["layout"]
        if data.get("theme") in THEMES:
            out["theme"] = data["theme"]
        if str(data.get("gallery_cols")) in GALLERY_COLS:
            out["gallery_cols"] = str(data["gallery_cols"])
        if isinstance(data.get("gpu3d"), bool):
            out["gpu3d"] = data["gpu3d"]
        if isinstance(data.get("drawer_w"), int) and 300 <= data["drawer_w"] <= 2000:
            out["drawer_w"] = data["drawer_w"]
    except Exception:
        pass
    return out


def save_settings(values: dict) -> None:
    try:
        sp = settings_path()
        sp.parent.mkdir(parents=True, exist_ok=True)
        atomic_write(sp, json.dumps({k: values[k] for k in ("layout", "theme", "gallery_cols", "drawer_w", "gpu3d") if k in values}, indent=2).encode("utf-8"))
    except Exception:
        pass


def _rgb(hex_color: str, a: int = 255):
    h = hex_color.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4)) + (a,)


_checker_cache: dict = {}


def checker(w: int, h: int, cell: int = 8) -> Image.Image:
    key = (w, h, cell)
    im = _checker_cache.get(key)
    if im is None:
        c1, c2 = _rgb(C.get("chk1", "#2a2c31")), _rgb(C.get("chk2", "#33363c"))
        tile = Image.new("RGBA", (cell * 2, cell * 2), c1)
        d = ImageDraw.Draw(tile)
        d.rectangle([cell, 0, cell * 2 - 1, cell - 1], fill=c2)
        d.rectangle([0, cell, cell - 1, cell * 2 - 1], fill=c2)
        im = Image.new("RGBA", (w, h))
        for y in range(0, h, cell * 2):
            for x in range(0, w, cell * 2):
                im.paste(tile, (x, y))
        if len(_checker_cache) > 12:
            _checker_cache.clear()
        _checker_cache[key] = im
    return im


def titlebar(win, dark: bool = True) -> None:
    """Dark or light Windows title bar for a window (no-op elsewhere)."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        win.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(win.winfo_id())
        val = ctypes.c_int(1 if dark else 0)
        for attr in (20, 19):
            if ctypes.windll.dwmapi.DwmSetWindowAttribute(
                    hwnd, attr, ctypes.byref(val), ctypes.sizeof(val)) == 0:
                break
    except Exception:
        pass
