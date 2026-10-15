"""Dialog windows: Settings (layout / theme) and Adjust image."""
from __future__ import annotations

import math

from tkinter import colorchooser
import tkinter as tk
from PIL import Image, ImageDraw, ImageTk

from ..boards import to_hex
from ..i18n import LANGS, N_, _, detect
from ..imageops import Adjust, render_adjusted
from ..settings import (C, LAYOUTS, SETTINGS, TEXT_SIZE_NAMES, TEXT_SIZES, THEME_NAMES, THEMES, checker,
                        settings_path, titlebar)
from .base import F, SegButton, Slider, button, label
from . import base


AUTHOR = "Mariusz Jarotek"          # a name: never translated


def credit_lines():
    """The Credits shown in Settings: (text, font, colour) per line. Used by the Settings window and the Skate shop
    Settings page, so both always say the same."""
    from .. import __version__
    return [(_("Designed and created by {name}", name=AUTHOR), "bold", "text"),
            (_("Coded with the help of Claude AI by Anthropic."), "body", "sub"),
            (_("XNB Board Texture Tool {version}", version=__version__), "small", "muted")]


# ---------------- settings dialog ----------------
class SettingsDialog(tk.Toplevel):
    """The Settings window of the Studio, Gallery and Classic layouts (the Skate shop layout has a Settings page
    instead, see shop_settings.py): picture tiles for the layout, theme and text size, the language, and the GPU
    switch. Nothing changes until Apply.
    """
    def __init__(self, master, app):
        """Builds the window (hidden while it is built, then centred over `master` and made modal). `app` is the
        App whose apply_settings() Apply calls.
        """
        super().__init__(master, bg=C["panel"])
        self.withdraw()
        self.app = app
        self.title(_("Settings"))
        self.transient(master)
        self.resizable(False, False)
        self.layout = tk.StringVar(value=SETTINGS.get("layout", "studio"))
        self.theme = tk.StringVar(value=SETTINGS.get("theme", "dark"))
        self.gpu = tk.BooleanVar(value=bool(SETTINGS.get("gpu3d", True)))
        self.lang = tk.StringVar(value=SETTINGS.get("language", "auto"))
        self.size = tk.StringVar(value=SETTINGS.get("text_size", "balanced"))
        body = tk.Frame(self, bg=C["panel"])
        body.pack(padx=22, pady=18)
        label(body, _("Settings"), "title").pack(anchor="w")
        label(body, _("Layout"), "h2").pack(anchor="w", pady=(16, 8))
        row = tk.Frame(body, bg=C["panel"])
        row.pack(fill="x")
        self.tiles = {}
        for key, (name, desc) in LAYOUTS.items():
            self._tile(row, self.layout, key, name, desc, self._draw_layout)
        label(body, _("Theme"), "h2").pack(anchor="w", pady=(18, 8))
        row2 = tk.Frame(body, bg=C["panel"])
        row2.pack(fill="x")
        for key, name in THEME_NAMES.items():
            self._tile(row2, self.theme, key, name, "", self._draw_theme, w=120, h=56)
        label(body, _("Text size"), "h2").pack(anchor="w", pady=(18, 8))
        row3 = tk.Frame(body, bg=C["panel"])
        row3.pack(fill="x")
        for key, name in TEXT_SIZE_NAMES.items():
            self._tile(row3, self.size, key, name, "", self._draw_size, w=120, h=56)
        label(body, _("Language"), "h2").pack(anchor="w", pady=(18, 8))
        lrow = tk.Frame(body, bg=C["bg"], highlightthickness=1, highlightbackground=C["border"])
        lrow.pack(anchor="w")
        auto = dict(LANGS).get(detect(), "English")
        for code, name in (("auto", _("Automatic ({language})", language=auto)),) + LANGS:
            SegButton(lrow, text=name, value=code, variable=self.lang, indicatoron=False,
                           bg=C["bg"], fg=C["text"], selectcolor=C["selfill"], activebackground=C["btnh"],
                           activeforeground=C["text"], relief="flat", bd=0, highlightthickness=0,
                           padx=12, pady=4, font=F["smallbold"], cursor="hand2").pack(side="left", padx=1, pady=1)
        label(body, _("Automatic follows the Windows display language."), "small", "muted",
              anchor="w").pack(anchor="w", pady=(4, 0))
        label(body, _("3D preview"), "h2").pack(anchor="w", pady=(18, 6))
        tk.Checkbutton(body, text=_("Draw the 3D board on the graphics card (GPU) - faster "
                                    "and sharper while turning"),
                       variable=self.gpu, bg=C["panel"], fg=C["text"], activebackground=C["panel"],
                       activeforeground=C["text"], selectcolor=C["bg"], font=F["body"], bd=0,
                       highlightthickness=0, cursor="hand2", anchor="w").pack(anchor="w")
        from ..board3d import gpu_status
        label(body, _("Now: {status}", status=gpu_status()[1]) + "\n"
              + _("The graphics driver needs some extra memory while loaded. If the 3D view looks wrong "
                  "or the tool crashes, untick this."), "small", "muted",
              justify="left", wraplength=520, anchor="w").pack(anchor="w", pady=(4, 0))
        label(body, _("Saved in {path}", path=settings_path()), "small", "muted").pack(anchor="w", pady=(16, 0))
        label(body, _("Credits"), "h2").pack(anchor="w", pady=(18, 6))
        for text, font, fg in credit_lines():
            label(body, text, font, fg).pack(anchor="w")
        btns = tk.Frame(body, bg=C["panel"])
        btns.pack(fill="x", pady=(16, 0))
        button(btns, _("Apply"), self._apply, "primary").pack(side="right")
        button(btns, _("Cancel"), self.destroy).pack(side="right", padx=(0, 8))
        self.bind("<Escape>", lambda e: self.destroy())
        self.bind("<Return>", lambda e: self._apply())
        self._refresh()
        self.update_idletasks()
        x = master.winfo_rootx() + (master.winfo_width() - self.winfo_reqwidth()) // 2
        y = master.winfo_rooty() + (master.winfo_height() - self.winfo_reqheight()) // 3
        self.geometry(f"+{max(0, x)}+{max(0, y)}")
        self.deiconify()
        titlebar(self, C["dark"])
        self.grab_set()
        self.focus_set()

    def _tile(self, parent, var, key, name, desc, draw, w=170, h=96):
        """A clickable picture tile: `draw(cv, key, w, h)` paints the picture, then the name and an optional
        description; clicking selects `key` in `var`.
        """
        f = tk.Frame(parent, bg=C["panel"], highlightthickness=2, highlightbackground=C["border"],
                     cursor="hand2")
        f.pack(side="left", padx=(0, 10), anchor="n")
        cv = tk.Canvas(f, width=w, height=h, bg=C["bg"], highlightthickness=0)
        cv.pack(padx=8, pady=(8, 6))
        draw(cv, key, w, h)
        label(f, _(name), "bold").pack(anchor="w", padx=8)
        parts = [f, cv]
        if desc:
            d = label(f, _(desc), "small", "muted", justify="left", wraplength=w, anchor="w")

            d.pack(anchor="w", padx=8, pady=(2, 8))
            parts.append(d)
        else:
            tk.Frame(f, bg=C["panel"], height=6).pack()
        for wdg in parts + list(f.winfo_children()):
            wdg.bind("<Button-1>", lambda e, v=var, k=key: (v.set(k), self._refresh()))
        self.tiles[(id(var), key)] = (f, var, key)

    def _refresh(self):
        """Outlines the selected tile of each group in the accent colour."""
        for f, var, key in self.tiles.values():
            f.config(highlightbackground=C["accent"] if var.get() == key else C["border"])

    def _draw_layout(self, cv, key, w, h):
        """Draws a small sketch of a layout (used by the tiles and by the Settings page). Uses no instance data, so
        it can be called as SettingsDialog._draw_layout(None, cv, key, w, h).
        """
        P, B, A = C["panel"], C["btnb"], C["accent"]
        if key == "studio":
            cv.create_rectangle(4, 4, 34, h - 4, fill=P, outline="")
            cv.create_rectangle(40, 4, w - 50, h - 30, fill=P, outline="")
            cv.create_oval(60, 26, w - 70, 48, outline=A, width=3)
            cv.create_rectangle(40, h - 24, w - 50, h - 4, fill=B, outline="")
            cv.create_rectangle(w - 44, 4, w - 4, h - 4, fill=P, outline="")
        elif key == "shop":
            ink = THEMES["concrete"]["ink"]
            cv.create_rectangle(0, 0, w, h, fill=THEMES["concrete"]["bg"], outline="")
            cv.create_rectangle(4, 4, w - 4, 8, fill=ink, outline="")
            cols = ("#8f7cf0", "#ff6a2b", "#1f9e8a", "#ffd23f", "#2b6cff", "#d82020", "#7bd389")
            for k in range(7):
                x = 10 + k * 22
                cv.create_line(x + 6, 8, x + 6, 14, fill=ink)
                cv.create_rectangle(x, 14, x + 12, h - 22, fill=cols[k], outline=ink,
                                    width=2 if k == 3 else 1)
                cv.create_rectangle(x - 1, h - 18, x + 13, h - 10, fill=A if k == 3 else ink, outline="")
            cv.create_rectangle(4, h - 6, w - 4, h - 2, fill=ink, outline="")
        elif key == "gallery":
            for r in range(3):
                for c in range(3):
                    x, y = 4 + c * 38, 4 + r * 30
                    cv.create_rectangle(x, y, x + 34, y + 26, fill=P, outline=A if (r, c) == (1, 1) else "")
            cv.create_rectangle(w - 50, 4, w - 4, h - 4, fill=P, outline="")
        else:
            cv.create_rectangle(4, 4, 34, h - 4, fill=P, outline="")
            cv.create_rectangle(40, 4, 100, 40, fill=P, outline="")
            cv.create_rectangle(104, 4, w - 4, 40, fill=P, outline="")
            cv.create_rectangle(40, 44, w - 4, 66, fill=B, outline="")
            cv.create_rectangle(40, 70, 103, h - 4, fill=P, outline="")
            cv.create_rectangle(107, 70, w - 4, h - 4, fill=P, outline="")

    def _draw_size(self, cv, key, w, h):
        """'Aa' and a line of body text at that scale's sizes."""
        t = TEXT_SIZES[key]
        fam = base.FAMILIES
        cv.create_rectangle(0, 0, w, h, fill=C["bg"], outline="")
        cv.create_text(10, h / 2 - 4, text="Aa", anchor="w", fill=C["text"],
                       font=(fam.get("cond", "TkDefaultFont"), t["section"], "bold"))
        cv.create_text(54, h / 2 - 6, text=_("Text"), anchor="w", fill=C["text"],
                       font=(fam.get("sans", "TkDefaultFont"), t["body"]))
        cv.create_text(54, h / 2 + 12, text=_("Hint"), anchor="w", fill=C["muted"],
                       font=(fam.get("sans", "TkDefaultFont"), t["cap"]))

    def _draw_theme(self, cv, key, w, h):
        """Draws a small sample of a theme's colours (also called with self=None by the Settings page)."""
        t = THEMES[key]
        cv.create_rectangle(0, 0, w, h, fill=t["bg"], outline="")
        cv.create_rectangle(8, 8, w - 8, h - 8, fill=t["panel"], outline=t["border"])
        cv.create_rectangle(16, 16, 60, 26, fill=t["text"], outline="")
        cv.create_rectangle(16, 32, w - 40, 38, fill=t["muted"], outline="")
        cv.create_rectangle(w - 34, 16, w - 16, 38, fill=t["accent"], outline="")

    def _apply(self):
        """Closes the window and hands the chosen layout, theme, GPU, language and text size to the App."""
        layout, theme, gpu = self.layout.get(), self.theme.get(), bool(self.gpu.get())
        self.grab_release()
        self.destroy()
        self.app.apply_settings(layout, theme, gpu, self.lang.get(), self.size.get())


