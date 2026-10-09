#!/usr/bin/env python3
"""
Builds "XNB Board Tool.exe" from xnb_board_tool_v2.py with PyInstaller.

Put this file next to xnb_board_tool_v2.py and run:
    python build_exe.py
(or double-click build_exe.bat)

Result: dist\\XNB Board Tool.exe  - a single file you can copy anywhere.
"""
import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT = HERE / "xnb_board_tool_v2.py"
NAME = "XNB Board Tool"
ICON = HERE / "build_icon.ico"


def pip(*pkgs):
    subprocess.check_call([sys.executable, "-m", "pip", "install", "--upgrade", *pkgs])


def make_icon():
    """Draws the app's logo (amber tile with a skateboard) as a multi-size .ico."""
    from PIL import Image, ImageDraw
    S = 256
    im = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle([8, 8, S - 8, S - 8], radius=48, fill=(240, 168, 48, 255))
    dark = (20, 21, 24, 255)
    d.rounded_rectangle([44, 92, S - 44, 152], radius=30, outline=dark, width=16)
    for cx in (84, S - 84):
        d.ellipse([cx - 16, 168, cx + 16, 200], fill=dark)
    im.save(ICON, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])


def main():
    if not SCRIPT.exists():
        sys.exit(f"Cannot find {SCRIPT.name} next to this build script.")
    try:
        import tkinter  # noqa: F401
    except ImportError:
        sys.exit("This Python has no tkinter. Install Python from python.org "
                 "(tick 'tcl/tk and IDLE') and run again.")

    print("== Installing build tools ==")
    pip("pyinstaller", "pillow")
    dnd = True
    try:
        pip("tkinterdnd2")
    except subprocess.CalledProcessError:
        dnd = False
        print("tkinterdnd2 could not be installed - building without drag & drop.")

    print("== Making icon ==")
    make_icon()

    print("== Building exe ==")
    for d in ("build", "dist"):
        shutil.rmtree(HERE / d, ignore_errors=True)
    args = [
        sys.executable, "-m", "PyInstaller", str(SCRIPT),
        "--name", NAME,
        "--onefile", "--windowed", "--noconfirm", "--clean",
        "--icon", str(ICON),
        "--distpath", str(HERE / "dist"),
        "--workpath", str(HERE / "build"),
        "--specpath", str(HERE / "build"),
    ]
    if dnd and importlib.util.find_spec("tkinterdnd2"):
        args += ["--collect-all", "tkinterdnd2"]
    subprocess.check_call(args)

    exe = HERE / "dist" / (NAME + (".exe" if sys.platform == "win32" else ""))
    print()
    print(f"Done: {exe}" if exe.exists() else "Build finished, but the exe was not found - see the log above.")


if __name__ == "__main__":
    main()
