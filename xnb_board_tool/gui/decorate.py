"""The Decorate tab: put stickers and images on the board in 3D, as layers on a base texture."""
from __future__ import annotations

import dataclasses
import math
import queue
import random
import threading
import time
from pathlib import Path
from typing import Optional

from tkinter import colorchooser, filedialog, messagebox, simpledialog, ttk
import tkinter as tk
from PIL import Image, ImageDraw, ImageTk

from .. import basetex
from ..effects import FINISH_FX, STICKER_FX, Finish, color_key, fx_key
from ..i18n import N_, _, _n
from .. import textshapes as TS
from ..colorsuggest import suggestions as color_suggestions
from ..boards import PALETTE_SLOTS, to_hex
from ..caches import TEXCACHE
from ..defaults import load_default_meta, set_default
from ..imageops import Adjust
from ..layers import (MIRRORS, Composer, Layer, drop_project, load_project, new_image_adjust, save_project,
                      sticker_adjust, with_outline)
from ..settings import C, SETTINGS, _rgb, save_settings
from ..stickers import StickerLibrary
from ..xnb import save_texture
from .base import F, FlatButton, Flow, Scroll, SegButton, Slider, button, card, hline, label, more_button, set_state
from . import base

PART_NAMES = [name for _key, name in PALETTE_SLOTS]


def img_types():
    """File-dialog filter list for the image formats Pillow can open as stickers or base textures."""
    return [(_("Images"), "*.png *.jpg *.jpeg *.bmp *.tga *.gif *.webp"), (_("All files"), "*.*")]


ALL = "*all*"
DEFAULT_PACK = "My stickers"


# ====================================================================== state
class DecorSession:
    """The decoration of one board: base texture, layers, selection and undo history."""

    def __init__(self, path: Path, tex, project: Optional[dict] = None):
        """Start decorating the board texture at `path`. `tex` is the loaded XNB texture; `original` keeps its art
        unchanged so 'Clear' and the 'Board's own art' base can always go back to it. `project` restores a saved
        decoration project (layers, base, tint, finish) when one exists next to the board.
        """
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
        self.finish: dict = {}                       # board finish effects: {'grip': 0..1, ...}
        self._finish_obj = None
        self._finish_fields: dict = {}               # noise etc. shared by all strengths
        if project:
            self.base_img, self.base_key = project["base"], project["base_key"]
            self.tint, self.tint_strength = project["tint"], project["tint_strength"]
            self.layers = project["layers"]
            self.finish = dict(project.get("finish") or {})
            self.restored = project.get("saved_at", "")
        self.saved_sig = self.sig()

    @property
    def size(self):
        """(width, height) of the board texture in pixels."""
        return self.original.size

    def sleep(self):
        """Frees everything that can be made again (used for boards you have stepped away from):
        cached renders, the composed texture and a generated base. Placement and undo stay."""
        self.composer.invalidate()
        self.work = None
        self._finish_obj, self._finish_fields = None, {}
        seen = set()
        for L in self.layers + [snap[0] for st in self.undo + self.redo for snap in st[0]]:
            if id(L) not in seen:
                seen.add(id(L))
                L.drop_cache()
        if self.base_regen and self.base_key != basetex.ORIGINAL:
            self.base_img = None

    def wake(self):
        """Rebuild `base_img` if it was dropped to save memory while this board was not shown."""
        if self.base_img is None:
            W, H = self.size
            self.base_img = basetex.make_base(self.base_key, W, H, self.original, self.tint, self.tint_strength)

    def sig(self):
        """Hashable signature of everything that is saved (base, tint, finish, every layer). Compared with
        `saved_sig` to tell whether there are unsaved changes.
        """
        return (self.base_key, self.tint, round(self.tint_strength, 3), fx_key(self.finish),
                tuple(L.key() for L in self.layers))

    def finish_obj(self, mask=None):
        """The board finish (effects.Finish) for the current settings, or None."""
        if not any(self.finish.values()):
            return None
        import zlib
        W, H = self.size
        seed = zlib.crc32(self.path.name.encode()) & 0xFFFF
        key = (W, H, seed, id(mask), tuple(sorted(self.finish.items())))
        f = self._finish_obj
        if f is None or getattr(f, "_gui_key", None) != key:
            fk = (W, H, seed, id(mask))
            if self._finish_fields.get("_key") != fk:
                self._finish_fields = {"_key": fk}
            f = Finish(W, H, self.finish, seed, mask, fields=self._finish_fields)
            f._gui_key = key
            self._finish_obj = f
        return f

    def dirty(self):
        """True when the session differs from what was last saved."""
        return self.sig() != self.saved_sig


