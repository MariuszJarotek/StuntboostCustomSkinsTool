"""The Tk user interface. Start it with run_gui()."""
from __future__ import annotations

import sys
from typing import Optional

APP = None          # the running App (handy for debugging and tests)


def run_gui(start_folder: Optional[str] = None) -> None:
    """Starts the program: writes the start-up log, creates the window and the App (opening `start_folder` if
    given), logs any error of a window event, notes when the window is on screen, and runs the Tk main loop. A
    failure during start-up is written to the log and shown instead of a silent crash.
    """
    global APP
    from .. import diag
    diag.start(sys.argv[1:])
    try:
        from . import base
        root = base.init()
        diag.write("window and fonts created")
        # imported only now: the GUI modules take root / F from base when they are imported
        from .app import App
        APP = App(start_folder)
        diag.write("main window built")
    except BaseException:
        diag.fatal("start-up")
        return
    default_report = root.report_callback_exception

    def report(*exc):
        """Writes an error raised in a window event to the log, then lets Tk report it as usual."""
        diag.error("a window event", exc)
        default_report(*exc)
    root.report_callback_exception = report

    def check_ready(tries=[0]):
        """Tells the log the window is up once it is on screen (checked every 250 ms, at most 20 times)."""
        tries[0] += 1
        if root.winfo_ismapped() or tries[0] > 20:
            diag.ready()
        else:
            root.after(250, check_ready)
    root.after(500, check_ready)
    if diag.SAFE:
        root.after(1500, lambda: APP.set_status(
            "Safe start: the last start did not finish, so this one uses English and draws the 3D "
            f"board on the processor. Details: {diag.log_path()}"))
    root.mainloop()
