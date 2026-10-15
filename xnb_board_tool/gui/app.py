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
from ..i18n import _, _n
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
from ..settings import BADGES, C, GAL_LAYOUTS, _rgb, titlebar
from .base import F, set_state
from . import base
from .dialogs import AdjustDialog
from .layouts import LayoutsMixin
from .preview3d import Preview3DMixin
from .speedmeter_tab import SpeedmeterMixin
from .speed_tools import SpeedToolsMixin
from .speed_shop import SpeedShopMixin
from .decorate import DecorateMixin
from .shop import ShopMixin
from .shop_settings import ShopSettingsMixin


class App(LayoutsMixin, ShopMixin, ShopSettingsMixin, Preview3DMixin, SpeedmeterMixin, SpeedToolsMixin, SpeedShopMixin, DecorateMixin):
    """The main window: state, loading boards, the board list and all file actions."""

    def __init__(self, start_folder=None):
        """Creates the application state (folder, boards, statuses, the current board, caches, worker queues),
        builds the window for the saved layout and theme, and opens `start_folder` when
        given.
        """
        base.root.title(_("XNB Board Texture Tool"))
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
        """Styles the ttk widgets the app uses (the hidden board lists, scrollbars) in the theme's colours."""
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
        """Shows the tab chosen in tab_var (Boards, Speedmeter or Decorate) and refreshes it. The Skate shop layout
        has its own version.
        """
        if self.layout == "shop":
            return self._shop_switch_tab()
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
        """Shows a message in the status bar at the bottom."""
        self.status_var.set(text)

    def busy(self, on):
        """Shows (or ends) the busy cursor right away, around work that blocks the window."""
        base.root.config(cursor="watch" if on else "")
        base.root.update_idletasks()

    def _path_text(self):
        """(caption, path) for the top bar: follows the selected tab."""
        if self.tab_var.get() == "speed":
            return _("Speedmeter"), (str(self.sm_folder) if self.sm_folder else
                                     _("No speedmeter folder — click Change…"))
        return _("Boards"), (self.path_full if self.folder else _("No folder loaded"))

    def _fit_path(self, _e=None):
        """Shows the folder path in the header, shortened in the middle when it does not fit."""
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
        """The search box got focus: removes the placeholder text."""
        if self._placeholder:
            self._placeholder = False
            self.filter.delete(0, "end")
            self.filter.config(fg=C["text"])

    def _filter_focus_out(self, _e):
        """The search box lost focus while empty: puts the placeholder back."""
        if not self.filter_var.get():
            self._placeholder = True
            self.filter.insert(0, _("Filter boards…"))
            self.filter.config(fg=C["muted"])

    def _filter_text(self):
        """The search text in lower case ('' while the placeholder shows)."""
        return "" if self._placeholder else self.filter_var.get().strip().lower()

    def _filter_enter(self, _e):
        """Enter in the search box: opens the first matching board."""
        kids = self.tree.get_children()
        if kids:
            self.select(int(kids[0]))

    def _row_image(self, i):
        """The picture of a board's list row: its status mark and a small strip of the deck."""
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
        """Updates one board's list row and card after its status or picture changed."""
        if self.tree.exists(str(i)):
            self.tree.item(str(i), image=self._row_image(i))
        self._gal_update(i)

    def _fill_list(self):
        """Rebuilds the board list from the search text and the status filter, keeping the selection; the Wall /
        gallery follow it.
        """
        if not hasattr(self, "tree"):
            return
        q = self._filter_text()
        flt = getattr(self, "_status_filter", None)
        self._syncing = True
        self.tree.delete(*self.tree.get_children())
        shown = 0
        for i, b in enumerate(self.boards):
            if q and q not in b.name.lower():
                continue
            if flt and self.status.get(i) != flt:
                continue
            self.tree.insert("", "end", iid=str(i), text=f"  {b.name}",
                             image=self._row_image(i))
            shown += 1
        n = len(self.boards)
        self.count_lbl.config(text=_("{n} found", n=n) if shown == n else _("{shown} of {n}", shown=shown, n=n))

        if self.sel is not None and self.tree.exists(str(self.sel)) and not self.custom:
            self.tree.selection_set(str(self.sel))
            self.tree.see(str(self.sel))
        self._syncing = False
        self._gal_layout()

    def _on_tree_select(self, _e=None):
        """A board was picked in the list: opens it."""
        if self._syncing:
            return
        s = self.tree.selection()
        if s and (int(s[0]) != self.sel or self.custom):
            self.select(int(s[0]))

    def _update_summary(self):
        """The footer summary (boards, modified, without stock, checking progress) and, in the Skate shop layout,
        the filter counts and the folder chip.
        """
        n = len(self.boards)
        if not n:
            self.summary_lbl.config(text="")
            return
        vals = [self.status.get(i) for i in range(n)]
        text = (_n("{n} board", "{n} boards", n) + " · " + _("{n} modified", n=vals.count('mod')) + " · "
                + _("{n} without default", n=vals.count('none')))
        if self.pending:
            text += " · " + _("checking {done}/{n}…", done=n - self.pending, n=n)
        self.summary_lbl.config(text=text)
        if self.layout == "shop":
            self._shop_chips_refresh()
            self._shop_tabs_refresh()           # the header chip's live counts

    # ---------- loading ----------
    def change_folder(self):
        """Top-bar Change… / Ctrl+O: pick the folder for the tab that is shown."""
        if self.tab_var.get() == "speed":
            self.sm_choose_folder()
        else:
            self.open_folder()

    def open_folder(self):
        """Asks for the game's content folder and loads it; then offers to save stock copies of files that have
        none.
        """
        from .. import diag
        diag.write("asking for the content folder")
        d = filedialog.askdirectory(title=_("Select content folder"), parent=base.root)
        diag.write(f"folder picked: {d!r}")
        if d:
            self.load(Path(d))
            if self.boards:
                base.root.after(300, self._offer_defaults)   # once the window shows the folder

    def _defaults_todo(self):
        """(all files, files without a saved default): board textures, thumbnails, speedmeter."""
        files = [p for b in self.boards for p in (b.texture, b.thumb) if p]
        files += [self.sm_path(k) for k in self.sm_tex]      # speedmeter files too
        return files, [p for p in files if not load_default_meta(p)]

    def _offer_defaults(self):
        """After a board folder is picked: offer to save defaults if some files have none yet."""
        files, todo = self._defaults_todo()
        if not todo:
            return
        if messagebox.askyesno(
                _("Save defaults?"),
                _n("{n} of {total} file in this folder has no saved default yet.",
                   "{n} of {total} files in this folder have no saved default yet.", len(files),
                   n=len(todo), total=len(files)) + "\n\n"
                + _("Save their current images as defaults now? You can then always revert a board to "
                    "how it looks today. Recommended before you change anything.\n\nYou can also do "
                    "this later with \"Save all as defaults\".")):
            self.save_all_defaults(confirm=False)
        else:
            self.set_status(_n("{n} file has no default yet — \"Save all as defaults\" lets you revert it later",
                               "{n} files have no default yet — \"Save all as defaults\" lets you revert them later",
                               len(todo)))

    def load(self, folder: Path):
        """Opens a content folder: scans it for boards, attaches the caches, loads the 3D model and the Speedmeter,
        fills the list, opens the first board and starts the background status check.
        """
        self.busy(True)
        try:
            boards = scan(folder)
        except Exception as e:
            messagebox.showerror(_("Cannot scan folder"), str(e))
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
        self.set_status(_n("{n} board found in {name}", "{n} boards found in {name}", len(boards),
                           name=self.folder.name))
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
        """Starts the background thread that, for every board, makes its list strip and card picture and works out
        whether it matches its stock copy. Results come back through the queue (see _poll).
        """
        self.gen += 1
        gen, boards, cache, q = self.gen, list(self.boards), self.cache, self.q
        have_strip = set(self.strip_pil)
        gw, gh = self.GAL_W, self.GAL_H
        self.pending = len(boards)
        self._update_summary()

        cards = self.cards

        def work():
            """The background job (stops when a newer folder was loaded): per board, the card (from the disk cache
            when possible), the strip, the deck colours and the file statuses.
            """
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
        """Takes the background results off the queue (every 60 ms while work is pending) and updates the list
        rows, cards, summary and the Wall.
        """
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
                    if gal is not None and self.layout in GAL_LAYOUTS \
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
        """Opens board i: makes it the current board, selects it in the list and loads its texture and thumbnail.
        """
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
        """The previous / next board (d = -1 / +1). In the Skate shop layout it moves through the deck fan, which
        loops; on the Speedmeter tab it moves through the parts.
        """
        if self.tab_var.get() == "speed":
            return self.sm_step(d)
        if self.layout == "shop":                     # the fan's decks: the filtered ones (+ the deck on the bench)
            kids = [str(i) for i in self._car_shown()]
        else:
            kids = list(self.tree.get_children())
        if not kids:
            return
        cur = str(self.sel)
        if cur not in kids:
            return self.select(int(kids[0]))
        j = kids.index(cur) + d
        if self.layout == "shop":                     # the deck fan never ends: after the last comes the first
            j %= len(kids)
        if 0 <= j < len(kids):
            self.select(int(kids[j]))

    def _load(self, path):
        """Loads a texture through the shared cache: (TexData, '') or (None, the error text)."""
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
            """The background job: loads the thumbnail first (small, so something shows quickly), then the texture.
            """
            for which, path, have in (("thumb", hp, thumb), ("tex", tp, tex)):   # small one first
                if path and have is None:
                    t, err = self._load(path)
                    lq.put((gen, which, t, err))
            lq.put((gen, "done", None, None))
        threading.Thread(target=work, daemon=True).start()
        base.root.after(10, self._load_poll)

    def _load_poll(self):
        """Takes the loaded thumbnail / texture off the queue (ignoring results of an older selection) and
        refreshes the panels; finishes with _after_load().
        """
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
        """Background thread: loads the boards next to the current one into the cache, so stepping to them is
        instant. Only the newest request is worked on.
        """
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
        """After the current board loaded: works out its status, updates its row and card pictures, the colours,
        the panels and the 3D view, and prefetches the neighbours.
        """
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
                    if self.layout in GAL_LAYOUTS:
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
        """The small detail chips under a file name: size, format and stock copy (or 'No default')."""
        for w in frame.winfo_children():
            w.destroy()
        if not tex:
            return
        fmt = "QOI" if tex.codec == "qoi" else \
            f"{SURFACE_NAMES.get(tex.fmt, tex.fmt)} · {tex.levels} mip"
        meta = load_default_meta(path)
        items = [f"{tex.width} × {tex.height}", fmt]
        items.append(_("Default · {kind} {size}", kind='PNG' if meta['storage'] == 'png' else 'XNB',
                       size=human_size(meta['stored_bytes'])) if meta else _("No default"))
        if getattr(frame, "_compact", False):
            tk.Label(frame, text="  \u00b7  ".join(items), font=F["small"], fg=C["muted"],
                     bg=frame.cget("bg"), anchor="w").pack(side="left")
            return
        for t in items:
            tk.Label(frame, text=t, font=F["small"], fg=C["sub"], bg=C["btn"],
                     padx=8, pady=2).pack(side="left", padx=(6, 0))

    def _refresh_panels(self):
        """Updates every panel for the current board: title and badge, previews (or why there is none), file
        details, button states, the stock copy details and the colours.
        """
        has_tex, has_th = self.tex is not None, self.thumb is not None
        if self.custom and self.tex_path:
            self.title_lbl.config(text=_("File {stem}", stem=self.tex_path.stem))
            try:
                st = file_status(self.tex_path, self.cache, self.tex) if has_tex else None
            except Exception:
                st = None
        elif self.sel is not None:
            self.title_lbl.config(text=_("Board {name}", name=self.boards[self.sel].name))
            st = self.status.get(self.sel)
        else:
            self.title_lbl.config(text=_("No board selected"))
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
            """What a preview says when it has no image: not found, loading, or the read error."""
            if not path:
                return _("Not found — use Open other .xnb…") if self.boards else \
                    _("Open a content folder to begin")
            if self._loading and not err:
                return _("Loading…")
            return _("Cannot read: {err}", err=err)
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
            """How a stock copy is stored, for the defaults details ('PNG - 412 KB')."""
            if not meta:
                return _("Not saved")
            kind = "PNG" if meta["storage"] == "png" else _("XNB copy")
            return f"{kind} · {human_size(meta['stored_bytes'])}"
        saved = (tmeta or hmeta or {}).get("saved_at", "—")
        self.def_vals["saved"].config(text=saved[:16] if saved != "—" else saved)
        self.def_vals["tex"].config(text=stored(tmeta))
        self.def_vals["thumb"].config(text=stored(hmeta))

        def bak(p):
            """True when a .bak backup of the file exists."""
            return bool(p) and p.with_suffix(p.suffix + ".bak").exists()
        b1, b2 = bak(self.tex_path), bak(self.thumb_path)
        self.def_vals["bak"].config(text=_("Texture + thumbnail") if b1 and b2 else
                                    _("Texture only") if b1 else _("Thumbnail only") if b2 else
                                    _("None yet"))
        self._refresh_palette()

    # ---------- board colors ----------
    def _refresh_palette(self):
        """Reads the board colours from the texture; colours picked but not written are kept while the same texture
        stays open.
        """
        self.pal_orig = read_palette(self.tex.img) if self.tex is not None else None
        if self.pal_orig is None:
            self.pal, self._pal_for = None, None
        elif self.pal is None or self._pal_for != self.tex_path:
            self.pal, self._pal_for = list(self.pal_orig), self.tex_path
        self._draw_palette()

    def _pal_changed(self):
        """The colour slots that differ from the texture (picked but not written yet)."""
        if not self.pal or not self.pal_orig:
            return []
        return [i for i in range(len(PALETTE_SLOTS)) if tuple(self.pal[i]) != tuple(self.pal_orig[i])]

    def _draw_palette(self):
        """Draws the colour swatches and hex fields (with what each was, when changed) and updates everything that
        shows the colours (3D view, flat decks, Wall card, Save button).
        """
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
                was.config(text=_("was {v}", v=to_hex(self.pal_orig[i])), fg=C["warn"])
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
                text=_("no texture loaded") if self.tex is None else _("texture too small"),
                fg=C["muted"])
        elif changed:
            self.pal_state.config(text=_("{n} changed — not applied yet", n=len(changed)),
                                  fg=C["warn"])
        else:
            self.pal_state.config(text=_("matches the texture"), fg=C["muted"])
        set_state([self.b_pal_apply, self.b_pal_reset], ok and bool(changed))
        set_state([self.b_pal_copy], ok)
        self.v3_schedule()          # 3D preview follows the picked (unapplied) colors
        set_state([self.b_pal_paste], ok)
        self.dc_palette_changed()   # the Decorate tab shares these colors
        self._shop_refresh()        # Skate shop: the flat deck views and the bench bar

    def pick_color(self, i):
        """Opens the colour chooser for colour slot i."""
        if self.pal is None:
            return
        name = _(PALETTE_SLOTS[i][1])
        rgb, _hex = colorchooser.askcolor(color=to_hex(self.pal[i]), parent=base.root,
                                          title=_("{name} color", name=name))
        if rgb:
            self.pal[i] = tuple(int(round(v)) for v in rgb[:3])
            self._draw_palette()

    def commit_color(self, i):
        """A hex / r,g,b value typed into slot i's field: uses it, or puts the old value back with a hint when it
        is not a colour.
        """
        if self.pal is None:
            return
        var = self.pal_widgets[i][1]
        c = parse_color(var.get())
        if c is None:
            if var.get().strip():
                self.set_status(_("'{v}' is not a color — use #rrggbb or r,g,b", v=var.get().strip()))
            var.set(to_hex(self.pal[i]))
            return
        self.pal[i] = c
        var.set(to_hex(c))
        self._draw_palette()

    def reset_colors(self):
        """Revert: the colours back to the ones in the texture."""
        if self.pal_orig:
            self.pal = list(self.pal_orig)
            self._draw_palette()

    def copy_colors(self):
        """Copies the four colours (also to the clipboard as hex codes)."""
        if not self.pal:
            return
        self.clip = list(self.pal)
        text = ", ".join(to_hex(c) for c in self.pal)
        base.root.clipboard_clear()
        base.root.clipboard_append(text)
        self.set_status(_("Copied board colors: {text}", text=text))

    def paste_colors(self):
        """Pastes four colours from the clipboard (hex codes) or from the last copy."""
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
            self.set_status(_("Nothing to paste — copy 4 colors first (e.g. from another board)"))
            return
        self.pal = list(found)
        self._draw_palette()
        self.set_status(_("Pasted board colors — click Apply to write them into the texture"))

    def apply_colors(self):
        """Save board: writes the changed colours into the texture file."""
        changed = self._pal_changed()
        if not (self.tex and changed):
            return
        names = ", ".join(_(PALETTE_SLOTS[i][1]).lower() for i in changed)
        new = apply_palette(self.tex.img, self.pal)
        self._write(self.tex_path, self.tex, new,
                    _("Applied board colors ({names}) to {name}", names=names, name=self.tex_path.name))

    # ---------- actions ----------
    def _which(self, which):
        """The (path, TexData) of the texture ('tex') or the thumbnail ('thumb')."""
        return (self.tex_path, self.tex) if which == "tex" else (self.thumb_path, self.thumb)

    def _write(self, path, tex, new_img, done_msg, after=None):
        """Writes a new image into a texture file: offers to save a stock copy first when there is none, keeps a
        .bak, writes, reloads, and shows done_msg; `after` runs when it is done.
        """
        if not load_default_meta(path) and messagebox.askyesno(
                _("Save default first?"),
                _("No default is saved for {name} yet.\n\nSave the current image as the "
                  "default before replacing it?", name=path.name)):
            try:
                set_default(path, tex)
            except Exception as e:
                messagebox.showerror(_("Cannot set default"), str(e))
                return
        self.busy(True)
        try:
            save_texture(path, new_img, tex)
        except Exception as e:
            messagebox.showerror(_("Save failed"), str(e))
            return
        finally:
            self.busy(False)
        TEXCACHE.remember_saved(path, tex, new_img)
        (after or (lambda: self._load_current(sync=True)))()
        self.set_status(done_msg)

    def replace(self, which, file=None):
        """Replaces the texture or thumbnail with an image file (asked for, or dropped): the Adjust window places
        it, the colours can be kept, then it is written.
        """
        path, tex = self._which(which)
        if not tex:
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
        # let the user position / zoom / rotate / flip the new image; the result
        # always has exactly the original size (the game expects it)
        dlg = AdjustDialog(base.root, new, tex.width, tex.height,
                           _("Adjust image — {name} ({w}×{h})", name=path.name, w=tex.width, h=tex.height))
        base.root.wait_window(dlg)
        if dlg.result is None:
            self.set_status(_("Replace cancelled"))
            return
        new = dlg.result
        if new.size != (tex.width, tex.height):
            new = new.resize((tex.width, tex.height), Image.LANCZOS)
        extra = ""
        if which == "tex" and self.keep_pal.get() and self.pal and new.width >= len(PALETTE_SLOTS):
            new = apply_palette(new, self.pal)
            extra += _(", board colors kept")
        self._write(path, tex, new,
                    _("Replaced {name} with {file}{extra} (backup: {name}.bak)", name=path.name,
                      file=Path(file).name, extra=extra))

    def generate_thumb(self):
        """Makes the thumbnail a downscale of the texture (after asking)."""
        if not (self.tex and self.thumb):
            return
        w, h = self.thumb.width, self.thumb.height
        if not messagebox.askyesno(
                _("Generate thumbnail"),
                _("Replace {name} with a {w}×{h} downscale of the board texture?", name=self.thumb_path.name, w=w, h=h)):
            return
        new = self.tex.img.resize((w, h), Image.LANCZOS)
        self._write(self.thumb_path, self.thumb, new,
                    _("Thumbnail regenerated from {name}", name=self.tex_path.name))

    def export(self, which):
        """Saves the texture or thumbnail as a PNG."""
        path, tex = self._which(which)
        if not tex:
            return
        f = filedialog.asksaveasfilename(defaultextension=".png",
                                         initialfile=path.stem + ".png",
                                         filetypes=[("PNG", "*.png")])
        if f:
            tex.img.save(f)
            self.set_status(_("Exported {f}", f=f))

    def set_default(self, which):
        """Saves the texture or thumbnail as its stock copy (asking first when one exists)."""
        path, tex = self._which(which)
        if not tex:
            return
        old = load_default_meta(path)
        if old and not messagebox.askyesno(
                _("Overwrite default?"),
                _("A default for {name} was already set on {saved_at}.\n\nReplace it with the "
                  "current image?", name=path.name, saved_at=old['saved_at'])):
            return
        self.busy(True)
        try:
            meta = set_default(path, tex)
            self.cache.put(path, meta["pixel_sha256"])
        except Exception as e:
            messagebox.showerror(_("Cannot set default"), str(e))
            return
        finally:
            self.busy(False)
        self._load_current()
        self.set_status(_("Default set for {name}: stored as {v}, {v2}", name=path.name, v=meta['storage'].upper(), v2=human_size(meta['stored_bytes'])))

    def revert(self, which):
        """Puts the texture or thumbnail back to its stock copy (after asking)."""
        path, _tex = self._which(which)
        meta = load_default_meta(path) if path else None
        if not meta or not messagebox.askyesno(
                _("Revert to default"),
                _("Replace {name} with the default set on {saved_at}?\n\nYour current version "
                  "will be overwritten.", name=path.name, saved_at=meta['saved_at'])):
            return
        if which == "tex":
            self.pal = None            # show the reverted file's colors, drop unapplied edits
        self.busy(True)
        try:
            revert_to_default(path)
        except Exception as e:
            messagebox.showerror(_("Revert failed"), str(e))
            return
        finally:
            self.busy(False)
        TEXCACHE.invalidate(path)
        self._load_current(sync=True)
        self.set_status(_("Reverted {name} to the default from {saved_at}", name=path.name, saved_at=meta['saved_at']))

    def open_other(self):
        """Opens any texture .xnb outside the board list (a 'custom' file; the list selection is cleared)."""
        f = filedialog.askopenfilename(filetypes=[(_("XNB texture"), "*.xnb")])
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
        self.set_status(_("Opened {name}", name=Path(f).name))

    def save_all_defaults(self, confirm=True):
        """Saves a stock copy of every texture and thumbnail that has none (after asking, unless confirm=False),
        with a progress cursor; reports files that failed.
        """
        files, todo = self._defaults_todo()
        if not files:
            return
        if not todo:
            messagebox.showinfo(_("Defaults"), _("Every texture and thumbnail already has a default."))
            return
        if confirm and not messagebox.askyesno(
                _("Save all as defaults"),
                _n("Save the CURRENT image of {n} file as its default?",
                   "Save the CURRENT images of {n} files as their defaults?", len(todo))
                + "\n" + _n("({n} file that already has a default is skipped.)",
                            "({n} files that already have a default are skipped.)", len(files) - len(todo))):
            return
        base.root.config(cursor="watch")
        errors = []
        for i, p in enumerate(todo, 1):
            self.set_status(_("Saving defaults… {i}/{n}  {name}", i=i, n=len(todo), name=p.name))
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
        self.set_status(_n("Default saved for {n} file", "Defaults saved for {n} files", len(todo) - len(errors))
                        + (_(", {n} failed", n=len(errors)) if errors else ""))
        if errors:
            messagebox.showwarning(_("Some defaults failed"), "\n".join(errors[:15]))

    def close(self):
        """Closing the window: asks first when decorations are unsaved, then saves the caches and quits."""
        unsaved = self.dc_unsaved()
        if unsaved and not messagebox.askyesno(
                _("Unsaved decorations"),
                _n("{n} board has decorations that are not saved yet:",
                   "{n} boards have decorations that are not saved yet:", len(unsaved))
                + "\n" + ", ".join(s.path.stem for s in unsaved[:8]) + "\n\n" + _("Close anyway?")):

            return
        self.gen += 1
        self.cache.save()
        base.root.destroy()
