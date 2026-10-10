"""The Tk user interface. Start it with run_gui()."""
from __future__ import annotations

from typing import Optional

APP = None          # the running App (handy for debugging and tests)


def run_gui(start_folder: Optional[str] = None) -> None:
    global APP
    from . import base
    root = base.init()
    # imported only now: the GUI modules take root / F from base when they are imported
    from .app import App
    APP = App(start_folder)
    root.mainloop()
