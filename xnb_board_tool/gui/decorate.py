"""The Decorate tab: put stickers and images on the board in 3D, as layers on a base texture."""
from __future__ import annotations

import dataclasses
import math
import queue
import threading
import time
from pathlib import Path
from typing import Optional

from tkinter import colorchooser, filedialog, messagebox, simpledialog, ttk
import tkinter as tk
from PIL import Image, ImageDraw, ImageTk

from .. import basetex
from ..boards import PALETTE_SLOTS, to_hex
from ..caches import TEXCACHE
from ..defaults import load_default_meta, set_default
from ..layers import (Composer, Layer, drop_project, load_project, new_image_adjust, save_project,
                      sticker_adjust, with_outline)
from ..settings import C, SETTINGS, _rgb, save_settings
from ..stickers import StickerLibrary
from ..xnb import save_texture
from .base import F, Scroll, button, card, hline, label, more_button, set_state
from . import base

PART_NAMES = [name for _key, name in PALETTE_SLOTS]
IMG_TYPES = [("Images", "*.png *.jpg *.jpeg *.bmp *.tga *.gif *.webp"), ("All files", "*.*")]
ALL = "*all*"
DEFAULT_PACK = "My stickers"


# ====================================================================== state
class DecorSession:
    """The decoration of one board: base texture, layers, selection and undo history."""

    def __init__(self, path: Path, tex, project: Optional[dict] = None):
        self.path, self.tex = path, tex
        # the board's own art when decorating began (shared with the texture cache, never changed)
        self.original = tex.img if tex.img.mode == "RGBA" else tex.img.convert("RGBA")
        self.base_key, self.tint, self.tint_strength = basetex.ORIGINAL, None, 0.0
        self.base_img = self.original
        self.base_regen = False                       # base_img can be made again from base_key
        self.work = None
        self.layers: list = []
        self.sel: Optional[Layer] = None
        self.undo, self.redo = [], []
        self.last_undo = (None, 0.0)
        self.composer = Composer()
        self.restored = ""
        if project:
            self.base_img, self.base_key = project["base"], project["base_key"]
            self.tint, self.tint_strength = project["tint"], project["tint_strength"]
            self.layers = project["layers"]
            self.restored = project.get("saved_at", "")
        self.saved_sig = self.sig()

    @property
    def size(self):
        return self.original.size

    def sleep(self):
        """Frees everything that can be made again (used for boards you have stepped away from):
        cached renders, the composed texture and a generated base. Placement and undo stay."""
        self.composer.invalidate()
        self.work = None
        seen = set()
        for L in self.layers + [snap[0] for st in self.undo + self.redo for snap in st[0]]:
            if id(L) not in seen:
                seen.add(id(L))
                L.drop_cache()
        if self.base_regen and self.base_key != basetex.ORIGINAL:
            self.base_img = None

    def wake(self):
        if self.base_img is None:
            W, H = self.size
            self.base_img = basetex.make_base(self.base_key, W, H, self.original, self.tint, self.tint_strength)

    def sig(self):
        return (self.base_key, self.tint, round(self.tint_strength, 3),
                tuple((L.id, dataclasses.astuple(L.adj), L.opacity, L.visible) for L in self.layers))

    def dirty(self):
        return self.sig() != self.saved_sig


class Renderer:
    """One background render thread for the Decorate 3D view; the newest request wins."""

    def __init__(self):
        self._cv = threading.Condition()
        self._job = None
        self.results: queue.Queue = queue.Queue()
        threading.Thread(target=self._loop, daemon=True).start()

    def request(self, **job):
        with self._cv:
            self._job = job
            self._cv.notify()

    def _loop(self):
        from ..board3d import render_board
        while True:
            with self._cv:
                while self._job is None:
                    self._cv.wait()
                job, self._job = self._job, None
            t0 = time.perf_counter()
            info = {}
            try:
                img = render_board(job["model"], job["tex"], job["yaw"], job["pitch"], job["zoom"],
                                   job["W"], job["H"], job["screws"], job["outline"], job["bg"], info=info)
            except Exception as e:
                img, info = e, None
            self.results.put((job, img, info, (time.perf_counter() - t0) * 1000))


