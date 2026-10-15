#!/usr/bin/env python3
"""
Builds the Windows version of XNB Board Tool from xnb_board_tool_v2.py with PyInstaller.

Put this file next to xnb_board_tool_v2.py and run:
    python build_exe.py              -> dist\\XNB-Board-Tool-v<version>-windows.zip   (recommended)
    python build_exe.py --onefile    -> dist\\XNB Board Tool.exe                      (single file)
(or double-click build_exe.bat)

Options:
    --stock-launcher     use PyInstaller's ready-made launcher instead of compiling one here
    --rebuild-launcher   compile the launcher again even if it was compiled before

Why the folder (zip) build is the default:
  Antivirus programs flag PyInstaller "--onefile" apps far more often, because a
  single exe that unpacks hidden code to a temp folder at start-up looks like a
  malware "dropper". The folder build runs in place - nothing is unpacked - and
  gets far fewer false positives. Users unzip it and run "XNB Board Tool.exe".

Own launcher (on by default):
  Every PyInstaller app starts through the same small launcher exe ("bootloader"), and
  malware packed with PyInstaller uses it too, so antivirus programs often flag that launcher
  itself ("Malware-gen", "W64.Malware"...). This script compiles a launcher on your PC from
  PyInstaller's source, which gives the exe its own fingerprint. It needs a C compiler once:
  the free "Build Tools for Visual Studio" with "Desktop development with C++"
  (https://visualstudio.microsoft.com/visual-cpp-build-tools/). Without one, the build
  still works with the ready-made launcher and says so. The compile takes a few minutes and
  is done again only when PyInstaller changes.

Other things this script does to look less suspicious to antivirus heuristics:
  * --noupx: never compress the exe with UPX (packed exes are a classic red flag)
  * embeds Windows version info (product name, version, description), which
    unidentified, metadata-less exes lack
"""
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT = HERE / "xnb_board_tool_v2.py"
NAME = "XNB Board Tool"
# the version has one home: __version__ in xnb_board_tool/__init__.py (read as text, so nothing is imported)
VERSION = re.search(r'__version__ = "([^"]+)"', (HERE / "xnb_board_tool" / "__init__.py").read_text("utf-8")).group(1)
AUTHOR = "XNB Board Tool"          # shown as "Company" in the exe's Properties -> Details
DESCRIPTION = "XNB Board Texture Tool - STUNTBOOST board texture editor"
ICON_NAME = "_xnb_tool_icon.ico"
LAUNCHER_MARK = HERE / "_xnb_own_launcher.json"     # remembers that the launcher was compiled here
LAUNCHER_LOG = HERE / "_xnb_launcher_build.log"


def pip(*pkgs):
    """Installs or upgrades the given packages into the Python that runs this script."""
    subprocess.check_call([sys.executable, "-m", "pip", "install", "--upgrade", *pkgs])


def _py(code: str) -> str:
    """Runs Python code in a fresh interpreter (sees a just re-installed PyInstaller)."""
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else ""


def installed_pyinstaller():
    """(version, path of the windowed launcher runw.exe) of the installed PyInstaller."""
    out = _py("import PyInstaller, os, glob\n"
              "d = os.path.dirname(PyInstaller.__file__)\n"
              "f = sorted(glob.glob(os.path.join(d, 'bootloader', 'Windows-*', 'runw.exe')))\n"
              "print(PyInstaller.__version__)\nprint(f[0] if f else '')").splitlines()
    if len(out) < 2:
        return None, None
    return out[0], (out[1] or None)


def _sha(path) -> str:
    """SHA-256 of a file, as hex (used to tell whether the stock launcher changed)."""
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def find_compiler():
    """A C compiler PyInstaller's launcher can be built with ('msvc' / 'gcc', description), or None."""
    pf = os.environ.get("ProgramFiles(x86)") or os.environ.get("ProgramFiles") or r"C:\Program Files (x86)"
    vswhere = Path(pf) / "Microsoft Visual Studio" / "Installer" / "vswhere.exe"
    if vswhere.exists():
        r = subprocess.run([str(vswhere), "-latest", "-products", "*", "-requires",
                            "Microsoft.VisualStudio.Component.VC.Tools.x86.x64",
                            "-property", "installationPath"], capture_output=True, text=True)
        if r.returncode == 0 and r.stdout.strip():
            return "msvc", "Visual C++ in " + r.stdout.strip().splitlines()[0]
    if shutil.which("cl"):
        return "msvc", "Visual C++ (cl.exe)"
    if shutil.which("gcc"):
        return "gcc", "MinGW gcc"
    return None


