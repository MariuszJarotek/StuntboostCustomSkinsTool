#!/usr/bin/env python3
"""
XNB Board Texture Tool  (v2 - redesigned dark UI)
=================================================
Scans a content folder for boards (GLTF model .xnb files wrapped by
BytingPipeline.GLTFReader, or <name>.xnb + <name>Thumbnail.xnb pairs), finds
each board's texture and thumbnail, shows them, and lets you replace either one
with any normal image (PNG/JPG/BMP/TGA/GIF/WEBP).

Usage:
    pip install pillow numpy
    pip install qoi             # optional: much faster texture loading
    pip install tkinterdnd2      # optional: drag & drop images onto the previews
    python xnb_board_tool_v2.py [content_folder]

What's new in v2:
  * Dark UI. Previews keep the real aspect ratio of the image (wide strips stay wide).
  * Board list with a mini preview and a status marker per board:
        green dot = matches default, amber square = modified, outlined ring = no default.
    Statuses are computed in the background; pixel hashes are cached in
    _board_defaults/_hash_cache.json so later launches are fast.
  * Filter box, previous / next buttons, summary in the footer.
  * "Generate from texture": rebuilds the thumbnail by downscaling the board texture.
  * Settings: Studio / Gallery / Classic layout and a Dark / Light theme, remembered in
    %APPDATA%\\XNB Board Tool\\settings.json (~/.config/... elsewhere).
  * Speedmeter tab: edit the HUD speedometer textures (Content/Textures/HUD/SpeedMeter:
    Texture, BarBeginning, Block, CMS, MMS) with a live in-game preview. The preview
    follows the game's own code (SE.SpeedMeter.DrawInner + the SpeedMeter shader): blocks
    every 164 px, bar length = 41 px per cm/s, the bar texture is screen-mapped, scrolls
    0.3 px per bar pixel (max 930), only its lower rows are reached and it is mirrored
    past its edges.
  * Adjust image: every new image (picked or dropped) opens an editor first - drag to
    position, scroll/slider to zoom, Fill / Fit / Stretch, rotate (90 deg steps or any
    angle), flip, and a color or transparency for uncovered areas. The result always
    has the texture's exact size.
  * Board colors: the first 4 pixels of the texture's top row are the board's
    border (x=0), under (x=1), wheels (x=2) and truck (x=3) colors. Pick them with a
    color picker or type #rrggbb / r,g,b, then 'Apply colors to texture'.
    Copy / Paste moves a color set between boards, and by default the colors are
    kept when you replace the texture with a new image.
  * Drag & drop an image onto a preview to replace it (needs tkinterdnd2).
  * Ctrl+O opens a folder (the board folder, or the speedmeter folder on that tab - the
    folder bar at the top follows the open tab); Ctrl+Left / Ctrl+Right step through boards.
  * 3D preview: the selected board on the game's own skateboard model
    (Content/Models/Export/Board.xnb + Board.bin.xnb). Drag to rotate, scroll to zoom,
    Top / Bottom / Side views, screws where the game shows them. Picked colors show
    before they are applied, and clicking the wheels, trucks, screws or border picks
    that color.
    Drawn on the graphics card (OpenGL 3.3 through ctypes, no extra packages) when one is
    usable, at full resolution even while turning; otherwise by the numpy renderer. A
    self-test and a crash guard fall back to the CPU on driver trouble; Settings has a
    switch, and XNB_NO_GPU=1 turns it off.
  * Decorate tab: put stickers and images straight onto the 3D board.
      - Stickers are dragged onto the board (or the flat texture below it) and follow the
        deck's surface; mouse wheel scales, Shift+wheel rotates.
      - Every sticker or image is a layer: reorder, hide, duplicate, delete, opacity,
        Fill / Fit / Rotate 90 / Flip. Undo / Redo (Ctrl+Z / Ctrl+Y) cover every change.
      - Sticker packs: each pack is a folder in "stickers" next to the program. A Starter
        pack of 24 original stickers is added the first time. Packs can be created,
        renamed, deleted, exported as .zip and imported from .zip (only images are taken
        from a zip, re-saved as PNG).
      - Base textures under the stickers: the board's own art or Black, Black stripes,
        Carbon, Checker, Blueprint grid, Sunset, Hazard, Camo, Grain, Flames, plus your
        own images in the "textures" folder; Tint recolors the base.
      - Save decorations: override the selected board or save to another board (the game
        loads a fixed list of boards 0-100, so a design replaces a board rather than adding
        one), optionally update the thumbnail, and optionally keep the layers editable
        (stored in _board_defaults/decor/). Defaults, .bak backups and Revert work as usual.
      - Unsaved designs stay with each board while you move between boards; closing the
        tool asks before they are lost.
  * Speed and memory: boards load in the background with the next / previous ones
    preloaded, statuses and gallery cards are cached on disk, the 3D view recolors the
    shown frame instead of rendering again, the Gallery draws and keeps only the cards
    near the screen, and recently opened textures are kept up to about 24 MB. With the
    optional `qoi` package, textures load and save many times faster.

Unchanged from v1 (same file formats and folders):
  * Supports BytingPipeline.QoiReader images (QOI inside XNB) and MonoGame Texture2D.
  * Texture2D replacements are written as RGBA8 with the original mip count.
  * Alpha is re-premultiplied only if the original texture looked premultiplied.
  * A one-time backup  <file>.xnb.bak  is written before the first overwrite.
  * Defaults are snapshots in a _board_defaults folder; 'Revert to default' restores them.
  * Compressed XNBs (LZX/LZ4 flag) are not supported.

Project layout (this file only starts the app):
  xnb_board_tool/            library: XNB/QOI formats, defaults, board colors, caches,
                             the speedometer and 3D renderers (CPU and GPU), settings, sticker packs,
                             base textures and decoration layers
  xnb_board_tool/assets/     the built-in Starter sticker pack
  xnb_board_tool/gui/        the Tk user interface (base widgets, dialogs, the main window
                             and its layouts, 3D preview, Decorate and Speedmeter tabs)

"""
from __future__ import annotations

import sys

from xnb_board_tool import *  # noqa: F401,F403  (the library API, handy for scripting)
from xnb_board_tool.gui import run_gui

if __name__ == "__main__":
    run_gui(sys.argv[1] if len(sys.argv) > 1 else None)
