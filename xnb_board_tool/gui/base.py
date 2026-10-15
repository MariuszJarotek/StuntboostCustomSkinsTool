"""Shared Tk state (root window, fonts) and small widgets used by every GUI module."""
from __future__ import annotations

from typing import Optional

from tkinter import ttk
import tkinter as tk
import tkinter.font as tkfont
from PIL import Image, ImageTk

from ..settings import C, SETTINGS, TEXT_SIZES, checker, load_settings, set_theme
from ..i18n import _, set_language


root = None             # the Tk root window, created by init()
F: dict = {}            # fonts
FAMILIES: dict = {}     # the font families found on this PC (sans, mono, condensed)
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
    from .. import diag
    set_language("en" if diag.SAFE else SETTINGS.get("language", "auto"))
    set_theme(SETTINGS["theme"])
    _setup_gpu()
    _set_app_id()
    root = TkinterDnD.Tk() if TkinterDnD else tk.Tk()
    _set_window_icon(root)
    fams = set(tkfont.families(root))

    def pick(*names):
        """The first of the given font families that is installed, else Tk's default font."""
        return next((n for n in names if n in fams), "TkDefaultFont")

    sans = pick("IBM Plex Sans", "Segoe UI", "Helvetica Neue", "DejaVu Sans")
    mono = pick("IBM Plex Mono", "Cascadia Mono", "Consolas", "DejaVu Sans Mono", "Courier New")
    cond = pick("Bahnschrift SemiBold Condensed", "Bahnschrift Condensed", "Archivo Narrow",
                "Roboto Condensed", "Arial Narrow", "DejaVu Sans Condensed", sans)
    FAMILIES.update(sans=sans, mono=mono, cond=cond)
    set_text_size(SETTINGS.get("text_size", "balanced"))
    root.bind_all("<MouseWheel>", _global_wheel)
    root.bind_all("<Button-4>", lambda e: _global_wheel(e, -1))
    root.bind_all("<Button-5>", lambda e: _global_wheel(e, 1))
    return root


def set_text_size(name: str) -> None:
    """Fills the font table from one of the TEXT_SIZES scales. Every widget takes its font from F,
    so rebuilding the window afterwards applies the new size everywhere."""
    t = TEXT_SIZES.get(name, TEXT_SIZES["balanced"])
    sans, mono, cond = FAMILIES["sans"], FAMILIES["mono"], FAMILIES["cond"]
    body, cap, tag, sec, page, mo = t["body"], t["cap"], t["tag"], t["section"], t["page"], t["mono"]
    F.clear()
    F.update({
        "body": (sans, body), "bold": (sans, body, "bold"), "h2": (sans, body, "bold"),
        "small": (sans, cap), "smallbold": (sans, cap, "bold"),
        "title": (sans, body + 1, "bold"), "h1": (sans, page - 4, "bold"),
        "mono": (mono, mo), "monolist": (mono, body), "tag": (mono, tag, "bold"),
        # condensed display type (Skate shop layout)
        "displayxl": (cond, page, "bold"), "displaylg": (cond, page, "bold"), "display": (cond, sec, "bold"),
        "displaysm": (cond, tag, "bold"), "displaytiny": (cond, cap, "bold"),
    })


def _setup_gpu():
    """3D on the graphics card unless turned off in Settings; the crash marker lives next to
    the settings file (see gpu3d.get)."""
    from .. import board3d, gpu3d
    from ..settings import settings_path
    gpu3d.crash_marker = settings_path().parent / "gpu_start.marker"
    from .. import diag
    board3d.set_gpu_enabled(SETTINGS.get("gpu3d", True) and not diag.SAFE)


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
_FRAME_KEYS = ("highlightthickness", "highlightbackground", "highlightcolor")