# ====================================================================== the tab
class DecorateMixin:
    """The Decorate tab. Mixed into App."""

    def _dc_init_state(self):
        self.dc_lib: Optional[StickerLibrary] = None
        self.dc_sessions: dict = {}             # texture path -> DecorSession (unsaved work survives)
        self.dc: Optional[DecorSession] = None
        self.dc_renderer = Renderer()
        self.dc_yaw, self.dc_pitch, self.dc_zoom = 28.0, 30.0, 0.95
        self.dc_info, self.dc_info_scale = None, 1.0
        self.dc_texarr = None
        self.dc_pack = ALL
        self._dc_mask = None
        self._dc_tex_prev: dict = {}
        self._dc_drag = self._dc_lib_drag = None
        self._dc_hover = None
        self._dc_sharp = self._dc_upd = self._dc_flat_job = None
        self._dc_polling = False

    # ------------------------------------------------------------------ building
    def _build_decorate(self, view):
        self._dc_photo = self._dc_flat_photo = self._dc_ghost_photo = self._dc_base_photo = None
        self._dc_lib_photos, self._dc_tex_photos, self._dc_tiles = [], {}, {}
        self._dc_tex_rows = {}
        self._dc_libs_built = False
        left = tk.Frame(view, bg=C["side"], width=272)
        left.pack(side="left", fill="y")
        left.pack_propagate(False)
        self._vline(view)
        insp = Scroll(view, width=350)
        insp.pack(side="right", fill="y")
        self._vline(view, "right")
        center = tk.Frame(view, bg=C["bg"])
        center.pack(side="left", fill="both", expand=True)
        self._dc_build_left(left)
        self._dc_build_center(center)
        self._dc_build_inspector(insp.inner)

    def _seg(self, parent, var, items, cmd, small=False):
        seg = tk.Frame(parent, bg=C["bg"], highlightthickness=1, highlightbackground=C["border"])
        for text, val in items:
            tk.Radiobutton(seg, text=text, value=val, variable=var, command=cmd, indicatoron=False,
                           bg=C["bg"], fg=C["text"], selectcolor=C["selfill"], activebackground=C["btnh"],
                           activeforeground=C["text"], relief="flat", bd=0, highlightthickness=0,
                           padx=12 if small else 14, pady=3 if small else 5,
                           font=F["smallbold" if small else "bold"], cursor="hand2").pack(
                side="left", padx=1, pady=1, fill="x", expand=True)
        return seg

    # -- left: stickers | textures
    def _dc_build_left(self, left):
        self.dc_left_tab = tk.StringVar(value=self._keep.get("dc_left", "stickers"))
        self._seg(left, self.dc_left_tab, (("Stickers", "stickers"), ("Textures", "textures")),
                  self._dc_left_switch).pack(fill="x", padx=12, pady=(14, 10))
        self.dc_stickers_frame = tk.Frame(left, bg=C["side"])
        self.dc_textures_frame = tk.Frame(left, bg=C["side"])
        # stickers
        f = self.dc_stickers_frame
        top = tk.Frame(f, bg=C["side"])
        top.pack(fill="x", padx=12, pady=(0, 4))
        label(top, "Sticker packs", "bold").pack(side="left")
        self.dc_pack_more, _ = more_button(top, [
            ("New pack…", self.dc_new_pack), ("Rename pack…", self.dc_rename_pack),
            ("Delete pack…", self.dc_delete_pack), ("Export pack as .zip…", self.dc_export_pack),
            ("Import pack from .zip…", self.dc_import_pack)])
        self.dc_pack_more.pack(side="right")
        button(top, "+ New", self.dc_new_pack, small=True).pack(side="right", padx=(0, 6))
        box = tk.Frame(f, bg=C["bg"], height=132, highlightthickness=1, highlightbackground=C["border"])
        box.pack(fill="x", padx=12)
        box.pack_propagate(False)
        self.dc_pack_scroll = Scroll(box)
        self.dc_pack_scroll.pack(fill="both", expand=True)
        top = tk.Frame(f, bg=C["side"])
        top.pack(fill="x", padx=12, pady=(10, 2))
        self.dc_lib_title = label(top, "Stickers", "bold")
        self.dc_lib_title.pack(side="left")
        self.dc_lib_count = label(top, "", "small", "muted")
        self.dc_lib_count.pack(side="left", padx=6)
        button(top, "Add…", self.dc_add_stickers, small=True).pack(side="right")
        label(f, "Drag onto the board, or click to add. Right-click for more.", "small", "muted",
              justify="left", anchor="w", wraplength=240).pack(fill="x", padx=12, pady=(0, 6))
        self.dc_lib_scroll = Scroll(f)
        self.dc_lib_scroll.pack(fill="both", expand=True, padx=(8, 0), pady=(0, 8))
        # textures
        f = self.dc_textures_frame
        top = tk.Frame(f, bg=C["side"])
        top.pack(fill="x", padx=12, pady=(0, 4))
        label(top, "Base texture", "bold").pack(side="left")
        button(top, "Add…", self.dc_add_textures, small=True).pack(side="right")
        label(f, "Click to put a texture under your stickers. Colors and layers stay as they are.",
              "small", "muted", justify="left", anchor="w", wraplength=240).pack(fill="x", padx=12, pady=(0, 8))
        tr = tk.Frame(f, bg=C["panel"], highlightthickness=1, highlightbackground=C["border"])
        tr.pack(fill="x", padx=12, pady=(0, 8))
        label(tr, "Tint", "small", "sub").pack(side="left", padx=(10, 6), pady=6)
        self.dc_tint_sw = tk.Canvas(tr, width=22, height=16, bg=C["btn"], highlightthickness=1,
                                    highlightbackground=C["btnb"], cursor="hand2")
        self.dc_tint_sw.pack(side="left")
        self.dc_tint_sw.bind("<Button-1>", lambda e: self.dc_pick_tint())
        self.dc_tint_val = label(tr, "0%", "small", "muted", width=4, anchor="e")
        self.dc_tint_val.pack(side="right", padx=(4, 10))
        self.dc_tint = tk.DoubleVar(value=0)
        self.dc_tint_scale = ttk.Scale(tr, from_=0, to=100, variable=self.dc_tint, command=self._dc_tint_moved)
        self.dc_tint_scale.pack(side="left", fill="x", expand=True, padx=8)
        self.dc_tint_scale.bind("<ButtonPress-1>", lambda e: self._dc_push("tint"))
        self.dc_tint_scale.bind("<ButtonRelease-1>", lambda e: self._dc_apply_base(final=True))
        self.dc_tex_scroll = Scroll(f)
        self.dc_tex_scroll.pack(fill="both", expand=True, padx=(8, 0), pady=(0, 8))
        if base.TkinterDnD:
            for w in (self.dc_lib_scroll.canvas, self.dc_lib_scroll.inner, self.dc_pack_scroll.canvas):
                w.drop_target_register(base.DND_FILES)
                w.dnd_bind("<<Drop>>", self._dc_lib_drop)
            for w in (self.dc_tex_scroll.canvas, self.dc_tex_scroll.inner):
                w.drop_target_register(base.DND_FILES)
                w.dnd_bind("<<Drop>>", lambda e: (self._dc_import_textures(base.root.tk.splitlist(e.data)),
                                                  e.action)[1])
        self._dc_left_switch()

    # -- center: title, 3D, flat texture
    def _dc_build_center(self, center):
        m = tk.Frame(center, bg=C["bg"])
        m.pack(fill="both", expand=True, padx=20, pady=16)
        tr = tk.Frame(m, bg=C["bg"])
        tr.pack(fill="x")
        self.dc_title = label(tr, "No board selected", "h1")
        self.dc_title.pack(side="left")
        self.dc_chip = tk.Label(tr, font=F["smallbold"], padx=10, pady=3, bg=C["btn"], fg=C["sub"])
        self.dc_chip.pack(side="left", padx=14)
        button(tr, "›", lambda: self.step(1), width=2).pack(side="right")
        button(tr, "‹", lambda: self.step(-1), width=2).pack(side="right", padx=(6, 6))
        self.dc_b_redo = button(tr, "Redo", self.dc_redo, small=True)
        self.dc_b_redo.pack(side="right", padx=(6, 10))
        self.dc_b_undo = button(tr, "Undo", self.dc_undo, small=True)
        self.dc_b_undo.pack(side="right")

        vc = card(m)
        vc.pack(fill="both", expand=True, pady=(14, 0))
        head = tk.Frame(vc, bg=C["panel"])
        head.pack(fill="x", padx=14, pady=8)
        label(head, "3D board", "h2").pack(side="left")
        self.dc_mode = tk.StringVar(value=self._keep.get("dc_mode", "place"))
        self._seg(head, self.dc_mode, (("View / colors", "view"), ("Place stickers", "place")),
                  self._dc_mode_changed, small=True).pack(side="left", padx=14)
        for text, var in (("Outline", self.v3_outline), ("Screws", self.v3_screws)):
            tk.Checkbutton(head, text=text, variable=var, command=self.dc_render,
                           bg=C["panel"], fg=C["sub"], activebackground=C["panel"],
                           activeforeground=C["text"], selectcolor=C["bg"], font=F["small"],
                           bd=0, highlightthickness=0, cursor="hand2").pack(side="right", padx=(8, 0))
        hline(vc).pack(fill="x")
        vbar = tk.Frame(vc, bg=C["panel"])
        vbar.pack(side="bottom", fill="x", padx=14, pady=(0, 10))
        for text, yaw, pitch in (("3/4", 28, 30), ("Top", 0, 75), ("Bottom", 0, -75), ("Side", 90, 6)):
            tk.Button(vbar, text=text, command=lambda y=yaw, p=pitch: self._dc_view(y, p),
                      bg=C["btn"], fg=C["text"], activebackground=C["btnh"], activeforeground=C["text"],
                      relief="flat", bd=0, highlightthickness=1, highlightbackground=C["btnb"], padx=10,
                      pady=3, font=F["small"], cursor="hand2").pack(side="left", padx=(0, 4))
        self.dc_hint = label(vbar, "", "small", "muted")
        self.dc_hint.pack(side="right")
        self.dc_cv = tk.Canvas(vc, bg=C["bg"], highlightthickness=0, height=300)
        self.dc_cv.pack(fill="both", expand=True, padx=14, pady=(10, 8))
        self.dc_cv._own_wheel = True
        c = self.dc_cv
        c.bind("<Configure>", lambda e: self.dc_render())
        c.bind("<Motion>", self._dc_on_hover)
        c.bind("<Leave>", lambda e: self._dc_set_hover(None))
        c.bind("<ButtonPress-1>", lambda e: self._dc_press(e, 1))
        c.bind("<B1-Motion>", self._dc_move)
        c.bind("<ButtonRelease-1>", self._dc_release)
        c.bind("<ButtonPress-3>", lambda e: self._dc_press(e, 3))
        c.bind("<B3-Motion>", self._dc_move)
        c.bind("<ButtonRelease-3>", self._dc_release)
        c.bind("<MouseWheel>", lambda e: self._dc_wheel(e, 1 if e.delta > 0 else -1))
        c.bind("<Button-4>", lambda e: self._dc_wheel(e, 1))
        c.bind("<Button-5>", lambda e: self._dc_wheel(e, -1))
        self._dc_img_item = c.create_image(0, 0, anchor="nw")
        self._dc_ghost_item = c.create_image(0, 0, state="hidden")
        self._dc_msg_item = c.create_text(0, 0, text="", fill=C["muted"], font=F["body"])

        fc = card(m)
        fc.pack(fill="x", pady=(14, 0))
        head = tk.Frame(fc, bg=C["panel"])
        head.pack(fill="x", padx=14, pady=(8, 6))
        label(head, "Board texture", "h2").pack(side="left")
        self.dc_tex_file = label(head, "", "mono", "muted")
        self.dc_tex_file.pack(side="left", padx=10)
        label(head, "Dimmed: not visible on the deck · outlines: layers", "small", "muted").pack(side="right")
        self.dc_flat = tk.Canvas(fc, bg=C["bg"], height=80, highlightthickness=0)
        self.dc_flat.pack(fill="x", padx=14, pady=(0, 12))
        self.dc_flat._own_wheel = True
        f = self.dc_flat
        f.bind("<Configure>", lambda e: self.dc_draw_flat())
        f.bind("<ButtonPress-1>", self._dc_flat_press)
        f.bind("<B1-Motion>", self._dc_flat_move)
        f.bind("<ButtonRelease-1>", lambda e: self._dc_end_drag())
        f.bind("<Motion>", self._dc_flat_hover)
        f.bind("<Leave>", lambda e: self._dc_set_hover(None))
        f.bind("<MouseWheel>", lambda e: self._dc_flat_wheel(e, 1 if e.delta > 0 else -1))
        f.bind("<Button-4>", lambda e: self._dc_flat_wheel(e, 1))
        f.bind("<Button-5>", lambda e: self._dc_flat_wheel(e, -1))
        if base.TkinterDnD:
            for w in (self.dc_cv, self.dc_flat):
                w.drop_target_register(base.DND_FILES)
                w.dnd_bind("<<Drop>>", self._dc_on_drop)

    # -- right: layers, colors, save
    def _dc_build_inspector(self, parent):
        i = tk.Frame(parent, bg=C["bg"])
        i.pack(fill="both", expand=True, padx=14, pady=16)
        lc = card(i)
        lc.pack(fill="x")
        r = tk.Frame(lc, bg=C["panel"])
        r.pack(fill="x", padx=12, pady=(10, 6))
        label(r, "Layers", "h2").pack(side="left")
        self.dc_layer_count = label(r, "", "small", "muted")
        self.dc_layer_count.pack(side="left", padx=6)
        button(r, "Image…", self.dc_ask_image, small=True).pack(side="right")
        lb = tk.Frame(lc, bg=C["bg"], height=196)
        lb.pack(fill="x", padx=12)
        lb.pack_propagate(False)
        self.dc_layer_scroll = Scroll(lb)
        self.dc_layer_scroll.pack(fill="both", expand=True)
        r = tk.Frame(lc, bg=C["panel"])
        r.pack(fill="x", padx=12, pady=(8, 4))
        b1 = button(r, "Up", lambda: self.dc_move_layer(1), small=True)
        b2 = button(r, "Down", lambda: self.dc_move_layer(-1), small=True)
        b3 = button(r, "Duplicate", self.dc_duplicate, small=True)
        b4 = button(r, "Delete", self.dc_delete_layer, small=True)
        for b in (b1, b2, b3, b4):
            b.pack(side="left", padx=(0, 5))
        r = tk.Frame(lc, bg=C["panel"])
        r.pack(fill="x", padx=12, pady=(0, 4))
        b5 = button(r, "Fill", lambda: self.dc_set_fit("fill"), small=True)
        b6 = button(r, "Fit", lambda: self.dc_set_fit("fit"), small=True)
        b7 = button(r, "Rotate 90°", lambda: self.dc_rotate(90), small=True)
        b8 = button(r, "Flip", self.dc_flip, small=True)
        for b in (b5, b6, b7, b8):
            b.pack(side="left", padx=(0, 5))
        r = tk.Frame(lc, bg=C["panel"])
        r.pack(fill="x", padx=12, pady=(2, 12))
        label(r, "Opacity", "small", "sub").pack(side="left")
        self.dc_op_val = label(r, "", "small", "muted", width=5, anchor="e")
        self.dc_op_val.pack(side="right")
        self.dc_opacity = tk.DoubleVar(value=100)
        self.dc_op_scale = ttk.Scale(r, from_=5, to=100, variable=self.dc_opacity, command=self._dc_opacity_moved)
        self.dc_op_scale.pack(side="left", fill="x", expand=True, padx=8)
        self.dc_op_scale.bind("<ButtonPress-1>", lambda e: self._dc_push("opacity"))
        self.dc_op_scale.bind("<ButtonRelease-1>", lambda e: self._dc_sharpen())
        self.dc_sel_btns = [b1, b2, b3, b4, b5, b6, b7, b8]

        cc = card(i)
        cc.pack(fill="x", pady=(14, 0))
        r = tk.Frame(cc, bg=C["panel"])
        r.pack(fill="x", padx=12, pady=(10, 6))
        label(r, "Board colors", "h2").pack(side="left")
        label(r, "or click a part in 3D", "small", "muted").pack(side="right")
        g = tk.Frame(cc, bg=C["panel"])
        g.pack(fill="x", padx=12, pady=(0, 12))
        self.dc_swatches = []
        for k, name in enumerate(PART_NAMES):
            g.columnconfigure(k, weight=1, uniform="dcp")
            cell = tk.Frame(g, bg=C["panel"])
            cell.grid(row=0, column=k, sticky="we", padx=(0 if k == 0 else 4, 0))
            sw = tk.Canvas(cell, height=28, bg=C["btn"], highlightthickness=1, highlightbackground=C["btnb"],
                           cursor="hand2")
            sw.pack(fill="x")
            sw.bind("<Button-1>", lambda e, k=k: self._dc_pick_color(k))
            sw.bind("<Configure>", lambda e: self._dc_draw_colors())
            nm = label(cell, name, "smallbold")
            nm.pack(anchor="w")
            hx = label(cell, "", "mono", "muted")
            hx.pack(anchor="w")
            self.dc_swatches.append((sw, nm, hx))

        sc = card(i)
        sc.pack(fill="x", pady=(14, 0))
        label(sc, "Save", "h2").pack(anchor="w", padx=12, pady=(10, 6))
        r = tk.Frame(sc, bg=C["panel"])
        r.pack(fill="x", padx=12)
        label(r, "Base", "small", "muted").pack(side="left")
        self.dc_base_thumb = tk.Label(r, bg=C["panel"])
        self.dc_base_thumb.pack(side="left", padx=8)
        self.dc_base_lbl = label(r, "", "small", "sub")
        self.dc_base_lbl.pack(side="left")
        r = tk.Frame(sc, bg=C["panel"])
        r.pack(fill="x", padx=12, pady=(10, 4))
        self.dc_b_save = button(r, "Save decorations…", self.dc_save_dialog, "primary")
        self.dc_b_save.pack(side="left")
        self.dc_b_clear = button(r, "Clear all", self.dc_clear)
        self.dc_b_clear.pack(side="left", padx=8)
        self.dc_changes = label(sc, "", "small", "muted", anchor="w", justify="left", wraplength=300)
        self.dc_changes.pack(fill="x", padx=12, pady=(4, 12))

        for k, f in (("r", lambda: self.dc_rotate(90)), ("f", self.dc_flip)):
            base.root.bind(f"<KeyPress-{k}>", lambda e, f=f: self._dc_key(f))
        base.root.bind("<Delete>", lambda e: self._dc_key(self.dc_delete_layer))
        base.root.bind("<BackSpace>", lambda e: self._dc_key(self.dc_delete_layer))
        base.root.bind("<Control-d>", lambda e: self._dc_key(self.dc_duplicate))
        base.root.bind("<Control-z>", lambda e: self._dc_key(self.dc_undo))
        base.root.bind("<Control-y>", lambda e: self._dc_key(self.dc_redo))
        base.root.bind("<Control-Z>", lambda e: self._dc_key(self.dc_redo))
        base.root.bind("<Prior>", lambda e: self._dc_key(lambda: self.dc_move_layer(1)))
        base.root.bind("<Next>", lambda e: self._dc_key(lambda: self.dc_move_layer(-1)))
        base.root.bind("<Escape>", lambda e: self._dc_key(lambda: self.dc_select_layer(None)), add="+")

    def _dc_key(self, f):
        """Keyboard shortcuts only act in the Decorate tab and never while typing in a field."""
        if self.tab_var.get() != "decor":
            return
        try:
            w = base.root.focus_get()
        except Exception:
            w = None
        if isinstance(w, (tk.Entry, ttk.Entry, ttk.Combobox)):
            return
        f()

    # ------------------------------------------------------------------ entering / sessions
    def dc_enter(self):
        """Called when the Decorate tab is shown or the board changes while it is shown."""
        if self.tab_var.get() != "decor" or not hasattr(self, "dc_cv"):
            return
        if not self._dc_polling:
            self._dc_polling = True
            base.root.after(15, self._dc_poll)
        if self.dc_lib is None:
            self.dc_lib = StickerLibrary()
        if not self._dc_libs_built:
            self._dc_libs_built = True
            self.dc_load_library()
        if self.dc_left_tab.get() == "textures" and not self._dc_tex_photos:
            self.dc_load_textures()
        if self.custom or self.sel is None or self.tex is None or not self.tex_path:
            self.dc = None
            self._dc_msg("Loading…" if self._loading else
                         "Pick a board (Boards tab, or ‹ ›) to decorate it")
            self._dc_refresh_all()
            return
        s = self.dc_sessions.get(self.tex_path)
        if s is None or (s.tex is not self.tex and not s.dirty()):
            proj = load_project(self.tex_path, self.tex.img)
            s = DecorSession(self.tex_path, self.tex, proj)
            self.dc_sessions[self.tex_path] = s
            if s.restored:
                self.set_status(f"Editable layers from {s.restored} restored for {self.tex_path.name}")
        s.tex = self.tex
        changed = s is not self.dc
        if changed:
            for path, other in list(self.dc_sessions.items()):
                if other is s:
                    continue
                if other.dirty():
                    other.sleep()                       # keeps the unsaved work, frees the pixels
                else:
                    del self.dc_sessions[path]          # nothing unsaved: made again on return
        s.wake()
        self.dc = s
        if changed:
            self.dc_info = None
            mm = self._v3_mask_for(s.size)
            self._dc_mask = mm
        self.dc_compose()
        self.dc_render()
        self._dc_refresh_all()

    def _v3_mask_for(self, size):
        from ..board3d import deck_top_mask
        if self.v3_model is None:
            return None
        cache = getattr(self, "_dc_mask_cache", {})
        if size not in cache:
            cache[size] = deck_top_mask(self.v3_model, *size)
            self._dc_mask_cache = cache
        return cache[size]

    def dc_unsaved(self):
        return [s for s in self.dc_sessions.values() if s.dirty()]

    # ------------------------------------------------------------------ library (stickers)
    def _dc_left_switch(self):
        if self.dc_left_tab.get() == "textures":
            self.dc_stickers_frame.pack_forget()
            self.dc_textures_frame.pack(fill="both", expand=True)
            if not self._dc_tex_photos and self.dc_lib is not None:
                self.dc_load_textures()
        else:
            self.dc_textures_frame.pack_forget()
            self.dc_stickers_frame.pack(fill="both", expand=True)

    def dc_load_library(self):
        lib = self.dc_lib
        if lib is None:
            return
        packs = lib.packs()
        keys = [k for k, _d, _l in packs]
        if self.dc_pack != ALL and self.dc_pack not in keys:
            self.dc_pack = ALL
        from ..stickers import images_in
        inner = self.dc_pack_scroll.inner
        for w in inner.winfo_children():
            w.destroy()
        counts = {k: len(images_in(d)) for k, d, _l in packs}
        for k, name, n in [(ALL, "All stickers", sum(counts.values()))] + [(k, l, counts[k]) for k, _d, l in packs]:
            sel = k == self.dc_pack
            bg = C["selfill"] if sel else C["bg"]
            row = tk.Frame(inner, bg=bg, cursor="hand2")
            row.pack(fill="x")
            a = tk.Label(row, text=name, bg=bg, fg=C["text"], font=F["bold" if sel else "body"], anchor="w")
            a.pack(side="left", fill="x", expand=True, padx=(8, 0), pady=3)
            b = tk.Label(row, text=str(n), bg=bg, fg=C["muted"], font=F["small"])
            b.pack(side="right", padx=8)
            for w in (row, a, b):
                w.bind("<Button-1>", lambda e, k=k: self._dc_select_pack(k))
                if k != ALL:
                    w.bind("<Button-3>", lambda e, k=k: (self._dc_select_pack(k), self.dc_pack_more.invoke()))
        grid = self.dc_lib_scroll.inner
        for w in grid.winfo_children():
            w.destroy()
        self._dc_lib_photos, self._dc_tiles = [], {}
        shown = packs if self.dc_pack == ALL else [p for p in packs if p[0] == self.dc_pack]
        cols, size, row = 3, 74, 0
        for k, d, name in shown:
            imgs = images_in(d)
            if self.dc_pack == ALL:
                tk.Label(grid, text=f"{name}  ·  {len(imgs)}", bg=C["bg"], fg=C["sub"], font=F["smallbold"],
                         anchor="w").grid(row=row, column=0, columnspan=cols, sticky="we", padx=4, pady=(8, 0))
                row += 1
            for j, p in enumerate(imgs):
                try:
                    ph = ImageTk.PhotoImage(self._dc_thumb(p, size - 10))
                except Exception:
                    continue
                tile = tk.Canvas(grid, width=size, height=size, bg=C["panel"], highlightthickness=1,
                                 highlightbackground=C["border"], cursor="hand2")
                tile.create_image(size // 2 + 1, size // 2 + 1, image=ph)
                tile.grid(row=row + j // cols, column=j % cols, padx=3, pady=3)
                tile.bind("<ButtonPress-1>", lambda e, p=p: self._dc_lib_press(e, p))
                tile.bind("<B1-Motion>", self._dc_lib_motion)
                tile.bind("<ButtonRelease-1>", self._dc_lib_release)
                tile.bind("<Button-3>", lambda e, p=p: self._dc_lib_menu(e, p))
                tile.bind("<Enter>", lambda e, t=tile, p=p, l=name: (
                    t.config(highlightbackground=C["accent"]), self.set_status(f"Sticker: {p.stem}  ({l})")))
                tile.bind("<Leave>", lambda e, t=tile: t.config(highlightbackground=C["border"]))
                self._dc_lib_photos.append(ph)
                self._dc_tiles[p] = tile
            row += (len(imgs) + cols - 1) // cols
            if not imgs and self.dc_pack != ALL:
                label(grid, "This pack is empty.\nUse Add… or drop images here.", "small", "muted",
                      justify="left").grid(row=row, column=0, columnspan=cols, padx=6, pady=6, sticky="w")
        if not packs:
            label(grid, "No stickers yet.\nCreate a pack with + New,\nor import a .zip pack.", "small", "muted",
                  justify="left").grid(padx=6, pady=6, sticky="w")
        title = "All stickers" if self.dc_pack == ALL else ("Unsorted" if self.dc_pack == lib.LOOSE else self.dc_pack)
        self.dc_lib_title.config(text=title if len(title) <= 20 else title[:19] + "…")
        self.dc_lib_count.config(text=str(len(self._dc_tiles)))
        self.dc_lib_scroll.canvas.yview_moveto(0)

    def _dc_thumb(self, p, side):
        """Sticker thumbnail, cached until the file changes (the library is redrawn often)."""
        cache = self.__dict__.setdefault("_dc_thumbs", {})
        try:
            st = p.stat()
            key = (str(p), st.st_mtime_ns, st.st_size, side)
        except OSError:
            key = (str(p), 0, 0, side)
        im = cache.get(key)
        if im is None:
            im = Image.open(p)
            im.thumbnail((side, side))
            im = im.convert("RGBA")
            if len(cache) > 2000:
                cache.clear()
            cache[key] = im
        return im

    def _dc_select_pack(self, key):
        if key != self.dc_pack:
            self.dc_pack = key
            self.dc_load_library()

    def _dc_ask_name(self, title, initial=""):
        return simpledialog.askstring(title, "Pack name:", initialvalue=initial, parent=base.root)

    def dc_new_pack(self):
        name = self._dc_ask_name("New sticker pack", DEFAULT_PACK)
        if not name:
            return None
        try:
            key = self.dc_lib.new_pack(name)
        except (OSError, ValueError) as e:
            messagebox.showerror("New sticker pack", str(e))
            return None
        self.dc_pack = key
        self.dc_load_library()
        self.set_status(f"Created pack “{key}”. Use Add… or drop images to fill it.")
        return key

    def dc_rename_pack(self):
        key = self.dc_pack
        if key in (ALL, self.dc_lib.LOOSE):
            return self.set_status("Select a pack to rename it")
        name = self._dc_ask_name("Rename sticker pack", key)
        if not name:
            return
        try:
            self.dc_pack = self.dc_lib.rename_pack(key, name)
        except (OSError, ValueError) as e:
            messagebox.showerror("Rename sticker pack", str(e))
        self.dc_load_library()

    def dc_delete_pack(self):
        key = self.dc_pack
        if key in (ALL, self.dc_lib.LOOSE):
            return self.set_status("Select a pack to delete it")
        from ..stickers import images_in
        n = len(images_in(self.dc_lib.pack_dir(key)))
        if not messagebox.askyesno("Delete sticker pack", f"Delete the pack “{key}”" +
                                   (f" and its {n} sticker(s)?" if n else "?") +
                                   "\n\nTip: export it as a .zip first if you may want it back."):
            return
        try:
            self.dc_lib.delete_pack(key)
        except OSError as e:
            messagebox.showerror("Delete sticker pack", f"{e}\n\nThe folder may contain other files.")
        self.dc_pack = ALL
        self.dc_load_library()

    def dc_export_pack(self):
        key = self.dc_pack
        if key == ALL:
            return self.set_status("Select a pack to export it")
        label_ = "Unsorted" if key == self.dc_lib.LOOSE else key
        f = filedialog.asksaveasfilename(title="Export sticker pack", defaultextension=".zip",
                                         initialfile=f"{label_}.zip", filetypes=[("Sticker pack", "*.zip")])
        if not f:
            return
        try:
            n = self.dc_lib.export_pack(key, Path(f))
        except OSError as e:
            return messagebox.showerror("Export sticker pack", str(e))
        self.set_status(f"Exported {n} sticker(s) to {Path(f).name}")

    def dc_import_pack(self, f=None):
        f = f or filedialog.askopenfilename(title="Import sticker pack", filetypes=[("Sticker pack", "*.zip")])
        if not f:
            return
        import zipfile
        try:
            key, n = self.dc_lib.import_zip(Path(f))
        except (zipfile.BadZipFile, OSError, ValueError) as e:
            return messagebox.showerror("Import sticker pack", f"{Path(f).name}: {e}")
        self.dc_pack = key
        self.dc_load_library()
        self.set_status(f"Imported “{key}” with {n} sticker(s)")

    def _dc_target_pack(self):
        if self.dc_pack != ALL:
            return self.dc_pack
        return self.dc_lib.ensure_pack(DEFAULT_PACK)

    def dc_add_stickers(self):
        if self.dc_lib is None:
            return
        key = self._dc_target_pack()
        files = filedialog.askopenfilenames(title=f"Add images to “{key or 'Unsorted'}”", filetypes=IMG_TYPES)
        if files:
            self._dc_import_stickers(files, key)
        else:
            self.dc_load_library()

    def _dc_import_stickers(self, files, key=None):
        key = self._dc_target_pack() if key is None else key
        added, errors = self.dc_lib.import_images(files, key)
        if errors:
            messagebox.showerror("Cannot add image", "\n".join(f"{n}: {e}" for n, e in errors[:10]))
        self.dc_load_library()
        if added:
            self.set_status(f"Added {added} sticker(s) to “{key or 'Unsorted'}”")

    def _dc_lib_drop(self, e):
        files = base.root.tk.splitlist(e.data)
        zips = [f for f in files if f.lower().endswith(".zip")]
        for z in zips:
            self.dc_import_pack(z)
        rest = [f for f in files if f not in zips]
        if rest:
            self._dc_import_stickers(rest)
        return e.action

    def _dc_lib_menu(self, e, p):
        m = tk.Menu(base.root, tearoff=0, bg=C["panel"], fg=C["text"], activebackground=C["btnh"],
                    activeforeground=C["text"], bd=0)
        m.add_command(label="Add to board", command=lambda: self.dc_add_sticker(p))
        mv = tk.Menu(m, tearoff=0, bg=C["panel"], fg=C["text"], activebackground=C["btnh"],
                     activeforeground=C["text"], bd=0)
        here = p.parent.resolve()
        for _k, d, name in self.dc_lib.packs():
            if d.resolve() != here:
                mv.add_command(label=name, command=lambda d=d: self._dc_lib_move(p, d))
        mv.add_separator()
        mv.add_command(label="New pack…", command=lambda: self._dc_lib_move_new(p))
        m.add_cascade(label="Move to pack", menu=mv)
        m.add_separator()
        m.add_command(label="Remove from library…", command=lambda: self._dc_lib_remove(p))
        m.tk_popup(e.x_root, e.y_root)

    def _dc_lib_move(self, p, d):
        try:
            self.dc_lib.move(p, d)
        except OSError as e:
            messagebox.showerror("Move sticker", str(e))
        self.dc_load_library()

    def _dc_lib_move_new(self, p):
        cur = self.dc_pack
        key = self.dc_new_pack()
        if key:
            self._dc_lib_move(p, self.dc_lib.pack_dir(key))
            self.dc_pack = cur if cur != ALL else key
            self.dc_load_library()

    def _dc_lib_remove(self, p):
        if messagebox.askyesno("Remove sticker", f"Remove {p.name} from the sticker library?\n\n"
                               "This deletes the file from its pack folder."):
            try:
                self.dc_lib.remove(p)
            except (OSError, ValueError) as e:
                messagebox.showerror("Remove sticker", str(e))
            self.dc_load_library()

    # drag a sticker from the library onto the board
    def _dc_lib_press(self, e, p):
        self._dc_lib_drag = {"path": p, "x": e.x_root, "y": e.y_root, "moved": False}

    def _dc_lib_motion(self, e):
        d = self._dc_lib_drag
        if not d:
            return
        if abs(e.x_root - d["x"]) + abs(e.y_root - d["y"]) > 6:
            d["moved"] = True
        x, y = e.x_root - self.dc_cv.winfo_rootx(), e.y_root - self.dc_cv.winfo_rooty()
        inside = 0 <= x < self.dc_cv.winfo_width() and 0 <= y < self.dc_cv.winfo_height()
        if d["moved"] and inside:
            if d.get("ghost") != d["path"]:
                im = Image.open(d["path"]).convert("RGBA")
                im.thumbnail((110, 110))
                im.putalpha(im.split()[3].point(lambda v: v * 3 // 4))
                self._dc_ghost_photo = ImageTk.PhotoImage(im)
                d["ghost"] = d["path"]
                self.dc_cv.itemconfig(self._dc_ghost_item, image=self._dc_ghost_photo)
            self.dc_cv.coords(self._dc_ghost_item, x, y)
            self.dc_cv.itemconfig(self._dc_ghost_item, state="normal")
            self.dc_cv.tag_raise(self._dc_ghost_item)
            t = self._dc_texel(x, y)
            self.set_status("Release to place the sticker here" if self._dc_part(t) == ("deck", None)
                            else "Drop it on the top of the deck")
        else:
            self.dc_cv.itemconfig(self._dc_ghost_item, state="hidden")

    def _dc_lib_release(self, e):
        d, self._dc_lib_drag = self._dc_lib_drag, None
        self.dc_cv.itemconfig(self._dc_ghost_item, state="hidden")
        if not d:
            return
        if not d["moved"]:
            return self.dc_add_sticker(d["path"])
        at = self._dc_texel_at_root(e.x_root, e.y_root)
        if at is not None:
            self.dc_add_sticker(d["path"], at)
        else:
            self.set_status("Drop stickers on the top of the deck (or the flat texture)")

    def _dc_texel_at_root(self, xr, yr):
        name = base.widget_path_at(xr, yr)
        if name == str(self.dc_cv):
            t = self._dc_texel(xr - self.dc_cv.winfo_rootx(), yr - self.dc_cv.winfo_rooty(), radius=0)
            return t if self._dc_part(t) == ("deck", None) else None
        if name == str(self.dc_flat):
            return self._dc_flat_xy(xr - self.dc_flat.winfo_rootx(), yr - self.dc_flat.winfo_rooty())
        return None

    # ------------------------------------------------------------------ textures (base)
    def dc_load_textures(self):
        inner = self.dc_tex_scroll.inner
        for w in inner.winfo_children():
            w.destroy()
        self._dc_tex_rows = {}
        W, H = (self.dc.size if self.dc else (1920, 432))
        mask = self._v3_mask_for((W, H))
        items = [(basetex.ORIGINAL, "Board's own art")] + [(k, l) for k, l, _f in basetex.BUILTIN] + \
                [(k, l) for k, l, _p in basetex.user_textures()]
        for key, name in items:
            fr = tk.Frame(inner, bg=C["panel"], highlightthickness=1, highlightbackground=C["border"], cursor="hand2")
            fr.pack(fill="x", padx=4, pady=3)
            ph = self._dc_tex_photos.get((key, W, H))
            if ph is None:
                try:
                    if key == basetex.ORIGINAL:
                        src = self.dc.original if self.dc else Image.new("RGBA", (W, H), (0, 0, 0, 255))
                        img = src.convert("RGB")
                        if mask is not None:
                            img = Image.composite(img, Image.new("RGB", (W, H), _rgb(C["bg"])[:3]), mask)
                        pv = img.resize((236, 53), Image.LANCZOS)
                    else:
                        pv = basetex.preview(key, W, H, mask, (236, 53), _rgb(C["bg"])[:3])
                    ph = ImageTk.PhotoImage(pv)
                except Exception:
                    ph = None
                if key != basetex.ORIGINAL:
                    self._dc_tex_photos[(key, W, H)] = ph
                else:
                    self._dc_orig_photo = ph
            lab = tk.Label(fr, image=ph, bg=C["panel"], bd=0) if ph else tk.Label(fr, text="(cannot read)", bg=C["panel"], fg=C["muted"])
            lab.pack(fill="x", padx=6, pady=(6, 2))
            nr = tk.Frame(fr, bg=C["panel"])
            nr.pack(fill="x", padx=6, pady=(0, 6))
            nm = tk.Label(nr, text=name, bg=C["panel"], fg=C["sub"], font=F["small"], anchor="w")
            nm.pack(side="left")
            use = tk.Label(nr, text="", bg=C["panel"], fg=C["warn"], font=F["smallbold"])
            use.pack(side="right")
            for w in (fr, lab, nr, nm):
                w.bind("<Button-1>", lambda e, k=key: self.dc_set_base(k))
            self._dc_tex_rows[key] = (fr, nm, use)
        self._dc_mark_base()

    def _dc_mark_base(self):
        cur = self.dc.base_key if self.dc else None
        for key, (fr, nm, use) in getattr(self, "_dc_tex_rows", {}).items():
            on = key == cur
            fr.config(highlightbackground=C["accent"] if on else C["border"])
            nm.config(fg=C["text"] if on else C["sub"], font=F["smallbold" if on else "small"])
            use.config(text="In use" if on else "")
        if self.dc:
            self.dc_tint.set(round(self.dc.tint_strength * 100))
            self.dc_tint_val.config(text=f"{self.dc_tint.get():.0f}%")
        self._dc_draw_tint()

    def _dc_draw_tint(self):
        sw = self.dc_tint_sw
        sw.delete("all")
        col = self.dc.tint if self.dc and self.dc.tint else (240, 168, 48)
        sw.create_rectangle(0, 0, 30, 20, fill=to_hex(col), outline="")

    def dc_set_base(self, key):
        s = self.dc
        if s is None or key == s.base_key:
            return
        self._dc_push("base")
        s.base_key = key
        self._dc_apply_base(final=True)
        self.set_status(f"Base texture: {basetex.label_of(key)}")

    def _dc_apply_base(self, final=False, fast=False):
        s = self.dc
        if s is None:
            return
        W, H = s.size
        try:
            s.base_img = basetex.make_base(s.base_key, W, H, s.original, s.tint, s.tint_strength)
            s.base_regen = True
        except Exception as e:
            messagebox.showerror("Base texture", f"Cannot use {basetex.label_of(s.base_key)}: {e}")
            s.base_key, s.base_img = basetex.ORIGINAL, s.original
        s.composer.invalidate()
        self._dc_mark_base()
        self.dc_changed(fast=fast)

    def dc_pick_tint(self):
        s = self.dc
        if s is None:
            return
        rgb, _hx = colorchooser.askcolor(color=to_hex(s.tint or (240, 168, 48)), parent=base.root, title="Tint color")
        if rgb:
            self._dc_push("tint")
            s.tint = tuple(int(round(v)) for v in rgb[:3])
            if s.tint_strength == 0:
                s.tint_strength = 0.5
            self._dc_apply_base(final=True)

    def _dc_tint_moved(self, _v=None):
        s = self.dc
        self.dc_tint_val.config(text=f"{self.dc_tint.get():.0f}%")
        if s is None:
            return
        v = self.dc_tint.get() / 100
        if abs(v - s.tint_strength) > 1e-3:
            s.tint_strength = v
            if s.tint is None:
                s.tint = (240, 168, 48)
            self._dc_apply_base(fast=True)

    def dc_add_textures(self):
        files = filedialog.askopenfilenames(title="Add base textures", filetypes=IMG_TYPES)
        if files:
            self._dc_import_textures(files)

    def _dc_import_textures(self, files):
        added, errors = basetex.add_user_textures(files)
        if errors:
            messagebox.showerror("Cannot add texture", "\n".join(f"{n}: {e}" for n, e in errors[:10]))
        self.dc_load_textures()
        if added:
            self.set_status(f"Added {added} texture(s) to {basetex.texture_dir()}")

    # ------------------------------------------------------------------ layers
    def dc_add_sticker(self, path, at=None):
        if self.dc is None:
            return self.set_status("Pick a board first")
        try:
            src = self._dc_open_src(path)
        except Exception as e:
            return messagebox.showerror("Cannot open image", str(e))
        W, H = self.dc.size
        self._dc_add_layer(src, Path(path).stem, sticker_adjust(src, W, H, at))

    def dc_ask_image(self):
        f = filedialog.askopenfilename(title="Image to place on the board", filetypes=IMG_TYPES)
        if f:
            self.dc_load_image(f)

    def _dc_on_drop(self, e):
        files = base.root.tk.splitlist(e.data)
        at = None
        try:
            at = self._dc_texel_at_root(int(e.x_root), int(e.y_root))
        except Exception:
            pass
        for k, f in enumerate(files):
            self.dc_load_image(f, at if k == 0 else None)
        return e.action

    def dc_load_image(self, f, at=None):
        if self.dc is None:
            return self.set_status("Pick a board first")
        try:
            src = self._dc_open_src(f)
        except Exception as e:
            return messagebox.showerror("Cannot open image", str(e))
        W, H = self.dc.size
        self._dc_add_layer(src, Path(f).stem, new_image_adjust(src, W, H, at))

    def _dc_open_src(self, path):
        """Image for a new layer. Very large images are reduced (a board is only ~1920 px wide,
        so nothing visible is lost), and the same file is loaded only once while it is in use."""
        import weakref
        cache = self.__dict__.setdefault("_dc_srcs", weakref.WeakValueDictionary())
        p = Path(path)
        try:
            st = p.stat()
            key = (str(p.resolve()), st.st_mtime_ns, st.st_size)
        except OSError:
            key = None
        im = cache.get(key) if key else None
        if im is None:
            im = Image.open(p)
            im.load()
            im = im.convert("RGBA")
            W, H = self.dc.size if self.dc else (1920, 432)
            lim = max(2560, int(max(W, H) * 1.34))
            if max(im.size) > lim:
                im.thumbnail((lim, lim), Image.LANCZOS)
            if key:
                cache[key] = im
        return im

    def _dc_add_layer(self, src, name, adj):
        s = self.dc
        self._dc_push("add")
        L = Layer(src, name, adj)
        s.layers.append(L)
        s.sel = L
        self.dc_opacity.set(100)
        if self.dc_mode.get() != "place":
            self.dc_mode.set("place")
        s.composer.invalidate()
        self.dc_changed(rebuild_list=True)
        self.set_status(f"Added {name}. Drag it on the board to move, wheel to scale, Shift+wheel to rotate.")

    def dc_select_layer(self, L):
        s = self.dc
        if s is None or L is s.sel:
            return
        s.sel = L
        s.composer.invalidate()
        if L is not None:
            self.dc_opacity.set(round(L.opacity * 100))
        self.dc_changed(rebuild_list=True)

    def dc_move_layer(self, d):
        s = self.dc
        if s is None or s.sel is None:
            return
        i = s.layers.index(s.sel)
        j = max(0, min(len(s.layers) - 1, i + d))
        if i != j:
            self._dc_push("order")
            s.layers.insert(j, s.layers.pop(i))
            s.composer.invalidate()
            self.dc_changed(rebuild_list=True)

    def dc_duplicate(self):
        s = self.dc
        if s is None or s.sel is None:
            return
        L = s.sel
        W, H = s.size
        adj = dataclasses.replace(L.adj)
        cx, cy = L.center(W, H)
        adj.cx, adj.cy = cx + W * 0.04, cy + H * 0.06
        self._dc_push("add")
        N = Layer(L.src, L.name, adj, L.opacity)
        s.layers.insert(s.layers.index(L) + 1, N)
        s.sel = N
        s.composer.invalidate()
        self.dc_changed(rebuild_list=True)

    def dc_delete_layer(self):
        s = self.dc
        if s is None or s.sel is None:
            return
        self._dc_push("delete")
        i = s.layers.index(s.sel)
        s.layers.remove(s.sel)
        s.sel = s.layers[min(i, len(s.layers) - 1)] if s.layers else None
        s.composer.invalidate()
        self.dc_changed(rebuild_list=True)

    def dc_toggle_visible(self, L):
        self._dc_push("visible")
        L.visible = not L.visible
        self.dc.composer.invalidate()
        self.dc_changed(rebuild_list=True)

    def dc_set_fit(self, mode):
        s = self.dc
        if s is None or s.sel is None:
            return
        self._dc_push("fit")
        s.sel.adj.mode, s.sel.adj.zoom = mode, 1.0
        if mode == "fill":
            s.sel.adj.cx = s.sel.adj.cy = None
        self.dc_changed()

    def dc_rotate(self, deg):
        s = self.dc
        if s and s.sel is not None:
            self._dc_push("rotate90")
            s.sel.adj.angle = (s.sel.adj.angle + deg) % 360
            self.dc_changed()

    def dc_flip(self):
        s = self.dc
        if s and s.sel is not None:
            self._dc_push("flip")
            s.sel.adj.flip_h = not s.sel.adj.flip_h
            self.dc_changed()

    def _dc_opacity_moved(self, _v=None):
        s = self.dc
        self.dc_op_val.config(text=f"{self.dc_opacity.get():.0f}%" if s and s.sel else "")
        if s and s.sel is not None and abs(s.sel.opacity - self.dc_opacity.get() / 100) > 1e-6:
            s.sel.opacity = self.dc_opacity.get() / 100
            self.dc_changed(fast=True)

    def _dc_scale_at(self, p, f):
        L, W, H = self.dc.sel, *self.dc.size
        z = min(20.0, max(0.03, L.adj.zoom * f))
        f = z / L.adj.zoom
        cx, cy = L.center(W, H)
        L.adj.zoom = z
        L.adj.cx, L.adj.cy = p[0] + (cx - p[0]) * f, p[1] + (cy - p[1]) * f
        self.dc_changed(fast=True)

    def _dc_rotate_at(self, p, deg):
        L, W, H = self.dc.sel, *self.dc.size
        cx, cy = L.center(W, H)
        t = math.radians(deg)
        dx, dy = cx - p[0], cy - p[1]
        L.adj.cx = p[0] + dx * math.cos(t) - dy * math.sin(t)
        L.adj.cy = p[1] + dx * math.sin(t) + dy * math.cos(t)
        L.adj.angle = (L.adj.angle + deg) % 360
        self.dc_changed(fast=True)

    def _dc_layer_at(self, t):
        if t is None or self.dc is None:
            return None
        for L in reversed(self.dc.layers):
            if L.hit(*t):
                return L
        return None

    def dc_clear(self):
        s = self.dc
        if s is None or not (s.layers or s.base_key != basetex.ORIGINAL or self._pal_changed()):
            return
        self._dc_push("clear")
        s.layers, s.sel = [], None
        s.base_key, s.tint, s.tint_strength, s.base_img = basetex.ORIGINAL, None, 0.0, s.original
        if self.pal_orig:
            self.pal = list(self.pal_orig)
        s.composer.invalidate()
        self._dc_mark_base()
        self._draw_palette()
        self.dc_changed(rebuild_list=True)
        self.set_status("Cleared. Ctrl+Z brings it back.")

    # -- undo
    def _dc_state(self):
        s = self.dc
        return ([L.snapshot() for L in s.layers], s.sel, list(self.pal) if self.pal else None,
                s.base_key, s.tint, s.tint_strength)

    def _dc_push(self, kind):
        s = self.dc
        if s is None:
            return
        now = time.monotonic()
        if kind in ("wheel", "opacity", "tint") and s.last_undo[0] == kind and now - s.last_undo[1] < 0.8:
            s.last_undo = (kind, now)
            return
        s.last_undo = (kind, now)
        s.undo.append(self._dc_state())
        del s.undo[:-80]
        s.redo.clear()

    def _dc_restore(self, st):
        s = self.dc
        snaps, sel, pal, bkey, tint, strength = st
        s.layers = []
        for L, adj, op, vis, name in snaps:
            L.adj, L.opacity, L.visible, L.name = dataclasses.replace(adj), op, vis, name
            s.layers.append(L)
        s.sel = sel if sel in s.layers else None
        if pal is not None:
            self.pal = list(pal)
            self._draw_palette()
        rebase = (bkey, tint, strength) != (s.base_key, s.tint, s.tint_strength)
        s.base_key, s.tint, s.tint_strength = bkey, tint, strength
        if s.sel is not None:
            self.dc_opacity.set(round(s.sel.opacity * 100))
        if rebase:
            self._dc_apply_base(final=True)
        s.composer.invalidate()
        self.dc_changed(rebuild_list=True)

    def dc_undo(self):
        s = self.dc
        if s and s.undo:
            s.redo.append(self._dc_state())
            self._dc_restore(s.undo.pop())
            s.last_undo = (None, 0.0)

    def dc_redo(self):
        s = self.dc
        if s and s.redo:
            s.undo.append(self._dc_state())
            self._dc_restore(s.redo.pop())
            s.last_undo = (None, 0.0)

    # ------------------------------------------------------------------ colors
    def _dc_pick_color(self, k):
        if self.pal is None:
            return
        old = list(self.pal)
        self.pick_color(k)                         # the app's own color picker (shared colors)
        if self.pal != old and self.dc:
            cur = list(self.pal)
            self.pal = old
            self._dc_push("color")
            self.pal = cur
            self._draw_palette()

    def _dc_draw_colors(self):
        if not hasattr(self, "dc_swatches"):
            return
        changed = set(self._pal_changed())
        for k, (sw, nm, hx) in enumerate(self.dc_swatches):
            sw.delete("all")
            if not self.pal:
                hx.config(text="")
                continue
            w, h = max(10, sw.winfo_width()), max(10, sw.winfo_height())
            sw.create_rectangle(0, 0, w + 4, h + 4, fill=to_hex(self.pal[k]), outline="")
            if k in changed:
                sw.create_polygon(w - 2, h * 0.35, w - 2, h - 2, w * 0.7, h - 2,
                                  fill=to_hex(self.pal_orig[k]), outline="")
            hx.config(text=to_hex(self.pal[k]), fg=C["warn"] if k in changed else C["muted"])

    def dc_palette_changed(self):
        """Called by the app whenever the (shared) board colors change."""
        if not hasattr(self, "dc_swatches"):
            return
        self._dc_draw_colors()
        if self.dc is not None and self.tab_var.get() == "decor":
            self.dc_changed()

    # ------------------------------------------------------------------ composing + 3D
    def dc_compose(self, fast=False):
        """Composes the texture. Returns the changed rectangle (texture pixels) when only part of
        it changed (dragging), else None."""
        import numpy as np
        s = self.dc
        if s is None:
            return None
        work = s.composer.compose(s.base_img, s.layers, s.sel, self.pal, fast)
        s.work = work
        region = s.composer.last_region
        outline = s.sel is not None and self.dc_mode.get() == "place"
        ta = self.dc_texarr
        if region is not None and ta is not None and ta.shape[:2] == (work.height, work.width) \
                and ta.flags.writeable:
            # update just the changed rectangle of the display texture (with the selection outline)
            x0, y0, x1, y1 = region
            part = work.crop(region)
            if outline and s.sel.visible:
                W, H = work.size
                pts = [(x - x0, y - y0) for x, y in s.sel.corners(W, H)]
                ImageDraw.Draw(part).line(pts + [pts[0]], fill=_rgb(C["accent"])[:3] + (255,), width=max(3, W // 400))
            arr = np.asarray(part.convert("RGB"))
            ta[y0:y1, x0:x1] = arr
            if self.pal and y0 == 0 and x0 < len(self.pal):
                for x, c in enumerate(self.pal[:min(len(self.pal), work.width)]):
                    ta[0, x] = c[:3]
            return region
        disp = with_outline(work, s.sel, _rgb(C["accent"]), self.pal) if outline else work
        self.dc_texarr = np.array(disp.convert("RGB"))        # writable: dragging updates it in place
        return None

    def dc_changed(self, fast=False, rebuild_list=False):
        """Texture edited, camera unchanged: re-texture the last 3D frame (no new rasterizing)."""
        from ..board3d import retexture, retexture_region
        if self.dc is None:
            return
        region = self.dc_compose(fast)
        if self.dc_info is not None and self.dc_info.get("tex_size") == self.dc.size:
            if region is not None:
                self._dc_show(retexture_region(self.dc_info, self.dc_texarr, region))
            else:
                self._dc_show(retexture(self.dc_info, self.dc_texarr))
        else:
            self.dc_render()
        if fast:
            # while dragging, the flat texture view is redrawn at most ~11 times a second
            if getattr(self, "_dc_flat_job", None) is None:
                self._dc_flat_job = base.root.after(90, self._dc_flat_due)
        else:
            self.dc_draw_flat()
        if rebuild_list:
            self._dc_rebuild_layers()
        self._dc_refresh_controls()
        if fast:
            if self._dc_sharp:
                base.root.after_cancel(self._dc_sharp)
            self._dc_sharp = base.root.after(200, self._dc_sharpen)

    def _dc_flat_due(self):
        self._dc_flat_job = None
        self.dc_draw_flat()

    def _dc_sharpen(self):
        self._dc_sharp = None
        if self._dc_drag is None and self.dc is not None:
            self.dc.composer.invalidate()
            self.dc_changed()

    def _dc_schedule_update(self):
        if self._dc_upd is None:
            self._dc_upd = base.root.after_idle(self._dc_run_update)

    def _dc_run_update(self):
        self._dc_upd = None
        self.dc_changed(fast=True)

    def dc_render(self, fast=False):
        if not hasattr(self, "dc_cv") or self.tab_var.get() != "decor":
            return
        if self.v3_model is None:
            return self._dc_msg(self.v3_err or "Board model not found")
        if self.dc is None or self.dc_texarr is None:
            return
        W, H = max(200, self.dc_cv.winfo_width()), max(150, self.dc_cv.winfo_height())
        s = min(1.0, (1300 * 760 / float(W * H)) ** 0.5) * (0.5 if fast else 1.0)
        self.dc_renderer.request(model=self.v3_model, tex=self.dc_texarr, yaw=self.dc_yaw, pitch=self.dc_pitch,
                                 zoom=self.dc_zoom, W=max(1, int(W * s)), H=max(1, int(H * s)),
                                 screws=self.v3_screws.get(), outline=self.v3_outline.get(),
                                 bg=_rgb(C["bg"])[:3], canvas=(W, H), fast=fast)

    def _dc_poll(self):
        from ..board3d import retexture
        try:
            while True:
                job, img, info, ms = self.dc_renderer.results.get_nowait()
                if not hasattr(self, "dc_cv") or not self.dc_cv.winfo_exists():
                    continue
                if isinstance(img, Exception):
                    self._dc_msg(f"3D preview failed: {img}")
                    continue
                if (job["yaw"], job["pitch"], job["zoom"]) != (self.dc_yaw, self.dc_pitch, self.dc_zoom) \
                        and not job["fast"]:
                    continue
                if not job["fast"]:
                    self.dc_info = info
                    self.dc_info_scale = job["W"] / float(job["canvas"][0])
                    if self.dc_texarr is not None \
                            and info.get("tex_size") == (self.dc_texarr.shape[1], self.dc_texarr.shape[0]):
                        img = retexture(info, self.dc_texarr)    # the texture may have changed meanwhile
                self._dc_show(img, job["canvas"])
        except queue.Empty:
            pass
        except tk.TclError:
            pass
        if self.tab_var.get() == "decor":
            base.root.after(15, self._dc_poll)
        else:
            self._dc_polling = False

    def _dc_show(self, img, canvas=None):
        c = self.dc_cv
        W, H = canvas or (c.winfo_width(), c.winfo_height())
        if img.size != (W, H):
            img = img.resize((W, H), Image.NEAREST if img.width * 1.5 < W else Image.BILINEAR)
        ph = self._dc_photo
        if ph is not None and (ph.width(), ph.height()) == img.size:
            ph.paste(img)
        else:
            self._dc_photo = ImageTk.PhotoImage(img)
            c.itemconfig(self._dc_img_item, image=self._dc_photo)
        c.itemconfig(self._dc_msg_item, text="")

    def _dc_msg(self, text):
        if not hasattr(self, "dc_cv"):
            return
        c = self.dc_cv
        c.coords(self._dc_msg_item, max(100, c.winfo_width() / 2), max(60, c.winfo_height() / 2))
        c.itemconfig(self._dc_msg_item, text=text)
        if self._dc_photo is not None:
            c.itemconfig(self._dc_img_item, image="")
            self._dc_photo = None

    def _dc_view(self, yaw, pitch):
        self.dc_yaw, self.dc_pitch = yaw, pitch
        self.dc_info = None
        self.dc_render()

    # ------------------------------------------------------------------ picking + mouse
    def _dc_texel(self, x, y, radius=2):
        from ..board3d import pick_texel
        if self.dc_info is None:
            return None
        s = self.dc_info_scale
        return pick_texel(self.dc_info, int(x * s), int(y * s), radius)

    @staticmethod
    def _dc_part(t):
        if t is None:
            return None
        if t[1] == 0 and t[0] < len(PART_NAMES):
            return "palette", t[0]
        return "deck", None

    def _dc_on_hover(self, e):
        if self._dc_drag is not None or self.dc is None:
            return
        t = self._dc_texel(e.x, e.y)
        self._dc_set_hover(t)
        part = self._dc_part(t)
        if part is None:
            self.dc_cv.config(cursor="fleur")
            return
        if part[0] == "palette":
            self.dc_cv.config(cursor="hand2")
            if self.pal:
                self.set_status(f"{PART_NAMES[part[1]]}  {to_hex(self.pal[part[1]])}  — click to change")
            return
        L = self._dc_layer_at(t) if self.dc_mode.get() == "place" else None
        self.dc_cv.config(cursor="fleur" if L else "arrow")
        self.set_status(f"{L.name} — drag to move, wheel to scale, Shift+wheel to rotate" if L else
                        f"Deck top · texture pixel {t[0]}, {t[1]}")

    def _dc_set_hover(self, t):
        self._dc_hover = t
        self._dc_draw_marker()

    def _dc_press(self, e, btn):
        if self.dc is None:
            return
        t = self._dc_texel(e.x, e.y, radius=0)
        L = None
        if btn == 1 and self.dc_mode.get() == "place" and self._dc_part(t) == ("deck", None):
            L = self._dc_layer_at(t)
            if L is not self.dc.sel:
                self.dc_select_layer(L)
        if L is not None:
            self._dc_push("move")
        W, H = self.dc.size
        self._dc_drag = {"x": e.x, "y": e.y, "x0": e.x, "y0": e.y, "btn": btn, "moved": False,
                         "layer": L, "t0": t, "c0": L.center(W, H) if L else None}

    def _dc_move(self, e):
        d = self._dc_drag
        if d is None:
            return
        if abs(e.x - d["x0"]) + abs(e.y - d["y0"]) > 3:
            d["moved"] = True
        L = d["layer"]
        if L is not None:
            t = self._dc_texel(e.x, e.y, radius=0)
            if t is not None and self._dc_part(t) == ("deck", None):
                L.adj.cx = d["c0"][0] + (t[0] - d["t0"][0])
                L.adj.cy = d["c0"][1] + (t[1] - d["t0"][1])
                self._dc_schedule_update()
            return
        dx, dy = e.x - d["x"], e.y - d["y"]
        d["x"], d["y"] = e.x, e.y
        self.dc_yaw = (self.dc_yaw + dx * 0.5) % 360
        self.dc_pitch = max(-89.0, min(89.0, self.dc_pitch + dy * 0.4))
        self.dc_info = None
        self.dc_render(fast=True)

    def _dc_release(self, e):
        d, self._dc_drag = self._dc_drag, None
        if d is None or self.dc is None:
            return
        if not d["moved"]:
            if d["layer"] is not None and self.dc.undo:
                self.dc.undo.pop()                  # a click that only selected
            part = self._dc_part(self._dc_texel(e.x, e.y))
            if part and part[0] == "palette":
                self._dc_pick_color(part[1])
            elif d["btn"] == 1 and self.dc_mode.get() == "place" and d["layer"] is None:
                self.dc_select_layer(None)
            return
        if d["layer"] is not None:
            self._dc_sharpen()
        else:
            self.dc_render()

    def _dc_end_drag(self):
        self._dc_drag = None
        self._dc_sharpen()

    def _dc_wheel(self, e, direction):
        s = self.dc
        if s is not None and self.dc_mode.get() == "place" and s.sel is not None:
            t = self._dc_texel(e.x, e.y)
            if self._dc_part(t) == ("deck", None) and (self._dc_layer_at(t) is s.sel or s.sel.hit(*t)):
                self._dc_push("wheel")
                if e.state & 0x0001:
                    self._dc_rotate_at(t, 5 * direction)
                else:
                    self._dc_scale_at(t, 1.1 if direction > 0 else 1 / 1.1)
                return
        self.dc_zoom = max(0.4, min(4.0, self.dc_zoom * (1.1 if direction > 0 else 1 / 1.1)))
        self.dc_info = None
        self.dc_render(fast=True)
        if self._dc_sharp:
            base.root.after_cancel(self._dc_sharp)
        self._dc_sharp = base.root.after(220, lambda: (setattr(self, "_dc_sharp", None), self.dc_render()))

    # ------------------------------------------------------------------ flat texture view
    def _dc_flat_k(self):
        if self.dc is None:
            return None
        cw = max(50, self.dc_flat.winfo_width())
        W, H = self.dc.size
        k = cw / W
        h = max(20, int(H * k))
        if int(float(self.dc_flat.cget("height"))) != h:
            self.dc_flat.config(height=h)
        return k

    def dc_draw_flat(self):
        if not hasattr(self, "dc_flat"):
            return
        k = self._dc_flat_k()
        self.dc_flat.delete("img")
        if not k:
            return
        s = self.dc
        W, H = s.size
        small = s.work.resize((max(1, int(W * k)), max(1, int(H * k))), Image.BILINEAR)
        small = Image.alpha_composite(Image.new("RGBA", small.size, _rgb(C["chk1"])[:3] + (255,)), small)
        if self._dc_mask is not None:
            mk = getattr(self, "_dc_mask_small", None)
            if mk is None or mk[0] != (id(self._dc_mask), small.size):
                inv = self._dc_mask.resize(small.size, Image.BILINEAR).point(lambda v: 255 - v)
                mk = self._dc_mask_small = ((id(self._dc_mask), small.size), inv,
                                            Image.new("RGBA", small.size, (0, 0, 0, 150)))
            small.paste(mk[2], (0, 0), mk[1])
        if self.dc_mode.get() == "place":
            d = ImageDraw.Draw(small)
            for L in s.layers:
                if L.visible:
                    pts = L.corners(W, H, k)
                    on = L is s.sel
                    d.line(pts + [pts[0]], fill=_rgb(C["accent"] if on else C["muted"])[:3], width=2 if on else 1)
        self._dc_flat_photo = ImageTk.PhotoImage(small)
        self.dc_flat.create_image(0, 0, anchor="nw", image=self._dc_flat_photo, tags="img")
        self.dc_flat.tag_lower("img")
        self._dc_draw_marker()

    def _dc_draw_marker(self):
        if not hasattr(self, "dc_flat"):
            return
        self.dc_flat.delete("mark")
        k = self._dc_flat_k() if self.dc else None
        if not k or self._dc_hover is None:
            return
        x, y = self._dc_hover[0] * k, self._dc_hover[1] * k
        col = C["accent"]
        self.dc_flat.create_line(x - 9, y, x + 9, y, fill=col, width=2, tags="mark")
        self.dc_flat.create_line(x, y - 9, x, y + 9, fill=col, width=2, tags="mark")
        self.dc_flat.create_oval(x - 4, y - 4, x + 4, y + 4, outline=col, tags="mark")

    def _dc_flat_xy(self, x, y):
        k = self._dc_flat_k()
        if not k:
            return None
        W, H = self.dc.size
        tx, ty = x / k, y / k
        return (tx, ty) if 0 <= tx < W and 0 <= ty < H else None

    def _dc_flat_hover(self, e):
        t = self._dc_flat_xy(e.x, e.y)
        if t is not None and self._dc_drag is None:
            self._dc_hover = (int(t[0]), int(t[1]))
            self._dc_draw_marker()
            L = self._dc_layer_at(t)
            self.set_status(f"{L.name} — drag to move" if L else f"Texture pixel {int(t[0])}, {int(t[1])}")

    def _dc_flat_press(self, e):
        t = self._dc_flat_xy(e.x, e.y)
        if t is None or self.dc is None:
            return
        L = self._dc_layer_at(t)
        if L is None:
            return self.dc_select_layer(None)
        if self.dc_mode.get() != "place":
            self.dc_mode.set("place")
        self.dc_select_layer(L)
        self._dc_push("move")
        W, H = self.dc.size
        self._dc_drag = {"flat": True, "layer": L, "t0": t, "c0": L.center(W, H)}

    def _dc_flat_move(self, e):
        d = self._dc_drag
        t = self._dc_flat_xy(e.x, e.y)
        if d and d.get("flat") and t is not None:
            d["layer"].adj.cx = d["c0"][0] + t[0] - d["t0"][0]
            d["layer"].adj.cy = d["c0"][1] + t[1] - d["t0"][1]
            self._dc_schedule_update()

    def _dc_flat_wheel(self, e, direction):
        t = self._dc_flat_xy(e.x, e.y)
        if t is None or self.dc is None or self.dc.sel is None:
            return
        self._dc_push("wheel")
        if e.state & 0x0001:
            self._dc_rotate_at(t, 5 * direction)
        else:
            self._dc_scale_at(t, 1.1 if direction > 0 else 1 / 1.1)

    # ------------------------------------------------------------------ panel state
    def _dc_rebuild_layers(self):
        inner = self.dc_layer_scroll.inner
        for w in inner.winfo_children():
            w.destroy()
        s = self.dc
        if s is None or not s.layers:
            label(inner, "No layers yet. Drag a sticker onto the board.", "small", "muted",
                  bg=C["bg"]).pack(anchor="w", padx=8, pady=8)
        for L in reversed(s.layers if s else []):           # top layer first
            on = L is s.sel
            bg = C["selfill"] if on else C["bg"]
            row = tk.Frame(inner, bg=bg, cursor="hand2")
            row.pack(fill="x", pady=1)
            if L.thumb is None:
                im = L.src.copy()
                im.thumbnail((40, 26))
                L.thumb = ImageTk.PhotoImage(im)
            th = tk.Label(row, image=L.thumb, bg=bg, width=44, height=28)
            th.pack(side="left", padx=(4, 6), pady=2)
            nm = tk.Label(row, text=L.name, bg=bg, fg=C["text"] if L.visible else C["dis"],
                          font=F["bold" if on else "body"], anchor="w")
            nm.pack(side="left", fill="x", expand=True)
            eye = tk.Label(row, text="Shown" if L.visible else "Hidden", bg=bg,
                           fg=C["sub"] if L.visible else C["dis"], font=F["small"], cursor="hand2")
            eye.pack(side="right", padx=8)
            eye.bind("<Button-1>", lambda e, L=L: self.dc_toggle_visible(L))
            for w in (row, th, nm):
                w.bind("<Button-1>", lambda e, L=L: (self.dc_mode.set("place"), self.dc_select_layer(L)))

    def _dc_mode_changed(self):
        if self.dc is not None:
            self.dc_changed()
        self._dc_refresh_controls()

    def _dc_refresh_all(self):
        if not hasattr(self, "dc_cv"):
            return
        self._dc_rebuild_layers()
        self._dc_mark_base()
        self._dc_draw_colors()
        self.dc_draw_flat()
        self._dc_refresh_controls()

    def _dc_refresh_controls(self):
        if not hasattr(self, "dc_cv"):
            return
        s = self.dc
        on = s is not None and s.sel is not None
        set_state(self.dc_sel_btns, on)
        self.dc_op_scale.state(["!disabled"] if on else ["disabled"])
        self.dc_op_val.config(text=f"{self.dc_opacity.get():.0f}%" if on else "")
        dirty = s is not None and (s.dirty() or bool(self._pal_changed()))
        set_state([self.dc_b_save], s is not None)
        set_state([self.dc_b_clear], s is not None and (bool(s.layers) or s.base_key != basetex.ORIGINAL
                                                         or bool(self._pal_changed())))
        set_state([self.dc_b_undo], bool(s and s.undo))
        set_state([self.dc_b_redo], bool(s and s.redo))
        if s is None:
            self.dc_title.config(text="No board selected")
            self.dc_chip.config(text="")
            self.dc_tex_file.config(text="")
            self.dc_changes.config(text="")
        else:
            name = self.boards[self.sel].name if self.sel is not None and self.sel < len(self.boards) else s.path.stem
            self.dc_title.config(text=f"Board {name}")
            n = len(s.layers)
            self.dc_chip.config(text=f"Decorating · {n} layer{'s' if n != 1 else ''}"
                                     + (" · unsaved" if dirty else ""),
                                bg=C["warnbg"] if dirty else C["btn"], fg=C["warn"] if dirty else C["sub"])
            self.dc_tex_file.config(text=s.path.name)
            parts = []
            if s.layers:
                parts.append(f"{n} layer(s)")
            if s.base_key != basetex.ORIGINAL:
                parts.append("base texture")
            if self._pal_changed():
                parts.append("colors")
            self.dc_changes.config(text=("Unsaved: " + ", ".join(parts) + ".") if dirty and parts else
                                   ("Saved. The layers stay editable." if s.layers else
                                    "Drag stickers onto the board, or pick a base texture."))
            self.dc_base_lbl.config(text=basetex.label_of(s.base_key))
            try:
                pv = s.base_img.convert("RGB").resize((64, 14), Image.LANCZOS)
                self._dc_base_photo = ImageTk.PhotoImage(pv)
                self.dc_base_thumb.config(image=self._dc_base_photo)
            except Exception:
                pass
        mode = self.dc_mode.get()
        self.dc_hint.config(text="drag sticker · right-drag rotate · wheel scale · click a part to recolor"
                            if mode == "place" else "drag rotate · wheel zoom · click a part to recolor")

    # ------------------------------------------------------------------ saving
    def dc_save_dialog(self):
        s = self.dc
        if s is None:
            return
        dlg = SaveDecorDialog(base.root, self)
        base.root.wait_window(dlg)
        if dlg.result:
            self.dc_save(*dlg.result)

    def dc_save(self, target: int, thumb: bool, keep: bool):
        """Writes the decoration into board `target` (the selected board or another one)."""
        s = self.dc
        if s is None or not (0 <= target < len(self.boards)):
            return
        b = self.boards[target]
        same = target == self.sel
        try:
            tex = self.tex if same else TEXCACHE.load(b.texture)
            th = TEXCACHE.load(b.thumb) if thumb and b.thumb else None
        except Exception as e:
            return messagebox.showerror("Save decorations", f"Cannot read Board {b.name}: {e}")
        s.composer.invalidate()
        work = s.composer.compose(s.base_img, s.layers, None, self.pal)
        if work.size != (tex.width, tex.height):
            work = work.resize((tex.width, tex.height), Image.LANCZOS)
        files = [(b.texture, tex)] + ([(b.thumb, th)] if th is not None else [])
        missing = [p for p, _t in files if not load_default_meta(p)]
        if missing and messagebox.askyesno(
                "Save defaults first?",
                f"No default is saved for {', '.join(p.name for p in missing)} yet.\n\n"
                "Save the current images as defaults before writing, so you can revert later?"):
            try:
                for p, t in files:
                    if p in missing:
                        meta = set_default(p, t)
                        self.cache.put(p, meta["pixel_sha256"])
            except Exception as e:
                return messagebox.showerror("Cannot set default", str(e))
        self.busy(True)
        try:
            save_texture(b.texture, work, tex)
            TEXCACHE.remember_saved(b.texture, tex, work)
            if th is not None:
                small = work.resize((th.width, th.height), Image.LANCZOS)
                save_texture(b.thumb, small, th)
                TEXCACHE.remember_saved(b.thumb, th, small)
            if keep and work.size == s.size:
                save_project(b.texture, s.base_img, s.base_key, s.tint, s.tint_strength, s.layers, work)
            else:
                drop_project(b.texture)
        except Exception as e:
            return messagebox.showerror("Save failed", str(e))
        finally:
            self.busy(False)
        what = f"Board {b.name}" + (" and its thumbnail" if th is not None else "")
        if same:
            if keep:
                s.saved_sig = s.sig()
                s.original_saved = True
            else:
                self.dc_sessions.pop(s.path, None)
                self.dc = None
            self.pal = None                        # read the written colors back
            self._load_current(sync=True)
        else:
            self.dc_sessions.pop(b.texture, None)
            self.status.pop(target, None)
            self.locked.discard(target)
            self.strip_pil.pop(target, None)
            self.gal_pil.pop(target, None)
            self.board_pal.pop(target, None)
            self._start_worker()
        self.set_status(f"Saved the decoration to {what}"
                        + (" · layers stay editable" if keep else "")
                        + (f" (Board {self.boards[self.sel].name} is unchanged)" if not same and self.sel is not None else ""))
        self._dc_refresh_controls()


class SaveDecorDialog(tk.Toplevel):
    """Override the selected board, or save the design into another board."""

    def __init__(self, master, app):
        super().__init__(master, bg=C["panel"])
        self.app, self.result = app, None
        self.title("Save decorations")
        self.transient(master)
        self.resizable(False, False)
        s = app.dc
        cur = app.boards[app.sel]
        self.boards = app.boards
        body = tk.Frame(self, bg=C["panel"])
        body.pack(fill="both", expand=True, padx=20, pady=16)
        top = tk.Frame(body, bg=C["panel"])
        top.pack(fill="x")
        prev = s.composer.compose(s.base_img, s.layers, None, app.pal).convert("RGB").resize((240, 54), Image.LANCZOS)
        self._ph = ImageTk.PhotoImage(prev)
        tk.Label(top, image=self._ph, bg=C["panel"], bd=1, relief="solid").pack(side="left")
        info = tk.Frame(top, bg=C["panel"])
        info.pack(side="left", padx=12)
        label(info, f"Board {cur.name} · {len(s.layers)} layer(s)", "bold").pack(anchor="w")
        bits = [f"base: {basetex.label_of(s.base_key)}"] + (["colors changed"] if app._pal_changed() else [])
        label(info, " · ".join(bits), "small", "muted").pack(anchor="w")

        self.mode = tk.StringVar(value="override")
        others = [b.name for i, b in enumerate(app.boards) if i != app.sel]
        self.opt1 = self._option(body, "override", "Override selected board",
                                 f"Replaces Board {cur.name} ({cur.texture.name}). The default snapshot stays, "
                                 "so Revert still brings the original back.")
        self.opt2 = self._option(body, "other", "Save to another board",
                                 f"Keeps Board {cur.name} as it is and writes the design into the board you pick. "
                                 "The game has a fixed set of boards, so the design replaces that one.")
        row = tk.Frame(self.opt2, bg=self.opt2.cget("bg"))
        row.pack(fill="x", padx=(34, 12), pady=(0, 10))
        label(row, "Board", "small", "muted", bg=self.opt2.cget("bg")).pack(side="left")
        self.target = tk.StringVar(value=others[(min(app.sel, len(others) - 1)) if others else 0] if others else "")
        self.combo = ttk.Combobox(row, textvariable=self.target, values=others, state="readonly", width=10)
        self.combo.pack(side="left", padx=8)
        self.combo.bind("<<ComboboxSelected>>", lambda e: (self.mode.set("other"), self._update()))
        self.thumb = tk.BooleanVar(value=SETTINGS.get("dc_thumb", True))
        self.keep = tk.BooleanVar(value=SETTINGS.get("dc_keep", True))
        for text, var in (("Also update the thumbnail", self.thumb), ("Keep layers editable after saving", self.keep)):
            tk.Checkbutton(body, text=text, variable=var, bg=C["panel"], fg=C["sub"], activebackground=C["panel"],
                           activeforeground=C["text"], selectcolor=C["bg"], font=F["small"], bd=0,
                           highlightthickness=0, cursor="hand2", anchor="w").pack(fill="x", pady=(8, 0))
        foot = tk.Frame(self, bg=C["side"])
        foot.pack(fill="x")
        self.ok = button(foot, "Save", self._ok, "primary")
        self.ok.pack(side="right", padx=(8, 16), pady=12)
        button(foot, "Cancel", self.destroy).pack(side="right", pady=12)
        self._update()
        self.bind("<Escape>", lambda e: self.destroy())
        self.bind("<Return>", lambda e: self._ok())
        self.update_idletasks()
        x = master.winfo_rootx() + (master.winfo_width() - self.winfo_width()) // 2
        y = master.winfo_rooty() + (master.winfo_height() - self.winfo_height()) // 3
        self.geometry(f"+{max(0, x)}+{max(0, y)}")
        self.grab_set()
        self.focus_set()

    def _option(self, parent, val, title, text):
        fr = tk.Frame(parent, bg=C["btn"], highlightthickness=1, highlightbackground=C["border"], cursor="hand2")
        fr.pack(fill="x", pady=(12, 0))
        r = tk.Radiobutton(fr, text=title, value=val, variable=self.mode, command=self._update, bg=C["btn"],
                           fg=C["text"], activebackground=C["btn"], activeforeground=C["text"],
                           selectcolor=C["bg"], font=F["bold"], bd=0, highlightthickness=0, anchor="w")
        r.pack(fill="x", padx=10, pady=(10, 2))
        t = tk.Label(fr, text=text, bg=C["btn"], fg=C["sub"], font=F["small"], justify="left", anchor="w",
                     wraplength=440)
        t.pack(fill="x", padx=(34, 12), pady=(0, 10))
        for w in (fr, t):
            w.bind("<Button-1>", lambda e: (self.mode.set(val), self._update()))
        fr._parts = (r, t)
        return fr

    def _update(self):
        for fr, val in ((self.opt1, "override"), (self.opt2, "other")):
            on = self.mode.get() == val
            fr.config(highlightbackground=C["accent"] if on else C["border"])
        cur = self.app.boards[self.app.sel].name
        self.ok.config(text=f"Override Board {cur}" if self.mode.get() == "override"
                       else f"Save to Board {self.target.get()}")

    def _ok(self):
        if self.mode.get() == "override":
            target = self.app.sel
        else:
            names = [b.name for b in self.boards]
            if self.target.get() not in names:
                return
            target = names.index(self.target.get())
            if not messagebox.askyesno("Save to another board",
                                       f"Replace Board {self.target.get()} with this design?", parent=self):
                return
        SETTINGS["dc_thumb"], SETTINGS["dc_keep"] = self.thumb.get(), self.keep.get()
        try:
            save_settings(SETTINGS)
        except Exception:
            pass
        self.result = (target, self.thumb.get(), self.keep.get())
        self.destroy()
