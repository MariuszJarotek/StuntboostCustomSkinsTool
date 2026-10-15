"""The Speedmeter's two editing tools, built the same way for every layout:

- Bar texture (Texture.xnb): "Recolor mine" keeps the texture and gives it new colors, "Make new"
  draws a new texture from a style.
- Text maker (CMS.xnb / MMS.xnb): new unit text.

Both only show on screen (the in-game preview, Play run included) until they are written. In the
Skate shop layout they are sheets of the Speedmeter bench and the bench's ink bar writes them; in the
other layouts each is a card with its own Apply button. The panels are narrow (they fit the shop's
sheet) and simply grow wider in the cards."""
from __future__ import annotations

from pathlib import Path

from tkinter import filedialog, messagebox
import tkinter as tk
from PIL import Image, ImageTk

from ..i18n import N_, _
from ..hud_generate import DEFAULT as GEN_DEFAULT, STYLES as GEN_STYLES, generate, style_swatch
from ..hud_text import DEFAULT as TX_DEFAULT, QUICK_TEXTS, available_fonts, make_text
from ..hud_recolor import PRESETS, deck_colors, gradient_swatch, is_identity, recolor
from ..settings import C, _rgb
from .base import F, Flow, Preview, SegButton, Slider, button, card, hline, label, set_state
from . import base

RC_DEFAULT = {"method": "shift", "hue": 0.0, "sat": 1.0, "bright": 0.0, "preset": "original",
              "stops": [(96, 8, 0), (236, 64, 12), (255, 214, 72)], "fill": "shade"}

GEN_COLOR_NAMES = {
    "solid": (N_("Color"),), "gradient": (N_("Slow"), N_("Middle"), N_("Fast")),
    "zones": (N_("Zone 1"), N_("Zone 2"), N_("Zone 3")), "stripes": (N_("Base"), N_("Pattern")),
    "checker": (N_("Base"), N_("Pattern")), "carbon": (N_("Base"), N_("Pattern")),
}

SLIDER_LEN = 120
LBL_W = 14