class _Boxed(tk.Frame):
    """A label inside a frame whose background is the outline. Windows draws tk.Button and its
    relatives natively and leaves out their highlight outline, and may do the same for labels; a
    frame's own background is painted everywhere, so the outline always shows. Options go to the
    right part: the highlight* options set the outline, everything else goes to the label."""

    def __init__(self, master, **kw):
        """Splits the options: the highlight* ones make the frame's coloured padding (the outline), the rest go to
        the label inside.
        """
        fk = {k: kw.pop(k) for k in _FRAME_KEYS if k in kw}
        t = int(fk.get("highlightthickness", 0) or 0)
        edge = fk.get("highlightbackground", fk.get("highlightcolor", master.cget("bg")))
        super().__init__(master, bg=edge if t else kw.get("bg", master.cget("bg")), padx=t, pady=t, bd=0,
                         highlightthickness=0, cursor=kw.get("cursor", ""))
        self._t, self._edge = t, edge
        kw.setdefault("bd", 0)
        kw.pop("relief", None)
        self.lbl = tk.Label(self, relief="flat", highlightthickness=0, **kw)
        self.lbl.pack(fill="both", expand=True)

    def bind(self, seq=None, func=None, add=None):
        """Binds an event on both the label and the frame, so the whole button (outline included) reacts."""
        if seq is None:
            return tk.Frame.bind(self)
        tk.Label.bind(self.lbl, seq, func, add)
        return tk.Frame.bind(self, seq, func, add)

    def _frame_opts(self, kw):
        """Takes the outline options out of `kw` and applies them to the frame (its padding is the outline width,
        its colour the outline colour).
        """
        t = kw.pop("highlightthickness", None)
        e = kw.pop("highlightbackground", None)
        kw.pop("highlightcolor", None)
        if t is not None:
            self._t = int(t or 0)
        if e is not None:
            self._edge = e
        if t is not None or e is not None:
            tk.Frame.configure(self, padx=self._t, pady=self._t,
                               bg=self._edge if self._t else self.lbl.cget("bg"))
        if "cursor" in kw:
            tk.Frame.configure(self, cursor=kw["cursor"])

    def configure(self, cnf=None, **kw):
        """Like Label.configure, with the outline options going to the frame. With no options it returns the
        label's configuration.
        """
        if cnf:
            kw.update(cnf)
        if not kw:
            return self.lbl.configure()
        kw.pop("relief", None)
        kw.pop("overrelief", None)
        self._frame_opts(kw)
        if kw:
            self.lbl.configure(**kw)
            if "bg" in kw and not self._t:
                tk.Frame.configure(self, bg=kw["bg"])
    config = configure

    def cget(self, key):
        """Reads an option: the outline ones from the frame, the rest from the label."""
        if key == "highlightthickness":
            return self._t
        if key in ("highlightbackground", "highlightcolor"):
            return self._edge
        return self.lbl.cget(key)
    __getitem__ = cget

    def _inside(self, e):
        """True when a mouse event happened inside its widget (a release outside cancels a click)."""
        w = e.widget
        return 0 <= e.x < w.winfo_width() and 0 <= e.y < w.winfo_height()


class FlatButton(_Boxed):
    """A button the app draws itself (see _Boxed). Takes the tk.Button options the app uses
    (command, state, activebackground, ...) and invoke()."""

    def __init__(self, master, command=None, **kw):
        """A button that looks the same on every system: a label with a frame outline. `command` runs on a click
        (mouse released inside); options Tk buttons have but labels do not are dropped.
        """
        for k in ("overrelief", "default", "activebackground", "activeforeground"):
            kw.pop(k, None)
        super().__init__(master, **kw)
        self.command = command
        tk.Label.bind(self.lbl, "<ButtonRelease-1>", self._release, add="+")
        tk.Frame.bind(self, "<ButtonRelease-1>", self._release, add="+")

    def _release(self, e):
        """Mouse released: click, unless the button is disabled or the pointer left it."""
        if str(self.lbl.cget("state")) != "disabled" and self._inside(e):
            self.invoke()

    def invoke(self):
        """Runs the command (unless disabled) and returns its result, like tk.Button.invoke."""
        if self.command and str(self.lbl.cget("state")) != "disabled":
            return self.command()

    def configure(self, cnf=None, **kw):
        """Like tk.Button.configure: 'command' is stored, the active* colours are ignored (hover is handled with
        bindings).
        """
        if "command" in kw:
            self.command = kw.pop("command")
        for k in ("activebackground", "activeforeground"):
            kw.pop(k, None)
        return _Boxed.configure(self, cnf, **kw)
    config = configure

    def cget(self, key):
        """Like tk.Button.cget, including 'command'."""
        return self.command if key == "command" else _Boxed.cget(self, key)
    __getitem__ = cget


