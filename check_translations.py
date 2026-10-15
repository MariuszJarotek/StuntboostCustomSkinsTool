#!/usr/bin/env python3
"""Checks the interface translations against the texts in the code.

    python check_translations.py

For every language in xnb_board_tool/locales it lists texts that are missing (shown in English),
entries the code no longer uses, wrong placeholders ({name}) and wrong plural forms.
Texts are found where the code calls _("..."), _n("one", "many", n) or N_("...").
"""
from __future__ import annotations

import ast
import importlib
import string
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PKG = ROOT / "xnb_board_tool"
KEEP_ENGLISH = {"XNB Board Texture Tool", "Board Texture Tool", "BOARD", "TOOL", "3D",
                "Impact", "Arial Black", "Bahnschrift", "Segoe Black", "Franklin Heavy", "Verdana Bold",
                "Consolas Bold"}   # font names
FORMS = {"pl": 3}                      # number of plural forms (default 2)


def texts() -> dict:
    """{English text: plural English text or None}"""
    out = {}
    for f in sorted(PKG.rglob("*.py")):
        if "locales" in f.parts:
            continue
        for n in ast.walk(ast.parse(f.read_text("utf-8"))):
            if (isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in ("_", "_n", "N_")
                    and n.args and isinstance(n.args[0], ast.Constant) and isinstance(n.args[0].value, str)):
                plural = n.args[1].value if n.func.id == "_n" and len(n.args) > 1 else None
                out.setdefault(n.args[0].value, plural)
    return out


def fields(s: str) -> set:
    """The {placeholders} in a text, as a set of (name, format spec), so a translation can be checked to use
    exactly the same ones as the English source.
    """
    return {(name, spec or "") for _l, name, spec, _c in string.Formatter().parse(s) if name is not None}


def main() -> int:
    """Compares every catalogue in xnb_board_tool/locales with the texts in the code and prints, per language, the
    missing, unused and wrong entries (wrong = different placeholders, or a plural entry with the wrong number
    of forms). Returns the exit code: 1 when something is missing or wrong, else 0.
    """
    sys.path.insert(0, str(ROOT))
    src = texts()
    bad = 0
    for f in sorted((PKG / "locales").glob("*.py")):
        if f.stem.startswith("_"):
            continue
        cat = importlib.import_module(f"xnb_board_tool.locales.{f.stem}").T
        missing = [k for k in src if k not in cat and k not in KEEP_ENGLISH]
        unused = [k for k in cat if k not in src]
        wrong = []
        for k, v in cat.items():
            if k not in src:
                continue
            plural = src[k]
            forms = v if isinstance(v, list) else [v]
            if plural is not None and len(forms) != FORMS.get(f.stem, 2):
                wrong.append(f"{k!r}: {len(forms)} plural forms")
            want = fields(plural if plural is not None else k)
            for t in forms:
                if fields(t) != want:
                    wrong.append(f"{k!r}: placeholders {sorted(fields(t))} should be {sorted(want)}")
        print(f"{f.stem}: {len(cat)} texts, {len(missing)} missing, {len(unused)} unused, {len(wrong)} wrong")
        for k in missing:
            print("   missing:", repr(k))
        for k in unused:
            print("   unused: ", repr(k))
        for w in wrong:
            print("   wrong:  ", w)
        bad += len(missing) + len(wrong)
    print(f"{len(src)} texts in the code")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
