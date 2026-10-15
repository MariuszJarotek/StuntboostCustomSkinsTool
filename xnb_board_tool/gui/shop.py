"""The Skate shop layout: the Wall (every deck hanging on rails) and the Bench (one deck, top and
bottom side by side, with a tool dock and a sheet per tool).

The Bench builds the same named widgets as the other layouts (title_lbl, tex_prev, pal_widgets,
b_tex_replace, ...), so every action of the App works here unchanged; this module only arranges
them and draws the Wall and the two flat deck views."""
from __future__ import annotations

from tkinter import ttk
import tkinter as tk
from PIL import Image, ImageDraw, ImageFilter, ImageTk

from ..boards import PALETTE_SLOTS, to_hex
from ..i18n import N_, _, _n
from ..settings import C, _rgb
from .base import F, FlatButton, set_state, MenuItem, Preview, Scroll, SegButton, Slider, button, label, more_button
from . import base


def ink():
    """The theme's 'ink' colour (the header rod, rails and tags; falls back to the text colour)."""
    return C.get("ink", C["text"])


def onink():
    """The colour for text on ink (falls back to the background colour)."""
    return C.get("onink", C["bg"])


def _flat_button(parent, text, cmd, bg, fg, hover, font=None, bd=None, padx=14, pady=7):
    """A button with explicit colors (for the ink bars, where the theme's button colors don't fit)."""
    b = FlatButton(parent, text=text, command=cmd, bg=bg, fg=fg, activebackground=hover,
                  activeforeground=fg, disabledforeground=C["dis"], relief="flat", bd=0,
                  highlightthickness=2 if bd else 0, highlightbackground=bd or bg, highlightcolor=bd or bg,
                  padx=padx, pady=pady, cursor="hand2", font=font or F["bold"])
    b.bind("<Enter>", lambda e: str(b["state"]) != "disabled" and b.config(bg=hover))
    b.bind("<Leave>", lambda e: b.config(bg=bg))
    return b


def _rounded(draw, box, r, **kw):
    """Draws a rounded rectangle (a plain one on very old Pillow)."""
    try:
        draw.rounded_rectangle(box, radius=r, **kw)
    except AttributeError:                      # very old Pillow
        draw.rectangle(box, **kw)


class HangTag(tk.Canvas):
    """A tag hanging on a short rod from the header's rail (the Skate shop header). kind: 'on' (the
    active tab, accent), 'ink' (filled), 'outline' (the folder chip). Hovering pulls it down a little."""
    HOOK, H = 12, 28

    def __init__(self, master, text, command, kind="ink", font=None, bg=None, hook=None, h=None):
        """A tag hanging from the header line. kind: 'on' (accent, the active one), 'ink' (filled), 'outline' or
        'color' (colours given with set()). hook=0 makes a plain tag that sits in a row; h sets its height.
        """
        if hook is not None:
            self.HOOK = hook                    # 0: a plain tag that sits in a row instead of hanging
        if h is not None:
            self.H = h
        super().__init__(master, bg=bg or C["bg"], highlightthickness=0, bd=0, cursor="hand2" if command else "",
                         height=self.HOOK + self.H + 6, width=40)
        self.text, self.command, self.kind = text, command, kind
        self.font = font or F["displaysm"]
        self.dot, self.warn, self.hover, self.colors = None, False, False, None
        self.bind("<Button-1>", lambda e: self.command and self.command())
        self.bind("<Enter>", lambda e: self.command and self._hov(True))
        self.bind("<Leave>", lambda e: self._hov(False))
        self.draw()

    def _hov(self, on):
        """Pointer over the tag: it drops a little and its outline lights."""
        self.hover = on
        self.draw()

    def invoke(self):
        """Runs the tag's command, like a button's invoke()."""
        if self.command:
            self.command()

    def set(self, text=None, kind=None, dot=None, warn=None, colors=None):
        """Changes the text, kind, dot colour, warning or colours; redraws only when something changed."""
        changed = False
        for k, v in (("text", text), ("kind", kind), ("dot", dot), ("warn", warn), ("colors", colors)):
            if v is not None and getattr(self, k) != v:
                setattr(self, k, v)
                changed = True
        if changed:
            self.draw()

    def draw(self):
        """Draws the rod and the tag (sized to its text), in the colours of its kind."""
        import tkinter.font as tkfont
        self.delete("all")
        f = tkfont.Font(root=self, font=self.font)
        dotw = 14 if self.dot else 0
        w = f.measure(self.text) + 24 + dotw
        if int(float(self.cget("width"))) != w + 4:
            self.config(width=w + 4)
        drop = 3 if self.hover else 0
        x0, y0 = 2, self.HOOK + drop
        cx = x0 + w / 2
        self.create_line(cx, 0, cx, y0 + 1, fill=ink(), width=2)
        if self.kind == "color" and self.colors:
            fill, fg = self.colors
            edge = fill
        elif self.kind == "on":
            fill, fg, edge = C["accent"], C["onaccent"], C["accent"]
        elif self.kind == "outline":
            fill, fg, edge = self.cget("bg"), ink(), ink()
        else:
            fill, fg, edge = ink(), onink(), ink()
        if self.hover and self.command:
            edge = C["accent"] if self.kind != "on" else ink()
        self.create_rectangle(x0, y0, x0 + w, y0 + self.H, fill=fill, outline=edge, width=2)
        tx = x0 + 12
        if self.dot:
            self.create_oval(tx, y0 + self.H / 2 - 4, tx + 8, y0 + self.H / 2 + 4, fill=self.dot, outline="")
            tx += dotw
        self.create_text(tx, y0 + self.H / 2, text=self.text, anchor="w", font=self.font,
                         fill=C["warn"] if (self.warn and self.kind == "outline") else fg)


class SideArrow(tk.Canvas):
    """A tall bar with a drawn chevron on a side of the deck fan (‹ or ›). Works with set_state()."""
    W = 40

    def __init__(self, master, direction, command, side_line, caption="", width=None):
        """A tall bar with a chevron (direction -1 = left, +1 = right) and an optional caption under it;
        `side_line` ('left' / 'right') is where its edge line is drawn.
        """
        super().__init__(master, width=width or self.W, height=60, bg=C["btn"], highlightthickness=0, bd=0,
                         cursor="hand2")
        self.dir, self.command, self.side_line, self.caption = direction, command, side_line, caption
        self.enabled, self.hover = True, False
        self.bind("<ButtonRelease-1>", self._click)
        self.bind("<Enter>", lambda e: self._hov(True))
        self.bind("<Leave>", lambda e: self._hov(False))
        self.bind("<Configure>", lambda e: self.draw())

    def _click(self, e):
        """Mouse released on the bar: runs the command when enabled and still inside."""
        if self.enabled and 0 <= e.x < self.winfo_width() and 0 <= e.y < self.winfo_height() and self.command:
            self.command()

    def _hov(self, on):
        """Pointer over the bar: accent fill."""
        self.hover = on
        self.draw()

    def configure(self, cnf=None, **kw):
        """Accepts state='disabled' / 'normal' like a button (for set_state); other options go to the canvas."""
        st = kw.pop("state", None)
        if st is not None:
            self.enabled = st != "disabled"
            self.draw()
        if kw or cnf:
            return tk.Canvas.configure(self, cnf, **kw)
    config = configure

    def cget(self, key):
        """Like a button's cget, including 'state'."""
        if key == "state":
            return "normal" if self.enabled else "disabled"
        return tk.Canvas.cget(self, key)
    __getitem__ = cget

    def draw(self):
        """Draws the bar: its edge line, the chevron and the caption, in the hover / disabled colours."""
        self.delete("all")
        W, H = self.winfo_width(), self.winfo_height()
        if W < 4 or H < 4:
            return
        hot = self.hover and self.enabled
        tk.Canvas.configure(self, bg=C["accent"] if hot else C["btn"])
        fg = (C["onaccent"] if hot else ink()) if self.enabled else C["dis"]
        lx = W - 1 if self.side_line == "right" else 1           # the line between the bar and the decks
        self.create_line(lx, 0, lx, H, fill=ink(), width=2)
        cx, cy, a, b = W / 2, H / 2 - (9 if self.caption else 0), 5, 12
        pts = (cx + a, cy - b, cx - a, cy, cx + a, cy + b) if self.dir < 0 else (cx - a, cy - b, cx + a, cy, cx - a, cy + b)
        self.create_line(*pts, fill=fg, width=3, capstyle="projecting", joinstyle="miter")
        if self.caption:
            self.create_text(cx, cy + b + 14, text=self.caption, font=F["displaytiny"], fill=fg)


class DeckTag(tk.Canvas):
    """The deck on the bench as a big tag hanging from the header's line on two rods: a small label
    ('BOARD'), the deck's number large, and its status on a coloured stripe. set() takes the status the
    same way as HangTag.set (text / colors), set_name() the label and the number."""
    ROD, PAD = 10, 12

    def __init__(self, master, height):
        """The tag, as tall as the title row."""
        super().__init__(master, height=height, width=170, bg=C["bg"], highlightthickness=0, bd=0)
        self.small, self.big, self.text, self.colors = _("Board").upper(), "", "", (C["btn"], C["muted"])
        self.bind("<Configure>", lambda e: self.draw())

    def set(self, text=None, kind=None, colors=None, **_kw):
        """Sets the status stripe's text and colours (the App calls this the same way as HangTag.set)."""
        changed = False
        if text is not None and text != self.text:
            self.text, changed = text, True
        if colors is not None and tuple(colors) != tuple(self.colors):
            self.colors, changed = tuple(colors), True
        if changed:
            self.draw()

    def set_name(self, small, big):
        """Sets the small label ('BOARD' / 'FILE') and the big name."""
        if (small, big) != (self.small, self.big):
            self.small, self.big = small, big
            self.draw()

    def draw(self):
        """Draws the rods, the plate with its shadow, the small label (top left), the name (right, as large as
        the plate allows) and the status stripe; the canvas takes the tag's width.

        Label and name sit side by side rather than stacked, so the name can use the plate's full height and
        the two never overlap, whatever the text size setting makes the label.
        """
        import tkinter.font as tkfont
        self.delete("all")
        H = int(float(self.cget("height")))
        sf = tkfont.Font(root=self, font=F["displaytiny"])
        top, y1 = self.ROD, H - 8
        stripe = sf.metrics("linespace") + 4
        area_top, area_bot = top + 6, y1 - stripe - 4    # the room for the name, above the stripe
        name = self.big or "—"
        fam = F["displayxl"][0]
        size = 40
        while True:                                     # too tall for the room, or a long file name: smaller
            big = tkfont.Font(root=self, family=fam, size=size, weight="bold")
            cap = big.metrics("ascent") * 0.74          # height of capitals and digits (no accents above)
            if (cap <= area_bot - area_top and big.measure(name) <= 300) or size <= 12:
                break
            size -= 1
        gap = 14
        w = max(150, self.PAD + sf.measure(self.small) + gap + big.measure(name) + self.PAD,
                sf.measure(self.text) + 2 * self.PAD)
        if int(float(self.cget("width"))) != w + 4:
            self.config(width=w + 4)
        x0, x1 = 2, 2 + w
        for rx in (x0 + 22, x1 - 22):                   # the two rods from the line
            self.create_line(rx, 0, rx, top + 1, fill=ink(), width=2)
        self.create_rectangle(x0 + 3, top + 4, x1 + 3, y1 + 4, fill=C["side"], outline="")    # a hard shadow
        self.create_rectangle(x0, top, x1, y1, fill=ink(), outline="")
        self.create_text(x0 + self.PAD, top + 4, text=self.small, anchor="nw", font=F["displaytiny"], fill=onink())
        # right-aligned, its digits centred in the room (anchor "se" is the bottom of the descent)
        baseline = (area_top + area_bot) / 2 + cap / 2
        self.create_text(x1 - self.PAD, baseline + big.metrics("descent"), text=name, anchor="se",
                         font=(fam, size, "bold"), fill=onink())
        bg, fg = self.colors
        self.create_rectangle(x0, y1 - stripe, x1, y1, fill=bg, outline="")
        self.create_text((x0 + x1) / 2, y1 - stripe / 2, text=self.text, font=F["displaytiny"], fill=fg)


class IconButton(tk.Canvas):
    """A square tool button with a drawn icon (the fonts on a PC may lack arrow and symbol glyphs).
    Hovering shows its name in the status bar. Works with set_state() like the other buttons."""
    W, H = 38, 32

    def __init__(self, master, icon, tip, command, status=None):
        """A square button with a drawn icon (see draw()); hovering shows `tip` through status()."""
        super().__init__(master, width=self.W, height=self.H, bg=master.cget("bg"), highlightthickness=0, bd=0,
                         cursor="hand2")
        self.icon, self.tip, self.command, self.status = icon, tip, command, status
        self.enabled, self.hover = True, False
        self.bind("<ButtonRelease-1>", self._click)
        self.bind("<Enter>", lambda e: self._hov(True))
        self.bind("<Leave>", lambda e: self._hov(False))
        self.draw()

    def _click(self, e):
        """Mouse released inside the button: runs the command when enabled."""
        if self.enabled and 0 <= e.x < self.W and 0 <= e.y < self.H and self.command:
            self.command()

    def _hov(self, on):
        """Pointer over the button: highlight and its tip in the status bar."""
        self.hover = on
        if on and self.status:
            self.status(self.tip)
        self.draw()

    def configure(self, cnf=None, **kw):
        """Accepts state='disabled' / 'normal' (for set_state); other options go to the canvas."""
        st = kw.pop("state", None)
        if st is not None:
            self.enabled = st != "disabled"
            self.draw()
        if kw or cnf:
            return tk.Canvas.configure(self, cnf, **kw)
    config = configure

    def cget(self, key):
        """Like a button's cget, including 'state'."""
        if key == "state":
            return "normal" if self.enabled else "disabled"
        return tk.Canvas.cget(self, key)
    __getitem__ = cget

    def draw(self):
        """Draws the frame and the icon: up, down, dup, delete, fill, fit, rotate or flip."""
        self.delete("all")
        W, H = self.W, self.H
        on = self.enabled
        fg = (C["accent"] if self.hover else ink()) if on else C["dis"]
        self.create_rectangle(1, 1, W - 2, H - 2, outline=fg if on else C["dis"], width=2,
                              fill=C["btnh"] if (self.hover and on) else self.cget("bg"))
        cx, cy = W / 2, H / 2
        L = dict(fill=fg, width=2)
        i = self.icon
        if i in ("up", "down"):
            d = -1 if i == "up" else 1                       # -1: points up
            self.create_line(cx, cy - 8 * d, cx, cy + 4 * d, **L)
            self.create_polygon(cx - 7, cy + 2 * d, cx + 7, cy + 2 * d, cx, cy + 10 * d, fill=fg, outline=fg)
        elif i == "dup":
            self.create_rectangle(cx - 8, cy - 7, cx + 3, cy + 4, outline=fg, width=2)
            self.create_rectangle(cx - 3, cy - 2, cx + 8, cy + 9, outline=fg, width=2, fill=self.cget("bg"))
        elif i == "delete":
            self.create_line(cx - 8, cy - 6, cx + 8, cy - 6, **L)
            self.create_line(cx - 3, cy - 9, cx + 3, cy - 9, **L)
            self.create_polygon(cx - 6, cy - 4, cx + 6, cy - 4, cx + 5, cy + 9, cx - 5, cy + 9, outline=fg, fill="", width=2)
            for x in (-2, 2):
                self.create_line(cx + x, cy - 1, cx + x, cy + 6, fill=fg, width=1)
        elif i == "fill":
            self.create_rectangle(cx - 9, cy - 8, cx + 9, cy + 8, outline=fg, width=2)
            self.create_rectangle(cx - 6, cy - 5, cx + 6, cy + 5, fill=fg, outline=fg)
        elif i == "fit":
            self.create_rectangle(cx - 9, cy - 8, cx + 9, cy + 8, outline=fg, width=2)
            self.create_rectangle(cx - 4, cy - 3, cx + 4, cy + 3, fill=fg, outline=fg)
        elif i == "rotate":
            self.create_arc(cx - 8, cy - 8, cx + 8, cy + 8, start=30, extent=270, style="arc", outline=fg, width=2)
            self.create_polygon(cx + 9, cy - 9, cx + 9, cy - 1, cx + 2, cy - 5, fill=fg, outline=fg)
        elif i == "flip":
            self.create_line(cx, cy - 10, cx, cy + 10, fill=fg, width=1, dash=(2, 2))
            self.create_polygon(cx - 3, cy - 7, cx - 3, cy + 7, cx - 11, cy + 7, fill=fg, outline=fg)
            self.create_polygon(cx + 3, cy - 7, cx + 3, cy + 7, cx + 11, cy + 7, fill="", outline=fg, width=2)


STATUS_WORDS = {"def": N_("Stock"), "mod": N_("Custom"), "none": N_("No backup")}

FILTERS = (("all", N_("All")), ("mod", N_("Custom")), ("def", N_("Stock")), ("none", N_("No backup")))

TOOLS = (("general", N_("General")), ("stickers", N_("Advanced")), ("stock", N_("Stock")))
SECTIONS = ("art", "paint", "thumb")          # parts of the General sheet


