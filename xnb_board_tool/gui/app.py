"""The main window: state, loading boards (in the background), the board list and actions."""
from __future__ import annotations

import queue
import re
import threading
from pathlib import Path
from typing import Optional

from tkinter import colorchooser
from tkinter import filedialog
from tkinter import messagebox
from tkinter import ttk
import tkinter as tk
import tkinter.font as tkfont
from PIL import Image, ImageDraw, ImageTk

from ..common import human_size
from ..xnb import SURFACE_NAMES, load_texture, save_texture
from ..defaults import (
    HashCache, board_status, file_status, load_default_meta, revert_to_default, set_default,
)
from ..boards import (
    Board, PALETTE_SLOTS, apply_palette, parse_color, read_palette, read_texture_palette, scan,
    strip_image, to_hex,
)
from ..caches import CardCache, TEXCACHE
from ..speedmeter import find_speedmeter_folder
from ..settings import BADGES, C, _rgb, titlebar
from .base import F, set_state
from . import base
from .dialogs import AdjustDialog
from .layouts import LayoutsMixin
from .preview3d import Preview3DMixin
from .speedmeter_tab import SpeedmeterMixin
from .decorate import DecorateMixin


class App(LayoutsMixin, Preview3DMixin, SpeedmeterMixin, DecorateMixin):
    """The main window: state, loading boards, the board list and all file actions."""

    def __init__(self, start_folder=None):
        base.root.title("XNB Board Texture Tool")
        base.root.geometry("1280x880")
        base.root.minsize(940, 620)
        base.root.configure(bg=C["bg"])
        self.folder: Optional[Path] = None
        self.path_full = "No folder loaded"
        self.boards: list[Board] = []
        self.status: dict[int, Optional[str]] = {}
        self.locked: set[int] = set()       # statuses computed on the UI thread
        self.strip_pil: dict[int, Image.Image] = {}
        self.row_imgs: dict[int, object] = {}
        self.sel: Optional[int] = None
        self.custom = False                 # texture panel shows a hand-picked .xnb
        self.tex_path = self.thumb_path = None
        self.tex = self.thumb = None
        self.tex_err = self.thumb_err = ""
        self.pal_orig = self.pal = None     # board colors: as stored / as edited
        self.clip = None                    # copied board colors
        self._pal_for = None                # texture path the edited colors belong to
        # speedmeter tab state
        self.sm_folder: Optional[Path] = None
        self.sm_tex: dict = {}              # part key -> TexData
        self.sm_err: dict = {}
        self.sm_status: dict = {}
        self.sm_key = "Texture"
        self.sm_imgs: dict = {}
        self._sm_job = None
        self._sm_busy = False
        self._sm_again = False
        self._sm_result = None
        self._sm_photo = None
        self._sm_last = None
        self.sm_font = None
        # 3D preview state
        self.v3_model, self.v3_err = None, ""
        self.v3_yaw, self.v3_pitch, self.v3_zoom = 120.0, 28.0, 1.0
        self._v3_job = self._v3_settle = self._v3_last = None
        self._v3_busy, self._v3_again, self._v3_result = False, None, None
        self._v3_photo, self._v3_size = None, (0, 0)
        self.v3_t_yaw, self.v3_t_pitch, self.v3_t_zoom = self.v3_yaw, self.v3_pitch, self.v3_zoom
        self._v3_tick, self._v3_vel, self._v3_dragging = None, (0.0, 0.0), False
        self._v3_scale, self._v3_fast, self._v3_t0, self._v3_item = 0.6, False, 0.0, None
        self._v3_texkey, self._v3_texarr, self._v3_texref = None, None, None
        self._v3_info, self._v3_info_scale, self._v3_down = None, 1.0, None
        self._dc_init_state()
        self.gal_pil: dict = {}             # gallery card images
        self.board_pal: dict = {}           # board index -> its 4 colors
        self.gal_cards: dict = {}
        self._keep: dict = {}               # values carried over when the window is rebuilt
        self.cache = HashCache()
        self.cards = CardCache()
        self._load_gen, self._loading = 0, False
        self.lq: queue.Queue = queue.Queue()            # background texture loads
        self._prefetch_q: queue.Queue = queue.Queue()
        threading.Thread(target=self._prefetch_loop, daemon=True).start()
        self.gen, self.pending = 0, 0
        self.q: queue.Queue = queue.Queue()
        self._syncing = False
        self._style()
        self._build()
        self._keep = {}
        base.root.protocol("WM_DELETE_WINDOW", self.close)
        base.root.bind("<Control-o>", lambda e: self.change_folder())
        base.root.bind("<Control-Left>", lambda e: self.step(-1))
        base.root.bind("<Control-Right>", lambda e: self.step(1))
        base.root.after(60, self._poll)
        titlebar(base.root, C["dark"])
        self._refresh_panels()
        if start_folder:
            base.root.after(50, lambda: self.load(Path(start_folder)))
        else:
            base.root.after(250, self.open_folder)

    # ---------- styling ----------
    def _style(self):
        st = ttk.Style(base.root)
        st.theme_use("clam")
        st.configure("Boards.Treeview", background=C["side"], fieldbackground=C["side"],
                     foreground=C["text"], borderwidth=0, rowheight=32, font=F["monolist"],
                     indent=0)
        st.layout("Boards.Treeview", [("Treeview.treearea", {"sticky": "nswe"})])
        st.layout("Boards.Treeview.Item", [("Treeitem.padding", {"sticky": "nswe", "children": [
            ("Treeitem.image", {"side": "left", "sticky": ""}),
            ("Treeitem.text", {"side": "left", "sticky": ""})]})])
        st.map("Boards.Treeview", background=[("selected", C["sel"])],
               foreground=[("selected", C["text"])])
        st.configure("Vertical.TScrollbar", background=C["btn"], troughcolor=C["side"],
                     bordercolor=C["side"], arrowcolor=C["muted"], lightcolor=C["btn"],
                     darkcolor=C["btn"], gripcount=0, arrowsize=12)
        st.map("Vertical.TScrollbar", background=[("active", C["btnh"])])

    def switch_tab(self):
        tab = self.tab_var.get()
        views = {"speed": self.speed_view, "decor": self.decor_view, "boards": self.board_view}
        for k, v in views.items():
            if k != tab:
                v.pack_forget()
        views.get(tab, self.board_view).pack(fill="both", expand=True)
        if tab == "speed":
            self.sm_refresh()
        elif tab == "decor":
            self.dc_enter()
        else:
            self.v3_schedule()
        self._fit_path()
        base.root.minsize(1180 if tab == "decor" else 940 if self.layout == "classic" or tab == "speed" else 1100, 640)

    # ---------- helpers ----------
    def set_status(self, text):
        self.status_var.set(text)

    def busy(self, on):
        base.root.config(cursor="watch" if on else "")
        base.root.update_idletasks()

    def _path_text(self):
        """(caption, path) for the top bar: follows the selected tab."""
        if self.tab_var.get() == "speed":
            return "Speedmeter", (str(self.sm_folder) if self.sm_folder else
                                  "No speedmeter folder — click Change…")
        return "Boards", self.path_full

    def _fit_path(self, _e=None):
        if not hasattr(self, "path_lbl"):
            return
        kind, full = self._path_text()
        self.path_kind.config(text=kind)
        avail = self.path_lbl.winfo_width() - 6
        key = (full, avail, str(F["mono"]))
        if key == getattr(self, "_fit_key", None):
            return                                   # same text, same width: nothing to do
        self._fit_key = key
        fk = str(F["mono"])
        if getattr(self, "_fit_fontkey", None) != fk:
            self._fit_font, self._fit_fontkey = tkfont.Font(root=base.root, font=F["mono"]), fk
        font = self._fit_font
        if avail < 30 or font.measure(full) <= avail:
            self.path_lbl.config(text=full)
            return
        # longest tail of the path that fits after the "…" (binary search, ~7 measures)
        lo, hi = 0, len(full)                        # tail length: lo fits, hi may not
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if font.measure("…" + full[-mid:]) <= avail:
                lo = mid
            else:
                hi = mid - 1
        self.path_lbl.config(text="…" + full[len(full) - lo:] if lo else "…")

    def _filter_focus_in(self, _e):
        if self._placeholder:
            self._placeholder = False
            self.filter.delete(0, "end")
            self.filter.config(fg=C["text"])

    def _filter_focus_out(self, _e):
        if not self.filter_var.get():
            self._placeholder = True
            self.filter.insert(0, "Filter boards…")
            self.filter.config(fg=C["muted"])

    def _filter_text(self):
        return "" if self._placeholder else self.filter_var.get().strip().lower()

    def _filter_enter(self, _e):
        kids = self.tree.get_children()
        if kids:
            self.select(int(kids[0]))

    def _row_image(self, i):
        im = Image.new("RGBA", (104, 24), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        st = self.status.get(i)
        if st == "def":
            d.ellipse([3, 8, 11, 16], fill=_rgb(C["green"]))
        elif st == "mod":
            d.rectangle([3, 8, 11, 16], fill=_rgb(C["accent"]))
        elif st == "none":
            d.ellipse([3, 8, 11, 16], outline=_rgb(C["muted"]), width=2)
        else:
            d.ellipse([5, 10, 9, 14], fill=_rgb(C["dis"]))
        strip = self.strip_pil.get(i)
        if strip is None:
            d.rectangle([20, 3, 95, 20], fill=_rgb(C["btn"]))
        else:
            im.paste(strip, (20, 3))
        ph = ImageTk.PhotoImage(im)
        self.row_imgs[i] = ph
        return ph

    def _refresh_row(self, i):
        if self.tree.exists(str(i)):
            self.tree.item(str(i), image=self._row_image(i))
        self._gal_update(i)

    def _fill_list(self):
        if not hasattr(self, "tree"):
            return
        q = self._filter_text()
        self._syncing = True
        self.tree.delete(*self.tree.get_children())
        shown = 0
        for i, b in enumerate(self.boards):
            if q and q not in b.name.lower():
                continue
            self.tree.insert("", "end", iid=str(i), text=f"  {b.name}",
                             image=self._row_image(i))
            shown += 1
        n = len(self.boards)
        self.count_lbl.config(text=f"{n} found" if shown == n else f"{shown} of {n}")
        if self.sel is not None and self.tree.exists(str(self.sel)) and not self.custom:
            self.tree.selection_set(str(self.sel))
            self.tree.see(str(self.sel))
        self._syncing = False
        self._gal_layout()

    def _on_tree_select(self, _e=None):
        if self._syncing:
            return
        s = self.tree.selection()
        if s and (int(s[0]) != self.sel or self.custom):
            self.select(int(s[0]))

    def _update_summary(self):
        n = len(self.boards)
        if not n:
            self.summary_lbl.config(text="")
            return
        vals = [self.status.get(i) for i in range(n)]
        text = (f"{n} boards · {vals.count('mod')} modified · "
                f"{vals.count('none')} without default")
        if self.pending:
            text += f" · checking {n - self.pending}/{n}…"
        self.summary_lbl.config(text=text)

    # ---------- loading ----------
    def change_folder(self):
        """Top-bar Change… / Ctrl+O: pick the folder for the tab that is shown."""
        if self.tab_var.get() == "speed":
            self.sm_choose_folder()
        else:
            self.open_folder()

    def open_folder(self):
        d = filedialog.askdirectory(title="Select content folder")
        if d:
            self.load(Path(d))

    def load(self, folder: Path):
        self.busy(True)
        try:
            boards = scan(folder)
        except Exception as e:
            messagebox.showerror("Cannot scan folder", str(e))
            return
        finally:
            self.busy(False)
        self.cache.save()
        self.folder = Path(folder).resolve()
        self.cache.attach(self.folder)
        self.cards.save()
        self.cards.attach(self.folder)
        self.boards = boards
        self.v3_load_model()
        self.status, self.locked, self.strip_pil, self.row_imgs = {}, set(), {}, {}
        if hasattr(self, "gal_canvas"):
            self.gal_canvas.delete("all")
        self.gal_cards, self.gal_pil, self.board_pal, self._gal_key = {}, {}, {}, None
        self.sel, self.custom = None, False
        self.path_full = str(self.folder)
        self._fit_path()
        self._fill_list()
        self.set_status(f"{len(boards)} board(s) found in {self.folder.name}")
        if boards:
            self.select(0)
        else:
            self.tex_path = self.thumb_path = self.tex = self.thumb = None
            self._refresh_panels()
        self._start_worker()
        sm = find_speedmeter_folder(self.folder)
        if sm is not None or self.sm_folder is None:
            self.sm_load(sm)
        if not boards and sm is not None:
            self.tab_var.set("speed")
            self.switch_tab()

    def _start_worker(self):
        self.gen += 1
        gen, boards, cache, q = self.gen, list(self.boards), self.cache, self.q
        have_strip = set(self.strip_pil)
        gw, gh = self.GAL_W, self.GAL_H
        self.pending = len(boards)
        self._update_summary()

        cards = self.cards

        def work():
            for i, b in enumerate(boards):
                if gen != self.gen:
                    return
                strip, gal, src_tex, sts = None, None, None, []
                src = b.thumb or b.texture
                src_sig, tex_sig = cards.sig(src), cards.sig(b.texture)
                if src and i not in have_strip:
                    gal = cards.card(b.name, src_sig)         # cached card image (no decoding)
                    if gal is None:
                        try:
                            src_tex = load_texture(src)
                            gal = strip_image(src_tex.img, gw, gh)
                            cards.store(b.name, src_sig, card=gal)
                        except Exception:
                            src_tex = None
                    if gal is not None:
                        strip = strip_image(gal)
                pal = cards.palette(b.name, tex_sig)
                if pal is None and b.texture:
                    pal = read_texture_palette(b.texture)
                    if pal:
                        cards.store(b.name, tex_sig=tex_sig, pal=pal)
                for p in (b.texture, b.thumb):
                    try:
                        sts.append(file_status(p, cache, src_tex if p == src else None))
                    except Exception:
                        pass
                q.put((gen, i, strip, board_status(sts), gal, pal))
                if i % 25 == 24:
                    cards.save()
            cards.save()
            q.put((gen, "done", None, None, None, None))

        threading.Thread(target=work, daemon=True).start()

    def _poll(self):
        try:
            while True:
                gen, i, strip, st, gal, pal = self.q.get_nowait()
                if gen != self.gen:
                    continue
                if i == "done":
                    self.pending = 0
                    self.cache.save()
                else:
                    self.pending = max(0, self.pending - 1)
                    if strip is not None:
                        self.strip_pil[i] = strip
                    if gal is not None and self.layout == "gallery" \
                            and not self._gal_on_disk(i):
                        self.gal_pil[i] = gal           # kept only when the disk cache can't hold it
                    if pal is not None and i not in self.locked:
                        self.board_pal[i] = pal
                    if i not in self.locked:
                        self.status[i] = st
                    self._refresh_row(i)
                self._update_summary()
        except queue.Empty:
            pass
        base.root.after(60, self._poll)

    def select(self, i: int):
        if not (0 <= i < len(self.boards)):
            return
        old = self.sel
        self.sel, self.custom = i, False
        b = self.boards[i]
        self.tex_path, self.thumb_path = b.texture, b.thumb
        if old is not None and old != i:
            self._gal_update(old)
        if hasattr(self, "v3_screws"):
            self.v3_screws.set(self._v3_screws_default())
        if self.tree.exists(str(i)):
            self._syncing = True
            self.tree.selection_set(str(i))
            self.tree.see(str(i))
            self._syncing = False
        self._load_current()
        self._gal_scroll_to(i)

    def step(self, d: int):
        if self.tab_var.get() == "speed":
            return self.sm_step(d)
        kids = list(self.tree.get_children())
        if not kids:
            return
        cur = str(self.sel)
        if cur not in kids:
            return self.select(int(kids[0]))
        j = kids.index(cur) + d
        if 0 <= j < len(kids):
            self.select(int(kids[j]))

    def _load(self, path):
        if not path:
            return None, ""
        try:
            return TEXCACHE.load(path), ""
        except Exception as e:
            return None, str(e)

    def _load_current(self, sync=False):
        """Shows the selected texture + thumbnail. Cached boards appear instantly; others are
        decoded in the background (thumbnail first) so the window never freezes. After a file
        was written, sync=True reloads it directly."""
        self._load_gen += 1
        gen = self._load_gen
        tp, hp = self.tex_path, self.thumb_path
        tex, thumb = TEXCACHE.get(tp), TEXCACHE.get(hp)
        if sync or ((tex is not None or not tp) and (thumb is not None or not hp)):
            self._loading = False
            self.busy(True)
            try:
                self.tex, self.tex_err = (tex, "") if tex is not None else self._load(tp)
                self.thumb, self.thumb_err = (thumb, "") if thumb is not None else self._load(hp)
            finally:
                self.busy(False)
            self._after_load()
            return
        self._loading = True
        self.tex, self.thumb, self.tex_err, self.thumb_err = tex, thumb, "", ""
        self._refresh_panels()
        lq = self.lq

        def work():
            for which, path, have in (("thumb", hp, thumb), ("tex", tp, tex)):   # small one first
                if path and have is None:
                    t, err = self._load(path)
                    lq.put((gen, which, t, err))
            lq.put((gen, "done", None, None))
        threading.Thread(target=work, daemon=True).start()
        base.root.after(10, self._load_poll)

    def _load_poll(self):
        done = False
        try:
            while True:
                gen, which, t, err = self.lq.get_nowait()
                if gen != self._load_gen:
                    continue                      # an older selection: ignore
                if which == "thumb":
                    self.thumb, self.thumb_err = t, err
                    self._refresh_panels()
                elif which == "tex":
                    self.tex, self.tex_err = t, err
                else:
                    done = True
        except queue.Empty:
            pass
        if done:
            self._loading = False
            self._after_load()
        elif self._loading:
            base.root.after(15, self._load_poll)

    def _prefetch_neighbors(self):
        """Decodes the previous and next board in the background, so stepping is instant."""
        if self.custom or self.sel is None:
            return
        kids = [int(k) for k in self.tree.get_children()]
        if self.sel not in kids:
            return
        j = kids.index(self.sel)
        paths = []
        for k in (j + 1, j - 1):
            if 0 <= k < len(kids):
                b = self.boards[kids[k]]
                paths += [b.thumb, b.texture]
        self._prefetch_q.put([p for p in paths if p])

    def _prefetch_loop(self):
        while True:
            paths = self._prefetch_q.get()
            while not self._prefetch_q.empty():          # only the newest request matters
                try:
                    paths = self._prefetch_q.get_nowait()
                except queue.Empty:
                    break
            for p in paths:
                if not self._prefetch_q.empty():
                    break
                try:
                    TEXCACHE.load(p)
                except Exception:
                    pass

    def _after_load(self):
        try:
            if not self.custom and self.sel is not None:
                sts = []
                for p, t in ((self.tex_path, self.tex), (self.thumb_path, self.thumb)):
                    try:
                        sts.append(file_status(p, self.cache, t))
                    except Exception:
                        pass
                self.status[self.sel] = board_status(sts)
                self.locked.add(self.sel)
                src = self.thumb or self.tex
                if src:
                    self.strip_pil[self.sel] = strip_image(src.img)
                    if self.layout == "gallery":
                        self.gal_pil[self.sel] = strip_image(src.img, self.GAL_W, self.GAL_H)
                if self.tex is not None:
                    pal = read_palette(self.tex.img)
                    if pal:
                        self.board_pal[self.sel] = pal
                self._refresh_row(self.sel)
                self._update_summary()
        finally:
            pass
        self._refresh_panels()
        self._prefetch_neighbors()
        if self.tab_var.get() == "decor":
            self.dc_enter()

    # ---------- panel refresh ----------
    def _chips(self, frame, tex, path):
        for w in frame.winfo_children():
            w.destroy()
        if not tex:
            return
        fmt = "QOI" if tex.codec == "qoi" else \
            f"{SURFACE_NAMES.get(tex.fmt, tex.fmt)} · {tex.levels} mip"
        meta = load_default_meta(path)
        items = [f"{tex.width} × {tex.height}", fmt]
        items.append(f"Default · {'PNG' if meta['storage'] == 'png' else 'XNB'} "
                     f"{human_size(meta['stored_bytes'])}" if meta else "No default")
        if getattr(frame, "_compact", False):
            tk.Label(frame, text="  \u00b7  ".join(items), font=F["small"], fg=C["muted"],
                     bg=frame.cget("bg"), anchor="w").pack(side="left")
            return
        for t in items:
            tk.Label(frame, text=t, font=F["small"], fg=C["sub"], bg=C["btn"],
                     padx=8, pady=2).pack(side="left", padx=(6, 0))

    def _refresh_panels(self):
        has_tex, has_th = self.tex is not None, self.thumb is not None
        if self.custom and self.tex_path:
            self.title_lbl.config(text=f"File {self.tex_path.stem}")
            try:
                st = file_status(self.tex_path, self.cache, self.tex) if has_tex else None
            except Exception:
                st = None
        elif self.sel is not None:
            self.title_lbl.config(text=f"Board {self.boards[self.sel].name}")
            st = self.status.get(self.sel)
        else:
            self.title_lbl.config(text="No board selected")
            st = "hide"
        if st == "hide":
            self.badge.pack_forget()
        else:
            text, fg, bg = BADGES.get(st, BADGES[None])
            self.badge.config(text=text, fg=fg, bg=bg)
            self.badge.pack(side="left", padx=14)
        set_state([self.btn_prev, self.btn_next], bool(self.boards))

        self.tex_file.config(text=self.tex_path.name if self.tex_path else "")
        self.thumb_file.config(text=self.thumb_path.name if self.thumb_path else "")
        self._chips(self.tex_chips, self.tex, self.tex_path)
        self._chips(self.thumb_chips, self.thumb, self.thumb_path)

        def msg(path, err):
            if not path:
                return "Not found — use Open other .xnb…" if self.boards else \
                    "Open a content folder to begin"
            if self._loading and not err:
                return "Loading\u2026"
            return f"Cannot read: {err}"
        # while the full texture is still decoding, show the (already loaded) thumbnail in its place
        tex_img = self.tex.img if has_tex else (self.thumb.img if (self._loading and has_th) else None)
        self.tex_prev.set_image(tex_img, msg(self.tex_path, self.tex_err))
        self.thumb_prev.set_image(self.thumb.img if has_th else None,
                                  msg(self.thumb_path, self.thumb_err))

        tmeta = load_default_meta(self.tex_path) if self.tex_path else None
        hmeta = load_default_meta(self.thumb_path) if self.thumb_path else None
        set_state([self.b_tex_replace, self.b_tex_export, self.b_tex_setdef], has_tex)
        set_state([self.b_tex_revert], bool(tmeta))
        set_state([self.b_th_replace, self.b_th_export, self.b_th_setdef], has_th)
        set_state([self.b_th_gen], has_th and has_tex)
        set_state([self.b_th_revert], bool(hmeta))
        set_state([self.btn_saveall], bool(self.boards) or bool(self.sm_tex))

        def stored(meta):
            if not meta:
                return "Not saved"
            kind = "PNG" if meta["storage"] == "png" else "XNB copy"
            return f"{kind} · {human_size(meta['stored_bytes'])}"
        saved = (tmeta or hmeta or {}).get("saved_at", "—")
        self.def_vals["saved"].config(text=saved[:16] if saved != "—" else saved)
        self.def_vals["tex"].config(text=stored(tmeta))
        self.def_vals["thumb"].config(text=stored(hmeta))

        def bak(p):
            return bool(p) and p.with_suffix(p.suffix + ".bak").exists()
        b1, b2 = bak(self.tex_path), bak(self.thumb_path)
        self.def_vals["bak"].config(text="Texture + thumbnail" if b1 and b2 else
                                    "Texture only" if b1 else "Thumbnail only" if b2 else
                                    "None yet")
        self._refresh_palette()

    # ---------- board colors ----------
    def _refresh_palette(self):
        self.pal_orig = read_palette(self.tex.img) if self.tex is not None else None
        if self.pal_orig is None:
            self.pal, self._pal_for = None, None
        elif self.pal is None or self._pal_for != self.tex_path:
            self.pal, self._pal_for = list(self.pal_orig), self.tex_path
        self._draw_palette()

    def _pal_changed(self):
        if not self.pal or not self.pal_orig:
            return []
        return [i for i in range(len(PALETTE_SLOTS)) if tuple(self.pal[i]) != tuple(self.pal_orig[i])]

    def _draw_palette(self):
        ok = self.pal is not None
        changed = self._pal_changed()
        for i, (sw, var, ent, was) in enumerate(self.pal_widgets):
            sw.delete("all")
            swd, sh = int(float(sw.cget("width"))), int(float(sw.cget("height")))
            if not ok:
                sw.config(cursor="arrow")
                sw.create_line(4, sh - 4, swd - 4, 4, fill=C["dis"])
                var.set("")
                ent.config(state="disabled")
                was.config(text="")
                continue
            sw.config(cursor="hand2")
            ent.config(state="normal")
            sw.create_rectangle(0, 0, swd + 4, sh + 4, fill=to_hex(self.pal[i]), outline="")
            if i in changed:
                # bottom-right corner shows the color currently in the file
                sw.create_polygon(swd - 2, sh * 0.4, swd - 2, sh - 2, swd * 0.5, sh - 2,
                                  fill=to_hex(self.pal_orig[i]), outline="")
                was.config(text=f"was {to_hex(self.pal_orig[i])}", fg=C["warn"])
            else:
                was.config(text="", fg=C["muted"])
            try:
                editing = base.root.focus_get() is ent
            except Exception:
                editing = False
            if not editing:
                var.set(to_hex(self.pal[i]))
        if not ok:
            self.pal_state.config(
                text="no texture loaded" if self.tex is None else "texture too small",
                fg=C["muted"])
        elif changed:
            self.pal_state.config(text=f"{len(changed)} changed — not applied yet",
                                  fg=C["warn"])
        else:
            self.pal_state.config(text="matches the texture", fg=C["muted"])
        set_state([self.b_pal_apply, self.b_pal_reset], ok and bool(changed))
        set_state([self.b_pal_copy], ok)
        self.v3_schedule()          # 3D preview follows the picked (unapplied) colors
        set_state([self.b_pal_paste], ok)
        self.dc_palette_changed()   # the Decorate tab shares these colors

    def pick_color(self, i):
        if self.pal is None:
            return
        name = PALETTE_SLOTS[i][1]
        rgb, _hex = colorchooser.askcolor(color=to_hex(self.pal[i]), parent=base.root,
                                          title=f"{name} color")
        if rgb:
            self.pal[i] = tuple(int(round(v)) for v in rgb[:3])
            self._draw_palette()

    def commit_color(self, i):
        if self.pal is None:
            return
        var = self.pal_widgets[i][1]
        c = parse_color(var.get())
        if c is None:
            if var.get().strip():
                self.set_status(f"'{var.get().strip()}' is not a color — use #rrggbb or r,g,b")
            var.set(to_hex(self.pal[i]))
            return
        self.pal[i] = c
        var.set(to_hex(c))
        self._draw_palette()

    def reset_colors(self):
        if self.pal_orig:
            self.pal = list(self.pal_orig)
            self._draw_palette()

    def copy_colors(self):
        if not self.pal:
            return
        self.clip = list(self.pal)
        text = ", ".join(to_hex(c) for c in self.pal)
        base.root.clipboard_clear()
        base.root.clipboard_append(text)
        self.set_status(f"Copied board colors: {text}")

    def paste_colors(self):
        if self.pal is None:
            return
        found = None
        try:
            text = base.root.clipboard_get()
            hexes = re.findall(r"#?([0-9a-fA-F]{6})\b", text)
            if len(hexes) >= len(PALETTE_SLOTS):
                found = [parse_color(h) for h in hexes[:len(PALETTE_SLOTS)]]
        except Exception:
            pass
        found = found or (list(self.clip) if self.clip else None)
        if not found:
            self.set_status("Nothing to paste — copy 4 colors first (e.g. from another board)")
            return
        self.pal = list(found)
        self._draw_palette()
        self.set_status("Pasted board colors — click Apply to write them into the texture")

    def apply_colors(self):
        changed = self._pal_changed()
        if not (self.tex and changed):
            return
        names = ", ".join(PALETTE_SLOTS[i][1].lower() for i in changed)
        new = apply_palette(self.tex.img, self.pal)
        self._write(self.tex_path, self.tex, new,
                    f"Applied board colors ({names}) to {self.tex_path.name}")

    # ---------- actions ----------
    def _which(self, which):
        return (self.tex_path, self.tex) if which == "tex" else (self.thumb_path, self.thumb)

    def _write(self, path, tex, new_img, done_msg, after=None):
        if not load_default_meta(path) and messagebox.askyesno(
                "Save default first?",
                f"No default is saved for {path.name} yet.\n\n"
                "Save the current image as the default before replacing it?"):
            try:
                set_default(path, tex)
            except Exception as e:
                messagebox.showerror("Cannot set default", str(e))
                return
        self.busy(True)
        try:
            save_texture(path, new_img, tex)
        except Exception as e:
            messagebox.showerror("Save failed", str(e))
            return
        finally:
            self.busy(False)
        TEXCACHE.remember_saved(path, tex, new_img)
        (after or (lambda: self._load_current(sync=True)))()
        self.set_status(done_msg)

    def replace(self, which, file=None):
        path, tex = self._which(which)
        if not tex:
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
        # let the user position / zoom / rotate / flip the new image; the result
        # always has exactly the original size (the game expects it)
        dlg = AdjustDialog(base.root, new, tex.width, tex.height,
                           f"Adjust image — {path.name} ({tex.width}×{tex.height})")
        base.root.wait_window(dlg)
        if dlg.result is None:
            self.set_status("Replace cancelled")
            return
        new = dlg.result
        if new.size != (tex.width, tex.height):
            new = new.resize((tex.width, tex.height), Image.LANCZOS)
        extra = ""
        if which == "tex" and self.keep_pal.get() and self.pal and new.width >= len(PALETTE_SLOTS):
            new = apply_palette(new, self.pal)
            extra += ", board colors kept"
        self._write(path, tex, new,
                    f"Replaced {path.name} with {Path(file).name}{extra} (backup: {path.name}.bak)")

    def generate_thumb(self):
        if not (self.tex and self.thumb):
            return
        w, h = self.thumb.width, self.thumb.height
        if not messagebox.askyesno(
                "Generate thumbnail",
                f"Replace {self.thumb_path.name} with a {w}×{h} downscale "
                "of the board texture?"):
            return
        new = self.tex.img.resize((w, h), Image.LANCZOS)
        self._write(self.thumb_path, self.thumb, new,
                    f"Thumbnail regenerated from {self.tex_path.name}")

    def export(self, which):
        path, tex = self._which(which)
        if not tex:
            return
        f = filedialog.asksaveasfilename(defaultextension=".png",
                                         initialfile=path.stem + ".png",
                                         filetypes=[("PNG", "*.png")])
        if f:
            tex.img.save(f)
            self.set_status(f"Exported {f}")

    def set_default(self, which):
        path, tex = self._which(which)
        if not tex:
            return
        old = load_default_meta(path)
        if old and not messagebox.askyesno(
                "Overwrite default?",
                f"A default for {path.name} was already set on {old['saved_at']}.\n\n"
                "Replace it with the current image?"):
            return
        self.busy(True)
        try:
            meta = set_default(path, tex)
            self.cache.put(path, meta["pixel_sha256"])
        except Exception as e:
            messagebox.showerror("Cannot set default", str(e))
            return
        finally:
            self.busy(False)
        self._load_current()
        self.set_status(f"Default set for {path.name}: stored as {meta['storage'].upper()}, "
                        f"{human_size(meta['stored_bytes'])}")

    def revert(self, which):
        path, _tex = self._which(which)
        meta = load_default_meta(path) if path else None
        if not meta or not messagebox.askyesno(
                "Revert to default",
                f"Replace {path.name} with the default set on {meta['saved_at']}?\n\n"
                "Your current version will be overwritten."):
            return
        if which == "tex":
            self.pal = None            # show the reverted file's colors, drop unapplied edits
        self.busy(True)
        try:
            revert_to_default(path)
        except Exception as e:
            messagebox.showerror("Revert failed", str(e))
            return
        finally:
            self.busy(False)
        TEXCACHE.invalidate(path)
        self._load_current(sync=True)
        self.set_status(f"Reverted {path.name} to the default from {meta['saved_at']}")

    def open_other(self):
        f = filedialog.askopenfilename(filetypes=[("XNB texture", "*.xnb")])
        if not f:
            return
        self.custom = True
        self.tex_path, self.thumb_path = Path(f), None
        if self.sel is not None:
            self._gal_update(self.sel)
        self._syncing = True
        self.tree.selection_remove(*self.tree.selection())
        self._syncing = False
        self._load_current()
        self.set_status(f"Opened {Path(f).name}")

    def save_all_defaults(self):
        files = [p for b in self.boards for p in (b.texture, b.thumb) if p]
        files += [self.sm_path(k) for k in self.sm_tex]      # speedmeter files too
        todo = [p for p in files if not load_default_meta(p)]
        if not files:
            return
        if not todo:
            messagebox.showinfo("Defaults", "Every texture and thumbnail already has a default.")
            return
        if not messagebox.askyesno(
                "Save all as defaults",
                f"Save the CURRENT images of {len(todo)} file(s) as their defaults?\n"
                f"({len(files) - len(todo)} file(s) that already have a default are skipped.)"):
            return
        base.root.config(cursor="watch")
        errors = []
        for i, p in enumerate(todo, 1):
            self.set_status(f"Saving defaults… {i}/{len(todo)}  {p.name}")
            base.root.update()
            try:
                meta = set_default(p)
                self.cache.put(p, meta["pixel_sha256"])
            except Exception as e:
                errors.append(f"{p.name}: {e}")
        base.root.config(cursor="")
        self.cache.save()
        self.locked.clear()
        if self.sel is not None and not self.custom:
            self._load_current()
        else:
            self._refresh_panels()
        self._start_worker()
        if self.sm_folder:
            self.sm_load(self.sm_folder)
        self.set_status(f"Defaults saved for {len(todo) - len(errors)} file(s)"
                        + (f", {len(errors)} failed" if errors else ""))
        if errors:
            messagebox.showwarning("Some defaults failed", "\n".join(errors[:15]))

    def close(self):
        unsaved = self.dc_unsaved()
        if unsaved and not messagebox.askyesno(
                "Unsaved decorations",
                f"{len(unsaved)} board(s) have decorations that are not saved yet:\n"
                + ", ".join(s.path.stem for s in unsaved[:8]) + "\n\nClose anyway?"):
            return
        self.gen += 1
        self.cache.save()
        base.root.destroy()