# ---------------- adjust-image dialog ----------------
class AdjustDialog(tk.Toplevel):
    """Position / zoom / rotate / flip a new image before it replaces a texture.
    After wait_window(), .result is the final W x H image, or None if cancelled."""
    M = 36   # margin (preview px) that shows the parts that will be cut off

    def __init__(self, master, img, W, H, title):
        """Builds the Adjust window for placing `img` on a W x H texture: a preview with the cut-off parts shaded,
        fit mode, zoom, rotation, flips, a fill colour, and Apply / Cancel. The preview is scaled to fit the
        screen.
        """
        super().__init__(master, bg=C["panel"])
        self.withdraw()
        self.title(title)
        self.transient(master)
        self.resizable(False, False)
        self.src, self.W, self.H = img.convert("RGBA"), W, H
        self.adj = Adjust()
        self.result = None
        self._cache, self._photo, self._drag, self._job = {}, None, None, None
        self._quiet = False
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        maxw = min(1100, int(sw * 0.8)) - 2 * self.M
        maxh = min(460, int(sh * 0.45))
        self.ps = min(maxw / W, maxh / H)
        self.pw, self.ph = max(1, round(W * self.ps)), max(1, round(H * self.ps))

        body = tk.Frame(self, bg=C["panel"])
        body.pack(padx=20, pady=16)
        top = tk.Frame(body, bg=C["panel"])
        top.pack(fill="x")
        label(top, _("Adjust image"), "title").pack(side="left")
        self.info = label(top, "", "small", "muted")
        self.info.pack(side="right")
        self.canvas = tk.Canvas(body, width=self.pw + 2 * self.M, height=self.ph + 2 * self.M,
                                bg=C["bg"], highlightthickness=0, cursor="fleur")
        self.canvas.pack(pady=(10, 4))
        label(body, _("Drag to move  ·  scroll to zoom  ·  double-click to reset  ·  arrows "
                      "nudge (Shift = 10 px)  ·  dimmed area will be cut off"),
              "small", "muted").pack(anchor="w")

        def seg(parent, text, value, var, cmd):
            """A segment button of the dialog's segmented controls."""
            return SegButton(parent, text=text, value=value, variable=var, command=cmd,
                                  indicatoron=False, bg=C["btn"], fg=C["text"],
                                  selectcolor=C["selfill"], activebackground=C["btnh"],
                                  activeforeground=C["text"], relief="flat", bd=0,
                                  highlightthickness=1, highlightbackground=C["btnb"],
                                  padx=12, pady=6, font=F["body"], cursor="hand2")

        def toggle(parent, text, var, cmd):
            """An on/off segment button (the flips)."""
            return SegButton(parent, text=text, variable=var, command=cmd,
                                  indicatoron=False, bg=C["btn"], fg=C["text"],
                                  selectcolor=C["selfill"], activebackground=C["btnh"],
                                  activeforeground=C["text"], relief="flat", bd=0,
                                  highlightthickness=1, highlightbackground=C["btnb"],
                                  padx=12, pady=6, font=F["body"], cursor="hand2")

        def slider(parent, lo, hi, cmd, length=220):
            """A slider in the dialog's style, whole steps."""
            return Slider(parent, lo, hi, command=cmd, resolution=1, length=length, bg=C["panel"])

        # row 1: size mode + zoom
        r1 = tk.Frame(body, bg=C["panel"])
        r1.pack(fill="x", pady=(14, 0))
        label(r1, _("Size"), "small", "muted", width=7, anchor="w").pack(side="left")
        self.mode_var = tk.StringVar(value="fill")
        for text, val in ((N_("Fill"), "fill"), (N_("Fit"), "fit"), (N_("Stretch"), "stretch")):
            seg(r1, _(text), val, self.mode_var, self._on_mode).pack(side="left", padx=(0, 4))
        self.zoom_lbl = label(r1, "100%", "mono", "sub", width=6, anchor="e")
        self.zoom_lbl.pack(side="right")
        self.zoom_scale = slider(r1, -200, 300, self._on_zoom_slider)
        self.zoom_scale.pack(side="right", padx=(8, 6))
        label(r1, _("Zoom"), "small", "muted").pack(side="right")

        # row 2: rotate + flip
        r2 = tk.Frame(body, bg=C["panel"])
        r2.pack(fill="x", pady=(10, 0))
        label(r2, _("Rotate"), "small", "muted", width=7, anchor="w").pack(side="left")
        button(r2, "⟲ 90°", lambda: self._rot90(-90)).pack(side="left")
        button(r2, "⟳ 90°", lambda: self._rot90(90)).pack(side="left", padx=(4, 0))
        self.fh_var, self.fv_var = tk.BooleanVar(), tk.BooleanVar()
        toggle(r2, _("Flip") + " ↔", self.fh_var, self._on_flip).pack(side="left", padx=(16, 4))
        toggle(r2, _("Flip") + " ↕", self.fv_var, self._on_flip).pack(side="left")
        self.angle_lbl = label(r2, "0°", "mono", "sub", width=6, anchor="e")
        self.angle_lbl.pack(side="right")
        self.angle_scale = slider(r2, -180, 180, self._on_angle_slider)
        self.angle_scale.pack(side="right", padx=(8, 6))
        label(r2, _("Angle"), "small", "muted").pack(side="right")

        # row 3: background + buttons
        r3 = tk.Frame(body, bg=C["panel"])
        r3.pack(fill="x", pady=(16, 0))
        label(r3, _("Empty area"), "small", "muted").pack(side="left", padx=(0, 8))
        self.bg_sw = tk.Canvas(r3, width=26, height=26, highlightthickness=1,
                               highlightbackground=C["btnb"], bg=C["btn"], cursor="hand2")
        self.bg_sw.pack(side="left")
        self.bg_sw.bind("<Button-1>", lambda e: self._pick_bg())
        button(r3, _("Color…"), self._pick_bg, "ghost").pack(side="left", padx=(6, 0))
        button(r3, _("Transparent"), self._clear_bg, "ghost").pack(side="left")
        button(r3, _("Apply"), self._apply, "primary").pack(side="right")
        button(r3, _("Cancel"), self._cancel).pack(side="right", padx=(0, 8))
        button(r3, _("Reset"), self._reset, "ghost").pack(side="right", padx=(0, 8))

        c = self.canvas
        c.bind("<ButtonPress-1>", self._press)
        c.bind("<B1-Motion>", self._motion)
        c.bind("<ButtonRelease-1>", lambda e: setattr(self, "_drag", None))
        c.bind("<Double-Button-1>", lambda e: self._reset_view())
        c.bind("<MouseWheel>", lambda e: self._wheel(e, 1 if e.delta > 0 else -1))
        c.bind("<Button-4>", lambda e: self._wheel(e, 1))
        c.bind("<Button-5>", lambda e: self._wheel(e, -1))
        for key, d in (("Left", (-1, 0)), ("Right", (1, 0)), ("Up", (0, -1)), ("Down", (0, 1))):
            self.bind(f"<{key}>", lambda e, d=d: self._nudge(*d, 1))
            self.bind(f"<Shift-{key}>", lambda e, d=d: self._nudge(*d, 10))
        self.bind("<plus>", lambda e: self._zoom_by(1.1))
        self.bind("<equal>", lambda e: self._zoom_by(1.1))
        self.bind("<minus>", lambda e: self._zoom_by(1 / 1.1))
        self.bind("<r>", lambda e: self._rot90(90))
        self.bind("<Return>", lambda e: self._apply())
        self.bind("<Escape>", lambda e: self._cancel())
        self.protocol("WM_DELETE_WINDOW", self._cancel)

        self._sync()
        self.update_idletasks()
        x = master.winfo_rootx() + (master.winfo_width() - self.winfo_reqwidth()) // 2
        y = master.winfo_rooty() + (master.winfo_height() - self.winfo_reqheight()) // 3
        self.geometry(f"+{max(0, x)}+{max(0, y)}")
        self.deiconify()
        titlebar(self, C["dark"])
        self.grab_set()
        self.focus_set()

    # --- state helpers ---
    def _center(self):
        """Where the image's centre is on the output (the middle when not moved)."""
        a = self.adj
        return (self.W / 2 if a.cx is None else a.cx, self.H / 2 if a.cy is None else a.cy)

    def _sync(self):
        """Push self.adj into the widgets (without feedback loops) and redraw."""
        a = self.adj
        self._quiet = True
        self.mode_var.set(a.mode)
        self.zoom_scale.set(round(math.log2(max(1e-6, a.zoom)) * 100))
        self.angle_scale.set(round(a.angle))
        self.fh_var.set(a.flip_h)
        self.fv_var.set(a.flip_v)
        self._quiet = False
        self.zoom_lbl.config(text=f"{a.zoom * 100:.0f}%")
        self.angle_lbl.config(text=f"{a.angle:.0f}°")
        self.bg_sw.delete("all")
        if a.bg is None:
            for i in range(0, 26, 6):
                for j in range(0, 26, 6):
                    if (i + j) // 6 % 2:
                        self.bg_sw.create_rectangle(i, j, i + 6, j + 6, fill=C["btnb"], outline="")
        else:
            self.bg_sw.create_rectangle(0, 0, 27, 27, fill=to_hex(a.bg), outline="")
        self._schedule()

    def _schedule(self):
        """Redraws soon (15 ms), merging several changes into one render."""
        if self._job is None:
            self._job = self.after(15, self._render)

    def _render(self):
        """Renders the preview: the image as it will be placed, over a checkerboard, with everything outside the
        texture veiled and the texture's edge outlined.
        """
        self._job = None
        out = render_adjusted(self.src, self.W, self.H, self.adj, ps=self.ps, margin=self.M,
                              resample=Image.BILINEAR, cache=self._cache)
        Wp, Hp = out.size
        M = self.M
        shown = checker(Wp, Hp).copy()
        shown.alpha_composite(out)
        veil = Image.new("RGBA", (Wp, Hp), (14, 15, 18, 175))
        ImageDraw.Draw(veil).rectangle([M, M, M + self.pw - 1, M + self.ph - 1], fill=(0, 0, 0, 0))
        shown.alpha_composite(veil)
        self._photo = ImageTk.PhotoImage(shown)
        c = self.canvas
        c.delete("all")
        c.create_image(0, 0, anchor="nw", image=self._photo)
        c.create_rectangle(M - 1, M - 1, M + self.pw, M + self.ph, outline=C["accent"])
        sx, sy = self.src.size
        self.info.config(text=_("image {sx}×{sy}  →  output {W}×{H}", sx=sx, sy=sy, W=self.W, H=self.H))

    # --- events ---
    def _on_mode(self):
        """Fit mode changed (fill / fit / stretch): resets zoom and position."""
        if self._quiet:
            return
        self.adj.mode = self.mode_var.get()
        self.adj.zoom, self.adj.cx, self.adj.cy = 1.0, None, None
        self._sync()

    def _on_zoom_slider(self, v):
        """Zoom slider moved (the slider is logarithmic: 100 = twice as big)."""
        if self._quiet:
            return
        self._set_zoom(2 ** (float(v) / 100))

    def _set_zoom(self, z, anchor=None):
        """Sets the zoom (0.25-8); with an anchor point the image zooms around that point instead of its centre.
        """
        z = max(0.25, min(8.0, z))
        a = self.adj
        if anchor is not None:
            cx, cy = self._center()
            f = z / a.zoom
            a.cx, a.cy = anchor[0] - (anchor[0] - cx) * f, anchor[1] - (anchor[1] - cy) * f
        a.zoom = z
        self._sync()

    def _zoom_by(self, f):
        """Zooms by a factor (the + / - buttons and keys)."""
        self._set_zoom(self.adj.zoom * f)

    def _wheel(self, e, d):
        """Mouse wheel over the preview: zooms around the point under the pointer."""
        anchor = ((e.x - self.M) / self.ps, (e.y - self.M) / self.ps)
        self._set_zoom(self.adj.zoom * (1.1 if d > 0 else 1 / 1.1), anchor)

    def _on_angle_slider(self, v):
        """Rotation slider moved."""
        if self._quiet:
            return
        self.adj.angle = float(v)
        self._sync()

    def _rot90(self, d):
        """Rotates by d degrees (the 90 degree buttons), keeping the angle within -180..180."""
        self.adj.angle = (self.adj.angle + d + 180) % 360 - 180
        self._sync()

    def _on_flip(self):
        """A flip toggle changed."""
        if self._quiet:
            return
        self.adj.flip_h, self.adj.flip_v = self.fh_var.get(), self.fv_var.get()
        self._sync()

    def _press(self, e):
        """Mouse pressed on the preview: starts dragging the image."""
        self.canvas.focus_set()
        self._drag = (e.x, e.y) + self._center()

    def _motion(self, e):
        """Mouse dragged: moves the image with it."""
        if not self._drag:
            return
        x0, y0, cx0, cy0 = self._drag
        self.adj.cx = cx0 + (e.x - x0) / self.ps
        self.adj.cy = cy0 + (e.y - y0) / self.ps
        self._schedule()

    def _nudge(self, dx, dy, step):
        """Arrow keys: moves the image by `step` output pixels."""
        cx, cy = self._center()
        self.adj.cx, self.adj.cy = cx + dx * step, cy + dy * step
        self._schedule()

    def _pick_bg(self):
        """Asks for a colour to fill the area the image does not cover."""
        cur = to_hex(self.adj.bg) if self.adj.bg else "#000000"
        rgb, _h = colorchooser.askcolor(color=cur, parent=self, title=_("Color for the empty area"))
        if rgb:
            self.adj.bg = tuple(int(round(v)) for v in rgb[:3])
            self._sync()

    def _clear_bg(self):
        """Makes the uncovered area transparent again."""
        self.adj.bg = None
        self._sync()

    def _reset_view(self):
        """Back to zoom 1 and centred (keeps rotation and flips)."""
        a = self.adj
        a.zoom, a.cx, a.cy = 1.0, None, None
        self._sync()

    def _reset(self):
        """Back to the default placement (keeps the fill colour)."""
        self.adj = Adjust(bg=self.adj.bg)
        self._sync()

    def _apply(self):
        """Renders the final image at full size into .result and closes."""
        self.config(cursor="watch")
        self.update_idletasks()
        try:
            self.result = render_adjusted(self.src, self.W, self.H, self.adj)
        finally:
            self.config(cursor="")
        self.grab_release()
        self.destroy()

    def _cancel(self):
        """Closes with .result = None (the caller then changes nothing)."""
        self.result = None
        self.grab_release()
        self.destroy()
