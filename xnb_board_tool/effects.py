"""Effects painted into the board texture: per-sticker effects and a whole-board finish.

The game shows one color texture per board, so effects are baked into its pixels (they look
the same from every angle; they don't react to light). Sizes scale with the texture height,
so a 1920 x 432 board and a smaller one look alike.

Sticker effects work on the sticker already placed on the texture (its own rectangle, with
`sticker_margin` pixels of room around it). The board finish is a set of per-pixel maps,
applied to the whole texture or to any rectangle of it (so dragging a sticker only finishes
the rectangle it moved through).
"""
from __future__ import annotations

from .i18n import N_

import math
import random
from typing import Optional

from PIL import Image, ImageDraw, ImageFilter

# (key, label, short help) in the order shown
STICKER_FX = (
    ("shadow", N_("Shadow"), N_("drop shadow under the sticker")),
    ("border", N_("White border"), N_("die-cut vinyl edge")),
    ("raised", N_("Raised"), N_("embossed, lit from the top left")),
    ("worn", N_("Worn"), N_("scuffed and peeling")),
    ("holo", N_("Holographic"), N_("rainbow foil shimmer")),
)
FINISH_FX = (
    ("grip", N_("Grip tape"), N_("sandpaper grain")),
    ("grain", N_("Matte grain"), N_("fine noise, less flat")),
    ("worn", N_("Worn edges"), N_("grip worn off at the edges: shows the maple wood")),
    ("faded", N_("Faded"), N_("sun-bleached colors")),
    ("gloss", N_("Gloss"), N_("glossy highlight streaks")),
)


def _k(H: int) -> float:
    """Effect size scale: 1 for the game's 432 px high boards."""
    return max(0.15, H / 432.0)


def fx_key(fx: Optional[dict]) -> tuple:
    """Hashable, rounded form of an effect dict (only effects that are on)."""
    if not fx:
        return ()
    return tuple(sorted((k, round(float(v), 3)) for k, v in fx.items() if k != "seed" and v)) + \
        ((("seed", fx.get("seed")),) if any(v for k, v in fx.items() if k != "seed") else ())


def fx_active(fx: Optional[dict]) -> bool:
    """True when a sticker's effect settings turn on at least one effect (the random seed alone does not count).
    """
    return bool(fx) and any(float(v) > 0 for k, v in fx.items() if k != "seed")


def sticker_margin(fx: Optional[dict], H: int) -> int:
    """Pixels the effects may reach beyond the sticker itself (border + shadow)."""
    if not fx_active(fx):
        return 0
    k = _k(H)
    m = 0.0
    if fx.get("border"):
        m += _border_w(fx["border"], k)
    if fx.get("shadow"):
        off, blur = _shadow_geom(fx["shadow"], k)
        m += off + 3 * blur
    return int(math.ceil(m)) + 2


def _border_w(s, k):
    """Width in pixels of the die-cut white border at strength s (0-1), for pattern scale k."""
    return (1.5 + 12.5 * float(s)) * k


def _shadow_geom(s, k):
    """The drop shadow's (offset, blur radius) in pixels at strength s, for pattern scale k."""
    s = float(s)
    return (2 + 7 * s) * k, (1.5 + 4 * s) * k           # offset, blur radius


def _np():
    """numpy, imported on first use so the tool starts quickly."""
    import numpy as np
    return np


def apply_sticker_fx(img: Image.Image, fx: dict, H: int) -> Image.Image:
    """Effects on a placed sticker (RGBA, already including sticker_margin of room)."""
    if not fx_active(fx):
        return img
    np = _np()
    k = _k(H)
    seed = int(fx.get("seed") or 1)
    img = img.convert("RGBA")
    if fx.get("holo"):
        img = _holo(img, float(fx["holo"]), k, seed)
    if fx.get("raised"):
        img = _raised(img, float(fx["raised"]), k)
    if fx.get("border"):
        img = _border(img, float(fx["border"]), k)
    if fx.get("worn"):
        img = _worn(img, float(fx["worn"]), k, seed)
    if fx.get("shadow"):
        img = _shadow(img, float(fx["shadow"]), k)
    del np
    return img