class Renderer:
    """One background render thread for the Decorate 3D view; the newest request wins."""

    def __init__(self):
        """Start the background 3D render thread. Only the newest request is kept; finished frames go to `results`
        and are picked up on the Tk thread by `DecorateMixin._dc_poll`.
        """
        self._cv = threading.Condition()
        self._job = None
        self.results: queue.Queue = queue.Queue()
        threading.Thread(target=self._loop, daemon=True).start()

    def request(self, **job):
        """Queue a render job (keyword arguments for board3d.render_board plus bookkeeping). Replaces any job that
        has not started yet, so fast mouse moves never pile up.
        """
        with self._cv:
            self._job = job
            self._cv.notify()

    def _loop(self):
        """Thread body: wait for a job, render it, and put (job, image or exception, info, milliseconds) on
        `results`.
        """
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
        """Create the Decorate tab's state: sticker library, per-board sessions, the renderer, camera angles and
        drag bookkeeping. Called once from App.__init__ before any widgets exist.
        """
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
        """Build the Decorate tab inside `view`: library on the left, 3D + flat deck in the centre and the
        inspector on the right. The Skate shop layout has its own builder (`_build_decorate_shop`).
        """
        self._dc_photo = self._dc_flat_photo = self._dc_ghost_photo = self._dc_base_photo = None
        self._dc_lib_photos, self._dc_tex_photos, self._dc_tiles = [], {}, {}
        self._dc_tex_rows = {}
        self._dc_libs_built = False
        if getattr(self, "layout", "") == "shop":
            return self._build_decorate_shop(view)
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

    def _dc_shop(self):
        """True when the app runs in the Skate shop layout (several controls are drawn differently)."""
        return getattr(self, "layout", "") == "shop"

    def _dc_card(self, parent):
        """A boxed card, or (Skate shop) a flat section of the sheet."""
        if self._dc_shop():
            return tk.Frame(parent, bg=C["panel"])
        return card(parent)

    def _dc_h(self, parent, text):
        """A section heading: condensed display type in the Skate shop layout."""
        if self._dc_shop():
            return tk.Label(parent, text=text.upper(), font=F["display"], fg=C.get("ink", C["text"]),
                            bg=parent.cget("bg"))
        return label(parent, text, "h2")

    def _seg(self, parent, var, items, cmd, small=False):
        """Make a segmented control: one SegButton per (label, value) in `items`, all bound to `var`, calling `cmd`
        on change. Labels are translated here.
        """
        seg = tk.Frame(parent, bg=C["bg"], highlightthickness=1, highlightbackground=C["border"])
        for text, val in items:
            SegButton(seg, text=_(text), value=val, variable=var, command=cmd, indicatoron=False,
                           bg=C["bg"], fg=C["text"], selectcolor=C["selfill"], activebackground=C["btnh"],
                           activeforeground=C["text"], relief="flat", bd=0, highlightthickness=0,
                           padx=12 if small else 14, pady=3 if small else 5,
                           font=F["smallbold" if small else "bold"], cursor="hand2").pack(
                side="left", padx=1, pady=1, fill="x", expand=True)
        return seg

    # -- left: stickers | textures
    def _dc_build_left(self, left):
        """Build the left column: the Stickers / Textures / Effects switch and the three pages (sticker packs, base
        textures with tint, layer effects and board finish).
        """
        self.dc_left_tab = tk.StringVar(value=self._keep.get("dc_left", "stickers"))
        if self._dc_shop():
            self._dc_left_tags_build(left)          # hanging tags, and the library folds away
        else:
            self._seg(left, self.dc_left_tab, ((N_("Stickers"), "stickers"), (N_("Textures"), "textures"),
                                               (N_("Effects"), "effects")),
                      self._dc_left_switch, small=True).pack(fill="x", padx=12, pady=(14, 10))
        self.dc_stickers_frame = tk.Frame(left, bg=C["side"])
        self.dc_textures_frame = tk.Frame(left, bg=C["side"])
        self.dc_effects_frame = tk.Frame(left, bg=C["side"])
        self._dc_build_effects(self.dc_effects_frame)
        # stickers
        f = self.dc_stickers_frame
        top = tk.Frame(f, bg=C["side"])
        top.pack(fill="x", padx=12, pady=(0, 4))
        label(top, _("Sticker packs"), "bold").pack(side="left")
        self.dc_pack_more, _items = more_button(top, [
            (N_("New pack…"), self.dc_new_pack), (N_("Rename pack…"), self.dc_rename_pack),
            (N_("Delete pack…"), self.dc_delete_pack), (N_("Export pack as .zip…"), self.dc_export_pack),
            (N_("Import pack from .zip…"), self.dc_import_pack)])
        self.dc_pack_more.pack(side="right")
        button(top, _("+ New"), self.dc_new_pack, small=True).pack(side="right", padx=(0, 6))
        box = tk.Frame(f, bg=C["bg"], height=132, highlightthickness=1, highlightbackground=C["border"])
        box.pack(fill="x", padx=12)
        box.pack_propagate(False)
        self.dc_pack_scroll = Scroll(box)
        self.dc_pack_scroll.pack(fill="both", expand=True)
        top = tk.Frame(f, bg=C["side"])
        top.pack(fill="x", padx=12, pady=(10, 2))
        self.dc_lib_title = label(top, _("Stickers"), "bold")
        self.dc_lib_title.pack(side="left")
        self.dc_lib_count = label(top, "", "small", "muted")
        self.dc_lib_count.pack(side="left", padx=6)
        button(top, _("Add…"), self.dc_add_stickers, small=True).pack(side="right")
        label(f, _("Drag onto the board, or click to add. Right-click for more."), "small", "muted",
              justify="left", anchor="w", wraplength=240).pack(fill="x", padx=12, pady=(0, 6))
        self.dc_lib_scroll = Scroll(f)
        self.dc_lib_scroll.pack(fill="both", expand=True, padx=(8, 0), pady=(0, 8))
        # textures
        f = self.dc_textures_frame
        top = tk.Frame(f, bg=C["side"])
        top.pack(fill="x", padx=12, pady=(0, 4))
        label(top, _("Base texture"), "bold").pack(side="left")
        button(top, _("Add…"), self.dc_add_textures, small=True).pack(side="right")
        label(f, _("Click to put a texture under your stickers. Colors and layers stay as "
                   "they are."),
              "small", "muted", justify="left", anchor="w", wraplength=240).pack(fill="x", padx=12, pady=(0, 8))
        tr = tk.Frame(f, bg=C["panel"], highlightthickness=1, highlightbackground=C["border"])
        tr.pack(fill="x", padx=12, pady=(0, 8))
        label(tr, _("Tint"), "small", "sub").pack(side="left", padx=(10, 6), pady=6)
        self.dc_tint_sw = tk.Canvas(tr, width=22, height=16, bg=C["btn"], highlightthickness=1,
                                    highlightbackground=C["btnb"], cursor="hand2")
        self.dc_tint_sw.pack(side="left")
        self.dc_tint_sw.bind("<Button-1>", lambda e: self.dc_pick_tint())
        self.dc_tint_val = label(tr, "0%", "small", "muted", width=4, anchor="e")
        self.dc_tint_val.pack(side="right", padx=(4, 10))
        self.dc_tint = tk.DoubleVar(value=0)
        self.dc_tint_scale = Slider(tr, from_=0, to=100, variable=self.dc_tint, command=self._dc_tint_moved)
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
        """Build the centre: title row with undo/redo and board arrows, the 3D canvas with its mouse bindings, and
        the flat texture view.
        """
        m = tk.Frame(center, bg=C["bg"])
        m.pack(fill="both", expand=True, padx=20, pady=16)
        tr = tk.Frame(m, bg=C["bg"])
        tr.pack(fill="x")
        self.dc_title = label(tr, _("No board selected"), "h1")
        self.dc_title.pack(side="left")
        self.dc_chip = tk.Label(tr, font=F["smallbold"], padx=10, pady=3, bg=C["btn"], fg=C["sub"])
        self.dc_chip.pack(side="left", padx=14)
        button(tr, "›", lambda: self.step(1), width=2).pack(side="right")
        button(tr, "‹", lambda: self.step(-1), width=2).pack(side="right", padx=(6, 6))
        self.dc_b_redo = button(tr, _("Redo"), self.dc_redo, small=True)
        self.dc_b_redo.pack(side="right", padx=(6, 10))
        self.dc_b_undo = button(tr, _("Undo"), self.dc_undo, small=True)
        self.dc_b_undo.pack(side="right")

        vc = card(m)
        vc.pack(fill="both", expand=True, pady=(14, 0))
        head = tk.Frame(vc, bg=C["panel"])
        head.pack(fill="x", padx=14, pady=8)
        label(head, _("3D board"), "h2").pack(side="left")
        self.dc_mode = tk.StringVar(value=self._keep.get("dc_mode", "place"))
        self._seg(head, self.dc_mode, ((N_("View / colors"), "view"), (N_("Place stickers"), "place")),
                  self._dc_mode_changed, small=True).pack(side="left", padx=14)
        for text, var in ((N_("Outline"), self.v3_outline), (N_("Screws"), self.v3_screws)):
            tk.Checkbutton(head, text=_(text), variable=var, command=self.dc_render,
                           bg=C["panel"], fg=C["sub"], activebackground=C["panel"],
                           activeforeground=C["text"], selectcolor=C["bg"], font=F["small"],
                           bd=0, highlightthickness=0, cursor="hand2").pack(side="right", padx=(8, 0))
        hline(vc).pack(fill="x")
        vbar = tk.Frame(vc, bg=C["panel"])
        vbar.pack(side="bottom", fill="x", padx=14, pady=(0, 10))
        for text, yaw, pitch in (("3/4", 28, 30), (N_("Top"), 0, 75), (N_("Bottom"), 0, -75), (N_("Side"), 90, 6)):
            FlatButton(vbar, text=_(text), command=lambda y=yaw, p=pitch: self._dc_view(y, p),
                      bg=C["btn"], fg=C["text"], activebackground=C["btnh"], activeforeground=C["text"],
                      relief="flat", bd=0, highlightthickness=1, highlightbackground=C["btnb"], padx=10,
                      pady=3, font=F["small"], cursor="hand2").pack(side="left", padx=(0, 4))
        self.dc_hint = label(vbar, "", "small", "muted")
        self.dc_hint.pack(side="right")
        self.dc_cv = tk.Canvas(vc, bg=C["bg"], highlightthickness=0, height=300)
        self.dc_cv.pack(fill="both", expand=True, padx=14, pady=(10, 8))
        self._dc_bind_cv()

        fc = card(m)
        fc.pack(fill="x", pady=(14, 0))
        head = tk.Frame(fc, bg=C["panel"])
        head.pack(fill="x", padx=14, pady=(8, 6))
        label(head, _("Board texture"), "h2").pack(side="left")
        self.dc_tex_file = label(head, "", "mono", "muted")
        self.dc_tex_file.pack(side="left", padx=10)
        label(head, _("Dimmed: not visible on the deck · outlines: layers"), "small", "muted").pack(side="right")
        self.dc_flat = tk.Canvas(fc, bg=C["bg"], height=80, highlightthickness=0)
        self.dc_flat.pack(fill="x", padx=14, pady=(0, 12))
        self._dc_bind_flat()

    def _dc_bind_cv(self):
        """Mouse bindings of the 3D canvas (dc_cv)."""
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

    def _dc_bind_flat(self):
        """Mouse bindings of the flat texture view (dc_flat), and dropping images on both views."""
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
        """Build the right column: the layer list and the tools for the selected layer (fit, rotate, flip, mirror,
        opacity, edit), board colours and the Save button.
        """
        shop = self._dc_shop()
        i = tk.Frame(parent, bg=C["panel"] if shop else C["bg"])
        i.pack(fill="both", expand=True, padx=(8 if shop else 14), pady=16)
        if shop:
            self._dc_build_layers_shop(i)       # icon toolbars that show when a layer is picked
        else:
            lc = self._dc_card(i)
            lc.pack(fill="x")
            r = tk.Frame(lc, bg=C["panel"])
            r.pack(fill="x", padx=12, pady=(10, 6))
            self._dc_h(r, _("Layers")).pack(side="left")
            self.dc_layer_count = label(r, "", "small", "muted")
            self.dc_layer_count.pack(side="left", padx=6)
            self.dc_shape_btn, _items = more_button(r, [(lab, (lambda k=k: self.dc_add_shape(k))) for k, lab in TS.SHAPES])
            self.dc_shape_btn.config(text=_("Shape") + " ▾")
            self.dc_shape_btn.pack(side="right")
            button(r, _("Text…"), self.dc_add_text, small=True).pack(side="right", padx=(0, 5))
            button(r, _("Image…"), self.dc_ask_image, small=True).pack(side="right", padx=(0, 5))
            lb = tk.Frame(lc, bg=C["bg"], height=236 if shop else 196)
            lb.pack(fill="x", padx=12)
            lb.pack_propagate(False)
            self.dc_layer_scroll = Scroll(lb)
            self.dc_layer_scroll.pack(fill="both", expand=True)
            r = Flow(lc, gap=5, vgap=4, bg=C["panel"])
            r.pack(fill="x", padx=12, pady=(8, 4))
            b1 = button(r, _("Up"), lambda: self.dc_move_layer(1), small=True)
            b2 = button(r, _("Down"), lambda: self.dc_move_layer(-1), small=True)
            b3 = button(r, _("Duplicate"), self.dc_duplicate, small=True)
            b4 = button(r, _("Delete"), self.dc_delete_layer, small=True)
            for b in (b1, b2, b3, b4):
                r.add(b)
            r = Flow(lc, gap=5, vgap=4, bg=C["panel"])
            r.pack(fill="x", padx=12, pady=(0, 4))
            b5 = button(r, _("Fill"), lambda: self.dc_set_fit("fill"), small=True)
            b6 = button(r, _("Fit"), lambda: self.dc_set_fit("fit"), small=True)
            b7 = button(r, _("Rotate 90°"), lambda: self.dc_rotate(90), small=True)
            b8 = button(r, _("Flip"), self.dc_flip, small=True)
            for b in (b5, b6, b7, b8):
                r.add(b)
            r = Flow(lc, gap=5, vgap=4, bg=C["panel"])
            r.pack(fill="x", padx=12, pady=(0, 4))
            self.dc_mirror_btn, _items = more_button(r, [(lab, (lambda m=m: self.dc_set_mirror(m))) for m, lab in MIRRORS])
            self.dc_mirror_btn.config(text=_("Mirror: {mode}", mode=_("Off")) + " ▾")
            r.add(self.dc_mirror_btn)
            self.dc_edit_btn = r.add(button(r, _("Edit text…"), self.dc_edit_layer, small=True))
            r = tk.Frame(lc, bg=C["panel"])
            r.pack(fill="x", padx=12, pady=(2, 12))
            label(r, _("Opacity"), "small", "sub").pack(side="left")
            self.dc_op_val = label(r, "", "small", "muted", width=5, anchor="e")
            self.dc_op_val.pack(side="right")
            self.dc_opacity = tk.DoubleVar(value=100)
            self.dc_op_scale = Slider(r, from_=5, to=100, variable=self.dc_opacity, command=self._dc_opacity_moved)
            self.dc_op_scale.pack(side="left", fill="x", expand=True, padx=8)
            self.dc_op_scale.bind("<ButtonPress-1>", lambda e: self._dc_push("opacity"))
            self.dc_op_scale.bind("<ButtonRelease-1>", lambda e: self._dc_sharpen())
            self.dc_sel_btns = [b1, b2, b3, b4, b5, b6, b7, b8, self.dc_mirror_btn]

        if shop:
            tk.Frame(i, bg=C["border"], height=1).pack(fill="x", padx=12, pady=(14, 0))
        cc = self._dc_card(i)
        cc.pack(fill="x", pady=(14, 0))
        r = tk.Frame(cc, bg=C["panel"])
        r.pack(fill="x", padx=12, pady=(10, 6))
        self._dc_h(r, _("Board colors")).pack(side="left")
        self.dc_suggest_btn = button(r, _("Suggest…"), self.dc_suggest_colors, small=True)
        self.dc_suggest_btn.pack(side="right")
        g = tk.Frame(cc, bg=C["panel"])
        g.pack(fill="x", padx=12)
        self.dc_swatches = []
        for k, name in enumerate(_(n) for n in PART_NAMES):
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
        label(cc, _("Click a colour to change it, or click a part of the 3D board."), "small", "muted",
              wraplength=270, justify="left",
              anchor="w").pack(fill="x", padx=12, pady=(4, 12))

        if shop:
            self._dc_bind_keys()
            return                          # Skate shop: saving lives in the ink bar at the bottom
        sc = card(i)
        sc.pack(fill="x", pady=(14, 0))
        label(sc, _("Save"), "h2").pack(anchor="w", padx=12, pady=(10, 6))
        r = tk.Frame(sc, bg=C["panel"])
        r.pack(fill="x", padx=12)
        label(r, _("Base"), "small", "muted").pack(side="left")
        self.dc_base_thumb = tk.Label(r, bg=C["panel"])
        self.dc_base_thumb.pack(side="left", padx=8)
        self.dc_base_lbl = label(r, "", "small", "sub", wraplength=170, justify="left", anchor="w")
        self.dc_base_lbl.pack(side="left")
        r = tk.Frame(sc, bg=C["panel"])
        r.pack(fill="x", padx=12, pady=(10, 4))
        self.dc_b_save = button(r, _("Save decorations…"), self.dc_save_dialog, "primary")
        self.dc_b_save.pack(side="left")
        self.dc_b_clear = button(r, _("Clear all"), self.dc_clear)
        self.dc_b_clear.pack(side="left", padx=8)
        self.dc_changes = label(sc, "", "small", "muted", anchor="w", justify="left", wraplength=300)
        self.dc_changes.pack(fill="x", padx=12, pady=(4, 12))
        self._dc_bind_keys()

    def _dc_bind_keys(self):
        """Bind the keyboard shortcuts: R rotate 90°, F flip, Delete/Backspace remove, Ctrl+D duplicate, Ctrl+Z /
        Ctrl+Y undo/redo, Page Up/Down change layer order, Esc deselect. Each goes through `_dc_key`, which
        ignores them unless the Decorate tab is active and no text field has focus.
        """
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
            self._dc_msg(_("Loading…") if self._loading else
                         _("Pick a board (Boards tab, or ‹ ›) to decorate it"))
            self._dc_refresh_all()
            return
        s = self.dc_sessions.get(self.tex_path)
        if s is None or (s.tex is not self.tex and not s.dirty()):
            proj = load_project(self.tex_path, self.tex.img)
            s = DecorSession(self.tex_path, self.tex, proj)
            s.saved_state = None                       # filled in below, once the session is the current one
            self.dc_sessions[self.tex_path] = s
            if s.restored:
                self.set_status(_("Editable layers from {restored} restored for {name}", restored=s.restored, name=self.tex_path.name))
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
        if getattr(s, "saved_state", None) is None and not s.dirty():
            s.saved_state = self._dc_state()           # what Revert goes back to
        if changed:
            self.dc_info = None
            mm = self._v3_mask_for(s.size)
            self._dc_mask = mm
        self.dc_compose()
        self.dc_render()
        self._dc_refresh_all()

    def _v3_mask_for(self, size):
        """Mask of the texture pixels that land on the top of the deck for a texture of `size`. Cached per size;
        None while the 3D model is missing.
        """
        from ..board3d import deck_top_mask
        if self.v3_model is None:
            return None
        cache = getattr(self, "_dc_mask_cache", {})
        if size not in cache:
            cache[size] = deck_top_mask(self.v3_model, *size)
            self._dc_mask_cache = cache
        return cache[size]

    def dc_unsaved(self):
        """List of decorate sessions (one per board) that have unsaved changes."""
        return [s for s in self.dc_sessions.values() if s.dirty()]

    # ------------------------------------------------------------------ library (stickers)
    def _dc_left_switch(self):
        """Show the left page chosen in `dc_left_tab` and load its content the first time (textures load lazily;
        effects sync with the selected layer).
        """
        tab = self.dc_left_tab.get()
        frames = {"stickers": self.dc_stickers_frame, "textures": self.dc_textures_frame,
                  "effects": self.dc_effects_frame}
        for k, fr in frames.items():
            if k != tab:
                fr.pack_forget()
        frames.get(tab, self.dc_stickers_frame).pack(fill="both", expand=True)
        if tab == "textures" and not self._dc_tex_photos and self.dc_lib is not None:
            self.dc_load_textures()
        if tab == "effects":
            self._dc_sync_fx()
        if self._dc_shop():
            self._dc_left_tags_refresh()

    # ------------------------------------------------------------------ effects
    def _dc_build_effects(self, f):
        """Left 'Effects' tab: a finish for the whole board and effects for the selected sticker.
        They are painted into the texture, so the game shows them too."""
        self._dc_fx_vars, self._dc_fx_vals, self._dc_fx_scales = {}, {}, {}
        label(f, _("Board finish"), "bold").pack(anchor="w", padx=12)
        label(f, _("Over the whole board, on top of everything."), "small", "muted", justify="left",
              anchor="w", wraplength=240).pack(fill="x", padx=12, pady=(0, 6))
        box = tk.Frame(f, bg=C["panel"], highlightthickness=1, highlightbackground=C["border"])
        box.pack(fill="x", padx=12)
        for key, lab, hlp in FINISH_FX:
            self._dc_fx_row(box, "finish", key, lab, hlp)
        top = tk.Frame(f, bg=C["side"])
        top.pack(fill="x", padx=12, pady=(16, 0))
        label(top, _("Selected sticker"), "bold").pack(side="left")
        self.dc_fx_clear_btn = button(top, _("Remove"), self._dc_fx_clear, small=True)
        self.dc_fx_clear_btn.pack(side="right")
        self.dc_fx_title = label(f, "", "small", "muted", justify="left", anchor="w", wraplength=240)
        self.dc_fx_title.pack(fill="x", padx=12, pady=(0, 6))
        box = tk.Frame(f, bg=C["panel"], highlightthickness=1, highlightbackground=C["border"])
        box.pack(fill="x", padx=12)
        for key, lab, hlp in STICKER_FX:
            self._dc_fx_row(box, "sticker", key, lab, hlp)
        top = tk.Frame(f, bg=C["side"])
        top.pack(fill="x", padx=12, pady=(12, 4))
        label(top, _("Sticker colour"), "bold").pack(side="left")
        self.dc_col_reset = button(top, _("Reset"), self._dc_color_reset, small=True)
        self.dc_col_reset.pack(side="right")
        box = tk.Frame(f, bg=C["panel"], highlightthickness=1, highlightbackground=C["border"])
        box.pack(fill="x", padx=12)
        self._dc_col_vars, self._dc_col_vals, self._dc_col_scales = {}, {}, {}
        for key, lab, lo, hi in (("hue", N_("Hue"), -180, 180), ("sat", N_("Saturation"), 0, 200),
                                 ("tint_s", N_("Tint"), 0, 100)):
            r = tk.Frame(box, bg=C["panel"])
            r.pack(fill="x", padx=8, pady=(5, 3))
            label(r, _(lab), "small", "sub", width=self._dc_name_w() - (0 if key != "tint_s" else 5),
                  anchor="w").pack(side="left")
            if key == "tint_s":
                self.dc_col_tint_sw = tk.Canvas(r, width=24, height=14, bg="#ffffff", highlightthickness=1,
                                                highlightbackground=C["btnb"], cursor="hand2")
                self.dc_col_tint_sw.pack(side="left", padx=(0, 8))
                self.dc_col_tint_sw.bind("<Button-1>", lambda e: self._dc_pick_sticker_tint())
            val = label(r, "", "small", "muted", width=5, anchor="e")
            val.pack(side="right")
            var = tk.DoubleVar(value=0 if key != "sat" else 100)
            sc = Slider(r, from_=lo, to=hi, variable=var, command=lambda _v, k=key: self._dc_color_moved(k))
            sc.pack(side="left", fill="x", expand=True, padx=(4, 6))
            sc.bind("<ButtonPress-1>", lambda e: self._dc_push("fx"))
            sc.bind("<ButtonRelease-1>", lambda e: self._dc_fx_done())
            self._dc_col_vars[key], self._dc_col_vals[key], self._dc_col_scales[key] = var, val, sc
        label(f, _("Recolour a sticker to match your board: turn its hue, make it more or "
                   "less colourful, or tint it with a colour (click the swatch)."), "small", "muted", justify="left", anchor="w",
              wraplength=240).pack(fill="x", padx=12, pady=(6, 0))
        label(f, _("Effects are painted into the texture: they look the same from every "
                   "angle in the game and don't react to light."), "small", "muted", justify="left", anchor="w",
              wraplength=240).pack(fill="x", padx=12, pady=(10, 0))

    @staticmethod
    def _dc_name_w():
        """Width (characters) of the slider names: room for the longest one in this language."""
        names = [lab for _k, lab, _h in FINISH_FX + STICKER_FX] + ["Hue", "Saturation"]
        return max(12, max(len(_(n)) for n in names) + 1)

    def _dc_fx_row(self, parent, kind, key, text, hlp):
        """Add one effect slider row (name, 0–100 slider, value) for `key` of `kind` ('fx' for the selected layer,
        'finish' for the whole board). Pressing the slider pushes one undo step.
        """
        r = tk.Frame(parent, bg=C["panel"])
        r.pack(fill="x", padx=8, pady=(5, 3))
        name = label(r, _(text), "small", "sub", width=self._dc_name_w(), anchor="w")
        name.pack(side="left")
        val = label(r, "0%", "small", "muted", width=4, anchor="e")
        val.pack(side="right")
        var = tk.DoubleVar(value=0)
        sc = Slider(r, from_=0, to=100, variable=var, command=lambda _v, k=kind, n=key: self._dc_fx_moved(k, n))
        sc.pack(side="left", fill="x", expand=True, padx=(4, 6))
        sc.bind("<ButtonPress-1>", lambda e, k=kind: self._dc_push(k if k == "finish" else "fx"))
        sc.bind("<ButtonRelease-1>", lambda e: self._dc_fx_done())
        for w in (r, name, sc):
            w.bind("<Enter>", lambda e, t=text, h=hlp: self.set_status(_(t) + ": " + _(h)), add="+")

        self._dc_fx_vars[(kind, key)], self._dc_fx_vals[(kind, key)] = var, val
        self._dc_fx_scales[(kind, key)] = sc

    def _dc_fx_moved(self, kind, key):
        """Slider callback: write the new effect strength into the layer's `fx` or the board's `finish` (0 removes
        the key) and redraw quickly.
        """
        s = self.dc
        if s is None:
            return
        v = round(self._dc_fx_vars[(kind, key)].get()) / 100.0
        target = s.finish if kind == "finish" else (s.sel.fx if s.sel is not None else None)
        if target is None or abs(float(target.get(key, 0)) - v) < 1e-9:
            return
        if v:
            target[key] = v
        else:
            target.pop(key, None)
        if kind == "sticker":
            if v and "seed" not in target:
                target["seed"] = random.randrange(1, 1 << 30)       # its own worn pattern, kept when saved
            if not any(val for k, val in target.items() if k != "seed"):
                target.clear()
        self._dc_fx_vals[(kind, key)].config(text=f"{int(round(v * 100))}%")
        self._dc_schedule_update()

    def _dc_color_moved(self, key):
        """Slider callback for the sticker colour sliders (hue in degrees, saturation, brightness, tint strength).
        Turning tint up without a tint colour picks the current board colour.
        """
        s = self.dc
        L = s.sel if s is not None else None
        if L is None:
            return
        v = float(self._dc_col_vars[key].get())
        v = round(v) if key == "hue" else round(v) / 100.0
        cur = float(L.color.get(key, 1.0 if key == "sat" else 0.0))
        if abs(cur - v) < 1e-9:
            return
        L.color[key] = v
        if key == "tint_s" and v and "tint" not in L.color:
            L.color["tint"] = [int(c) for c in self.pal[2][:3]] if self.pal else [240, 168, 48]
        self._dc_col_vals[key].config(text=self._dc_col_text(key, v))
        self._dc_draw_tint_swatch()
        self._dc_schedule_update()

    @staticmethod
    def _dc_col_text(key, v):
        """Text shown next to a colour slider: '+12°' for hue, a percentage for the others."""
        return f"{int(v):+d}\u00b0" if key == "hue" else f"{int(round(v * 100))}%"

    def _dc_pick_sticker_tint(self):
        """Ask for a tint colour for the selected layer (one undo step); sets a 50% strength if tint was off."""
        s = self.dc
        L = s.sel if s is not None else None
        if L is None:
            return
        cur = tuple(L.color.get("tint") or (self.pal[2][:3] if self.pal else (240, 168, 48)))
        rgb, _hx = colorchooser.askcolor(color=to_hex(cur), parent=base.root, title=_("Tint colour"))
        if not rgb:
            return
        self._dc_push("fx-tint")
        L.color["tint"] = [int(round(v)) for v in rgb[:3]]
        if not float(L.color.get("tint_s", 0)):
            L.color["tint_s"] = 0.6
        self.dc_changed()
        self._dc_sync_fx()

    def _dc_color_reset(self):
        """Remove every colour change from the selected layer."""
        s = self.dc
        L = s.sel if s is not None else None
        if L is None or not color_key(L.color):
            return
        self._dc_push("fx-color")
        L.color = {}
        self.dc_changed()
        self._dc_sync_fx()

    def _dc_draw_tint_swatch(self):
        """Paint the sticker-tint swatch with the layer's tint (or the default)."""
        s = self.dc
        L = s.sel if s is not None else None
        col = tuple((L.color.get("tint") if L is not None else None) or (self.pal[2][:3] if self.pal else (255, 255, 255)))
        try:
            self.dc_col_tint_sw.config(bg=to_hex(col))
        except Exception:
            pass

    def _dc_fx_done(self):
        """Slider released: the final, full-quality picture."""
        if self.dc is not None:
            self.dc_changed()

    def _dc_fx_clear(self):
        """Remove every effect from the selected layer."""
        s = self.dc
        if s is None or s.sel is None or not s.sel.fx:
            return
        self._dc_push("fx-clear")
        s.sel.fx = {}
        self.dc_changed()
        self._dc_sync_fx()

    def _dc_sync_fx(self):
        """Sliders show the current board finish and the selected sticker's effects."""
        if not hasattr(self, "_dc_fx_vars"):
            return
        s = self.dc
        L = s.sel if s is not None else None
        for (kind, key), var in self._dc_fx_vars.items():
            src = (s.finish if s is not None else {}) if kind == "finish" else (L.fx if L is not None else {})
            v = float(src.get(key, 0))
            if abs(var.get() - v * 100) > 0.4:
                var.set(v * 100)
            self._dc_fx_vals[(kind, key)].config(text=f"{int(round(v * 100))}%")
            on = s is not None and (kind == "finish" or L is not None)
            self._dc_fx_scales[(kind, key)].state(["!disabled"] if on else ["disabled"])
        self.dc_fx_title.config(text=f"\u201c{L.name}\u201d" if L is not None else
                                _("Click a sticker on the board to give it effects."))
        set_state([self.dc_fx_clear_btn], bool(L is not None and L.fx))
        for key, var in self._dc_col_vars.items():
            v = float(L.color.get(key, 1.0 if key == "sat" else 0.0)) if L is not None else (1.0 if key == "sat" else 0.0)
            shown = v if key == "hue" else v * 100
            if abs(var.get() - shown) > 0.4:
                var.set(shown)
            self._dc_col_vals[key].config(text=self._dc_col_text(key, v))
            self._dc_col_scales[key].state(["!disabled"] if L is not None else ["disabled"])
        set_state([self.dc_col_reset], bool(L is not None and color_key(L.color)))
        self._dc_draw_tint_swatch()

    def dc_load_library(self):
        """Rebuild the sticker library: the pack chips and the thumbnail grid for the current pack (or all packs).
        Thumbnails come from the sticker cache so this is fast after the first time.
        """
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
        for k, name, n in [(ALL, _("All stickers"), sum(counts.values()))] + [(k, l, counts[k]) for k, _d, l in packs]:
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
        cols, size, row = (getattr(self, "_dc_lib_cols", 3) if self._dc_shop() else 3), 74, 0
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
                    t.config(highlightbackground=C["accent"]), self.set_status(_("Sticker: {stem}  ({l})", stem=p.stem, l=l))))
                tile.bind("<Leave>", lambda e, t=tile: t.config(highlightbackground=C["border"]))
                self._dc_lib_photos.append(ph)
                self._dc_tiles[p] = tile
            row += (len(imgs) + cols - 1) // cols
            if not imgs and self.dc_pack != ALL:
                label(grid, _("This pack is empty.\nUse Add… or drop images here."), "small", "muted",
                      justify="left").grid(row=row, column=0, columnspan=cols, padx=6, pady=6, sticky="w")
        if not packs:
            label(grid, _("No stickers yet.\nCreate a pack with + New,\nor import a .zip pack."), "small", "muted",
                  justify="left").grid(padx=6, pady=6, sticky="w")
        title = _("All stickers") if self.dc_pack == ALL else (_("Unsorted") if self.dc_pack == lib.LOOSE else self.dc_pack)
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
        """Show sticker pack `key` (or ALL)."""
        if key != self.dc_pack:
            self.dc_pack = key
            self.dc_load_library()

    def _dc_ask_name(self, title, initial=""):
        """Ask for a sticker pack name; returns None when cancelled."""
        return simpledialog.askstring(title, _("Pack name:"), initialvalue=initial, parent=base.root)

    def dc_new_pack(self):
        """Ask for a name and create an empty sticker pack. Returns its key, or None."""
        name = self._dc_ask_name(_("New sticker pack"), DEFAULT_PACK)
        if not name:
            return None
        try:
            key = self.dc_lib.new_pack(name)
        except (OSError, ValueError) as e:
            messagebox.showerror(_("New sticker pack"), str(e))
            return None
        self.dc_pack = key
        self.dc_load_library()
        self.set_status(_("Created pack “{key}”. Use Add… or drop images to fill it.", key=key))
        return key

    def dc_rename_pack(self):
        """Rename the current sticker pack (not ALL or Unsorted)."""
        key = self.dc_pack
        if key in (ALL, self.dc_lib.LOOSE):
            return self.set_status(_("Select a pack to rename it"))
        name = self._dc_ask_name(_("Rename sticker pack"), key)
        if not name:
            return
        try:
            self.dc_pack = self.dc_lib.rename_pack(key, name)
        except (OSError, ValueError) as e:
            messagebox.showerror(_("Rename sticker pack"), str(e))
        self.dc_load_library()

    def dc_delete_pack(self):
        """Delete the current sticker pack and its files after confirmation."""
        key = self.dc_pack
        if key in (ALL, self.dc_lib.LOOSE):
            return self.set_status(_("Select a pack to delete it"))
        from ..stickers import images_in
        n = len(images_in(self.dc_lib.pack_dir(key)))
        if not messagebox.askyesno(_("Delete sticker pack"),
                                   (_n("Delete the pack “{key}” and its {n} sticker?",
                                       "Delete the pack “{key}” and its {n} stickers?", n, key=key) if n else
                                    _("Delete the pack “{key}”?", key=key))
                                   + "\n\n" + _("Tip: export it as a .zip first if you may want it back.")):
            return
        try:
            self.dc_lib.delete_pack(key)
        except OSError as e:
            messagebox.showerror(_("Delete sticker pack"), _("{e}\n\nThe folder may contain other "
                                                          "files.", e=e))
        self.dc_pack = ALL
        self.dc_load_library()

    def dc_export_pack(self):
        """Save the current pack (or Unsorted) as a .zip that can be shared."""
        key = self.dc_pack
        if key == ALL:
            return self.set_status(_("Select a pack to export it"))
        label_ = _("Unsorted") if key == self.dc_lib.LOOSE else key
        f = filedialog.asksaveasfilename(title=_("Export sticker pack"), defaultextension=".zip",
                                         initialfile=f"{label_}.zip", filetypes=[(_("Sticker pack"), "*.zip")])
        if not f:
            return
        try:
            n = self.dc_lib.export_pack(key, Path(f))
        except OSError as e:
            return messagebox.showerror(_("Export sticker pack"), str(e))
        self.set_status(_n("Exported {n} sticker to {name}", "Exported {n} stickers to {name}", n, name=Path(f).name))

    def dc_import_pack(self, f=None):
        """Import a sticker pack .zip (asks for the file when `f` is None) and show it."""
        f = f or filedialog.askopenfilename(title=_("Import sticker pack"), filetypes=[(_("Sticker pack"), "*.zip")])
        if not f:
            return
        import zipfile
        try:
            key, n = self.dc_lib.import_zip(Path(f))
        except (zipfile.BadZipFile, OSError, ValueError) as e:
            return messagebox.showerror(_("Import sticker pack"), f"{Path(f).name}: {e}")
        self.dc_pack = key
        self.dc_load_library()
        self.set_status(_n("Imported “{key}” with {n} sticker", "Imported “{key}” with {n} stickers", n, key=key))

    def _dc_target_pack(self):
        """Pack that new stickers go into: the shown pack, or the default pack when showing ALL."""
        if self.dc_pack != ALL:
            return self.dc_pack
        return self.dc_lib.ensure_pack(DEFAULT_PACK)

    def dc_add_stickers(self):
        """Ask for image files and copy them into the target sticker pack."""
        if self.dc_lib is None:
            return
        key = self._dc_target_pack()
        files = filedialog.askopenfilenames(title=_("Add images to “{pack}”", pack=key or _('Unsorted')), filetypes=img_types())
        if files:
            self._dc_import_stickers(files, key)
        else:
            self.dc_load_library()

    def _dc_import_stickers(self, files, key=None):
        """Copy image `files` into pack `key` and report errors and the count."""
        key = self._dc_target_pack() if key is None else key
        added, errors = self.dc_lib.import_images(files, key)
        if errors:
            messagebox.showerror(_("Cannot add image"), "\n".join(f"{n}: {e}" for n, e in errors[:10]))
        self.dc_load_library()
        if added:
            self.set_status(_n("Added {n} sticker to “{pack}”", "Added {n} stickers to “{pack}”", added,
                               pack=key or _('Unsorted')))

    def _dc_lib_drop(self, e):
        """Files dropped on the library: .zip files import as packs, images become stickers."""
        files = base.root.tk.splitlist(e.data)
        zips = [f for f in files if f.lower().endswith(".zip")]
        for z in zips:
            self.dc_import_pack(z)
        rest = [f for f in files if f not in zips]
        if rest:
            self._dc_import_stickers(rest)
        return e.action

    def _dc_lib_menu(self, e, p):
        """Right-click menu of a sticker thumbnail `p`: add to board, move to another pack or a new one, remove.
        """
        m = tk.Menu(base.root, tearoff=0, bg=C["panel"], fg=C["text"], activebackground=C["btnh"],
                    activeforeground=C["text"], bd=0)
        m.add_command(label=_("Add to board"), command=lambda: self.dc_add_sticker(p))
        mv = tk.Menu(m, tearoff=0, bg=C["panel"], fg=C["text"], activebackground=C["btnh"],
                     activeforeground=C["text"], bd=0)
        here = p.parent.resolve()
        for _k, d, name in self.dc_lib.packs():
            if d.resolve() != here:
                mv.add_command(label=name, command=lambda d=d: self._dc_lib_move(p, d))
        mv.add_separator()
        mv.add_command(label=_("New pack…"), command=lambda: self._dc_lib_move_new(p))
        m.add_cascade(label=_("Move to pack"), menu=mv)
        m.add_separator()
        m.add_command(label=_("Remove from library…"), command=lambda: self._dc_lib_remove(p))
        m.tk_popup(e.x_root, e.y_root)

    def _dc_lib_move(self, p, d):
        """Move sticker file `p` into pack folder `d`."""
        try:
            self.dc_lib.move(p, d)
        except OSError as e:
            messagebox.showerror(_("Move sticker"), str(e))
        self.dc_load_library()

    def _dc_lib_move_new(self, p):
        """Create a new pack and move sticker `p` into it."""
        cur = self.dc_pack
        key = self.dc_new_pack()
        if key:
            self._dc_lib_move(p, self.dc_lib.pack_dir(key))
            self.dc_pack = cur if cur != ALL else key
            self.dc_load_library()

    def _dc_lib_remove(self, p):
        """Delete sticker file `p` from the library after confirmation."""
        if messagebox.askyesno(_("Remove sticker"), _("Remove {name} from the sticker "
                                                   "library?\n\nThis deletes the file from its "
                                                   "pack folder.", name=p.name)):
            try:
                self.dc_lib.remove(p)
            except (OSError, ValueError) as e:
                messagebox.showerror(_("Remove sticker"), str(e))
            self.dc_load_library()

    # drag a sticker from the library onto the board
    def _dc_lib_press(self, e, p):
        """Start a possible drag of sticker `p` from the library."""
        self._dc_lib_drag = {"path": p, "x": e.x_root, "y": e.y_root, "moved": False}

    def _dc_lib_motion(self, e):
        """While dragging a sticker: once it moved more than 6 px, show a ghost thumbnail over the 3D canvas."""
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
            self.set_status(_("Release to place the sticker here") if self._dc_part(t) == ("deck", None)
                            else _("Drop it on the top of the deck"))
        else:
            self.dc_cv.itemconfig(self._dc_ghost_item, state="hidden")

    def _dc_lib_release(self, e):
        """End of a library drag: a plain click adds the sticker in the default place; a drop on the deck top (3D
        or flat view) adds it at that spot.
        """
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
            self.set_status(_("Drop stickers on the top of the deck (or the flat texture)"))

    def _dc_texel_at_root(self, xr, yr):
        """Texture pixel under screen point (xr, yr), from the 3D view (deck top only) or the flat view; None
        elsewhere.
        """
        name = base.widget_path_at(xr, yr)
        if name == str(self.dc_cv):
            t = self._dc_texel(xr - self.dc_cv.winfo_rootx(), yr - self.dc_cv.winfo_rooty(), radius=0)
            return t if self._dc_part(t) == ("deck", None) else None
        if name == str(self.dc_flat):
            return self._dc_flat_xy(xr - self.dc_flat.winfo_rootx(), yr - self.dc_flat.winfo_rooty())
        return None

    # ------------------------------------------------------------------ textures (base)
    def dc_load_textures(self):
        """Rebuild the base texture list: the board's own art, the built-in textures and the user's textures, each
        with a preview masked to the deck shape.
        """
        inner = self.dc_tex_scroll.inner
        for w in inner.winfo_children():
            w.destroy()
        self._dc_tex_rows = {}
        W, H = (self.dc.size if self.dc else (1920, 432))
        mask = self._v3_mask_for((W, H))
        items = [(basetex.ORIGINAL, _("Board's own art"))] + [(k, _(l)) for k, l, _f in basetex.BUILTIN] + \
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
            lab = tk.Label(fr, image=ph, bg=C["panel"], bd=0) if ph else tk.Label(fr, text=_("(cannot read)"), bg=C["panel"], fg=C["muted"])
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
        """Highlight the base texture in use and sync the tint slider and swatch."""
        cur = self.dc.base_key if self.dc else None
        for key, (fr, nm, use) in getattr(self, "_dc_tex_rows", {}).items():
            on = key == cur
            fr.config(highlightbackground=C["accent"] if on else C["border"])
            nm.config(fg=C["text"] if on else C["sub"], font=F["smallbold" if on else "small"])
            use.config(text=_("In use") if on else "")
        if self.dc:
            self.dc_tint.set(round(self.dc.tint_strength * 100))
            self.dc_tint_val.config(text=f"{self.dc_tint.get():.0f}%")
        self._dc_draw_tint()

    def _dc_draw_tint(self):
        """Paint the base-tint swatch."""
        sw = self.dc_tint_sw
        sw.delete("all")
        col = self.dc.tint if self.dc and self.dc.tint else (240, 168, 48)
        sw.create_rectangle(0, 0, 30, 20, fill=to_hex(col), outline="")

    def dc_set_base(self, key):
        """Use base texture `key` under the layers (one undo step)."""
        s = self.dc
        if s is None or key == s.base_key:
            return
        self._dc_push("base")
        s.base_key = key
        self._dc_apply_base(final=True)
        self.set_status(_("Base texture: {v}", v=basetex.label_of(key)))

    def _dc_apply_base(self, final=False, fast=False):
        """Rebuild the base image from key, tint and strength and redraw. Falls back to the board's own art if the
        texture cannot be made. `fast` is for slider drags, `final` for a full redraw.
        """
        s = self.dc
        if s is None:
            return
        W, H = s.size
        try:
            s.base_img = basetex.make_base(s.base_key, W, H, s.original, s.tint, s.tint_strength)
            s.base_regen = True
        except Exception as e:
            messagebox.showerror(_("Base texture"), _("Cannot use {v}: {e}", v=basetex.label_of(s.base_key), e=e))
            s.base_key, s.base_img = basetex.ORIGINAL, s.original
        s.composer.invalidate()
        self._dc_mark_base()
        self.dc_changed(fast=fast)

    def dc_pick_tint(self):
        """Ask for the base tint colour; turns the strength to 50% if it was 0."""
        s = self.dc
        if s is None:
            return
        rgb, _hx = colorchooser.askcolor(color=to_hex(s.tint or (240, 168, 48)), parent=base.root, title=_("Tint color"))
        if rgb:
            self._dc_push("tint")
            s.tint = tuple(int(round(v)) for v in rgb[:3])
            if s.tint_strength == 0:
                s.tint_strength = 0.5
            self._dc_apply_base(final=True)

    def _dc_tint_moved(self, _v=None):
        """Tint strength slider callback."""
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
        """Ask for image files and add them as user base textures."""
        files = filedialog.askopenfilenames(title=_("Add base textures"), filetypes=img_types())
        if files:
            self._dc_import_textures(files)

    def _dc_import_textures(self, files):
        """Copy `files` into the user texture folder and report errors and the count."""
        added, errors = basetex.add_user_textures(files)
        if errors:
            messagebox.showerror(_("Cannot add texture"), "\n".join(f"{n}: {e}" for n, e in errors[:10]))
        self.dc_load_textures()
        if added:
            self.set_status(_n("Added {n} texture to {folder}", "Added {n} textures to {folder}", added,
                               folder=basetex.texture_dir()))

    # ------------------------------------------------------------------ layers
    def dc_add_sticker(self, path, at=None):
        """Add the sticker image at `path` as a new layer, at texel `at` or the default spot."""
        if self.dc is None:
            return self.set_status(_("Pick a board first"))
        try:
            src = self._dc_open_src(path)
        except Exception as e:
            return messagebox.showerror(_("Cannot open image"), str(e))
        W, H = self.dc.size
        self._dc_add_layer(src, Path(path).stem, sticker_adjust(src, W, H, at))

    def dc_ask_image(self):
        """Ask for any image file and place it on the board."""
        f = filedialog.askopenfilename(title=_("Image to place on the board"), filetypes=img_types())
        if f:
            self.dc_load_image(f)

    def _dc_on_drop(self, e):
        """Files dropped on the canvas: each becomes a layer; the first goes where it was dropped."""
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
        """Add image file `f` as a new layer: wide, board-shaped images cover the deck, anything else is placed like a
        sticker (at texel `at` when given)."""
        if self.dc is None:
            return self.set_status(_("Pick a board first"))
        try:
            src = self._dc_open_src(f)
        except Exception as e:
            return messagebox.showerror(_("Cannot open image"), str(e))
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

    def _dc_add_layer(self, src, name, adj, gen=None):
        """Append a layer made from `src` with placement `adj` (and generator settings `gen` for text/shapes),
        select it, switch to Place mode and push one undo step.
        """
        s = self.dc
        self._dc_push("add")
        L = Layer(src, name, adj, gen=gen)
        s.layers.append(L)
        s.sel = L
        self.dc_opacity.set(100)
        if self.dc_mode.get() != "place":
            self.dc_mode.set("place")
        s.composer.invalidate()
        self.dc_changed(rebuild_list=True)
        self.set_status(_("Added {name}. Drag it on the board to move, wheel to scale, "
                          "Shift+wheel to rotate.", name=name))

    # -- text, shapes, mirror
    def dc_add_text(self):
        """Open the text dialog and add the result as a text layer."""
        if self.dc is None:
            return self.set_status(_("Pick a board first"))
        g = TS.default_text()
        if self.pal:
            g["color"] = [255, 255, 255]
        g = TextDialog.ask(base.root, g, _("Add text"))
        if g:
            W, H = self.dc.size
            src = TS.render_text(g)
            self._dc_add_layer(src, TS.gen_name(g), sticker_adjust(src, W, H), gen=g)

    def dc_add_shape(self, kind):
        """Add a shape layer of `kind` in the current wheel colour. Board-wide shapes (stripes, fades) fill the
        deck; others are placed like stickers.
        """
        if self.dc is None:
            return self.set_status(_("Pick a board first"))
        g = TS.default_shape(kind)
        if self.pal:
            g["color"] = [int(c) for c in self.pal[2][:3]]          # starts in the wheel colour
        W, H = self.dc.size
        src = TS.render_shape(g, (W, H))
        adj = Adjust(mode="fill") if kind in TS.BOARD_SHAPES else sticker_adjust(src, W, H)
        self._dc_add_layer(src, TS.gen_name(g), adj, gen=g)

    def dc_edit_layer(self):
        """Edit the selected generated layer: the text dialog for text, a colour picker for shapes. The layer is
        re-rendered and keeps its placement.
        """
        s = self.dc
        L = s.sel if s is not None else None
        if L is None or not L.gen:
            return
        g = dict(L.gen)
        if g.get("kind") == "text":
            new = TextDialog.ask(base.root, g, _("Edit text"))
        else:
            rgb, _hx = colorchooser.askcolor(color=to_hex(tuple(g.get("color", (240, 168, 48)))), parent=base.root,
                                             title=_("{v} colour", v=TS.gen_name(g)))
            new = dict(g, color=[int(round(v)) for v in rgb[:3]]) if rgb else None
        if not new or new == g:
            return
        self._dc_push("edit")
        L.set_src(TS.render_gen(new, s.size))
        L.gen, L.name, L.thumb = new, TS.gen_name(new), None
        s.composer.invalidate()
        self.dc_changed(rebuild_list=True)

    def dc_set_mirror(self, m):
        """Set the selected layer's mirror mode: '' off, 'ends' copy at nose/tail, 'sides' copy on the other side.
        """
        s = self.dc
        if s is None or s.sel is None or s.sel.mirror == m:
            return
        self._dc_push("mirror")
        s.sel.mirror = m
        s.composer.invalidate()
        self.dc_changed()
        self.set_status(_("Mirror off") if not m else
                        {"ends": _("Mirrored: a copy at the other end (nose and tail)"),
                         "sides": _("Mirrored: a copy on the other side")}[m]
                        + " · " + _("drag either one, they move together"))

    def _dc_mirror_sign(self, L, t):
        """How a drag on the copy at t moves the layer: (1, 1) for the layer itself."""
        part = L.hit_part(*t) if (L is not None and t is not None and L.mirror) else None
        if part != "mirror":
            return (1, 1)
        return (-1, -1) if L.mirror == "ends" else (1, -1)

    def _dc_main_point(self, L, t):
        """A point on the mirrored copy -> the same point on the layer itself, and the rotation sign."""
        part = L.hit_part(*t) if (L is not None and L.mirror) else None
        if part != "mirror":
            return t, 1
        W, H = self.dc.size
        return ((W - t[0], H - t[1]), 1) if L.mirror == "ends" else ((t[0], H - t[1]), -1)

    def dc_suggest_colors(self):
        """A small menu of board colour sets picked from the artwork (click one to use it)."""
        s = self.dc
        if s is None or self.pal is None:
            return self.set_status(_("Pick a board first"))
        if s.work is None:
            self.dc_compose()
        sets = color_suggestions(s.work, self._dc_mask)
        if not sets:
            return self.set_status(_("No colours found in the artwork"))
        old = getattr(self, "_dc_suggest_win", None)
        if old is not None:
            try:
                old.destroy()
            except tk.TclError:
                pass
        win = tk.Toplevel(base.root, bg=C["border"])
        self._dc_suggest_win = win
        win.overrideredirect(True)
        inner = tk.Frame(win, bg=C["panel"])
        inner.pack(padx=1, pady=1)
        label(inner, _("Colours from the artwork"), "smallbold", bg=C["panel"]).pack(anchor="w", padx=10, pady=(8, 2))
        label(inner, _("Border · Under · Wheels · Truck"), "small", "muted", bg=C["panel"]).pack(anchor="w", padx=10, pady=(0, 4))

        def use(cols, name):
            """Apply the suggested colour set `cols` (one undo step) and close the window."""
            win.destroy()
            self._dc_push("color")
            self.pal = [tuple(int(v) for v in c[:3]) for c in cols]
            self._draw_palette()
            self.set_status(_("Board colours: {name} (from the artwork) — Ctrl+Z to undo", name=_(name)))

        for name, cols in sets:
            row = tk.Frame(inner, bg=C["panel"], cursor="hand2")
            row.pack(fill="x", padx=6, pady=1)
            sw = tk.Frame(row, bg=C["panel"])
            sw.pack(side="left", padx=4, pady=4)
            parts = [row, sw]
            for c in cols:
                cv = tk.Frame(sw, bg=to_hex(c), width=26, height=18, highlightthickness=1,
                              highlightbackground=C["btnb"])
                cv.pack(side="left", padx=1)
                parts.append(cv)
            lb = label(row, _(name), "small", bg=C["panel"])
            lb.pack(side="left", padx=8)
            parts.append(lb)
            for w in parts:
                w.bind("<Button-1>", lambda e, c=cols, n=name: use(c, n))
                w.bind("<Enter>", lambda e, r=row: r.config(bg=C["btnh"]))
                w.bind("<Leave>", lambda e, r=row: r.config(bg=C["panel"]))
        tk.Frame(inner, bg=C["panel"], height=6).pack()
        b = self.dc_suggest_btn
        win.update_idletasks()
        x = b.winfo_rootx() + b.winfo_width() - win.winfo_reqwidth()
        win.geometry(f"+{max(0, x)}+{b.winfo_rooty() + b.winfo_height() + 2}")
        win.bind("<Escape>", lambda e: win.destroy())
        win.bind("<FocusOut>", lambda e: win.after(150, lambda: win.winfo_exists() and win.destroy()))
        win.focus_force()

    def dc_select_layer(self, L):
        """Select layer `L` (None deselects) and sync the controls."""
        s = self.dc
        if s is None or L is s.sel:
            return
        s.sel = L
        s.composer.invalidate()
        if L is not None:
            self.dc_opacity.set(round(L.opacity * 100))
        self.dc_changed(rebuild_list=True)

    def dc_move_layer(self, d):
        """Move the selected layer `d` steps up (+) or down (-) in the stack."""
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
        """Copy the selected layer, nudged a little so the copy is visible, and select it."""
        s = self.dc
        if s is None or s.sel is None:
            return
        L = s.sel
        W, H = s.size
        adj = dataclasses.replace(L.adj)
        cx, cy = L.center(W, H)
        adj.cx, adj.cy = cx + W * 0.04, cy + H * 0.06
        self._dc_push("add")
        N = Layer(L.src, L.name, adj, L.opacity, fx=dict(L.fx), color=dict(L.color), mirror=L.mirror,
                  gen=dict(L.gen) if L.gen else None)
        s.layers.insert(s.layers.index(L) + 1, N)
        s.sel = N
        s.composer.invalidate()
        self.dc_changed(rebuild_list=True)

    def dc_delete_layer(self):
        """Remove the selected layer and select its neighbour."""
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
        """Show or hide layer `L` (hidden layers are not saved into the texture)."""
        self._dc_push("visible")
        L.visible = not L.visible
        self.dc.composer.invalidate()
        self.dc_changed(rebuild_list=True)

    def dc_set_fit(self, mode):
        """Reset the selected layer to fit `mode` ('fill' covers the deck, 'fit' fits inside it) at zoom 1; 'fill'
        also re-centres it."""
        s = self.dc
        if s is None or s.sel is None:
            return
        self._dc_push("fit")
        s.sel.adj.mode, s.sel.adj.zoom = mode, 1.0
        if mode == "fill":
            s.sel.adj.cx = s.sel.adj.cy = None
        self.dc_changed()

    def dc_rotate(self, deg):
        """Rotate the selected layer by `deg` degrees around its centre."""
        s = self.dc
        if s and s.sel is not None:
            self._dc_push("rotate90")
            s.sel.adj.angle = (s.sel.adj.angle + deg) % 360
            self.dc_changed()

    def dc_flip(self):
        """Flip the selected layer horizontally."""
        s = self.dc
        if s and s.sel is not None:
            self._dc_push("flip")
            s.sel.adj.flip_h = not s.sel.adj.flip_h
            self.dc_changed()

    def _dc_opacity_moved(self, _v=None):
        """Opacity slider callback for the selected layer."""
        s = self.dc
        self.dc_op_val.config(text=f"{self.dc_opacity.get():.0f}%" if s and s.sel else "")
        if s and s.sel is not None and abs(s.sel.opacity - self.dc_opacity.get() / 100) > 1e-6:
            s.sel.opacity = self.dc_opacity.get() / 100
            self.dc_changed(fast=True)

    def _dc_scale_at(self, p, f):
        """Scale the selected layer by factor `f` around texture point `p` (zoom kept between 0.03 and 20)."""
        L, W, H = self.dc.sel, *self.dc.size
        z = min(20.0, max(0.03, L.adj.zoom * f))
        f = z / L.adj.zoom
        cx, cy = L.center(W, H)
        L.adj.zoom = z
        L.adj.cx, L.adj.cy = p[0] + (cx - p[0]) * f, p[1] + (cy - p[1]) * f
        self.dc_changed(fast=True)

    def _dc_rotate_at(self, p, deg):
        """Rotate the selected layer by `deg` around texture point `p`."""
        L, W, H = self.dc.sel, *self.dc.size
        cx, cy = L.center(W, H)
        t = math.radians(deg)
        dx, dy = cx - p[0], cy - p[1]
        L.adj.cx = p[0] + dx * math.cos(t) - dy * math.sin(t)
        L.adj.cy = p[1] + dx * math.sin(t) + dy * math.cos(t)
        L.adj.angle = (L.adj.angle + deg) % 360
        self.dc_changed(fast=True)

    def _dc_layer_at(self, t):
        """Topmost visible layer that covers texel `t`, or None."""
        if t is None or self.dc is None:
            return None
        for L in reversed(self.dc.layers):
            if L.hit(*t):
                return L
        return None

    def dc_revert(self):
        """Back to how the board was when it was last saved (or opened): every unsaved layer, effect,
        base texture and color change goes. Ctrl+Z brings them back."""
        s = self.dc
        if s is None or not (s.dirty() or self._pal_changed()):
            return
        st = getattr(s, "saved_state", None)
        if st is None:
            return
        self._dc_push("revert")
        snaps, sel, _pal, bkey, tint, strength, finish = st
        self._dc_restore((snaps, None, list(self.pal_orig) if self.pal_orig else None, bkey, tint, strength, finish))
        self._dc_mark_base()
        self.set_status(_("Back to the last saved board. Ctrl+Z brings your changes back."))

    def dc_clear(self):
        """Remove all layers, effects, base texture, tint and colour changes (one undo step)."""
        s = self.dc
        if s is None or not (s.layers or s.base_key != basetex.ORIGINAL or self._pal_changed()
                             or any(s.finish.values())):
            return
        self._dc_push("clear")
        s.layers, s.sel = [], None
        s.finish = {}
        s.base_key, s.tint, s.tint_strength, s.base_img = basetex.ORIGINAL, None, 0.0, s.original
        if self.pal_orig:
            self.pal = list(self.pal_orig)
        s.composer.invalidate()
        self._dc_mark_base()
        self._draw_palette()
        self.dc_changed(rebuild_list=True)
        self.set_status(_("Cleared. Ctrl+Z brings it back."))

    # -- undo
    def _dc_state(self):
        """Snapshot used by undo: layer states, selection, colours, base, tint and finish."""
        s = self.dc
        return ([L.snapshot() for L in s.layers], s.sel, list(self.pal) if self.pal else None,
                s.base_key, s.tint, s.tint_strength, dict(s.finish))

    def _dc_push(self, kind):
        """Push an undo step before a change of `kind`. Repeated wheel/opacity/tint/fx/finish changes within 0.8 s
        merge into one step. Keeps at most 80 steps and clears redo.
        """
        s = self.dc
        if s is None:
            return
        now = time.monotonic()
        if kind in ("wheel", "opacity", "tint", "fx", "finish") and s.last_undo[0] == kind \
                and now - s.last_undo[1] < 0.8:
            s.last_undo = (kind, now)
            return
        s.last_undo = (kind, now)
        s.undo.append(self._dc_state())
        del s.undo[:-80]
        s.redo.clear()

    def _dc_restore(self, st):
        """Put back a snapshot made by `_dc_state` and redraw everything."""
        s = self.dc
        snaps, sel, pal, bkey, tint, strength, finish = st
        s.layers = []
        for snap in snaps:
            L = snap[0]
            L.restore(snap)
            L.thumb = None
            s.layers.append(L)
        s.finish = dict(finish)
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
        """Undo the last change on this board."""
        s = self.dc
        if s and s.undo:
            s.redo.append(self._dc_state())
            self._dc_restore(s.undo.pop())
            s.last_undo = (None, 0.0)

    def dc_redo(self):
        """Redo the last undone change on this board."""
        s = self.dc
        if s and s.redo:
            s.undo.append(self._dc_state())
            self._dc_restore(s.redo.pop())
            s.last_undo = (None, 0.0)

    # ------------------------------------------------------------------ colors
    def _dc_pick_color(self, k):
        """Change board colour `k` with the shared colour picker; records one undo step if the colour changed.
        """
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
        """Redraw the board colour swatches; changed colours get a marker."""
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
        """Composes the texture. Returns the changed rectangles (texture pixels) when only part of
        it changed (dragging), else None."""
        import numpy as np
        s = self.dc
        if s is None:
            return None
        work = s.composer.compose(s.base_img, s.layers, s.sel, self.pal, fast, s.finish_obj(self._dc_mask))
        s.work = work
        regions = s.composer.last_regions
        outline = s.sel is not None and self.dc_mode.get() == "place"
        ta = self.dc_texarr
        if regions and ta is not None and ta.shape[:2] == (work.height, work.width) \
                and ta.flags.writeable:
            # update just the changed rectangles of the display texture (with the selection outline)
            W, H = work.size
            for region in regions:
                x0, y0, x1, y1 = region
                part = work.crop(region)
                if outline and s.sel.visible:
                    dr = ImageDraw.Draw(part)
                    for cs in s.sel.all_corners(W, H):
                        pts = [(x - x0, y - y0) for x, y in cs]
                        dr.line(pts + [pts[0]], fill=_rgb(C["accent"])[:3] + (255,), width=max(3, W // 400))
                ta[y0:y1, x0:x1] = np.asarray(part.convert("RGB"))
                if self.pal and y0 == 0 and x0 < len(self.pal):
                    for x, c in enumerate(self.pal[:min(len(self.pal), work.width)]):
                        ta[0, x] = c[:3]
            return regions
        disp = with_outline(work, s.sel, _rgb(C["accent"]), self.pal) if outline else work
        self.dc_texarr = np.array(disp.convert("RGB"))        # writable: dragging updates it in place
        return None

    def dc_changed(self, fast=False, rebuild_list=False):
        """Texture edited, camera unchanged: re-texture the last 3D frame (no new rasterizing)."""
        from ..board3d import retexture, retexture_region
        if self.dc is None:
            return
        regions = self.dc_compose(fast)
        if self.dc_info is not None and self.dc_info.get("tex_size") == self.dc.size:
            info = self.dc_info
            if regions:
                boxes, whole = [], False
                for region in regions:
                    img = retexture_region(info, self.dc_texarr, region)
                    cb = info.get("changed_box")
                    if cb is None:                       # the whole frame was redone
                        whole = True
                    else:
                        boxes.append(cb)
                # a partial update is only right if the screen shows this same frame
                same = getattr(self, "_dc_shown", None) is info and not whole
                self._dc_show(img, box=boxes if same else None)
            else:
                self._dc_show(retexture(info, self.dc_texarr))
            self._dc_shown = info
        else:
            self.dc_render()
        if fast and regions:
            for region in regions:
                self.dc_draw_flat(region)       # just the rectangles the sticker moved through
        elif fast:
            # a whole-texture change while dragging: redraw at most ~30 times a second
            if getattr(self, "_dc_flat_job", None) is None:
                self._dc_flat_job = base.root.after(33, self._dc_flat_due)
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
        """Delayed flat-view redraw (scheduled by dc_changed)."""
        self._dc_flat_job = None
        self.dc_draw_flat()

    def _dc_sharpen(self):
        """After a fast (low-resolution) interaction, redraw at full quality once nothing is being dragged."""
        self._dc_sharp = None
        if self._dc_drag is None and self.dc is not None:
            self.dc.composer.invalidate()
            self.dc_changed()

    def _dc_schedule_update(self):
        """Ask for one fast redraw when Tk is idle (coalesces many drag events)."""
        if self._dc_upd is None:
            self._dc_upd = base.root.after_idle(self._dc_run_update)

    def _dc_run_update(self):
        """Run the redraw scheduled by `_dc_schedule_update`."""
        self._dc_upd = None
        self.dc_changed(fast=True)

    def dc_render(self, fast=False):
        """Send a 3D render request for the current texture and camera. The size is capped (lower while dragging on
        the CPU) to keep the preview responsive.
        """
        if not hasattr(self, "dc_cv") or self.tab_var.get() != "decor":
            return
        if self.v3_model is None:
            return self._dc_msg(self.v3_err or _("Board model not found"))
        if self.dc is None or self.dc_texarr is None:
            return
        W, H = max(200, self.dc_cv.winfo_width()), max(150, self.dc_cv.winfo_height())
        from ..board3d import gpu_active
        gpu = gpu_active()
        # on the GPU even frames while turning are drawn at full resolution
        s = min(1.0, ((1920 * 1200 if gpu else 1300 * 760) / float(W * H)) ** 0.5) * (0.5 if fast and not gpu else 1.0)
        self.dc_renderer.request(model=self.v3_model, tex=self.dc_texarr, yaw=self.dc_yaw, pitch=self.dc_pitch,
                                 zoom=self.dc_zoom, W=max(1, int(W * s)), H=max(1, int(H * s)),
                                 screws=self.v3_screws.get(), outline=self.v3_outline.get(),
                                 bg=_rgb(C["bg"])[:3], canvas=(W, H), fast=fast)

    def _dc_poll(self):
        """Timer on the Tk thread: take finished frames from the renderer, show the newest, keep its pick info for
        mouse hits, and re-request a sharp frame if the camera moved meanwhile.
        """
        from ..board3d import retexture
        try:
            while True:
                job, img, info, ms = self.dc_renderer.results.get_nowait()
                if not hasattr(self, "dc_cv") or not self.dc_cv.winfo_exists():
                    continue
                if isinstance(img, Exception):
                    self._dc_msg(_("3D preview failed: {img}", img=img))
                    continue
                if (job["yaw"], job["pitch"], job["zoom"]) != (self.dc_yaw, self.dc_pitch, self.dc_zoom) \
                        and not job["fast"]:
                    continue
                shown = None
                if not job["fast"]:
                    self.dc_info = info
                    self.dc_info_scale = job["W"] / float(job["canvas"][0])
                    if self.dc_texarr is not None \
                            and info.get("tex_size") == (self.dc_texarr.shape[1], self.dc_texarr.shape[0]):
                        img = retexture(info, self.dc_texarr)    # the texture may have changed meanwhile
                        shown = info
                self._dc_show(img, job["canvas"])
                self._dc_shown = shown                           # which frame data is on screen
        except queue.Empty:
            pass
        except tk.TclError:
            pass
        if self.tab_var.get() == "decor":
            base.root.after(15, self._dc_poll)
        else:
            self._dc_polling = False

    def _dc_show(self, img, canvas=None, box=None):
        """Shows a 3D frame. With `box` (the screen rectangle that changed, from retexture_region,
        or a list of them) only those parts are copied into the shown image."""
        c = self.dc_cv
        W, H = canvas or (c.winfo_width(), c.winfo_height())
        ph = self._dc_photo
        if box is not None and img.size == (W, H) and ph is not None and (ph.width(), ph.height()) == (W, H):
            for b in (box if isinstance(box, list) else [box]):
                x0, y0, x1, y1 = b
                if x1 > x0 and y1 > y0:
                    part = ImageTk.PhotoImage(img.crop(b))
                    c.tk.call(str(ph), "copy", str(part), "-to", x0, y0)
            return
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
        """Show `text` in the middle of the 3D canvas instead of a picture."""
        if not hasattr(self, "dc_cv"):
            return
        c = self.dc_cv
        c.coords(self._dc_msg_item, max(100, c.winfo_width() / 2), max(60, c.winfo_height() / 2))
        c.itemconfig(self._dc_msg_item, text=text)
        if self._dc_photo is not None:
            c.itemconfig(self._dc_img_item, image="")
            self._dc_photo = None

    def _dc_view(self, yaw, pitch):
        """Set the camera to `yaw`/`pitch` degrees and redraw."""
        self.dc_yaw, self.dc_pitch = yaw, pitch
        self.dc_info = None
        self.dc_render()

    # ------------------------------------------------------------------ picking + mouse
    def _dc_texel(self, x, y, radius=2):
        """Texture pixel under canvas point (x, y) using the last frame's pick info; `radius` searches nearby
        pixels so edges are easier to hit.
        """
        from ..board3d import pick_texel
        if self.dc_info is None:
            return None
        s = self.dc_info_scale
        return pick_texel(self.dc_info, int(x * s), int(y * s), radius)

    @staticmethod
    def _dc_part(t):
        """What a texel belongs to: ('palette', k) for the k-th colour row of the texture, ('deck', None) for the
        art, None for nothing.
        """
        if t is None:
            return None
        if t[1] == 0 and t[0] < len(PART_NAMES):
            return "palette", t[0]
        return "deck", None

    def _dc_on_hover(self, e):
        """Mouse move over the 3D view: update the cursor, the flat-view marker and the status text."""
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
                self.set_status(_("{part}  {color}  — click to change", part=_(PART_NAMES[part[1]]), color=to_hex(self.pal[part[1]])))

            return
        L = self._dc_layer_at(t) if self.dc_mode.get() == "place" else None
        self.dc_cv.config(cursor="fleur" if L else "arrow")
        self.set_status(_("{name} — drag to move, wheel to scale, Shift+wheel to rotate", name=L.name) if L else
                        _("Deck top · texture pixel {v}, {v2}", v=t[0], v2=t[1]))

    def _dc_set_hover(self, t):
        """Remember the hovered texel and redraw the flat-view marker."""
        self._dc_hover = t
        self._dc_draw_marker()

    def _dc_press(self, e, btn):
        """Mouse press on the 3D view: in Place mode, pick the layer under the cursor to move it; otherwise start
        turning the camera.
        """
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
                         "layer": L, "t0": t, "c0": L.center(W, H) if L else None,
                         "sign": self._dc_mirror_sign(L, t)}

    def _dc_move(self, e):
        """Mouse drag on the 3D view: move the layer (mirrored copies move the other way) or turn the camera."""
        d = self._dc_drag
        if d is None:
            return
        if abs(e.x - d["x0"]) + abs(e.y - d["y0"]) > 3:
            d["moved"] = True
        L = d["layer"]
        if L is not None:
            t = self._dc_texel(e.x, e.y, radius=0)
            if t is not None and self._dc_part(t) == ("deck", None):
                sx, sy = d.get("sign", (1, 1))
                L.adj.cx = d["c0"][0] + sx * (t[0] - d["t0"][0])
                L.adj.cy = d["c0"][1] + sy * (t[1] - d["t0"][1])
                self._dc_schedule_update()
            return
        dx, dy = e.x - d["x"], e.y - d["y"]
        d["x"], d["y"] = e.x, e.y
        self.dc_yaw = (self.dc_yaw + dx * 0.5) % 360
        self.dc_pitch = max(-89.0, min(89.0, self.dc_pitch + dy * 0.4))
        self.dc_info = None
        self.dc_render(fast=True)

    def _dc_release(self, e):
        """Mouse release: a click without movement selects, deselects or opens a colour picker; a drag ends with a
        sharp redraw.
        """
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
        """Cancel any drag and redraw at full quality."""
        self._dc_drag = None
        self._dc_sharpen()

    def _dc_wheel(self, e, direction):
        """Mouse wheel on the 3D view: over the selected layer it scales (Shift rotates 5°); elsewhere it zooms the
        camera.
        """
        s = self.dc
        if s is not None and self.dc_mode.get() == "place" and s.sel is not None:
            t = self._dc_texel(e.x, e.y)
            if self._dc_part(t) == ("deck", None) and (self._dc_layer_at(t) is s.sel or s.sel.hit(*t)):
                self._dc_push("wheel")
                p, rs = self._dc_main_point(s.sel, t)
                if e.state & 0x0001:
                    self._dc_rotate_at(p, 5 * direction * rs)
                else:
                    self._dc_scale_at(p, 1.1 if direction > 0 else 1 / 1.1)
                return
        self.dc_zoom = max(0.4, min(4.0, self.dc_zoom * (1.1 if direction > 0 else 1 / 1.1)))
        self.dc_info = None
        self.dc_render(fast=True)
        if self._dc_sharp:
            base.root.after_cancel(self._dc_sharp)
        self._dc_sharp = base.root.after(220, lambda: (setattr(self, "_dc_sharp", None), self.dc_render()))

    # ------------------------------------------------------------------ flat texture view
    def _dc_flat_k(self):
        """Scale from texture pixels to the flat view. In the Skate shop the flat deck stands upright, so the
        canvas width is resized to match.
        """
        if self.dc is None:
            return None
        if self._dc_shop():
            # upright deck (Skate shop): the texture's long side runs down the canvas height
            ch = max(80, self.dc_flat.winfo_height())
            W, H = self.dc.size
            k = ch / W
            w = max(20, int(H * k))
            if int(float(self.dc_flat.cget("width"))) != w:
                self.dc_flat.config(width=w)
            return k
        cw = max(50, self.dc_flat.winfo_width())
        W, H = self.dc.size
        k = cw / W
        h = max(20, int(H * k))
        if int(float(self.dc_flat.cget("height"))) != h:
            self.dc_flat.config(height=h)
        return k

    def _dc_fpt(self, x, y, k):
        """View point of texture-scaled point (x, y): turned a quarter (nose at the bottom, like
        the decks on the Wall) in the Skate shop layout, unchanged otherwise."""
        if self._dc_shop() and self.dc is not None:
            return y, self.dc.size[0] * k - x
        return x, y

    def _dc_fimg(self, img, at=(0, 0), full=None):
        """Turns a flat-view image (or a part of it at `at` in the turned view) upright for the
        Skate shop layout and rounds it like a deck: outside the rounded ends shows the wall colour."""
        if not self._dc_shop():
            return img
        img = img.transpose(Image.ROTATE_90)
        if full is None:
            full = img.size
        key = (full, C["bg"])
        cache = getattr(self, "_dc_round", None)
        if cache is None or cache[0] != key:
            from PIL import ImageDraw
            fw, fh = full
            m = Image.new("L", full, 0)
            ImageDraw.Draw(m).rounded_rectangle((0, 0, fw - 1, fh - 1), radius=fw // 2, fill=255)
            cache = self._dc_round = (key, m)
        x, y = at
        m = cache[1].crop((x, y, x + img.width, y + img.height))
        out = Image.new("RGBA", img.size, _rgb(C["bg"])[:3] + (255,))
        out.paste(img, (0, 0), m)
        return out

    def dc_draw_flat(self, region=None):
        """The flat texture view. With `region` (texture pixels) only that rectangle is redrawn and
        pasted into the shown image, so dragging updates it on every mouse move. Layer outlines
        are canvas lines on top (moving them costs almost nothing)."""
        if not hasattr(self, "dc_flat"):
            return
        k = self._dc_flat_k()
        if not k:
            self.dc_flat.delete("img", "outline")
            self._dc_flat_photo = None
            return
        s = self.dc
        W, H = s.size
        sw, sh = max(1, int(W * k)), max(1, int(H * k))
        photo = self._dc_flat_photo
        key = (id(s), sw, sh, C["chk1"])
        if region is None or photo is None or getattr(self, "_dc_flat_key", None) != key \
                or not self.dc_flat.find_withtag("img"):
            self._dc_flat_photo = ImageTk.PhotoImage(self._dc_fimg(self._dc_flat_part(s, (0, 0, sw, sh), sw, sh),
                                                                   full=(sh, sw)))
            self._dc_flat_key = key
            self.dc_flat.delete("img")
            self.dc_flat.create_image(0, 0, anchor="nw", image=self._dc_flat_photo, tags="img")
            self.dc_flat.tag_lower("img")
        else:
            x0, y0, x1, y1 = region
            bx0, by0 = max(0, int(math.floor(x0 * sw / W)) - 1), max(0, int(math.floor(y0 * sh / H)) - 1)
            bx1, by1 = min(sw, int(math.ceil(x1 * sw / W)) + 1), min(sh, int(math.ceil(y1 * sh / H)) + 1)
            if bx1 > bx0 and by1 > by0:
                tx, ty = (by0, sw - bx1) if self._dc_shop() else (bx0, by0)
                part = ImageTk.PhotoImage(self._dc_fimg(self._dc_flat_part(s, (bx0, by0, bx1, by1), sw, sh),
                                                        at=(tx, ty), full=(sh, sw)))
                # Tk copies the small image into the shown one in place (works with any Pillow)
                self.dc_flat.tk.call(str(photo), "copy", str(part), "-to", tx, ty)
        self._dc_flat_outlines(k)
        self._dc_flat_deckline(sw, sh)
        self._dc_draw_marker()

    def _dc_flat_deckline(self, sw, sh):
        """Skate shop: a rounded deck outline in the board's edge colour around the upright view."""
        f = self.dc_flat
        f.delete("deck")
        if not self._dc_shop():
            return
        w, h = sh, sw                           # the upright view is turned a quarter
        r = w / 2
        col = to_hex(self.pal[0]) if self.pal else C.get("ink", C["text"])
        e = 2                                   # half the line width: the line sits inside the deck
        f.create_arc(e, e, w - e, 2 * r - e, start=0, extent=180, style="arc", outline=col, width=4, tags="deck")
        f.create_arc(e, h - 2 * r + e, w - e, h - e, start=180, extent=180, style="arc", outline=col, width=4,
                     tags="deck")
        f.create_line(e, r, e, h - r, fill=col, width=4, tags="deck")
        f.create_line(w - e, r, w - e, h - r, fill=col, width=4, tags="deck")
        f.tag_raise("outline")
        f.tag_raise("mark")

    def _dc_flat_part(self, s, box, sw, sh):
        """Rectangle `box` (view pixels) of the flat view: texture scaled down, over the checker
        color, with the area that doesn't show on the deck dimmed."""
        W, H = s.size
        bx0, by0, bx1, by1 = box
        fx, fy = W / sw, H / sh
        # cut the area out first (with room for the filter): Pillow would otherwise convert the
        # whole texture before resizing even a small rectangle
        m = int(math.ceil(max(fx, fy))) + 2
        cx0, cy0 = max(0, int(bx0 * fx) - m), max(0, int(by0 * fy) - m)
        cx1, cy1 = min(W, int(math.ceil(bx1 * fx)) + m), min(H, int(math.ceil(by1 * fy)) + m)
        src = s.work if (cx0, cy0, cx1, cy1) == (0, 0, W, H) else s.work.crop((cx0, cy0, cx1, cy1))
        small = src.resize((bx1 - bx0, by1 - by0), Image.BILINEAR,
                           box=(bx0 * fx - cx0, by0 * fy - cy0, bx1 * fx - cx0, by1 * fy - cy0))
        small = Image.alpha_composite(Image.new("RGBA", small.size, _rgb(C["chk1"])[:3] + (255,)), small)
        if self._dc_mask is not None:
            # dim what doesn't show on the deck: blended on top, so the result stays fully opaque
            # (a partly transparent image would let old content show through when pasted)
            mk = getattr(self, "_dc_mask_small", None)
            if mk is None or mk[0] != (id(self._dc_mask), (sw, sh)):
                shade = Image.new("RGBA", (sw, sh), (0, 0, 0, 0))
                shade.putalpha(self._dc_mask.resize((sw, sh), Image.BILINEAR).point(lambda v: (255 - v) * 150 // 255))
                mk = self._dc_mask_small = ((id(self._dc_mask), (sw, sh)), shade)
            small = Image.alpha_composite(small, mk[1].crop(box))
        return small

    def _dc_flat_outlines(self, k):
        """Draw the outline of each visible layer on the flat view (selected one highlighted). Only in Place mode.
        """
        f = self.dc_flat
        f.delete("outline")
        s = self.dc
        if s is None or self.dc_mode.get() != "place":
            return
        W, H = s.size
        for L in s.layers:
            if L.visible:
                on = L is s.sel
                for cs in L.all_corners(W, H, k):
                    pts = [c for xy in cs for c in self._dc_fpt(xy[0], xy[1], k)]
                    f.create_polygon(*pts, fill="", outline=C["accent"] if on else C["muted"],
                                     width=2 if on else 1, tags="outline")

    def _dc_draw_marker(self):
        """Draw the crosshair at the hovered texel on the flat view."""
        if not hasattr(self, "dc_flat"):
            return
        self.dc_flat.delete("mark")
        k = self._dc_flat_k() if self.dc else None
        if not k or self._dc_hover is None:
            return
        x, y = self._dc_fpt(self._dc_hover[0] * k, self._dc_hover[1] * k, k)
        col = C["accent"]
        self.dc_flat.create_line(x - 9, y, x + 9, y, fill=col, width=2, tags="mark")
        self.dc_flat.create_line(x, y - 9, x, y + 9, fill=col, width=2, tags="mark")
        self.dc_flat.create_oval(x - 4, y - 4, x + 4, y + 4, outline=col, tags="mark")

    def _dc_flat_xy(self, x, y):
        """Texture pixel for flat-view point (x, y), undoing the upright rotation in the Skate shop; None outside
        the texture.
        """
        k = self._dc_flat_k()
        if not k:
            return None
        W, H = self.dc.size
        if self._dc_shop():
            x, y = W * k - y, x                 # back from the upright view
        tx, ty = x / k, y / k
        return (tx, ty) if 0 <= tx < W and 0 <= ty < H else None

    def _dc_flat_hover(self, e):
        """Mouse move over the flat view: marker and status text."""
        t = self._dc_flat_xy(e.x, e.y)
        if t is not None and self._dc_drag is None:
            self._dc_hover = (int(t[0]), int(t[1]))
            self._dc_draw_marker()
            L = self._dc_layer_at(t)
            self.set_status(_("{name} — drag to move", name=L.name) if L else _("Texture pixel {v}, {v2}", v=int(t[0]), v2=int(t[1])))

    def _dc_flat_press(self, e):
        """Mouse press on the flat view: select the layer there and start moving it."""
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
        self._dc_drag = {"flat": True, "layer": L, "t0": t, "c0": L.center(W, H), "sign": self._dc_mirror_sign(L, t)}

    def _dc_flat_move(self, e):
        """Drag on the flat view: move the layer."""
        d = self._dc_drag
        t = self._dc_flat_xy(e.x, e.y)
        if d and d.get("flat") and t is not None:
            sx, sy = d.get("sign", (1, 1))
            d["layer"].adj.cx = d["c0"][0] + sx * (t[0] - d["t0"][0])
            d["layer"].adj.cy = d["c0"][1] + sy * (t[1] - d["t0"][1])
            self._dc_schedule_update()

    def _dc_flat_wheel(self, e, direction):
        """Mouse wheel on the flat view: scale the selected layer (Shift rotates 5°)."""
        t = self._dc_flat_xy(e.x, e.y)
        if t is None or self.dc is None or self.dc.sel is None:
            return
        self._dc_push("wheel")
        t, rs = self._dc_main_point(self.dc.sel, t)
        if e.state & 0x0001:
            self._dc_rotate_at(t, 5 * direction * rs)
        else:
            self._dc_scale_at(t, 1.1 if direction > 0 else 1 / 1.1)

    # ------------------------------------------------------------------ panel state
    def _dc_rebuild_layers(self):
        """Rebuild the layer list, top layer first, with thumbnail, name, visibility and selection."""
        inner = self.dc_layer_scroll.inner
        for w in inner.winfo_children():
            w.destroy()
        s = self.dc
        if s is None or not s.layers:
            wl = max(140, self.dc_layer_scroll.winfo_width() - 40) if self.dc_layer_scroll.winfo_ismapped() else 200
            label(inner, _("No layers yet. Drag a sticker onto the board."), "small", "muted",
                  bg=inner.cget("bg"), wraplength=wl, justify="left").pack(anchor="w", padx=8, pady=8)
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
            eye = tk.Label(row, text=_("Shown") if L.visible else _("Hidden"), bg=bg,
                           fg=C["sub"] if L.visible else C["dis"], font=F["small"], cursor="hand2")
            eye.pack(side="right", padx=8)
            eye.bind("<Button-1>", lambda e, L=L: self.dc_toggle_visible(L))
            for w in (row, th, nm):
                w.bind("<Button-1>", lambda e, L=L: (self.dc_mode.set("place"), self.dc_select_layer(L)))
                if L.gen:
                    w.bind("<Double-Button-1>", lambda e, L=L: (self.dc_select_layer(L), self.dc_edit_layer()))

    def _dc_mode_changed(self):
        """Place / View mode switch callback."""
        if self.dc is not None:
            self.dc_changed()
        self._dc_refresh_controls()

    def _dc_refresh_all(self):
        """Refresh every Decorate control after switching boards or undo/redo."""
        if not hasattr(self, "dc_cv"):
            return
        self._dc_rebuild_layers()
        self._dc_mark_base()
        self._dc_draw_colors()
        self.dc_draw_flat()
        self._dc_refresh_controls()

    def _dc_refresh_controls(self):
        """Enable, disable and relabel the controls for the current selection (layer tools, mirror, edit, opacity,
        save/undo/redo).
        """
        if not hasattr(self, "dc_cv"):
            return
        if self.dc_left_tab.get() == "effects":
            self._dc_sync_fx()
        s = self.dc
        on = s is not None and s.sel is not None
        set_state(self.dc_sel_btns, on)
        L = s.sel if on else None
        self.dc_mirror_btn.config(text=_("Mirror: {mode}", mode=_(dict(MIRRORS).get(L.mirror if L else "", "Off"))) + " \u25be")
        gk = (L.gen or {}).get("kind") if L is not None else None
        if self._dc_shop():
            self._dc_layers_shop_refresh(L, gk)
        self.dc_edit_btn.config(text=_("Edit text…") if gk == "text" else _("Edit colour…") if gk == "shape" else _("Edit…"))
        set_state([self.dc_edit_btn], bool(gk))
        self.dc_op_scale.state(["!disabled"] if on else ["disabled"])
        self.dc_op_val.config(text=f"{self.dc_opacity.get():.0f}%" if on else "")
        dirty = s is not None and (s.dirty() or bool(self._pal_changed()))
        set_state([self.dc_b_save], s is not None)
        set_state([self.dc_b_clear], s is not None and (bool(s.layers) or s.base_key != basetex.ORIGINAL
                                                         or bool(self._pal_changed()) or any(s.finish.values())))
        rb = getattr(self, "dc_b_revert", None)
        if rb is not None and rb.winfo_exists():
            set_state([rb], s is not None and getattr(s, "saved_state", None) is not None
                      and (s.dirty() or bool(self._pal_changed())))
        set_state([self.dc_b_undo], bool(s and s.undo))
        set_state([self.dc_b_redo], bool(s and s.redo))
        if s is None:
            self.dc_title.config(text=_("No board selected"))
            self.dc_chip.config(text="")
            self.dc_tex_file.config(text="")
            self.dc_changes.config(text="")
        else:
            name = self.boards[self.sel].name if self.sel is not None and self.sel < len(self.boards) else s.path.stem
            self.dc_title.config(text=_("Board {name}", name=name))
            n = len(s.layers)
            self.dc_chip.config(text=_("Decorating") + " · " + _n("{n} layer", "{n} layers", n)
                                     + (_(" · unsaved") if dirty else ""),
                                bg=C["warnbg"] if dirty else C["btn"], fg=C["warn"] if dirty else C["sub"])
            self.dc_tex_file.config(text=s.path.name)
            parts = []
            if s.layers:
                parts.append(_n("{n} layer", "{n} layers", n))
            if s.base_key != basetex.ORIGINAL:
                parts.append(_("base texture"))
            if any(s.finish.values()):
                parts.append(_("board finish"))
            if self._pal_changed():
                parts.append(_("colors"))
            self.dc_changes.config(text=_("Unsaved: {changes}.", changes=", ".join(parts)) if dirty and parts else
                                   (_("Saved. The layers stay editable.") if s.layers else
                                    _("Drag stickers onto the board, or pick a base texture.")))
            self.dc_base_lbl.config(text=basetex.label_of(s.base_key))
            # the small base preview only changes with the base itself (not while dragging stickers)
            key = (id(s.base_img), s.base_key, s.tint, round(s.tint_strength, 3), str(self.dc_base_thumb))
            if getattr(self, "_dc_base_key", None) != key:
                try:
                    pv = s.base_img.convert("RGB").resize((64, 14), Image.LANCZOS)
                    self._dc_base_photo = ImageTk.PhotoImage(pv)
                    self.dc_base_thumb.config(image=self._dc_base_photo)
                    self._dc_base_key = key
                except Exception:
                    pass
        if getattr(self, "layout", "") == "shop":
            self._dc_shop_bar()
        mode = self.dc_mode.get()
        self.dc_hint.config(text=_("drag sticker · right-drag rotate · wheel scale · click a "
                                   "part to recolor")
                            if mode == "place" else _("drag rotate · wheel zoom · click a part to recolor"))

    # ------------------------------------------------------------------ saving
    def dc_save_dialog(self):
        """Open the save dialog and save the design as it chooses."""
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
            return messagebox.showerror(_("Save decorations"), _("Cannot read Board {name}: {e}", name=b.name, e=e))
        s.composer.invalidate()
        work = s.composer.compose(s.base_img, s.layers, None, self.pal, finish=s.finish_obj(self._dc_mask))
        if work.size != (tex.width, tex.height):
            work = work.resize((tex.width, tex.height), Image.LANCZOS)
        files = [(b.texture, tex)] + ([(b.thumb, th)] if th is not None else [])
        missing = [p for p, _t in files if not load_default_meta(p)]
        if missing and messagebox.askyesno(
                _("Save defaults first?"),
                _("No default is saved for {v} yet.\n\nSave the current images as defaults "
                  "before writing, so you can revert later?", v=', '.join(p.name for p in missing))):
            try:
                for p, t in files:
                    if p in missing:
                        meta = set_default(p, t)
                        self.cache.put(p, meta["pixel_sha256"])
            except Exception as e:
                return messagebox.showerror(_("Cannot set default"), str(e))
        self.busy(True)
        try:
            save_texture(b.texture, work, tex)
            TEXCACHE.remember_saved(b.texture, tex, work)
            if th is not None:
                small = work.resize((th.width, th.height), Image.LANCZOS)
                save_texture(b.thumb, small, th)
                TEXCACHE.remember_saved(b.thumb, th, small)
            if keep and work.size == s.size:
                save_project(b.texture, s.base_img, s.base_key, s.tint, s.tint_strength, s.layers, work,
                             finish=s.finish)
            else:
                drop_project(b.texture)
        except Exception as e:
            return messagebox.showerror(_("Save failed"), str(e))
        finally:
            self.busy(False)
        what = _("Board {name} and its thumbnail", name=b.name) if th is not None else _("Board {name}", name=b.name)
        if same:
            if keep:
                s.saved_sig = s.sig()
                s.original_saved = True
                s.saved_state = self._dc_state() if s is self.dc else None
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
        self.set_status(_("Saved the decoration to {what}", what=what)
                        + (_(" · layers stay editable") if keep else "")
                        + (_(" (Board {name} is unchanged)", name=self.boards[self.sel].name) if not same and self.sel is not None else ""))
        self._dc_refresh_controls()


class TextDialog(tk.Toplevel):
    """Text layer settings: text, font, colour, outline. TextDialog.ask() returns the settings or None."""

    @classmethod
    def ask(cls, master, g: dict, title: str):
        """Show the text dialog for settings `g` and return the new settings, or None when cancelled. Scans the
        system fonts first (only slow the first time).
        """
        base.root.config(cursor="watch")
        base.root.update_idletasks()
        try:
            names = TS.font_names()                  # scans the fonts the first time
        finally:
            base.root.config(cursor="")
        dlg = cls(master, dict(g), title, names)
        master.wait_window(dlg)
        return dlg.result

    def __init__(self, master, g, title, names):
        """Build the dialog: text box, font list, colour and outline controls and a live preview."""
        super().__init__(master, bg=C["panel"])
        self.withdraw()
        self.g, self.result, self._job = g, None, None
        self.title(title)
        self.transient(master)
        self.resizable(False, False)
        body = tk.Frame(self, bg=C["panel"])
        body.pack(fill="both", expand=True, padx=18, pady=14)
        label(body, _("Text"), "smallbold").pack(anchor="w")
        self.txt = tk.Text(body, width=34, height=3, bg=C["bg"], fg=C["text"], insertbackground=C["text"],
                           relief="flat", highlightthickness=1, highlightbackground=C["border"], font=F["body"])
        self.txt.pack(fill="x", pady=(2, 10))
        self.txt.insert("1.0", g.get("text", ""))
        self.txt.bind("<<Modified>>", self._modified)
        row = tk.Frame(body, bg=C["panel"])
        row.pack(fill="x")
        label(row, _("Font"), "smallbold").pack(side="left")
        self.font = tk.StringVar(value=g.get("font") if g.get("font") in names else TS.default_font())
        cb = ttk.Combobox(row, textvariable=self.font, values=names, state="readonly", width=30)
        cb.pack(side="left", padx=8)
        cb.bind("<<ComboboxSelected>>", lambda e: self._changed())
        row = tk.Frame(body, bg=C["panel"])
        row.pack(fill="x", pady=(10, 0))
        self.sw = {}
        for key, text in (("color", N_("Colour")), ("outline", N_("Outline"))):
            label(row, _(text), "smallbold").pack(side="left")
            sw = tk.Canvas(row, width=28, height=18, highlightthickness=1, highlightbackground=C["btnb"], cursor="hand2",
                           bg=to_hex(tuple(g.get(key, (255, 255, 255))[:3])))
            sw.pack(side="left", padx=(6, 14))
            sw.bind("<Button-1>", lambda e, k=key: self._pick(k))
            self.sw[key] = sw
        label(row, _("Outline width"), "small", "sub").pack(side="left")
        self.ow = tk.DoubleVar(value=float(g.get("outline_w", 0.06)) * 100)
        Slider(row, from_=0, to=15, variable=self.ow, command=lambda v: self._changed()).pack(
            side="left", fill="x", expand=True, padx=6)
        self.prev = tk.Label(body, bg=C["bg"], height=7, width=50)
        self.prev.pack(fill="x", pady=(12, 0))
        label(body, _("Tip: add a White border or Shadow in the Effects tab, like a real sticker."), "small", "muted",
              justify="left", anchor="w").pack(fill="x", pady=(8, 0))
        foot = tk.Frame(self, bg=C["side"])
        foot.pack(fill="x")
        button(foot, _("OK"), self._ok, "primary").pack(side="right", padx=(8, 16), pady=12)
        button(foot, _("Cancel"), self.destroy).pack(side="right", pady=12)
        self.bind("<Escape>", lambda e: self.destroy())
        self._render()
        self.update_idletasks()
        x = master.winfo_rootx() + (master.winfo_width() - self.winfo_reqwidth()) // 2
        y = master.winfo_rooty() + (master.winfo_height() - self.winfo_reqheight()) // 3
        self.geometry(f"+{max(0, x)}+{max(0, y)}")
        self.deiconify()
        self.grab_set()
        self.txt.focus_set()

    def _modified(self, _e=None):
        """Text box change callback."""
        self.txt.edit_modified(False)
        self._changed()

    def _pick(self, key):
        """Pick the text colour (`key`='color') or the outline colour."""
        rgb, _hx = colorchooser.askcolor(color=to_hex(tuple(self.g.get(key, (255, 255, 255))[:3])), parent=self,
                                         title=_("Text colour") if key == "color" else _("Outline colour"))
        if rgb:
            self.g[key] = [int(round(v)) for v in rgb[:3]]
            self.sw[key].config(bg=to_hex(tuple(self.g[key])))
            self._changed()

    def _settings(self):
        """Text settings read from the controls (text limited to 200 characters)."""
        g = dict(self.g)
        g["text"] = self.txt.get("1.0", "end-1c").strip("\n")[:200]
        g["font"] = self.font.get()
        g["outline_w"] = round(float(self.ow.get()) / 100.0, 3)
        return g

    def _changed(self):
        """Redraw the preview 120 ms after the last change."""
        if self._job is not None:
            self.after_cancel(self._job)
        self._job = self.after(120, self._render)

    def _render(self):
        """Draw the preview of the current settings."""
        self._job = None
        g = self._settings()
        if not g["text"].strip():
            self.prev.config(image="", text=_("(type some text)"), fg=C["muted"])
            return
        im = TS.render_text(g)
        im.thumbnail((380, 100), Image.LANCZOS)
        bg = Image.new("RGBA", im.size, _rgb(C["bg"])[:3] + (255,))
        bg.alpha_composite(im)
        self._ph = ImageTk.PhotoImage(bg)
        self.prev.config(image=self._ph, text="", height=110)

    def _ok(self):
        """Accept the settings (needs some text)."""
        g = self._settings()
        if not g["text"].strip():
            return
        self.result = g
        self.destroy()


class SaveDecorDialog(tk.Toplevel):
    """Override the selected board, or save the design into another board."""

    def __init__(self, master, app):
        """Build the save dialog: override this board or save to another board, plus 'also make the thumbnail' and
        'keep the editable project' options.
        """
        super().__init__(master, bg=C["panel"])
        self.app, self.result = app, None
        self.title(_("Save decorations"))
        self.transient(master)
        self.resizable(False, False)
        s = app.dc
        cur = app.boards[app.sel]
        self.boards = app.boards
        body = tk.Frame(self, bg=C["panel"])
        body.pack(fill="both", expand=True, padx=20, pady=16)
        top = tk.Frame(body, bg=C["panel"])
        top.pack(fill="x")
        prev = s.composer.compose(s.base_img, s.layers, None, app.pal,
                                  finish=s.finish_obj(app._dc_mask)).convert("RGB").resize((240, 54), Image.LANCZOS)
        self._ph = ImageTk.PhotoImage(prev)
        tk.Label(top, image=self._ph, bg=C["panel"], bd=1, relief="solid").pack(side="left")
        info = tk.Frame(top, bg=C["panel"])
        info.pack(side="left", padx=12)
        label(info, _("Board {name}", name=cur.name) + " · " + _n("{n} layer", "{n} layers", len(s.layers)),
              "bold").pack(anchor="w")
        bits = [_("base: {name}", name=basetex.label_of(s.base_key))] + ([_("colors changed")] if app._pal_changed() else [])
        label(info, " · ".join(bits), "small", "muted").pack(anchor="w")

        self.mode = tk.StringVar(value="override")
        others = [b.name for i, b in enumerate(app.boards) if i != app.sel]
        self.opt1 = self._option(body, "override", _("Override selected board"),
                                 _("Replaces Board {name} ({file}). The default snapshot stays, so Revert still "
                                   "brings the original back.", name=cur.name, file=cur.texture.name))
        self.opt2 = self._option(body, "other", _("Save to another board"),
                                 _("Keeps Board {name} as it is and writes the design into the board you pick. "
                                   "The game has a fixed set of boards, so the design replaces that one.",
                                   name=cur.name))
        row = tk.Frame(self.opt2, bg=self.opt2.cget("bg"))
        row.pack(fill="x", padx=(34, 12), pady=(0, 10))
        label(row, _("Board"), "small", "muted", bg=self.opt2.cget("bg")).pack(side="left")
        self.target = tk.StringVar(value=others[(min(app.sel, len(others) - 1)) if others else 0] if others else "")
        self.combo = ttk.Combobox(row, textvariable=self.target, values=others, state="readonly", width=10)
        self.combo.pack(side="left", padx=8)
        self.combo.bind("<<ComboboxSelected>>", lambda e: (self.mode.set("other"), self._update()))
        self.thumb = tk.BooleanVar(value=SETTINGS.get("dc_thumb", True))
        self.keep = tk.BooleanVar(value=SETTINGS.get("dc_keep", True))
        for text, var in ((N_("Also update the thumbnail"), self.thumb), (N_("Keep layers editable after saving"), self.keep)):
            tk.Checkbutton(body, text=_(text), variable=var, bg=C["panel"], fg=C["sub"], activebackground=C["panel"],
                           activeforeground=C["text"], selectcolor=C["bg"], font=F["small"], bd=0,
                           highlightthickness=0, cursor="hand2", anchor="w").pack(fill="x", pady=(8, 0))
        foot = tk.Frame(self, bg=C["side"])
        foot.pack(fill="x")
        self.ok = button(foot, _("Save"), self._ok, "primary")
        self.ok.pack(side="right", padx=(8, 16), pady=12)
        button(foot, _("Cancel"), self.destroy).pack(side="right", pady=12)
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
        """Add one clickable radio option card with a title and a description."""
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
        """Highlight the chosen option and set the Save button text."""
        for fr, val in ((self.opt1, "override"), (self.opt2, "other")):
            on = self.mode.get() == val
            fr.config(highlightbackground=C["accent"] if on else C["border"])
        cur = self.app.boards[self.app.sel].name
        self.ok.config(text=_("Override Board {cur}", cur=cur) if self.mode.get() == "override"
                       else _("Save to Board {v}", v=self.target.get()))

    def _ok(self):
        """Store the choice in `result` (target board index, thumbnail, keep project) and close; saving to another
        board asks for confirmation.
        """
        if self.mode.get() == "override":
            target = self.app.sel
        else:
            names = [b.name for b in self.boards]
            if self.target.get() not in names:
                return
            target = names.index(self.target.get())
            if not messagebox.askyesno(_("Save to another board"),
                                       _("Replace Board {v} with this design?", v=self.target.get()), parent=self):
                return
        SETTINGS["dc_thumb"], SETTINGS["dc_keep"] = self.thumb.get(), self.keep.get()
        try:
            save_settings(SETTINGS)
        except Exception:
            pass
        self.result = (target, self.thumb.get(), self.keep.get())
        self.destroy()
