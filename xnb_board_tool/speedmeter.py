"""HUD speedometer: files, game font and the in-game preview renderer."""
from __future__ import annotations

from .i18n import N_

import io
import struct
from pathlib import Path
from typing import Optional

from PIL import Image, ImageChops, ImageDraw

from .common import XnbError, check_size
from .xnb import FOURCC, _dds, parse_xnb, read7


# --------------------------------------------------------------------------
#  Speedometer (Content/Textures/HUD/SpeedMeter) - files and in-game preview
# --------------------------------------------------------------------------
# Reverse-engineered from STUNTBOOST.dll (SE.SpeedMeter.DrawInner) and the
# Effects/D2/SpeedMeter shader. The HUD is drawn on a 3840 x 2160 virtual screen.
SPEEDMETER_PARTS = [
    ("Texture", N_("Bar texture"), N_("The color/pattern seen through the whole bar (scrolls with speed)")),
    ("BarBeginning", N_("Bar beginning"), N_("First section of the bar, above the unit text")),
    ("Block", N_("Block"), N_("Repeated every 164 px to make the bar longer")),
    ("CMS", N_("CM/S text"), N_("Unit text in normal mode")),
    ("MMS", N_("MM/S text"), N_("Unit text in precise mode")),
]


SM_SCREEN = (3840, 2160)


SM_MARGIN = 64          # SpeedMeter.margin


SM_DIGIT_STEP = 180     # distance between the digits


SM_BLOCK_STEP = 164     # distance between blocks


SM_PX_PER_CMS = 41      # bar length per cm/s


SM_OUTLINE = [(0, 12), (4, 4), (-4, 4), (4, -4), (-4, -4)]   # black passes, then white at (0,0)


def find_speedmeter_folder(root: Path) -> Optional[Path]:
    """Finds .../Textures/HUD/SpeedMeter from a content folder or any folder inside it."""
    root = Path(root).resolve()
    tail = Path("Textures") / "HUD" / "SpeedMeter"
    for base in [root] + list(root.parents):
        for cand in (base / tail, base / "Content" / tail):
            if (cand / "Texture.xnb").exists():
                return cand
        if base.name.lower() == "speedmeter" and (base / "Texture.xnb").exists():
            return base
    try:   # last resort: search below the chosen folder (bounded)
        for p in root.rglob("SpeedMeter"):
            if (p / "Texture.xnb").exists() and (p / "Block.xnb").exists():
                return p
    except OSError:
        pass
    return None


def _mirror_tile(tex: Image.Image) -> Image.Image:
    """2W x 2H tile that repeats like Mirror texture addressing."""
    w, h = tex.size
    t = Image.new("RGBA", (w * 2, h * 2))
    t.paste(tex, (0, 0))
    t.paste(tex.transpose(Image.FLIP_LEFT_RIGHT), (w, 0))
    t.paste(tex.transpose(Image.FLIP_TOP_BOTTOM), (0, h))
    t.paste(tex.transpose(Image.ROTATE_180), (w, h))
    return t


def _mirror_sample(tile: Image.Image, tw: int, th: int, x0: int, y0: int, size) -> Image.Image:
    """Back-texture as seen on screen: screen pixel (x0+i, y0+j) shows texture (u, v) = (i+x0-ox, ...).
    x0/y0 are the texture coordinates of the region's top-left pixel."""
    W, H = size
    pw, ph = tw * 2, th * 2
    out = Image.new("RGBA", (W, H))
    sx, sy = (-x0) % pw, (-y0) % ph
    for yy in range(sy - ph, H, ph):
        for xx in range(sx - pw, W, pw):
            out.paste(tile, (xx, yy))
    return out


def _cut_mask(size, ox, oy, region_x, region_y, speed_px):
    """Shader discard: keep pixels where (x-ox-590) + 0.4*(y-oy-1956) <= speed."""
    W, H = size
    m = Image.new("L", (W, H), 0)
    if speed_px >= 1e9:
        m.paste(255, (0, 0, W, H))
        return m
    def x_at(y):   # boundary x (region coords) at region row y
        """The x position (in region coordinates) of the bar's slanted cut at row y, from the shader's formula for
        the current speed.
        """
        sy = y + region_y
        return (speed_px + 590 + ox - 0.4 * (sy - oy - 1956)) - region_x
    ImageDraw.Draw(m).polygon([(0, 0), (x_at(0), 0), (x_at(H), H), (0, H)], fill=255)
    return m


