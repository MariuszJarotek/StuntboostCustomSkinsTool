"""Interface languages.

Texts are written in English in the code and looked up in a catalog per language
(locales/pl.py, de.py, fr.py): T = {"English text": "translation"}. Missing entries show
in English. Placeholders use str.format names: _("Added {name}.", name=n).
Plurals: _n("{n} board", "{n} boards", n) with the catalog entry holding a list of forms,
chosen by the language's plural rule (Polish has three).
"""
from __future__ import annotations

import os
import sys

LANGS = (("en", "English"), ("pl", "Polski"), ("de", "Deutsch"), ("fr", "Français"))
CODES = tuple(c for c, _n in LANGS)

_lang = "en"
_cat: dict = {}


def _plural_index(lang: str, n: int) -> int:
    """Which plural form to use for count n in a language: Polish has three (1 / 2-4 / 5+, with the teens in the
    third), French treats 0 like 1, everything else is one / many.
    """
    n = abs(int(n))
    if lang == "pl":
        if n == 1:
            return 0
        return 1 if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14) else 2
    if lang == "fr":
        return 0 if n in (0, 1) else 1
    return 0 if n == 1 else 1


def detect() -> str:
    """The language of the PC (Windows display language), if the tool has it; else English."""
    code = ""
    if sys.platform == "win32":
        try:
            import ctypes
            lid = ctypes.windll.kernel32.GetUserDefaultUILanguage() & 0x3FF   # primary language id
            code = {0x15: "pl", 0x07: "de", 0x0C: "fr", 0x09: "en"}.get(lid, "")
        except Exception:
            code = ""
    if not code:
        for var in ("LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG"):
            v = os.environ.get(var, "")
            if v and v not in ("C", "POSIX"):
                code = v.split(":")[0][:2].lower()
                break
    return code if code in CODES else "en"


def load_catalog(code: str) -> dict:
    # imported by name (not with importlib) so the Windows build bundles them
    """The translation dictionary T of a language ('pl', 'de', 'fr'); {} for English or an unknown code. The
    modules are imported by name so PyInstaller bundles them.
    """
    if code == "pl":
        from .locales import pl as m
    elif code == "de":
        from .locales import de as m
    elif code == "fr":
        from .locales import fr as m
    else:
        return {}
    return m.T


def set_language(code: str) -> str:
    """'auto' or a language code. Returns the language now used."""
    global _lang, _cat
    if code not in CODES:
        code = detect()
    try:
        cat = load_catalog(code)
    except Exception:
        code, cat = "en", {}
    _lang, _cat = code, cat
    return code


def language() -> str:
    """The language code in use right now ('en', 'pl', 'de' or 'fr')."""
    return _lang


def _fmt(s: str, src: str, kw: dict) -> str:
    """Fills the {placeholders} of a translated text. A translation with a broken placeholder falls back to the
    English source, and if that fails too the text is shown unformatted - a bad translation never crashes the
    tool.
    """
    if not kw:
        return s
    try:
        return s.format(**kw)
    except Exception:                       # a broken translation never breaks the tool
        try:
            return src.format(**kw)
        except Exception:
            return src


def _(s: str, /, **kw) -> str:
    """The text in the current language (formatted with kw, if any)."""
    t = _cat.get(s)
    if not isinstance(t, str) or not t:
        t = s
    return _fmt(t, s, kw)


def _n(one: str, many: str, count: int, /, **kw) -> str:
    """Singular / plural text chosen by count ({n} is filled in with count unless given)."""
    kw.setdefault("n", count)
    src = one if count == 1 else many
    t = _cat.get(one)
    if isinstance(t, (list, tuple)) and t:
        i = min(_plural_index(_lang, count), len(t) - 1)
        return _fmt(t[i] or src, src, kw)
    return _fmt(src, src, kw)


def N_(s: str) -> str:
    """Marks a text for translation where it is defined; it is translated where it is shown."""
    return s


__all__ = ["LANGS", "CODES", "detect", "set_language", "language", "_", "_n", "N_"]