def _holo(img, s, k, seed):
    """Rainbow foil: hue changes along a diagonal, mixed in with 'screen' so darks stay."""
    np = _np()
    w, h = img.size
    a = np.asarray(img, np.float32)
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    period = 140.0 * k
    t = ((xx * 0.8 + yy * 0.6) / period + (seed % 97) / 97.0) % 1.0
    # hue -> rgb (vectorised HSV with s=0.55, v=1)
    hue6 = t * 6.0
    i = np.floor(hue6).astype(np.int32) % 6
    f = hue6 - np.floor(hue6)
    sat = 0.85
    p, q, tt = 1 - sat, 1 - sat * f, 1 - sat * (1 - f)
    r = np.choose(i, [1, q, p, p, tt, 1])
    g = np.choose(i, [tt, 1, 1, q, p, p])
    b = np.choose(i, [p, p, tt, 1, 1, q])
    rainbow = np.stack([r, g, b], -1)
    rgb = a[..., :3]
    luma = rgb @ np.array([0.299, 0.587, 0.114], np.float32)
    foil = rainbow * (luma[..., None] * 0.75 + 70.0)          # foil keeps the art's light and dark
    sheen = np.exp(-(((xx * 0.8 + yy * 0.6) / (period * 2.2)) % 1.0 - 0.5) ** 2 / 0.02)
    foil = foil + sheen[..., None] * 60.0
    mix = 0.8 * s
    a[..., :3] = rgb * (1 - mix) + foil * mix
    return Image.fromarray(np.clip(a, 0, 255).astype(np.uint8), "RGBA")


def _raised(img, s, k):
    """Bevel from the sticker's own shape: lighter on top-left edges, darker on bottom-right."""
    np = _np()
    r = max(1.0, 2.2 * k)
    a = np.asarray(img, np.float32)
    luma = (a[..., :3] @ np.array([0.299, 0.587, 0.114], np.float32)) * (a[..., 3] / 255.0)
    hmap = Image.fromarray(np.clip(a[..., 3] * 0.75 + luma * 0.25, 0, 255).astype(np.uint8), "L")
    height = np.asarray(hmap.filter(ImageFilter.GaussianBlur(r)), np.float32) / 255.0
    gy, gx = np.gradient(height)
    light = -(gx * -0.7071 + gy * -0.7071) * (2.5 * r)     # facing the top-left light: > 0
    a[..., :3] += (np.clip(light, -1, 1) * 260.0 * s)[..., None]
    return Image.fromarray(np.clip(a, 0, 255).astype(np.uint8), "RGBA")


def _border(img, s, k):
    """White die-cut edge: the sticker's shape grown by the border width, under the sticker."""
    np = _np()
    bw = _border_w(s, k)
    sigma = max(0.6, bw / 2.05)                 # a blurred edge crosses 2 % at about 2 sigma
    alpha = img.getchannel("A").point(lambda v: 255 if v > 40 else 0)
    blur = np.asarray(alpha.filter(ImageFilter.GaussianBlur(sigma)), np.float32) / 255.0
    ramp = 0.054 / sigma                        # the blurred edge's slope there: ~1 px anti-aliasing
    grown = np.clip((blur - 0.02) / ramp + 0.5, 0, 1)
    under = np.zeros((img.height, img.width, 4), np.float32)
    under[..., :3] = 250.0
    under[..., 3] = grown * 255.0
    out = Image.fromarray(under.astype(np.uint8), "RGBA")
    out.alpha_composite(img)
    return out


def _noise(w, h, scale, seed):
    """Smooth value noise 0..1 at roughly `scale` px blobs."""
    np = _np()
    rng = np.random.default_rng(seed)
    gw, gh = max(2, int(w / scale) + 2), max(2, int(h / scale) + 2)
    small = Image.fromarray((rng.random((gh, gw)) * 255).astype(np.uint8), "L")
    return np.asarray(small.resize((w, h), Image.BICUBIC), np.float32) / 255.0


def _worn(img, s, k, seed):
    """Scuffs: holes in the sticker (more near its edges) and a slightly paler surface."""
    np = _np()
    w, h = img.size
    a = np.asarray(img, np.float32)
    alpha = a[..., 3] / 255.0
    inner = np.asarray(img.getchannel("A").filter(ImageFilter.GaussianBlur(5 * k)), np.float32) / 255.0
    edge = np.clip((1.0 - inner) * 2.0, 0, 1) * (alpha > 0)
    blobs = _noise(w, h, 9 * k, seed) * 0.65 + _noise(w, h, 2.2 * k, seed + 1) * 0.35
    worn = s * (0.25 + 0.75 * edge)                        # how likely a spot is worn off
    hole = np.clip((blobs - (1.0 - 0.75 * worn)) / 0.06, 0, 1)
    a[..., 3] = alpha * (1.0 - hole) * 255.0
    pale = 0.18 * s * _noise(w, h, 14 * k, seed + 2)
    a[..., :3] = a[..., :3] * (1 - pale[..., None]) + 235.0 * pale[..., None]
    return Image.fromarray(np.clip(a, 0, 255).astype(np.uint8), "RGBA")