def load_spritefont(path: Path) -> dict:
    """Reads a MonoGame SpriteFont .xnb (uncompressed). Returns
    {'tex': RGBA image, 'line': int, 'glyphs': {char: [bounds, crop, lsb, width, rsb]}}."""
    data = Path(path).read_bytes()
    info = parse_xnb(data)
    if "SpriteFontReader" not in info.reader:
        raise XnbError("not a SpriteFont")
    p = info.content
    _t, p = read7(data, p)                                   # Texture2D
    fmt, w, h, levels = struct.unpack_from("<4i", data, p)
    p += 16
    check_size(w, h)
    size, = struct.unpack_from("<i", data, p)
    raw = data[p + 4:p + 4 + size]
    if fmt == 0:
        tex = Image.frombytes("RGBa", (w, h), raw).convert("RGBA")
    elif fmt in FOURCC:
        tex = Image.open(io.BytesIO(_dds(w, h, FOURCC[fmt], raw))).convert("RGBA")
    else:
        raise XnbError(f"unsupported font texture format {fmt}")
    for _i in range(max(1, levels)):
        sz, = struct.unpack_from("<i", data, p)
        p += 4 + sz

    def rlist(p, kind):
        """Reads one list of a SpriteFont XNB at offset p: characters (UTF-8) for kind 'char', else fixed-size
        records packed as `kind` (a struct format). Returns (list, offset after it).
        """
        _t, p = read7(data, p)
        n, = struct.unpack_from("<i", data, p)
        p += 4
        if n < 0 or n > 100000:
            raise XnbError("bad SpriteFont list")
        out = []
        for _i in range(n):
            if kind == "char":
                b = data[p]
                ln = 1 if b < 0x80 else 2 if b < 0xE0 else 3 if b < 0xF0 else 4
                out.append(data[p:p + ln].decode("utf-8"))
                p += ln
            else:
                out.append(list(struct.unpack_from(kind, data, p)))
                p += struct.calcsize(kind)
        return out, p
    bounds, p = rlist(p, "<4i")
    crops, p = rlist(p, "<4i")
    chars, p = rlist(p, "char")
    line, _spacing = struct.unpack_from("<if", data, p)
    p += 8
    kern, p = rlist(p, "<3f")
    glyphs = {c: [b, cr, k[0], k[1], k[2]] for c, b, cr, k in zip(chars, bounds, crops, kern)}
    return {"tex": tex, "line": line, "glyphs": glyphs}


def fix_sinkingship_italic(font: dict) -> dict:
    """Same tweaks the game applies after loading (SE.UIAssets.FixSinkingShipItalicFont)."""
    g = font["glyphs"]
    any_glyph = next(iter(g.values()))
    scale = any_glyph[1][3] / 107.0          # DefaultCharacterHeight / 107
    if "7" in g:
        g["7"][2] += 20
    if "1" in g:
        g["1"][2] += 20
    for i in range(10):
        c = str(i)
        if c in g:
            g[c][2] -= 3
            g[c][4] -= 3
    for c, amount in (("0", 2), ("3", -1), ("5", 2), ("6", 1), ("7", 11), ("8", 5), ("9", 2)):
        if c in g:
            g[c][3] += -amount * scale
    return font


def find_digit_font(speedmeter_folder: Optional[Path]) -> Optional[Path]:
    """Finds the game's digit font (Content/Fonts/SinkingShip/VeryBigItalicNumeric.xnb) from the SpeedMeter folder
    by walking up to the Content folder. None when it is not there.
    """
    if not speedmeter_folder:
        return None
    content = Path(speedmeter_folder).parents[2] if len(Path(speedmeter_folder).parents) > 2 else None
    for base in [content] + list(Path(speedmeter_folder).parents):
        if base is None:
            continue
        cand = Path(base) / "Fonts" / "SinkingShip" / "VeryBigItalicNumeric.xnb"
        if cand.exists():
            return cand
    return None


