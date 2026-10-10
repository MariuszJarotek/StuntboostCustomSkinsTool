"""Shared helpers: errors, size limits, safe file writing."""
from __future__ import annotations

import os
from pathlib import Path


# --------------------------------------------------------------------------
#  XNB parsing / writing (no GUI dependencies)
# --------------------------------------------------------------------------
class XnbError(Exception):
    pass


# ---- Safety limits & safe writing ----
# A damaged or hostile .xnb could claim absurd sizes; reject them instead of trying to
# allocate gigabytes of memory (which could freeze the PC).
MAX_DIM = 16384                 # largest width/height accepted


MAX_PIXELS = 64 * 1024 * 1024   # 64 Mpx = 256 MB as RGBA


def check_size(w: int, h: int) -> None:
    if w <= 0 or h <= 0 or w > MAX_DIM or h > MAX_DIM or w * h > MAX_PIXELS:
        raise XnbError(f"image size {w}x{h} is outside the supported range")


def atomic_write(path: Path, data: bytes) -> None:
    """Write via a temp file + rename, so a crash or power loss mid-write never
    leaves a half-written (corrupted) file behind."""
    path = Path(path)
    tmp = path.with_name(path.name + ".tmp-xnbtool")
    try:
        with open(tmp, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass


def human_size(n: int) -> str:
    return f"{n / 1048576:.2f} MB" if n >= 1048576 else f"{n / 1024:.0f} KB"


# --------------------------------------------------------------------------
#  Board status (matches default / modified / no default), with a hash cache
# --------------------------------------------------------------------------
def _norm(path) -> str:
    return os.path.normcase(os.path.abspath(str(path)))