def _shadow(img, s, k):
    """Adds a soft drop shadow under a sticker: its alpha shape moved down-right, blurred and darkened by strength
    s, with the sticker composited on top.
    """
    off, blur = _shadow_geom(s, k)
    np = _np()
    alpha = img.getchannel("A")
    sh = Image.new("L", img.size, 0)
    sh.paste(alpha, (int(round(off)), int(round(off))))
    sh = sh.filter(ImageFilter.GaussianBlur(blur))
    opacity = 0.35 + 0.4 * float(s)
    sha = np.asarray(sh, np.float32) * opacity
    out = np.zeros((img.height, img.width, 4), np.float32)
    out[..., 3] = sha
    base = Image.fromarray(np.clip(out, 0, 255).astype(np.uint8), "RGBA")
    base.alpha_composite(img)
    return base


# ---------------------------------------------------------------- recolour
def color_key(c: Optional[dict]) -> tuple:
    """Hashable form of a layer's recolour settings; () when it changes nothing."""
    if not c:
        return ()
    hue = round(float(c.get("hue", 0.0)), 1)
    sat = round(float(c.get("sat", 1.0)), 3)
    ts = round(float(c.get("tint_s", 0.0)), 3)
    tint = tuple(int(v) for v in (c.get("tint") or (255, 255, 255))[:3]) if ts else ()
    if hue == 0 and sat == 1 and not ts:
        return ()
    return (hue, sat, tint, ts)


def recolor(img: Image.Image, c: Optional[dict]) -> Image.Image:
    """Hue shift (degrees), saturation (0..2) and a tint (colour + strength 0..1) on an RGBA image.
    The tint colourises: white becomes the tint colour, black stays black."""
    if not color_key(c):
        return img
    np = _np()
    a = np.asarray(img.convert("RGBA"), np.float32)
    rgb = a[..., :3]
    hue = float(c.get("hue", 0.0))
    if hue:
        # rotation about the grey axis (keeps brightness), as in common image editors
        t = math.radians(hue)
        cs, sn = math.cos(t), math.sin(t)
        k = 1.0 / 3.0
        sq = math.sqrt(k)
        m = np.array([[cs + (1 - cs) * k, k * (1 - cs) - sq * sn, k * (1 - cs) + sq * sn],
                      [k * (1 - cs) + sq * sn, cs + k * (1 - cs), k * (1 - cs) - sq * sn],
                      [k * (1 - cs) - sq * sn, k * (1 - cs) + sq * sn, cs + k * (1 - cs)]], np.float32)
        rgb = rgb @ m.T
    sat = float(c.get("sat", 1.0))
    luma = rgb @ np.array([0.299, 0.587, 0.114], np.float32)
    if sat != 1.0:
        rgb = luma[..., None] + (rgb - luma[..., None]) * sat
    ts = float(c.get("tint_s", 0.0))
    if ts:
        tint = np.array((c.get("tint") or (255, 255, 255))[:3], np.float32)
        col = tint[None, None, :] * (np.clip(luma, 0, 255)[..., None] / 255.0)
        rgb = rgb * (1 - ts) + col * ts
    a[..., :3] = rgb
    return Image.fromarray(np.clip(a, 0, 255).astype(np.uint8), "RGBA")