def _digit_sprite_font(font: dict, ch: str, right: float, bottom: float):
    """One digit as MonoGame's SpriteFont draws it, right/bottom aligned (Anchor.BottomRight)."""
    b, cr, lsb, w, rsb = font["glyphs"][ch]
    width = max(lsb, 0) + w + max(rsb, 0)                       # SpriteFont.MeasureString
    height = max(font["line"], cr[3])
    left, top = right - width, bottom - height
    img = font["tex"].crop((b[0], b[1], b[0] + b[2], b[1] + b[3]))
    return img, (left + max(lsb, 0) + cr[0], top + cr[1])


def _digit_font(size):
    """A stand-in TrueType font for the digits when the game's own digit font is not found (Impact or a similar
    heavy font, else Pillow's default).
    """
    from PIL import ImageFont
    for name in ("impact.ttf", "Impact.ttf", "ariblk.ttf", "arialbd.ttf", "DejaVuSans-Bold.ttf",
                 "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "Poppins-Bold.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    try:
        return ImageFont.load_default(size)
    except TypeError:
        return ImageFont.load_default()


_UNIT_CACHE: dict = {}          # fast mode: the unit text's layers (they don't change with speed)


def render_speedmeter(tex: dict, speed_cms: float, charge_cms: float = 0.0, precise: bool = False,
                      region=(0, 1780, 3840, 2160), digits=True, font: Optional[dict] = None,
                      fast: bool = False) -> Image.Image:
    """Renders the in-game speedometer at virtual 4K resolution (crop = region).
    tex: {'Texture','BarBeginning','Block','CMS','MMS'} -> straight-alpha RGBA images.
    fast: for animation frames (Play run): the black outline is drawn with its outermost offset
    only, which looks almost the same in a moving preview at a fraction of the cost."""
    rx0, ry0, rx1, ry1 = region
    size = (rx1 - rx0, ry1 - ry0)
    back = tex["Texture"].convert("RGBA")
    bw, bh = back.size
    tile = _mirror_tile(back)
    speed_px = int(round(SM_PX_PER_CMS * speed_cms))
    charge_px = max(speed_px, int(round(SM_PX_PER_CMS * charge_cms)))
    frame = Image.new("RGBA", size, (0, 0, 0, 0))

    def shift_for(sp):            # texture scroll, from the shader
        """How far the bar texture scrolls at speed sp, as the game's shader does it (0.3 px per speed unit, capped
        at 930).
        """
        return 930.0 if sp >= 3100 else 0.3 * sp

    def layer_for(off, sp, sprites):
        """Draw one pass: sprites=[(img, (x, y) top-left in screen coords)], offset off, speed sp."""
        lay = Image.new("RGBA", size, (0, 0, 0, 0))
        for img, (x, y) in sprites:
            px, py = int(round(x + off[0])) - rx0, int(round(y + off[1])) - ry0
            if px >= size[0] or py >= size[1] or px + img.width <= 0 or py + img.height <= 0:
                continue
            # blend the sprite straight into its place (same pixels as compositing a full-size
            # layer that holds only this sprite, without making one per sprite)
            sx, sy = max(0, -px), max(0, -py)
            src = img if (sx, sy) == (0, 0) else img.crop((sx, sy, img.width, img.height))
            if src.mode != "RGBA":
                src = src.convert("RGBA")
            lay.alpha_composite(src, dest=(px + sx, py + sy))
        return lay

    def shade(lay, off, sp, black, shift=None):
        """One HUD sprite as the shader draws it: its alpha cut by the bar's slanted mask, its colour either black
        (charge blocks) or the bar texture sampled at the scrolled position and multiplied in.
        """
        a = lay.getchannel("A")
        a = ImageChops.multiply(a, _cut_mask(size, off[0], off[1], rx0, ry0, sp))
        if black:
            rgb = Image.new("RGB", size, (0, 0, 0))
        else:
            sh = shift_for(sp) if shift is None else shift
            samp = _mirror_sample(tile, bw, bh, int(round(rx0 - 220 - sh)), ry0 - 1820, size)
            rgb = ImageChops.multiply(lay.convert("RGB"), samp.convert("RGB"))
        out = rgb.convert("RGBA")
        out.putalpha(a)
        return out

    # ---- layout (SE.SpeedMeter.DrawInner, horizontal HUD) ----
    ax, ay = 0 + SM_MARGIN, SM_SCREEN[1] - SM_MARGIN          # anchor (bottom-right of digits)
    digit_right = [ax + SM_DIGIT_STEP * (i + 1) for i in range(3)]
    bx, by = digit_right[2] - 30, ay - 36                       # bottom-left of unit text / bar
    unit = tex["MMS" if precise else "CMS"]
    beg, blk = tex["BarBeginning"], tex["Block"]
    unit_sprite = [(unit, (bx, by - unit.height))]
    def bar_sprites(sp):
        """The sprites that make the bar at speed sp: the bar beginning, then as many blocks as the length needs,
        each SM_BLOCK_STEP further right. Returns [(image, (x, y))].
        """
        s = [(beg, (bx, by - beg.height))]
        length = sp + 100
        if length > beg.width:
            x = bx + beg.width - (blk.width - SM_BLOCK_STEP)
            top = by - beg.height
            rem = length - beg.width
            while rem > 0:
                s.append((blk, (x, top)))
                x += SM_BLOCK_STEP
                rem -= SM_BLOCK_STEP
        return s

    digit_sprites = []
    if digits:
        shown = int(round(speed_cms * (10 if precise else 1)))
        shown = max(0, min(999, shown))
        txt = [str(shown // 100) if shown >= 100 else "", str(shown // 10 % 10) if shown >= 10 else "",
               str(shown % 10)]
        if font is not None:
            for ch, right in zip(txt, digit_right):
                if ch and ch in font["glyphs"]:
                    digit_sprites.append(_digit_sprite_font(font, ch, right, ay))
            txt = ["", "", ""]
        sysfont = _digit_font(230)
        for ch, right in zip(txt, digit_right):
            if not ch:
                continue
            font = sysfont
            l, t, r, b = font.getbbox(ch)
            gw, gh = r - l, b - t
            g = Image.new("RGBA", (gw + 60, gh), (0, 0, 0, 0))
            ImageDraw.Draw(g).text((-l + 30, -t), ch, font=font, fill=(255, 255, 255, 255))
            g = g.transform(g.size, Image.AFFINE, (1, 0.22, -0.22 * gh, 0, 1, 0), resample=Image.BICUBIC)
            digit_sprites.append((g, (right - g.width + 30, ay - g.height)))

    # digits: drawn before the shader's speed is set (default -1: no cut, ~no scroll)
    # unit text: speed = float.MaxValue (no cut, full 930 px scroll); bar: real speed
    BIG = 1e12
    outline = SM_OUTLINE if not fast else [max(SM_OUTLINE, key=lambda o: abs(o[0]) + abs(o[1]))]
    # the unit text looks the same at every speed: in fast mode (animation frames) its layers are
    # kept and reused. Its black passes are drawn apart from the digits' (black over black blends
    # the same either way), so the result is unchanged.
    ukey = (fast, precise, region, unit.size, hash(unit.tobytes()), hash(back.tobytes()), bw, bh)
    cached = _UNIT_CACHE.get("key") == ukey
    if not cached and fast:
        _UNIT_CACHE.clear()
    for off in outline:                                        # black outline passes
        if digit_sprites:
            lay = layer_for(off, BIG, digit_sprites)
            frame = Image.alpha_composite(frame, shade(lay, off, BIG, True))
        if cached:
            ublack = _UNIT_CACHE["black"][off]
        else:
            ublack = shade(layer_for(off, BIG, unit_sprite), off, BIG, True)
            if fast:
                _UNIT_CACHE.setdefault("black", {})[off] = ublack
        frame = Image.alpha_composite(frame, ublack)
        lay = layer_for(off, charge_px, bar_sprites(charge_px))
        frame = Image.alpha_composite(frame, shade(lay, off, charge_px, True))
    if digit_sprites:                                          # white passes
        lay = layer_for((0, 0), BIG, digit_sprites)
        frame = Image.alpha_composite(frame, shade(lay, (0, 0), BIG, False, shift=0.0))
    if cached:
        uwhite = _UNIT_CACHE["white"]
    else:
        uwhite = shade(layer_for((0, 0), BIG, unit_sprite), (0, 0), BIG, False)
        if fast:
            _UNIT_CACHE["white"], _UNIT_CACHE["key"] = uwhite, ukey
    frame = Image.alpha_composite(frame, uwhite)
    lay = layer_for((0, 0), speed_px, bar_sprites(speed_px))
    frame = Image.alpha_composite(frame, shade(lay, (0, 0), speed_px, False))
    return frame
