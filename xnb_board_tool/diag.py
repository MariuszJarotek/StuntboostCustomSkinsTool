"""Start-up diagnostics.

A windowed .exe has no console, so an error or a hang while the window is being built would
leave only a process in Task Manager. This module:
  * writes startup.log (in %LOCALAPPDATA%\\XNB Board Tool) with each start-up stage and any error,
  * dumps what every thread is doing into the log if the window is not up after 30 s (a hang),
  * shows a message box when the start fails instead of leaving a silent process behind,
  * starts in safe mode (English, 3D on the processor) when the previous start never finished.
"""
from __future__ import annotations

import faulthandler
import os
import platform
import sys
import time
import traceback
from pathlib import Path

SAFE = False                # this start is in safe mode
HANG_SECONDS = 30
_t0 = time.time()
_log = None
_marker: Path | None = None
_ready = False


def log_dir() -> Path:
    """The folder for the start-up log: %LOCALAPPDATA%\\XNB Board Tool on Windows, ~/.cache/XNB Board Tool
    elsewhere.
    """
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / ".cache")
    return Path(base) / "XNB Board Tool"


def log_path() -> Path:
    """The start-up log file (startup.log in log_dir())."""
    return log_dir() / "startup.log"


def write(msg: str) -> None:
    """Adds a time-stamped line to the start-up log (seconds since start). Does nothing when logging is off and
    never raises.
    """
    if _log is None:
        return
    try:
        _log.write(f"{time.time() - _t0:7.2f}s  {msg}\n")
        _log.flush()
    except Exception:
        pass


def start(argv=()) -> None:
    """Call first thing at start-up."""
    global _log, _marker, SAFE
    try:
        d = log_dir()
        d.mkdir(parents=True, exist_ok=True)
        _marker = d / "starting.marker"
        SAFE = _marker.exists() or "--safe" in argv
        _marker.write_text(time.strftime("%Y-%m-%d %H:%M:%S") + " start-up began\n", "utf-8")
        _log = open(log_path(), "w", encoding="utf-8", buffering=1)
    except Exception:
        _log = None
        return
    from . import __version__
    write(f"XNB Board Texture Tool {__version__} | Python {sys.version.split()[0]} | "
          f"{platform.platform()} | frozen={getattr(sys, 'frozen', False)}"
          + (" | SAFE MODE (the last start did not finish)" if SAFE else ""))
    try:
        faulthandler.enable(_log, all_threads=True)        # crashes inside drivers / C code
        faulthandler.dump_traceback_later(HANG_SECONDS, repeat=False, file=_log)   # a hang
    except Exception as e:
        write(f"faulthandler not available: {e}")


def ready() -> None:
    """The window is up and responding: no hang dump, and the next start is a normal one."""
    global _ready
    if _ready:
        return
    _ready = True
    try:
        faulthandler.cancel_dump_traceback_later()
    except Exception:
        pass
    if _marker is not None:
        try:
            _marker.unlink()
        except OSError:
            pass
    write("window ready")


def error(where: str, exc_info=None) -> None:
    """Logs an exception (current one if exc_info is None)."""
    et, ev, tb = exc_info or sys.exc_info()
    write(f"ERROR in {where}:\n" + "".join(traceback.format_exception(et, ev, tb)))


def fatal(where: str) -> None:
    """The start failed: log it, tell the user, and end the process (no silent leftover)."""
    error(where)
    msg = (f"XNB Board Texture Tool could not start.\n\n{sys.exc_info()[1]!r}\n\n"
           f"Details are in:\n{log_path()}")
    try:
        import tkinter as tk
        from tkinter import messagebox
        r = tk.Tk()
        r.withdraw()
        messagebox.showerror("XNB Board Texture Tool", msg, parent=r)
        r.destroy()
    except Exception:
        pass
    os._exit(1)


__all__ = ["SAFE", "start", "ready", "write", "error", "fatal", "log_path"]
