"""The 3D board preview card: smooth rotation, zoom and background rendering."""
from __future__ import annotations

import threading
import time

from PIL import Image, ImageTk

from ..xnb import parse_xnb, read_str
from ..boards import apply_palette
from ..board3d import find_board_model, load_board_model, render_board
from ..settings import C, _rgb
from .base import F
from . import base


class Preview3DMixin:
    """The 3D board preview card: smooth rotation, zoom and background rendering. Mixed into App."""

    # ---------- 3D board preview ----------
    def v3_load_model(self):
        self.v3_model, self.v3_err = None, ""
        found = find_board_model(self.folder)
        if found is None:
            self.v3_err = "Board model not found (Content\\Models\\Export\\Board.xnb + Board.bin.xnb)."
            return
        try:
            import numpy  # noqa: F401
        except ImportError:
            self.v3_err = "The 3D preview needs numpy:  pip install numpy"
            return
        try:
            self.v3_model = load_board_model(*found)
        except Exception as e:
            self.v3_err = f"Cannot read the board model: {e}"

    def _v3_screws_default(self):
        """The game shows screws when Models/Resources/Board/Screws/<board>.xnb says something other than '0'."""
        if self.custom or self.sel is None or not self.tex_path:
            return True
        p = self.tex_path.parent / "Screws" / f"{self.boards[self.sel].name}.xnb"
        try:
            d = p.read_bytes()
            s, _ = read_str(d, parse_xnb(d).content)
            return s.strip() != "0"
        except Exception:
            return False

    def v3_view(self, yaw, pitch, zoom=None):
        """Smoothly turn to a preset view."""
        # take the short way round
        self.v3_t_yaw = self.v3_yaw + ((yaw - self.v3_yaw + 180) % 360 - 180)
        self.v3_t_pitch = pitch
        if zoom is not None:
            self.v3_t_zoom = zoom
        self._v3_vel = (0.0, 0.0)
        self._v3_animate()

    def open_decorate(self):
        """Boards tab -> Decorate tab, on the same board."""
        self.tab_var.set("decor")
        self.switch_tab()

    def _v3_part_at(self, x, y):
        """Board-color slot (0..3) of the part under the cursor in the last sharp frame, or None."""
        from ..board3d import pick_texel
        info = self._v3_info
        if not info:
            return None
        s = self._v3_info_scale
        t = pick_texel(info, int(x * s), int(y * s), 2)
        if t is not None and t[1] == 0 and t[0] < 4:
            return t[0]
        return None

    def _v3_hover(self, e):
        if self._v3_dragging:
            return
        k = self._v3_part_at(e.x, e.y)
        self.v3_canvas.config(cursor="hand2" if k is not None else "fleur")
        if k is not None and self.pal:
            from ..boards import PALETTE_SLOTS, to_hex
            self.set_status(f"{PALETTE_SLOTS[k][1]}  {to_hex(self.pal[k])}  \u2014 click to change")

    def _v3_press(self, e):
        self._v3_down = (e.x, e.y)
        self._v3_last = (e.x, e.y, time.perf_counter())
        self._v3_vel = (0.0, 0.0)
        self._v3_dragging = True

    def _v3_drag(self, e):
        if not self._v3_last:
            return
        x0, y0, t0 = self._v3_last
        now = time.perf_counter()
        dx, dy = e.x - x0, e.y - y0
        self._v3_last = (e.x, e.y, now)
        self.v3_t_yaw += dx * 0.6
        self.v3_t_pitch = max(-89.0, min(89.0, self.v3_t_pitch + dy * 0.5))
        dt = max(1e-3, now - t0)
        # degrees per 16 ms frame, smoothed - used for the coast after release
        vx, vy = self._v3_vel
        self._v3_vel = (vx * 0.5 + 0.5 * dx * 0.6 * 0.016 / dt, vy * 0.5 + 0.5 * dy * 0.5 * 0.016 / dt)
        self._v3_animate()

    def _v3_release(self, e=None):
        self._v3_dragging = False
        down, self._v3_down = self._v3_down, None
        if e is not None and down and abs(e.x - down[0]) + abs(e.y - down[1]) <= 3:
            k = self._v3_part_at(e.x, e.y)
            if k is not None:
                self._v3_vel = (0.0, 0.0)
                self._v3_last = None
                self.pick_color(k)               # same as clicking the color swatch
                return
        if self._v3_last and time.perf_counter() - self._v3_last[2] > 0.08:
            self._v3_vel = (0.0, 0.0)          # mouse had stopped before release: no coast
        self._v3_last = None
        self._v3_animate()

    def _v3_zoom(self, d):
        self.v3_t_zoom = max(0.5, min(4.0, self.v3_t_zoom * (1.15 if d > 0 else 1 / 1.15)))
        self._v3_animate()

    def _v3_animate(self):
        if self._v3_tick is None:
            self._v3_tick = base.root.after(0, self._v3_step)

    def _v3_step(self):
        """~60 fps animation tick: ease toward the target, coast after release."""
        self._v3_tick = None
        vx, vy = self._v3_vel
        if not self._v3_dragging and (abs(vx) > 0.02 or abs(vy) > 0.02):
            self.v3_t_yaw += vx
            self.v3_t_pitch = max(-89.0, min(89.0, self.v3_t_pitch + vy))
            self._v3_vel = (vx * 0.90, vy * 0.90)
        else:
            self._v3_vel = (0.0, 0.0) if not self._v3_dragging else self._v3_vel
        k = 0.45
        self.v3_yaw += (self.v3_t_yaw - self.v3_yaw) * k
        self.v3_pitch += (self.v3_t_pitch - self.v3_pitch) * k
        self.v3_zoom += (self.v3_t_zoom - self.v3_zoom) * k
        moving = (self._v3_dragging or abs(self.v3_t_yaw - self.v3_yaw) > 0.05
                  or abs(self.v3_t_pitch - self.v3_pitch) > 0.05
                  or abs(self.v3_t_zoom - self.v3_zoom) > 0.002 or self._v3_vel != (0.0, 0.0))
        if moving:
            if not self._v3_busy:
                self._v3_start(True)
            self._v3_tick = base.root.after(16, self._v3_step)
        else:
            self.v3_yaw, self.v3_pitch, self.v3_zoom = self.v3_t_yaw, self.v3_t_pitch, self.v3_t_zoom
            self.v3_schedule()                    # one sharp full-resolution frame

    def v3_schedule(self, fast=False):
        """Full-quality frame soon (colors, texture, toggles, resize)."""
        if not hasattr(self, "v3_canvas"):
            return
        if self._v3_job:
            base.root.after_cancel(self._v3_job)
        self._v3_job = base.root.after(40, lambda: self._v3_start(False))

    def _v3_message(self, text):
        self._v3_info = None
        c = self.v3_canvas
        c.delete("all")
        self._v3_item = None
        c.create_text(max(100, c.winfo_width() // 2), max(60, c.winfo_height() // 2), text=text,
                      fill=C["muted"], font=F["body"], width=max(150, c.winfo_width() - 40))

    def _v3_texture(self):
        """Board texture (with picked colors) as a numpy array, cached until it changes."""
        import numpy as np
        changed = bool(self.pal) and bool(self._pal_changed())
        key = (id(self.tex), tuple(map(tuple, self.pal)) if changed else None)
        if key != self._v3_texkey:
            img = apply_palette(self.tex.img, self.pal) if changed else self.tex.img
            self._v3_texarr = np.ascontiguousarray(np.asarray(img.convert("RGB")))
            self._v3_texkey, self._v3_texref = key, self.tex
        return self._v3_texarr

    def _v3_start(self, fast):
        self._v3_job = None
        if self.tab_var.get() != "boards":
            return
        if self.v3_model is None:
            self._v3_message(self.v3_err or "Open a content folder to see the board in 3D")
            self.v3_note.config(text="")
            return
        if self.tex is None:
            self._v3_message("Loading\u2026" if self._loading else "No board texture loaded")
            return
        if self._v3_busy:
            if not fast:
                self._v3_again = True              # sharp frame once the current one is done
            return
        c = self.v3_canvas
        # always fill the whole canvas so the board stays centered; very large canvases are
        # rendered at a lower resolution and scaled up instead of being cut off
        W = max(200, c.winfo_width())
        H = max(120, c.winfo_height() if c.winfo_height() > 20 else int(float(c.cget("height"))))
        from ..board3d import gpu_active
        # the CPU renderer is capped at about 1400x800 (larger canvases are scaled up); the GPU
        # draws up to about 1920x1200 directly
        cap = 1920 * 1200 if gpu_active() else 1400 * 800
        budget = min(1.0, (cap / float(W * H)) ** 0.5)
        s = budget * (self._v3_scale if fast else 1.0)
        key = (self.v3_yaw, self.v3_pitch, self.v3_zoom, W, H, self.v3_screws.get(), self.v3_outline.get(), C["bg"])
        if not fast and self._v3_info is not None and getattr(self, "_v3_info_key", None) == key \
                and self.v3_model is getattr(self, "_v3_info_model", None):
            # only the texture or colors changed: recolor the last frame instead of rendering again
            from ..board3d import retexture
            try:
                self._v3_size = (W, H)
                self._v3_display(retexture(self._v3_info, self._v3_texture()))
                return
            except Exception:
                self._v3_info = None
        args = (self.v3_model, self._v3_texture(), self.v3_yaw, self.v3_pitch, self.v3_zoom,
                max(1, int(W * s)), max(1, int(H * s)), self.v3_screws.get(), self.v3_outline.get(),
                _rgb(C["bg"])[:3])
        self._v3_busy, self._v3_result, self._v3_size, self._v3_fast = True, None, (W, H), fast
        self._v3_t0 = time.perf_counter()

        info = {} if not fast else None
        self._v3_pending_info = (info, (max(1, int(W * s))) / float(W), key, self.v3_model)

        def work():
            try:
                self._v3_result = render_board(*args, info=info)
            except Exception as e:
                self._v3_result = e
        threading.Thread(target=work, daemon=True).start()
        base.root.after(4, self._v3_poll)

    def _v3_poll(self):
        if self._v3_result is None:
            base.root.after(4, self._v3_poll)
            return
        res, self._v3_result = self._v3_result, None
        self._v3_busy = False
        if self._v3_fast:
            # adapt the moving resolution so each frame takes ~20 ms on this PC
            ms = (time.perf_counter() - self._v3_t0) * 1000
            self._v3_scale = max(0.35, min(1.0, self._v3_scale * min(1.25, max(0.8, (20 / max(ms, 1)) ** 0.5))))
        if isinstance(res, Exception):
            self._v3_message(f"3D preview failed: {res}")
        else:
            info, scale, key, model = getattr(self, "_v3_pending_info", (None, 1.0, None, None))
            self._v3_info = info if info else None          # picking + recoloring use sharp frames only
            self._v3_info_scale, self._v3_info_key, self._v3_info_model = scale, key, model
            self._v3_display(res)
        if self._v3_again and self._v3_tick is None:
            self._v3_again = False
            self._v3_start(False)

    def _v3_display(self, res):
        W, H = self._v3_size
        if res.size != (W, H):
            res = res.resize((W, H), Image.BILINEAR)
        c = self.v3_canvas
        if self._v3_photo is not None and self._v3_item is not None and \
                (self._v3_photo.width(), self._v3_photo.height()) == (W, H):
            self._v3_photo.paste(res)        # update in place: no flicker, no reallocation
        else:
            self._v3_photo = ImageTk.PhotoImage(res)
            c.delete("all")
            self._v3_item = c.create_image(0, 0, anchor="nw", image=self._v3_photo)
        from .. import board3d
        note = "Game's board model \u00b7 colors from the texture's first pixels"
        if board3d.LAST_RENDERER == "gpu":
            note += " \u00b7 GPU"
        if self.pal and self._pal_changed():
            note += " \u00b7 showing picked colors (not applied yet)"
        self.v3_note.config(text=note)
