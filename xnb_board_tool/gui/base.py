"""Shared Tk state (root window, fonts) and small widgets used by every GUI module."""
from __future__ import annotations

from typing import Optional

from tkinter import ttk
import tkinter as tk
import tkinter.font as tkfont
from PIL import Image, ImageTk

from ..settings import C, SETTINGS, checker, load_settings, set_theme


root = None             # the Tk root window, created by init()
F: dict = {}            # fonts
TkinterDnD = None       # drag & drop support (tkinterdnd2), if installed
DND_FILES = None
_scrolls: list = []     # every Scroll area (one mouse-wheel handler serves them all)


def init():
    """Creates the root window, fonts and the shared mouse-wheel handler. Call once, before
    importing the other GUI modules (they import root / F from here)."""
    global root, TkinterDnD, DND_FILES
    try:
        from tkinterdnd2 import TkinterDnD as _dnd, DND_FILES as _files
        TkinterDnD, DND_FILES = _dnd, _files
    except Exception:
        TkinterDnD, DND_FILES = None, None
    SETTINGS.update(load_settings())
    set_theme(SETTINGS["theme"])
    _setup_gpu()
    _set_app_id()
    root = TkinterDnD.Tk() if TkinterDnD else tk.Tk()
    _set_window_icon(root)
    fams = set(tkfont.families(root))

    def pick(*names):
        return next((n for n in names if n in fams), "TkDefaultFont")

    sans = pick("IBM Plex Sans", "Segoe UI", "Helvetica Neue", "DejaVu Sans")
    mono = pick("IBM Plex Mono", "Cascadia Mono", "Consolas", "DejaVu Sans Mono", "Courier New")
    F.clear()
    F.update({
        "body": (sans, 10), "small": (sans, 9), "bold": (sans, 10, "bold"),
        "smallbold": (sans, 9, "bold"), "h1": (sans, 18, "bold"), "h2": (sans, 10, "bold"),
        "title": (sans, 11, "bold"), "mono": (mono, 9), "monolist": (mono, 10),
    })
    root.bind_all("<MouseWheel>", _global_wheel)
    root.bind_all("<Button-4>", lambda e: _global_wheel(e, -1))
    root.bind_all("<Button-5>", lambda e: _global_wheel(e, 1))
    return root


def _setup_gpu():
    """3D on the graphics card unless turned off in Settings; the crash marker lives next to
    the settings file (see gpu3d.get)."""
    from .. import board3d, gpu3d
    from ..settings import settings_path
    gpu3d.crash_marker = settings_path().parent / "gpu_start.marker"
    board3d.set_gpu_enabled(SETTINGS.get("gpu3d", True))


_icon_photos: list = []  # Tk drops images nobody references, so the icon photos are kept here


def _set_app_id():
    """Windows groups taskbar buttons by app ID. Without its own ID a script run with python.exe
    is shown as Python (with Python's icon); with one, the taskbar uses this app's window icon."""
    import sys
    if sys.platform != "win32":
        return
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("XNBBoardTool.App")
    except Exception:
        pass


def _set_window_icon(win):
    """The app's logo as the icon of every window (title bar, taskbar, Alt+Tab)."""
    from ..icon import draw_icon
    try:
        _icon_photos[:] = [ImageTk.PhotoImage(draw_icon(s), master=win) for s in (16, 32, 48, 64, 256)]
        # True: also the default for every window opened later (dialogs)
        win.iconphoto(True, *reversed(_icon_photos))
    except Exception:
        pass


def widget_path_at(x_root, y_root) -> str:
    """Tk path of the widget under a screen point ('' if none).
    Unlike winfo_containing() this never fails on Tk's own internal widgets, such as the
    open list of a combobox ('...popdown'), which Python cannot look up (KeyError)."""
    try:
        return str(root.tk.call("winfo", "containing", "-displayof", root._w, x_root, y_root))
    except tk.TclError:
        return ""


def widget_at(x_root, y_root):
    """Python widget under a screen point, or None (also for Tk-internal widgets)."""
    name = widget_path_at(x_root, y_root)
    if not name:
        return None
    try:
        return root.nametowidget(name)
    except (KeyError, tk.TclError):
        return None


def _global_wheel(e, direction=None):
    """One mouse-wheel handler for every scroll area (the one under the cursor scrolls)."""
    name = widget_path_at(e.x_root, e.y_root)
    w = widget_at(e.x_root, e.y_root) if name else None
    if w is None or getattr(w, "_own_wheel", False):      # e.g. the 3D preview zooms instead
        return
    for sc in reversed(_scrolls):
        try:
            if sc.winfo_exists() and name.startswith(str(sc.canvas)):
                sc.scroll(e, direction)
                return
        except tk.TclError:
            pass


# ---------------- small widget helpers ----------------
def button(parent, text, cmd, kind="secondary", small=False, **kw):
    pbg = parent.cget("bg")
    if kind == "primary":
        bg, fg, hov, bd, font = C["accent"], C["onaccent"], C["accenth"], C["accent"], F["bold"]
    elif kind == "ghost":
        bg, fg, hov, bd, font = pbg, C["sub"], C["btn"], pbg, F["body"]
    else:
        bg, fg, hov, bd, font = C["btn"], C["text"], C["btnh"], C["btnb"], F["body"]
    if small:
        font = F["smallbold"] if kind == "primary" else F["small"]
    b = tk.Button(parent, text=text, command=cmd, bg=bg, fg=fg, activebackground=hov,
                  activeforeground=fg, disabledforeground=C["dis"], relief="flat", bd=0,
                  highlightthickness=1, highlightbackground=bd, highlightcolor=bd,
                  padx=10 if small else 14, pady=3 if small else 7, cursor="hand2", font=font, **kw)
    b.bind("<Enter>", lambda e: str(b["state"]) != "disabled" and b.config(bg=hov))
    b.bind("<Leave>", lambda e: b.config(bg=bg))
    return b


