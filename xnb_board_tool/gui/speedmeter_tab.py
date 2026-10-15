"""The Speedmeter tab: files list, live in-game preview and actions."""
from __future__ import annotations

import math
import threading
from pathlib import Path

from tkinter import filedialog
from tkinter import messagebox
from tkinter import ttk
import tkinter as tk
from PIL import Image, ImageDraw, ImageTk

from ..xnb import load_texture
from ..i18n import N_, _, _n
from ..defaults import board_status, file_status, load_default_meta, revert_to_default, set_default
from ..boards import strip_image
from ..speedmeter import (
    SM_BLOCK_STEP, SM_PX_PER_CMS, SM_SCREEN, SPEEDMETER_PARTS, find_digit_font,
    find_speedmeter_folder, fix_sinkingship_italic, load_spritefont, render_speedmeter,
)
from ..settings import BADGES, C, _rgb, checker
from .base import F, Preview, SegButton, Slider, button, card, hline, label, set_state
from . import base
from .dialogs import AdjustDialog


class SpeedmeterMixin:
    """The Speedmeter tab: files list, live in-game preview and actions. Mixed into App."""

    # ---------- speedmeter tab: layout ----------
    def _build_speed_sidebar(self, side):
        """The Speedmeter list of the Studio / Gallery / Classic layouts: the file count, the folder and the list
        of the five parts.
        """
        top = tk.Frame(side, bg=C["side"])
        top.pack(fill="x", padx=14, pady=(12, 8))
        r = tk.Frame(top, bg=C["side"])
        r.pack(fill="x")
        label(r, _("Speedmeter files"), "bold").pack(side="left")
        self.sm_count = label(r, "", "small", "muted")
        self.sm_count.pack(side="right")
        self.sm_folder_lbl = label(top, "", "small", "muted", anchor="w", justify="left", wraplength=250)
        self.sm_folder_lbl.pack(fill="x", pady=(6, 0))
        lst = tk.Frame(side, bg=C["side"])
        lst.pack(fill="both", expand=True, padx=(8, 0), pady=(10, 10))
        self.sm_tree = ttk.Treeview(lst, show="tree", style="Boards.Treeview", selectmode="browse")
        self.sm_tree.pack(fill="both", expand=True)
        self.sm_tree.bind("<<TreeviewSelect>>", self._sm_on_select)

    def _build_speed_main(self, parent):
        """The Speedmeter page of the Studio / Gallery / Classic layouts: the live preview card with its sliders
        and the card of the picked part.
        """
        m = tk.Frame(parent, bg=C["bg"])
        m.pack(fill="both", expand=True, padx=28, pady=22)
        tr = tk.Frame(m, bg=C["bg"])
        tr.pack(fill="x")
        label(tr, _("Speedmeter"), "h1").pack(side="left")
        self.sm_badge = tk.Label(tr, font=F["smallbold"], padx=10, pady=3)
        self.sm_badge.pack(side="left", padx=14)

        # live preview card
        pc = card(m)
        pc.pack(fill="x", pady=(18, 0))
        head = tk.Frame(pc, bg=C["panel"])
        head.pack(fill="x", padx=16, pady=10)
        label(head, _("In-game preview"), "h2").pack(side="left")
        label(head, _("built from your files with the game's own layout and shader math"),
              "small", "muted").pack(side="left", padx=10)
        self.b_sm_bartex = button(head, _("◐  Bar texture"), lambda: self.sm_tool_toggle("bt"), small=True)
        self.b_sm_bartex.pack(side="right")
        self.b_sm_text = button(head, _("Aa  Text maker"), lambda: self.sm_tool_toggle("tx"), small=True)
        self.b_sm_text.pack(side="right", padx=(0, 8))
        hline(pc).pack(fill="x")
        self.sm_canvas = tk.Canvas(pc, height=160, bg=C["bg"], highlightthickness=0)
        self.sm_canvas.pack(fill="x", padx=16, pady=(16, 10))
        self.sm_canvas.bind("<Configure>", lambda e: self.sm_schedule())
        ctl = tk.Frame(pc, bg=C["panel"])
        ctl.pack(fill="x", padx=16)

        def slider(parent, lo, hi, var, cmd):
            """A speed slider (0.1 steps) for the preview card."""
            return Slider(parent, lo, hi, variable=var, resolution=0.1, command=cmd, length=260,
                          bg=C["panel"])
        self.sm_speed = tk.DoubleVar(value=19.4)
        self.sm_charge = tk.DoubleVar(value=0.0)
        self.sm_precise = tk.BooleanVar(value=True)
        self.sm_bg = tk.StringVar(value="game")
        r1 = tk.Frame(ctl, bg=C["panel"])
        r1.pack(fill="x")
        label(r1, _("Speed"), "small", "muted", width=7, anchor="w").pack(side="left")
        slider(r1, 0, 120, self.sm_speed, lambda v: self._sm_controls()).pack(side="left")
        self.sm_speed_lbl = label(r1, "", "mono", "sub", width=22, anchor="w")
        self.sm_speed_lbl.pack(side="left", padx=8)
        self._sm_play = self._sm_play_job = None
        self._sm_play_setting = False
        self.b_sm_play = button(r1, _("▶  Play run"), self.sm_play_toggle, "primary", small=True)
        self.b_sm_play.pack(side="left", padx=(4, 0))
        tk.Checkbutton(r1, text=_("Precise (MM/S)"), variable=self.sm_precise,
                       command=self._sm_controls, bg=C["panel"], fg=C["sub"],
                       activebackground=C["panel"], activeforeground=C["text"],
                       selectcolor=C["bg"], font=F["small"], bd=0, highlightthickness=0,
                       cursor="hand2").pack(side="right")
        r2 = tk.Frame(ctl, bg=C["panel"])
        r2.pack(fill="x", pady=(6, 0))
        label(r2, _("Charge"), "small", "muted", width=7, anchor="w").pack(side="left")
        slider(r2, 0, 120, self.sm_charge, lambda v: self._sm_controls()).pack(side="left")
        self.sm_charge_lbl = label(r2, "", "mono", "sub", width=22, anchor="w")
        self.sm_charge_lbl.pack(side="left", padx=8)
        for text, val in ((N_("Checker"), "checker"), (N_("Dark"), "dark"), (N_("Game"), "game")):
            SegButton(r2, text=_(text), value=val, variable=self.sm_bg,
                           command=self.sm_schedule, indicatoron=False, bg=C["btn"],
                           fg=C["text"], selectcolor=C["selfill"], activebackground=C["btnh"],
                           activeforeground=C["text"], relief="flat", bd=0, highlightthickness=1,
                           highlightbackground=C["btnb"], padx=10, pady=3, font=F["small"],
                           cursor="hand2").pack(side="right", padx=(4, 0))
        label(r2, _("Background"), "small", "muted").pack(side="right", padx=(0, 6))
        self.sm_note = label(pc, "", "small", "muted", anchor="w", justify="left")
        self.sm_note.pack(fill="x", padx=16, pady=(8, 14))
        self._sm_preview_card = pc
        self._build_tool_cards(m, after=pc)

        # selected file card
        fc = card(m)
        fc.pack(fill="x", pady=(20, 0))
        head = tk.Frame(fc, bg=C["panel"])
        head.pack(fill="x", padx=16, pady=10)
        self.sm_part_title = label(head, "", "h2")
        self.sm_part_title.pack(side="left")
        self.sm_part_file = label(head, "", "mono", "muted")
        self.sm_part_file.pack(side="left", padx=10)
        self.sm_chips = tk.Frame(head, bg=C["panel"])
        self.sm_chips.pack(side="right")
        hline(fc).pack(fill="x")
        self.sm_part_desc = label(fc, "", "small", "sub", anchor="w", justify="left")
        self.sm_part_desc.pack(fill="x", padx=16, pady=(12, 0))
        self.sm_prev = Preview(fc, 154 / 3699, 300, on_drop=lambda f: self.sm_replace(f))
        self.sm_prev.pack(fill="x", padx=16, pady=12)
        self.sm_usage = label(fc, "", "small", "muted", anchor="w", justify="left")
        self.sm_usage.pack(fill="x", padx=16)
        self.sm_usage.bind("<Configure>", lambda e: self.sm_usage.config(wraplength=max(200, e.width - 8)))
        act = tk.Frame(fc, bg=C["panel"])
        act.pack(fill="x", padx=16, pady=(10, 16))
        self.b_sm_replace = button(act, _("↑  Replace image…"), lambda: self.sm_replace(), "primary")
        self.b_sm_replace.pack(side="left")
        self.b_sm_export = button(act, _("Export PNG…"), self.sm_export)
        self.b_sm_export.pack(side="left", padx=(8, 0))
        self.b_sm_revert = button(act, _("Revert to default"), self.sm_revert)
        self.b_sm_revert.pack(side="left", padx=(8, 0))
        self.b_sm_setdef = button(act, _("Set current as default"), self.sm_set_default, "ghost")
        self.b_sm_setdef.pack(side="right")

    def sm_path(self, key):
        """The .xnb file of a speedmeter part ('Texture', 'Block', ...), or None without a folder."""
        return self.sm_folder / f"{key}.xnb" if self.sm_folder else None

    def sm_choose_folder(self):
        """Asks for the SpeedMeter folder (or the game's Content folder, searched for it) and loads it; says so
        when no speedmeter textures are there.
        """
        d = filedialog.askdirectory(title=_("Select the SpeedMeter folder (or the game's "
                                            "Content folder)"))
        if not d:
            return
        f = find_speedmeter_folder(Path(d))
        if f is None:
            messagebox.showinfo(_("Speedmeter"), _("No speedmeter textures (Texture.xnb, "
                                                "Block.xnb, …) were found in that "
                                                "folder.\n\nThey are in "
                                                "Content\\Textures\\HUD\\SpeedMeter inside the "
                                                "game folder."))
            return
        if self.cache.file is None:
            self.cache.attach(f)
        self.sm_load(f)
        self.set_status(_("Speedmeter files loaded from {f}", f=f))

    def sm_load(self, folder):
        """Loads the five speedmeter textures of a folder with their stock status (a missing or unreadable file is
        noted in sm_err), finds the digit font and refreshes the tab.
        """
        self.busy(True)
        try:
            self.sm_folder = folder
            self.sm_tex, self.sm_err, self.sm_status = {}, {}, {}
            for key, _name, _desc in SPEEDMETER_PARTS:
                p = self.sm_path(key)
                if p is None or not p.exists():
                    self.sm_err[key] = _("file not found")
                    continue
                try:
                    self.sm_tex[key] = load_texture(p)
                except Exception as e:
                    self.sm_err[key] = str(e)
                try:
                    self.sm_status[key] = file_status(p, self.cache, self.sm_tex.get(key))
                except Exception:
                    self.sm_status[key] = None
        finally:
            self.busy(False)
        self.sm_font = None
        fp = find_digit_font(folder)
        if fp is not None:
            try:
                self.sm_font = fix_sinkingship_italic(load_spritefont(fp))
            except Exception:
                self.sm_font = None
        self._sm_set_note()
        self._sm_fill_tree()
        self.sm_refresh()
        self._sm_tools_reload()                      # the Bar texture / Text maker tools follow the files

    def _sm_set_note(self):
        """The note under the preview (what charge means, which digit font is used) and the folder hint."""
        self.sm_note.config(text=_("Charge = the black blocks ahead of the bar (potential speed).") + " " + (
            _("Digits use the game's own font (VeryBigItalicNumeric).") if self.sm_font else
            _("Digits use a stand-in font ({path} not found).",
              path="Content\\Fonts\\SinkingShip\\VeryBigItalicNumeric.xnb")))
        self.sm_folder_lbl.config(text="" if self.sm_folder else
                                  _("Not found — use Change… in the top bar to pick the "
                                         "SpeedMeter folder (or the game's Content folder)."))
        self._fit_path()

    def _sm_row_image(self, key):
        """The picture of a part's list row: a status mark (stock / changed / no stock / missing) and a small strip
        of the image.
        """
        im = Image.new("RGBA", (104, 24), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        st = self.sm_status.get(key)
        if key not in self.sm_tex:
            d.line([4, 8, 10, 16], fill=_rgb(C["dis"]), width=2)
            d.line([4, 16, 10, 8], fill=_rgb(C["dis"]), width=2)
        elif st == "def":
            d.ellipse([3, 8, 11, 16], fill=_rgb(C["green"]))
        elif st == "mod":
            d.rectangle([3, 8, 11, 16], fill=_rgb(C["accent"]))
        else:
            d.ellipse([3, 8, 11, 16], outline=_rgb(C["muted"]), width=2)
        t = self.sm_tex.get(key)
        if t is not None:
            im.paste(strip_image(t.img), (20, 3))
        else:
            d.rectangle([20, 3, 95, 20], fill=_rgb(C["btn"]))
        ph = ImageTk.PhotoImage(im)
        self.sm_imgs[key] = ph
        return ph

    def _sm_fill_tree(self):
        """Fills the part list (and the shop layout's rows) and the 'x of 5' count."""
        self._syncing = True
        self.sm_tree.delete(*self.sm_tree.get_children())
        for key, name, _d in SPEEDMETER_PARTS:
            self.sm_tree.insert("", "end", iid=key, text="  " + _(name), image=self._sm_row_image(key))
        if self.sm_tree.exists(self.sm_key):
            self.sm_tree.selection_set(self.sm_key)
        self._syncing = False
        found = len(self.sm_tex)
        self.sm_count.config(text=_("{found} of {n}", found=found, n=len(SPEEDMETER_PARTS)))
        if self.layout == "shop":
            self._sms_rows_refresh()

    def _sm_on_select(self, _e=None):
        """A part picked in the list: shows it."""
        if self._syncing:
            return
        s = self.sm_tree.selection()
        if s and s[0] != self.sm_key:
            self.sm_key = s[0]
            self.sm_refresh(render=False)

    def sm_step(self, d):
        """Picks the previous / next part (‹ › while on the Speedmeter tab)."""
        keys = [k for k, _n, _d in SPEEDMETER_PARTS]
        j = keys.index(self.sm_key) + d
        if 0 <= j < len(keys):
            self.sm_key = keys[j]
            self._syncing = True
            self.sm_tree.selection_set(self.sm_key)
            self._syncing = False
            self.sm_refresh(render=False)

    # ------------------------------------------------------------------ play run
    SM_RUN = (2.6, 0.9, 2.6, 0.9)      # seconds: speed up, hold at the top, slow down, rest at 0

    def sm_play_toggle(self):
        """Play run / Stop (the button and the Space key)."""
        if self._sm_play:
            self.sm_play_stop()
        else:
            self.sm_play_start()

    def sm_play_start(self):
        """Animates a run: 0 -> top speed -> 0, again and again, with the charge (the black blocks of
        potential speed) running ahead while speeding up. Top = the speed set before (at least 30)."""
        import time
        if len(self.sm_tex) < len(SPEEDMETER_PARTS):
            self.set_status(_("Preview needs all five speedmeter files"))
            return
        top = max(30.0, float(self.sm_speed.get()))
        self._sm_play = {"t0": time.monotonic(), "top": top, "keep": (self.sm_speed.get(), self.sm_charge.get()),
                         "n": 0}
        self.b_sm_play.config(text=_("■  Stop"))
        self.set_status(_("Playing a run up to {top:.0f} cm/s — click Stop to end", top=top))
        self._sm_play_tick()

    def sm_play_stop(self, restore=True):
        """Stops a run; restore=True puts the speed and charge sliders back where they were before it."""
        p, self._sm_play = self._sm_play, None
        if self._sm_play_job:
            base.root.after_cancel(self._sm_play_job)
            self._sm_play_job = None
        if hasattr(self, "b_sm_play") and self.b_sm_play.winfo_exists():
            self.b_sm_play.config(text=_("▶  Play run"))
        if p and restore:
            self._sm_play_setting = True
            self.sm_speed.set(p["keep"][0])
            self.sm_charge.set(p["keep"][1])
            self._sm_play_setting = False
            self._sm_controls()

    @staticmethod
    def _sm_ease(u):
        """Smoothstep easing of u (0-1) for the run animation."""
        u = max(0.0, min(1.0, u))
        return u * u * (3 - 2 * u)

    def _sm_play_at(self, t, top):
        """(speed, charge) at t seconds into the run."""
        up, hold, down, rest = self.SM_RUN
        t %= up + hold + down + rest
        if t < up:                                  # speeding up, the charge leads the way
            u = t / up
            sp = top * self._sm_ease(u)
            return sp, min(top * 1.15, top * self._sm_ease(u + 0.3) * 1.1)
        if t < up + hold:
            return top, 0.0
        if t < up + hold + down:
            return top * (1 - self._sm_ease((t - up - hold) / down)), 0.0
        return 0.0, 0.0

    def _sm_play_tick(self):
        """One frame of a run: sets the speed and charge for the elapsed time, renders a quick frame while moving
        and one sharp frame while standing still, and stops when the run is over or the tab changed.
        """
        import time
        self._sm_play_job = None
        p = self._sm_play
        if not p:
            return
        if self.tab_var.get() != "speed" or not self.b_sm_play.winfo_exists():
            return self.sm_play_stop()
        sp, ch = self._sm_play_at(time.monotonic() - p["t0"], p["top"])
        sp, ch = round(sp, 1), round(ch, 1)
        still = (sp, ch) == p.get("last")          # holding at the top or resting at 0
        p["last"] = (sp, ch)
        if still:
            if not p.get("sharp"):                  # one full-quality frame while it stands still
                p["sharp"] = True
                self._sm_start_render()
            self._sm_play_job = base.root.after(40, self._sm_play_tick)
            return
        p["sharp"] = False
        self._sm_play_setting = True
        self.sm_speed.set(round(sp, 1))
        self.sm_charge.set(round(ch, 1))
        self._sm_play_setting = False
        self._sm_controls_labels()
        p["n"] += 1
        if self.sm_key == "Texture" and p["n"] % 6 == 0:
            self._sm_part_preview()                 # the highlighted part of the bar texture follows
        self._sm_start_render(fast=True)            # renders now, or the newest value when it's free
        self._sm_play_job = base.root.after(40, self._sm_play_tick)

    def _sm_controls(self):
        """A slider or the Precise box changed: ends a running run, updates the labels and the texture usage view,
        and re-renders the preview.
        """
        if self._sm_play and not self._sm_play_setting:
            self.sm_play_stop(restore=False)        # the user moved a slider: the run ends there
        self._sm_controls_labels()
        if self.sm_key == "Texture":
            self._sm_part_preview()
        self.sm_schedule()

    def sm_refresh(self, render=True):
        """Shows the picked part (name, file, description, details, preview, buttons) and the folder's status
        badge; render=True also re-renders the preview.
        """
        key = self.sm_key
        name, desc = next((n, d) for k, n, d in SPEEDMETER_PARTS if k == key)
        t = self.sm_tex.get(key)
        p = self.sm_path(key)
        self.sm_part_title.config(text=_(name))
        self.sm_part_file.config(text=p.name if p else "")
        self.sm_part_desc.config(text=_(desc))
        self._chips(self.sm_chips, t, p)
        have = len(self.sm_tex)
        if not self.sm_folder:
            self.sm_badge.config(text=_("Folder not found"), fg=C["sub"], bg=C["btn"])
        else:
            sts = [self.sm_status.get(k) for k in self.sm_tex]
            text, fg, bg = BADGES.get(board_status(sts), BADGES[None])
            if have < len(SPEEDMETER_PARTS):
                text, fg, bg = _n("{n} file missing", "{n} files missing", len(SPEEDMETER_PARTS) - have), C["warn"], C["warnbg"]
            self.sm_badge.config(text=text, fg=fg, bg=bg)
        meta = load_default_meta(p) if p and t else None
        set_state([self.b_sm_replace, self.b_sm_export, self.b_sm_setdef], t is not None)
        set_state([self.b_sm_revert], bool(meta))
        self._sm_controls_labels()
        self._sm_part_preview()
        if self.layout == "shop":
            self._sms_refresh()
        if render:
            self.sm_schedule()

    def _sm_controls_labels(self):
        """The text next to the speed and charge sliders."""
        sp, ch, pr = self.sm_speed.get(), self.sm_charge.get(), self.sm_precise.get()
        shown = f"{sp * 10:.0f} mm/s" if pr else f"{sp:.0f} cm/s"
        self.sm_speed_lbl.config(text=_("{sp:5.1f} cm/s  ({shown})", sp=sp, shown=shown))
        self.sm_charge_lbl.config(text=_("{ch:5.1f} cm/s", ch=ch) if ch > sp else _("off (≤ speed)"))

    def _sm_part_preview(self):
        """The picked part's picture with an explanation of how the game uses it (for the bar texture: which
        columns and rows show at the current speed, highlighted).
        """
        key = self.sm_key
        t = self.sm_tex.get(key)
        if t is None:
            self.sm_prev.set_image(None, self.sm_err.get(key, _("Not loaded")))
            self.sm_usage.config(text="")
            return
        img = t.img
        usage = ""
        if key == "Texture":
            img, usage = self._sm_texture_usage(t.img)
        elif key == "BarBeginning":
            usage = f"{t.width}×{t.height}. " + _("Drawn once at the start of the bar; the bar texture "
                                                   "shows through it. Keep the size the same as the original.")
        elif key == "Block":
            usage = f"{t.width}×{t.height}. " + _("Placed every {step} px, so neighbouring blocks overlap by "
                                                   "{overlap} px. The bar texture shows through it; black blocks "
                                                   "beyond the bar show the charge.", step=SM_BLOCK_STEP,
                                                   overlap=t.width - SM_BLOCK_STEP)
        else:
            usage = f"{t.width}×{t.height}. " + _("Drawn under the start of the bar, colored by the bar "
                                                   "texture (always fully lit).")
        self.sm_prev.aspect = img.height / max(1, img.width)
        self.sm_prev.set_image(img)
        self.sm_usage.config(text=usage)

    def _sm_texture_usage(self, img):
        """Darkens the parts of the bar texture the game doesn't show at the current speed."""
        W, H = img.size
        sp = int(round(SM_PX_PER_CMS * self.sm_speed.get()))
        shift = 930.0 if sp >= 3100 else 0.3 * sp
        u0 = 574 - 220 - shift
        u1 = min(590 + sp + 21, SM_SCREEN[0]) - 220 - shift

        def fold(a, b):     # interval after Mirror addressing, clipped to [0, W]
            """An interval of texture columns after the game's mirror addressing, clipped to the texture width.
            """
            if a < 0:
                return 0, max(min(b, W), min(-a, W))
            if b > W:
                return max(0, min(a, 2 * W - b)), W
            return a, b
        lo, hi = fold(u0, u1)
        v0, v1 = 68, min(154, H)       # rows reached by the meter (lower part + mirror)
        dim = Image.alpha_composite(img, Image.new("RGBA", img.size, (10, 10, 12, 175)))
        box = (int(lo), int(v0), int(max(lo + 1, hi)), int(v1))
        dim.paste(img.crop(box), box[:2])
        d = ImageDraw.Draw(dim)
        d.rectangle([box[0], box[1], box[2] - 1, box[3] - 1], outline=_rgb(C["accent"]), width=3)
        usage = f"{W}×{H}. " + _("Highlighted = what the bar shows at {speed:.1f} cm/s (columns {c0}–{c1}, "
                                 "rows {r0}–{r1}). Only the lower rows are used; past the edges the game "
                                 "mirrors the texture. The texture scrolls left by 0.3 px per bar pixel "
                                 "(max 930 px), so higher speeds reveal more of the right side.",
                                 speed=self.sm_speed.get(), c0=int(lo), c1=int(hi), r0=v0, r1=v1)
        return dim, usage

    def sm_schedule(self, *_args):
        """Re-renders the preview soon (90 ms), merging bursts of changes."""
        if self._sm_job:
            base.root.after_cancel(self._sm_job)
        self._sm_job = base.root.after(90, self._sm_start_render)

    def _sm_start_render(self, fast=False):
        """Renders the preview in a background thread with the current textures (unsaved Bar texture / Text results
        included), speed, charge and precise mode. Shows a hint instead when files are missing; while a frame is
        rendering, asks for another one afterwards.
        """
        self._sm_job = None
        if self.tab_var.get() != "speed":
            return
        missing = [k for k, _n, _d in SPEEDMETER_PARTS if k not in self.sm_tex]
        if missing:
            c = self.sm_canvas
            c.delete("all")
            c.configure(height=120)
            c.create_text(max(100, c.winfo_width() // 2), 60, fill=C["muted"], font=F["body"],
                          text=_("Preview needs all five speedmeter files") if self.sm_folder else
                          _("Choose the SpeedMeter folder to see the preview"))
            return
        if self._sm_busy:
            self._sm_again = "fast" if fast else True
            return
        sp, ch, pr = self.sm_speed.get(), self.sm_charge.get(), self.sm_precise.get()
        # during a run the preview keeps the width of the top speed, so it doesn't rescale every frame
        reach = self._sm_play["top"] * 1.15 if self._sm_play else max(sp, ch)
        end = 574 + SM_PX_PER_CMS * reach + 360
        rw = int(min(SM_SCREEN[0], max(1600, math.ceil(end / 400) * 400)))
        region = (0, 1790, rw, 2160)
        tex = {k: t.img for k, t in self.sm_tex.items()}
        tex.update(self._sm_overrides())           # the tools' results (only on screen until written)
        font = self.sm_font
        self._sm_busy, self._sm_result = True, None

        def work():
            """The background job: renders the speedmeter and leaves the image or the error in _sm_result."""
            try:
                self._sm_result = render_speedmeter(tex, sp, ch, pr, region=region, font=font, fast=fast)
            except Exception as e:
                self._sm_result = e
        threading.Thread(target=work, daemon=True).start()
        base.root.after(30, self._sm_poll)

    def _sm_poll(self):
        """Waits for the background frame, shows it (or the error) and starts the next one if asked for."""
        if self._sm_result is None:
            base.root.after(30, self._sm_poll)
            return
        res, self._sm_result = self._sm_result, None
        self._sm_busy = False
        if isinstance(res, Exception):
            self.set_status(_("Preview failed: {res}", res=res))
        else:
            self._sm_last = res
            self._sm_draw()
        if self._sm_again:
            again, self._sm_again = self._sm_again, False
            self._sm_start_render(fast=(again == "fast" and bool(self._sm_play)))

    def _sm_draw(self):
        """Puts the last rendered frame on the canvas over the chosen backdrop, scaled to the canvas width."""
        res = self._sm_last
        if res is None:
            return
        c = self.sm_canvas
        W = max(200, c.winfo_width())
        s = W / res.width
        H = max(40, round(res.height * s))
        mode = self.sm_bg.get()
        if mode == "checker":
            bg = checker(res.width, res.height, 24).copy()
        else:
            bg = Image.new("RGBA", res.size, (160, 140, 110, 255) if mode == "game" else (20, 21, 24, 255))
        bg.alpha_composite(res)
        if self._sm_play:                           # moving frames: a quicker scale-down
            f = max(1, int(bg.width // max(1, W) // 1))
            shown = (bg.reduce(f) if f > 1 else bg).resize((W, H), Image.BILINEAR)
        else:
            shown = bg.resize((W, H), Image.LANCZOS)
        self._sm_photo = ImageTk.PhotoImage(shown)
        if int(float(c.cget("height"))) != H:
            c.configure(height=H)
        c.delete("all")
        c.create_image(0, 0, anchor="nw", image=self._sm_photo)

    def _sm_after_write(self):
        """After a file was written: reloads the folder (statuses, previews)."""
        self.sm_load(self.sm_folder)

    def sm_replace(self, file=None):
        """Replaces the picked part with an image file (asked for, or dropped): opens the Adjust window when the
        size differs, then writes the .xnb (with a .bak backup).
        """
        key = self.sm_key
        t, p = self.sm_tex.get(key), self.sm_path(key)
        if t is None:
            return
        if file is None:
            file = filedialog.askopenfilename(filetypes=[
                (_("Images"), "*.png *.jpg *.jpeg *.bmp *.tga *.gif *.webp"), (_("All files"), "*.*")])
            if not file:
                return
        try:
            new = Image.open(file)
            new.load()
            new = new.convert("RGBA")
        except Exception as e:
            messagebox.showerror(_("Cannot open image"), str(e))
            return
        dlg = AdjustDialog(base.root, new, t.width, t.height,
                           _("Adjust image — {name} ({w}×{h})", name=p.name, w=t.width, h=t.height))
        base.root.wait_window(dlg)
        if dlg.result is None:
            self.set_status(_("Replace cancelled"))
            return
        new = dlg.result
        if new.size != (t.width, t.height):
            new = new.resize((t.width, t.height), Image.LANCZOS)
        self._write(p, t, new, _("Replaced {name} with {file}{extra} (backup: {name}.bak)", name=p.name, file=Path(file).name, extra=""),
                    after=self._sm_after_write)

    def sm_export(self):
        """Saves the picked part as a PNG."""
        t, p = self.sm_tex.get(self.sm_key), self.sm_path(self.sm_key)
        if t is None:
            return
        f = filedialog.asksaveasfilename(defaultextension=".png", initialfile=p.stem + ".png",
                                         filetypes=[("PNG", "*.png")])
        if f:
            t.img.save(f)
            self.set_status(_("Exported {f}", f=f))

    def sm_set_default(self):
        """Saves the picked part as its stock copy (asking first when one exists)."""
        t, p = self.sm_tex.get(self.sm_key), self.sm_path(self.sm_key)
        if t is None:
            return
        old = load_default_meta(p)
        if old and not messagebox.askyesno(
                _("Overwrite default?"), _("A default for {name} was already set on "
                                        "{saved_at}.\n\nReplace it with the current image?", name=p.name, saved_at=old['saved_at'])):
            return
        try:
            meta = set_default(p, t)
            self.cache.put(p, meta["pixel_sha256"])
        except Exception as e:
            messagebox.showerror(_("Cannot set default"), str(e))
            return
        self.sm_load(self.sm_folder)
        self.set_status(_("Default set for {name}", name=p.name))

    def sm_revert(self):
        """Puts the picked part back to its stock copy (after asking)."""
        p = self.sm_path(self.sm_key)
        meta = load_default_meta(p) if p else None
        if not meta or not messagebox.askyesno(
                _("Revert to default"), _("Replace {name} with the default set on "
                                       "{saved_at}?\n\nYour current version will be "
                                       "overwritten.", name=p.name, saved_at=meta['saved_at'])):
            return
        try:
            revert_to_default(p)
        except Exception as e:
            messagebox.showerror(_("Revert failed"), str(e))
            return
        self.sm_load(self.sm_folder)
        self.set_status(_("Reverted {name} to the default from {saved_at}", name=p.name, saved_at=meta['saved_at']))