def own_launcher(force=False):
    """Makes sure PyInstaller uses a launcher compiled on this PC. Returns (ok, text)."""
    ver, runw = installed_pyinstaller()
    try:
        mark = json.loads(LAUNCHER_MARK.read_text("utf-8"))
    except Exception:
        mark = {}
    if not force and ver and runw and mark.get("pyinstaller") == ver and mark.get("runw_sha256") == _sha(runw):
        return True, f"own launcher, compiled on this PC on {mark.get('built', '?')} (PyInstaller {ver})"
    comp = find_compiler()
    if comp is None:
        return False, ("no C compiler found. Install the free 'Build Tools for Visual Studio' with "
                       "'Desktop development with C++' (https://visualstudio.microsoft.com/visual-cpp-build-tools/) "
                       "and build again")
    kind, desc = comp
    print(f"== Compiling PyInstaller's launcher on this PC with {desc} ==")
    print("   (one time, takes a few minutes; details in " + LAUNCHER_LOG.name + ")")
    env = dict(os.environ, PYINSTALLER_COMPILE_BOOTLOADER="1")
    if kind == "gcc":
        env["PYINSTALLER_BOOTLOADER_WAF_ARGS"] = "--gcc"
    subprocess.call([sys.executable, "-m", "pip", "uninstall", "-y", "pyinstaller"])
    subprocess.call([sys.executable, "-m", "pip", "cache", "remove", "pyinstaller"],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)    # fails harmlessly if no cache
    t0 = time.time()
    with open(LAUNCHER_LOG, "w", encoding="utf-8", errors="replace") as log:
        r = subprocess.call([sys.executable, "-m", "pip", "install", "--verbose", "--no-binary=PyInstaller",
                             "pyinstaller"], env=env, stdout=log, stderr=subprocess.STDOUT)
    text = LAUNCHER_LOG.read_text("utf-8", errors="replace")
    ver, runw = installed_pyinstaller()
    built = (r == 0 and runw is not None and
             ("finished successfully" in text or os.path.getmtime(runw) >= t0 - 5))
    if not built:
        print("\n".join(text.splitlines()[-25:]))
        print("Compiling the launcher failed - installing the ready-made PyInstaller instead.")
        pip("pyinstaller")
        return False, f"compiling failed (see {LAUNCHER_LOG.name})"
    LAUNCHER_MARK.write_text(json.dumps({"pyinstaller": ver, "runw_sha256": _sha(runw), "compiler": desc,
                                         "built": time.strftime("%Y-%m-%d %H:%M")}, indent=1), "utf-8")
    return True, f"own launcher, just compiled with {desc} (PyInstaller {ver})"


def make_icon(path: Path):
    """The app's logo as a multi-size .ico (the same drawing the window uses)."""
    sys.path.insert(0, str(HERE))
    from xnb_board_tool.icon import save_ico
    save_ico(path)


def write_version_file(path: Path):
    """Windows version resource (Properties -> Details) in PyInstaller's format."""
    nums = [int(x) for x in VERSION.split(".")] + [0] * 4
    v = tuple(nums[:4])

    def q(s):
        """Escapes a text for the single-quoted Python literals in the version resource file."""
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
    """Zips `folder` into `zip_path` (replacing an older zip), keeping the folder's own name as the top folder
    inside the zip, so it unpacks into one folder.
    """
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for p in sorted(folder.rglob("*")):
            if p.is_file():
                z.write(p, Path(folder.name) / p.relative_to(folder))


def main():
    """Builds the Windows program with PyInstaller: checks the sources, installs the build tools, writes the
    version resource, runs PyInstaller (one folder, or one file with --onefile; --stock-launcher skips the
    custom launcher) and zips the result into dist/ ready for a GitHub release.
    """
    argv = sys.argv[1:]
    onefile = "--onefile" in argv
    stock = "--stock-launcher" in argv
    if not SCRIPT.exists():
        sys.exit(f"Cannot find {SCRIPT.name} next to this build script.")
    if not (HERE / "xnb_board_tool" / "__init__.py").exists():
        sys.exit("Cannot find the xnb_board_tool folder next to this build script.")
    try:
        import tkinter  # noqa: F401
    except ImportError:
        sys.exit("This Python has no tkinter. Install Python from python.org "
                 "(tick 'tcl/tk and IDLE') and run again.")

    print("== Installing build tools ==")
    pip("pillow", "numpy")
    if stock:
        pip("pyinstaller")
        launcher = "ready-made PyInstaller launcher (--stock-launcher)"
    else:
        ok, launcher = own_launcher(force="--rebuild-launcher" in argv)
        if not ok:
            launcher = "ready-made PyInstaller launcher - " + launcher
            if installed_pyinstaller()[0] is None:
                pip("pyinstaller")
    dnd = True
    try:
        pip("tkinterdnd2")
    except subprocess.CalledProcessError:
        dnd = False
        print("tkinterdnd2 could not be installed - building without drag & drop.")
    try:
        pip("qoi")
    except subprocess.CalledProcessError:
        print("qoi could not be installed - building with the built-in (slower) decoder.")

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
        "--paths", str(HERE),
        "--collect-submodules", "xnb_board_tool",
        "--collect-data", "xnb_board_tool",          # built-in Starter sticker pack
    ]
    if dnd and importlib.util.find_spec("tkinterdnd2"):
        args += ["--collect-all", "tkinterdnd2"]
    if importlib.util.find_spec("qoi"):
        args += ["--collect-all", "qoi"]
    subprocess.check_call(args)
    shutil.rmtree(work, ignore_errors=True)

    print()
    print(f"Launcher: {launcher}")
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