class SpeedToolsMixin:
    """Bar texture + Text maker for the Speedmeter tab. Mixed into App."""

    # ------------------------------------------------------------------ state
    def _tools_init(self):
        """State that outlives a rebuild of the window (layout / theme / language changes)."""
        if hasattr(self, "sm_rc"):
            return
        self.sm_rc = dict(RC_DEFAULT)
        self.sm_gen = {**GEN_DEFAULT, "colors": list(GEN_DEFAULT["colors"])}
        self.sm_tx = dict(TX_DEFAULT)
        fonts = available_fonts()
        if fonts and self.sm_tx["font"] not in [k for k, _l in fonts]:
            self.sm_tx["font"] = fonts[0][0]
        self.sm_bt_mode = "recolor"
        self.sm_bt_on = False             # the bar texture tool is in use (its result shows on screen)
        self.sm_tx_on = False             # the text maker is in use …
        self._tx_touched = False          # … and something in it was changed
        self._bt_img = None
        self._tx_imgs = {}
        self._tx_focus = "cms"

    @staticmethod
    def _sm_seg(parent, text, val, var, cmd):
        """A small segment button for the tools' segmented controls."""
        return SegButton(parent, text=text, value=val, variable=var, command=cmd, indicatoron=False,
                              bg=C["btn"], fg=C["text"], selectcolor=C["selfill"], activebackground=C["btnh"],
                              activeforeground=C["text"], relief="flat", bd=0, highlightthickness=1,
                              highlightbackground=C["btnb"], padx=10, pady=3, font=F["small"], cursor="hand2")

    def _slider_row(self, parent, name, lo, hi, res, var, cmd):
        """A row with a caption, a slider and a value label (the label is filled by the caller via row._val)."""
        P = C["panel"]
        fr = tk.Frame(parent, bg=P)
        cap = label(fr, _(name), "small", "muted", width=LBL_W, anchor="w", bg=P)
        cap.pack(side="left")
        val = label(fr, "", "mono", "sub", width=9, anchor="w", bg=P)
        val.pack(side="right", padx=(6, 0))
        Slider(fr, lo, hi, variable=var, resolution=res, command=lambda _v: cmd(), length=SLIDER_LEN,
               bg=P).pack(side="left", fill="x", expand=True)
        fr._cap, fr._val = cap, val
        return fr

    def _chip(self, parent, key, cmd):
        """An empty picture chip (preset / style); clicking it calls cmd(key). Drawn by _draw_chip."""
        cv = tk.Canvas(parent, width=78, height=40, bg=C["panel"], highlightthickness=0, cursor="hand2")
        cv.bind("<Button-1>", lambda e: cmd(key))
        return cv

    def _draw_chip(self, cv, img, name, on, enabled=True, store=None, key=None):
        """Draws a chip: its swatch image, its name, outlined when selected, greyed when not usable. The PhotoImage
        is kept in store[key].
        """
        cv.delete("all")
        ph = ImageTk.PhotoImage(img)
        store[key] = ph
        cv.create_rectangle(1, 1, 76, 38, outline=C["accent"] if on else C["border"], width=2 if on else 1,
                            fill=C["selfill"] if on else C["panel"])
        cv.create_image(7, 6, anchor="nw", image=ph)
        cv.create_text(39, 29, text=_(name), font=F["small"], fill=C["text"] if enabled else C["dis"])

    def _wrap_label(self, parent, text, font="small", fg="sub"):
        """A label on the panel that wraps its text to the width it gets."""
        lb = label(parent, text, font, fg, anchor="w", justify="left", bg=C["panel"])
        lb.bind("<Configure>", lambda e: lb.config(wraplength=max(120, e.width - 4)))
        return lb

    # ------------------------------------------------------------------ bar texture: building
    def _bt_build(self, parent, shop):
        """The Bar texture panel: mode switch, the mode's controls, before / after."""
        self._tools_init()
        P = C["panel"]
        self._bt_photos = {}
        top = tk.Frame(parent, bg=P)
        top.pack(fill="x")
        self._bt_mode_var = tk.StringVar(value=self.sm_bt_mode)
        # the two ways to make a bar texture, as two big tabs side by side
        top.columnconfigure(0, weight=1, uniform="btmode")
        top.columnconfigure(1, weight=1, uniform="btmode")
        for col, (text, val) in enumerate(((_("Recolor mine"), "recolor"), (_("Make new"), "make"))):
            SegButton(top, text=text.upper(), value=val, variable=self._bt_mode_var, command=self._bt_mode_changed,
                      bg=C["btn"], fg=C["text"], selectcolor=C["selfill"], activebackground=C["btnh"],
                      highlightthickness=2, highlightbackground=C["btnb"], padx=10, pady=7,
                      font=F["displaysm"], cursor="hand2").grid(row=0, column=col, sticky="ew",
                                                                padx=(0 if col == 0 else 4, 0))
        self._bt_mode_hint = self._wrap_label(parent, "")
        self._bt_mode_hint.pack(fill="x", pady=(6, 4))

        # -- recolor mine --
        rcf = self._bt_rc_frame = tk.Frame(parent, bg=P)
        label(rcf, _("Presets"), "smallbold", "text", anchor="w", bg=P).pack(fill="x", pady=(8, 4))
        row = Flow(rcf, gap=6, vgap=6, bg=P)
        row.pack(fill="x")
        self._rc_chips = {}
        for key, name, stops, _fill in [("original", N_("Original"), None, None)] + PRESETS + \
                [("deck", N_("From deck"), None, None)]:
            cv = row.add(self._chip(row, key, self.sm_rc_preset))
            self._rc_chips[key] = (cv, name, stops)
        r = tk.Frame(rcf, bg=P)
        r.pack(fill="x", pady=(12, 0))
        label(r, _("Method"), "small", "muted", width=LBL_W, anchor="w", bg=P).pack(side="left")
        self._rc_method = tk.StringVar(value=self.sm_rc["method"])
        self._sm_seg(r, _("Shift colors"), "shift", self._rc_method, self._rc_method_changed).pack(side="left")
        self._sm_seg(r, _("New colors"), "colors", self._rc_method, self._rc_method_changed).pack(side="left", padx=(4, 0))
        self._rc_method_hint = self._wrap_label(rcf, "", fg="muted")
        self._rc_method_hint.pack(fill="x", pady=(4, 0))
        self._rc_shift = tk.Frame(rcf, bg=P)
        self._rc_vars, self._rc_rows = {}, {}
        for key, name, lo, hi in (("hue", N_("Hue"), -180, 180), ("sat", N_("Saturation"), 0, 200),
                                  ("bright", N_("Brightness"), -100, 100)):
            v = tk.DoubleVar()
            fr = self._slider_row(self._rc_shift, name, lo, hi, 1, v, self._rc_slid)
            fr.pack(fill="x", pady=(6, 0))
            self._rc_vars[key], self._rc_rows[key] = v, fr
        self._rc_colors = tk.Frame(rcf, bg=P)
        r = tk.Frame(self._rc_colors, bg=P)
        r.pack(fill="x", pady=(8, 0))
        label(r, _("Colors"), "small", "muted", width=LBL_W, anchor="w", bg=P).pack(side="left")
        self._rc_stop_btns = []
        for i, name in enumerate((N_("Dark"), N_("Middle"), N_("Light"))):
            f = tk.Frame(r, bg=P)
            f.pack(side="left", padx=(0, 8))
            sw = tk.Label(f, width=3, bg="#000000", relief="flat", bd=0, highlightthickness=1,
                          highlightbackground=C["btnb"], cursor="hand2")
            sw.pack(side="left", ipady=3)
            sw.bind("<Button-1>", lambda e, k=i: self.sm_rc_pick(k))
            label(f, _(name), "small", "sub", bg=P).pack(side="left", padx=(4, 0))
            self._rc_stop_btns.append(sw)
        r = tk.Frame(self._rc_colors, bg=P)
        r.pack(fill="x", pady=(8, 0))
        label(r, _("Fill"), "small", "muted", width=LBL_W, anchor="w", bg=P).pack(side="left")
        self._rc_fill = tk.StringVar(value=self.sm_rc["fill"])
        self._sm_seg(r, _("By shade"), "shade", self._rc_fill, self._rc_fill_changed).pack(side="left")
        self._sm_seg(r, _("Along the bar"), "along", self._rc_fill, self._rc_fill_changed).pack(side="left", padx=(4, 0))
        self._rc_fill_hint = self._wrap_label(self._rc_colors, "", fg="muted")
        self._rc_fill_hint.pack(fill="x", pady=(4, 0))

        # -- make new --
        gf = self._bt_gen_frame = tk.Frame(parent, bg=P)
        label(gf, _("Style"), "smallbold", "text", anchor="w", bg=P).pack(fill="x", pady=(8, 4))
        row = Flow(gf, gap=6, vgap=6, bg=P)
        row.pack(fill="x")
        self._gen_chips = {}
        for key, name, _n, _sz, _h in GEN_STYLES:
            self._gen_chips[key] = (row.add(self._chip(row, key, self.sm_gen_style)), name)
        self._gen_help = self._wrap_label(gf, "", fg="sub")
        self._gen_help.pack(fill="x", pady=(8, 0))
        self._gen_colors_row = tk.Frame(gf, bg=P)
        r = tk.Frame(self._gen_colors_row, bg=P)
        r.pack(fill="x", pady=(8, 0))
        label(r, _("Colors"), "small", "muted", width=LBL_W, anchor="w", bg=P).pack(side="left")
        self._gen_sw = []
        for i in range(3):
            f = tk.Frame(r, bg=P)
            sw = tk.Label(f, width=3, bg="#000000", relief="flat", bd=0, highlightthickness=1,
                          highlightbackground=C["btnb"], cursor="hand2")
            sw.pack(side="left", ipady=3)
            sw.bind("<Button-1>", lambda e, k=i: self.sm_gen_pick(k))
            lb = label(f, "", "small", "sub", bg=P)
            lb.pack(side="left", padx=(4, 0))
            self._gen_sw.append((f, sw, lb))
        self.b_gen_deckcols = button(self._gen_colors_row, _("Colors from deck"), self.sm_gen_deck_colors,
                                     "ghost", small=True)
        self.b_gen_deckcols.pack(anchor="w", pady=(4, 0))
        self._gen_vars, self._gen_rows = {}, {}
        for key, name, lo, hi in (("size", N_("Size"), 10, 160), ("full", N_("Last color at"), 20, 120),
                                  ("zone1", N_("Zone 2 from"), 1, 119), ("zone2", N_("Zone 3 from"), 2, 120)):
            v = tk.DoubleVar()
            fr = self._slider_row(gf, name, lo, hi, 1, v, lambda k=key: self._gen_slid(k))
            self._gen_vars[key], self._gen_rows[key] = v, fr
        self._gen_shine = tk.BooleanVar(value=self.sm_gen["shine"])
        self._gen_shine_cb = tk.Checkbutton(gf, text=_("Shine (a round, lit look)"), variable=self._gen_shine,
                                            command=self._gen_shine_changed, bg=P, fg=C["sub"],
                                            activebackground=P, activeforeground=C["text"], selectcolor=C["bg"],
                                            font=F["small"], bd=0, highlightthickness=0, cursor="hand2")

        # -- before / after --
        st = self._bt_strips = tk.Frame(parent, bg=P)
        st.pack(fill="x", pady=(14, 0))
        self._bt_prev = {}
        for key, name in (("before", N_("Before")), ("after", N_("After"))):
            label(st, _(name), "small", "muted", anchor="w", bg=P).pack(fill="x")
            pv = Preview(st, 86 / 3699, 30)
            pv.pack(fill="x", pady=(2, 6))
            self._bt_prev[key] = pv
        self._bt_sync()

    # ------------------------------------------------------------------ bar texture: syncing
    def _bt_sync(self):
        """Puts the state into the widgets (after a preset, a mode change, a rebuild, …)."""
        f = getattr(self, "_bt_rc_frame", None)
        if f is None or not f.winfo_exists():
            return
        mode = self.sm_bt_mode
        self._bt_mode_var.set(mode)
        if mode == "make":
            self._bt_rc_frame.pack_forget()
            self._bt_gen_frame.pack(fill="x", before=self._bt_strips)
            self._bt_mode_hint.config(text=_("Draws a new texture from a style. Your current texture is not used."))
            self._gen_sync()
        else:
            self._bt_gen_frame.pack_forget()
            self._bt_rc_frame.pack(fill="x", before=self._bt_strips)
            self._bt_mode_hint.config(text=_("Keeps your texture (its light, shade and details) and gives it "
                                             "new colors."))
            self._rc_sync()

    def _bt_mode_changed(self):
        """Recolor mine / Make new switched: shows that mode's controls and renders its result."""
        self.sm_bt_mode = self._bt_mode_var.get()
        self._bt_sync()
        self._bt_update()

    # -- recolor mine --
    def sm_rc_preset(self, key):
        """A recolor preset chip: Original (no change), From deck (the selected deck's colours) or one of PRESETS.
        """
        rc = self.sm_rc
        if key == "original":
            rc.update(method="shift", hue=0.0, sat=1.0, bright=0.0)
        elif key == "deck":
            if self._gen_deck() is None:
                self.set_status(_("Select a deck on the Decks tab first — its colors become the HUD colors"))
                return
            rc.update(method="colors", stops=self._rc_deck_colors(), fill="shade")
        else:
            _k, _n, stops, fill = next(p for p in PRESETS if p[0] == key)
            rc.update(method="colors", stops=[tuple(s) for s in stops], fill=fill)
        rc["preset"] = key
        self._rc_sync()
        self._bt_update()

    def _rc_method_changed(self):
        """Shift colours / New colours switched."""
        self.sm_rc.update(method=self._rc_method.get(), preset=None)
        self._rc_sync()
        self._bt_update()

    def _rc_fill_changed(self):
        """By shade / Along the bar switched."""
        self.sm_rc.update(fill=self._rc_fill.get(), preset=None)
        self._rc_sync()
        self._bt_update()

    def _rc_slid(self):
        """A hue / saturation / brightness slider moved: switches to Shift colours and renders soon."""
        if getattr(self, "_rc_syncing", False):
            return
        v = self._rc_vars
        self.sm_rc.update(hue=float(v["hue"].get()), sat=float(v["sat"].get()) / 100.0,
                          bright=float(v["bright"].get()) / 100.0, method="shift", preset=None)
        self._rc_labels()
        self._rc_draw_chips()
        self._bt_later()

    def sm_rc_pick(self, i):
        """Picks one of the three New colours (dark, middle, light) with the colour chooser."""
        from tkinter import colorchooser
        from ..boards import to_hex
        stops = list(self.sm_rc["stops"])
        rgb, _hx = colorchooser.askcolor(color=to_hex(stops[i]), parent=base.root, title=_("Pick a color"))
        if not rgb:
            return
        stops[i] = tuple(int(round(x)) for x in rgb[:3])
        self.sm_rc.update(stops=stops, method="colors", preset=None)
        self._rc_sync()
        self._bt_update()

    def _rc_labels(self):
        """The value labels of the three recolor sliders."""
        rc = self.sm_rc
        self._rc_rows["hue"]._val.config(text=f"{rc['hue']:+.0f}°")
        self._rc_rows["sat"]._val.config(text=f"{rc['sat'] * 100:.0f} %")
        self._rc_rows["bright"]._val.config(text=f"{rc['bright'] * 100:+.0f} %")

    def _rc_sync(self):
        """Shows the recolor settings in the controls (switches, sliders, swatches, which group is visible, chips).
        """
        from ..boards import to_hex
        rc = self.sm_rc
        self._rc_syncing = True
        self._rc_method.set(rc["method"])
        self._rc_fill.set(rc["fill"])
        self._rc_vars["hue"].set(rc["hue"])
        self._rc_vars["sat"].set(rc["sat"] * 100)
        self._rc_vars["bright"].set(rc["bright"] * 100)
        self._rc_syncing = False
        self._rc_labels()
        for sw, col in zip(self._rc_stop_btns, rc["stops"]):
            sw.config(bg=to_hex(col))
        if rc["method"] == "colors":
            self._rc_shift.pack_forget()
            self._rc_colors.pack(fill="x")
            self._rc_method_hint.config(text=_("replaces the colors, keeps the light and shade"))
        else:
            self._rc_colors.pack_forget()
            self._rc_shift.pack(fill="x")
            self._rc_method_hint.config(text=_("keeps your texture, turns its colors"))
        self._rc_fill_hint.config(text=_("the bar's tip changes color as the speed rises")
                                  if rc["fill"] == "along" else _("dark parts take the first color"))
        self._rc_draw_chips()

    def _rc_draw_chips(self):
        """Draws the preset chips (Original shows the real texture, From deck the deck's colours)."""
        sel = self.sm_rc.get("preset")
        have_deck = self._gen_deck() is not None
        for key, (cv, name, stops) in self._rc_chips.items():
            if key == "original":
                src = self.sm_tex.get("Texture")
                img = (src.img.crop((0, 68, src.width, min(154, src.height))).convert("RGB").resize((64, 14))
                       if src is not None else Image.new("RGB", (64, 14), _rgb(C["btn"])))
            elif key == "deck":
                img = gradient_swatch(self._rc_deck_colors() if have_deck else [_rgb(C["btn"])] * 3)
            else:
                img = gradient_swatch(stops)
            self._draw_chip(cv, img, name, key == sel, key != "deck" or have_deck, self._bt_photos, "rc" + key)

    def _rc_deck_colors(self):
        """Three colours (dark to light) taken from the selected deck's artwork; cached per image."""
        img = self.tex.img
        if getattr(self, "_rc_deck", (None,))[0] is not img:
            self._rc_deck = (img, deck_colors(img))
        return list(self._rc_deck[1])

    # -- make new --
    def _gen_deck(self):
        """The selected deck's artwork, or None when no deck is open."""
        return self.tex.img if getattr(self, "tex", None) is not None else None

    def sm_gen_style(self, key):
        """A Make new style chip (Deck art needs a deck open on the Decks tab)."""
        if key == "deck" and self._gen_deck() is None:
            self.set_status(_("Select a deck on the Decks tab first — its artwork becomes the bar texture"))
            return
        self.sm_gen["style"] = key
        self._gen_sync()
        self._bt_update()

    def sm_gen_pick(self, i):
        """Picks one of the style's colours with the colour chooser."""
        from tkinter import colorchooser
        from ..boards import to_hex
        cols = list(self.sm_gen["colors"])
        rgb, _hx = colorchooser.askcolor(color=to_hex(cols[i]), parent=base.root, title=_("Pick a color"))
        if not rgb:
            return
        cols[i] = tuple(int(round(x)) for x in rgb[:3])
        self.sm_gen["colors"] = cols
        self._gen_sync()
        self._bt_update()

    def sm_gen_deck_colors(self):
        """Colours from deck: fills the style's colours from the selected deck's artwork."""
        if self._gen_deck() is None:
            self.set_status(_("Select a deck on the Decks tab first — its colors become the HUD colors"))
            return
        cols = self._rc_deck_colors()                 # dark -> light
        n = len(GEN_COLOR_NAMES.get(self.sm_gen["style"], (0, 0, 0)))
        if n == 1:
            cols = [cols[1]]
        elif n == 2:
            cols = [cols[0], cols[2]]
        self.sm_gen["colors"] = (cols + list(self.sm_gen["colors"]))[:3]
        self._gen_sync()
        self._bt_update()

    def _gen_slid(self, key):
        """A Make new slider moved (keeping zone 1 below zone 2) and renders soon."""
        if getattr(self, "_gen_syncing", False):
            return
        g = self.sm_gen
        g[key] = float(self._gen_vars[key].get())
        if key == "zone1" and g["zone1"] >= g["zone2"]:
            g["zone2"] = min(120.0, g["zone1"] + 1)
        if key == "zone2" and g["zone2"] <= g["zone1"]:
            g["zone1"] = max(1.0, g["zone2"] - 1)
        self._gen_sync(chips=False)
        self._bt_later()

    def _gen_shine_changed(self):
        """The Shine box changed."""
        self.sm_gen["shine"] = bool(self._gen_shine.get())
        self._bt_update()

    def _gen_sync(self, chips=True):
        """Shows the Make new settings in the controls: the style's help, its colour swatches, the sliders it uses
        and the chips.
        """
        from ..boards import to_hex
        g = self.sm_gen
        key = g["style"]
        _k, _name, _ncol, uses_size, helptext = next(s for s in GEN_STYLES if s[0] == key)
        self._gen_help.config(text=_(helptext))
        names = GEN_COLOR_NAMES.get(key, ())
        for i, (f, sw, lb) in enumerate(self._gen_sw):
            if i < len(names):
                sw.config(bg=to_hex(g["colors"][i]))
                lb.config(text=_(names[i]))
                f.pack(side="left", padx=(0, 8))
            else:
                f.pack_forget()
        fmts = {"size": "{:.0f} px", "full": "{:.0f} cm/s", "zone1": "{:.0f} cm/s", "zone2": "{:.0f} cm/s"}
        self._gen_syncing = True
        for k, v in self._gen_vars.items():
            v.set(g[k])
            self._gen_rows[k]._val.config(text=fmts[k].format(g[k]))
        self._gen_syncing = False
        self._gen_shine.set(g["shine"])
        show = {"size": uses_size, "full": key in ("gradient", "rainbow"), "zone1": key == "zones",
                "zone2": key == "zones"}
        for w in [self._gen_colors_row, self._gen_shine_cb] + list(self._gen_rows.values()):
            w.pack_forget()
        if names:
            self._gen_colors_row.pack(fill="x")
        for k, fr in self._gen_rows.items():
            if show[k]:
                fr.pack(fill="x", pady=(6, 0))
        self._gen_rows["size"]._cap.config(text=_("Zoom") if key == "deck" else _("Size"))
        self._gen_shine_cb.pack(anchor="w", pady=(8, 0))
        if chips:
            self._gen_draw_chips()

    def _gen_draw_chips(self):
        """Draws the style chips (their swatches are made once)."""
        sel = self.sm_gen["style"]
        have_deck = self._gen_deck() is not None
        if not hasattr(self, "_gen_sw_cache"):
            self._gen_sw_cache = {k: style_swatch(k) for k, *_r in GEN_STYLES}
        for key, (cv, name) in self._gen_chips.items():
            self._draw_chip(cv, self._gen_sw_cache[key], name, key == sel, key != "deck" or have_deck,
                            self._bt_photos, "gen" + key)

    # ------------------------------------------------------------------ bar texture: result
    def _bt_later(self, ms=70):
        """Renders the bar texture result soon (merging slider bursts)."""
        if getattr(self, "_bt_job", None):
            base.root.after_cancel(self._bt_job)
        self._bt_job = base.root.after(ms, self._bt_update)

    def _bt_changes(self):
        """True when the tool's result differs from the file."""
        return self.sm_bt_on and (self.sm_bt_mode == "make" or not is_identity(self.sm_rc))

    def _bt_update(self):
        """Makes the new texture for the current settings and refreshes the previews."""
        self._bt_job = None
        t = self.sm_tex.get("Texture") if hasattr(self, "sm_tex") else None
        self._bt_img = None
        if t is not None and self._bt_changes():
            try:
                self._bt_img = (generate(t.img.size, self.sm_gen, self._gen_deck()) if self.sm_bt_mode == "make"
                                else recolor(t.img, self.sm_rc))
            except Exception as e:
                self._bt_img = None
                self.set_status(_("Could not make the texture: {e}", e=e))
        if hasattr(self, "_bt_prev") and self._bt_prev["before"].winfo_exists():
            if t is not None:
                crop = (0, 68, t.width, min(154, t.height))
                self._bt_prev["before"].set_image(t.img.crop(crop))
                self._bt_prev["after"].set_image((self._bt_img or t.img).crop(crop))
            else:
                self._bt_prev["before"].set_image(None, _("Texture.xnb not loaded"))
                self._bt_prev["after"].set_image(None, "")
        self._sm_tools_changed()

    def sm_bt_apply(self, after=None):
        """Writes the new bar texture to Texture.xnb (with a .bak backup)."""
        t, p = self.sm_tex.get("Texture"), self.sm_path("Texture")
        if t is None or self._bt_img is None:
            return (after or (lambda: None))()
        new = self._bt_img
        if self._sm_play:
            self.sm_play_stop()

        def done():
            """After writing: forgets the on-screen result, reloads the folder and runs `after`."""
            self._bt_clear()
            self._sm_after_write()
            (after or (lambda: None))()
        self._write(p, t, new, _("New bar texture written to {name} (backup: {name}.bak)", name=p.name), after=done)

    def _bt_clear(self):
        """Back to 'nothing changed': the recolor settings go back to the original texture."""
        self.sm_rc.update(method="shift", hue=0.0, sat=1.0, bright=0.0, preset="original")
        self.sm_bt_mode = "recolor"
        self._bt_img = None
        self._bt_sync()

    def sm_bt_reset(self):
        """Drops the bar texture result (back to the file as it is)."""
        self._bt_clear()
        self._bt_update()

    def sm_bt_export(self):
        """Saves the bar texture result (or the current texture) as a PNG."""
        img = self._bt_img or (self.sm_tex["Texture"].img if "Texture" in self.sm_tex else None)
        if img is None:
            return
        f = filedialog.asksaveasfilename(defaultextension=".png", initialfile="Texture_new.png",
                                         filetypes=[("PNG", "*.png")])
        if f:
            img.save(f)
            self.set_status(_("Exported {f}", f=f))

    # ------------------------------------------------------------------ text maker: building
    def _tx_build(self, parent, shop):
        """Builds the Text maker: quick texts, the normal and precise labels with their previews, the font cards
        and Font file..., size / slant / spacing / weight sliders and alignment.
        """
        self._tools_init()
        P = C["panel"]
        t = self.sm_tx
        self._tx_vars, self._tx_prev = {}, {}
        label(parent, _("Quick text"), "small", "muted", anchor="w", bg=P).pack(fill="x", pady=(0, 4))
        row = Flow(parent, gap=6, vgap=6, bg=P)
        row.pack(fill="x", pady=(0, 12))
        for q in QUICK_TEXTS:
            row.add(button(row, q, lambda q=q: self.sm_tx_quick(q), small=True))
        row.add(button(row, _("Original"), lambda: self.sm_tx_quick(None), "ghost", small=True))
        for key, name in (("cms", N_("Normal (CM/S)")), ("mms", N_("Precise (MM/S)"))):
            label(parent, _(name), "small", "muted", anchor="w", bg=P).pack(fill="x", pady=(0, 2))
            r = tk.Frame(parent, bg=P)
            r.pack(fill="x", pady=(0, 10))
            v = tk.StringVar(value=t[key])
            e = tk.Entry(r, textvariable=v, width=12, font=F["mono"], bg=C["btn"], fg=C["text"],
                         insertbackground=C["text"], relief="flat", highlightthickness=1,
                         highlightbackground=C["btnb"], highlightcolor=C["accent"])
            e.pack(side="left", ipady=4)
            e.bind("<FocusIn>", lambda _e, k=key: self._tx_focus_on(k))
            v.trace_add("write", lambda *_a, k=key: self._tx_typed(k))
            self._tx_vars[key] = v
            pv = Preview(r, 64 / 260, 46)
            pv.pack(side="left", fill="x", expand=True, padx=(10, 0))
            self._tx_prev[key] = pv

        # the fonts as cards, each showing a sample in its own lettering
        label(parent, _("Font"), "small", "muted", anchor="w", bg=P).pack(fill="x", pady=(2, 4))
        grid = tk.Frame(parent, bg=P)
        grid.pack(fill="x")
        grid.columnconfigure(0, weight=1, uniform="font")
        grid.columnconfigure(1, weight=1, uniform="font")
        self._tx_font = tk.StringVar(value="" if t.get("file") else t["font"])
        self._tx_font_cards, self._tx_font_photos = {}, {}
        for n, (k, lab) in enumerate(available_fonts()):
            cv = tk.Canvas(grid, height=44, width=150, bg=P, highlightthickness=0, cursor="hand2")
            cv.grid(row=n // 2, column=n % 2, sticky="ew", padx=(0 if n % 2 == 0 else 6, 0), pady=(0, 6))
            cv.bind("<Button-1>", lambda e, k=k: (self._tx_font.set(k), self._tx_font_changed()))
            cv.bind("<Configure>", lambda e, k=k: self._tx_draw_font_card(k))
            self._tx_font_cards[k] = (cv, lab)
        self.b_tx_file = button(parent, _("Font file…"), self.sm_tx_font_file, "ghost", small=True)
        self.b_tx_file.pack(anchor="w", pady=(2, 0))
        self._tx_font.trace_add("write", lambda *_a: [self._tx_draw_font_card(k) for k in self._tx_font_cards])

        self._tx_sliders = {}
        for key, name, lo, hi, res in (("size", N_("Size"), 40, 100, 1), ("slant", N_("Slant"), 0, 30, 1),
                                       ("spacing", N_("Letter spacing"), -10, 40, 1),
                                       ("weight", N_("Weight"), 0, 4, 0.5)):
            v = tk.DoubleVar(value=t[key])
            fr = self._slider_row(parent, name, lo, hi, res, v, lambda k=key: self._tx_slid(k))
            fr.pack(fill="x", pady=(8 if key == "size" else 4, 0))
            self._tx_sliders[key] = (v, fr)
        r = tk.Frame(parent, bg=P)
        r.pack(fill="x", pady=(10, 0))
        label(r, _("Align"), "small", "muted", width=LBL_W, anchor="w", bg=P).pack(side="left")
        self._tx_align = tk.StringVar(value=t["align"])
        for val, name in (("left", N_("Left")), ("center", N_("Center")), ("right", N_("Right"))):
            self._sm_seg(r, _(name), val, self._tx_align, self._tx_align_changed).pack(side="left", padx=(0, 4))
        self._wrap_label(parent, _("The numbers stay in cm/s (mm/s in precise mode): only the label changes."),
                         fg="muted").pack(fill="x", pady=(12, 0))
        self._tx_sync()

    def _tx_draw_font_card(self, key):
        """Draws a font card: a sample ('Aa 194') in that font, its name, outlined when selected."""
        cv, lab = self._tx_font_cards.get(key, (None, None))
        if cv is None or not cv.winfo_exists():
            return
        cv.delete("all")
        W, H = max(80, cv.winfo_width()), 44
        on = self._tx_font.get() == key
        cv.create_rectangle(1, 1, W - 2, H - 2, outline=C["accent"] if on else C["btnb"], width=2 if on else 1,
                            fill=C["selfill"] if on else C["btn"])
        ph = self._tx_font_photos.get(key)
        if ph is None:
            try:
                st = {**self.sm_tx, "font": key, "file": None, "size": 90.0, "spacing": 2.0, "align": "left",
                      "weight": 0.0}
                m = make_text((72, 26), "Aa 194", st).getchannel("A")
                img = Image.new("RGBA", m.size, _rgb(C["text"]))
                img.putalpha(m)
                ph = self._tx_font_photos[key] = ImageTk.PhotoImage(img)
            except Exception:
                ph = None
        if ph is not None:
            cv.create_image(8, H / 2, image=ph, anchor="w")
        cv.create_text(W - 8, H / 2, text=_(lab), anchor="e", font=F["small"], fill=C["text"])

    # ------------------------------------------------------------------ text maker: editing
    def _tx_touch(self):
        """Marks the text maker as in use and changed (its result now shows on screen)."""
        self._tx_touched = True
        self.sm_tx_on = True

    def _tx_focus_on(self, key):
        """Typing the precise text shows the preview in precise mode, and the other way round."""
        self._tx_focus = key
        want = key == "mms"
        if bool(self.sm_precise.get()) != want:
            self.sm_precise.set(want)
            self._sm_controls()

    def _tx_typed(self, key):
        """A label typed: stores it (16 characters at most) and renders soon."""
        if getattr(self, "_tx_syncing", False):
            return
        self.sm_tx[key] = self._tx_vars[key].get()[:16]
        self._tx_touch()
        self._tx_later()

    def _tx_later(self):
        """Renders the text result soon (merging typing bursts)."""
        if getattr(self, "_tx_job", None):
            base.root.after_cancel(self._tx_job)
        self._tx_job = base.root.after(120, self._tx_update)

    def sm_tx_quick(self, text):
        """A quick text button: puts the text into the label being edited (None = the original CM/S and MM/S).
        """
        key = self._tx_focus
        if text is None:
            self.sm_tx.update(cms=TX_DEFAULT["cms"], mms=TX_DEFAULT["mms"])
        else:
            self.sm_tx[key] = text
            self._tx_focus_on(key)
        self._tx_touch()
        self._tx_sync()
        self._tx_update()

    def _tx_font_changed(self):
        """A font card was picked (drops a chosen font file)."""
        self.sm_tx.update(font=self._tx_font.get(), file=None)
        self._tx_touch()
        self._tx_sync()
        self._tx_update()

    def sm_tx_font_file(self):
        """Uses a font file (.ttf / .otf / .ttc) chosen by the user, after checking it can draw text."""
        f = filedialog.askopenfilename(title=_("Choose a font"), filetypes=[
            (_("Fonts"), "*.ttf *.otf *.ttc"), (_("All files"), "*.*")])
        if not f:
            return
        try:
            make_text((240, 64), "AB", {**self.sm_tx, "file": f})
        except Exception as e:
            messagebox.showerror(_("Cannot use this font"), str(e))
            return
        self.sm_tx["file"] = f
        self._tx_touch()
        self._tx_sync()
        self._tx_update()

    def _tx_slid(self, key):
        """A text slider moved."""
        if getattr(self, "_tx_syncing", False):
            return
        self.sm_tx[key] = float(self._tx_sliders[key][0].get())
        self._tx_touch()
        self._tx_sync()
        self._tx_later()

    def _tx_align_changed(self):
        """Left / Center / Right switched."""
        self.sm_tx["align"] = self._tx_align.get()
        self._tx_touch()
        self._tx_update()

    def _tx_sync(self):
        """Shows the text settings in the controls (labels, sliders and their values, alignment, font, the font
        file button).
        """
        if not hasattr(self, "_tx_vars"):
            return
        t = self.sm_tx
        fmts = {"size": "{:.0f} %", "slant": "{:.0f}°", "spacing": "{:+.0f} px", "weight": "+{:.1f} px"}
        self._tx_syncing = True
        for key, v in self._tx_vars.items():
            if v.get() != t[key]:
                v.set(t[key])
        for k, (v, fr) in self._tx_sliders.items():
            v.set(t[k])
            fr._val.config(text=fmts[k].format(t[k]))
        self._tx_align.set(t["align"])
        self._tx_font.set("" if t.get("file") else t["font"])
        self._tx_syncing = False
        self.b_tx_file.config(text=(Path(t["file"]).name if t.get("file") else _("Font file…")))

    # ------------------------------------------------------------------ text maker: result
    def _tx_changes(self):
        """True when the text maker has a change to show and write."""
        return self.sm_tx_on and self._tx_touched

    def _tx_update(self):
        """Makes the new CMS and MMS images from the settings and shows them in the previews (and the HUD preview).
        """
        self._tx_job = None
        have = hasattr(self, "sm_tex") and "CMS" in self.sm_tex and "MMS" in self.sm_tex
        self._tx_imgs = {}
        if have and self._tx_changes():
            try:
                self._tx_imgs = {"CMS": make_text(self.sm_tex["CMS"].img.size, self.sm_tx["cms"], self.sm_tx),
                                 "MMS": make_text(self.sm_tex["MMS"].img.size, self.sm_tx["mms"], self.sm_tx)}
            except Exception as e:
                self._tx_imgs = {}
                self.set_status(_("Could not make the text: {e}", e=e))
        if hasattr(self, "_tx_prev") and self._tx_prev["cms"].winfo_exists():
            for key, part in (("cms", "CMS"), ("mms", "MMS")):
                im = self._tx_imgs.get(part) or (self.sm_tex[part].img if have else None)
                if im is None:
                    self._tx_prev[key].set_image(None, _("{name} not loaded", name=part + ".xnb"))
                    continue
                back = Image.new("RGBA", im.size, (38, 38, 42, 255))     # white text needs a dark backing
                back.alpha_composite(im.convert("RGBA"))
                self._tx_prev[key].set_image(back)
        self._sm_tools_changed()

    def sm_tx_apply(self, after=None):
        """Writes the new unit text into CMS.xnb and MMS.xnb (one after the other, each with a .bak), then runs
        `after`.
        """
        if not self._tx_imgs:
            return (after or (lambda: None))()
        imgs = dict(self._tx_imgs)
        if self._sm_play:
            self.sm_play_stop()
        steps = [k for k in ("CMS", "MMS") if k in self.sm_tex]

        def done():
            """After writing: clears the result, reloads the folder and runs `after`."""
            self._tx_touched = False
            self._tx_imgs = {}
            self._sm_after_write()
            (after or (lambda: None))()

        def write(i=0):
            """Writes step i, then the next one when it is done."""
            if i >= len(steps):
                return done()
            k = steps[i]
            # _write shows its message after the next step ran, so every step carries the final message
            self._write(self.sm_path(k), self.sm_tex[k], imgs[k],
                        _("New unit text written to CMS.xnb and MMS.xnb (backups: .bak)"),
                        after=lambda: write(i + 1))
        write()

    def sm_tx_reset(self):
        """Back to the original labels; the result is dropped."""
        self.sm_tx.update({k: TX_DEFAULT[k] for k in ("cms", "mms")})
        self._tx_touched = False
        self._tx_sync()
        self._tx_update()

    def sm_tx_export(self):
        """Saves the new (or current) CMS and MMS images as PNGs in a chosen folder."""
        imgs = self._tx_imgs or {k: self.sm_tex[k].img for k in ("CMS", "MMS") if k in self.sm_tex}
        if not imgs:
            return
        d = filedialog.askdirectory(title=_("Folder for CMS.png and MMS.png"))
        if d:
            for k, im in imgs.items():
                im.save(Path(d) / f"{k}.png")
            self.set_status(_("Exported CMS.png and MMS.png to {f}", f=d))

    # ------------------------------------------------------------------ both
    def _sm_overrides(self):
        """What the in-game preview draws instead of the files: the tools' results."""
        out = {}
        if self._bt_img is not None and self._bt_changes():
            out["Texture"] = self._bt_img
        if self._tx_imgs and self._tx_changes():
            out.update(self._tx_imgs)
        return out

    def _sm_pending(self):
        """The parts with changes that are only on screen."""
        out = []
        if self._bt_img is not None and self._bt_changes():
            out.append(N_("bar texture"))
        if self._tx_imgs and self._tx_changes():
            out.append(N_("unit text"))
        return out

    def sm_write_all(self):
        """Writes every change that is only on screen (the bar texture, then the unit text)."""
        what = [_(x) for x in self._sm_pending()]

        def done():                  # each write shows its own message; end with one for both
            """After both writes: one status message naming everything written."""
            base.root.after_idle(lambda: self.set_status(_("Written to the game: {what} (backups: .bak)",
                                                           what=" + ".join(what))))
        self.sm_bt_apply(after=lambda: self.sm_tx_apply(after=done))

    def sm_reset_all(self):
        """Reset in the bar: drops the bar texture and text results."""
        self.sm_bt_reset()
        self.sm_tx_reset()

    def _sm_tools_reload(self):
        """After the files were (re)loaded: the tools follow the new files."""
        self._tools_init()
        f = getattr(self, "_bt_rc_frame", None)
        if f is not None and f.winfo_exists():
            self._rc_draw_chips()
        self._bt_update()
        self._tx_update()

    def _sm_tools_changed(self):
        """A tool's result changed: buttons, bars and the preview follow."""
        if hasattr(self, "_sm_cards_refresh"):
            self._sm_cards_refresh()
        if getattr(self, "layout", None) == "shop" and hasattr(self, "_sms_refresh"):
            self._sms_refresh()
        if not hasattr(self, "sm_canvas"):
            return
        if self._sm_play:
            self._sm_start_render(fast=True)
        else:
            self.sm_schedule()

    # ------------------------------------------------------------------ cards (layouts other than the shop)
    def _build_tool_cards(self, m, after):
        """A card per tool, shown under the in-game preview when its button is clicked."""
        self._tools_init()
        # coming from the shop layout: a tool's card opens only if it holds a change
        self.sm_bt_on, self.sm_tx_on = self._bt_changes(), self._tx_changes()
        self._sm_tool_cards = {}
        for key, title, sub, build, apply_text, apply, reset, export in (
                ("bt", N_("Bar texture"), N_("colors the bar, the blocks, the unit text and the digits"),
                 self._bt_build, N_("Apply to Texture.xnb"), self.sm_bt_apply, self.sm_bt_reset, self.sm_bt_export),
                ("tx", N_("Text maker"), N_("new unit text under the bar — the bar texture colors it and the game "
                                            "adds the black outline"),
                 self._tx_build, N_("Apply to CMS.xnb + MMS.xnb"), self.sm_tx_apply, self.sm_tx_reset,
                 self.sm_tx_export)):
            c = card(m)
            head = tk.Frame(c, bg=C["panel"])
            head.pack(fill="x", padx=16, pady=10)
            label(head, _(title), "h2").pack(side="left")
            label(head, _(sub), "small", "muted").pack(side="left", padx=10)
            button(head, _("Close"), lambda k=key: self.sm_tool_toggle(k), "ghost", small=True).pack(side="right")
            hline(c).pack(fill="x")
            body = tk.Frame(c, bg=C["panel"])
            body.pack(fill="x", padx=16, pady=(12, 0))
            inner = tk.Frame(body, bg=C["panel"], width=520)
            inner.pack(side="left", fill="y", anchor="n")
            build(inner, shop=False)
            act = tk.Frame(c, bg=C["panel"])
            act.pack(fill="x", padx=16, pady=(12, 16))
            b_apply = button(act, _(apply_text), lambda a=apply: a(after=self._sm_cards_refresh), "primary")
            b_apply.pack(side="left")
            button(act, _("Save as PNG…"), export).pack(side="left", padx=(8, 0))
            b_reset = button(act, _("Reset"), reset, "ghost")
            b_reset.pack(side="left", padx=(8, 0))
            note = self._wrap_label(act, _("The preview above shows the result. Nothing is written until you click "
                                           "Apply (a .bak backup is kept)."), fg="muted")
            note.pack(side="left", fill="x", expand=True, padx=(14, 0))
            self._sm_tool_cards[key] = (c, b_apply, b_reset)
        self._sm_card_after = after
        for key, on in (("bt", self.sm_bt_on), ("tx", self.sm_tx_on)):
            if on:
                self._sm_tool_cards[key][0].pack(fill="x", pady=(20, 0), after=after)
        base.root.after_idle(lambda: (self._bt_update(), self._tx_update()))

    def sm_tool_toggle(self, key):
        """Opens / closes a tool's card (layouts other than the shop). One tool at a time."""
        cards = getattr(self, "_sm_tool_cards", None)
        if not cards:
            return
        need = {"bt": ["Texture"], "tx": ["CMS", "MMS"]}[key]
        is_on = self.sm_bt_on if key == "bt" else self.sm_tx_on
        if not is_on and any(k not in self.sm_tex for k in need):
            self.set_status(_("{names} not loaded", names=", ".join(k + ".xnb" for k in need)))
            return
        for k in ("bt", "tx"):
            on = (k == key) and not is_on
            if k == "bt":
                self.sm_bt_on = on
            else:
                self.sm_tx_on = on
            c = cards[k][0]
            if on:
                c.pack(fill="x", pady=(20, 0), after=self._sm_card_after)
            else:
                c.pack_forget()
        self._bt_update()
        self._tx_update()

    def _sm_cards_refresh(self):
        """The tool cards of the other layouts: Apply / Reset enabled only with a change, and a dot on the tool
        buttons that are in use.
        """
        cards = getattr(self, "_sm_tool_cards", None)
        if not cards or not cards["bt"][0].winfo_exists():
            return
        for key, changed in (("bt", self._bt_img is not None and self._bt_changes()),
                             ("tx", bool(self._tx_imgs) and self._tx_changes())):
            _c, b_apply, b_reset = cards[key]
            set_state([b_apply, b_reset], changed)
            b_apply.config(bg=C["accent"] if changed else C["btn"])
            b_apply.bind("<Leave>", lambda e, b=b_apply, on=changed: b.config(bg=C["accent"] if on else C["btn"]))
        for attr, key, text in (("b_sm_bartex", "bt", N_("◐  Bar texture")), ("b_sm_text", "tx", N_("Aa  Text maker"))):
            b = getattr(self, attr, None)
            if b is not None and b.winfo_exists():
                on = self.sm_bt_on if key == "bt" else self.sm_tx_on
                b.config(text=_(text) + ("  •" if on else ""))
