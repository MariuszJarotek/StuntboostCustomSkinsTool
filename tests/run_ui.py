#!/usr/bin/env python3
"""Runs the real app window through a scripted scenario: clicks, checks (assert) and screenshots.

    python tests/run_ui.py tests/scenarios/02_deck_fan.txt      one scenario, on fake boards
    python tests/run_ui.py --all                                 every scenario, on fake boards
    python tests/run_ui.py --all --game "D:/.../STUNTBOOST/Content/Models/Resources/Board"

Options:
    --game DIR      test on your own boards instead of fake ones (or set XNB_TEST_GAME). The folder is only read:
                    every scenario runs on a fresh copy in a temporary folder (see gamecopy.py).
                    Without it, fixture.py generates 40 fake boards and the speedometer for every scenario.
    --shots DIR     where SHOT lines save their screenshots (default tests/shots)
    --delay MS      pause after each step so loading and redraws can finish (default 1500)

A scenario is a text file of Python steps separated by lines holding only `---`. Each step runs on the Tk
thread, then the runner waits `--delay` ms before the next one. All steps share one namespace with:

    app      the running App (gui/app.py) - call its methods as a click would
    base     xnb_board_tool.gui.base (base.root is the Tk window)
    BOARDS   the board folder that was opened (pathlib.Path)
    shot(n)  save a screenshot of the window as <shots>/<n>

A line `SHOT name.png` (anywhere in a step) is a shortcut for shot("name.png"). A failing assert or any exception -
also one raised later inside a Tk callback - counts as an error; the exit code is 1 when there were errors.

Settings are kept in a temporary folder, so running tests never changes your own settings.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
import time
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent


def parse_steps(text: str) -> list:
    """Split a scenario into its steps (separated by lines that hold only ---)."""
    steps, cur = [], []
    for line in text.splitlines():
        if line.lstrip().startswith("SHOT "):          # SHOT name.png  ->  shot("name.png")
            indent = line[:len(line) - len(line.lstrip())]
            line = f"{indent}shot({line.strip()[5:].strip()!r})"
        if line.strip() == "---":
            steps.append("\n".join(cur))
            cur = []
        else:
            cur.append(line)
    steps.append("\n".join(cur))
    return [s for s in steps if s.strip()]


def run_one(scenario: Path, content: Path, shots: Path, delay: int) -> int:
    """Open the app on `content`, run every step of `scenario`, return the number of errors."""
    sys.path.insert(0, str(ROOT))
    from xnb_board_tool.gui import base
    base.init()
    from xnb_board_tool.gui.app import App
    from PIL import ImageGrab

    app = App(start_folder=str(content))
    base.root.geometry("1440x900+0+0")
    shots.mkdir(parents=True, exist_ok=True)
    errors: list = []

    def report(*exc):
        """Errors inside Tk callbacks would otherwise only be printed."""
        errors.append("callback: " + "".join(traceback.format_exception_only(exc[0], exc[1])).strip())
        traceback.print_exception(*exc)
    base.root.report_callback_exception = report

    def shot(name: str):
        """Screenshot of the app window."""
        r = base.root
        r.update()
        time.sleep(0.3)
        r.update()
        x, y = r.winfo_rootx(), r.winfo_rooty()
        kw = {"xdisplay": os.environ["DISPLAY"]} if sys.platform.startswith("linux") else {}
        ImageGrab.grab(bbox=(x, y, x + r.winfo_width(), y + r.winfo_height()), **kw).save(shots / name)
        print("   shot", shots / name)

    ns = {"app": app, "base": base, "BOARDS": Path(content), "shot": shot}
    steps = parse_steps(scenario.read_text("utf-8"))

    def run(k=0):
        """Run step k, then schedule the next one."""
        if k >= len(steps):
            base.root.destroy()
            return
        code = steps[k].strip()
        first = code.splitlines()[0][:70]
        print(f" [{k + 1}/{len(steps)}] {first}")
        try:
            exec(compile(code, f"{scenario.name} step {k + 1}", "exec"), ns)
        except Exception:
            traceback.print_exc()
            errors.append(f"step {k + 1}: {first}")
        base.root.after(delay, run, k + 1)

    base.root.after(2500, run)         # let the folder load first
    base.root.mainloop()
    return len(errors)


def main() -> int:
    """Command line entry point. With --all every scenario runs in its own process (a fresh window)."""
    ap = argparse.ArgumentParser(description="Run UI scenarios against the app.")
    ap.add_argument("scenario", nargs="?", type=Path)
    ap.add_argument("--all", action="store_true", help="run every tests/scenarios/*.txt")
    ap.add_argument("--game", help="test on a copy of your board folder (default: fake boards, or XNB_TEST_GAME)")
    ap.add_argument("--copied", type=Path, help=argparse.SUPPRESS)   # internal: --all passes the folder it made
    ap.add_argument("--shots", type=Path, default=HERE / "shots")
    ap.add_argument("--delay", type=int, default=1500)
    a = ap.parse_args()
    if not a.all and a.scenario is None:
        ap.error("give a scenario file or --all")

    tmp = tempfile.TemporaryDirectory(prefix="xnb_ui_")
    os.environ["APPDATA"] = str(Path(tmp.name) / "settings")      # keep the user's settings untouched
    sys.path.insert(0, str(HERE))
    import fixture
    import gamecopy

    game = None if a.copied else gamecopy.find_game(a.game)

    def prepare(dest: Path) -> Path:
        """A fresh board folder for one scenario: a copy of the user's game, or fake boards."""
        return gamecopy.copy_game(game, dest) if game else fixture.make_game(dest, 40)

    if a.all:
        failed = []
        scenarios = sorted((HERE / "scenarios").glob("*.txt"))
        for sc in scenarios:
            print(f"== {sc.name}")
            # every scenario gets its own fresh folder, so saves in one never affect another
            copy = prepare(Path(tmp.name) / sc.stem)
            r = subprocess.run([sys.executable, __file__, str(sc), "--copied", str(copy),
                                "--shots", str(a.shots), "--delay", str(a.delay)], env=os.environ)
            if r.returncode:
                failed.append(sc.name)
        print(f"\n{len(failed)} of {len(scenarios)} scenarios failed", *failed, sep="\n  " if failed else "")
        return 1 if failed else 0

    content = a.copied or prepare(Path(tmp.name) / "game")
    n = run_one(a.scenario, content, a.shots, a.delay)
    print(f"{a.scenario.name}: {'OK' if not n else f'{n} error(s)'}")
    return 1 if n else 0


if __name__ == "__main__":
    sys.exit(main())
