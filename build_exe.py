#!/usr/bin/env python3
"""
Builds the Windows version of XNB Board Tool from xnb_board_tool_v2.py with PyInstaller.

Put this file next to xnb_board_tool_v2.py and run:
    python build_exe.py              -> dist\\XNB-Board-Tool-v<version>-windows.zip   (recommended)
    python build_exe.py --onefile    -> dist\\XNB Board Tool.exe                      (single file)
(or double-click build_exe.bat)

Why the folder (zip) build is the default:
  Antivirus programs flag PyInstaller "--onefile" apps far more often, because a
  single exe that unpacks hidden code to a temp folder at start-up looks like a
  malware "dropper". The folder build runs in place - nothing is unpacked - and
  gets far fewer false positives. Users unzip it and run "XNB Board Tool.exe".

Other things this script does to look less suspicious to antivirus heuristics:
  * --noupx: never compress the exe with UPX (packed exes are a classic red flag)
  * embeds Windows version info (product name, version, description), which
    unidentified, metadata-less exes lack
"""
import importlib.util
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT = HERE / "xnb_board_tool_v2.py"
NAME = "XNB Board Tool"
VERSION = "1.0.0"
AUTHOR = "XNB Board Tool"          # shown as "Company" in the exe's Properties -> Details
DESCRIPTION = "XNB Board Texture Tool - STUNTBOOST board texture editor"
ICON_NAME = "_xnb_tool_icon.ico"


def pip(*pkgs):
    subprocess.check_call([sys.executable, "-m", "pip", "install", "--upgrade", *pkgs])


def make_icon(path: Path):
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
    im.save(path, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])


def write_version_file(path: Path):
    """Windows version resource (Properties -> Details) in PyInstaller's format."""
    nums = [int(x) for x in VERSION.split(".")] + [0] * 4
    v = tuple(nums[:4])

    def q(s):
        return s.replace("\\", "\\\\").replace("'", "\\'")
    path.write_text(f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers={v}, prodvers={v}, mask=0x3f, flags=0x0, OS=0x40004,
                    fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('040904B0', [
      StringStruct('CompanyName', '{q(AUTHOR)}'),
      StringStruct('FileDescription', '{q(DESCRIPTION)}'),
      StringStruct('FileVersion', '{VERSION}'),
      StringStruct('InternalName', '{q(NAME)}'),
      StringStruct('LegalCopyright', '{q(AUTHOR)}'),
      StringStruct('OriginalFilename', '{q(NAME)}.exe'),
      StringStruct('ProductName', '{q(NAME)}'),
      StringStruct('ProductVersion', '{VERSION}')])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
""", "utf-8")


def zip_folder(folder: Path, zip_path: Path):
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for p in sorted(folder.rglob("*")):
            if p.is_file():
                z.write(p, Path(folder.name) / p.relative_to(folder))


def main():
    onefile = "--onefile" in sys.argv[1:]
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

    # Only ever delete our own, uniquely named temp folder - never a generic
    # "build"/"dist" folder that might belong to something else.
    work = HERE / "_xnb_tool_build_tmp"
    if work.is_dir() and (work / ".xnb_tool_build").exists():
        shutil.rmtree(work)
    work.mkdir(exist_ok=True)
    (work / ".xnb_tool_build").write_text("temporary build folder, safe to delete\n")
    icon, verfile = work / ICON_NAME, work / "version_info.txt"
    make_icon(icon)
    write_version_file(verfile)

    print(f"== Building ({'single exe' if onefile else 'folder + zip'}) ==")
    dist = HERE / "dist"
    args = [
        sys.executable, "-m", "PyInstaller", str(SCRIPT),
        "--name", NAME,
        "--onefile" if onefile else "--onedir",
        "--windowed", "--noconfirm", "--clean", "--noupx",
        "--icon", str(icon),
        "--version-file", str(verfile),
        "--distpath", str(dist),
        "--workpath", str(work),
        "--specpath", str(work),
    ]
    if dnd and importlib.util.find_spec("tkinterdnd2"):
        args += ["--collect-all", "tkinterdnd2"]
    subprocess.check_call(args)
    shutil.rmtree(work, ignore_errors=True)

    print()
    if onefile:
        exe = dist / f"{NAME}.exe"
        print(f"Done: {exe}" if exe.exists() else "Build finished, but the exe was not found - see the log above.")
        return
    folder = dist / NAME
    if not (folder / f"{NAME}.exe").exists():
        print("Build finished, but the app folder was not found - see the log above.")
        return
    zip_path = dist / f"{NAME.replace(' ', '-')}-v{VERSION}-windows.zip"
    zip_folder(folder, zip_path)
    print(f"Done:\n  app folder: {folder}\n  release zip: {zip_path}")
    print("Upload the zip to the GitHub release; users unzip it and run "
          f"'{NAME}.exe' inside the folder.")


if __name__ == "__main__":
    main()