class SegButton(_Boxed):
    """A segment of a segmented control (replaces tk.Radiobutton / tk.Checkbutton with
    indicatoron=False). With `value` it is a radio button for `variable`; without, a toggle of a
    BooleanVar. Filled with `selectcolor` when on, and given a stronger outline."""

    def __init__(self, master, variable=None, value=None, command=None, selectcolor=None, indicatoron=False,
                 onvalue=True, offvalue=False, **kw):
        """A segment of a segmented control: with `value` a radio button of `variable`, without it a toggle between
        onvalue and offvalue. Repaints itself whenever the variable changes.
        """
        for k in ("overrelief", "offrelief", "default", "tristatevalue", "activeforeground"):
            kw.pop(k, None)
        hov = kw.pop("activebackground", C["btnh"])
        super().__init__(master, **kw)
        self.var, self.value, self.command = variable, value, command
        self.onvalue, self.offvalue = onvalue, offvalue
        self._bg = kw.get("bg", master.cget("bg"))
        self._sel = selectcolor or C["selfill"]
        self._hov = hov
        self._in = False
        tk.Label.bind(self.lbl, "<ButtonRelease-1>", self._release, add="+")
        tk.Label.bind(self.lbl, "<Enter>", lambda e: self._hover(True), add="+")
        tk.Label.bind(self.lbl, "<Leave>", lambda e: self._hover(False), add="+")
        self._trace = None
        if self.var is not None:
            self._trace = self.var.trace_add("write", lambda *_a: self._paint())
            tk.Frame.bind(self, "<Destroy>", self._gone, add="+")
        self._paint()

    def _on(self):
        """True when this segment is the selected one (or the toggle is on)."""
        if self.var is None:
            return False
        try:
            v = self.var.get()
        except tk.TclError:
            return False
        if self.value is not None:
            return str(v) == str(self.value)
        return v == self.onvalue or v is True

    def _paint(self):
        """Paints the state: the select colour when on, the hover colour under the pointer, the accent outline when
        selected.
        """
        try:
            on = self._on()
            dis = str(self.lbl.cget("state")) == "disabled"
            self.lbl.configure(bg=self._sel if on else (self._hov if self._in and not dis else self._bg))
            if self._t:
                tk.Frame.configure(self, bg=C["accent"] if on else self._edge)
        except tk.TclError:
            pass

    def _hover(self, on):
        """Remembers whether the pointer is over the segment and repaints."""
        self._in = on
        self._paint()

    def _release(self, e):
        """Mouse released: click, unless disabled or the pointer left the segment."""
        if str(self.lbl.cget("state")) != "disabled" and self._inside(e):
            self.invoke()

    def invoke(self):
        """Selects this segment (or flips the toggle) and runs the command."""
        if self.var is not None:
            if self.value is not None:
                self.var.set(self.value)
            else:
                self.var.set(self.offvalue if self._on() else self.onvalue)
        if self.command:
            self.command()

    def select(self):
        """Selects this segment / turns the toggle on, without running the command (like Radiobutton.select)."""
        if self.var is not None:
            self.var.set(self.value if self.value is not None else self.onvalue)

    def deselect(self):
        """Turns a toggle off without running the command (like Checkbutton.deselect); radio segments ignore it.
        """
        if self.var is not None and self.value is None:
            self.var.set(self.offvalue)

    def configure(self, cnf=None, **kw):
        """Like Radiobutton.configure: command, selectcolor, activebackground and bg are remembered for painting.
        """
        if "command" in kw:
            self.command = kw.pop("command")
        if "selectcolor" in kw:
            self._sel = kw.pop("selectcolor")
        if "activebackground" in kw:
            self._hov = kw.pop("activebackground")
        kw.pop("activeforeground", None)
        if "bg" in kw:
            self._bg = kw["bg"]
        r = _Boxed.configure(self, cnf, **kw)
        self._paint()
        return r
    config = configure

    def _gone(self, e):
        """Stops watching the variable when the segment is destroyed."""
        if e.widget is self and self._trace:
            try:
                self.var.trace_remove("write", self._trace)
            except (tk.TclError, ValueError):
                pass


