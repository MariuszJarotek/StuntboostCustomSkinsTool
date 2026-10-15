"""Settings as a page of the Skate shop layout (the other layouts keep the Settings window).

The page covers the window below the header: picture cards for the layout, theme and text size, the
language, the game folder, the 3D renderer and the credits, all on one page. A change is used
right away (the window rebuilds for a new layout, theme, language or text size, and the page stays
open); Done or Esc closes it."""
from __future__ import annotations

import tkinter as tk

from ..i18n import LANGS, N_, _, _n, detect
from ..settings import C, LAYOUTS, SETTINGS, TEXT_SIZE_NAMES, THEME_NAMES, settings_path
from .base import F, SegButton, Scroll, label
from .dialogs import SettingsDialog, credit_lines
from .shop import _flat_button, ink, onink
from . import base


class ShopSettingsMixin:
    # ------------------------------------------------------------------ open / close
    """The Settings page of the Skate shop layout (mixed into App). The page is built on first use and placed over
    the content area; it is rebuilt with the window when the theme or layout changes.
    """
    def _shop_settings_toggle(self):
        """The Settings tag in the header: opens the page, or closes it when it is open."""
        if getattr(self, "_set_page", None) is not None and self._set_page.winfo_ismapped():
            self._shop_settings_close()
        else:
            self._shop_settings_open()

    def _shop_settings_open(self):
        """Shows the page over the content (building it the first time), lights the Settings tag and dims the tab
        tags.
        """
        body = getattr(self, "_body", None)
        if body is None:
            return
        page = getattr(self, "_set_page", None)
        if page is None or not page.winfo_exists():
            page = self._set_page = tk.Frame(body, bg=C["bg"])
            self._shop_settings_build(page)
        page.place(in_=body, x=0, y=0, relwidth=1, relheight=1)
        page.lift()
        self._shop_settings_refresh()
        tag = getattr(self, "_shop_settings_tag", None)
        if tag is not None:
            tag.set(kind="on")
        for t in getattr(self, "_shop_tabs", {}).values():
            t.set(kind="ink")
        base.root.bind("<Escape>", self._shop_settings_esc, add="+")

    def _shop_settings_close(self):
        """Hides the page and lights the current tab's tag again."""
        page = getattr(self, "_set_page", None)
        if page is not None and page.winfo_exists():
            page.place_forget()
        tag = getattr(self, "_shop_settings_tag", None)
        if tag is not None and tag.winfo_exists():
            tag.set(kind="ink")
            self._shop_tabs_refresh()

    def _shop_settings_esc(self, e):
        """Esc closes the page when it is open."""
        if self._shop_settings_is_open():
            self._shop_settings_close()

    def _shop_settings_is_open(self):
        """True while the settings page is shown."""
        page = getattr(self, "_set_page", None)
        return page is not None and page.winfo_exists() and page.winfo_ismapped()

    # ------------------------------------------------------------------ building
    def _shop_settings_build(self, page):
        # the ink bar at the bottom: what happens, and Done
        """Builds the page: the ink bar with Done, then the sections Look (layout and theme cards), Language &
        text, Game folder, 3D preview and Credits. Everything fits on one page, so there is no section menu.
        """
        bar = tk.Frame(page, bg=ink())
        bar.pack(side="bottom", fill="x")
        bi = tk.Frame(bar, bg=ink())
        bi.pack(fill="x", padx=24, pady=10)
        tk.Label(bi, text=_("Changes are used right away. The window rebuilds for a new layout, theme, language "
                            "or text size."), font=F["body"], fg=onink(), bg=ink(), anchor="w").pack(
            side="left", fill="x", expand=True)
        _flat_button(bi, _("Done"), self._shop_settings_close, C["accent"], C["onaccent"], C["accenth"],
                     bd=C["accent"]).pack(side="right")

        sc = self._set_scroll = Scroll(page)
        sc.canvas.config(bg=C["bg"])
        sc.inner.config(bg=C["bg"])
        sc.pack(side="left", fill="both", expand=True)
        main = tk.Frame(sc.inner, bg=C["bg"])
        main.pack(fill="both", expand=True, padx=40, pady=(18, 30))
        tk.Label(main, text=_("Settings").upper(), font=F["displayxl"], fg=ink(), bg=C["bg"],
                 anchor="w").pack(fill="x", pady=(0, 14))
        self._set_secs = {}

        def head(parent, text):
            """A section heading."""
            tk.Label(parent, text=_(text).upper(), font=F["display"], fg=ink(), bg=C["bg"],
                     anchor="w").pack(fill="x", pady=(0, 10))

        self._set_cards = []

        # Look: layout and theme as picture cards
        sec = self._set_secs["look"] = tk.Frame(main, bg=C["bg"])
        sec.pack(fill="x")
        head(sec, N_("Layout"))
        row = tk.Frame(sec, bg=C["bg"])
        row.pack(fill="x")
        for n, (key, (name, desc)) in enumerate(LAYOUTS.items()):
            row.columnconfigure(n, weight=1, uniform="lay")
            self._shop_settings_card(row, n, "layout", key, name, desc, SettingsDialog._draw_layout, 170, 96)
        head_box = tk.Frame(sec, bg=C["bg"])
        head_box.pack(fill="x", pady=(22, 0))
        head(head_box, N_("Theme"))
        row = tk.Frame(sec, bg=C["bg"])
        row.pack(fill="x")
        for n, (key, name) in enumerate(THEME_NAMES.items()):
            row.columnconfigure(n, weight=1, uniform="theme")
            self._shop_settings_card(row, n, "theme", key, name, "", SettingsDialog._draw_theme, 150, 56)

        # Language & text size
        sec = self._set_secs["lang"] = tk.Frame(main, bg=C["bg"])
        sec.pack(fill="x", pady=(28, 0))
        sec.columnconfigure(0, weight=1, uniform="lt")
        sec.columnconfigure(1, weight=1, uniform="lt")
        left = tk.Frame(sec, bg=C["bg"])
        left.grid(row=0, column=0, sticky="nw", padx=(0, 30))
        head(left, N_("Language"))
        lrow = tk.Frame(left, bg=C["bg"])
        lrow.pack(anchor="w")
        self._set_lang = tk.StringVar(value=SETTINGS.get("language", "auto"))
        auto = dict(LANGS).get(detect(), "English")
        for code, name in (("auto", _("Automatic ({language})", language=auto)),) + LANGS:
            SegButton(lrow, text=name, value=code, variable=self._set_lang, command=self._shop_settings_apply,
                      bg=C["btn"], fg=C["text"], selectcolor=C["selfill"], activebackground=C["btnh"],
                      highlightthickness=2, highlightbackground=C["btnb"], padx=12, pady=6, font=F["bold"],
                      cursor="hand2").pack(side="left", padx=(0, 6))
        label(left, _("Automatic follows the Windows display language."), "small", "muted",
              bg=C["bg"]).pack(anchor="w", pady=(6, 0))
        right = tk.Frame(sec, bg=C["bg"])
        right.grid(row=0, column=1, sticky="nw")
        head(right, N_("Text size"))
        srow = tk.Frame(right, bg=C["bg"])
        srow.pack(anchor="w")
        for n, (key, name) in enumerate(TEXT_SIZE_NAMES.items()):
            self._shop_settings_card(srow, n, "text_size", key, name, "", SettingsDialog._draw_size, 110, 50)

        # Game folder
        sec = self._set_secs["game"] = tk.Frame(main, bg=C["bg"])
        sec.pack(fill="x", pady=(28, 0))
        head(sec, N_("Game folder"))
        row = tk.Frame(sec, bg=C["bg"])
        row.pack(fill="x")
        self._set_path = tk.Label(row, text="", font=F["mono"], fg=C["text"], bg=C["bg"], anchor="w",
                                  highlightthickness=2, highlightbackground=ink(), padx=10, pady=7)
        self._set_path.pack(side="left", fill="x", expand=True)
        _flat_button(row, _("Change folder…"), self.change_folder, ink(), onink(), C["sub"],
                     font=F["bold"]).pack(side="left", padx=(8, 0), fill="y")
        self._set_found = label(sec, "", "small", "muted", bg=C["bg"], anchor="w")
        self._set_found.pack(fill="x", pady=(6, 0))

        # 3D preview
        sec = self._set_secs["perf"] = tk.Frame(main, bg=C["bg"])
        sec.pack(fill="x", pady=(28, 0))
        head(sec, N_("3D preview"))
        self._set_gpu = tk.BooleanVar(value=bool(SETTINGS.get("gpu3d", True)))
        tk.Checkbutton(sec, text=_("Draw the 3D board on the graphics card (GPU) - faster and sharper while "
                                   "turning"), variable=self._set_gpu, command=self._shop_settings_gpu,
                       bg=C["bg"], fg=C["text"], activebackground=C["bg"], activeforeground=C["text"],
                       selectcolor=C["panel"], font=F["body"], bd=0, highlightthickness=0, cursor="hand2",
                       anchor="w").pack(anchor="w")
        self._set_gpu_note = label(sec, "", "small", "muted", bg=C["bg"], anchor="w", justify="left")
        self._set_gpu_note.pack(fill="x", pady=(4, 0))
        self._set_gpu_note.bind("<Configure>",
                                lambda e: self._set_gpu_note.config(wraplength=max(200, e.width - 4)))
        label(sec, _("Saved in {path}", path=settings_path()), "small", "muted", bg=C["bg"],
              anchor="w").pack(fill="x", pady=(18, 0))

        # Credits
        sec = self._set_secs["credits"] = tk.Frame(main, bg=C["bg"])
        sec.pack(fill="x", pady=(28, 0))
        head(sec, N_("Credits"))
        for text, font, fg in credit_lines():
            label(sec, text, font, fg, bg=C["bg"], anchor="w").pack(fill="x", pady=(0, 2))

    def _shop_settings_card(self, parent, col, what, key, name, desc, draw, w, h):
        """A picture card; clicking it uses that layout / theme / text size."""
        f = tk.Frame(parent, bg=C["bg"], highlightthickness=2, highlightbackground=ink(), cursor="hand2")
        if what == "text_size":
            f.pack(side="left", padx=(0, 10), anchor="n")
        else:
            f.grid(row=0, column=col, sticky="nsew", padx=(0 if col == 0 else 14, 0))
        cv = tk.Canvas(f, width=w, height=h, bg=C["bg"], highlightthickness=0)
        cv.pack(padx=10, pady=(10, 6), anchor="w")
        draw(None, cv, key, w, h)
        nm = tk.Label(f, text=_(name).upper(), font=F["displaysm"], fg=ink(), bg=C["bg"], anchor="w")
        nm.pack(fill="x", padx=10)
        parts = [f, cv, nm]
        if desc:
            d = label(f, _(desc), "small", "muted", justify="left", anchor="w", bg=C["bg"])
            d.pack(fill="x", padx=10, pady=(2, 10))
            d.bind("<Configure>", lambda e, d=d: d.config(wraplength=max(100, e.width - 4)))
            parts.append(d)
        else:
            tk.Frame(f, bg=C["bg"], height=8).pack()
        for wdg in parts:
            wdg.bind("<Button-1>", lambda e, a=what, k=key: self._shop_settings_pick(a, k))
        self._set_cards.append((what, key, f, parts))

    # ------------------------------------------------------------------ state
    def _shop_settings_refresh(self):
        """Shows the current settings on the page: the chosen cards outlined, the game folder and what was found in
        it, and the GPU status.
        """
        cur = {"layout": SETTINGS.get("layout", "shop"), "theme": SETTINGS.get("theme", "concrete"),
               "text_size": SETTINGS.get("text_size", "balanced")}
        for what, key, f, parts in getattr(self, "_set_cards", []):
            on = cur.get(what) == key
            bg = C["panel"] if on else C["bg"]
            f.config(highlightbackground=C["accent"] if on else ink(), bg=bg,
                     highlightthickness=3 if on else 2)
            for wdg in parts[2:]:
                wdg.config(bg=bg)
            for ch in f.winfo_children():
                if isinstance(ch, tk.Frame):
                    ch.config(bg=bg)
        if hasattr(self, "_set_path"):
            kind, full = self._path_text()
            self._set_path.config(text=full if self.folder else _("No folder chosen yet"))
            parts = []
            if self.folder:
                parts.append(_n("{n} deck", "{n} decks", len(self.boards)))
            if getattr(self, "sm_folder", None) is not None:
                parts.append(_("speedmeter found"))
            self._set_found.config(text="  ·  ".join(parts))
            from ..board3d import gpu_status
            self._set_gpu_note.config(
                text=_("Now: {status}", status=gpu_status()[1]) + "\n"
                + _("The graphics driver needs some extra memory while loaded. If the 3D view looks wrong or "
                    "the tool crashes, untick this."))

    def _shop_settings_pick(self, what, key):
        """A layout, theme or text size card was clicked: applies it unless it is already in use."""
        cur = {"layout": SETTINGS.get("layout", "shop"), "theme": SETTINGS.get("theme", "concrete"),
               "text_size": SETTINGS.get("text_size", "balanced")}
        if cur.get(what) == key:
            return
        cur[what] = key
        self._shop_settings_apply(**cur)

    def _shop_settings_apply(self, layout=None, theme=None, text_size=None):
        """Applies the settings (the window rebuilds) and opens the page again afterwards when the layout is still
        Skate shop.
        """
        self._settings_reopen = True
        self.apply_settings(layout or SETTINGS.get("layout", "shop"), theme or SETTINGS.get("theme", "concrete"),
                            None, self._set_lang.get() if hasattr(self, "_set_lang") else None,
                            text_size or SETTINGS.get("text_size", "balanced"))
        if self._settings_reopen and self.layout == "shop":
            base.root.after_idle(self._shop_settings_open)
        self._settings_reopen = False

    def _shop_settings_gpu(self):
        """The GPU checkbox changed: switches the 3D renderer (no rebuild needed)."""
        self.apply_settings(SETTINGS.get("layout", "shop"), SETTINGS.get("theme", "concrete"),
                            bool(self._set_gpu.get()))
        self._shop_settings_refresh()
