"""The tests run on a copy of your own STUNTBOOST files, so the real game folder is never changed.

Tell the tests where the game is in one of two ways:
    --game "D:/SteamLibrary/steamapps/common/STUNTBOOST/Content/Models/Resources/Board"   (run_ui.py)
    set XNB_TEST_GAME=D:/SteamLibrary/steamapps/common/STUNTBOOST/Content/Models/Resources/Board

The path is the board folder. copy_game() copies the boards, the speedometer textures and the 3D board model
(whichever exist) into a temporary folder, keeping the Content/... layout so the tool finds them all. Stock
copies (_board_defaults) and .bak files are left out, so every test starts as if the tool was never used.
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Optional

ENV = "XNB_TEST_GAME"
SKIP = shutil.ignore_patterns("_board_defaults", "*.bak", "__pycache__")


def find_game(arg: Optional[str] = None) -> Optional[Path]:
    """The board folder from the argument or the XNB_TEST_GAME variable; None when neither is set."""
    p = arg or os.environ.get(ENV)
    if not p:
        return None
    p = Path(p)
    if not p.is_dir() or not any(p.glob("*.xnb")):
        raise SystemExit(f"{p} is not a board folder (no .xnb files in it)")
    return p


def _content_root(board_dir: Path) -> Optional[Path]:
    """The game's Content folder above the board folder, if there is one."""
    for d in [board_dir] + list(board_dir.parents):
        if d.name.lower() == "content":
            return d
    return None


def copy_game(board_dir: Path, dest: Path) -> Path:
    """Copy what the tool uses into `dest` and return the copied board folder."""
    board_dir, dest = Path(board_dir).resolve(), Path(dest)
    content = _content_root(board_dir)
    if content is None:                                   # a loose board folder: copy just that
        out = dest / board_dir.name
        shutil.copytree(board_dir, out, ignore=SKIP)
        return out
    new_content = dest / "Content"
    out = new_content / board_dir.relative_to(content)
    shutil.copytree(board_dir, out, ignore=SKIP)
    for extra in (Path("Textures") / "HUD" / "SpeedMeter", Path("Models") / "Export"):
        if (content / extra).is_dir():
            shutil.copytree(content / extra, new_content / extra, ignore=SKIP)
    return out
