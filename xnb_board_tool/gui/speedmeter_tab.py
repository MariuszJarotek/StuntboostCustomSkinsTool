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
from ..defaults import board_status, file_status, load_default_meta, revert_to_default, set_default
from ..boards import strip_image
from ..speedmeter import (
    SM_BLOCK_STEP, SM_PX_PER_CMS, SM_SCREEN, SPEEDMETER_PARTS, find_digit_font,
    find_speedmeter_folder, fix_sinkingship_italic, load_spritefont, render_speedmeter,
)
from ..settings import BADGES, C, _rgb, checker
from .base import F, Preview, button, card, hline, label, set_state
from . import base
from .dialogs import AdjustDialog


class SpeedmeterMixin:
    """The Speedmeter tab: files list, live in-game preview and actions. Mixed into App."""

    # ---------- speedmeter tab: layout ----------
    def _build_speed_sidebar(self, side):
        top = tk.Frame(side, bg=C["side"])
        top.pack(fill="x", padx=14, pady=(12, 8))
        r = tk.Frame(top, bg=C["side"])
        r.pack(fill="x")
        label(r, "Speedmeter files", "bold").pack(side="left")
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
        m = tk.Frame(parent, bg=C["bg"])
        m.pack(fill="both", expand=True, padx=28, pady=22)
        tr = tk.Frame(m, bg=C["bg"])
        tr.pack(fill="x")
        label(tr, "Speedmeter", "h1").pack(side="left")
        self.sm_badge = tk.Label(tr, font=F["smallbold"], padx=10, pady=3)
        self.sm_badge.pack(side="left", padx=14)

        # live preview card
        pc = card(m)
        pc.pack(fill="x", pady=(18, 0))
        head = tk.Frame(pc, bg=C["panel"])
        head.pack(fill="x", padx=16, pady=10)
        label(head, "In-game preview", "h2").pack(side="left")
        label(head, "built from your files with the game's own layout and shader math",
              "small", "muted").pack(side="left", padx=10)
        hline(pc).pack(fill="x")
        self.sm_canvas = tk.Canvas(pc, height=160, bg=C["bg"], highlightthickness=0)
        self.sm_canvas.pack(fill="x", padx=16, pady=(16, 10))
        self.sm_canvas.bind("<Configure>", lambda e: self.sm_schedule())
        ctl = tk.Frame(pc, bg=C["panel"])
        ctl.pack(fill="x", padx=16)

        def slider(parent, lo, hi, var, cmd):
            return tk.Scale(parent, from_=lo, to=hi, orient="horizontal", variable=var,
                            resolution=0.1, showvalue=False, command=cmd, bg=C["panel"],
                            troughcolor=C["btn"], activebackground=C["accent"],
                            highlightthickness=0, bd=0, sliderrelief="flat", sliderlength=16,
                            width=10, length=260)
        self.sm_speed = tk.DoubleVar(value=19.4)
        self.sm_charge = tk.DoubleVar(value=0.0)
        self.sm_precise = tk.BooleanVar(value=True)
        self.sm_bg = tk.StringVar(value="game")
        r1 = tk.Frame(ctl, bg=C["panel"])
        r1.pack(fill="x")
        label(r1, "Speed", "small", "muted", width=7, anchor="w").pack(side="left")
        slider(r1, 0, 120, self.sm_speed, lambda v: self._sm_controls()).pack(side="left")
        self.sm_speed_lbl = label(r1, "", "mono", "sub", width=22, anchor="w")
        self.sm_speed_lbl.pack(side="left", padx=8)
        tk.Checkbutton(r1, text="Precise (MM/S)", variable=self.sm_precise,
                       command=self._sm_controls, bg=C["panel"], fg=C["sub"],
                       activebackground=C["panel"], activeforeground=C["text"],
                       selectcolor=C["bg"], font=F["small"], bd=0, highlightthickness=0,
                       cursor="hand2").pack(side="right")
        r2 = tk.Frame(ctl, bg=C["panel"])
        r2.pack(fill="x", pady=(6, 0))
        label(r2, "Charge", "small", "muted", width=7, anchor="w").pack(side="left")
        slider(r2, 0, 120, self.sm_charge, lambda v: self._sm_controls()).pack(side="left")
        self.sm_charge_lbl = label(r2, "", "mono", "sub", width=22, anchor="w")
        self.sm_charge_lbl.pack(side="left", padx=8)
        for text, val in (("Checker", "checker"), ("Dark", "dark"), ("Game", "game")):
            tk.Radiobutton(r2, text=text, value=val, variable=self.sm_bg,
                           command=self.sm_schedule, indicatoron=False, bg=C["btn"],
                           fg=C["text"], selectcolor=C["selfill"], activebackground=C["btnh"],
                           activeforeground=C["text"], relief="flat", bd=0, highlightthickness=1,
                           highlightbackground=C["btnb"], padx=10, pady=3, font=F["small"],
                           cursor="hand2").pack(side="right", padx=(4, 0))
        label(r2, "Background", "small", "muted").pack(side="right", padx=(0, 6))
        self.sm_note = label(pc, "", "small", "muted", anchor="w", justify="left")
        self.sm_note.pack(fill="x", padx=16, pady=(8, 14))

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
        self.b_sm_replace = button(act, "↑  Replace image…", lambda: self.sm_replace(), "primary")
        self.b_sm_replace.pack(side="left")
        self.b_sm_export = button(act, "Export PNG…", self.sm_export)
        self.b_sm_export.pack(side="left", padx=(8, 0))
        self.b_sm_revert = button(act, "Revert to default", self.sm_revert)
        self.b_sm_revert.pack(side="left", padx=(8, 0))
        self.b_sm_setdef = button(act, "Set current as default", self.sm_set_default, "ghost")
        self.b_sm_setdef.pack(side="right")

    def sm_path(self, key):
        return self.sm_folder / f"{key}.xnb" if self.sm_folder else None

    def sm_choose_folder(self):
        d = filedialog.askdirectory(title="Select the SpeedMeter folder (or the game's Content folder)")
        if not d:
            return
        f = find_speedmeter_folder(Path(d))
        if f is None:
            messagebox.showinfo("Speedmeter", "No speedmeter textures (Texture.xnb, Block.xnb, …) "
                                "were found in that folder.\n\nThey are in "
                                "Content\\Textures\\HUD\\SpeedMeter inside the game folder.")
            return
        if self.cache.file is None:
            self.cache.attach(f)
        self.sm_load(f)
        self.set_status(f"Speedmeter files loaded from {f}")

    def sm_load(self, folder):
        self.busy(True)
        try:
            self.sm_folder = folder
            self.sm_tex, self.sm_err, self.sm_status = {}, {}, {}
            for key, _name, _desc in SPEEDMETER_PARTS:
                p = self.sm_path(key)
                if p is None or not p.exists():
                    self.sm_err[key] = "file not found"
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

    def _sm_set_note(self):
        self.sm_note.config(text="Charge = the black blocks ahead of the bar (potential speed). " + (
            "Digits use the game's own font (VeryBigItalicNumeric)." if self.sm_font else
            "Digits use a stand-in font (Content\\Fonts\\SinkingShip\\VeryBigItalicNumeric.xnb not found)."))
        self.sm_folder_lbl.config(text="" if self.sm_folder else
                                  "Not found \u2014 use Change\u2026 in the top bar to pick the "
                                  "SpeedMeter folder (or the game's Content folder).")
        self._fit_path()

    def _sm_row_image(self, key):
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
        self._syncing = True
        self.sm_tree.delete(*self.sm_tree.get_children())
        for key, name, _d in SPEEDMETER_PARTS:
            self.sm_tree.insert("", "end", iid=key, text=f"  {name}", image=self._sm_row_image(key))
        if self.sm_tree.exists(self.sm_key):
            self.sm_tree.selection_set(self.sm_key)
        self._syncing = False
        found = len(self.sm_tex)
        self.sm_count.config(text=f"{found} of {len(SPEEDMETER_PARTS)}")

    def _sm_on_select(self, _e=None):
        if self._syncing:
            return
        s = self.sm_tree.selection()
        if s and s[0] != self.sm_key:
            self.sm_key = s[0]
            self.sm_refresh(render=False)

    def sm_step(self, d):
        keys = [k for k, _n, _d in SPEEDMETER_PARTS]
        j = keys.index(self.sm_key) + d
        if 0 <= j < len(keys):
            self.sm_key = keys[j]
            self._syncing = True
            self.sm_tree.selection_set(self.sm_key)
            self._syncing = False
            self.sm_refresh(render=False)

    def _sm_controls(self):
        sp, ch, pr = self.sm_speed.get(), self.sm_charge.get(), self.sm_precise.get()
        shown = f"{sp * 10:.0f} mm/s" if pr else f"{sp:.0f} cm/s"
        self.sm_speed_lbl.config(text=f"{sp:5.1f} cm/s  ({shown})")
        self.sm_charge_lbl.config(text=f"{ch:5.1f} cm/s" if ch > sp else "off (≤ speed)")
        if self.sm_key == "Texture":
            self._sm_part_preview()
        self.sm_schedule()

    def sm_refresh(self, render=True):
        key = self.sm_key
        name, desc = next((n, d) for k, n, d in SPEEDMETER_PARTS if k == key)
        t = self.sm_tex.get(key)
        p = self.sm_path(key)
        self.sm_part_title.config(text=name)
        self.sm_part_file.config(text=p.name if p else "")
        self.sm_part_desc.config(text=desc)
        self._chips(self.sm_chips, t, p)
        have = len(self.sm_tex)
        if not self.sm_folder:
            self.sm_badge.config(text="Folder not found", fg=C["sub"], bg=C["btn"])
        else:
            sts = [self.sm_status.get(k) for k in self.sm_tex]
            text, fg, bg = BADGES.get(board_status(sts), BADGES[None])
            if have < len(SPEEDMETER_PARTS):
                text, fg, bg = f"{len(SPEEDMETER_PARTS) - have} file(s) missing", C["warn"], C["warnbg"]
            self.sm_badge.config(text=text, fg=fg, bg=bg)
        meta = load_default_meta(p) if p and t else None
        set_state([self.b_sm_replace, self.b_sm_export, self.b_sm_setdef], t is not None)
        set_state([self.b_sm_revert], bool(meta))
        self._sm_controls_labels()
        self._sm_part_preview()
        if render:
            self.sm_schedule()

    def _sm_controls_labels(self):
        sp, ch, pr = self.sm_speed.get(), self.sm_charge.get(), self.sm_precise.get()
        shown = f"{sp * 10:.0f} mm/s" if pr else f"{sp:.0f} cm/s"
        self.sm_speed_lbl.config(text=f"{sp:5.1f} cm/s  ({shown})")
        self.sm_charge_lbl.config(text=f"{ch:5.1f} cm/s" if ch > sp else "off (≤ speed)")

    def _sm_part_preview(self):
        key = self.sm_key
        t = self.sm_tex.get(key)
        if t is None:
            self.sm_prev.set_image(None, self.sm_err.get(key, "Not loaded"))
            self.sm_usage.config(text="")
            return
        img = t.img
        usage = ""
        if key == "Texture":
            img, usage = self._sm_texture_usage(t.img)
        elif key == "BarBeginning":
            usage = (f"{t.width}×{t.height}. Drawn once at the start of the bar; the "
                     "bar texture shows through it. Keep the size the same as the original.")
        elif key == "Block":
            usage = (f"{t.width}×{t.height}. Placed every {SM_BLOCK_STEP} px, so neighbouring "
                     f"blocks overlap by {t.width - SM_BLOCK_STEP} px. The bar texture shows "
                     "through it; black blocks beyond the bar show the charge.")
        else:
            usage = (f"{t.width}×{t.height}. Drawn under the start of the bar, colored by the "
                     "bar texture (always fully lit).")
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
        usage = (f"{W}×{H}. Highlighted = what the bar shows at {self.sm_speed.get():.1f} cm/s "
                 f"(columns {int(lo)}–{int(hi)}, rows {v0}–{v1}). Only the lower rows are "
                 "used; past the edges the game mirrors the texture. The texture scrolls left by "
                 "0.3 px per bar pixel (max 930 px), so higher speeds reveal more of the right side.")
        return dim, usage

    def sm_schedule(self, *_):
        if self._sm_job:
            base.root.after_cancel(self._sm_job)
        self._sm_job = base.root.after(90, self._sm_start_render)

    def _sm_start_render(self):
        self._sm_job = None
        if self.tab_var.get() != "speed":
            return
        missing = [k for k, _n, _d in SPEEDMETER_PARTS if k not in self.sm_tex]
        if missing:
            c = self.sm_canvas
            c.delete("all")
            c.configure(height=120)
            c.create_text(max(100, c.winfo_width() // 2), 60, fill=C["muted"], font=F["body"],
                          text="Preview needs all five speedmeter files" if self.sm_folder else
                          "Choose the SpeedMeter folder to see the preview")
            return
        if self._sm_busy:
            self._sm_again = True
            return
        sp, ch, pr = self.sm_speed.get(), self.sm_charge.get(), self.sm_precise.get()
        end = 574 + SM_PX_PER_CMS * max(sp, ch) + 360
        rw = int(min(SM_SCREEN[0], max(1600, math.ceil(end / 400) * 400)))
        region = (0, 1790, rw, 2160)
        tex = {k: t.img for k, t in self.sm_tex.items()}
        font = self.sm_font
        self._sm_busy, self._sm_result = True, None

        def work():
            try:
                self._sm_result = render_speedmeter(tex, sp, ch, pr, region=region, font=font)
            except Exception as e:
                self._sm_result = e
        threading.Thread(target=work, daemon=True).start()
        base.root.after(30, self._sm_poll)

    def _sm_poll(self):
        if self._sm_result is None:
            base.root.after(30, self._sm_poll)
            return
        res, self._sm_result = self._sm_result, None
        self._sm_busy = False
        if isinstance(res, Exception):
            self.set_status(f"Preview failed: {res}")
        else:
            self._sm_last = res
            self._sm_draw()
        if self._sm_again:
            self._sm_again = False
            self._sm_start_render()

    def _sm_draw(self):
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
        shown = bg.resize((W, H), Image.LANCZOS)
        self._sm_photo = ImageTk.PhotoImage(shown)
        if int(float(c.cget("height"))) != H:
            c.configure(height=H)
        c.delete("all")
        c.create_image(0, 0, anchor="nw", image=self._sm_photo)

    def _sm_after_write(self):
        self.sm_load(self.sm_folder)

    def sm_replace(self, file=None):
        key = self.sm_key
        t, p = self.sm_tex.get(key), self.sm_path(key)
        if t is None:
            return
        if file is None:
            file = filedialog.askopenfilename(filetypes=[
                ("Images", "*.png *.jpg *.jpeg *.bmp *.tga *.gif *.webp"), ("All", "*.*")])
            if not file:
                return
        try:
            new = Image.open(file)
            new.load()
            new = new.convert("RGBA")
        except Exception as e:
            messagebox.showerror("Cannot open image", str(e))
            return
        dlg = AdjustDialog(base.root, new, t.width, t.height,
                           f"Adjust image — {p.name} ({t.width}×{t.height})")
        base.root.wait_window(dlg)
        if dlg.result is None:
            self.set_status("Replace cancelled")
            return
        new = dlg.result
        if new.size != (t.width, t.height):
            new = new.resize((t.width, t.height), Image.LANCZOS)
        self._write(p, t, new, f"Replaced {p.name} with {Path(file).name} (backup: {p.name}.bak)",
                    after=self._sm_after_write)

    def sm_export(self):
        t, p = self.sm_tex.get(self.sm_key), self.sm_path(self.sm_key)
        if t is None:
            return
        f = filedialog.asksaveasfilename(defaultextension=".png", initialfile=p.stem + ".png",
                                         filetypes=[("PNG", "*.png")])
        if f:
            t.img.save(f)
            self.set_status(f"Exported {f}")

    def sm_set_default(self):
        t, p = self.sm_tex.get(self.sm_key), self.sm_path(self.sm_key)
        if t is None:
            return
        old = load_default_meta(p)
        if old and not messagebox.askyesno(
                "Overwrite default?", f"A default for {p.name} was already set on {old['saved_at']}.\n\n"
                                      "Replace it with the current image?"):
            return
        try:
            meta = set_default(p, t)
            self.cache.put(p, meta["pixel_sha256"])
        except Exception as e:
            messagebox.showerror("Cannot set default", str(e))
            return
        self.sm_load(self.sm_folder)
        self.set_status(f"Default set for {p.name}")

    def sm_revert(self):
        p = self.sm_path(self.sm_key)
        meta = load_default_meta(p) if p else None
        if not meta or not messagebox.askyesno(
                "Revert to default", f"Replace {p.name} with the default set on {meta['saved_at']}?\n\n"
                                     "Your current version will be overwritten."):
            return
        try:
            revert_to_default(p)
        except Exception as e:
            messagebox.showerror("Revert failed", str(e))
            return
        self.sm_load(self.sm_folder)
        self.set_status(f"Reverted {p.name} to the default from {meta['saved_at']}")
