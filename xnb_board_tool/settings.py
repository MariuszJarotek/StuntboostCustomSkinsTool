"""Themes, layouts and the user settings file."""
from __future__ import annotations

from .i18n import N_, _

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
    # Skate shop: warm concrete, ink black and one orange accent (made for the Skate shop layout)
    "concrete": {
        "bg": "#ebe8e1", "panel": "#f6f4ef", "side": "#e3dfd6", "border": "#cdc7bb",
        "btn": "#f6f4ef", "btnh": "#e2ddd2", "btnb": "#17161a", "sel": "#dcd6c9",
        "text": "#17161a", "muted": "#5d5a55", "sub": "#3f3c38", "dis": "#a19c92",
        "accent": "#ff6a2b", "accenth": "#ff8a55", "green": "#1f8a4c", "onaccent": "#17161a",
        "selfill": "#ffc2a3", "warn": "#b33a00", "warnbg": "#ffe2d1", "okfg": "#1f7a45",
        "okbg": "#dcefe2", "chk1": "#e6e2da", "chk2": "#d8d3c9", "dark": False,
        "ink": "#17161a", "onink": "#ebe8e1",
    },
    # Blueprint: navy drafting paper, light lines, amber accent (dark; the ink bars turn light)
    "blueprint": {
        "bg": "#0f2740", "panel": "#16324f", "side": "#122d49", "border": "#2a4c72",
        "btn": "#16324f", "btnh": "#1e3f62", "btnb": "#7d9cc2", "sel": "#1f4268",
        "text": "#e3eefc", "muted": "#9fb3cc", "sub": "#c4d3e6", "dis": "#5f7896",
        "accent": "#ffb703", "accenth": "#ffc94a", "green": "#4cc38a", "onaccent": "#0f2740",
        "selfill": "#6b4e00", "warn": "#ffc94a", "warnbg": "#3d3210", "okfg": "#7fe0ad",
        "okbg": "#143d33", "chk1": "#13304d", "chk2": "#1a3a5c", "dark": True,
        "ink": "#e3eefc", "onink": "#0f2740", "grid": "#163453",
    },
}

THEME_NAMES = {"dark": N_("Dark"), "light": N_("Light"), "concrete": N_("Concrete"), "blueprint": N_("Blueprint")}


LAYOUTS = {
    "studio": (N_("Studio"), N_("Big 3D preview in the middle. Board list on the left, colors, thumbnail "
                         "and defaults in an inspector on the right.")),
    "gallery": (N_("Gallery"), N_("Every board as a card with its 4 colors. The selected board opens in an "
                           "editor drawer on the right.")),
    "classic": (N_("Classic"), N_("The original layout: texture and 3D side by side, colors below, "
                           "thumbnail and defaults at the bottom.")),
    "shop": (N_("Skate shop"), N_("Every deck hangs on a wall. Pick one to put it on the bench: top and "
                                  "bottom side by side, one tool at a time.")),
}

# Text sizes (points). Six roles, one size each, everywhere in the app:
#   page = page titles (THE WALL, Board 7)   section = section headings and the wordmark
#   tag = tabs, tags and condensed labels      body = text, buttons, fields
#   cap = hints and small print                mono = codes (#rrggbb, file names)
TEXT_SIZES = {
    "compact": {"page": 20, "section": 14, "tag": 10, "body": 10, "cap": 10, "mono": 10},
    "balanced": {"page": 22, "section": 16, "tag": 11, "body": 11, "cap": 10, "mono": 10},
    "large": {"page": 26, "section": 18, "tag": 12, "body": 12, "cap": 11, "mono": 11},
}
TEXT_SIZE_NAMES = {"compact": N_("Compact"), "balanced": N_("Balanced"), "large": N_("Large")}

GAL_LAYOUTS = ("gallery", "shop")       # layouts that show every board as a picture


C: dict = {}


BADGES: dict = {}


SETTINGS = {"layout": "shop", "theme": "concrete", "gallery_cols": "auto", "gpu3d": True, "language": "auto",
            "text_size": "balanced"}


GALLERY_COLS = ("auto", "2", "3", "4", "5", "6")


def set_theme(name: str) -> None:
    """Switches the colour table C (and the status badge colours) to a theme. Widgets read C when they are built,
    so the window is rebuilt afterwards.
    """
    C.clear()
    C.update(THEMES.get(name, THEMES["dark"]))
    BADGES.clear()
    BADGES.update({
        "def": (_("Matches default"), C["okfg"], C["okbg"]),
        "mod": (_("Modified — differs from default"), C["warn"], C["warnbg"]),
        "none": (_("No default saved"), C["sub"], C["btn"]),
        None: (_("Checking…"), C["muted"], C["btn"]),
    })
    _checker_cache.clear()


def settings_path() -> Path:
    """Where settings.json lives: %APPDATA%\\XNB Board Tool on Windows, ~/.config/XNB Board Tool elsewhere."""
    base = os.environ.get("APPDATA") or str(Path.home() / ".config")
    return Path(base) / "XNB Board Tool" / "settings.json"


def load_settings() -> dict:
    """Reads settings.json, keeping only known and valid values; anything missing or broken falls back to the
    defaults (Skate shop layout, Concrete theme, automatic language).
    """
    out = {"layout": "shop", "theme": "concrete", "gallery_cols": "auto", "gpu3d": True, "language": "auto",
           "text_size": "balanced"}
    try:
        data = json.loads(settings_path().read_text("utf-8"))
        if data.get("layout") in LAYOUTS:
            out["layout"] = data["layout"]
        if data.get("theme") in THEMES:
            out["theme"] = data["theme"]
        if str(data.get("gallery_cols")) in GALLERY_COLS:
            out["gallery_cols"] = str(data["gallery_cols"])
        if data.get("text_size") in TEXT_SIZES:
            out["text_size"] = data["text_size"]
        if isinstance(data.get("gpu3d"), bool):
            out["gpu3d"] = data["gpu3d"]
        from .i18n import CODES
        if data.get("language") in ("auto",) + CODES:
            out["language"] = data["language"]
        if isinstance(data.get("drawer_w"), int) and 300 <= data["drawer_w"] <= 2000:
            out["drawer_w"] = data["drawer_w"]
    except Exception:
        pass
    return out


def save_settings(values: dict) -> None:
    """Writes the user's settings to settings.json (atomically). Errors are ignored: not being able to save
    settings must never stop the tool.
    """
    try:
        sp = settings_path()
        sp.parent.mkdir(parents=True, exist_ok=True)
        atomic_write(sp, json.dumps({k: values[k] for k in ("layout", "theme", "gallery_cols", "drawer_w", "gpu3d", "language", "text_size") if k in values}, indent=2).encode("utf-8"))
    except Exception:
        pass


def _rgb(hex_color: str, a: int = 255):
    """'#rrggbb' as an (r, g, b, a) tuple with the given alpha."""
    h = hex_color.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4)) + (a,)


_checker_cache: dict = {}


def checker(w: int, h: int, cell: int = 8) -> Image.Image:
    """A transparency checkerboard of w x h in the theme's checker colours (cached per size)."""
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