def button(parent, text, cmd, kind="secondary", small=False, **kw):
    """The app's standard button. kind: 'primary' (accent fill, for the main action), 'secondary' (normal) or
    'ghost' (outline only); small=True for compact rows. Hover colours included.
    """
    pbg = parent.cget("bg")
    if kind == "primary":
        bg, fg, hov, bd, font = C["accent"], C["onaccent"], C["accenth"], C["accent"], F["bold"]
    elif kind == "ghost":
        bg, fg, hov, bd, font = pbg, C["sub"], C["btnh"], C["dis"], F["body"]   # a light outline: it reads as a button
    else:
        bg, fg, hov, bd, font = C["btn"], C["text"], C["btnh"], C["btnb"], F["body"]
    if small:
        font = F["smallbold"] if kind == "primary" else F["small"]
    b = FlatButton(parent, text=text, command=cmd, bg=bg, fg=fg, activebackground=hov,
                  activeforeground=fg, disabledforeground=C["dis"], relief="flat", bd=0,
                  highlightthickness=1, highlightbackground=bd, highlightcolor=bd,
                  padx=10 if small else 14, pady=3 if small else 7, cursor="hand2", font=font, **kw)
    b.bind("<Enter>", lambda e: str(b["state"]) != "disabled" and b.config(bg=hov))
    b.bind("<Leave>", lambda e: b.config(bg=bg))
    return b


class MenuItem:
    """A '\u22ef' menu entry that set_state() can enable/disable like a button."""
    def __init__(self, menu, index):
        """Remembers which entry of which menu this is."""
        self.menu, self.index = menu, index

    def config(self, state=None, **_kw):
        """Enables or disables the menu entry (only `state` is used)."""
        if state is not None:
            self.menu.entryconfig(self.index, state=state)


def more_button(parent, items, small=True):
    """'\u22ef' button opening a menu; returns (button, [MenuItem per item])."""
    m = tk.Menu(parent, tearoff=0, bg=C["panel"], fg=C["text"], activebackground=C["btnh"],
                activeforeground=C["text"], disabledforeground=C["dis"], bd=0, relief="flat",
                font=F["body"])
    entries = []
    for k, (text, cmd) in enumerate(items):
        m.add_command(label=_(text), command=cmd)

        entries.append(MenuItem(m, k))
    b = button(parent, "\u22ef", None, small=small)
    b.config(command=lambda: m.tk_popup(b.winfo_rootx(), b.winfo_rooty() + b.winfo_height()))
    return b, entries


class Flow(tk.Frame):
    """A row of widgets that wraps onto more lines when it is too narrow (translated texts can be
    much longer than the English ones). Create the widgets with the Flow as parent, then add().
    natural=True: asks for the width of one line (for rows that are not stretched to fill)."""

    def __init__(self, master, gap=6, vgap=6, natural=False, **kw):
        """A frame that lays its children out in rows, wrapping to the next row when one is full (like text). gap /
        vgap: space between items / rows; natural=True asks for the width of one line instead of the widest
        item.
        """
        kw.setdefault("bg", master.cget("bg"))
        super().__init__(master, **kw)
        self.gap, self.vgap, self.natural, self._items = gap, vgap, natural, []
        self._job, self._runs, self._since = None, 0, 0.0
        self.bind("<Configure>", lambda e: self._later())

    def add(self, w, gap=None):
        """Adds a widget (already created with this Flow as parent) and lays out again. Returns the widget."""
        self._items.append((w, self.gap if gap is None else gap))
        w.bind("<Configure>", lambda e: self._later(), add="+")      # its text may change
        self._layout(None)
        return w

    def _later(self):
        """Lays out once the current events are handled (several changes -> one layout). A
        layout that keeps changing the size it depends on stops after a burst instead of
        keeping the program busy."""
        if self._job is not None:
            return
        import time
        now = time.monotonic()
        if now - self._since > 1.0:
            self._since, self._runs = now, 0
        self._runs += 1
        if self._runs > 40:
            return
        self._job = self.after_idle(self._run)

    def _run(self):
        """Lays out for the current width (the delayed job of _later())."""
        self._job = None
        try:
            self._layout(self.winfo_width())
        except tk.TclError:
            pass

    def _layout(self, width=None):
        """Places the items in rows that fit the width and sizes the frame to hold them."""
        items = [(w, g) for w, g in self._items if w.winfo_exists()]
        if not items:
            return
        one_line = sum(w.winfo_reqwidth() + g for w, g in items) - items[-1][1]
        widest = max(w.winfo_reqwidth() for w, _g in items)
        W = width if width and width > 1 else (one_line if self.natural else max(widest, self.winfo_width()))
        x = y = rowh = 0
        for w, g in items:
            rw, rh = w.winfo_reqwidth(), w.winfo_reqheight()
            if x and x + rw > W:
                x, y, rowh = 0, y + rowh + self.vgap, 0
            w.place(x=x, y=y)
            x += rw + g
            rowh = max(rowh, rh)
        want = (one_line if self.natural else widest, y + rowh)
        if (int(self.cget("width")), int(self.cget("height"))) != want:
            self.config(width=want[0], height=want[1])