class ShopMixin:
    """The Skate shop layout. Mixed into App."""

    WALL_DW, WALL_DH = 58, 258          # a deck on the wall (px, including its edge)
    WALL_HOOK, WALL_RAIL = 16, 8
    WALL_GAP_X, WALL_GAP_Y = 26, 34

    # ------------------------------------------------------------------ header
    def _shop_header(self):
        """The shop sign: a rod along the top of the window (like the Wall's rails) with the tabs, the
        game-folder chip (live counts, opens a menu) and Settings hanging from it as tags."""
        for stale in ("path_lbl", "path_kind"):          # the long path label is gone in this layout
            self.__dict__.pop(stale, None)
        hdr = tk.Frame(base.root, bg=C["bg"])
        hdr.pack(fill="x")
        tk.Frame(hdr, bg=ink(), height=5).pack(fill="x")             # the rod
        row = tk.Frame(hdr, bg=C["bg"])
        row.pack(fill="x", padx=24)
        mark = tk.Frame(row, bg=C["bg"])
        mark.pack(side="left", pady=(8, 8))
        tk.Label(mark, text=_("BOARD"), font=F["display"], fg=ink(), bg=C["bg"]).pack(side="left")
        tk.Label(mark, text=_("TOOL"), font=F["display"], fg=C["onaccent"], bg=C["accent"], padx=6).pack(side="left", padx=(4, 0))
        tabs = tk.Frame(row, bg=C["bg"])
        tabs.pack(side="left", padx=(28, 0), anchor="n")
        self.tab_var = tk.StringVar(value=self._keep.get("tab", "boards"))
        self._shop_tabs = {}
        for text, val in ((N_("Decks"), "boards"), (N_("Speedmeter"), "speed")):
            t = HangTag(tabs, _(text).upper(), lambda v=val: (self.tab_var.set(v), self.switch_tab()))
            t.pack(side="left", padx=(0, 10), anchor="n")
            self._shop_tabs[val] = t
        self._shop_settings_tag = HangTag(row, _("Settings").upper(), self.open_settings)
        self._shop_settings_tag.pack(side="right", anchor="n")
        # the folder chip: game name and live counts; its menu holds the path and the folder actions
        menu = self._shop_folder_menu = tk.Menu(base.root, tearoff=0, bg=C["panel"], fg=C["text"],
                                                activebackground=C["btnh"], activeforeground=C["text"],
                                                disabledforeground=C["muted"], bd=0, relief="flat", font=F["body"])
        menu.add_command(label="", state="disabled")                  # 0: the full path
        menu.add_separator()                                          # 1
        menu.add_command(label=_("Change folder…"), command=self.change_folder)            # 2
        menu.add_command(label=_("Copy path"), command=self._shop_copy_path)                # 3
        menu.add_separator()                                          # 4
        menu.add_command(label=_("Save all as stock"), command=self.save_all_defaults)     # 5
        self.btn_saveall = MenuItem(menu, 5)
        self._shop_chip = HangTag(row, "", self._shop_folder_popup, kind="outline")
        self._shop_chip.pack(side="right", padx=(0, 12), anchor="n")
        tk.Frame(base.root, bg=ink(), height=2).pack(fill="x")

    def _shop_folder_popup(self):
        """Opens the folder chip's menu (full path, Change folder..., Copy path, Save all as stock) under the chip.
        """
        menu, chip = self._shop_folder_menu, self._shop_chip
        kind, full = self._path_text()
        menu.entryconfig(0, label=full)
        menu.tk_popup(chip.winfo_rootx(), chip.winfo_rooty() + chip.winfo_height())

    def _shop_copy_path(self):
        """Copies the game folder's path to the clipboard."""
        _kind, full = self._path_text()
        base.root.clipboard_clear()
        base.root.clipboard_append(full)
        self.set_status(_("Copied {path}", path=full))

    def _shop_game_name(self):
        """'STUNTBOOST' for …/STUNTBOOST/Content/…: the folder above Content, else the folder's own name."""
        f = self.folder
        if f is None:
            return ""
        for p in [f] + list(f.parents):
            if p.name.lower() == "content" and p.parent.name:
                return p.parent.name
        return f.name

    def _shop_tabs_refresh(self):
        """Lights the current tab's tag and writes the folder chip: the game's name with live counts (decks,
        custom, unsaved) or, on the Speedmeter tab, the HUD's parts.
        """
        tab = self.tab_var.get()
        tab = "boards" if tab == "decor" else tab           # decorating happens on the Bench
        for val, t in getattr(self, "_shop_tabs", {}).items():
            t.set(kind="on" if val == tab else "ink")
        chip = getattr(self, "_shop_chip", None)
        if chip is None:
            return
        unsaved = set()
        if tab == "speed":
            ok = self.sm_folder is not None
            parts = [self._shop_game_name().upper() or _("SPEEDMETER"), _("HUD"),
                     _n("{n} part", "{n} parts", len(self.sm_tex)).upper()]
            pend = self._sm_pending() if hasattr(self, "_sm_pending") and hasattr(self, "sm_rc") else []
            if pend:
                unsaved = set(pend)
                parts.append(_("{n} unsaved", n=len(pend)).upper())
            text = "  ·  ".join(parts) if ok else _("SPEEDMETER") + " · " + _("no folder").upper()
        elif not self.folder:
            ok, text = False, _("Open a content folder")
        else:
            ok = True
            n = len(self.boards)
            custom = sum(1 for i in range(n) if self.status.get(i) == "mod")
            unsaved = {s.path for s in self.dc_unsaved()} if hasattr(self, "dc_sessions") else set()
            if self.sel is not None and not self.custom and self._pal_changed() and self.tex_path:
                unsaved.add(self.tex_path)
            parts = [self._shop_game_name().upper(), _n("{n} deck", "{n} decks", n).upper()]
            if custom:
                parts.append(_("{n} custom", n=custom).upper())
            if unsaved:
                parts.append(_("{n} unsaved", n=len(unsaved)).upper())
            text = "  ·  ".join(parts)
        chip.set(text=text + "  ▾", dot=C["green"] if ok else C["dis"], warn=bool(unsaved))

    # ------------------------------------------------------------------ layout
    def _layout_shop(self, view):
        """The boards view of the Skate shop layout: the Wall and the Bench pages (the board list is a hidden tree,
        used for filtering and stepping).
        """
        self._status_filter = self._keep.get("status_filter")
        # the list model (filtering / stepping) lives in a tree that is never shown, as in the Gallery
        self.tree = ttk.Treeview(view, show="tree", style="Boards.Treeview", selectmode="browse")
        self.tree.bind("<<TreeviewSelect>>", self._on_tree_select)
        wall = tk.Frame(view, bg=C["bg"])
        bench = tk.Frame(view, bg=C["bg"])
        self._shop_build_wall(wall)
        self._shop_build_bench(bench)
        self.shop_pages = {"wall": wall, "bench": bench}
        self.shop_show(self._keep.get("shop_page", "wall"))
        base.root.bind("<Escape>", self._shop_escape, add="+")

    def shop_show(self, page):
        """Shows the Wall or the Bench. Leaving the Bench while decorating goes back to the Boards tab (unsaved
        stickers stay in their session).
        """
        if not hasattr(self, "shop_pages"):
            return
        self.shop_page = page if page in self.shop_pages else "wall"
        if self.shop_page == "wall" and self.tab_var.get() == "decor":
            self.tab_var.set("boards")                        # unsaved stickers stay in their session
        for k, f in self.shop_pages.items():
            if k != self.shop_page:
                f.pack_forget()
        self.shop_pages[self.shop_page].pack(fill="both", expand=True)
        if self.shop_page == "bench":
            self._shop_mode_apply()
        else:
            base.root.after(30, lambda: (self._wall_layout(force=True),
                                         self.sel is not None and self._wall_scroll_to(self.sel)))
        self._shop_bars()

    def _shop_escape(self, e):
        """Esc on the Bench goes back to the Wall (not while typing in a field)."""
        if getattr(self, "layout", None) != "shop" or self.tab_var.get() != "boards":
            return
        if isinstance(e.widget, tk.Entry):
            return
        if getattr(self, "shop_page", "") == "bench":
            self.shop_show("wall")

    # ------------------------------------------------------------------ the Wall
    def _shop_build_wall(self, page):
        # the Wall's own row: its name and count on the left; the filters hang from the header's line as
        # tags, with the deck number search next to them
        """Builds the Wall: its title and count, the filter tags and the deck search, the scrolling canvas with the
        decks on rails, and the 'On the bench' bar.
        """
        top = tk.Frame(page, bg=C["bg"])
        top.pack(fill="x", padx=24, pady=(0, 4))
        left = tk.Frame(top, bg=C["bg"])
        left.pack(side="left", anchor="n", pady=(12, 0))
        tk.Label(left, text=_("THE WALL"), font=F["displayxl"], fg=ink(), bg=C["bg"]).pack(side="left")
        self.count_lbl = label(left, "", "small", "sub", bg=C["bg"])
        self.count_lbl.pack(side="left", padx=(12, 0), pady=(8, 0))
        right = tk.Frame(top, bg=C["bg"])
        right.pack(side="right", anchor="n")
        chips = tk.Frame(right, bg=C["bg"])
        chips.pack(side="left", padx=(0, 14), anchor="n")
        self._shop_chips = {}
        for key, text in FILTERS:
            t = HangTag(chips, _(text).upper(), lambda k=key: self._shop_set_filter(k), kind="ink")
            t.pack(side="left", padx=(0, 8), anchor="n")
            self._shop_chips[key] = (t, text)
        fb = self._build_filter(right, C["bg"])
        fb.config(highlightthickness=2, highlightbackground=ink(), highlightcolor=ink())
        fb.pack(side="left", ipadx=30, anchor="n", pady=(12, 0))
        self._shop_chips_refresh()

        area = tk.Frame(page, bg=C["bg"])
        area.pack(fill="both", expand=True, padx=(24, 0), pady=(6, 0))
        c = self.gal_canvas = tk.Canvas(area, bg=C["bg"], highlightthickness=0, bd=0, yscrollincrement=24)
        sb = ttk.Scrollbar(area, orient="vertical", command=c.yview)

        def _yscroll(a, b, _sb=sb):
            """Scrollbar moved: also draws the decks that came into view."""
            _sb.set(a, b)
            self._wall_fill()
        c.configure(yscrollcommand=_yscroll)
        sb.pack(side="right", fill="y")
        c.pack(side="left", fill="both", expand=True)
        c._own_wheel = True
        c.bind("<Configure>", lambda e: self._wall_schedule())
        c.bind("<Button-1>", self._wall_click)
        c.bind("<Motion>", self._wall_motion)
        c.bind("<Leave>", lambda e: (self._wall_set_hover(None), c.config(cursor="")))
        c.bind("<MouseWheel>", lambda e: self._wall_wheel(-1 if e.delta > 0 else 1))
        c.bind("<Button-4>", lambda e: self._wall_wheel(-1))
        c.bind("<Button-5>", lambda e: self._wall_wheel(1))
        self._gal_geom, self._gal_key, self._wall_job = {}, None, None
        self._gal_drawn, self._wall_photos, self._wall_rows = set(), {}, []

        bar = self._wall_bar = tk.Frame(page, bg=ink())
        bar.pack(side="bottom", fill="x")
        inner = tk.Frame(bar, bg=ink())
        inner.pack(fill="x", padx=24, pady=10)
        tk.Label(inner, text=_("ON THE BENCH"), font=F["displaysm"], fg=onink(), bg=ink()).pack(side="left")
        self._wall_bar_msg = tk.Label(inner, text="", font=F["body"], fg=onink(), bg=ink(), anchor="w")
        self._wall_bar_msg.pack(side="left", fill="x", expand=True, padx=16)
        self._wall_bar_btn = _flat_button(inner, "", None, C["accent"], C["onaccent"], C["accenth"])
        # packed by _shop_bars when there is something to open
        bar.pack_forget()
        bar.pack(side="bottom", fill="x", before=area)

    def _shop_set_filter(self, key):
        """Uses a status filter ('all', 'mod', 'def', 'none') for the Wall and the deck fan."""
        self._status_filter = None if key == "all" else key
        self._shop_chips_refresh()
        self._fill_list()

    def _shop_chips_refresh(self):
        """Writes the filter tags on the Wall and on the Bench: each with its count, the current one lit."""
        cur = getattr(self, "_status_filter", None) or "all"
        n = len(self.boards)
        vals = [self.status.get(i) for i in range(n)]
        for chips in (getattr(self, "_shop_chips", {}), getattr(self, "_shop_bench_chips", {})):
            for key, (t, text) in chips.items():
                count = n if key == "all" else vals.count(key)
                t.set(text=f"{_(text).upper()}  {count}", kind="on" if key == cur else "ink")

    # -- drawing --
    def _wall_schedule(self):
        """Lays the Wall out again soon (60 ms), merging resize bursts."""
        if getattr(self, "_wall_job", None):
            base.root.after_cancel(self._wall_job)
        self._wall_job = base.root.after(60, self._wall_layout)

    def _wall_layout(self, force=False):
        """Works out the Wall's grid (as many decks per rail as fit), draws the rails (each ending at its last
        deck) and the decks in view. Does nothing when nothing changed unless force=True.
        """
        self._wall_job = None
        if self.layout != "shop" or not hasattr(self, "gal_canvas"):
            return
        c = self.gal_canvas
        avail = max(200, c.winfo_width() - 24)
        cell_min = self.WALL_DW + self.WALL_GAP_X
        cols = max(1, avail // cell_min)
        cw = avail / cols
        rh = self._wall_row_h()
        shown = [int(k) for k in self.tree.get_children()]
        key = (cols, avail, tuple(shown))
        if not force and key == self._gal_key:
            return
        self._gal_key = key
        c.delete("all")
        self._gal_geom, self._gal_drawn = {}, set()
        self._wall_hover = None
        rows = -(-len(shown) // cols) if shown else 0
        self._wall_grid(c, avail + 12, 24 + rows * rh)
        self._wall_rows = []
        for r in range(rows):
            y = 14 + r * rh
            n_in_row = min(cols, len(shown) - r * cols)
            # the rail ends just past the last deck hanging on it (decks sit in the middle of their cells)
            x0 = max(4, 6 + 0.5 * cw - self.WALL_DW / 2 - 14)
            x1 = 6 + (n_in_row - 0.5) * cw + self.WALL_DW / 2 + 14
            c.create_rectangle(x0, y, x1, y + self.WALL_RAIL, fill=ink(), outline="", tags=("rail",))
            self._wall_rows.append(y)
        for n, i in enumerate(shown):
            r, k = divmod(n, cols)
            x0 = 6 + k * cw
            y0 = 14 + r * rh
            self._gal_geom[i] = (x0, y0, x0 + cw, y0 + rh - self.WALL_GAP_Y)
        if not shown:
            c.create_text(20, 30, anchor="nw", fill=C["muted"], font=F["body"],
                          text=_("No decks match this filter.") if self.boards else _("Open a content folder to begin"))
        c.configure(scrollregion=(0, 0, avail + 12, 24 + rows * rh))
        self._wall_fill()

    @staticmethod
    def _wall_grid(c, w, h):
        """Themes with a 'grid' colour (Blueprint) draw faint drafting lines behind the decks."""
        col = C.get("grid")
        if not col:
            return
        step = 24
        for x in range(0, int(w) + step, step):
            c.create_line(x, 0, x, h, fill=col, width=2 if x % (step * 5) == 0 else 1, tags=("grid",))
        for y in range(0, int(h) + step, step):
            c.create_line(0, y, w, y, fill=col, width=2 if y % (step * 5) == 0 else 1, tags=("grid",))
        c.tag_lower("grid")

    def _wall_row_h(self):
        """The height of one rail with its decks, number and status label."""
        return self.WALL_RAIL + self.WALL_HOOK + self.WALL_DH + 56 + self.WALL_GAP_Y

    def _wall_window(self, before, after):
        """The part of the Wall to keep drawn: from `before` screen heights above the view to `after` below it.
        """
        c = self.gal_canvas
        h = max(c.winfo_height(), 200)
        y = c.canvasy(0)
        return y - h * before, y + h * after

    def _wall_fill(self):
        """Draws the decks near the view and drops the pictures of decks far away (so a wall of hundreds of decks
        stays light).
        """
        if self.layout != "shop" or not hasattr(self, "gal_canvas") or not self._gal_geom:
            return
        top, bot = self._wall_window(0.5, 1.5)
        for i, (_x0, y0, _x1, y1) in self._gal_geom.items():
            if i not in self._gal_drawn and y1 >= top and y0 <= bot:
                self._wall_draw(i)
        ftop, fbot = self._wall_window(3, 4)
        for i in list(self._gal_drawn):
            geo = self._gal_geom.get(i)
            if geo is not None and (geo[3] < ftop or geo[1] > fbot):
                self.gal_canvas.delete(f"deck{i}")
                self._gal_drawn.discard(i)
                self._wall_photos.pop(i, None)

    def _wall_src(self, i):
        """(image, version key) for deck i: the card image from memory or the disk cache, else the
        small list strip, else None."""
        b = self.boards[i] if i < len(self.boards) else None
        if b is None:
            return None, None
        pil = self.gal_pil.get(i)
        if pil is not None:
            return pil, ("mem", id(pil))
        src = b.thumb or b.texture
        sig = self.cards.sig(src) if src else None
        if src:
            pil = self.cards.card(b.name, sig)
            if pil is not None:
                return pil, ("disk", tuple(sig or ()))
            # not on disk for this version of the file (it was just written): build the card from
            # the decoded texture if it is still in memory, and keep it for next time
            from ..caches import TEXCACHE
            from ..boards import strip_image
            t = TEXCACHE.get(src)
            if t is not None:
                pil = strip_image(t.img, self.GAL_W, self.GAL_H)
                try:
                    self.cards.store(b.name, sig, card=pil)
                except Exception:
                    self.gal_pil[i] = pil
                return pil, ("built", tuple(sig or ()))
        strip = self.strip_pil.get(i)
        if strip is not None:
            return strip, ("strip", id(strip))
        return None, None

    def _wall_deck_image(self, img, edge, w, h, bg, shadow=True, ring=None, angle=0.0):
        """A vertical deck: the (landscape) art turned upright, rounded, with a colored edge and a
        soft shadow, on the wall color. `ring`: an outline colour around the deck (hover);
        `angle`: swing in degrees around the hook at the top centre (the padding grows to fit)."""
        E = max(3, w // 14)
        pad = (10 if shadow else 0) + (int(h * abs(angle) / 57) + 4 if angle else 0) + (4 if ring else 0)
        clear = bool(ring or angle or C.get("grid"))   # hover / grid themes: transparent around the deck
        out = Image.new("RGBA", (w + 2 * pad, h + 2 * pad), (0, 0, 0, 0) if clear else _rgb(bg))   # never covers its neighbours
        if shadow:
            sh = Image.new("L", out.size, 0)
            _rounded(ImageDraw.Draw(sh), (pad, pad + 5, pad + w - 1, pad + h + 3), w // 2, fill=90)
            sh = sh.filter(ImageFilter.GaussianBlur(5))
            if clear:
                shade = Image.new("RGBA", out.size, (0, 0, 0, 0))
                shade.putalpha(sh)
                out = Image.alpha_composite(out, shade)
            else:
                out.paste(Image.new("RGBA", out.size, (0, 0, 0, 255)), (0, 0), sh)
        deck = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        m = Image.new("L", (w, h), 0)
        _rounded(ImageDraw.Draw(m), (0, 0, w - 1, h - 1), w // 2, fill=255)
        deck.paste(Image.new("RGBA", (w, h), _rgb(edge)), (0, 0), m)
        iw, ih = w - 2 * E, h - 2 * E
        if img is not None and iw > 4 and ih > 4:
            art = img.convert("RGBA").transpose(Image.ROTATE_90).resize((iw, ih), Image.LANCZOS)
            flat = Image.new("RGBA", (iw, ih), _rgb(C["chk1"]))
            flat.alpha_composite(art)
            mi = Image.new("L", (iw, ih), 0)
            _rounded(ImageDraw.Draw(mi), (0, 0, iw - 1, ih - 1), iw // 2, fill=255)
            deck.paste(flat, (E, E), mi)
        if ring:
            _rounded(ImageDraw.Draw(out), (pad - 4, pad - 4, pad + w + 3, pad + h + 3), w // 2 + 4,
                     outline=_rgb(ring), width=3)
        out.alpha_composite(deck, (pad, pad))
        if angle:
            # swing on the hook: rotate around the top centre of the deck, wall colour behind
            out = out.rotate(angle, resample=Image.BICUBIC, center=(pad + w / 2, pad),
                             fillcolor=(0, 0, 0, 0) if clear else _rgb(bg))
        return (out if clear else out.convert("RGB")), pad

    def _wall_status(self, i):
        """The word and colour under a deck: Unsaved (stickers not written), Stock, Custom or No backup."""
        unsaved = {s.path for s in self.dc_unsaved()} if hasattr(self, "dc_sessions") else set()
        b = self.boards[i]
        if b.texture in unsaved:
            return _("Unsaved"), C["warn"]
        st = self.status.get(i)
        if st is None:
            return "…", C["muted"]
        return _(STATUS_WORDS[st]), {"def": C["okfg"], "mod": ink(), "none": C["warn"]}[st]

    def _wall_draw(self, i):
        """Draws one deck on the Wall: its picture on the hook (lifted when it is on the bench or pointed at,
        swinging while pointed at), the number tag and the status word.
        """
        c, geo = self.gal_canvas, self._gal_geom.get(i)
        if geo is None:
            return
        x0, y0, x1, _y1 = geo
        t = f"deck{i}"
        c.delete(t)
        self._gal_drawn.add(i)
        sel = (i == self.sel and not self.custom)
        hover = i == getattr(self, "_wall_hover", None)
        angle = getattr(self, "_wall_angle", 0.0) if hover else 0.0
        cx = (x0 + x1) / 2
        W, H = self.WALL_DW, self.WALL_DH
        lift = (-10 if sel else 0) + (-8 if hover else 0)
        rail_b = y0 + self.WALL_RAIL
        src, ver = self._wall_src(i)
        pal = self.board_pal.get(i)
        edge = to_hex(pal[0]) if pal else C["btnb"]
        ring = C["accent"] if hover else None
        key = (ver, edge, sel, W, H, C["bg"], ring, round(angle, 1))
        ent = self._wall_photos.get(i)
        if ent is None or ent[0] != key:
            img, pad = self._wall_deck_image(src, edge, W, H, C["bg"], shadow=True, ring=ring, angle=angle)
            ent = (key, ImageTk.PhotoImage(img), pad)
            self._wall_photos[i] = ent
        _k, photo, pad = ent
        top = rail_b + self.WALL_HOOK + lift
        c.create_image(cx - W / 2 - pad, top - pad, image=photo, anchor="nw", tags=(t,))
        c.create_line(cx, rail_b, cx, top + 3, fill=ink(), width=2, tags=(t,))
        c.tag_raise("rail")
        ty = rail_b + self.WALL_HOOK + H + 16
        name = self.boards[i].name
        num = name if len(name) > 2 or not name.isdigit() else name.zfill(2)
        tid = c.create_text(cx, ty, text=num, font=F["tag"], fill=C["onaccent"] if sel else onink(), tags=(t,))
        bx0, by0, bx1, by1 = c.bbox(tid)
        rect = c.create_rectangle(bx0 - 7, by0 - 3, bx1 + 7, by1 + 3, fill=C["accent"] if sel else ink(),
                                  outline=C["accent"] if hover else "", width=2, tags=(t,))
        c.tag_lower(rect, tid)
        word, col = self._wall_status(i)
        if hover:
            word, col = _("Open →"), C["warn"]
        c.create_text(cx, by1 + 14, text=word.upper(), font=F["displaytiny"], fill=col, tags=(t,))

    def _wall_update(self, i):
        """Redraws one deck if it is drawn."""
        if self.layout == "shop" and hasattr(self, "gal_canvas") and i is not None and i in self._gal_drawn:
            self._wall_draw(i)

    def _wall_hit(self, e):
        """The deck under a mouse event, or None."""
        x, y = self.gal_canvas.canvasx(e.x), self.gal_canvas.canvasy(e.y)
        for i, (x0, y0, x1, y1) in self._gal_geom.items():
            cx = (x0 + x1) / 2
            if abs(x - cx) <= self.WALL_DW / 2 + 8 and y0 <= y <= y1:
                return i
        return None

    def _wall_click(self, e):
        """Click on a deck: puts it on the bench and shows the Bench."""
        i = self._wall_hit(e)
        if i is not None:
            if i != self.sel or self.custom:
                self.select(i)
            self.shop_show("bench")

    WALL_SWING = (4.0, -3.0, 2.0, -1.2, 0.6, 0.0)       # degrees, one frame every 40 ms

    def _wall_motion(self, e):
        """Pointer over the Wall: hand cursor and hover on the deck under it."""
        i = self._wall_hit(e)
        self.gal_canvas.config(cursor="hand2" if i is not None else "")
        self._wall_set_hover(i)

    def _wall_set_hover(self, i):
        """Starts the hover (swing, status text) on deck i and ends it on the previous one."""
        old = getattr(self, "_wall_hover", None)
        if i == old:
            return
        self._wall_hover = i
        job = getattr(self, "_wall_anim", None)
        if job:
            base.root.after_cancel(job)
            self._wall_anim = None
        self._wall_angle = 0.0
        if old is not None:
            self._wall_update(old)
        if i is not None:
            self._wall_swing(i, 0)
            b = self.boards[i]
            word, _col = self._wall_status(i)
            self.set_status(_("Deck {name} · {status} — click to put it on the bench", name=b.name, status=word))

    def _wall_swing(self, i, k):
        """A short swing on the hook while the pointer is on deck i."""
        self._wall_anim = None
        if getattr(self, "_wall_hover", None) != i or k >= len(self.WALL_SWING):
            return
        self._wall_angle = self.WALL_SWING[k]
        self._wall_update(i)
        self._wall_anim = base.root.after(40, self._wall_swing, i, k + 1)

    def _wall_wheel(self, d):
        """Mouse wheel over the Wall: scrolls when there is more to see."""
        c = self.gal_canvas
        sr = c.cget("scrollregion").split()
        if sr and float(sr[3]) > c.winfo_height():
            c.yview_scroll(d * 3, "units")

    def _wall_scroll_to(self, i):
        """Scrolls the Wall so deck i is in view."""
        if self.layout != "shop" or not hasattr(self, "gal_canvas") or i not in self._gal_geom:
            return
        c = self.gal_canvas
        _x0, y0, _x1, y1 = self._gal_geom[i]
        sr = c.cget("scrollregion").split()
        total = float(sr[3]) if sr else 1.0
        top = c.canvasy(0)
        if y0 < top or y1 > top + c.winfo_height():
            c.yview_moveto(max(0.0, (y0 - 12) / max(total, 1.0)))

    # ------------------------------------------------------------------ the Bench
    def _shop_build_bench(self, page):
        """Builds the Bench: the title row (Wall bar, the deck tag, the filter tags, the deck fan), the dock
        (views, tools, hint), the bottom bar (Revert / Save board), the stage and the tool sheet.
        """
        top = tk.Frame(page, bg=C["bg"])
        top.pack(fill="x")
        # one row: the tall Wall bar, the deck's tag hanging from the line, the Wall's filters (they pick which
        # decks the fan holds) with what isn't written yet under them, then the deck fan
        self._shop_wall_bar = SideArrow(top, -1, lambda: self.shop_show("wall"), "right", caption=_("Wall").upper(),
                                        width=64)
        self._shop_wall_bar.config(height=self.CAR_H)
        self._shop_wall_bar.pack(side="left", fill="y")
        # the App writes the title and the status here; the tag shows them (_shop_refresh)
        hidden = tk.Frame(top)
        self.title_lbl = tk.Label(hidden, text="")
        self.badge = tk.Label(hidden, font=F["smallbold"])
        self._shop_deck_tag = DeckTag(top, self.CAR_H)
        self._shop_deck_tag.pack(side="left", padx=(22, 0))
        mid = tk.Frame(top, bg=C["bg"])
        mid.pack(side="left", fill="y", padx=(22, 0))
        flt = tk.Frame(mid, bg=C["bg"])
        flt.pack(side="top", anchor="w")
        self._shop_bench_chips = {}
        for key, text in FILTERS:
            t = HangTag(flt, _(text).upper(), lambda k=key: self._shop_filter_swap(k), kind="ink")
            t.pack(side="left", padx=(0, 8), anchor="n")
            self._shop_bench_chips[key] = (t, text)
        self._shop_lead2 = tk.Frame(mid, bg=C["bg"])
        self._shop_lead2.pack(side="top", anchor="w", pady=(6, 0))
        self.shop_dirty_lbl = label(self._shop_lead2, "", "smallbold", "warn", bg=C["bg"])
        self.shop_dirty_lbl.pack(side="left")
        # the deck fan: every deck hangs from the header's line on a long arm from a point far above;
        # the one on the bench hangs right down, the others show their lower half. ‹ › on the sides,
        # the wheel turns it, and it never ends (after the last deck comes the first)
        fan = self._car_box = tk.Frame(top, bg=C["bg"])
        fan.pack(side="left", fill="x", expand=True, padx=(22, 0))
        self.btn_prev = SideArrow(fan, -1, lambda: self.step(-1), "right")
        self.btn_prev.pack(side="left", fill="y")
        self.btn_next = SideArrow(fan, 1, lambda: self.step(1), "left")
        self.btn_next.pack(side="right", fill="y")
        self._car_cv = tk.Canvas(fan, height=self.CAR_H, width=120, bg=C["bg"], highlightthickness=0, bd=0)
        self._car_cv.pack(side="left", fill="x", expand=True)
        self._car_init()
        # Decorate's chip and Undo / Redo live here; shown only while decorating
        self._shop_dc_tools = tk.Frame(self._shop_lead2, bg=C["bg"])
        tk.Frame(page, bg=ink(), height=2).pack(fill="x")

        # the dock hangs from the line under the title: the view toggle on the left, the tools in the
        # middle (Advanced = stickers, layers, effects), the hint on the right
        dock_row = tk.Frame(page, bg=C["bg"])
        dock_row.pack(fill="x", padx=24)
        dock_row.columnconfigure(0, weight=1, uniform="dock")
        dock_row.columnconfigure(2, weight=1, uniform="dock")
        views = self._shop_views_frame = tk.Frame(dock_row, bg=C["bg"])
        views.grid(row=0, column=0, sticky="nw")
        self.shop_view = tk.StringVar(value=self._keep.get("shop_view", "3d"))      # 3D first
        self._shop_view_btns = {}
        for text, val in ((N_("3D"), "3d"), (N_("Top & bottom"), "flat")):
            t = HangTag(views, _(text).upper(), lambda v=val: (self.shop_view.set(v), self._shop_view_show()))
            t.pack(side="left", padx=(0, 8), anchor="n")
            self._shop_view_btns[val] = t
        dock = tk.Frame(dock_row, bg=C["bg"])
        dock.grid(row=0, column=1, sticky="n")
        kept = self._keep.get("shop_tool", "general")
        self.shop_tool = tk.StringVar(value="general" if kept in SECTIONS else kept)
        self._shop_tool_btns = {}
        for val, text in TOOLS:
            cmd = self.open_decorate if val == "stickers" else (lambda v=val: self._shop_dock(v))
            t = HangTag(dock, _(text).upper(), cmd)
            t.pack(side="left", padx=5, anchor="n")
            self._shop_tool_btns[val] = t
        self._shop_hint = label(dock_row, _("Click a part of the deck to paint it"), "small", "sub", bg=C["bg"])
        self._shop_hint.grid(row=0, column=2, sticky="e")

        # Decorate's view is built into this frame (see LayoutsMixin._build_rest)
        self._shop_decor_holder = tk.Frame(page, bg=C["bg"])
        grp = self._shop_bench_group = tk.Frame(page, bg=C["bg"])
        grp.pack(fill="both", expand=True)
        page = grp

        # bottom bar first so it stays visible
        bar = self._shop_bench_bar = tk.Frame(page, bg=ink())
        bar.pack(side="bottom", fill="x")
        bi = tk.Frame(bar, bg=ink())
        bi.pack(fill="x", padx=24, pady=10)
        self.shop_bench_msg = tk.Label(bi, text="", font=F["body"], fg=onink(), bg=ink(), anchor="w")
        self.shop_bench_msg.pack(side="left", fill="x", expand=True)
        self.b_pal_apply = _flat_button(bi, _("Save board"), self.apply_colors, C["accent"],
                                        C["onaccent"], C["accenth"], bd=C["accent"])
        self.b_pal_apply.pack(side="right")
        self.b_pal_reset = _flat_button(bi, _("Revert"), self.reset_colors, ink(), onink(), C["sub"],
                                        font=F["body"], bd=onink())
        self.b_pal_reset.pack(side="right", padx=(0, 10))

        body = self._shop_bench_body = tk.Frame(page, bg=C["bg"])
        body.pack(fill="both", expand=True)
        sheet_wrap = tk.Frame(body, bg=C["panel"], width=400)
        sheet_wrap.pack(side="right", fill="y")
        sheet_wrap.pack_propagate(False)
        tk.Frame(body, bg=ink(), width=2).pack(side="right", fill="y")
        stage = tk.Frame(body, bg=C["bg"])
        stage.pack(side="left", fill="both", expand=True)
        self._shop_build_stage(stage)
        sc = self._shop_sheet_scroll = Scroll(sheet_wrap)
        sc.canvas.config(bg=C["panel"])
        sc.inner.config(bg=C["panel"])
        sc.pack(fill="both", expand=True)
        self._shop_build_sheets(sc.inner)

    # -- stage: top + bottom flat views, or the 3D preview --
    def _shop_build_stage(self, stage):
        """Builds the stage: the flat Top / Bottom decks, the Stock comparison and the 3D view (only one shows at a
        time, see _shop_view_show).
        """
        holder = tk.Frame(stage, bg=C["bg"])
        holder.pack(fill="both", expand=True, padx=24, pady=10)
        # flat views
        flat = self._shop_flat = tk.Frame(holder, bg=C["bg"])
        flat.columnconfigure(0, weight=1)
        flat.columnconfigure(1, weight=1)
        flat.rowconfigure(0, weight=1)
        self._shop_cv = {}
        for col, (key, cap) in enumerate((("top", N_("Top")), ("bottom", N_("Bottom")))):
            f = tk.Frame(flat, bg=C["bg"])
            f.grid(row=0, column=col, sticky="nsew")
            cv = tk.Canvas(f, bg=C["bg"], highlightthickness=0, bd=0, width=160, height=300)
            cv.pack(fill="both", expand=True)
            cv.bind("<Configure>", lambda e: self._shop_draw_decks())
            tk.Label(f, text=_(cap).upper(), font=F["displaysm"], fg=ink(), bg=C["bg"]).pack(pady=(6, 0))
            self._shop_cv[key] = cv
        self._shop_cv["top"].bind("<Button-1>", self._shop_top_click)
        self._shop_cv["top"].bind("<Motion>", lambda e: self._shop_cv["top"].config(cursor="hand2"))
        # Stock: the deck as it is now against its stock, side by side, with what changed
        cmp_ = self._shop_cmp = tk.Frame(holder, bg=C["bg"])
        hr = tk.Frame(cmp_, bg=C["bg"])
        hr.pack(fill="x", pady=(4, 10))
        tk.Label(hr, text=_("Your deck against its stock").upper(), font=F["display"], fg=ink(),
                 bg=C["bg"]).pack(side="left")
        self._shop_cmp_tag = tk.Label(hr, text="", font=F["displaysm"], padx=8, pady=2, bg=C["bg"])
        self._shop_cmp_tag.pack(side="left", padx=(12, 0))
        self._shop_cmp_mode = tk.StringVar(value="side")
        segs = tk.Frame(hr, bg=C["bg"])
        segs.pack(side="right")
        for val, text in (("side", N_("Side by side")), ("diff", N_("Show what changed"))):
            SegButton(segs, text=_(text), variable=self._shop_cmp_mode, value=val, command=self._shop_draw_stock,
                      font=F["small"], bg=C["btn"], fg=C["text"], padx=12, pady=5, highlightthickness=1,
                      highlightbackground=C["btnb"], cursor="hand2").pack(side="left")
        self._shop_cmp_chips = tk.Frame(cmp_, bg=C["bg"])
        self._shop_cmp_chips.pack(side="bottom", fill="x", pady=(10, 0))
        self._shop_cmp_cv = tk.Canvas(cmp_, bg=C["bg"], highlightthickness=0, bd=0, height=300)
        self._shop_cmp_cv.pack(fill="both", expand=True)
        self._shop_cmp_cv.bind("<Configure>", lambda e: self._shop_draw_stock())
        # 3D view: the same widgets and bindings as the 3D card of the other layouts
        v3 = self._shop_3d = tk.Frame(holder, bg=C["bg"])
        vbar = tk.Frame(v3, bg=C["bg"])
        vbar.pack(side="bottom", fill="x", pady=(6, 0))
        for text, yaw, pitch in (("3/4", 120, 28), (N_("Top"), 120, 30), (N_("Bottom"), 120, -30), (N_("Side"), 90, 0)):
            button(vbar, _(text), lambda y=yaw, p=pitch: self.v3_view(y, p), small=True).pack(side="left", padx=(0, 4))
        self.v3_screws = tk.BooleanVar(value=self._keep.get("screws", True))
        self.v3_outline = tk.BooleanVar(value=self._keep.get("outline", True))
        for text, var in ((N_("Outline"), self.v3_outline), (N_("Screws"), self.v3_screws)):
            tk.Checkbutton(vbar, text=_(text), variable=var, command=self.v3_schedule, bg=C["bg"], fg=C["sub"],
                           activebackground=C["bg"], activeforeground=C["text"], selectcolor=C["panel"],
                           font=F["small"], bd=0, highlightthickness=0, cursor="hand2").pack(side="right", padx=(8, 0))
        self.v3_note = label(v3, "", "small", "muted", anchor="w", justify="left", bg=C["bg"])
        self.v3_note.pack(side="bottom", fill="x", pady=(4, 0))
        self.v3_note.bind("<Configure>", lambda e: self.v3_note.config(wraplength=max(150, e.width - 4)))
        self.v3_canvas = tk.Canvas(v3, height=300, bg=C["bg"], highlightthickness=0, cursor="fleur")
        self.v3_canvas.pack(fill="both", expand=True)
        self.v3_canvas._own_wheel = True
        c = self.v3_canvas
        c.bind("<Configure>", lambda e: self.v3_schedule())
        c.bind("<ButtonPress-1>", self._v3_press)
        c.bind("<B1-Motion>", self._v3_drag)
        c.bind("<ButtonRelease-1>", self._v3_release)
        c.bind("<Motion>", self._v3_hover)
        c.bind("<Double-Button-1>", lambda e: self.v3_view(120, 28, 1.0))
        c.bind("<MouseWheel>", lambda e: self._v3_zoom(1 if e.delta > 0 else -1))
        c.bind("<Button-4>", lambda e: self._v3_zoom(1))
        c.bind("<Button-5>", lambda e: self._v3_zoom(-1))

    def _shop_view_show(self):
        """Shows the stage view that fits: the Stock comparison while the Stock tool is open, else 3D or Top &
        bottom as chosen.
        """
        if not hasattr(self, "_shop_flat"):
            return
        v = self.shop_view.get()
        for val, t in self._shop_view_btns.items():
            t.set(kind="on" if val == v else "ink")
        if self.shop_tool.get() == "stock":              # the Stock tool fills the stage with the comparison
            self._shop_flat.pack_forget()
            self._shop_3d.pack_forget()
            self._shop_views_frame.grid_remove()
            self._shop_cmp.pack(fill="both", expand=True)
            self._shop_hint.config(text=_("Your deck now, next to the stock saved for it"))
            self._shop_draw_stock()
            return
        self._shop_cmp.pack_forget()
        if self.tab_var.get() != "decor":
            self._shop_views_frame.grid()
        if v == "3d":
            self._shop_flat.pack_forget()
            self._shop_3d.pack(fill="both", expand=True)
            self._shop_hint.config(text=_("Drag to turn · scroll to zoom · click a part to paint it"))
            self.v3_schedule()
        else:
            self._shop_3d.pack_forget()
            self._shop_flat.pack(fill="both", expand=True)
            self._shop_hint.config(text=_("Click a part of the deck to paint it"))
            self._shop_draw_decks()

    def _shop_dock_light(self, active):
        """Lights the active tool's tag in the dock."""
        for val, t in self._shop_tool_btns.items():
            t.set(kind="on" if val == active else "ink")

    def _shop_dock(self, tool):
        """A dock tool other than Stickers: back from decorating (if needed), then that tool's sheet."""
        if self.tab_var.get() == "decor":
            self.tab_var.set("boards")
            self.switch_tab()
        self._shop_tool_set(tool)

    def _shop_switch_tab(self):
        """switch_tab for the Skate shop layout: Decorate is a mode of the Bench, not a page."""
        if hasattr(self, "_shop_settings_close"):
            self._shop_settings_close()                 # a tab tag closes the Settings page
        tab = self.tab_var.get()
        if tab == "speed":
            self.board_view.pack_forget()
            self.speed_view.pack(fill="both", expand=True)
            self.sm_refresh()
        else:
            self.speed_view.pack_forget()
            self.board_view.pack(fill="both", expand=True)
            if tab == "decor" and getattr(self, "shop_page", "") != "bench":
                self.shop_show("bench")                   # applies the mode
            else:
                self._shop_mode_apply()
        self._fit_path()
        base.root.minsize(1180 if tab == "decor" else 1100, 640)
        self._shop_bars()

    def _shop_mode_apply(self):
        """Shows the Bench's normal content or the decorating view, for the current tab."""
        if not hasattr(self, "_shop_bench_group") or getattr(self, "shop_page", "") != "bench":
            return
        dec = self.tab_var.get() == "decor"
        if dec:
            self._shop_bench_group.pack_forget()
            self._shop_decor_holder.pack(fill="both", expand=True)
            self.shop_dirty_lbl.pack_forget()
            self._shop_views_frame.grid_remove()          # Advanced has its own view controls
            self._shop_hint.grid_remove()
            self._shop_dc_tools.pack(side="left")
            self._shop_dock_light("stickers")
            # while the window is being (re)built Decorate's widgets don't exist yet (or are the old,
            # destroyed ones); the build's final switch_tab enters decorating again
            if getattr(self, "decor_view", None) is self._shop_decor_holder:
                self.dc_enter()
        else:
            self._shop_decor_holder.pack_forget()
            self._shop_dc_tools.pack_forget()
            self._shop_views_frame.grid()
            self._shop_hint.grid()
            self.shop_dirty_lbl.pack(side="left")
            self._shop_bench_group.pack(fill="both", expand=True)
            self._shop_tool_set(self.shop_tool.get() if self.shop_tool.get() in self._shop_sheets else "general")
            self._shop_view_show()
            self._shop_refresh()

    def _shop_tool_set(self, tool):
        """Shows a dock tool's sheet. Artwork, Paint and Thumbnail are sections of General: asking
        for one shows General scrolled to it."""
        section = tool if tool in SECTIONS else None
        tool = "general" if section else tool
        if tool not in self._shop_sheets:
            tool = "general"
        self.shop_tool.set(tool)
        self._shop_dock_light(tool)
        for val, f in self._shop_sheets.items():
            if val != tool:
                f.pack_forget()
        self._shop_sheets[tool].pack(fill="both", expand=True, padx=22, pady=20)
        bar = getattr(self, "_shop_bench_bar", None)
        if bar is not None and bar.winfo_exists():
            if tool == "stock":                        # nothing to save or revert on the Stock sheet
                bar.pack_forget()
            elif not bar.winfo_ismapped():
                bar.pack(side="bottom", fill="x", before=self._shop_bench_body)
        sc = getattr(self, "_shop_sheet_scroll", None)
        if sc is not None:
            if section:
                base.root.after_idle(lambda: self._shop_scroll_to(self._shop_sec[section]))
            else:
                sc.canvas.yview_moveto(0)
        if getattr(self, "_shop_cmp", None) is not None and self.tab_var.get() != "decor":
            self._shop_view_show()

    def _shop_scroll_to(self, frame):
        """Scrolls the tool sheet so `frame` (a section) is at the top."""
        sc = self._shop_sheet_scroll
        try:
            sc.update_idletasks()
            total = max(1, sc.inner.winfo_height())
            y = frame.winfo_rooty() - sc.inner.winfo_rooty() - 12
            if total > sc.canvas.winfo_height():
                sc.canvas.yview_moveto(max(0.0, y / total))
        except tk.TclError:
            pass

    # -- the two flat decks --
    def _shop_deck_box(self, cv):
        """(x0, y0, w, h) of a deck drawn as large as the canvas allows (deck ratio about 1 : 4)."""
        W, H = cv.winfo_width(), cv.winfo_height()
        h = max(60, H - 16)
        w = max(20, round(h * 0.25))
        if w > W - 20:
            w = max(20, W - 20)
            h = round(w * 4)
        return (W - w) // 2, (H - h) // 2, w, h

    def _shop_deck_photo(self, slot, img, edge, w, h, extra=None):
        """Photo of an upright deck (art turned upright, rounded, coloured edge, soft shadow), cached
        per drawing slot; (photo, padding around the deck)."""
        cache = self.__dict__.setdefault("_shop_photos", {})
        key = (id(img), w, h, edge, C["bg"] if slot != "stock" else C["panel"], extra)
        ent = cache.get(slot)
        if ent is None or ent[0] != key:
            bg = C["panel"] if slot.startswith("stock") else C["bg"]
            pil, pad = self._wall_deck_image(img, edge, w, h, bg, shadow=True)
            ent = cache[slot] = (key, ImageTk.PhotoImage(pil), pad)
        return ent[1], ent[2]

    def _shop_paint_top(self, cv, img, pal, box, slot, extra=None):
        """Draws a deck's top (its artwork upright) in `box` on a canvas."""
        x0, y0, w, h = box
        photo, p = self._shop_deck_photo(slot, img, pal[0], w, h, extra)
        cv.create_image(x0 - p, y0 - p, image=photo, anchor="nw")
        if img is None:
            cv.create_text(x0 + w / 2, y0 + h / 2, text=_("No image"), fill=C["muted"], font=F["small"])

    def _shop_paint_bottom(self, cv, pal, box, slot, clickable=False):
        """The underside: the same deck shape as the top (filled with the underside colour), with the
        trucks and wheels in the board's colours on top."""
        x0, y0, w, h = box
        under = self.__dict__.setdefault("_shop_under", {})
        if under.get(slot, (None,))[0] != pal[1]:
            under[slot] = (pal[1], Image.new("RGBA", (8, 8), _rgb(pal[1])))
        photo, p = self._shop_deck_photo(slot, under[slot][1], pal[0], w, h, pal[1])
        cv.create_image(x0 - p, y0 - p, image=photo, anchor="nw", tags=("deckimg",))
        tags = (lambda k: ("part", f"part{k}")) if clickable else (lambda k: ())
        for fy in (0.27, 0.73):
            ty = y0 + h * fy
            bw, bh = w * 0.42, h * 0.07
            cv.create_rectangle(x0 + w / 2 - bw / 2, ty - bh / 2, x0 + w / 2 + bw / 2, ty + bh / 2,
                                fill=pal[3], outline=ink(), width=1, tags=tags(3))
            ah = max(4, h * 0.022)
            cv.create_rectangle(x0 - w * 0.12, ty - ah / 2, x0 + w * 1.12, ty + ah / 2,
                                fill=pal[3], outline=ink(), width=1, tags=tags(3))
            ww, wh = w * 0.2, h * 0.075
            for wx in (x0 - w * 0.22, x0 + w * 1.02):
                cv.create_rectangle(wx, ty - wh / 2, wx + ww, ty + wh / 2, fill=pal[2], outline=ink(),
                                    width=2, tags=tags(2))

    @staticmethod
    def _shop_edge_hit(box, x, y):
        """None outside the deck, True on its coloured edge, False inside."""
        x0, y0, w, h = box
        if not (x0 <= x <= x0 + w and y0 <= y <= y0 + h):
            return None
        E = max(3, w // 14) + 2
        r = w / 2
        cx = x0 + r
        cy = min(max(y, y0 + r), y0 + h - r)            # nearest point on the deck's centre line
        d = ((x - cx) ** 2 + (y - cy) ** 2) ** 0.5
        if d > r:
            return None                                 # outside the rounded ends
        return d > r - E

    def _shop_draw_decks(self):
        """Draws the Top & bottom view: the top with the artwork (and unsaved stickers), the bottom with its
        colours, trucks and wheels; every part can be clicked to paint it.
        """
        if self.layout != "shop" or not hasattr(self, "_shop_cv") or getattr(self, "shop_page", "") != "bench":
            return
        if self.shop_view.get() != "flat":
            return
        pal = [to_hex(c) for c in self.pal] if self.pal else [C["btnb"], C["btn"], C["btn"], C["btnb"]]
        # top: the texture upright inside the deck (with stickers that are not written yet)
        cv = self._shop_cv["top"]
        cv.delete("all")
        box = self._shop_top_box = self._shop_deck_box(cv)
        img = self.tex.img if self.tex is not None else (self.thumb.img if self.thumb is not None else None)
        ds = self._shop_dc_session()
        if ds is not None:
            img = ds.work
        self._shop_paint_top(cv, img, pal, box, "top", ds is not None and ds.sig())
        # bottom: the same shape, underside, trucks and wheels; every part is clickable
        cv = self._shop_cv["bottom"]
        cv.delete("all")
        box = self._shop_bottom_box = self._shop_deck_box(cv)
        self._shop_paint_bottom(cv, pal, box, "bottom", clickable=True)
        for k in (2, 3):
            cv.tag_bind(f"part{k}", "<Button-1>", lambda e, k=k: self._shop_paint_part(k))
        cv.tag_bind("part", "<Enter>", lambda e: cv.config(cursor="hand2"))
        cv.tag_bind("part", "<Leave>", lambda e: cv.config(cursor=""))
        cv.tag_bind("deckimg", "<Button-1>", self._shop_bottom_click)
        cv.tag_bind("deckimg", "<Enter>", lambda e: cv.config(cursor="hand2"))
        cv.tag_bind("deckimg", "<Leave>", lambda e: cv.config(cursor=""))
        if self.pal is None:
            x0, y0, w, h = box
            cv.create_text(x0 + w / 2, y0 + h / 2, text=_("No colors"), fill=C["muted"], font=F["small"])

    def _shop_bottom_click(self, e):
        """Click on the bottom deck: its edge paints the border, the inside the underside."""
        hit = self._shop_edge_hit(getattr(self, "_shop_bottom_box", (0, 0, 0, 0)), e.x, e.y)
        if hit is not None:
            self._shop_paint_part(0 if hit else 1)

    def _shop_stock_info(self):
        """(meta, stock image, stock palette as hex) for the deck on the bench; meta None = no stock."""
        path = self.tex_path if not self.custom else None
        from ..defaults import load_default_image, load_default_meta
        meta = load_default_meta(path) if path else None
        if not meta:
            return None, None, None
        key = (str(path), meta.get("saved_at"))
        if getattr(self, "_shop_stock_key", None) != key:
            try:
                self._shop_stock_img = load_default_image(path)
            except Exception:
                self._shop_stock_img = None
            self._shop_stock_key = key
            self._shop_stock_diffkey = None
        img = self._shop_stock_img
        from ..boards import read_palette
        spal = read_palette(img) if img is not None else None
        return meta, img, ([to_hex(c) for c in spal] if spal else None)

    def _shop_stock_diffs(self, img, spal):
        """What differs between the deck now and its stock: [(kind, slot or None, now hex, was hex)]."""
        out = []
        pal = [to_hex(c) for c in self.pal] if self.pal else None
        if pal and spal:
            for k in range(4):
                if pal[k].lower() != spal[k].lower():
                    out.append(("color", k, pal[k], spal[k]))
        now = self.tex.img if self.tex is not None else None
        if now is not None and img is not None:
            key = (id(now), id(img))
            if getattr(self, "_shop_stock_diffkey", None) != key:
                try:
                    a = now.convert("RGB").resize((96, 24))
                    b = img.convert("RGB").resize((96, 24))
                    from PIL import ImageChops, ImageStat
                    d = sum(ImageStat.Stat(ImageChops.difference(a, b)).mean) / 3
                except Exception:
                    d = 0
                self._shop_stock_diffkey, self._shop_stock_artdiff = key, d > 4
            if self._shop_stock_artdiff:
                out.insert(0, ("art", None, None, None))
        return out

    def _shop_draw_stock(self):
        """The Stock tool's stage: the deck now and its stock, top and bottom, side by side; 'Show what
        changed' outlines the parts that differ; the chips below list them."""
        cv = getattr(self, "_shop_cmp_cv", None)
        if cv is None or not cv.winfo_exists() or self.shop_tool.get() != "stock":
            return
        self._shop_stock_for = self.tex_path        # (tests read which deck the drawing belongs to)
        cv.delete("all")
        for w in self._shop_cmp_chips.winfo_children():
            w.destroy()
        W, H = max(300, cv.winfo_width()), max(200, cv.winfo_height())
        meta, img, spal = self._shop_stock_info()
        set_state([self.b_all_revert], bool(meta))
        if not meta:
            self._shop_cmp_tag.config(text="", bg=C["bg"])
            cv.create_text(W / 2, H / 2, text=_("No stock saved for this deck yet. Save one with "
                                                "\u201cSave as stock\u2026\u201d on the right."),
                           fill=C["muted"], font=F["body"], width=W - 80)
            return
        loading = bool(getattr(self, "_loading", False))      # the deck's own colours are not in yet
        diffs = [] if loading else self._shop_stock_diffs(img, spal)
        n = len(diffs)
        if loading:
            self._shop_cmp_tag.config(text="…", bg=C["btn"], fg=C["muted"])
        elif n:
            self._shop_cmp_tag.config(text=_n("{n} difference", "{n} differences", n).upper(),
                                      bg=C["warnbg"], fg=C["warn"])
        else:
            self._shop_cmp_tag.config(text=_("Same as stock").upper(), bg=C["okbg"], fg=C["okfg"])
        pal = [to_hex(c) for c in self.pal] if self.pal else [C["btnb"], C["btn"], C["btn"], C["btnb"]]
        now = self.tex.img if self.tex is not None else None
        P, gap = C["panel"], 24
        pw = (W - gap) / 2
        show = self._shop_cmp_mode.get() == "diff"
        art_changed = any(d[0] == "art" for d in diffs) or any(d[1] == 0 for d in diffs if d[0] == "color")
        under_changed = any(d[0] == "color" and d[1] in (0, 1, 2, 3) for d in diffs)
        saved = str(meta.get("saved_at", ""))[:10]
        for col, (tag, sub, ipal, iimg) in enumerate(((_("Now"), _("what the game shows"), pal, now),
                                                      (_("Stock"), _("saved {date}", date=saved), spal or pal, img))):
            x0 = col * (pw + gap)
            cv.create_rectangle(x0, 0, x0 + pw, H - 1, fill=P, outline=C["border"], width=2)
            tid = cv.create_text(x0 + 18, 22, text=tag.upper(), anchor="w", font=F["displaysm"],
                                 fill=onink() if col == 0 else C["okfg"])
            bx0, by0, bx1, by1 = cv.bbox(tid)
            r = cv.create_rectangle(bx0 - 6, by0 - 2, bx1 + 6, by1 + 2, fill=ink() if col == 0 else C["okbg"],
                                    outline="")
            cv.tag_lower(r, tid)
            cv.create_text(bx1 + 14, 22, text=sub, anchor="w", font=F["small"], fill=C["muted"])
            h = max(80, H - 96)
            w = max(16, round(h * 0.25))
            if w * 2 + 60 > pw - 40:
                w = max(16, int((pw - 100) / 2))
                h = w * 4
            y = 48 + (H - 48 - 30 - h) / 2
            xt = x0 + pw / 2 - 30 - w
            xb = x0 + pw / 2 + 30
            slot = "stocknow" if col == 0 else "stockold"
            if col == 0 and loading:
                cv.create_text(x0 + pw / 2, y + h / 2, text=_("Loading…"), fill=C["muted"], font=F["body"])
                continue
            self._shop_paint_top(cv, iimg, ipal, (int(xt), int(y), w, h), slot + "_top")
            self._shop_paint_bottom(cv, ipal, (int(xb), int(y), w, h), slot + "_bottom")
            for x, cap in ((xt, _("Top")), (xb, _("Bottom"))):
                cv.create_text(x + w / 2, y + h + 16, text=cap.upper(), font=F["displaytiny"], fill=C["muted"])
            if show and col == 0:
                for flag, x, cap in ((art_changed, xt, _("Artwork / border")), (under_changed, xb, _("Colors"))):
                    if flag:
                        cv.create_rectangle(x - 12, y - 10, x + w + 12, y + h + 6, outline=C["accent"], width=3,
                                            dash=(8, 5))
                        t2 = cv.create_text(x + w / 2, y - 18, text=cap.upper(), font=F["displaytiny"],
                                            fill=C["onaccent"])
                        b0, b1_, b2, b3 = cv.bbox(t2)
                        rr = cv.create_rectangle(b0 - 4, b1_ - 1, b2 + 4, b3 + 1, fill=C["accent"], outline="")
                        cv.tag_lower(rr, t2)
        # the chips: one per difference
        names = [_(nm) for _k, nm in PALETTE_SLOTS]
        for kind, k, now_hex, was in diffs:
            chip = tk.Frame(self._shop_cmp_chips, bg=C["btn"], highlightthickness=2, highlightbackground=C["border"])
            chip.pack(side="left", padx=(0, 8))
            sw = tk.Frame(chip, width=14, height=14, bg=now_hex if kind == "color" else C["accent"])
            sw.pack(side="left", padx=(8, 6), pady=6)
            text = (_("{part} · was {hex}", part=names[k], hex=was) if kind == "color"
                    else _("The artwork differs from stock"))
            tk.Label(chip, text=text, font=F["small"], fg=C["text"], bg=C["btn"]).pack(side="left", padx=(0, 8))
        if not diffs and not loading:
            label(self._shop_cmp_chips, _("Nothing to put back: the deck matches its stock."), "small", "okfg",
                  bg=C["bg"]).pack(side="left")

    def _shop_revert_all(self):
        """Puts the texture and the thumbnail back to stock with one question."""
        from tkinter import messagebox
        from ..defaults import load_default_meta, revert_to_default
        from ..caches import TEXCACHE
        paths = [p for p in (self.tex_path, self.thumb_path) if p is not None and load_default_meta(p)]
        if not paths:
            return
        meta = load_default_meta(paths[0])
        if not messagebox.askyesno(_("Put the whole deck back to stock"),
                                   _("Put {name} back to the stock saved on {saved_at}?\n\nThe texture and the "
                                     "thumbnail are replaced; your current version is overwritten.",
                                     name=paths[0].stem, saved_at=str(meta.get("saved_at", ""))[:16])):
            return
        self.pal = None
        self.busy(True)
        try:
            for p in paths:
                revert_to_default(p)
                TEXCACHE.invalidate(p)
        except Exception as e:
            messagebox.showerror(_("Revert failed"), str(e))
            return
        finally:
            self.busy(False)
        self._load_current(sync=True)
        self.set_status(_("Deck {name} is stock again", name=paths[0].stem))

    def _shop_dc_session(self):
        """The current deck's decorating session when it has unsaved work in memory, else None."""
        s = getattr(self, "dc_sessions", {}).get(self.tex_path) if self.tex_path else None
        if s is None or not s.dirty() or getattr(s, "work", None) is None:
            return None
        return s

    def _shop_top_click(self, e):
        """Click on the top deck: its edge paints the border, the inside opens the Artwork section."""
        hit = self._shop_edge_hit(getattr(self, "_shop_top_box", (0, 0, 0, 0)), e.x, e.y)
        if hit is True:
            self._shop_paint_part(0)
        elif hit is False:
            self._shop_tool_set("art")

    def _shop_paint_part(self, k):
        """Opens the Paint section on colour slot k and its colour picker."""
        self._shop_part = k
        self._shop_tool_set("paint")
        self._shop_paint_rows()
        self.pick_color(k)

    # -- tool sheets --
    def _sheet_head_inline(self, parent, title, sub=""):
        """A sheet section's head on one line: the title, then a short note; returns the note label."""
        row = tk.Frame(parent, bg=C["panel"])
        row.pack(fill="x", pady=(0, 8))
        tk.Label(row, text=_(title).upper(), font=F["display"], fg=ink(), bg=C["panel"]).pack(side="left")
        note = label(row, _(sub) if sub else "", "small", "muted", bg=C["panel"])
        note.pack(side="left", padx=(12, 0), pady=(4, 0))
        return note

    def _sheet_head(self, parent, title, sub, font="display"):
        """A sheet's title with a wrapping explanation under it."""
        tk.Label(parent, text=_(title).upper(), font=F[font], fg=ink(), bg=C["panel"], anchor="w").pack(fill="x")
        s = label(parent, _(sub), "small", "sub", anchor="w", justify="left", bg=C["panel"])
        s.pack(fill="x", pady=(2, 14))
        s.bind("<Configure>", lambda e: s.config(wraplength=max(120, e.width - 4)))

    def _shop_build_sheets(self, parent):
        """Builds the tool sheets: General (Artwork, Paint, Thumbnail sections) and Stock (facts and the ways
        back).
        """
        P = C["panel"]
        self._shop_sheets = {}
        self._shop_part = self._keep.get("shop_part", 2)

        # General: Artwork, Paint and Thumbnail, one after another on one sheet
        gen = tk.Frame(parent, bg=P)
        self._shop_sec = {}

        def section(key, first=False):
            """A new section of the General sheet (with a separator above it)."""
            if not first:
                tk.Frame(gen, bg=C["border"], height=2).pack(fill="x", pady=(14, 12))
            f = tk.Frame(gen, bg=P)
            f.pack(fill="x")
            self._shop_sec[key] = f
            return f

        # Artwork: the head carries the file, the picture, then Replace / Export / Open on one row
        pg = section("art", first=True)
        self.tex_file = self._sheet_head_inline(pg, N_("Artwork"))
        self.tex_chips = tk.Frame(pg, bg=P)
        self.tex_chips._compact = True
        self.tex_chips.pack(fill="x", pady=(0, 6))
        self.tex_prev = Preview(pg, 432 / 1920, 92, on_drop=lambda f: self.replace("tex", f))
        self.tex_prev.pack(fill="x")
        self.b_tex_replace = button(pg, _("↑  Replace image…"), lambda: self.replace("tex"), "primary")
        self.b_tex_replace.pack(fill="x", pady=(10, 0))
        row = tk.Frame(pg, bg=P)
        row.pack(fill="x", pady=(6, 0))
        self.b_tex_export = button(row, _("Export PNG…"), lambda: self.export("tex"), small=True)
        self.b_tex_export.pack(side="left")
        button(row, _("Open other .xnb…"), self.open_other, "ghost", small=True).pack(side="left", padx=(6, 0))
        self.keep_pal = tk.BooleanVar(value=self._keep.get("keep_pal", True))
        tk.Checkbutton(pg, text=_("Keep these colors when replacing the texture image"), variable=self.keep_pal,
                       bg=P, fg=C["sub"], activebackground=P, activeforeground=C["text"], selectcolor=C["bg"],
                       font=F["small"], bd=0, highlightthickness=0, cursor="hand2", anchor="w",
                       wraplength=340, justify="left").pack(fill="x", pady=(8, 0))

        # Paint
        pg = section("paint")
        self._sheet_head_inline(pg, N_("Paint"), N_("pick a part, then a color"))
        # the four colors side by side: swatch, name, hex code (and what it was, once changed)
        self.pal_widgets, self._shop_rows = [], []
        grid = tk.Frame(pg, bg=P)
        grid.pack(fill="x")
        for i, (_key, name) in enumerate(PALETTE_SLOTS):
            grid.columnconfigure(i, weight=1, uniform="paint")
            cell = tk.Frame(grid, bg=C["bg"], highlightthickness=2, highlightbackground=C["bg"], cursor="hand2")
            cell.grid(row=0, column=i, sticky="nsew", padx=(0 if i == 0 else 5, 0))
            sw = tk.Canvas(cell, width=70, height=28, bg=C["btn"], highlightthickness=1,
                           highlightbackground=C["btnb"], cursor="hand2")
            sw.pack(padx=6, pady=(6, 3), fill="x")
            sw.bind("<Button-1>", lambda e, i=i: (self._shop_part_set(i), self.pick_color(i)))
            nm = label(cell, _(name), "smallbold", bg=C["bg"])
            nm.pack()
            var = tk.StringVar()
            ent = tk.Entry(cell, textvariable=var, width=8, bg=C["panel"], fg=C["text"], insertbackground=C["text"],
                           relief="flat", bd=0, font=F["mono"], highlightthickness=1, justify="center",
                           highlightbackground=C["btnb"], highlightcolor=C["accent"], disabledbackground=C["bg"])
            ent.pack(padx=6, pady=(2, 2), ipady=1)
            ent.bind("<Return>", lambda e, i=i: self.commit_color(i))
            ent.bind("<FocusOut>", lambda e, i=i: self.commit_color(i))
            ent.bind("<FocusIn>", lambda e, i=i: self._shop_part_set(i), add="+")
            was = label(cell, "", "small", "muted", bg=C["bg"])
            was.pack(pady=(0, 3))
            for w in (cell, nm, was):
                w.bind("<Button-1>", lambda e, i=i: self._shop_part_set(i))
            self.pal_widgets.append((sw, var, ent, was))
            self._shop_rows.append((cell, [cell, nm, was]))
        row = tk.Frame(pg, bg=P)
        row.pack(fill="x", pady=(6, 6))
        self.pal_state = label(row, "", "small", "muted", anchor="w", bg=P)
        self.pal_state.pack(side="left")
        self.b_pal_paste = button(row, _("Paste"), self.paste_colors, "ghost", small=True)
        self.b_pal_paste.pack(side="right")
        self.b_pal_copy = button(row, _("Copy"), self.copy_colors, "ghost", small=True)
        self.b_pal_copy.pack(side="right", padx=(0, 6))
        self._shop_sugg_title = label(pg, "", "smallbold", "text", anchor="w", bg=P)
        self._shop_sugg_title.pack(fill="x")
        self._shop_sugg = tk.Canvas(pg, height=40, bg=P, highlightthickness=0)
        self._shop_sugg.pack(fill="x", pady=(6, 0))
        self._shop_sugg.bind("<Configure>", lambda e: self._shop_draw_sugg())
        self._shop_sugg_cols, self._shop_sugg_for = [], None

        # Thumbnail: the picture on the left, what it is and its buttons on the right
        pg = section("thumb")
        self.thumb_file = self._sheet_head_inline(pg, N_("Thumbnail"))
        self.thumb_chips = tk.Frame(pg, bg=P)
        self.thumb_chips._compact = True
        self.thumb_chips.pack(fill="x", pady=(0, 6))
        self.thumb_prev = Preview(pg, 144 / 640, 70, on_drop=lambda f: self.replace("thumb", f))
        self.thumb_prev.pack(fill="x")
        label(pg, _("The small picture the game shows in the board shop."), "small", "muted", anchor="w",
              bg=P).pack(fill="x", pady=(6, 0))
        row = tk.Frame(pg, bg=P)
        row.pack(fill="x", pady=(8, 0))
        self.b_th_gen = button(row, _("Generate from texture"), self.generate_thumb, "primary", small=True)
        self.b_th_gen.pack(side="left", fill="x", expand=True)
        self.b_th_replace = button(row, _("Replace…"), lambda: self.replace("thumb"), small=True)
        self.b_th_replace.pack(side="left", padx=(6, 0))
        self.b_th_export = button(row, _("Export PNG…"), lambda: self.export("thumb"), small=True)
        self.b_th_export.pack(side="left", padx=(6, 0))
        self._shop_sheets["general"] = gen

        # Stock: what was saved and the ways back (the stage shows the deck against its stock)
        pg = tk.Frame(parent, bg=P)
        self._sheet_head(pg, N_("Stock"), N_("Stock is the board as you first saved it. Put it back any time; "
                                             "the tool restores the saved pixels exactly."))
        grid = tk.Frame(pg, bg=P)
        grid.pack(fill="x")
        grid.columnconfigure(0, weight=1, uniform="d")
        grid.columnconfigure(1, weight=1, uniform="d")
        self.def_vals = {}
        for i, (key, cap) in enumerate((("saved", N_("Saved")), ("tex", N_("Texture stored as")),
                                        ("thumb", N_("Thumbnail stored as")), ("bak", N_("Backup (.bak)")))):
            cell = tk.Frame(grid, bg=P)
            cell.grid(row=i // 2, column=i % 2, sticky="w", pady=(0, 12))
            label(cell, _(cap), "small", "muted", bg=P).pack(anchor="w")
            v = label(cell, "—", "bold", bg=P)
            v.pack(anchor="w")
            self.def_vals[key] = v
        tk.Frame(pg, bg=C["border"], height=2).pack(fill="x", pady=(4, 14))
        self.b_all_revert = button(pg, _("Put the whole deck back to stock"), self._shop_revert_all, "primary")
        self.b_all_revert.pack(fill="x")
        self.b_tex_revert = button(pg, _("Only the texture"), lambda: self.revert("tex"))
        self.b_tex_revert.pack(fill="x", pady=(8, 0))
        self.b_th_revert = button(pg, _("Only the thumbnail"), lambda: self.revert("thumb"))
        self.b_th_revert.pack(fill="x", pady=(8, 0))
        box = tk.Frame(pg, bg=P, highlightthickness=2, highlightbackground=C["btnb"])
        box.pack(fill="x", pady=(24, 0))
        tk.Label(box, text=_("Make this the new stock").upper(), font=F["displaysm"], fg=ink(), bg=P,
                 anchor="w").pack(fill="x", padx=12, pady=(10, 2))
        note = label(box, _("Keeps the deck as it is now as the version you go back to. The old stock is "
                            "replaced."), "small", "sub", anchor="w", justify="left", bg=P)
        note.pack(fill="x", padx=12)
        note.bind("<Configure>", lambda e: note.config(wraplength=max(120, e.width - 4)))
        more, (self.b_tex_setdef, self.b_th_setdef) = more_button(box, [
            (N_("Save the current texture as stock"), lambda: self.set_default("tex")),
            (N_("Save the current thumbnail as stock"), lambda: self.set_default("thumb"))], small=False)
        more.config(text=_("Save as stock…"))
        more.pack(anchor="w", padx=12, pady=(8, 12))
        label(pg, _("Stock copies live in _board_defaults next to the board files."), "small", "muted",
              anchor="w", justify="left", wraplength=340, bg=P).pack(fill="x", pady=(14, 0))
        self._shop_sheets["stock"] = pg

        self._shop_tool_set(self.shop_tool.get() if self.shop_tool.get() in self._shop_sheets else "general")
        self._shop_paint_rows()

    def _shop_part_set(self, k):
        """Makes colour slot k the one the artwork colours paint."""
        self._shop_part = k
        self._shop_paint_rows()
        self._shop_draw_sugg()

    def _shop_paint_rows(self):
        """Outlines the chosen colour slot."""
        for k, (rowf, parts) in enumerate(getattr(self, "_shop_rows", [])):
            rowf.config(highlightbackground=C["accent"] if k == getattr(self, "_shop_part", 2) else C["bg"])

    def _shop_draw_sugg(self):
        """Round chips with the artwork's main colors; a click paints the chosen part with it."""
        cv = getattr(self, "_shop_sugg", None)
        if cv is None:
            return
        img = self.tex.img if self.tex is not None else None
        if img is not None and self._shop_sugg_for != id(img):
            try:
                from ..colorsuggest import art_colors
                self._shop_sugg_cols = [c for c, _share in art_colors(img, n=8)][:8]
            except Exception:
                self._shop_sugg_cols = []
            self._shop_sugg_for = id(img)
        elif img is None:
            self._shop_sugg_cols, self._shop_sugg_for = [], None
        part = _(PALETTE_SLOTS[getattr(self, "_shop_part", 2)][1]).lower()
        self._shop_sugg_title.config(text=_("From your artwork, for the {part}", part=part)
                                     if self._shop_sugg_cols else "")
        cv.delete("all")
        d, gap = 34, 8
        for k, col in enumerate(self._shop_sugg_cols):
            x = k * (d + gap)
            tag = f"s{k}"
            cv.create_oval(x + 2, 2, x + d, d, fill=to_hex(col), outline=ink(), width=2, tags=(tag,))
            cv.tag_bind(tag, "<Button-1>", lambda e, c=col: self._shop_use_color(c))
            cv.tag_bind(tag, "<Enter>", lambda e: cv.config(cursor="hand2"))
            cv.tag_bind(tag, "<Leave>", lambda e: cv.config(cursor=""))

    def _shop_use_color(self, col):
        """A colour from the artwork was clicked: paints the chosen slot with it."""
        if self.pal is None:
            return
        self.pal[self._shop_part] = tuple(col[:3])
        self._draw_palette()

    # ------------------------------------------------------------------ the deck fan
    # Every deck hangs on a long arm from a point far above the header's line and the arms spread
    # like a hand of cards. The deck on the bench hangs straight down, whole; the others are pulled
    # up so only their lower half shows below the line. The next decks sit to the right.
    CAR_H = 94                  # canvas height
    CAR_W, CAR_HH = 22, 86      # a deck standing up
    CAR_ARM = 11.0              # the pivot is this many deck lengths above the line
    CAR_STEP = 2.6              # degrees between two decks
    CAR_K = 10                  # decks drawn on each side
    CAR_PEEK = 14               # a hovered deck comes down this much more

    def _car_init(self):
        """Sets up the deck fan's state and its mouse bindings (hover, click, wheel)."""
        cv = self._car_cv
        self._car_pos = None            # where the fan is (an index into the shown decks; animates, wraps)
        self._car_job = None
        self._car_hover = None
        self._car_photos = getattr(self, "_car_photos", {})
        self._car_bases = getattr(self, "_car_bases", {})
        self._car_wheel_t = 0.0
        self._car_vers = {}
        cv.bind("<Configure>", lambda e: self._car_draw())
        cv.bind("<Motion>", self._car_motion)
        cv.bind("<Leave>", lambda e: self._car_set_hover(None))
        cv.bind("<Button-1>", self._car_click)
        cv.bind("<MouseWheel>", lambda e: self._car_wheel(1 if e.delta < 0 else -1))
        cv.bind("<Button-4>", lambda e: self._car_wheel(-1))
        cv.bind("<Button-5>", lambda e: self._car_wheel(1))
        cv._own_wheel = True

    def _car_wheel(self, d):
        """Mouse wheel over the fan: one deck per notch (at most one every 70 ms)."""
        import time
        now = time.monotonic()
        if now - self._car_wheel_t < 0.07:              # one deck per notch, even on fast wheels
            return
        self._car_wheel_t = now
        self.step(d)

    def _car_shown(self):
        """The decks in the fan: the Wall's filtered list, plus the deck on the bench where it belongs when
        the filter leaves it out (a 'guest': changing the filter never changes the deck on the bench)."""
        try:
            shown = [int(k) for k in self.tree.get_children()]
        except tk.TclError:
            return []
        if self.sel is not None and not self.custom and self.sel not in shown and self.sel < len(self.boards):
            import bisect
            bisect.insort(shown, self.sel)
        return shown

    def _car_guest(self):
        """True when the deck on the bench is left out by the filter (it shows in the fan as a guest)."""
        try:
            return self.sel is not None and not self.custom and not self.tree.exists(str(self.sel))
        except tk.TclError:
            return False

    # -- the filter swap: the whole fan lifts out of sight, the filter changes, the fan comes back down --
    CAR_SWAP_UP, CAR_SWAP_DOWN, CAR_SWAP_STAGGER = 0.26, 0.30, 0.018

    def _shop_filter_swap(self, key):
        """A filter tag on the Bench: lifts the fan out of sight, changes the filter, and lets it come back down
        (just changes the filter when the fan is not on screen).
        """
        cur = getattr(self, "_status_filter", None) or "all"
        cv = getattr(self, "_car_cv", None)
        if key == cur:
            return
        if cv is None or not cv.winfo_ismapped() or getattr(self, "_car_swap", None):
            return self._shop_set_filter(key)
        import time
        self._car_swap = ("up", time.monotonic(), key)
        self._car_swap_tick()

    def _car_swap_offset(self, ad):
        """How far (px) a deck ad places from the middle is lifted by the swap right now (0 = in place)."""
        sw = getattr(self, "_car_swap", None)
        if not sw:
            return 0.0
        import time
        phase, t0, _key = sw
        t = time.monotonic() - t0
        gone = self.CAR_HH + 30
        K = self.CAR_K
        if phase == "up":                                 # the outer decks go first
            u = (t - (K - min(ad, K)) * self.CAR_SWAP_STAGGER) / self.CAR_SWAP_UP
            u = max(0.0, min(1.0, u))
            return gone * u * u
        u = (t - min(ad, K) * self.CAR_SWAP_STAGGER) / self.CAR_SWAP_DOWN   # the middle comes back first
        u = max(0.0, min(1.0, u))
        return gone * (1 - (1 - (1 - u) ** 3))

    def _car_swap_tick(self):
        """One frame of the filter swap: when the fan is up, applies the filter; when it is down again, ends."""
        import time
        sw = getattr(self, "_car_swap", None)
        if not sw:
            return
        phase, t0, key = sw
        t = time.monotonic() - t0
        span = self.CAR_K * self.CAR_SWAP_STAGGER
        if phase == "up" and t >= self.CAR_SWAP_UP + span:
            self._car_swap = ("down", time.monotonic(), key)
            self._shop_set_filter(key)                    # the refreshed set, while the fan is out of sight
            self._car_pos = None                          # it comes back centred on the deck on the bench
        elif phase == "down" and t >= self.CAR_SWAP_DOWN + span:
            self._car_swap = None
            self._car_draw()
            return
        self._car_draw()
        base.root.after(16, self._car_swap_tick)

    def _car_target(self, shown):
        """Where the deck on the bench sits in the fan's list, or None."""
        if self.sel is not None and not self.custom and self.sel in shown:
            return float(shown.index(self.sel))
        return None

    @staticmethod
    def _car_wrap(d, n):
        """d as the shortest way round a ring of n decks (in -n/2 … n/2)."""
        d = d % n
        return d - n if d > n / 2 else d

    def _car_goto(self):
        """Turns the fan to the deck on the bench (a short eased turn, the short way round)."""
        cv = getattr(self, "_car_cv", None)
        if cv is None or not cv.winfo_exists():
            return
        self._car_vers = {}                           # the decks' pictures may have changed
        shown = self._car_shown()
        tgt = self._car_target(shown)
        if tgt is None or not shown:
            return self._car_draw()
        n = len(shown)
        if self._car_pos is None:
            self._car_pos = tgt
            return self._car_draw()
        delta = self._car_wrap(tgt - self._car_pos, n)
        if abs(delta) < 1e-6:
            return self._car_draw()
        if abs(delta) > 12:                               # far away: jump
            self._car_pos = tgt
            return self._car_draw()
        if self._car_job:
            base.root.after_cancel(self._car_job)
        import time
        start, t0 = self._car_pos, time.monotonic()

        def tick():
            """One frame of the fan's turn (eased over 0.26 s)."""
            u = min(1.0, (time.monotonic() - t0) / 0.26)
            e = 1 - (1 - u) ** 3
            self._car_pos = (start + delta * e) % n
            self._car_draw()
            self._car_job = base.root.after(16, tick) if u < 1 else None
        tick()

    def _car_base(self, i, w, h, ring):
        """A deck standing up: its art turned upright in a rounded board with its border colour."""
        src, ver = self._wall_src(i)
        pal = self.board_pal.get(i)
        edge = to_hex(pal[0]) if pal else C["btnb"]
        key = (i, ver, edge, w, h, ring, C["bg"])
        im = self._car_bases.get(key)
        if im is not None:
            return im
        if len(self._car_bases) > 300:
            self._car_bases.clear()
        pad = 4
        out = Image.new("RGBA", (w + 2 * pad, h + 2 * pad), (0, 0, 0, 0))
        E = max(2, w // 9)
        deck = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        m = Image.new("L", (w, h), 0)
        _rounded(ImageDraw.Draw(m), (0, 0, w - 1, h - 1), w // 2, fill=255)
        deck.paste(Image.new("RGBA", (w, h), _rgb(edge)), (0, 0), m)
        iw, ih = w - 2 * E, h - 2 * E
        if src is not None and iw > 4 and ih > 4:
            art = src.convert("RGBA").transpose(Image.ROTATE_90).resize((iw, ih), Image.LANCZOS)
            flat = Image.new("RGBA", (iw, ih), _rgb(C["chk1"]))
            flat.alpha_composite(art)
            mi = Image.new("L", (iw, ih), 0)
            _rounded(ImageDraw.Draw(mi), (0, 0, iw - 1, ih - 1), iw // 2, fill=255)
            deck.paste(flat, (E, E), mi)
        if ring:
            _rounded(ImageDraw.Draw(out), (0, 0, w + 2 * pad - 1, h + 2 * pad - 1), w // 2 + pad,
                     outline=_rgb(ring), width=3)
        out.alpha_composite(deck, (pad, pad))
        self._car_bases[key] = out
        return out

    def _car_image(self, i, w, h, ang, dim, ring):
        """The upright deck faded by dim and turned by ang degrees (clockwise on screen)."""
        ang = float(round(ang))                       # whole degrees, so a turn reuses its pictures
        dim = round(dim * 10) / 10
        ver = self._car_vers.get(i, False)
        if ver is False:                              # looked up once per refresh, not on every frame
            ver = self._car_vers[i] = self._wall_src(i)[1]
        pal = self.board_pal.get(i)
        key = (i, ver, pal[0] if pal else None, w, h, ang, dim, ring, C["bg"])
        ph = self._car_photos.get(key)
        if ph is not None:
            return ph
        if len(self._car_photos) > 900:
            for k in list(self._car_photos)[:300]:     # drop the oldest third
                del self._car_photos[k]
        im = self._car_base(i, w, h, ring)
        if dim > 0:                                   # decks far from the middle fade into the wall
            veil = Image.new("RGBA", im.size, _rgb(C["bg"], int(255 * dim)))
            a = im.getchannel("A")
            im = im.copy()
            im.alpha_composite(Image.composite(veil, Image.new("RGBA", im.size, (0, 0, 0, 0)), a))
        if ang:
            im = im.rotate(-ang, resample=Image.BICUBIC, expand=True)
        ph = ImageTk.PhotoImage(im)
        self._car_photos[key] = ph
        return ph

    def _car_place(self, W, d, lift):
        """(centre x, centre y, angle) of a deck d places from the middle, pulled up by lift pixels."""
        import math
        H = self.CAR_HH
        a = -d * self.CAR_STEP                        # the next decks (d > 0) swing out to the right
        r = math.radians(a)
        L = self.CAR_ARM * H + H / 2 - lift           # pivot → deck centre
        px, py = W / 2, -self.CAR_ARM * H
        return px - L * math.sin(r), py + L * math.cos(r), a

    def _car_draw(self):
        """Draws the fan: every deck within reach of the middle on its arm (the one on the bench hanging down, the
        others showing their lower half, a pointed-at one lower), the number tags, the guest outline and the
        counter.
        """
        import math
        cv = getattr(self, "_car_cv", None)
        if cv is None or not cv.winfo_exists():
            return
        cv.delete("all")
        W = cv.winfo_width()
        shown = self._car_shown()
        if W < 60 or not shown:
            return
        n = len(shown)
        if self._car_pos is None:
            t = self._car_target(shown)
            self._car_pos = t if t is not None else 0.0
        pos = self._car_pos
        cur = self.sel if not self.custom else None
        w, h = self.CAR_W, self.CAR_HH
        K = min(self.CAR_K, (n - 1) // 2) if n > 1 else 0
        items = []
        for k in range(n):
            d = self._car_wrap(k - pos, n)
            if abs(d) > K + 0.999:
                continue
            i = shown[k]
            on = i == cur
            hover = i == self._car_hover
            near = max(0.0, 1.0 - abs(d))             # 1 when the deck is in the middle (smooth while turning)
            lift = (h / 2) * (1 - near)                # the others hide their upper half above the line
            if hover and not on:
                lift = max(0.0, lift - self.CAR_PEEK)
            lift += self._car_swap_offset(abs(d))
            x, y, ang = self._car_place(W, d, lift)
            if x < -h or x > W + h:
                continue
            items.append((abs(d), d, k, i, on, hover, x, y, ang, lift))
        self._car_hits = []
        guest = self._car_guest()
        for ad, d, k, i, on, hover, x, y, ang, lift in sorted(items, key=lambda t: -t[0]):   # middle drawn last
            is_guest = guest and on
            dim = 0.45 if is_guest else 0.0 if on else min(0.65, 0.06 * ad)
            ring = None if is_guest else C["accent"] if (on or hover) else None
            ph = self._car_image(i, w, h, ang, dim, ring)
            cv.create_image(x, y, image=ph)
            if is_guest:                              # not in the filter: a dashed outline, it stays on the bench
                r = math.radians(ang)
                hw, hh = w / 2 + 5, h / 2 + 5
                pts = []
                for px, py in ((-hw, -hh), (hw, -hh), (hw, hh), (-hw, hh)):
                    pts += [x + px * math.cos(r) - py * math.sin(r), y + px * math.sin(r) + py * math.cos(r)]
                cv.create_polygon(*pts, outline=C["accent"], fill="", width=2, dash=(5, 3))
            self._car_hits.append((x, y, ang, i))
            if on or hover:                           # its number on a small tag at the tail
                r = math.radians(ang)
                tx, ty = x - (h / 2 - 12) * math.sin(r), y + (h / 2 - 12) * math.cos(r)
                name = self.boards[i].name
                num = name if len(name) > 2 or not name.isdigit() else name.zfill(2)
                tid = cv.create_text(tx, ty, text=num, font=F["displaytiny"],
                                     fill=C["onaccent"] if on else onink())
                bx0, by0, bx1, by1 = cv.bbox(tid)
                rid = cv.create_rectangle(bx0 - 4, by0 - 1, bx1 + 4, by1 + 1, fill=C["accent"] if on else ink(),
                                          outline="")
                cv.tag_lower(rid, tid)
        # where we are in the ring (or why the deck on the bench is outside the filter)
        if guest:
            name = self.boards[cur].name
            cv.create_text(W - 8, self.CAR_H - 4, anchor="se", font=F["small"], fill=C["warn"],
                           text=_("Deck {name} is not in this filter · it stays on the bench", name=name))
        elif cur is not None and cur in shown:
            cv.create_text(W - 8, self.CAR_H - 4, anchor="se", font=F["small"], fill=C["muted"],
                           text="{} / {}".format(shown.index(cur) + 1, n))

    def _car_at(self, ex, ey):
        """The deck under a point of the fan (tested in each deck's own turned frame, front ones first), or None.
        """
        import math
        if ey < 0:
            return None
        w, h = self.CAR_W + 4, self.CAR_HH + 4
        for x, y, ang, i in reversed(getattr(self, "_car_hits", [])):
            r = math.radians(ang)
            vx, vy = ex - x, ey - y
            lx = vx * math.cos(r) + vy * math.sin(r)      # into the deck's own frame
            ly = -vx * math.sin(r) + vy * math.cos(r)
            if abs(lx) <= w / 2 and abs(ly) <= h / 2:
                return i
        return None

    def _car_motion(self, e):
        """Pointer over the fan: hover on the deck under it."""
        self._car_set_hover(self._car_at(e.x, e.y))

    def _car_set_hover(self, i):
        """Hover on deck i: hand cursor, its name and status in the status bar, and it comes down a little."""
        if i == self._car_hover:
            return
        self._car_hover = i
        cv = self._car_cv
        cv.config(cursor="hand2" if i is not None else "")
        if i is not None:
            word, _col = self._wall_status(i)
            self.set_status(_("Deck {name} · {status} — click to put it on the bench",
                              name=self.boards[i].name, status=word))
        self._car_draw()

    def _car_click(self, e):
        """Click on a deck in the fan: puts it on the bench."""
        i = self._car_at(e.x, e.y)
        if i is not None and (i != self.sel or self.custom):
            self.select(i)

    # ------------------------------------------------------------------ refresh hooks
    def _shop_refresh(self):
        """Called after the panels or the colors changed (see App._refresh_panels / _draw_palette)."""
        if self.layout != "shop" or not hasattr(self, "shop_pages"):
            return
        tag = getattr(self, "_shop_deck_tag", None)
        if tag is not None:
            if self.custom and self.tex_path:
                tag.set_name(_("File").upper(), self.tex_path.stem)
            elif self.sel is not None:
                nm = self.boards[self.sel].name
                tag.set_name(_("Board").upper(), nm.zfill(2) if nm.isdigit() and len(nm) < 2 else nm)
            else:
                tag.set_name(_("Board").upper(), "—")
        st = None if self.custom else self.status.get(self.sel) if self.sel is not None else "hide"
        if self.sel is not None and not self.custom and st in STATUS_WORDS:
            fg, bg = {"def": (C["okfg"], C["okbg"]), "mod": (onink(), ink()),
                      "none": (C["warn"], C["warnbg"])}[st]
            self.badge.config(text=_(STATUS_WORDS[st]).upper(), fg=fg, bg=bg)
            self._shop_deck_tag.set(text=_(STATUS_WORDS[st]).upper(), kind="color", colors=(bg, fg))
        changed = self._pal_changed()
        if st not in STATUS_WORDS or self.sel is None or self.custom:
            self._shop_deck_tag.set(text="…", kind="color", colors=(C["btn"], C["muted"]))
        self.shop_dirty_lbl.config(text=("●  " + _n("{n} color not written yet", "{n} colors not written yet",
                                                     len(changed))) if changed else "")
        stickers = self.tex_path is not None and any(x.path == self.tex_path for x in self.dc_unsaved())
        if stickers and not changed:
            self.shop_bench_msg.config(text=_("The stickers on this deck are not written yet. Open Advanced to write "
                                              "them to the game."))
        elif changed:
            self.shop_bench_msg.config(text=_n("{n} color is only on screen. Save the board, or revert it.",
                                               "{n} colors are only on screen. Save the board, or revert them.",
                                               len(changed)))
        elif self.tex is not None:
            self.shop_bench_msg.config(text=_("Everything on this deck is in the game."))
        else:
            self.shop_bench_msg.config(text="")
        on = bool(changed) and self.tex is not None
        self.b_pal_apply.config(bg=C["accent"] if on else ink(), fg=C["onaccent"] if on else C["dis"],
                                highlightbackground=C["accent"] if on else C["dis"])
        self.b_pal_apply.bind("<Leave>", lambda e, b=self.b_pal_apply, on=on: b.config(bg=C["accent"] if on else ink()))
        self._shop_draw_decks()
        self._shop_draw_sugg()
        self._car_goto()
        if self.shop_tool.get() == "stock":
            self._shop_draw_stock()
        self._shop_bars()

    def _shop_bars(self):
        """The Wall's 'On the bench' bar and the header tabs."""
        self._shop_tabs_refresh()
        if not hasattr(self, "_wall_bar_msg"):
            return
        self._shop_chips_refresh()
        unsaved = self.dc_unsaved() if hasattr(self, "dc_sessions") else []
        changed = self._pal_changed() if self.sel is not None and not self.custom else []
        btn = self._wall_bar_btn
        btn.pack_forget()
        if unsaved:
            names = ", ".join(s.path.stem for s in unsaved[:6])
            self._wall_bar_msg.config(text=_n("{n} deck has stickers that are not saved yet: {names}",
                                              "{n} decks have stickers that are not saved yet: {names}",
                                              len(unsaved), names=names))
            target = next((i for i, b in enumerate(self.boards) if b.texture == unsaved[0].path), None)

            def go(i=target):
                """'Open in Advanced' on the Wall's bar: puts the deck with unsaved stickers on the bench and opens
                decorating.
                """
                if i is not None and (i != self.sel or self.custom):
                    self.select(i)
                self.open_decorate()
            btn.config(text=_("Open in Advanced"), command=go)
            btn.pack(side="right")
        elif changed:
            name = self.boards[self.sel].name
            self._wall_bar_msg.config(text=_n("Deck {name}: {n} color is not written to the game yet",
                                              "Deck {name}: {n} colors are not written to the game yet",
                                              len(changed), name=name))
            btn.config(text=_("Back to deck {name}", name=name), command=lambda: self.shop_show("bench"))
            btn.pack(side="right")
        else:
            self._wall_bar_msg.config(text=_("Nothing waiting. Every change is in the game.")
                                      if self.boards else _("Open a content folder to begin"))

    # ------------------------------------------------------------------ Decorate, Skate shop style
    def _build_decorate_shop(self, view):
        """Decorate as a mode of the Bench (the dock's Stickers tool): the same widgets as the other
        layouts (dc_cv, dc_flat, dc_b_save, ...), built into the Bench below its title bar and dock:
        the library on the left, an upright flat deck next to the 3D board, the layers sheet on the
        right and an ink bar at the bottom for saving. The chip and Undo / Redo sit in the Bench's
        title bar while decorating."""
        tools = getattr(self, "_shop_dc_tools", None) or tk.Frame(view, bg=C["bg"])
        self.dc_title = tk.Label(tools, text="", bg=C["bg"])      # the Bench title shows the deck
        self.dc_chip = tk.Label(tools, font=F["smallbold"], padx=10, pady=3, bg=C["btn"], fg=C["sub"])
        self.dc_chip.pack(side="left", padx=(0, 14))
        self.dc_b_undo = button(tools, _("Undo"), self.dc_undo, small=True)
        self.dc_b_undo.pack(side="left")
        self.dc_b_redo = button(tools, _("Redo"), self.dc_redo, small=True)
        self.dc_b_redo.pack(side="left", padx=(6, 0))
        tk.Frame(view, bg=C["border"], height=1).pack(fill="x", pady=(10, 0))

        # bottom ink bar: what is not saved yet, the base texture, Clear all and Write to game
        bar = tk.Frame(view, bg=ink())
        bar.pack(side="bottom", fill="x")
        bi = tk.Frame(bar, bg=ink())
        bi.pack(fill="x", padx=24, pady=10)
        tk.Label(bi, text=_("BASE"), font=F["displaysm"], fg=onink(), bg=ink()).pack(side="left")
        self.dc_base_thumb = tk.Label(bi, bg=ink())
        self.dc_base_thumb.pack(side="left", padx=8)
        self.dc_base_lbl = tk.Label(bi, text="", font=F["small"], fg=onink(), bg=ink(), anchor="w")
        self.dc_base_lbl.pack(side="left")
        tk.Frame(bi, bg=C["sub"], width=1, height=26).pack(side="left", padx=16)
        self.dc_changes = tk.Label(bi, text="", font=F["body"], fg=onink(), bg=ink(), anchor="w", justify="left")
        self.dc_changes.pack(side="left", fill="x", expand=True)
        self.dc_b_save = _flat_button(bi, _("Save board…"), self.dc_save_dialog, C["accent"], C["onaccent"],
                                      C["accenth"], bd=C["accent"])
        self.dc_b_save.pack(side="right")
        self.dc_b_revert = _flat_button(bi, _("Revert"), self.dc_revert, ink(), onink(), C["sub"],
                                        font=F["body"], bd=onink())
        self.dc_b_revert.pack(side="right", padx=(0, 10))
        self.dc_b_clear = _flat_button(bi, _("Clear all"), self.dc_clear, ink(), onink(), C["sub"],
                                       font=F["body"], bd=onink())
        self.dc_b_clear.pack(side="right", padx=(0, 10))

        body = tk.Frame(view, bg=C["bg"])
        body.pack(fill="both", expand=True)
        left = self._dc_left_panel = tk.Frame(body, bg=C["side"], width=getattr(self, "_dc_left_w", self.DC_LEFT_W))
        left.pack(side="left", fill="y")
        left.pack_propagate(False)
        self._dc_left_strip = self._dc_build_left_strip(body)
        self._dc_left_line = self._dc_build_left_grip(body)
        self._dc_left_line.pack(side="left", fill="y")
        insp = self._dc_insp = Scroll(body, width=getattr(self, "_dc_right_w", self.DC_RIGHT_W))
        insp.canvas.config(bg=C["panel"])
        insp.inner.config(bg=C["panel"])
        insp.pack(side="right", fill="y")
        self._dc_build_grip(body, self._dc_right_drag, self._dc_right_done,
                            lambda: self._dc_right_resize(self.DC_RIGHT_W, done=True)).pack(side="right", fill="y")
        center = tk.Frame(body, bg=C["bg"])
        center.pack(side="left", fill="both", expand=True)
        self._dc_build_left(left)
        self._dc_build_center_shop(center)
        self._dc_build_inspector(insp.inner)
        if getattr(self, "_dc_left_collapsed", False):
            self.dc_left_collapse(True)
        if getattr(self, "_dc_left_w", self.DC_LEFT_W) != self.DC_LEFT_W:
            base.root.after(200, self._dc_left_reflow)

    # -- the library on the left: hanging tags, it folds away, and its edge drags --
    DC_LEFT_W, DC_LEFT_MIN, DC_LEFT_MAX, DC_LEFT_FOLD = 310, 240, 640, 170

    DC_RIGHT_W, DC_RIGHT_MIN, DC_RIGHT_MAX = 360, 300, 620

    def _dc_build_grip(self, body, drag, done, reset):
        """An edge between two parts of the Advanced view that drags (↔). drag(dx) while dragging,
        done(dx) on release, reset() on a double-click."""
        grip = tk.Frame(body, bg=C["bg"], width=8, cursor="sb_h_double_arrow")
        line = tk.Frame(grip, bg=ink(), width=2, cursor="sb_h_double_arrow")
        line.place(relx=0.5, rely=0, relheight=1, anchor="n")
        knob = tk.Frame(grip, bg=ink(), width=6, height=36, cursor="sb_h_double_arrow")
        knob.place(relx=0.5, rely=0.5, anchor="center")
        st = {}
        for w in (grip, line, knob):
            w.bind("<ButtonPress-1>", lambda e: st.update(x=e.x_root))
            w.bind("<B1-Motion>", lambda e: drag(e.x_root - st.get("x", e.x_root)))
            w.bind("<ButtonRelease-1>", lambda e: done(e.x_root - st.get("x", e.x_root)))
            w.bind("<Double-Button-1>", lambda e: reset())
            w.bind("<Enter>", lambda e: knob.config(bg=C["accent"]))
            w.bind("<Leave>", lambda e: knob.config(bg=ink()))
        return grip

    def _dc_right_drag(self, dx):
        """The Layers panel's edge dragged: resizes it live."""
        if not hasattr(self, "_dc_right_w0"):
            self._dc_right_w0 = self._dc_insp.winfo_width()
        self._dc_right_resize(self._dc_right_w0 - dx)

    def _dc_right_done(self, dx):
        """The Layers panel's edge released: final size, then the text inside re-wraps."""
        w0 = getattr(self, "_dc_right_w0", self._dc_insp.winfo_width())
        self.__dict__.pop("_dc_right_w0", None)
        self._dc_right_resize(w0 - dx, done=True)

    def _dc_right_resize(self, w, done=False):
        """Sets the Layers panel width, kept between its limits and leaving room for the deck view."""
        left = 0 if getattr(self, "_dc_left_collapsed", False) else getattr(self, "_dc_left_w", self.DC_LEFT_W)
        room = base.root.winfo_width() - left - 520          # keep a usable deck view
        w = int(max(self.DC_RIGHT_MIN, min(self.DC_RIGHT_MAX, max(self.DC_RIGHT_MIN, room), w)))
        self._dc_right_w = w
        self._dc_insp.config(width=w)
        if done:
            base.root.after_idle(self._dc_right_reflow)

    def _dc_right_reflow(self):
        """Re-wraps the wrapping labels of the Layers panel to its new width."""
        w = getattr(self, "_dc_right_w", self.DC_RIGHT_W)
        stack = [self._dc_insp.inner]
        while stack:
            x = stack.pop()
            stack.extend(x.winfo_children())
            if isinstance(x, tk.Label) and int(float(x.cget("wraplength") or 0)) > 0:
                x.config(wraplength=max(220, w - 70))

    # -- the Layers sheet --
    def _dc_build_layers_shop(self, i):
        """Layers in the Skate shop: add tags on a rail, the list, and the picked layer's tools as
        icon toolbars (they show only when a layer is picked, instead of a wall of greyed buttons)."""
        from ..layers import MIRRORS
        from .. import textshapes as TS
        P = C["panel"]
        r = tk.Frame(i, bg=P)
        r.pack(fill="x", padx=12, pady=(0, 2))
        self._dc_h(r, _("Layers")).pack(side="left")
        self.dc_layer_count = label(r, "", "small", "muted", bg=P)
        self.dc_layer_count.pack(side="left", padx=6)
        tk.Frame(i, bg=ink(), height=3).pack(fill="x", padx=12, pady=(6, 0))          # the rail
        tags = tk.Frame(i, bg=P)
        tags.pack(fill="x", padx=12)
        shape_menu = tk.Menu(base.root, tearoff=0, bg=C["panel"], fg=C["text"], activebackground=C["btnh"],
                             activeforeground=C["text"], bd=0, relief="flat", font=F["body"])
        for k, lab in TS.SHAPES:
            shape_menu.add_command(label=_(lab), command=lambda k=k: self.dc_add_shape(k))
        HangTag(tags, "+ " + _("Image").upper(), self.dc_ask_image, bg=P).pack(side="left", padx=(0, 6), anchor="n")
        HangTag(tags, "+ " + _("Text").upper(), self.dc_add_text, bg=P).pack(side="left", padx=(0, 6), anchor="n")
        st = HangTag(tags, "+ " + _("Shape").upper() + " ▾", None, bg=P)
        st.command = lambda: shape_menu.tk_popup(st.winfo_rootx(), st.winfo_rooty() + st.winfo_height())
        st.config(cursor="hand2")
        st.pack(side="left", anchor="n")
        self.dc_shape_btn = st
        lb = tk.Frame(i, bg=C["bg"], height=230)
        lb.pack(fill="x", padx=12, pady=(10, 0))
        lb.pack_propagate(False)
        self.dc_layer_scroll = Scroll(lb)
        self.dc_layer_scroll.pack(fill="both", expand=True)

        # the picked layer
        self._dc_sel_hint = self._wrap_label(i, _("Click a layer here or a sticker on the board to move, copy or "
                                                  "change it."), fg="muted")
        sel = self._dc_sel_box = tk.Frame(i, bg=P)
        hd = tk.Frame(sel, bg=P)
        hd.pack(fill="x", pady=(12, 8))
        tk.Label(hd, text=_("Selected").upper(), font=F["displaysm"], fg=onink(), bg=ink(), padx=6).pack(side="left")
        self._dc_sel_name = label(hd, "", "bold", bg=P, anchor="w")
        self._dc_sel_name.pack(side="left", padx=8, fill="x", expand=True)

        def group(parent, title, items):
            """A titled group of icon buttons; returns (frame, buttons)."""
            g = tk.Frame(parent, bg=P)
            label(g, _(title).upper(), "small", "muted", bg=P, anchor="w").pack(fill="x")
            row = tk.Frame(g, bg=P)
            row.pack(anchor="w", pady=(2, 0))
            btns = []
            for icon, tip, cmd in items:
                b = IconButton(row, icon, _(tip), cmd, status=self.set_status)
                b.pack(side="left", padx=(0, 4))
                btns.append(b)
            return g, btns
        r1 = tk.Frame(sel, bg=P)
        r1.pack(fill="x")
        g, b_order = group(r1, N_("Order"), (("up", N_("Up — bring forward (Page Up)"), lambda: self.dc_move_layer(1)),
                                             ("down", N_("Down — send back (Page Down)"), lambda: self.dc_move_layer(-1))))
        g.pack(side="left", padx=(0, 18))
        g, b_copy = group(r1, N_("Copy & delete"), (("dup", N_("Duplicate (Ctrl+D)"), self.dc_duplicate),
                                                    ("delete", N_("Delete (Del)"), self.dc_delete_layer)))
        g.pack(side="left")
        g, b_place = group(sel, N_("Place"), (("fill", N_("Fill — cover the whole board"), lambda: self.dc_set_fit("fill")),
                                              ("fit", N_("Fit — whole sticker on the board"), lambda: self.dc_set_fit("fit")),
                                              ("rotate", N_("Rotate 90° (R)"), lambda: self.dc_rotate(90)),
                                              ("flip", N_("Flip (F)"), self.dc_flip)))
        g.pack(fill="x", pady=(10, 0))
        label(sel, _("Mirror").upper(), "small", "muted", bg=P, anchor="w").pack(fill="x", pady=(10, 2))
        mr = tk.Frame(sel, bg=P)
        mr.pack(anchor="w")
        self._dc_mirror_var = tk.StringVar(value="")
        segs = []
        for m, lab in MIRRORS:
            b = SegButton(mr, text=_(lab), value=m, variable=self._dc_mirror_var,
                          command=lambda: self.dc_set_mirror(self._dc_mirror_var.get()), bg=C["btn"], fg=C["text"],
                          selectcolor=C["selfill"], activebackground=C["btnh"], highlightthickness=1,
                          highlightbackground=C["btnb"], padx=10, pady=3, font=F["small"], cursor="hand2")
            b.pack(side="left", padx=(0, 4))
            segs.append(b)
        self.dc_mirror_btn = FlatButton(tk.Frame(sel), text="")               # kept for the shared refresh code
        self.dc_edit_btn = button(sel, _("Edit…"), self.dc_edit_layer)
        r = tk.Frame(sel, bg=P)
        r.pack(fill="x", pady=(12, 4))
        self._dc_op_row = r
        label(r, _("Opacity").upper(), "small", "muted", bg=P).pack(side="left")
        self.dc_op_val = label(r, "", "small", "muted", width=5, anchor="e", bg=P)
        self.dc_op_val.pack(side="right")
        self.dc_opacity = tk.DoubleVar(value=100)
        self.dc_op_scale = Slider(r, from_=5, to=100, variable=self.dc_opacity, command=self._dc_opacity_moved)
        self.dc_op_scale.pack(side="left", fill="x", expand=True, padx=8)
        self.dc_op_scale.bind("<ButtonPress-1>", lambda e: self._dc_push("opacity"))
        self.dc_op_scale.bind("<ButtonRelease-1>", lambda e: self._dc_sharpen())
        self.dc_sel_btns = b_order + b_copy + b_place + segs
        self._dc_sel_hint.pack(fill="x", padx=12, pady=(10, 0))

    def _dc_layers_shop_refresh(self, L, gk):
        """Shows the tools for the selected layer (or the hint when none is selected): its name, mirror mode,
        Edit... for text and shapes.
        """
        box, hint = getattr(self, "_dc_sel_box", None), getattr(self, "_dc_sel_hint", None)
        if box is None or not box.winfo_exists():
            return
        if L is None:
            box.pack_forget()
            hint.pack(fill="x", padx=12, pady=(10, 0), after=self.dc_layer_scroll.master)
            return
        hint.pack_forget()
        box.pack(fill="x", padx=12, after=self.dc_layer_scroll.master)
        self._dc_sel_name.config(text=L.name if len(L.name) <= 28 else L.name[:27] + "…")
        self._dc_mirror_var.set(L.mirror or "")
        if gk:
            self.dc_edit_btn.pack(anchor="w", pady=(12, 0), before=self._dc_op_row)
        else:
            self.dc_edit_btn.pack_forget()

    def _dc_build_left_grip(self, body):
        """The library's right edge: drag it to make the library wider or narrower (drag it almost shut
        to fold it away, or out of the folded strip to open it). Double-click: back to the usual width."""
        grip = tk.Frame(body, bg=C["bg"], width=8, cursor="sb_h_double_arrow")
        line = tk.Frame(grip, bg=ink(), width=2, cursor="sb_h_double_arrow")
        line.place(relx=0.5, rely=0, relheight=1, anchor="n")
        knob = tk.Frame(grip, bg=ink(), width=6, height=36, cursor="sb_h_double_arrow")
        knob.place(relx=0.5, rely=0.5, anchor="center")
        for w in (grip, line, knob):
            w.bind("<ButtonPress-1>", self._dc_grip_press)
            w.bind("<B1-Motion>", self._dc_grip_drag)
            w.bind("<ButtonRelease-1>", self._dc_grip_release)
            w.bind("<Double-Button-1>", lambda e: self._dc_left_resize(self.DC_LEFT_W, done=True))
            w.bind("<Enter>", lambda e: knob.config(bg=C["accent"]))
            w.bind("<Leave>", lambda e: knob.config(bg=ink()))
        return grip

    def _dc_grip_press(self, e):
        """The library panel's grip pressed: remembers where the drag started."""
        self._dc_grip_x0 = e.x_root
        self._dc_grip_w0 = (0 if getattr(self, "_dc_left_collapsed", False)
                            else self._dc_left_panel.winfo_width())

    def _dc_grip_drag(self, e):
        """The grip dragged: resizes the library live (dragging a folded panel out opens it)."""
        w = self._dc_grip_w0 + (e.x_root - self._dc_grip_x0)
        if getattr(self, "_dc_left_collapsed", False):
            if w > self.DC_LEFT_FOLD:
                self.dc_left_collapse(False)
            else:
                return
        self._dc_left_resize(w)

    def _dc_grip_release(self, e):
        """The grip released: folds the library when dragged very narrow, else keeps the new width."""
        w = self._dc_grip_w0 + (e.x_root - self._dc_grip_x0)
        if getattr(self, "_dc_left_collapsed", False):
            return
        if w < self.DC_LEFT_FOLD:
            self._dc_left_w = max(self.DC_LEFT_MIN, self._dc_grip_w0 or self.DC_LEFT_W)
            self._dc_left_panel.config(width=self._dc_left_w)
            self.dc_left_collapse(True)
            return
        self._dc_left_resize(w, done=True)

    def _dc_left_resize(self, w, done=False):
        """Sets the library width, kept between its limits and leaving room for the deck view and the Layers panel.
        """
        if getattr(self, "_dc_left_collapsed", False):
            self.dc_left_collapse(False)
        room = base.root.winfo_width() - 380 - 520           # keep the inspector and a usable deck view
        w = int(max(self.DC_LEFT_MIN, min(self.DC_LEFT_MAX, max(self.DC_LEFT_MIN, room), w)))
        self._dc_left_w = w
        self._dc_left_panel.config(width=w)
        if done:
            base.root.after_idle(self._dc_left_reflow)

    def _dc_left_reflow(self):
        """After a resize: more sticker columns when there is room, and texts wrap to the new width."""
        w = getattr(self, "_dc_left_w", self.DC_LEFT_W)        # the size asked for (Tk may not have applied it yet)
        cols = max(2, (w - 40) // 80)
        if cols != getattr(self, "_dc_lib_cols", 3):
            self._dc_lib_cols = cols
            if getattr(self, "dc_lib", None) is not None:
                self.dc_load_library()
        stack = [self._dc_left_panel]
        while stack:
            x = stack.pop()
            stack.extend(x.winfo_children())
            if isinstance(x, tk.Label) and int(float(x.cget("wraplength") or 0)) > 0:
                x.config(wraplength=max(200, w - 56))

    DC_LEFT_TABS = ((N_("Stickers"), "stickers"), (N_("Textures"), "textures"), (N_("Effects"), "effects"))

    def _dc_left_tags_build(self, left):
        """Stickers / Textures / Effects as tags hanging from a rail along the top of the library,
        with « to fold the library away."""
        side = C["side"]
        tk.Frame(left, bg=ink(), height=3).pack(fill="x")             # the rail
        row = tk.Frame(left, bg=side)
        row.pack(fill="x", padx=10, pady=(0, 10))
        self._dc_left_tags = {}
        for text, val in self.DC_LEFT_TABS:
            t = HangTag(row, _(text).upper(), lambda v=val: self._dc_left_pick(v), bg=side)
            t.pack(side="left", padx=(0, 6), anchor="n")
            self._dc_left_tags[val] = t
        fold = HangTag(row, "«", lambda: self.dc_left_collapse(True), kind="outline", bg=side)
        fold.pack(side="right", anchor="n")
        self._dc_left_tags_refresh()

    def _dc_left_pick(self, val):
        """A library tag (Stickers / Textures / Effects): opens the folded panel if needed and switches to it.
        """
        if getattr(self, "_dc_left_collapsed", False):
            self.dc_left_collapse(False)
        self.dc_left_tab.set(val)
        self._dc_left_switch()

    def _dc_left_tags_refresh(self):
        """Lights the current library tag (and redraws the folded strip)."""
        tab = self.dc_left_tab.get()
        for val, t in getattr(self, "_dc_left_tags", {}).items():
            if t.winfo_exists():
                t.set(kind="on" if val == tab else "ink")
        strip = getattr(self, "_dc_left_strip", None)
        if strip is not None and strip.winfo_exists():
            self._dc_left_strip_draw()

    def _dc_build_left_strip(self, body):
        """The folded library: a narrow strip with » and the three tabs written upwards."""
        cv = tk.Canvas(body, width=38, bg=C["side"], highlightthickness=0, bd=0)
        cv.bind("<Configure>", lambda e: self._dc_left_strip_draw())
        self._dc_strip_cv = cv
        return cv

    def _dc_left_strip_draw(self):
        """Draws the folded library strip: the open button and the three tabs written upwards."""
        cv = getattr(self, "_dc_strip_cv", None)
        if cv is None or not cv.winfo_exists():
            return
        import tkinter.font as tkfont
        cv.delete("all")
        f = tkfont.Font(root=cv, font=F["displaysm"])
        cv.create_rectangle(0, 0, 38, 3, fill=ink(), outline="")
        cv.create_line(19, 3, 19, 12, fill=ink(), width=2)
        cv.create_rectangle(5, 12, 33, 40, fill=C["side"], outline=ink(), width=2, tags=("open",))
        cv.create_text(19, 26, text="»", font=F["displaysm"], fill=ink(), tags=("open",))
        cv.tag_bind("open", "<Button-1>", lambda e: self.dc_left_collapse(False))
        y = 56
        tab = self.dc_left_tab.get() if hasattr(self, "dc_left_tab") else "stickers"
        for text, val in self.DC_LEFT_TABS:
            t = _(text).upper()
            h = f.measure(t) + 34
            on = val == tab
            tag = "tab_" + val
            cv.create_rectangle(5, y, 33, y + h, fill=C["accent"] if on else ink(), outline=C["accent"] if on else ink(),
                                width=2, tags=(tag,))
            cv.create_text(19, y + h / 2, text=t, angle=90, font=F["displaysm"],
                           fill=C["onaccent"] if on else onink(), tags=(tag,))
            cv.tag_bind(tag, "<Button-1>", lambda e, v=val: self._dc_left_pick(v))
            y += h + 8
        cv.config(cursor="hand2")

    def dc_left_collapse(self, fold):
        """Folds the library away (more room for the deck) or opens it again."""
        left, strip, line = (getattr(self, "_dc_left_panel", None), getattr(self, "_dc_left_strip", None),
                             getattr(self, "_dc_left_line", None))
        if left is None or not left.winfo_exists():
            return
        self._dc_left_collapsed = fold
        if fold:
            left.pack_forget()
            strip.pack(side="left", fill="y", before=line)
            self._dc_left_strip_draw()
        else:
            strip.pack_forget()
            left.pack(side="left", fill="y", before=line)

    def _dc_build_center_shop(self, center):
        """Builds the decorating view's centre: Place stickers / View & colours, outline and screws, the upright
        flat deck next to the 3D board, the view buttons and the hint.
        """
        bar = tk.Frame(center, bg=C["bg"])
        bar.pack(fill="x", padx=20, pady=(14, 0))
        self.dc_mode = tk.StringVar(value=self._keep.get("dc_mode", "place"))
        seg = self._seg(bar, self.dc_mode, ((N_("Place stickers"), "place"), (N_("View / colors"), "view")),
                        self._dc_mode_changed)
        seg.config(highlightthickness=2, highlightbackground=ink())
        seg.pack(side="left")
        for text, var in ((N_("Outline"), self.v3_outline), (N_("Screws"), self.v3_screws)):
            tk.Checkbutton(bar, text=_(text), variable=var, command=self.dc_render, bg=C["bg"], fg=C["sub"],
                           activebackground=C["bg"], activeforeground=C["text"], selectcolor=C["panel"],
                           font=F["small"], bd=0, highlightthickness=0, cursor="hand2").pack(side="right", padx=(8, 0))

        vbar = tk.Frame(center, bg=C["bg"])
        vbar.pack(side="bottom", fill="x", padx=20, pady=(0, 12))
        for text, yaw, pitch in (("3/4", 28, 30), (N_("Top"), 0, 75), (N_("Bottom"), 0, -75), (N_("Side"), 90, 6)):
            button(vbar, _(text), lambda y=yaw, p=pitch: self._dc_view(y, p), small=True).pack(side="left", padx=(0, 4))
        self.dc_hint = label(vbar, "", "small", "sub", bg=C["bg"])
        self.dc_hint.pack(side="right")

        stage = tk.Frame(center, bg=C["bg"])
        stage.pack(fill="both", expand=True, padx=20, pady=12)
        fcol = tk.Frame(stage, bg=C["bg"])
        fcol.pack(side="left", fill="y", padx=(0, 22))
        tk.Label(fcol, text=_("FLAT"), font=F["displaysm"], fg=ink(), bg=C["bg"]).pack(side="bottom", pady=(6, 0))
        self.dc_tex_file = label(fcol, "", "mono", "muted", bg=C["bg"])
        self.dc_tex_file.pack(side="bottom")
        self.dc_flat = tk.Canvas(fcol, bg=C["bg"], width=110, height=300, highlightthickness=0)
        self.dc_flat.pack(side="top", fill="y", expand=True)
        v3 = tk.Frame(stage, bg=C["bg"])
        v3.pack(side="left", fill="both", expand=True)
        tk.Label(v3, text=_("3D"), font=F["displaysm"], fg=ink(), bg=C["bg"]).pack(side="bottom", pady=(6, 0))
        self.dc_cv = tk.Canvas(v3, bg=C["bg"], highlightthickness=0, height=300)
        self.dc_cv.pack(fill="both", expand=True)
        self._dc_bind_cv()
        self._dc_bind_flat()

    def _dc_shop_bar(self):
        """Keeps the ink bar's Write button readable when there is nothing to write."""
        if self.layout != "shop" or not hasattr(self, "dc_b_save"):
            return
        s = self.dc
        dirty = s is not None and (s.dirty() or bool(self._pal_changed()))
        on = dirty
        b = self.dc_b_save
        b.config(bg=C["accent"] if on else ink(), fg=C["onaccent"] if on else C["dis"],
                 highlightbackground=C["accent"] if on else C["dis"],
                 activebackground=C["accenth"] if on else C["btnh"])
        b.bind("<Leave>", lambda e, b=b, on=on: b.config(bg=C["accent"] if on else ink()))
        if s is not None:
            self.dc_chip.config(text=self.dc_chip.cget("text").upper())