class MenuItem:
    """A '\u22ef' menu entry that set_state() can enable/disable like a button."""
    def __init__(self, menu, index):
        self.menu, self.index = menu, index

    def config(self, state=None, **_):
        if state is not None:
            self.menu.entryconfig(self.index, state=state)


def more_button(parent, items, small=True):
    """'\u22ef' button opening a menu; returns (button, [MenuItem per item])."""
    m = tk.Menu(parent, tearoff=0, bg=C["panel"], fg=C["text"], activebackground=C["btnh"],
                activeforeground=C["text"], disabledforeground=C["dis"], bd=0, relief="flat",
                font=F["body"])
    entries = []
    for k, (text, cmd) in enumerate(items):
        m.add_command(label=text, command=cmd)
        entries.append(MenuItem(m, k))
    b = button(parent, "\u22ef", None, small=small)
    b.config(command=lambda: m.tk_popup(b.winfo_rootx(), b.winfo_rooty() + b.winfo_height()))
    return b, entries


def card(parent):
    return tk.Frame(parent, bg=C["panel"], highlightthickness=1,
                    highlightbackground=C["border"])


def hline(parent, color=None):
    return tk.Frame(parent, bg=color or C["border"], height=1)


def label(parent, text="", font="body", fg="text", **kw):
    return tk.Label(parent, text=text, font=F[font], fg=C.get(fg, fg),
                    bg=kw.pop("bg", parent.cget("bg")), **kw)


def set_state(widgets, enabled):
    for w in widgets:
        w.config(state="normal" if enabled else "disabled",
                 cursor="hand2" if enabled else "arrow")


# ---------------- preview canvas ----------------
class Preview(tk.Canvas):
    HL = 1

    def __init__(self, master, aspect, max_h, on_drop=None):
        super().__init__(master, bg=C["btn"], bd=0, height=80, highlightthickness=self.HL,
                         highlightbackground=C["border"])
        self.img: Optional[Image.Image] = None
        self.aspect, self.max_h, self.message = aspect, max_h, ""
        self._photo, self._job, self._wh = None, None, None
        self.bind("<Configure>", lambda e: self._schedule())
        if on_drop and TkinterDnD:
            self.drop_target_register(DND_FILES)
            self.dnd_bind("<<DropEnter>>", lambda e: self._hl(True) or e.action)
            self.dnd_bind("<<DropLeave>>", lambda e: self._hl(False) or e.action)

            def dropped(e):
                self._hl(False)
                files = self.tk.splitlist(e.data)
                if files:
                    self.after(10, lambda: on_drop(files[0]))
                return e.action
            self.dnd_bind("<<Drop>>", dropped)

    def _hl(self, on):
        self.config(highlightbackground=C["accent"] if on else C["border"])

    def set_image(self, img, message=""):
        self.img, self.message = img, message
        if img is not None:
            self.aspect = img.height / max(1, img.width)
        self._wh = None
        self._schedule()

    def _schedule(self):
        if self._job:
            self.after_cancel(self._job)
        self._job = self.after(60, self._redraw)

    def _redraw(self):
        self._job = None
        W = self.winfo_width() - 2 * self.HL
        if W < 10:
            return
        H = max(40, min(round(W * self.aspect), self.max_h))
        if int(float(self.cget("height"))) != H:
            self.configure(height=H)
        if self._wh == (W, H, id(self.img)):
            return
        self._wh = (W, H, id(self.img))
        self.delete("all")
        o = self.HL
        if self.img is None:
            self.create_text(o + W // 2, o + H // 2, text=self.message or "No image",
                             fill=C["muted"], font=F["body"])
            return
        img = self.img
        s = min(W / img.width, H / img.height)
        nw, nh = max(1, round(img.width * s)), max(1, round(img.height * s))
        res = Image.LANCZOS if s < 1 else Image.NEAREST
        shown = Image.alpha_composite(checker(nw, nh), img.resize((nw, nh), res))
        self._photo = ImageTk.PhotoImage(shown)
        self.create_image(o + (W - nw) // 2, o + (H - nh) // 2, anchor="nw", image=self._photo)


# ---------------- scrollable area ----------------
class Scroll(tk.Frame):
    def __init__(self, master, width=None):
        super().__init__(master, bg=C["bg"])
        if width:
            self.config(width=width)
            self.pack_propagate(False)
        self.canvas = tk.Canvas(self, bg=C["bg"], highlightthickness=0, bd=0, yscrollincrement=24)
        sb = ttk.Scrollbar(self, orient="vertical", command=self._yview)
        self.inner = tk.Frame(self.canvas, bg=C["bg"])
        win = self.canvas.create_window(0, 0, window=self.inner, anchor="nw")
        self.canvas.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.inner.bind("<Configure>", lambda e: self.canvas.configure(
            scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(win, width=e.width))
        _scrolls.append(self)

    def scroll(self, e, direction=None):
        if self.inner.winfo_height() <= self.canvas.winfo_height():
            return
        if direction is None:
            direction = -1 if e.delta > 0 else 1
        self.canvas.yview_scroll(direction * 3, "units")
        self.canvas.update_idletasks()          # repaint the moved widgets now (avoids smearing)

    def _yview(self, *args):
        self.canvas.yview(*args)
        self.canvas.update_idletasks()
