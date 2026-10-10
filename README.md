# XNB Board Texture Tool

A small desktop tool for swapping skateboard textures in **STUNTBOOST** (and other MonoGame / XNA games that store images in `.xnb` files).

Pick a board, drop in any PNG or JPG, choose the board's colors, and the tool writes a game-ready `.xnb` for you. Backups and one-click revert are built in.

![Screenshot of the XNB Board Texture Tool](docs/screenshot.png)

---

## Features

- **Board browser:** lists every board in the content folder with a mini preview and a status marker.
  - 🟢 matches the saved default
  - 🟧 modified
  - ⭕ no default saved yet
- **Replace by drag & drop or file picker:** accepts PNG, JPG, BMP, TGA, GIF and WEBP.
- **Adjust before applying:** every new image opens an editor where you can drag to position it, zoom with the mouse wheel, choose **Fill / Fit / Stretch**, rotate (90° steps or any angle), flip, and pick a color or transparency for uncovered areas. A dimmed border shows what will be cut off. The result always has the original texture size, so the game gets exactly what it expects.
- **Board colors:** pick the border, under, wheels and truck colors with a color picker, or type `#rrggbb` / `r,g,b`. The tool writes them into the texture for you. You can copy and paste a color set between boards, and the colors are kept when you replace the artwork.
- **Layouts and themes:** choose **Studio** (big 3D view in the middle), **Gallery** (all boards as cards with their colors) or **Classic** in **Settings**, in a **Dark** or **Light** theme.
- **3D preview:** see the selected board on the game's own skateboard model. Drag to rotate, scroll to zoom, and use the Top, Bottom and Side views. Picked colors show up before you apply them, and screws appear on boards that have them in the game. Click the wheels, trucks, screws or border to change that color.
- **Decorate tab:** put stickers and images straight onto the 3D board as layers, on top of the board's art or a base texture (black, stripes, carbon, camo, flames…). Comes with a Starter pack of 24 stickers; make your own packs and share them as .zip files. Layers stay editable after saving.
- **Thumbnails:** replace the thumbnail separately, or generate it from the board texture with one click.
- **Speedmeter tab:** restyle the HUD speedometer. Edit the bar texture, bar beginning, blocks and the CM/S and MM/S text, and see a **live in-game preview** with speed and charge sliders.
- **Defaults and revert:** snapshot the current images as "defaults" and restore them exactly at any time. A `.bak` backup is also made before a file is first overwritten.
- **Export to PNG:** pull any board texture or thumbnail out of the game as a normal image.
- **Fast:**
  - Boards load in the background, so the window never freezes. The thumbnail shows right away, and the full texture follows a moment later.
  - Recently opened boards stay in memory, and the next and previous boards are preloaded, so stepping through boards is instant.
  - Gallery card images and board statuses are cached on disk, so large folders open instantly the second time.
  - Changing a color or switching boards recolors the 3D frame already on screen instead of rendering it again.
  - Dragging a sticker in Decorate only redraws the area the sticker moved through.
  - The Gallery draws only the cards you can see (and a few around them), so large folders switch to it quickly; the rest appear as you scroll.
  - After saving a QOI texture (the format STUNTBOOST uses), the tool keeps the pixels it just wrote instead of reading the file back.
  - Low memory use: stickers keep only the pixels they cover, boards you have stepped away from in Decorate keep just their unsaved design (the rest is rebuilt when you come back), very large images are reduced to what a board can show, and the Gallery keeps only the small on-screen pictures: card images are read back from the disk cache when needed. Recently opened textures are kept up to about 24 MB, not by count, so the worst case stays bounded.
  - If the optional `qoi` package is installed, textures load and save many times faster. Saved files are checked to decode back to exactly the same pixels; otherwise the built-in encoder is used.

## Supported formats

