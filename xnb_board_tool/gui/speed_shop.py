"""The Speedmeter tab in the Skate shop layout: built like the deck Bench.

    title bar   THE HUD · status tag · what is not written yet · folder
    dock        backdrop tags (Game / Dark / Checker)   tool tags (Parts / Bar texture / Text)   hint
    body        the in-game preview with the speed controls  |  the tool's sheet
    ink bar     what is only on screen · Reset · Write to game

It creates the same named widgets as the other layouts' Speedmeter tab (sm_canvas, sm_tree, sm_prev,
b_sm_replace, ...), so every action works unchanged; the tree that holds the part list is never shown
(the Parts sheet draws its own rows from it)."""
from __future__ import annotations

from tkinter import ttk
import tkinter as tk

from ..i18n import N_, _
from ..speedmeter import SPEEDMETER_PARTS
from ..settings import C
from .base import F, Preview, Scroll, Slider, button, label
from . import base
from .shop import HangTag, _flat_button, ink, onink

SMS_TOOLS = (("parts", N_("Parts")), ("bartex", N_("Bar texture")), ("text", N_("Text")))
SMS_BACKDROPS = (("game", N_("Game")), ("dark", N_("Dark")), ("checker", N_("Checker")))


class SpeedShopMixin:
    """The Skate shop Speedmeter page. Mixed into App."""

    def _build_speed_shop(self, view):
        """Builds the Speedmeter tab of the Skate shop layout: the title bar ('The HUD' with its status tag), the
        dock (backdrop tags, the Parts / Bar texture / Text tools), the stage with the live preview and the
        sliders, the tool sheet on the right and the ink bar with Write to game / Reset.
        """
        P = C["panel"]
        # ---- title bar ----
        top = tk.Frame(view, bg=C["bg"])
        top.pack(fill="x", padx=24, pady=(0, 10))
        tk.Label(top, text=_("The HUD").upper(), font=F["displaylg"], fg=ink(), bg=C["bg"]).pack(side="left", pady=(12, 0))
        self.sm_badge = tk.Label(tk.Frame(top), font=F["smallbold"])     # written by sm_refresh, never shown
        self._sms_badge = HangTag(top, "…", None, kind="ink")
        self._sms_badge.pack(side="left", padx=(16, 14), anchor="n")
        self._sms_dirty = label(top, "", "smallbold", "warn", bg=C["bg"])
        self._sms_dirty.pack(side="left", pady=(12, 0))
        self.sm_folder_lbl = label(top, "", "small", "muted", bg=C["bg"], anchor="e")
        self.sm_folder_lbl.pack(side="right", pady=(12, 0))
        tk.Frame(view, bg=ink(), height=2).pack(fill="x")

        # ---- dock ----
        dock_row = tk.Frame(view, bg=C["bg"])
        dock_row.pack(fill="x", padx=24)
        dock_row.columnconfigure(0, weight=1, uniform="dock")
        dock_row.columnconfigure(2, weight=1, uniform="dock")
        views = tk.Frame(dock_row, bg=C["bg"])
        views.grid(row=0, column=0, sticky="nw")
        self.sm_bg = tk.StringVar(value="game")
        self._sms_bg_tags = {}
        for val, text in SMS_BACKDROPS:
            t = HangTag(views, _(text).upper(), lambda v=val: self._sms_backdrop(v))
            t.pack(side="left", padx=(0, 8), anchor="n")
            self._sms_bg_tags[val] = t
        dock = tk.Frame(dock_row, bg=C["bg"])
        dock.grid(row=0, column=1, sticky="n")
        self._sms_tool_tags = {}
        for val, text in SMS_TOOLS:
            t = HangTag(dock, _(text).upper(), lambda v=val: self.sms_tool(v))
            t.pack(side="left", padx=5, anchor="n")
            self._sms_tool_tags[val] = t
        label(dock_row, _("Space plays a run · drag the sliders to set the speed"), "small", "sub",
              bg=C["bg"]).grid(row=0, column=2, sticky="e")

        # ---- ink bar (first, so it stays visible) ----
        bar = tk.Frame(view, bg=ink())
        bar.pack(side="bottom", fill="x")
        bi = tk.Frame(bar, bg=ink())
        bi.pack(fill="x", padx=24, pady=10)
        self._sms_msg = tk.Label(bi, text="", font=F["body"], fg=onink(), bg=ink(), anchor="w")
        self._sms_msg.pack(side="left", fill="x", expand=True)
        self._sms_write = _flat_button(bi, _("Write to game"), self.sm_write_all, C["accent"], C["onaccent"],
                                       C["accenth"], bd=C["accent"])
        self._sms_write.pack(side="right")
        self._sms_reset = _flat_button(bi, _("Reset"), self.sm_reset_all, ink(), onink(), C["sub"],
                                       font=F["body"], bd=onink())
        self._sms_reset.pack(side="right", padx=(0, 10))

        # ---- body: stage | sheet ----
        body = tk.Frame(view, bg=C["bg"])
        body.pack(fill="both", expand=True)
        sheet_wrap = tk.Frame(body, bg=P, width=420)
        sheet_wrap.pack(side="right", fill="y")
        sheet_wrap.pack_propagate(False)
        tk.Frame(body, bg=ink(), width=2).pack(side="right", fill="y")
        stage = tk.Frame(body, bg=C["bg"])
        stage.pack(side="left", fill="both", expand=True)
        self._sms_build_stage(stage)
        sc = self._sms_scroll = Scroll(sheet_wrap)
        sc.canvas.config(bg=P)
        sc.inner.config(bg=P)
        sc.pack(fill="both", expand=True)
        self._sms_build_sheets(sc.inner)

        if not getattr(self, "_sms_space_bound", False):        # the root outlives rebuilds: bind once
            base.root.bind("<space>", self._sms_space, add="+")
            self._sms_space_bound = True
        self._sms_backdrop(self.sm_bg.get(), render=False)
        self.sms_tool(getattr(self, "_sms_tool", "parts"))

    # ------------------------------------------------------------------ stage
    def _sms_build_stage(self, stage):
        """The stage: the in-game preview canvas in a frame, the note under it, Play run and the speed / charge
        sliders.
        """
        holder = tk.Frame(stage, bg=C["bg"])
        holder.pack(fill="both", expand=True, padx=24, pady=(14, 16))
        ctl = tk.Frame(holder, bg=C["bg"])
        ctl.pack(side="bottom", fill="x", pady=(14, 0))
        self.sm_note = label(holder, "", "small", "muted", anchor="w", justify="left", bg=C["bg"])
        self.sm_note.pack(side="bottom", fill="x", pady=(10, 0))
        self.sm_note.bind("<Configure>", lambda e: self.sm_note.config(wraplength=max(200, e.width - 4)))
        frame = tk.Frame(holder, bg=C["bg"], highlightthickness=2, highlightbackground=ink())
        frame.pack(fill="both", expand=True)
        cap = tk.Label(frame, text=_("IN-GAME PREVIEW · THE GAME'S OWN LAYOUT AND SHADER"), font=F["displaysm"],
                       fg=onink(), bg=ink(), padx=8, pady=1)
        cap.place(x=10, y=10)
        self.sm_canvas = tk.Canvas(frame, height=160, bg=C["bg"], highlightthickness=0)
        self.sm_canvas.pack(fill="x", expand=True, padx=14)
        self.sm_canvas.bind("<Configure>", lambda e: self.sm_schedule())
        cap.lift()

        def slider(parent, var):
            """A speed slider (0-120, 0.1 steps) that re-renders the preview when moved."""
            return Slider(parent, 0, 120, variable=var, resolution=0.1, command=lambda v: self._sm_controls(),
                          length=360, bg=C["bg"])
        self.sm_speed = tk.DoubleVar(value=19.4)
        self.sm_charge = tk.DoubleVar(value=0.0)
        self.sm_precise = tk.BooleanVar(value=True)
        self._sm_play = self._sm_play_job = None
        self._sm_play_setting = False
        self.b_sm_play = _flat_button(ctl, _("▶  Play run"), self.sm_play_toggle, C["accent"], C["onaccent"],
                                      C["accenth"], bd=C["accent"], padx=18, pady=12)
        self.b_sm_play.grid(row=0, column=0, rowspan=2, sticky="nsw", padx=(0, 18))
        for r, (name, var, lblattr) in enumerate(((N_("Speed"), self.sm_speed, "sm_speed_lbl"),
                                                   (N_("Charge"), self.sm_charge, "sm_charge_lbl"))):
            label(ctl, _(name).upper(), "displaysm", "text", bg=C["bg"], width=8, anchor="w").grid(
                row=r, column=1, sticky="w")
            slider(ctl, var).grid(row=r, column=2, sticky="we", pady=3)
            lb = label(ctl, "", "mono", "sub", bg=C["bg"], width=22, anchor="w")
            lb.grid(row=r, column=3, sticky="w", padx=(10, 0))
            setattr(self, lblattr, lb)
        ctl.columnconfigure(2, weight=1)
        tk.Checkbutton(ctl, text=_("Precise (MM/S)"), variable=self.sm_precise, command=self._sm_controls,
                       bg=C["bg"], fg=C["sub"], activebackground=C["bg"], activeforeground=C["text"],
                       selectcolor=C["panel"], font=F["small"], bd=0, highlightthickness=0,
                       cursor="hand2").grid(row=0, column=4, rowspan=2, sticky="e", padx=(14, 0))

    def _sms_backdrop(self, val, render=True):
        """Picks the preview's backdrop (game screenshot, dark or checkerboard) and lights its tag."""
        self.sm_bg.set(val)
        for v, t in self._sms_bg_tags.items():
            t.set(kind="on" if v == val else "ink")
        if render:
            self.sm_schedule()

    def _sms_space(self, e):
        """Space plays or stops a run while the Speedmeter tab is open (not while typing in a text field)."""
        if getattr(self, "layout", None) != "shop" or self.tab_var.get() != "speed":
            return
        if isinstance(e.widget, (tk.Entry, tk.Text, ttk.Entry)):
            return
        self.sm_play_toggle()
        return "break"

    # ------------------------------------------------------------------ sheets
    def _sms_build_sheets(self, parent):
        """Builds the three tool sheets: Parts (the five files as rows, then the picked one with Replace / Export /
        Revert), Bar texture and Text (built by SpeedToolsMixin).
        """
        P = C["panel"]
        self._sms_sheets = {}

        # Parts: the five files, then the picked one
        pg = tk.Frame(parent, bg=P)
        hd = tk.Frame(pg, bg=P)
        hd.pack(fill="x")
        tk.Label(hd, text=_("Parts").upper(), font=F["display"], fg=ink(), bg=P, anchor="w").pack(side="left")
        self.sm_count = label(hd, "", "small", "muted", bg=P)
        self.sm_count.pack(side="right")
        self._wrap_label(pg, _("The five files the speedometer is drawn from. Pick one to see it and replace it."),
                         fg="sub").pack(fill="x", pady=(2, 12))
        self.sm_tree = ttk.Treeview(tk.Frame(pg), show="tree", selectmode="browse")   # the list model, hidden
        self.sm_tree.bind("<<TreeviewSelect>>", self._sm_on_select)
        self._sms_rows = {}
        for key, name, _d in SPEEDMETER_PARTS:
            rowf = tk.Frame(pg, bg=C["bg"], highlightthickness=2, highlightbackground=C["bg"], cursor="hand2")
            rowf.pack(fill="x", pady=(0, 6))
            img = tk.Label(rowf, bg=C["bg"])
            img.pack(side="left", padx=(6, 4), pady=6)
            nm = label(rowf, _(name), "bold", bg=C["bg"])
            nm.pack(side="left")
            stw = label(rowf, "", "small", "muted", bg=C["bg"])
            stw.pack(side="right", padx=10)
            for w in (rowf, img, nm, stw):
                w.bind("<Button-1>", lambda e, k=key: self._sms_pick(k))
            self._sms_rows[key] = (rowf, img, nm, stw)
        tk.Frame(pg, bg=C["border"], height=1).pack(fill="x", pady=(14, 14))
        self.sm_part_title = tk.Label(pg, text="", font=F["display"], fg=ink(), bg=P, anchor="w")
        self.sm_part_title.pack(fill="x")
        self.sm_part_file = label(pg, "", "mono", "muted", anchor="w", bg=P)
        self.sm_part_file.pack(fill="x")
        self.sm_chips = tk.Frame(pg, bg=P)
        self.sm_chips._compact = True
        self.sm_chips.pack(fill="x", pady=(2, 6))
        self.sm_part_desc = self._wrap_label(pg, "", fg="sub")
        self.sm_part_desc.pack(fill="x", pady=(0, 8))
        self.sm_prev = Preview(pg, 154 / 3699, 150, on_drop=lambda f: self.sm_replace(f))
        self.sm_prev.pack(fill="x")
        self.sm_usage = self._wrap_label(pg, "", fg="muted")
        self.sm_usage.pack(fill="x", pady=(8, 0))
        self.b_sm_replace = button(pg, _("↑  Replace image…"), lambda: self.sm_replace(), "primary")
        self.b_sm_replace.pack(fill="x", pady=(12, 0))
        row = tk.Frame(pg, bg=P)
        row.pack(fill="x", pady=(8, 0))
        self.b_sm_export = button(row, _("Export PNG…"), self.sm_export)
        self.b_sm_export.pack(side="left")
        self.b_sm_revert = button(row, _("Revert to default"), self.sm_revert)
        self.b_sm_revert.pack(side="left", padx=(8, 0))
        self.b_sm_setdef = button(pg, _("Set current as default"), self.sm_set_default, "ghost")
        self.b_sm_setdef.pack(anchor="w", pady=(8, 0))
        self._sms_sheets["parts"] = pg

        # Bar texture
        pg = tk.Frame(parent, bg=P)
        tk.Label(pg, text=_("Bar texture").upper(), font=F["display"], fg=ink(), bg=P, anchor="w").pack(fill="x")
        self._wrap_label(pg, _("Texture.xnb colors the bar, the blocks, the unit text and the digits. Changes show "
                               "on the preview; write them with the button at the bottom."),
                         fg="sub").pack(fill="x", pady=(2, 14))
        self._bt_build(pg, shop=True)
        button(pg, _("Save as PNG…"), self.sm_bt_export, "ghost").pack(anchor="w", pady=(4, 0))
        self._sms_sheets["bartex"] = pg

        # Text
        pg = tk.Frame(parent, bg=P)
        tk.Label(pg, text=_("Text maker").upper(), font=F["display"], fg=ink(), bg=P, anchor="w").pack(fill="x")
        self._wrap_label(pg, _("New unit text under the bar (CMS.xnb and MMS.xnb). It is made white: the bar "
                               "texture colors it and the game adds the black outline."),
                         fg="sub").pack(fill="x", pady=(2, 14))
        self._tx_build(pg, shop=True)
        button(pg, _("Save as PNG…"), self.sm_tx_export, "ghost").pack(anchor="w", pady=(10, 0))
        self._sms_sheets["text"] = pg

    def sms_tool(self, tool):
        """Shows a tool's sheet. The Bar texture and Text tools start working when their sheet is first
        opened; what they change stays on screen until it is written or reset."""
        if tool not in self._sms_sheets:
            tool = "parts"
        self._sms_tool = tool
        for v, t in self._sms_tool_tags.items():
            t.set(kind="on" if v == tool else "ink")
        for v, f in self._sms_sheets.items():
            if v != tool:
                f.pack_forget()
        self._sms_sheets[tool].pack(fill="both", expand=True, padx=22, pady=20)
        self._sms_scroll.canvas.yview_moveto(0)
        if tool == "bartex" and not self.sm_bt_on:
            self.sm_bt_on = True
            base.root.after_idle(self._bt_update)
        elif tool == "text" and not self.sm_tx_on:
            self.sm_tx_on = True
            base.root.after_idle(self._tx_update)
        self._sms_refresh()

    def _sms_pick(self, key):
        """A part row was clicked: selects that file and refreshes the sheet."""
        if key == self.sm_key:
            return
        self.sm_key = key
        self._syncing = True
        if self.sm_tree.exists(key):
            self.sm_tree.selection_set(key)
        self._syncing = False
        self.sm_refresh(render=False)

    # ------------------------------------------------------------------ refresh
    def _sms_rows_refresh(self):
        """Updates the part rows: the picked one outlined, each with its picture and status (stock / changed / on
        screen only / missing).
        """
        rows = getattr(self, "_sms_rows", None)
        if not rows:
            return
        words = {"def": N_("Default"), "mod": N_("Changed"), None: N_("No default")}
        pending = self._sm_pending()
        touched = {"Texture"} if "bar texture" in pending else set()
        if "unit text" in pending:
            touched |= {"CMS", "MMS"}
        for key, (rowf, img, nm, stw) in rows.items():
            on = key == self.sm_key
            rowf.config(highlightbackground=C["accent"] if on else C["bg"])
            if key in self.sm_tex:
                ph = self._sm_row_image(key)
                img.config(image=ph)
                img._ph = ph
                st = _("on screen only") if key in touched else _(words.get(self.sm_status.get(key), words[None]))
                stw.config(text=st, fg=C["warn"] if key in touched else C["muted"])
            else:
                stw.config(text=self.sm_err.get(key, _("file not found")), fg=C["warn"])

    def _sms_refresh(self):
        """Status tag, 'not written yet', the ink bar and the part rows."""
        if getattr(self, "layout", None) != "shop" or not hasattr(self, "_sms_msg"):
            return
        if not self._sms_msg.winfo_exists():
            return
        b = self.sm_badge
        self._sms_badge.set(text=(b.cget("text") or "…").upper(), kind="color",
                            colors=(b.cget("bg") or C["btn"], b.cget("fg") or C["muted"]))
        pending = self._sm_pending()
        names = [_(p) for p in pending]
        self._sms_dirty.config(text=("●  " + _("{what} not written yet", what=" + ".join(names))) if names else "")
        if names:
            self._sms_msg.config(text=_("The new {what} is only on screen. Write it to the game, or reset it.",
                                        what=" + ".join(names)))
        elif self.sm_folder is None:
            self._sms_msg.config(text=_("Choose the SpeedMeter folder to begin (Change folder… in the folder chip)."))
        else:
            self._sms_msg.config(text=_("Everything on the HUD is in the game."))
        on = bool(pending)
        self._sms_write.config(state="normal" if on else "disabled", bg=C["accent"] if on else ink(),
                               fg=C["onaccent"] if on else C["dis"],
                               highlightbackground=C["accent"] if on else C["dis"])
        self._sms_write.bind("<Leave>", lambda e, w=self._sms_write, on=on: w.config(bg=C["accent"] if on else ink()))
        self._sms_reset.config(state="normal" if on else "disabled")
        self._sms_rows_refresh()
        if hasattr(self, "_shop_tabs_refresh"):
            self._shop_tabs_refresh()
