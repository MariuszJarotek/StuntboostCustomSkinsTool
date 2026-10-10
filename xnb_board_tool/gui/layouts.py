"""Window layouts (Studio / Gallery / Classic), the cards they are built from, the gallery and rebuilding the window for new settings."""
from __future__ import annotations

from tkinter import ttk
import tkinter as tk
import tkinter.font as tkfont
from PIL import Image, ImageTk

from ..boards import PALETTE_SLOTS, to_hex
from ..settings import C, GALLERY_COLS, LAYOUTS, SETTINGS, _rgb, save_settings, set_theme, titlebar
from .base import F, Preview, Scroll, _scrolls, button, card, hline, label, more_button
from . import base
from .dialogs import SettingsDialog


class LayoutsMixin:
    """Window layouts (Studio / Gallery / Classic), the cards they are built from, the gallery and rebuilding the window for new settings. Mixed into App."""

    # ---------- layout ----------
    def _build(self):
        del _scrolls[:]
        self.gal_cards = {}
        # header
        hdr = tk.Frame(base.root, bg=C["panel"])
        hdr.pack(fill="x")
        hline(base.root).pack(fill="x")
        row = tk.Frame(hdr, bg=C["panel"])
        row.pack(fill="x", padx=16, pady=10)
        logo = tk.Canvas(row, width=28, height=28, bg=C["panel"], highlightthickness=0)
        logo.create_rectangle(0, 0, 28, 28, fill=C["accent"], outline=C["accent"])
        logo.create_rectangle(6, 9, 22, 17, outline=C["onaccent"], width=2)
        logo.create_oval(8, 19, 12, 23, fill=C["onaccent"], outline="")
        logo.create_oval(16, 19, 20, 23, fill=C["onaccent"], outline="")
        logo.pack(side="left")
        label(row, "Board Texture Tool", "title").pack(side="left", padx=(10, 16))
        tabs = tk.Frame(row, bg=C["bg"], highlightthickness=1, highlightbackground=C["border"])
        tabs.pack(side="left", padx=(0, 16))
        self.tab_var = tk.StringVar(value=self._keep.get("tab", "boards"))
        for text, val in (("Boards", "boards"), ("Decorate", "decor"), ("Speedmeter", "speed")):
            tk.Radiobutton(tabs, text=text, value=val, variable=self.tab_var,
                           command=self.switch_tab, indicatoron=False, bg=C["bg"],
                           fg=C["text"], selectcolor=C["selfill"], activebackground=C["btnh"],
                           activeforeground=C["text"], relief="flat", bd=0, highlightthickness=0,
                           padx=16, pady=6, font=F["bold"], cursor="hand2").pack(side="left", padx=2, pady=2)
        button(row, "⚙  Settings", self.open_settings).pack(side="right", padx=(8, 0))
        self.btn_saveall = button(row, "Save all as defaults", self.save_all_defaults)
        self.btn_saveall.pack(side="right", padx=(12, 0))
        box = tk.Frame(row, bg=C["bg"], highlightthickness=1, highlightbackground=C["border"])
        box.pack(side="left", fill="x", expand=True)
        ic = tk.Canvas(box, width=16, height=14, bg=C["bg"], highlightthickness=0)
        ic.create_polygon(1, 2, 6, 2, 8, 4, 15, 4, 15, 13, 1, 13, outline=C["muted"],
                          fill="", width=1.5)
        ic.pack(side="left", padx=(10, 0))
        self.path_kind = label(box, "", "small", "muted", bg=C["bg"])
        self.path_kind.pack(side="left", padx=(6, 0))
        button(box, "Change…", self.change_folder).pack(side="right", padx=4, pady=4)
        self.path_lbl = label(box, self.path_full, "mono", "sub", anchor="w", width=1)
        self.path_lbl.pack(side="left", fill="x", expand=True, padx=8)
        self.path_lbl.bind("<Configure>", self._fit_path)

        # footer (packed before the body so it stays visible)
        foot = tk.Frame(base.root, bg=C["panel"])
        foot.pack(side="bottom", fill="x")
        hline(base.root).pack(side="bottom", fill="x")
        self.status_var = tk.StringVar(value=self._keep.get("status", "Open a content folder to begin."))
        tk.Label(foot, textvariable=self.status_var, font=F["small"], fg=C["muted"],
                 bg=C["panel"], anchor="w").pack(side="left", padx=16, pady=6)
        self.summary_lbl = label(foot, "", "small", "muted")
        self.summary_lbl.pack(side="right", padx=16)

        body = tk.Frame(base.root, bg=C["bg"])
        body.pack(fill="both", expand=True)
        # speedmeter view: file list + scrolling main area
        self.speed_view = tk.Frame(body, bg=C["bg"])
        side = tk.Frame(self.speed_view, bg=C["side"], width=290)
        side.pack(side="left", fill="y")
        side.pack_propagate(False)
        self._build_speed_sidebar(side)
        tk.Frame(self.speed_view, bg=C["border"], width=1).pack(side="left", fill="y")
        sc = Scroll(self.speed_view)
        sc.pack(side="left", fill="both", expand=True)
        self.speed_main = sc.inner
        self._build_speed_main(sc.inner)
        # boards view: arranged by the chosen layout
        self.board_view = tk.Frame(body, bg=C["bg"])
        self.layout = SETTINGS.get("layout", "studio")
        {"classic": self._layout_classic, "gallery": self._layout_gallery}.get(
            self.layout, self._layout_studio)(self.board_view)
        # decorate view (built after the boards view: it shares the 3D toggles)
        self.decor_view = tk.Frame(body, bg=C["bg"])
        self._build_decorate(self.decor_view)
        self.switch_tab()

    # -- shared pieces --
    def _vline(self, parent, side="left"):
        tk.Frame(parent, bg=C["border"], width=1).pack(side=side, fill="y")

    def _build_filter(self, parent, bg):
        sbox = tk.Frame(parent, bg=C["bg"], highlightthickness=1, highlightbackground=C["border"])
        ic = tk.Canvas(sbox, width=14, height=14, bg=C["bg"], highlightthickness=0)
        ic.create_oval(1, 1, 10, 10, outline=C["muted"], width=1.6)
        ic.create_line(9, 9, 13, 13, fill=C["muted"], width=1.6)
        ic.pack(side="left", padx=(10, 0))
        self.filter_var = tk.StringVar()
        self.filter = tk.Entry(sbox, textvariable=self.filter_var, bg=C["bg"], fg=C["text"],
                               insertbackground=C["text"], relief="flat", bd=0,
                               font=F["body"], highlightthickness=0)
        self.filter.pack(side="left", fill="x", expand=True, padx=8, ipady=7)
        kept = self._keep.get("filter", "")
        self._placeholder = not kept
        if kept:
            self.filter.insert(0, kept)
        else:
            self.filter.insert(0, "Filter boards…")
            self.filter.config(fg=C["muted"])
        self.filter.bind("<FocusIn>", self._filter_focus_in)
        self.filter.bind("<FocusOut>", self._filter_focus_out)
        self.filter.bind("<Return>", self._filter_enter)
        self.filter.bind("<Escape>", lambda e: self.filter_var.set(""))
        self.filter_var.trace_add("write", lambda *a: self._fill_list())
        return sbox

    def _build_legend(self, parent, bg):
        leg = tk.Frame(parent, bg=bg)
        for kind, text in (("def", "Default"), ("mod", "Modified"), ("none", "No default")):
            c = tk.Canvas(leg, width=10, height=10, bg=bg, highlightthickness=0)
            if kind == "def":
                c.create_oval(1, 1, 9, 9, fill=C["green"], outline="")
            elif kind == "mod":
                c.create_rectangle(1, 1, 9, 9, fill=C["accent"], outline="")
            else:
                c.create_oval(1, 1, 9, 9, outline=C["muted"], width=1.5)
            c.pack(side="left")
            label(leg, text, "small", "muted").pack(side="left", padx=(4, 12))
        return leg

    def _build_board_list(self, parent, width=290):
        side = tk.Frame(parent, bg=C["side"], width=width)
        side.pack(side="left", fill="y")
        side.pack_propagate(False)
        top = tk.Frame(side, bg=C["side"])
        top.pack(fill="x", padx=14, pady=(14, 8))
        r = tk.Frame(top, bg=C["side"])
        r.pack(fill="x")
        label(r, "Boards", "bold").pack(side="left")
        self.count_lbl = label(r, "", "small", "muted")
        self.count_lbl.pack(side="right")
        self._build_filter(top, C["side"]).pack(fill="x", pady=(10, 8))
        self._build_legend(top, C["side"]).pack(fill="x")
        lst = tk.Frame(side, bg=C["side"])
        lst.pack(fill="both", expand=True, padx=(8, 0), pady=(0, 10))
        self.tree = ttk.Treeview(lst, show="tree", style="Boards.Treeview", selectmode="browse")
        self.tree.column("#0", stretch=True)
        sb = ttk.Scrollbar(lst, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.tree.pack(side="left", fill="both", expand=True)
        self.tree.bind("<<TreeviewSelect>>", self._on_tree_select)
        self._vline(parent)

    def _card_title(self, parent, size="h1"):
        tr = tk.Frame(parent, bg=parent.cget("bg"))
        self.title_lbl = label(tr, "No board selected", size)
        self.title_lbl.pack(side="left")
        self.badge = tk.Label(tr, font=F["smallbold"], padx=10, pady=3)
        self.badge.pack(side="left", padx=14)
        self.btn_next = button(tr, "›", lambda: self.step(1), width=2)
        self.btn_next.pack(side="right")
        self.btn_prev = button(tr, "‹", lambda: self.step(-1), width=2)
        self.btn_prev.pack(side="right", padx=6)
        return tr

    def _card_texture(self, parent, compact=False):
        tc = card(parent)
        head = tk.Frame(tc, bg=C["panel"])
        head.pack(fill="x", padx=16, pady=(10, 0))
        label(head, "Board texture", "h2").pack(side="left")
        self.tex_file = label(head, "", "mono", "muted")
        self.tex_file.pack(side="left", padx=10)
        self.tex_chips = tk.Frame(tc, bg=C["panel"])
        self.tex_chips.pack(fill="x", padx=10, pady=(6, 10))
        hline(tc).pack(fill="x")
        self.tex_prev = Preview(tc, 432 / 1920, 460, on_drop=lambda f: self.replace("tex", f))
        self.tex_prev.pack(fill="x", padx=16, pady=16)
        act = tk.Frame(tc, bg=C["panel"])
        act.pack(fill="x", padx=16)
        self.b_tex_replace = button(act, "↑  Replace…" if compact else "↑  Replace image…",
                                    lambda: self.replace("tex"), "primary")
        self.b_tex_replace.pack(side="left")
        self.b_tex_export = button(act, "Export" if compact else "Export PNG…", lambda: self.export("tex"))
        self.b_tex_export.pack(side="left", padx=(8, 0))
        self.b_tex_revert = button(act, "Revert" if compact else "Revert to default", lambda: self.revert("tex"))
        self.b_tex_revert.pack(side="left", padx=(8, 0))
        act2 = tk.Frame(tc, bg=C["panel"])
        act2.pack(fill="x", padx=16, pady=(6, 14))
        self.b_tex_setdef = button(act2, "Set as default" if compact else "Set current as default",
                                   lambda: self.set_default("tex"), "ghost")
        self.b_tex_setdef.pack(side="left")
        button(act2, "Open other…" if compact else "Open other .xnb…", self.open_other,
               "ghost").pack(side="left")
        return tc

    def _card_colors(self, parent, cols=4):
        pc = card(parent)
        head = tk.Frame(pc, bg=C["panel"])
        head.pack(fill="x", padx=16, pady=10)
        label(head, "Board colors", "h2").pack(side="left")
        if cols >= 4:
            label(head, "first 4 pixels of the texture's top row", "small", "muted").pack(
                side="left", padx=10)
        self.pal_state = label(head, "", "small", "muted")
        self.pal_state.pack(side="right")
        hline(pc).pack(fill="x")
        slots = tk.Frame(pc, bg=C["panel"])
        slots.pack(fill="x", padx=16, pady=(14, 4))
        self.pal_widgets = []
        for i, (_key, name) in enumerate(PALETTE_SLOTS):
            slots.columnconfigure(i % cols, weight=1, uniform="p")
            cell = tk.Frame(slots, bg=C["panel"])
            cell.grid(row=i // cols, column=i % cols, sticky="w", pady=(0, 10 if cols < 4 else 0))
            sw = tk.Canvas(cell, width=60 if cols != 2 else 46, height=44, bg=C["btn"],
                           highlightthickness=1, highlightbackground=C["btnb"], cursor="hand2")
            sw.grid(row=0, column=0, rowspan=3, padx=(0, 10))
            sw.bind("<Button-1>", lambda e, i=i: self.pick_color(i))
            label(cell, name if cols != 1 else f"{name}  ·  pixel {i}, 0", "bold").grid(
                row=0, column=1, sticky="w")
            var = tk.StringVar()
            ent = tk.Entry(cell, textvariable=var, width=9, bg=C["bg"], fg=C["text"],
                           insertbackground=C["text"], relief="flat", bd=0, font=F["mono"],
                           highlightthickness=1, highlightbackground=C["border"],
                           highlightcolor=C["accent"], disabledbackground=C["panel"])
            ent.grid(row=1, column=1, sticky="w", ipady=3, pady=(2, 0))
            ent.bind("<Return>", lambda e, i=i: self.commit_color(i))
            ent.bind("<FocusOut>", lambda e, i=i: self.commit_color(i))
            was = label(cell, "", "small", "muted")
            was.grid(row=2, column=1, sticky="w")
            self.pal_widgets.append((sw, var, ent, was))
        pact = tk.Frame(pc, bg=C["panel"])
        pact.pack(fill="x", padx=16, pady=(8, 8 if cols < 4 else 16))
        self.b_pal_apply = button(pact, "Apply colors" if cols < 4 else "Apply colors to texture",
                                  self.apply_colors, "primary")
        self.b_pal_apply.pack(side="left")
        self.b_pal_reset = button(pact, "Reset", self.reset_colors)
        self.b_pal_reset.pack(side="left", padx=(8, 0))
        self.b_pal_copy = button(pact, "Copy", self.copy_colors, "ghost")
        self.b_pal_copy.pack(side="left", padx=(8, 0))
        self.b_pal_paste = button(pact, "Paste", self.paste_colors, "ghost")
        self.b_pal_paste.pack(side="left")
        self.keep_pal = tk.BooleanVar(value=self._keep.get("keep_pal", True))
        cb = tk.Checkbutton(pact if cols >= 4 else pc,
                            text="Keep these colors when replacing the texture image",
                            variable=self.keep_pal, bg=C["panel"], fg=C["sub"],
                            activebackground=C["panel"], activeforeground=C["text"],
                            selectcolor=C["bg"], font=F["small"], bd=0, highlightthickness=0,
                            cursor="hand2", anchor="w", justify="left")
        if cols >= 4:
            cb.pack(side="right")
        else:
            cb.pack(fill="x", padx=16, pady=(0, 14))
        return pc

    def _card_v3(self, parent, height=200):
        vc = card(parent)
        head = tk.Frame(vc, bg=C["panel"])
        head.pack(fill="x", padx=16, pady=10)
        label(head, "3D preview", "h2").pack(side="left")
        button(head, "Decorate\u2026", self.open_decorate, "primary", small=True).pack(side="right", padx=(12, 0))
        self.v3_screws = tk.BooleanVar(value=self._keep.get("screws", True))
        self.v3_outline = tk.BooleanVar(value=self._keep.get("outline", True))
        for text, var in (("Outline", self.v3_outline), ("Screws", self.v3_screws)):
            tk.Checkbutton(head, text=text, variable=var, command=self.v3_schedule,
                           bg=C["panel"], fg=C["sub"], activebackground=C["panel"],
                           activeforeground=C["text"], selectcolor=C["bg"], font=F["small"],
                           bd=0, highlightthickness=0, cursor="hand2").pack(side="right", padx=(8, 0))
        hline(vc).pack(fill="x")
        vbar = tk.Frame(vc, bg=C["panel"])
        vbar.pack(side="bottom", fill="x", padx=16, pady=(0, 12))
        for text, yaw, pitch in (("3/4", 120, 28), ("Top", 120, 30), ("Bottom", 120, -30), ("Side", 90, 0)):
            tk.Button(vbar, text=text, command=lambda y=yaw, p=pitch: self.v3_view(y, p),
                      bg=C["btn"], fg=C["text"], activebackground=C["btnh"],
                      activeforeground=C["text"], relief="flat", bd=0, highlightthickness=1,
                      highlightbackground=C["btnb"], padx=10, pady=3, font=F["small"],
                      cursor="hand2").pack(side="left", padx=(0, 4))
        label(vbar, "drag · scroll · double-click · click a part to recolor", "small", "muted").pack(side="right")
        self.v3_note = label(vc, "", "small", "muted", anchor="w", justify="left")
        self.v3_note.pack(side="bottom", fill="x", padx=16, pady=(0, 8))
        self.v3_note.bind("<Configure>", lambda e: self.v3_note.config(wraplength=max(150, e.width - 4)))
        self.v3_canvas = tk.Canvas(vc, height=height, bg=C["bg"], highlightthickness=0, cursor="fleur")
        self.v3_canvas.pack(fill="both", expand=True, padx=16, pady=(14, 8))
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
        return vc

    def _card_thumb(self, parent, compact=False):
        th = card(parent)
        head = tk.Frame(th, bg=C["panel"])
        head.pack(fill="x", padx=16, pady=(10, 0) if compact else 10)
        label(head, "Thumbnail", "h2").pack(side="left")
        self.thumb_file = label(head, "", "mono", "muted")
        self.thumb_file.pack(side="left", padx=10)
        self.thumb_chips = tk.Frame(th if compact else head, bg=C["panel"])
        if compact:
            self.thumb_chips.pack(fill="x", padx=10, pady=(6, 10))
        else:
            self.thumb_chips.pack(side="right")
        hline(th).pack(fill="x")
        self.thumb_prev = Preview(th, 144 / 640, 260, on_drop=lambda f: self.replace("thumb", f))
        self.thumb_prev.pack(fill="x", padx=16, pady=(16, 12))
        a1 = tk.Frame(th, bg=C["panel"])
        a1.pack(fill="x", padx=16)
        self.b_th_gen = button(a1, "Generate from texture", self.generate_thumb)
        self.b_th_replace = button(a1, "Replace…", lambda: self.replace("thumb"))
        if compact:
            self.b_th_gen.pack(side="left")
            self.b_th_replace.pack(side="left", padx=(8, 0))
            a1b = tk.Frame(th, bg=C["panel"])
            a1b.pack(fill="x", padx=16, pady=(8, 0))
            parent2 = a1b
        else:
            self.b_th_replace.pack(side="left")
            self.b_th_gen.pack(side="left", padx=(8, 0))
            parent2 = a1
        self.b_th_export = button(parent2, "Export" if compact else "Export PNG…",
                                  lambda: self.export("thumb"))
        self.b_th_export.pack(side="left", padx=(0 if compact else 8, 0))
        a2 = tk.Frame(th, bg=C["panel"])
        a2.pack(fill="x", padx=16, pady=(8, 16))
        self.b_th_revert = button(a2, "Revert" if compact else "Revert to default",
                                  lambda: self.revert("thumb"))
        self.b_th_revert.pack(side="left")
        self.b_th_setdef = button(a2, "Set as default" if compact else "Set current as default",
                                  lambda: self.set_default("thumb"), "ghost")
        self.b_th_setdef.pack(side="left", padx=(8, 0))
        return th

    def _card_board(self, parent):
        """Gallery drawer: Texture / Thumbnail tabs sharing one preview area, then the 4 colors in one row."""
        bc = card(parent)
        top = tk.Frame(bc, bg=C["panel"])
        top.pack(fill="x", padx=12, pady=(10, 0))
        self.board_tab = tk.StringVar(value=self._keep.get("board_tab", "tex"))
        seg = tk.Frame(top, bg=C["bg"], highlightthickness=1, highlightbackground=C["border"])
        seg.pack(side="left")
        for text, val in (("Texture", "tex"), ("Thumbnail", "thumb")):
            tk.Radiobutton(seg, text=text, value=val, variable=self.board_tab, command=self._board_tab_show,
                           indicatoron=False, bg=C["bg"], fg=C["text"], selectcolor=C["selfill"],
                           activebackground=C["btnh"], activeforeground=C["text"], relief="flat", bd=0,
                           highlightthickness=0, padx=12, pady=3, font=F["smallbold"],
                           cursor="hand2").pack(side="left", padx=1, pady=1)
        self.tex_file = label(top, "", "mono", "muted")
        self.thumb_file = label(top, "", "mono", "muted")
        holder = tk.Frame(bc, bg=C["panel"])
        holder.pack(fill="x")
        self._bt_pages = {}

        # texture page
        pg = tk.Frame(holder, bg=C["panel"])
        self.tex_chips = tk.Frame(pg, bg=C["panel"])
        self.tex_chips._compact = True
        self.tex_chips.pack(fill="x", padx=12, pady=(6, 6))
        self.tex_prev = Preview(pg, 432 / 1920, 300, on_drop=lambda f: self.replace("tex", f))
        self.tex_prev.pack(fill="x", padx=12)
        act = tk.Frame(pg, bg=C["panel"])
        act.pack(fill="x", padx=12, pady=(8, 10))
        self.b_tex_replace = button(act, "\u2191 Replace\u2026", lambda: self.replace("tex"), "primary", small=True)
        self.b_tex_replace.pack(side="left")
        self.b_tex_export = button(act, "Export", lambda: self.export("tex"), small=True)
        self.b_tex_export.pack(side="left", padx=(6, 0))
        self.b_tex_revert = button(act, "Revert", lambda: self.revert("tex"), small=True)
        self.b_tex_revert.pack(side="left", padx=(6, 0))
        more, (self.b_tex_setdef, _o) = more_button(act, [
            ("Set current as default", lambda: self.set_default("tex")),
            ("Open other .xnb\u2026", self.open_other)])
        more.pack(side="right")
        self._bt_pages["tex"] = pg

        # thumbnail page
        pg2 = tk.Frame(holder, bg=C["panel"])
        self.thumb_chips = tk.Frame(pg2, bg=C["panel"])
        self.thumb_chips._compact = True
        self.thumb_chips.pack(fill="x", padx=12, pady=(6, 6))
        self.thumb_prev = Preview(pg2, 144 / 640, 300, on_drop=lambda f: self.replace("thumb", f))
        self.thumb_prev.pack(fill="x", padx=12)
        act2 = tk.Frame(pg2, bg=C["panel"])
        act2.pack(fill="x", padx=12, pady=(8, 10))
        self.b_th_gen = button(act2, "Generate from texture", self.generate_thumb, "primary", small=True)
        self.b_th_gen.pack(side="left")
        self.b_th_replace = button(act2, "Replace\u2026", lambda: self.replace("thumb"), small=True)
        self.b_th_replace.pack(side="left", padx=(6, 0))
        self.b_th_export = button(act2, "Export", lambda: self.export("thumb"), small=True)
        self.b_th_export.pack(side="left", padx=(6, 0))
        more2, (self.b_th_revert, self.b_th_setdef) = more_button(act2, [
            ("Revert to default", lambda: self.revert("thumb")),
            ("Set current as default", lambda: self.set_default("thumb"))])
        more2.pack(side="right")
        self._bt_pages["thumb"] = pg2

        # colors: one row of four
        hline(bc).pack(fill="x")
        ch = tk.Frame(bc, bg=C["panel"])
        ch.pack(fill="x", padx=12, pady=(8, 6))
        label(ch, "Board colors", "smallbold").pack(side="left")
        self.pal_state = label(ch, "", "small", "muted")
        self.pal_state.pack(side="right")
        slots = tk.Frame(bc, bg=C["panel"])
        slots.pack(fill="x", padx=12)
        self.pal_widgets = []
        for i, (_key, name) in enumerate(PALETTE_SLOTS):
            slots.columnconfigure(i, weight=1, uniform="p")
            cell = tk.Frame(slots, bg=C["panel"])
            cell.grid(row=0, column=i, sticky="w")
            sw = tk.Canvas(cell, width=26, height=26, bg=C["btn"], highlightthickness=1,
                           highlightbackground=C["btnb"], cursor="hand2")
            sw.grid(row=0, column=0, rowspan=2, padx=(0, 6))
            sw.bind("<Button-1>", lambda e, i=i: self.pick_color(i))
            label(cell, name, "small", "muted").grid(row=0, column=1, sticky="w")
            var = tk.StringVar()
            ent = tk.Entry(cell, textvariable=var, width=7, bg=C["bg"], fg=C["text"],
                           insertbackground=C["text"], relief="flat", bd=0, font=F["mono"],
                           highlightthickness=1, highlightbackground=C["border"],
                           highlightcolor=C["accent"], disabledbackground=C["panel"])
            ent.grid(row=1, column=1, sticky="w", ipady=1)
            ent.bind("<Return>", lambda e, i=i: self.commit_color(i))
            ent.bind("<FocusOut>", lambda e, i=i: self.commit_color(i))
            was = label(cell, "", "small", "muted")     # not shown: the swatch corner shows it
            self.pal_widgets.append((sw, var, ent, was))
        pact = tk.Frame(bc, bg=C["panel"])
        pact.pack(fill="x", padx=12, pady=(8, 12))
        self.b_pal_apply = button(pact, "Apply", self.apply_colors, "primary", small=True)
        self.b_pal_apply.pack(side="left")
        self.b_pal_reset = button(pact, "Reset", self.reset_colors, small=True)
        self.b_pal_reset.pack(side="left", padx=(6, 0))
        self.b_pal_copy = button(pact, "Copy", self.copy_colors, "ghost", small=True)
        self.b_pal_copy.pack(side="left", padx=(6, 0))
        self.b_pal_paste = button(pact, "Paste", self.paste_colors, "ghost", small=True)
        self.b_pal_paste.pack(side="left")
        self.keep_pal = tk.BooleanVar(value=self._keep.get("keep_pal", True))
        tk.Checkbutton(pact, text="Keep on replace", variable=self.keep_pal, bg=C["panel"], fg=C["sub"],
                       activebackground=C["panel"], activeforeground=C["text"], selectcolor=C["bg"],
                       font=F["small"], bd=0, highlightthickness=0, cursor="hand2").pack(side="right")
        self._board_tab_show()
        return bc

    def _board_tab_show(self):
        t = self.board_tab.get() if self.board_tab.get() in self._bt_pages else "tex"
        for pg in self._bt_pages.values():
            pg.pack_forget()
        self._bt_pages[t].pack(fill="x")
        self.tex_file.pack_forget()
        self.thumb_file.pack_forget()
        (self.tex_file if t == "tex" else self.thumb_file).pack(side="left", padx=10)

    def _card_defaults(self, parent):
        dc = card(parent)
        inner = tk.Frame(dc, bg=C["panel"])
        inner.pack(fill="both", expand=True, padx=16, pady=14)
        label(inner, "Default snapshot", "h2").pack(anchor="w")
        grid = tk.Frame(inner, bg=C["panel"])
        grid.pack(fill="x", pady=(12, 0))
        grid.columnconfigure(0, weight=1, uniform="d")
        grid.columnconfigure(1, weight=1, uniform="d")
        self.def_vals = {}
        for i, (key, cap) in enumerate((("saved", "Saved"), ("tex", "Texture stored as"),
                                        ("thumb", "Thumbnail stored as"),
                                        ("bak", "Backup (.bak)"))):
            cell = tk.Frame(grid, bg=C["panel"])
            cell.grid(row=i // 2, column=i % 2, sticky="w", pady=(0, 12))
            label(cell, cap, "small", "muted").pack(anchor="w")
            v = label(cell, "—", "mono" if key == "saved" else "body")
            v.pack(anchor="w")
            self.def_vals[key] = v
        note = tk.Label(inner, bg=C["bg"], fg=C["sub"], font=F["small"], justify="left",
                        anchor="w", padx=12, pady=10, wraplength=380,
                        text="Defaults live in _board_defaults next to the board files. "
                             "Revert restores the saved pixels exactly.")
        note.pack(fill="x", side="bottom")
        note.bind("<Configure>", lambda e: note.config(wraplength=max(120, e.width - 24)))
        hint = ("Tip: drag an image onto a preview to replace it." if base.TkinterDnD else
                "Tip: pip install tkinterdnd2 to drag images onto the previews.")
        hl = label(inner, hint, "small", "muted", anchor="w", justify="left")
        hl.pack(fill="x", side="bottom", pady=(0, 8))
        hl.bind("<Configure>", lambda e: hl.config(wraplength=max(120, e.width - 4)))
        return dc

    # -- layout: Classic (list | texture + 3D, colors, thumbnail + defaults) --
    def _layout_classic(self, view):
        self._build_board_list(view)
        sc = Scroll(view)
        sc.pack(side="left", fill="both", expand=True)
        m = tk.Frame(sc.inner, bg=C["bg"])
        m.pack(fill="both", expand=True, padx=28, pady=22)
        self._card_title(m).pack(fill="x")
        self.top_row = tk.Frame(m, bg=C["bg"])
        self.top_row.pack(fill="x", pady=(18, 0))
        self._top_mode = None
        self.tex_card = self._card_texture(self.top_row)
        self.v3_card = self._card_v3(self.top_row)
        self.top_row.bind("<Configure>", self._layout_top_row)
        self._card_colors(m, 4).pack(fill="x", pady=(20, 0))
        low = tk.Frame(m, bg=C["bg"])
        low.pack(fill="x", pady=(20, 0))
        low.columnconfigure(0, weight=1, uniform="c")
        low.columnconfigure(1, weight=1, uniform="c")
        self._card_thumb(low).grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        self._card_defaults(low).grid(row=0, column=1, sticky="nsew", padx=(10, 0))

    # -- layout: Studio (list | big 3D + texture | inspector) --
    def _layout_studio(self, view):
        self._build_board_list(view, width=260)
        insp = Scroll(view, width=390)
        insp.pack(side="right", fill="y")
        self._vline(view, "right")
        center = Scroll(view)
        center.pack(side="left", fill="both", expand=True)
        m = tk.Frame(center.inner, bg=C["bg"])
        m.pack(fill="both", expand=True, padx=24, pady=20)
        self._card_title(m).pack(fill="x")
        self._card_v3(m, height=400).pack(fill="x", pady=(16, 0))
        self._card_texture(m).pack(fill="x", pady=(20, 0))
        i = tk.Frame(insp.inner, bg=C["bg"])
        i.pack(fill="both", expand=True, padx=16, pady=20)
        self._card_colors(i, 1).pack(fill="x")
        self._card_thumb(i, compact=True).pack(fill="x", pady=(16, 0))
        self._card_defaults(i).pack(fill="x", pady=(16, 0))

    # -- layout: Gallery (board cards | editor drawer) --
    def _layout_gallery(self, view):
        # left: gallery | right: editor drawer, split by a draggable sash
        pw = self.gal_paned = tk.PanedWindow(view, orient="horizontal", bg=C["border"], sashwidth=6,
                                             sashrelief="flat", bd=0, opaqueresize=False,
                                             sashcursor="sb_h_double_arrow", showhandle=False)
        pw.pack(fill="both", expand=True)
        left = tk.Frame(pw, bg=C["bg"])
        drawer = self.gal_drawer = Scroll(pw)
        pw.add(left, minsize=420, stretch="always")
        pw.add(drawer, minsize=400, width=max(400, int(SETTINGS.get("drawer_w", 430))), stretch="never")
        pw.bind("<ButtonRelease-1>", self._gal_sash_released, add="+")
        m = tk.Frame(left, bg=C["bg"])
        m.pack(fill="x", padx=24, pady=(20, 0))
        bar = tk.Frame(m, bg=C["bg"])
        bar.pack(fill="x")
        label(bar, "Boards", "h1").pack(side="left")
        self.count_lbl = label(bar, "", "small", "muted")
        self.count_lbl.pack(side="left", padx=(12, 0), pady=(8, 0))
        self._build_filter(bar, C["bg"]).pack(side="right", ipadx=60)
        lrow = tk.Frame(m, bg=C["bg"])
        lrow.pack(fill="x", pady=(10, 8))
        self._build_legend(lrow, C["bg"]).pack(side="left")
        per = tk.Frame(lrow, bg=C["bg"], highlightthickness=1, highlightbackground=C["border"])
        per.pack(side="right")
        self.gal_cols_var = tk.StringVar(value=SETTINGS.get("gallery_cols", "auto"))
        for val in GALLERY_COLS:
            tk.Radiobutton(per, text="Auto" if val == "auto" else val, value=val,
                           variable=self.gal_cols_var, command=self._gal_set_cols,
                           indicatoron=False, bg=C["bg"], fg=C["text"], selectcolor=C["selfill"],
                           activebackground=C["btnh"], activeforeground=C["text"], relief="flat",
                           bd=0, highlightthickness=0, padx=10, pady=3, font=F["small"],
                           cursor="hand2").pack(side="left", padx=1, pady=1)
        label(lrow, "Per row", "small", "muted").pack(side="right", padx=(0, 8))
        # the cards are drawn on ONE canvas (no widget per card) so scrolling is smooth
        area = tk.Frame(left, bg=C["bg"])
        area.pack(fill="both", expand=True, padx=(12, 0), pady=(4, 0))
        c = self.gal_canvas = tk.Canvas(area, bg=C["bg"], highlightthickness=0, bd=0,
                                        yscrollincrement=24)
        sb = ttk.Scrollbar(area, orient="vertical", command=c.yview)
        def _yscroll(a, b, _sb=sb):
            _sb.set(a, b)
            self._gal_fill()                       # cards that scrolled into view get drawn now
        c.configure(yscrollcommand=_yscroll)
        sb.pack(side="right", fill="y")
        c.pack(side="left", fill="both", expand=True)
        c._own_wheel = True
        c.bind("<Configure>", lambda e: self._gal_schedule())
        c.bind("<Button-1>", self._gal_click)
        c.bind("<Motion>", self._gal_motion)
        c.bind("<MouseWheel>", lambda e: self._gal_wheel(-1 if e.delta > 0 else 1))
        c.bind("<Button-4>", lambda e: self._gal_wheel(-1))
        c.bind("<Button-5>", lambda e: self._gal_wheel(1))
        self._gal_geom, self._gal_key, self._gal_job = {}, None, None
        self._gal_drawn = set()
        self._gal_numfont = tkfont.Font(root=base.root, font=F["monolist"])
        # the list model (filtering / stepping) still lives in a tree that is never shown
        self.tree = ttk.Treeview(view, show="tree", style="Boards.Treeview", selectmode="browse")
        self.tree.bind("<<TreeviewSelect>>", self._on_tree_select)
        d = tk.Frame(drawer.inner, bg=C["bg"])
        d.pack(fill="both", expand=True, padx=16, pady=20)
        self._card_title(d, "h1").pack(fill="x")
        self._card_v3(d, height=230).pack(fill="x", pady=(14, 0))
        self._card_board(d).pack(fill="x", pady=(12, 0))
        self._card_defaults(d).pack(fill="x", pady=(12, 0))

    # -- gallery cards (canvas items) --
    GAL_W, GAL_H = 424, 96          # source size of card images (scaled to fit the cards)

    GAL_MIN = 212                   # card image width in Auto mode

    GAL_GAP, GAL_PAD, GAL_ROW = 12, 8, 24

    def _gal_sash_released(self, _e=None):
        try:
            w = int(self.gal_drawer.winfo_width())
        except Exception:
            return
        if w > 50 and w != int(SETTINGS.get("drawer_w", 0) or 0):
            SETTINGS["drawer_w"] = w
            save_settings(SETTINGS)

    def _gal_schedule(self):
        if getattr(self, "_gal_job", None):
            base.root.after_cancel(self._gal_job)
        self._gal_job = base.root.after(60, self._gal_layout)

    def _gal_photo(self, i):
        """Photo for card i. The source card image is read from the disk cache when needed and
        not kept afterwards; only images that are not on disk (yet) stay in memory."""
        g = self.gal_cards.setdefault(i, {})
        w = getattr(self, "_gal_img_w", self.GAL_MIN)
        h = max(8, round(w * self.GAL_H / self.GAL_W))
        pil = self.gal_pil.get(i)
        b = self.boards[i] if i < len(self.boards) else None
        src = (b.thumb or b.texture) if b is not None else None
        if pil is not None:
            ver = ("mem", id(pil))
        else:
            sig = self.cards.sig(src) if src else None
            ver = ("disk", tuple(sig or ()), self._gal_on_disk(i))
        key = (w, ver, C["btn"])
        if g.get("pkey") != key:
            if pil is None and src:
                pil = self.cards.card(b.name, self.cards.sig(src))
            if pil is None:
                img = Image.new("RGBA", (w, h), _rgb(C["btn"]))
            else:
                img = pil.resize((w, h), Image.LANCZOS if w < pil.width else Image.BILINEAR)
            g["photo"], g["pkey"] = ImageTk.PhotoImage(img), key
            if ver[0] == "mem" and self._gal_on_disk(i):
                # the disk cache has it: free the source, keep the key so the photo stays valid
                self.gal_pil.pop(i, None)
                g["pkey"] = (w, ("disk", tuple(self.cards.sig(src) or ()), True), C["btn"])
        return g["photo"], w, h

    def _gal_draw(self, i):
        c, geo = self.gal_canvas, self._gal_geom.get(i)
        if geo is None:
            return
        x0, y0, x1, y1 = geo
        t = f"card{i}"
        c.delete(t)
        self._gal_drawn.add(i)
        P = self.GAL_PAD
        photo, w, h = self._gal_photo(i)
        sel = (i == self.sel and not self.custom)
        c.create_rectangle(x0, y0, x1, y1, fill=C["panel"], width=2,
                           outline=C["accent"] if sel else C["border"], tags=(t,))
        c.create_image(x0 + P, y0 + P, image=photo, anchor="nw", tags=(t,))
        ty = y0 + P + h + self.GAL_ROW // 2 + 2
        name = self.boards[i].name
        c.create_text(x0 + P + 2, ty, text=name, anchor="w", font=F["monolist"], fill=C["text"], tags=(t,))
        st = self.status.get(i)
        short = w < 170
        tag = {"mod": "mod" if short else "modified", "none": "no def" if short else "no default"}.get(st, "")
        if tag:
            c.create_text(x0 + P + 10 + self._gal_numfont.measure(name), ty, text=tag, anchor="w",
                          font=F["small"], fill=C["warn"] if st == "mod" else C["muted"], tags=(t,))
        pal = self.board_pal.get(i)
        for k in range(4):
            dx = x1 - P - (4 - k) * 15 + 3
            c.create_rectangle(dx, ty - 6, dx + 11, ty + 5, outline=C["btnb"],
                               fill=to_hex(pal[k]) if pal else C["btn"], tags=(t,))

    def _gal_update(self, i):
        if self.layout == "gallery" and hasattr(self, "gal_canvas") and i is not None \
                and i in self._gal_drawn:
            self._gal_draw(i)                       # cards not drawn yet pick up the new state when they are

    def _gal_window(self, before, after):
        """Canvas y-range from `before` screens above the view to `after` screens below its top."""
        c = self.gal_canvas
        h = max(c.winfo_height(), 200)
        y = c.canvasy(0)
        return y - h * before, y + h * after

    def _gal_on_disk(self, i):
        """True when the disk cache holds card i for the current file, so it can be re-read."""
        if i >= len(self.boards):
            return False
        b = self.boards[i]
        src = b.thumb or b.texture
        e = self.cards.index.get(b.name) if src else None
        return bool(e) and e.get("src") is not None and e.get("src") == self.cards.sig(src)

    def _gal_fill(self):
        """Draws the cards in (or near) the visible part of the canvas that are not drawn yet, and
        frees the cards far away (their images are read back from the disk cache when needed)."""
        if self.layout != "gallery" or not hasattr(self, "gal_canvas") or not self._gal_geom:
            return
        top, bot = self._gal_window(0.6, 1.6)
        for i, (_x0, y0, _x1, y1) in self._gal_geom.items():
            if i not in self._gal_drawn and y1 >= top and y0 <= bot:
                self._gal_draw(i)
        ftop, fbot = self._gal_window(3, 4)
        c = self.gal_canvas
        for i in list(self._gal_drawn):
            geo = self._gal_geom.get(i)
            if geo is not None and (geo[3] < ftop or geo[1] > fbot):
                c.delete(f"card{i}")
                self._gal_drawn.discard(i)
                self.gal_cards.pop(i, None)            # its photo
                if self._gal_on_disk(i):
                    self.gal_pil.pop(i, None)
        for i in [k for k in self.gal_pil if k not in self._gal_drawn]:
            geo = self._gal_geom.get(i)
            if (geo is None or geo[3] < ftop or geo[1] > fbot) and self._gal_on_disk(i):
                self.gal_pil.pop(i, None)

    def _gal_layout(self, force=False):
        self._gal_job = None
        if self.layout != "gallery" or not hasattr(self, "gal_canvas"):
            return
        c = self.gal_canvas
        avail = max(100, c.winfo_width() - 24)
        G, P = self.GAL_GAP, self.GAL_PAD
        pref = SETTINGS.get("gallery_cols", "auto")
        if pref == "auto":
            cols = max(1, (avail + G) // (self.GAL_MIN + 2 * P + G))
        else:
            cols = max(1, int(pref))
        cw = max(80 + 2 * P, (avail - (cols - 1) * G) // cols)
        img_w = max(60, min(self.GAL_W * 2, cw - 2 * P))
        img_h = max(8, round(img_w * self.GAL_H / self.GAL_W))
        ch = img_h + 2 * P + self.GAL_ROW
        shown = [int(k) for k in self.tree.get_children()]
        key = (cols, img_w, avail, tuple(shown))
        if not force and key == self._gal_key:
            return
        self._gal_key = key
        self._gal_img_w = img_w
        self.gal_cols = cols
        c.delete("all")
        self._gal_geom, self._gal_drawn = {}, set()
        for n, i in enumerate(shown):
            r, k = divmod(n, cols)
            x0, y0 = 12 + k * (cw + G), 12 + r * (ch + G)
            self._gal_geom[i] = (x0, y0, x0 + cw, y0 + ch)
        rows = -(-len(shown) // cols)
        c.configure(scrollregion=(0, 0, avail + 12, 24 + rows * (ch + G)))
        self._gal_fill()

    def _gal_hit(self, e):
        x, y = self.gal_canvas.canvasx(e.x), self.gal_canvas.canvasy(e.y)
        for i, (x0, y0, x1, y1) in self._gal_geom.items():
            if x0 <= x <= x1 and y0 <= y <= y1:
                return i
        return None

    def _gal_click(self, e):
        i = self._gal_hit(e)
        if i is not None:
            self.select(i)

    def _gal_motion(self, e):
        self.gal_canvas.config(cursor="hand2" if self._gal_hit(e) is not None else "")

    def _gal_wheel(self, d):
        c = self.gal_canvas
        sr = c.cget("scrollregion").split()
        if sr and float(sr[3]) > c.winfo_height():
            c.yview_scroll(d * 3, "units")

    def _gal_set_cols(self):
        SETTINGS["gallery_cols"] = self.gal_cols_var.get()
        save_settings(SETTINGS)
        self._gal_layout(force=True)
        if self.sel is not None:
            base.root.after(30, lambda: self._gal_scroll_to(self.sel))

    def _gal_scroll_to(self, i):
        if self.layout != "gallery" or not hasattr(self, "gal_canvas") or i not in self._gal_geom:
            return
        c = self.gal_canvas
        _x0, y0, _x1, y1 = self._gal_geom[i]
        sr = c.cget("scrollregion").split()
        total = float(sr[3]) if sr else 1.0
        top = c.canvasy(0)
        if y0 < top or y1 > top + c.winfo_height():
            c.yview_moveto(max(0.0, (y0 - 12) / max(total, 1.0)))

    # -- settings & rebuilding --
    def open_settings(self):
        SettingsDialog(base.root, self)

    def apply_settings(self, layout, theme, gpu=None):
        if gpu is not None and gpu != bool(SETTINGS.get("gpu3d", True)):
            from ..board3d import set_gpu_enabled
            SETTINGS["gpu3d"] = gpu
            save_settings(SETTINGS)
            set_gpu_enabled(gpu, retry=gpu)           # ticking it again also retries after a failure
            self._v3_info = None                      # next frames come from the other renderer
            self.v3_schedule()
            if self.tab_var.get() == "decor":
                self.dc_render()
            from .. import gpu3d
            self.set_status("3D preview: " + ("graphics card (GPU)" if gpu else
                            "processor (CPU)" + (" \u00b7 restart the tool to free the graphics driver's memory"
                                                 if gpu3d.existing() is not None else "")))
        if layout == SETTINGS.get("layout") and theme == SETTINGS.get("theme"):
            return
        SETTINGS["layout"], SETTINGS["theme"] = layout, theme
        save_settings(SETTINGS)
        self.rebuild()
        self.set_status(f"Layout: {LAYOUTS[layout][0]} · theme: {theme}")

    def rebuild(self):
        """Rebuilds the whole window for a new layout / theme; keeps folder, selection and edits."""
        self._keep = {
            "tab": self.tab_var.get(), "filter": self._filter_text() and self.filter_var.get(),
            "board_tab": self.board_tab.get() if hasattr(self, "board_tab") else "tex",
            "status": self.status_var.get(), "keep_pal": self.keep_pal.get(),
            "screws": self.v3_screws.get(), "outline": self.v3_outline.get(),
            "sm": (self.sm_speed.get(), self.sm_charge.get(), self.sm_precise.get(), self.sm_bg.get()),
            "dc_left": self.dc_left_tab.get(), "dc_mode": self.dc_mode.get(),
        }
        self._dc_tex_photos, self.dc_info = {}, None
        for job in ("_v3_job", "_v3_tick", "_sm_job", "_dc_sharp", "_dc_upd", "_dc_flat_job"):
            j = getattr(self, job, None)
            if j:
                try:
                    base.root.after_cancel(j)
                except Exception:
                    pass
                setattr(self, job, None)
        self._v3_photo = self._v3_item = self._sm_photo = None
        self._v3_again = False
        for w in base.root.winfo_children():
            w.destroy()
        set_theme(SETTINGS.get("theme", "dark"))
        base.root.configure(bg=C["bg"])
        if SETTINGS.get("layout") != "gallery":
            self.gal_pil = {}                   # card images are only needed in the Gallery layout
        self.row_imgs, self.sm_imgs = {}, {}
        self._style()
        self._build()
        sp, ch, pr, bg = self._keep["sm"]
        self.sm_speed.set(sp), self.sm_charge.set(ch), self.sm_precise.set(pr), self.sm_bg.set(bg)
        titlebar(base.root, C["dark"])
        self._fit_path()
        self._fill_list()
        if self.sel is not None and not self.custom and self.sel < len(self.boards):
            self._syncing = True
            if self.tree.exists(str(self.sel)):
                self.tree.selection_set(str(self.sel))
                self.tree.see(str(self.sel))
            self._syncing = False
        self._refresh_panels()
        self._update_summary()
        if self.sm_folder is not None or self.sm_tex:
            self._sm_fill_tree()
            self._sm_set_note()
        self.sm_refresh(render=self.tab_var.get() == "speed")
        base.root.after(50, lambda: (self._gal_layout(force=True), self.sel is not None and self._gal_scroll_to(self.sel)))

    # ---------- classic layout: texture | 3D row ----------
    def _layout_top_row(self, e=None):
        """Texture and 3D preview side by side on wide windows, stacked on narrow ones."""
        if self.layout != "classic" or not hasattr(self, "top_row"):
            return
        w = e.width if e is not None else self.top_row.winfo_width()
        mode = "side" if w >= 980 else "stack"
        if mode == getattr(self, "_top_mode", None):
            return
        self._top_mode = mode
        r = self.top_row
        self.tex_card.grid_forget()
        self.v3_card.grid_forget()
        for i in range(2):
            r.columnconfigure(i, weight=0, uniform="")
            r.rowconfigure(i, weight=0)
        if mode == "side":
            r.columnconfigure(0, weight=5, uniform="top")
            r.columnconfigure(1, weight=4, uniform="top")
            self.tex_card.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
            self.v3_card.grid(row=0, column=1, sticky="nsew", padx=(10, 0))
            self.v3_canvas.config(height=200)
        else:
            r.columnconfigure(0, weight=1)
            self.tex_card.grid(row=0, column=0, sticky="nsew")
            self.v3_card.grid(row=1, column=0, sticky="nsew", pady=(20, 0))
            self.v3_canvas.config(height=300)
        self.v3_schedule()