| Format | Read | Write |
|---|---|---|
| QOI images in XNB (`BytingPipeline.QoiReader`), used by STUNTBOOST | ✅ | ✅ |
| MonoGame `Texture2D`, Color (RGBA8) | ✅ | ✅ |
| MonoGame `Texture2D`, DXT1 / DXT3 / DXT5 | ✅ | ✅ (saved as RGBA8) |
| Compressed XNB (LZX / LZ4) | ❌ | ❌ |

Boards are found automatically as `<name>.xnb` + `<name>Thumbnail.xnb` pairs. If no pairs are found, the tool falls back to GLTF models (`BytingPipeline.GLTFReader`) and their referenced textures.

## Getting started

### Option A: download the Windows version (easiest)

1. Go to [Releases](../../releases) and download `XNB-Board-Tool-v1.2.4-windows.zip`.
2. Unzip it anywhere, for example to your Desktop.
3. Open the `XNB Board Tool` folder and run **`XNB Board Tool.exe`**. Keep the `_internal` folder next to it, because the app needs it.

No installation or Python needed.

> **⚠️ Windows SmartScreen / antivirus warnings**
>
> The app is not code-signed yet, so on first launch Windows may show **"Windows protected your PC"**. Click **More info → Run anyway**.
>
> Some antivirus programs may also flag it. This is a known false positive for Python apps packaged with PyInstaller: thousands of harmless tools share the same launcher, and scanners match on it. The tool contains no network code and doesn't need admin rights; see [Safety](#safety).
>
> If you'd rather not run an unsigned app:
> - check the zip on [VirusTotal](https://www.virustotal.com/) yourself, or
> - use **Option B** below and run the readable Python source directly. The release is built from exactly this code (see [Building the Windows version](#building-the-windows-version)).

### Option B: run the Python script

1. Install **Python 3.9 or newer** from [python.org](https://www.python.org/downloads/). Keep the "tcl/tk and IDLE" option ticked.
2. Install the dependencies:
   ```bash
   pip install pillow numpy
   pip install tkinterdnd2   # optional, enables drag & drop
   pip install qoi           # optional, faster texture loading
   ```
3. Run the tool:
   ```bash
   python xnb_board_tool_v2.py
   ```
   Keep the `xnb_board_tool` folder next to `xnb_board_tool_v2.py`; the script is only a launcher for it.

   It asks for the content folder on start. You can also pass the folder directly:
   ```bash
   python xnb_board_tool_v2.py "E:\SteamLibrary\steamapps\common\STUNTBOOST\Content\Models\Resources\Board"
   ```

### Building the Windows version

You only need this if you want to build the release yourself. It requires Python 3.9+ from python.org on Windows.

1. Put `build_exe.bat` and `build_exe.py` next to `xnb_board_tool_v2.py` and the `xnb_board_tool` folder.
2. Double-click `build_exe.bat`. It installs PyInstaller, Pillow, numpy, tkinterdnd2 and qoi (the last two are optional), then builds the app.
3. The results are in the `dist` folder:
   - `dist\XNB Board Tool\`: the app folder
   - `dist\XNB-Board-Tool-v1.2.4-windows.zip`: the same folder zipped, ready to upload to a GitHub release

To make a single `.exe` instead, run `build_exe.bat --onefile`. Single-file builds are flagged by antivirus much more often, because they unpack themselves to a temp folder on every start. That's why the folder build is the default.

To reduce false positives, the build also skips UPX compression and embeds version information (product name, version, description) in the exe. To release a new version, change `VERSION` at the top of `build_exe.py`.

## How to use

1. **Open the content folder:** `Content\Models\Resources\Board` inside the game folder.
2. **Save defaults first:** click **Save all as defaults** once. This snapshots every original texture, so you can always go back.
3. **Pick a board** from the list on the left. Use the filter box, the ‹ › buttons or Ctrl+←/→ to move between boards.
4. **Replace the artwork:** drop an image onto the texture preview, or click **Replace image…**. In the **Adjust image** window, position and zoom the image, then click **Apply**.
5. **Set the colors** in the **Board colors** section, then click **Apply colors to texture**.
6. **Update the thumbnail:** click **Generate from texture** or replace it with your own image.
7. **Start the game** and check your board.

Made a mistake? Click **Revert to default** on the texture or thumbnail.

### Settings: layout and theme

Click **⚙ Settings** in the header to choose:

| Layout | What it looks like |
|---|---|
| **Studio** (default) | Board list on the left, a big 3D preview with the texture below it in the middle, and colors, thumbnail and defaults in an inspector on the right. |
| **Gallery** | Every board as a card with its art and its 4 colors, so you can compare all boards at a glance. Click a card to edit it in the drawer on the right. Use **Per row** (Auto, 2–6) above the grid to choose how many cards fit in a row; the cards scale to fill it. Drag the divider between the cards and the drawer to resize the drawer. The drawer combines everything in one card: **Texture / Thumbnail** tabs share the preview (drop an image on it to replace whichever is shown), and the 4 board colors sit in one row below. Less common actions are in the **⋯** menus. |
| **Classic** | The original layout: texture and 3D side by side, colors below, thumbnail and defaults at the bottom. |

You can also pick a **Dark** or **Light** theme. The window rebuilds right away and keeps your folder, the selected board and any colors you haven't applied yet. Your choice is remembered for next time.

### Speedmeter

Switch to the **Speedmeter** tab in the header. The files are found automatically in `Content\Textures\HUD\SpeedMeter`. While this tab is open, the folder bar at the top shows the speedmeter folder, and **Change…** (or Ctrl+O) picks a different speedmeter folder; on the **Boards** tab it shows and changes the board folder.

| File | What it is |
|---|---|
| `Texture.xnb` | The color/pattern seen through the whole bar |
| `BarBeginning.xnb` | First section of the bar, above the unit text |
| `Block.xnb` | Repeated to make the bar longer |
| `CMS.xnb` / `MMS.xnb` | Unit text (normal / precise mode) |

The preview at the top rebuilds the speedometer exactly the way the game draws it. Move the **Speed** slider to see the bar grow, the **Charge** slider for the black "potential speed" blocks, and tick **Precise** to switch between CM/S and MM/S. The digits are drawn with the game's own font (`Content\Fonts\SinkingShip\VeryBigItalicNumeric.xnb`, found automatically), with the same spacing tweaks the game applies.

How the game uses the bar texture (good to know when designing one):
- It's mapped to the **screen**, not to each block. The blocks are windows onto one long strip.
- Only the **lower rows** (about 68–154) are reached, and past the texture's edges it is **mirrored**.
- It **scrolls left** as speed increases (0.3 px per bar pixel, up to 930 px). The left part shows at low speeds; the middle and right appear as the bar fills.

When the bar texture is selected, the highlighted box shows which part is visible at the current speed.

### Decorate

Click **Decorate** in the header (or **Decorate…** on the 3D preview) to decorate the selected board directly on the 3D model. Use ‹ › to move between boards; unsaved work stays with each board until you save it or close the tool.

**Left panel: Stickers | Textures**
- **Stickers:** your sticker packs are listed at the top. Each pack is a folder inside the `stickers` folder next to the tool, and a **Starter** pack of 24 original stickers is added the first time.
  - Drag a sticker onto the 3D board (or the flat texture below it) to place it there, or click it to add it in the middle.
  - **+ New** creates a pack. The **⋯** menu (or right-clicking a pack) renames, deletes, exports or imports packs.
  - **Export pack as .zip** makes a file you can share. **Import pack from .zip** (or dropping a .zip on the panel) adds someone else's pack. Only images are taken from the zip, re-saved as PNG, so nothing else in the file is used.
  - **Add…** or dropping images adds them to the selected pack (to **My stickers** when **All stickers** is shown). Right-click a sticker to move it to another pack or remove it.
- **Textures:** click a base texture to put it under your stickers: the board's own art, or Black, Black stripes, Carbon, Checker, Blueprint grid, Sunset, Hazard, Camo, Grain or Flames. **Tint** recolors the base. **Add…** puts your own images in the `textures` folder.

**Center: the board**
- **Place stickers** mode: click a sticker on the board to select it, then drag to move it. It follows the cursor on the deck's surface. The mouse wheel scales it around the cursor and Shift+wheel rotates it. Dragging an empty part of the deck rotates the board.
- **View / colors** mode: dragging always rotates the board.
- In both modes, clicking the wheels, trucks, screws or border changes that color. The colors are the same ones as in the Boards tab.
- Below the 3D view is the flat texture. The dimmed area doesn't show on the top of the deck, and each layer is outlined.
- Images from disk: **Image…**, or drop files on the board (needs `tkinterdnd2`). Wide, board-shaped images cover the whole deck; other images become stickers where you drop them.

**Right panel: layers, colors, save**
- **Layers:** reorder (Up / Down), show or hide, duplicate, delete and set the opacity. Fill / Fit / Rotate 90° / Flip work on the selected layer.
- **Undo / Redo** (Ctrl+Z / Ctrl+Y) cover every change, including the base texture and colors.
- **Save decorations…** opens a window with two choices:
  - **Override selected board** writes the design into that board.
  - **Save to another board** keeps the selected board as it is and writes the design into a board you pick. STUNTBOOST loads a fixed set of boards (0–100), so the design replaces that board rather than adding a new one.
  - **Also update the thumbnail** makes the board's thumbnail from the new design.
  - **Keep layers editable after saving** stores the base and layers in `_board_defaults\decor\`. Next time you open Decorate on that board, the stickers are still separate and movable. If the texture was changed in another way since, the stored layers are ignored.
- Saving works like everywhere else in the tool: it offers to save a default first, keeps a `.bak` backup, and **Revert** still brings the original back.

### Board colors

The first four pixels of the texture's top row hold the board's colors:

| Pixel (x, y) | Part |
|---|---|
| `0, 0` | Border |
| `1, 0` | Under (bottom of the deck) |
| `2, 0` | Wheels |
| `3, 0` | Truck (and screws) |

The tool edits these pixels for you, so you don't need an image editor. Copy produces text like `#d02020, #c8b400, #40c060, #4050c0` that you can share with other players. Paste reads it back.

### Keyboard shortcuts

| Keys | Action |
|---|---|
| Ctrl+O | Change the folder for the open tab (boards or speedmeter) |
| Ctrl+← / Ctrl+→ | Previous / next board |
| Enter (in the filter box) | Jump to the first matching board |
| Esc (in the filter box) | Clear the filter |

In the **Decorate** tab:

| Keys / mouse | Action |
|---|---|
| Drag a sticker on the deck | Move it |
| Mouse wheel / Shift+wheel over the selected sticker | Scale / rotate it around the cursor |
| Right-drag (or drag an empty spot) | Rotate the board |
| Click a wheel, truck, screw or the border | Change that color |
| R / F | Rotate 90° / flip the selected sticker |
| Delete, Ctrl+D | Delete / duplicate the selected sticker |
| Page Up / Page Down | Move the selected layer up / down |
| Ctrl+Z / Ctrl+Y | Undo / redo |
| Esc | Deselect |

In the **Adjust image** window:

| Keys / mouse | Action |
|---|---|
| Drag | Move the image |
| Mouse wheel | Zoom at the cursor |
| Double-click | Reset position and zoom |
| Arrow keys (Shift = 10 px) | Nudge the image |
| + / − | Zoom in / out |
| R | Rotate 90° |
| Enter / Esc | Apply / Cancel |

## Files the tool creates

| File / folder | What it is |
|---|---|
| `<board>.xnb.bak` | Copy of the file before the tool first changed it |
| `_board_defaults\` | Your saved defaults (lossless PNG or exact XNB copy) plus metadata |
| `_board_defaults\_hash_cache.json` | Cache that makes board statuses load fast |
| `_board_defaults\decor\<board>.xnb\` | Editable layers of a decorated board (base image, sticker images, placement) |
| `stickers\<pack>\` (next to the tool) | Your sticker packs. The Starter pack is added the first time. |
| `textures\` (next to the tool) | Your own base textures |
| `%APPDATA%\XNB Board Tool\settings.json` | Your layout, theme, gallery cards-per-row and drawer width |
| `%LOCALAPPDATA%\XNB Board Tool\cache\` | Small gallery card images and colors, one subfolder per content folder. Rebuilt automatically when a board changes. |

All of them can be deleted safely (but deleting `stickers` or `textures` removes your packs and textures). Deleting the game-folder files only loses the ability to revert; deleting settings.json resets the layout and theme; deleting the cache only makes the next start a little slower.

## Safety

- The tool **does not** connect to the internet, run other programs or touch system folders, and it needs no administrator rights.
- It only writes the `.xnb` files you change, their backups, the `_board_defaults` folder, PNG files you export, sticker packs and textures in the `stickers` and `textures` folders next to the tool (or in `%APPDATA%\XNB Board Tool` if that folder isn't writable), a small settings file in `%APPDATA%\XNB Board Tool`, and a cache in `%LOCALAPPDATA%\XNB Board Tool\cache`.
- Files are written safely through a temp file and swap, so a crash or power cut can't leave a half-written game file.
- Damaged or malformed `.xnb` files are rejected instead of being loaded.

## Tips and troubleshooting

- **Close the game** before changing textures.
- **Steam "Verify integrity of game files"** restores the original textures. Your `_board_defaults` and `.bak` files let you reapply your changes afterwards.
- **"compressed XNB files are not supported"** means the file uses LZX/LZ4 compression. Decompress it with an XNB tool first.
- **Drag & drop doesn't work:** install `tkinterdnd2` (`pip install tkinterdnd2`) and restart the tool.

## Requirements

- Windows 10/11. The script also runs on Linux and macOS with Python and Tk.
- Python 3.9+ with Tkinter
- [Pillow](https://pypi.org/project/pillow/)
- [numpy](https://pypi.org/project/numpy/) (for the 3D preview)
- [tkinterdnd2](https://pypi.org/project/tkinterdnd2/) (optional, for drag & drop)
- [qoi](https://pypi.org/project/qoi/) (optional, for faster loading). The tool checks it on start and falls back to its built-in decoder if it doesn't work correctly.

## Project structure

```
xnb_board_tool_v2.py        launcher (run this)
build_exe.py / .bat         Windows build
xnb_board_tool/
  common.py                 errors, size limits, safe file writes
  qoi.py                    QOI image codec (uses the qoi package if available)
  xnb.py                    XNB reading/writing (Texture2D, QOI, fonts, models)
  defaults.py               saved defaults and status hashing
  boards.py                 board scanning and board colors
  caches.py                 in-memory texture cache and on-disk gallery cache
  imageops.py               image fitting, rotation, thumbnails
  speedmeter.py             speedometer rendering, as the game draws it
  board3d.py                skateboard model and software 3D renderer
  settings.py               themes, layouts, saved settings
  stickers.py               sticker packs on disk, .zip import / export
  basetex.py                base textures for decorating (built-in patterns, your images)
  layers.py                 layers, composing, editable-layer project files
  assets/stickers/Starter/  the built-in Starter sticker pack
  gui/
    base.py                 Tk setup and shared widgets
    dialogs.py              Settings and Adjust image windows
    layouts.py              Studio / Gallery / Classic layouts
    preview3d.py            3D preview panel
    speedmeter_tab.py       Speedmeter tab
    decorate.py             Decorate tab and the Save decorations window
    app.py                  main window
```

The core modules have no GUI code, so they can also be used from other scripts:

```python
from xnb_board_tool import scan, read_texture_palette
```

## Disclaimer

This is a fan-made modding tool and is not affiliated with the developers of STUNTBOOST. Back up your files and use it at your own risk. Share only artwork you have the right to share.

## License

<!-- Choose a license, e.g. MIT: https://choosealicense.com/licenses/mit/ -->
TBD