def card(parent):
    """A panel frame with a thin border (the classic layouts' cards)."""
    return tk.Frame(parent, bg=C["panel"], highlightthickness=1,
                    highlightbackground=C["border"])


def hline(parent, color=None):
    """A one pixel horizontal line in the border colour (or the given colour)."""
    return tk.Frame(parent, bg=color or C["border"], height=1)


def label(parent, text="", font="body", fg="text", **kw):
    """A Label in one of the app's fonts (a key of F) and colours (a key of C, or a colour)."""
    return tk.Label(parent, text=text, font=F[font], fg=C.get(fg, fg),
                    bg=kw.pop("bg", parent.cget("bg")), **kw)


def set_state(widgets, enabled):
    """Enables or disables a list of widgets (also MenuItems) and sets the matching cursor."""
    for w in widgets:
        w.config(state="normal" if enabled else "disabled",
                 cursor="hand2" if enabled else "arrow")


# ---------------- preview canvas ----------------
class Preview(tk.Canvas):
    """Shows an image scaled to the width it gets (keeping its aspect ratio, up to max_h tall) over a checkerboard,
    or a message when there is no image. With on_drop and tkinterdnd2 installed, image files can be dropped on
    it.
    """
    HL = 1

    def __init__(self, master, aspect, max_h, on_drop=None):
        """A preview of the given aspect (height / width) and maximum height; on_drop(path) is called when a file
        is dropped on it.
        """
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
                """A file was dropped: hands its path to on_drop (shortly after, outside the drop event)."""
                self._hl(False)
                files = self.tk.splitlist(e.data)
                if files:
                    self.after(10, lambda: on_drop(files[0]))
                return e.action
            self.dnd_bind("<<Drop>>", dropped)

    def _hl(self, on):
        """Highlights the outline while a file is dragged over the preview."""
        self.config(highlightbackground=C["accent"] if on else C["border"])

    def set_image(self, img, message=""):
        """Shows an image (or `message` when img is None); the aspect follows the image."""
        self.img, self.message = img, message
        if img is not None:
            self.aspect = img.height / max(1, img.width)
        self._wh = None
        self._schedule()

    def _schedule(self):
        """Redraws shortly (60 ms), merging bursts of resizes into one redraw."""
        if self._job:
            self.after_cancel(self._job)
        self._job = self.after(60, self._redraw)

    def _redraw(self):
        """Draws the image at the current size (cached while nothing changed)."""
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
            self.create_text(o + W // 2, o + H // 2, text=self.message or _("No image"),
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
class Slider(tk.Frame):
    """The app's slider: a clear track (filled in the accent color up to the value), a solid knob,
    and ◀ ▶ arrows at both ends that step the value (hold to repeat). Drop-in for tk.Scale /
    ttk.Scale as the app uses them: variable, command (called with the value as text), resolution,
    length, set(), get(), state(['disabled']) and config(state=...). Bindings for the mouse buttons
    (bind('<ButtonPress-1>'), ...) go to the track and the arrows, so code that wraps a drag in
    an undo step keeps working."""

    H = 22          # track height (px)
    AW = 20         # arrow width

    def __init__(self, master, from_=0.0, to=100.0, variable=None, command=None, resolution=None,
                 length=200, step=None, bg=None, **_ignored):
        """A slider from `from_` to `to` bound to `variable`; `command(value_text)` runs on every change made by
        the user; `resolution` rounds the value; `step` is how far one arrow click moves (a round tenth of a
        percent of the range by default).
        """
        bg = bg or master.cget("bg")
        super().__init__(master, bg=bg)
        self.lo, self.hi = float(from_), float(to)
        self.res = float(resolution) if resolution else None
        span = abs(self.hi - self.lo) or 1.0
        import math
        nice = 10 ** math.floor(math.log10(max(span / 100.0, 1e-9)))
        self.step = float(step) if step else max(self.res or 0.0, nice)
        self.var = variable if variable is not None else tk.DoubleVar(value=self.lo)
        self.command = command
        self.enabled = True
        self._rep = None
        self._bg = bg
        self.left = tk.Canvas(self, width=self.AW, height=self.H, bg=bg, highlightthickness=0, cursor="hand2")
        self.track = tk.Canvas(self, width=length, height=self.H, bg=bg, highlightthickness=0, cursor="hand2")
        self.right = tk.Canvas(self, width=self.AW, height=self.H, bg=bg, highlightthickness=0, cursor="hand2")
        self.left.pack(side="left")
        self.right.pack(side="right")              # packed before the track, so it is never squeezed out
        self.track.pack(side="left", fill="x", expand=True, padx=2)
        for cv, d in ((self.left, -1), (self.right, 1)):
            tk.Canvas.bind(cv, "<ButtonPress-1>", lambda e, d=d: self._arrow_press(d))
            tk.Canvas.bind(cv, "<ButtonRelease-1>", lambda e: self._arrow_release())
            tk.Canvas.bind(cv, "<Enter>", lambda e, c=cv: self._draw_arrow(c, hover=True))
            tk.Canvas.bind(cv, "<Leave>", lambda e, c=cv: (self._draw_arrow(c), self._arrow_release()))
        tk.Canvas.bind(self.track, "<ButtonPress-1>", self._drag)
        tk.Canvas.bind(self.track, "<B1-Motion>", self._drag)
        tk.Canvas.bind(self.track, "<Configure>", lambda e: self._draw())
        self._trace = self.var.trace_add("write", lambda *_a: self._draw())
        self.bind("<Destroy>", self._gone, add="+")
        self._draw_arrow(self.left)
        self._draw_arrow(self.right)
        self._draw()

    # -- value --
    def _fix(self, v):
        """A value clamped to the range and rounded to the resolution."""
        lo, hi = min(self.lo, self.hi), max(self.lo, self.hi)
        v = max(lo, min(hi, float(v)))
        if self.res:
            v = self.lo + round((v - self.lo) / self.res) * self.res
            v = round(v, 6)
        return v

    def get(self):
        """The current value (the start of the range if the variable holds nothing usable)."""
        try:
            return float(self.var.get())
        except (tk.TclError, ValueError):
            return self.lo

    def set(self, v, fire=False):
        """Sets the value (clamped and rounded); fire=True also runs the command, as a user change does."""
        v = self._fix(v)
        if v != self.get():
            self.var.set(v)
            if fire and self.command:
                self.command(str(v))
        else:
            self._draw()

    def _frac(self):
        """Where the value sits in the range, 0-1 (for drawing the handle)."""
        span = self.hi - self.lo
        return 0.0 if not span else max(0.0, min(1.0, (self.get() - self.lo) / span))

    # -- input --
    def _drag(self, e):
        """Mouse pressed or dragged on the track: jumps the value to that point."""
        if not self.enabled:
            return
        W = max(1, self.track.winfo_width() - 14)
        f = max(0.0, min(1.0, (e.x - 7) / W))
        self.set(self.lo + f * (self.hi - self.lo), fire=True)

    def _arrow_press(self, d, first=True):
        """An arrow pressed: one step, then repeats while held (after 380 ms, then every 55 ms)."""
        if not self.enabled:
            return
        self.set(self.get() + d * self.step * (1 if self.hi >= self.lo else -1), fire=True)
        self._rep = self.after(380 if first else 55, lambda: self._arrow_press(d, False))

    def _arrow_release(self):
        """An arrow released: stops repeating."""
        if self._rep is not None:
            self.after_cancel(self._rep)
            self._rep = None

    # -- drawing --
    def _draw_arrow(self, cv, hover=False):
        """Draws an arrow (accent colour under the pointer, grey when disabled)."""
        cv.delete("all")
        col = C["dis"] if not self.enabled else (C["accent"] if hover else C["text"])
        w, h = self.AW, self.H
        if cv is self.left:
            pts = (w - 6, 5, 5, h / 2, w - 6, h - 5)
        else:
            pts = (6, 5, w - 5, h / 2, 6, h - 5)
        cv.create_polygon(*pts, fill=col, outline=col)

    def _draw(self):
        """Draws the track, the filled part (from the start, or from 0 when the range crosses 0) and the handle.
        """
        cv = self.track
        try:
            W = cv.winfo_width()
        except tk.TclError:
            return
        if W < 20:
            W = int(cv.cget("width"))
        cv.delete("all")
        y = self.H / 2
        x0, x1 = 7, W - 7
        x = x0 + self._frac() * (x1 - x0)
        line = C["btnb"] if self.enabled else C["dis"]
        cv.create_rectangle(x0, y - 3, x1, y + 3, fill=C["chk2"], outline=line, width=1)
        if self.enabled:
            # filled from the start (or from 0 when the range crosses 0)
            z = x0 if not (min(self.lo, self.hi) < 0 < max(self.lo, self.hi)) else \
                x0 + (0 - self.lo) / (self.hi - self.lo) * (x1 - x0)
            cv.create_rectangle(min(z, x), y - 3, max(z, x), y + 3, fill=C["accent"], outline="")
        cv.create_rectangle(x - 5, 2, x + 5, self.H - 2, fill=C["accent"] if self.enabled else C["dis"],
                            outline=C["text"] if self.enabled else C["dis"], width=2)

    # -- compatibility --
    def bind(self, seq=None, func=None, add=None):
        """Binds mouse presses on the track and both arrows (as ttk.Scale bindings would), Enter / Leave on the
        track, everything else on the frame.
        """
        if seq in ("<ButtonPress-1>", "<ButtonRelease-1>", "<Button-1>"):
            for w in (self.track, self.left, self.right):
                tk.Canvas.bind(w, seq, func, add="+")
            return None
        if seq in ("<Enter>", "<Leave>"):
            tk.Canvas.bind(self.track, seq, func, add="+")
        return tk.Frame.bind(self, seq, func, add)

    def state(self, spec=None):
        """ttk-style state: state(['disabled']) / state(['!disabled']); returns the current state."""
        if spec:
            self._set_enabled(not any(s == "disabled" for s in spec))
        return () if self.enabled else ("disabled",)

    def configure(self, cnf=None, **kw):
        """Accepts state='disabled' / 'normal' and command, like a Scale; other options go to the frame."""
        st = kw.pop("state", None)
        if st is not None:
            self._set_enabled(st != "disabled")
        if "command" in kw:
            self.command = kw.pop("command")
        if kw or cnf:
            return tk.Frame.configure(self, cnf, **kw)
    config = configure

    def _set_enabled(self, on):
        """Enables or disables the slider and repaints it."""
        if on == self.enabled:
            return
        self.enabled = on
        for cv in (self.left, self.right, self.track):
            cv.config(cursor="hand2" if on else "arrow")
        self._draw_arrow(self.left)
        self._draw_arrow(self.right)
        self._draw()

    def _gone(self, e):
        """Stops watching the variable when the slider is destroyed."""
        if e.widget is self:
            try:
                self.var.trace_remove("write", self._trace)
            except (tk.TclError, ValueError):
                pass


class Scroll(tk.Frame):
    """A vertically scrolling area: put widgets in .inner. The mouse wheel scrolls the area under the pointer (see
    the global wheel handler).
    """
    def __init__(self, master, width=None):
        """A scrolling area, optionally of a fixed width."""
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
        """Scrolls by a wheel event (or a given direction) when the content is taller than the area."""
        if self.inner.winfo_height() <= self.canvas.winfo_height():
            return
        if direction is None:
            direction = -1 if e.delta > 0 else 1
        self.canvas.yview_scroll(direction * 3, "units")
        self.canvas.update_idletasks()          # repaint the moved widgets now (avoids smearing)

    def _yview(self, *args):
        """Scrollbar moved: scroll and repaint right away."""
        self.canvas.yview(*args)
        self.canvas.update_idletasks()