# ---------------------------------------------------------------- wood
def maple_wood(W: int, H: int, seed: int = 1):
    """Bare maple deck veneer (what shows under worn grip tape): pale cream with soft grain
    lines running along the board, long fibres and gentle tone changes. HxWx3 uint8 array."""
    np = _np()
    k = _k(H)
    rng = np.random.default_rng(seed)
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    warp = (_noise(W, H, 260 * k, seed + 21) - 0.5) * 70 * k + (_noise(W, H, 60 * k, seed + 22) - 0.5) * 12 * k
    period = 26.0 * k * (0.75 + 0.5 * _noise(W, H, 400 * k, seed + 25))   # uneven spacing
    t = (yy + warp) / period
    wobble = _noise(W, H, 120 * k, seed + 23) * 3.0
    ring = 0.5 + 0.5 * np.sin(2 * np.pi * t + wobble)
    ring = ring ** 14 * (0.35 + 0.65 * _noise(W, H, 90 * k, seed + 26))   # faint, broken grain lines
    # long fibres: noise stretched along the board
    fw = max(8, W // 28)
    fib = Image.fromarray((rng.random((H, fw)) * 255).astype(np.uint8), "L").resize((W, H), Image.BICUBIC)
    fib = np.asarray(fib.filter(ImageFilter.GaussianBlur(0.6 * k)), np.float32) / 255.0 - 0.5
    tone = _noise(W, H, 320 * k, seed + 24) - 0.5               # big, soft color changes
    light = np.array([236, 216, 178], np.float32)                # pale maple
    dark = np.array([200, 168, 120], np.float32)
    f = np.clip(0.28 * ring + 0.16 * fib + 0.42 * tone + 0.16, 0, 1)
    rgb = light * (1 - f[..., None]) + dark * f[..., None]
    return np.clip(rgb + (rng.random((H, W, 1), dtype=np.float32) - 0.5) * 5, 0, 255).astype(np.uint8)


# ---------------------------------------------------------------- board finish
class Finish:
    """The whole-board finish as per-pixel maps, in the order things lie on a real deck:
        surface = fade(in) * M + A                (grip tape, matte grain; A is gray)
        worn    = surface * (1 - w) + wood * w    (worn spots show the maple underneath)
        out     = worn * M2 + A2                  (gloss over everything)
    Built once per settings; apply() works on the full texture or any rectangle of it."""

    def __init__(self, W: int, H: int, settings: dict, seed: int = 1, deck_mask: Optional[Image.Image] = None,
                 fields: Optional[dict] = None):
        """Builds the per-pixel maps for the chosen finishes (grip, grain, worn, faded, gloss) at W x H. `fields`
        can share the expensive random fields between Finish objects of the same size; `deck_mask` is the deck's
        shape (worn edges follow it).
        """
        np = _np()
        self.W, self.H = W, H
        self.settings = {k: float(v) for k, v in (settings or {}).items() if v}
        self.key = (W, H, seed, id(deck_mask), tuple(sorted((k, round(v, 3)) for k, v in self.settings.items())))
        self.fade = self.settings.get("faded", 0.0)
        f = fields if fields is not None else {}
        self.fields = f
        k = _k(H)
        M = np.ones((H, W), np.float32)
        A = np.zeros((H, W), np.float32)

        def field(name, make):
            """A named random field from the shared cache, made with `make` the first time."""
            if name not in f:
                f[name] = make()
            return f[name]

        def then(m2, a2):                       # chain: out = (out * M + A) * m2 + a2
            """Chains one more multiply-add step onto the surface maps: out = (out * M + A) * m2 + a2."""
            nonlocal M, A
            M = M * m2
            A = A * m2 + a2

        g = self.settings.get("grip", 0.0)
        if g:
            fine = field("fine", lambda: np.random.default_rng(seed).random((H, W), dtype=np.float32))
            grit = field("grit", lambda: (np.random.default_rng(seed + 7).random((H, W), dtype=np.float32) > 0.97)
                         .astype(np.float32))
            then(1.0 - g * 0.38 * fine, g * 46.0 * grit)
        gr = self.settings.get("grain", 0.0)
        if gr:
            soft = field("soft", lambda: np.asarray(Image.fromarray(
                (np.random.default_rng(seed + 3).random((H, W)) * 255).astype(np.uint8), "L")
                .filter(ImageFilter.GaussianBlur(0.9 * k)), np.float32) / 255.0)
            then(1.0 - gr * 0.05, gr * (soft - 0.5) * 70.0)
        self.M, self.A = M.astype(np.float32), A.astype(np.float32)
        self.wear = self.wood = None
        wo = self.settings.get("worn", 0.0)
        if wo:
            depth = field("depth", lambda: self._depth_field(W, H, k, deck_mask))
            rag = field("rag", lambda: _noise(W, H, 34 * k, seed + 11) * 0.55 + _noise(W, H, 9 * k, seed + 12) * 0.3
                        + _noise(W, H, 2.5 * k, seed + 14) * 0.15)
            scr = field("scratch", lambda: self._scratches(W, H, k, seed + 13) * np.clip(depth * 1.6, 0, 1))
            # grip is gone where we are closer to the outline than the (ragged) wear front
            front = np.minimum(0.9, wo * (0.35 + 1.0 * rag))             # never reaches the middle
            w = np.clip((depth - (1.0 - front)) / 0.04, 0, 1)                   # torn grip: sharp edge
            self.wear = np.maximum(w, scr * np.clip(wo * 1.6 - 0.25, 0, 1)).astype(np.float32)
            self.wood = field("wood", lambda: maple_wood(W, H, seed + 31))
        self.M2 = self.A2 = None
        gl = self.settings.get("gloss", 0.0)
        if gl:
            band = field("band", lambda: self._bands(W, H))
            self.A2 = (gl * 95.0 * band).astype(np.float32)
        self.identity = not self.settings

    @staticmethod
    def _depth_field(W, H, k, mask):
        """How exposed a spot is: 1 at the deck's outline, falling to 0 inside; it reaches
        further in at the nose and tail, which wear the most on a real board."""
        np = _np()
        if mask is None:
            m = Image.new("L", (W, H), 0)
            ImageDraw.Draw(m).rounded_rectangle([0, 0, W - 1, H - 1], radius=H // 2, fill=255)
        else:
            m = mask if mask.size == (W, H) else mask.resize((W, H), Image.BILINEAR)
        near = np.asarray(m.filter(ImageFilter.GaussianBlur(9 * k)), np.float32) / 255.0
        far = np.asarray(m.filter(ImageFilter.GaussianBlur(38 * k)), np.float32) / 255.0
        d = np.maximum(np.clip((1.0 - near) * 2.0, 0, 1), np.clip((1.0 - far) * 1.6, 0, 1) * 0.9)
        x = np.abs(np.arange(W, dtype=np.float32) / max(1, W - 1) - 0.5) * 2      # 0 middle, 1 ends
        ends = np.clip((x - 0.55) / 0.45, 0, 1) ** 1.5
        return np.clip(d * (0.75 + 0.55 * ends[None, :]), 0, 1)

    @staticmethod
    def _scratches(W, H, k, seed):
        """A map of thin random scratches (0-1) for the worn finish, blurred slightly."""
        np = _np()
        rnd = random.Random(seed)
        im = Image.new("L", (W, H), 0)
        d = ImageDraw.Draw(im)
        for _i in range(int(34 * W / 1920.0) + 4):
            x, y = rnd.uniform(0, W), rnd.uniform(0, H)
            ang = rnd.gauss(0, 0.35) + (math.pi if rnd.random() < 0.5 else 0)
            ln = rnd.uniform(25, 140) * k
            d.line([x, y, x + math.cos(ang) * ln, y + math.sin(ang) * ln],
                   fill=int(rnd.uniform(90, 200)), width=max(1, int(round(rnd.uniform(0.6, 1.6) * k))))
        return np.asarray(im.filter(ImageFilter.GaussianBlur(0.5 * k)), np.float32) / 255.0

    @staticmethod
    def _bands(W, H):
        """The soft diagonal light bands of the gloss finish (0 to about 1.2)."""
        np = _np()
        yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
        out = np.zeros((H, W), np.float32)
        for c, wdt, amp in ((0.30, 0.06, 1.0), (0.38, 0.018, 0.7), (0.72, 0.035, 0.55)):
            d = (xx / W - c) + (yy / H - 0.5) * 0.35 * H / W * 4.4
            out += amp * np.exp(-(d / wdt) ** 2)
        return np.clip(out, 0, 1.2)

    def apply(self, img: Image.Image, box=None) -> Image.Image:
        """Finished copy of img, which is the texture (box None) or the rectangle `box` of it."""
        if self.identity:
            return img
        np = _np()
        x0, y0 = (0, 0) if box is None else box[:2]
        a = np.asarray(img.convert("RGBA"), np.float32)
        h, w = a.shape[:2]
        rgb = a[..., :3]
        if self.fade:
            f = self.fade
            luma = rgb @ np.array([0.299, 0.587, 0.114], np.float32)
            rgb = rgb * (1 - 0.55 * f) + luma[..., None] * (0.55 * f)
            rgb = rgb * (1 - 0.28 * f) + np.array([238, 228, 208], np.float32) * (0.28 * f)
        sl = (slice(y0, y0 + h), slice(x0, x0 + w))
        rgb = rgb * self.M[sl][..., None] + self.A[sl][..., None]
        if self.wear is not None:
            wv = self.wear[sl][..., None]
            rgb = rgb * (1.0 - wv) + self.wood[sl].astype(np.float32) * wv
        if self.A2 is not None:
            rgb = rgb + self.A2[sl][..., None]
        a[..., :3] = rgb
        return Image.fromarray(np.clip(a, 0, 255).astype(np.uint8), "RGBA")


__all__ = ["STICKER_FX", "FINISH_FX", "fx_key", "fx_active", "sticker_margin", "apply_sticker_fx", "Finish",
           "maple_wood", "recolor", "color_key"]
