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
- **Languages:** English, Polski, Deutsch and Français. The tool starts in your Windows display language (when it has it) and you can switch in **Settings** at any time; the window changes right away.
- **Layouts and themes:** choose **Skate shop** (every deck on a wall; one deck on the bench with its top and bottom side by side), **Studio** (big 3D view in the middle), **Gallery** (all boards as cards with their colors) or **Classic** in **Settings**, in a **Concrete**, **Dark** or **Light** theme.
- **3D preview:** see the selected board on the game's own skateboard model. Drag to rotate, scroll to zoom, and use the Top, Bottom and Side views. Picked colors show up before you apply them, and screws appear on boards that have them in the game. Click the wheels, trucks, screws or border to change that color. It is drawn on the graphics card when one is available, so it stays sharp while you turn it.
- **Decorate tab:** put stickers and images straight onto the 3D board as layers, on top of the board's art or a base texture (black, stripes, carbon, camo, flames…). Comes with a Starter pack of 24 stickers; make your own packs and share them as .zip files. Add text in any installed font and simple shapes (racing stripes, circles, stars, chevrons…), recolour stickers to match your board, mirror a sticker to the nose and tail or both sides, and let the tool suggest wheel, truck and border colours from the artwork. Add effects to stickers (shadow, white die-cut border, raised, worn, holographic) and a finish to the whole board (grip tape, matte grain, worn edges, faded, gloss). Layers, text and effects stay editable after saving.
- **Thumbnails:** replace the thumbnail separately, or generate it from the board texture with one click.
- **Speedmeter tab:** restyle the HUD speedometer. In the Skate shop layout it is a bench like the decks': a big **live in-game preview** with backdrop tags (Game / Dark / Checker) and the speed and charge sliders, and three tools hanging from the dock. **Parts** lists the five files (bar texture, bar beginning, block, CM/S and MM/S text) to view, replace, export or revert. **Bar texture** has two modes, as two big tabs: **Recolor mine** keeps your texture and gives it new colors (presets, From deck, shift hue / saturation / brightness, or three new colors by shade or along the bar), and **Make new** draws a new texture from a style (Solid, Gradient, Speed zones, Chevrons, Checker, Carbon, Rainbow, Deck art). **Text** makes new unit text (quick labels first, then any label; the fonts as cards with a sample in their own lettering, or a .ttf/.otf file; size, slant, letter spacing, weight, alignment); only the label changes, the numbers stay in cm/s. Changes stay on screen, the same as deck colors, until **Write to game** in the bar at the bottom (a .bak backup is kept; Revert to default brings the original back). Every slider in the app has ◀ ▶ arrows at its ends for fine steps (hold to repeat). **▶ Play run** (or Space) animates a run from 0 to the speed you set and back, with the charge blocks running ahead; it shows your unsaved changes too. In the other layouts the same tools open as cards under the preview (◐ Bar texture, Aa Text maker), each with its own Apply button.
- **Defaults and revert:** snapshot the current images as "defaults" and restore them exactly at any time. A `.bak` backup is also made before a file is first overwritten.
- **Export to PNG:** pull any board texture or thumbnail out of the game as a normal image.
- **Fast:**
  - Boards load in the background, so the window never freezes. The thumbnail shows right away, and the full texture follows a moment later.
  - Recently opened boards stay in memory, and the next and previous boards are preloaded, so stepping through boards is instant.
  - Gallery card images and board statuses are cached on disk, so large folders open instantly the second time.
  - The 3D board is drawn on the graphics card (OpenGL 3.3, no extra install), at full resolution even while turning. Without a usable graphics card it is drawn by the processor, as before.
  - Changing a color or switching boards recolors the 3D frame already on screen instead of rendering it again.
  - Dragging a sticker in Decorate only redraws the area the sticker moved through, in both the 3D view and the flat texture, and only that part is sent to the screen. Both follow the mouse smoothly with little processor use.
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

1. Go to [Releases](../../releases) and download `XNB-Board-Tool-v1.12.2-windows.zip`.
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
2. Double-click `build_exe.bat`. It installs Pillow, numpy, tkinterdnd2 and qoi (the last two are optional), builds PyInstaller with its own launcher (see below), then builds the app.
3. The results are in the `dist` folder:
   - `dist\XNB Board Tool\`: the app folder
   - `dist\XNB-Board-Tool-v1.12.2-windows.zip`: the same folder zipped, ready to upload to a GitHub release

To make a single `.exe` instead, run `build_exe.bat --onefile`. Single-file builds are flagged by antivirus much more often, because they unpack themselves to a temp folder on every start. That's why the folder build is the default.

To reduce antivirus false positives, the build compiles PyInstaller's launcher on your PC. Every PyInstaller app starts through the same small launcher, malware packed with PyInstaller uses it too, so antivirus programs often flag that launcher itself; a launcher compiled on your PC gives the exe its own fingerprint. This needs a C compiler once: install the free [Build Tools for Visual Studio](https://visualstudio.microsoft.com/visual-cpp-build-tools/) with **Desktop development with C++**. The compile takes a few minutes and runs again only when PyInstaller is updated (`_xnb_own_launcher.json` remembers it; `--rebuild-launcher` forces it). Without a compiler the build still works with PyInstaller's ready-made launcher, or use `--stock-launcher` to skip the step. The end of the build log says which launcher was used.

The build also skips UPX compression and embeds version information (product name, version, description) in the exe. To release a new version, change `__version__` in `xnb_board_tool/__init__.py` (the build reads it from there); see CONTRIBUTING.md.

## How to use

1. **Open the content folder:** `Content\Models\Resources\Board` inside the game folder.
2. **Save defaults first:** when you pick a folder whose boards have no defaults yet, the tool offers to save them. Click **Yes** (or click **Save all as defaults** later). This snapshots every original texture, so you can always go back.
3. **Pick a board** from the list on the left. Use the filter box, the ‹ › buttons or Ctrl+←/→ to move between boards.
4. **Replace the artwork:** drop an image onto the texture preview, or click **Replace image…**. In the **Adjust image** window, position and zoom the image, then click **Apply**.
5. **Set the colors** in the **Board colors** section, then click **Apply colors to texture**.
6. **Update the thumbnail:** click **Generate from texture** or replace it with your own image.
7. **Start the game** and check your board.

Made a mistake? Click **Revert to default** on the texture or thumbnail.

### Settings: layout, theme and language

Click **⚙ Settings** in the header to choose:

| Layout | What it looks like |
|---|---|
| **Skate shop** (default) | **The Bench's title row**: a tall **‹ Wall** bar on the left, the deck on the bench as a big tag hanging from the header's line (its number large, its status on a coloured stripe), the Wall's filters (All, Custom, Stock, No backup, with counts; what isn't written yet shows under them) and **the deck fan**. Choosing a filter lifts the whole fan out of sight and brings it back down holding only those decks; the deck on the bench never changes with a filter: when the filter leaves it out it stays in the fan as a guest (dashed outline) until you pick another deck. In the fan, every deck hangs from the header's line spread like a hand of cards from a point far above. The deck on the bench hangs right down with its number on it; the others show only their lower half (point at one and it comes down a little). Click a deck to put it on the bench, use the **‹ ›** bars on both sides, or scroll the mouse wheel over the fan. It turns the short way round, never ends (after the last deck comes the first again) and follows the Wall's filter. **The header** is a rod along the top of the window with everything hanging from it as tags: **Decks** and **Speedmeter** (the open one in the accent colour), the game-folder chip with live counts (e.g. *STUNTBOOST · 101 DECKS · 3 CUSTOM · 2 UNSAVED*; it opens a menu with the full path, **Change folder…**, **Copy path** and **Save all as stock**) and **Settings**. **The Wall:** every deck hangs upright on rails, in its own art and edge color, with its number and a **Stock / Custom / No backup** label. Point at a deck and it lifts off the rail, swings on its hook and gets an orange outline. Filter with the tags hanging from the header's line (All, Custom, Stock, No backup, each with its count) or type a deck number. Stock decks are labelled in green. The black **On the bench** bar at the bottom says what is not in the game yet (colors you haven't written, decks with unsaved stickers) and takes you there. Click a deck to put it on **the Bench:** the 3D board (or **Top & bottom**: both sides of the deck side by side, in the same shape), and a tool dock with **General** (Artwork, Paint and Thumbnail on one compact sheet), **Advanced** (stickers, layers, base textures and effects) and **Stock**. **Stock** fills the stage with your deck **now** next to its **stock**, top and bottom, a tag with the number of differences, chips listing them (e.g. *Border · was #d82020*, *The artwork differs from stock*) and **Show what changed**, which outlines the changed parts; on the right, **Put the whole deck back to stock** (texture and thumbnail with one question), **Only the texture**, **Only the thumbnail** and **Save as stock…**. Click any part of the deck to paint it, or pick a colour taken from your artwork; **Save board** at the bottom writes them into the texture. **← The Wall** or Esc goes back. **Advanced** in the tool dock turns the Bench into the decorating view right there, with no separate tab: the dock stays on top, so **General** or **Stock** takes you straight back, and unsaved stickers stay with their deck (the Bench shows them and says they are not written yet). Decorating follows the same look: the sticker library on the left, the deck standing upright next to the 3D board (drag, scale and rotate stickers on either), the layers and board colours on the right, and a black bar at the bottom with the base texture, what isn't saved yet, **Clear all** and **Write to game…**. **Settings** opens as a page of its own: picture cards for the layout, theme and text size, the language, the game folder and the 3D renderer; every change is used right away (Done or Esc closes it). Made for the **Concrete** theme. |
| **Studio** | Board list on the left, a big 3D preview with the texture below it in the middle, and colors, thumbnail and defaults in an inspector on the right. |
| **Gallery** | Every board as a card with its art and its 4 colors, so you can compare all boards at a glance. Click a card to edit it in the drawer on the right. Use **Per row** (Auto, 2–6) above the grid to choose how many cards fit in a row; the cards scale to fill it. Drag the divider between the cards and the drawer to resize the drawer. The drawer combines everything in one card: **Texture / Thumbnail** tabs share the preview (drop an image on it to replace whichever is shown), and the 4 board colors sit in one row below. Less common actions are in the **⋯** menus. |
| **Classic** | The original layout: texture and 3D side by side, colors below, thumbnail and defaults at the bottom. |

**3D preview:** untick **Draw the 3D board on the graphics card (GPU)** to draw it with the processor instead. The window also shows which one is in use. The graphics driver needs some extra memory while it's loaded (how much depends on the driver), and unticking frees it after a restart.

You can also pick a **Dark**, **Light**, **Concrete** or **Blueprint** theme. Concrete (warm concrete, ink black and an orange accent) is the look the Skate shop layout was designed for; Blueprint is its dark counterpart: navy drafting paper with a faint grid behind the Wall, light lines and an amber accent. The window rebuilds right away and keeps your folder, the selected board and any colors you haven't applied yet. Your choice is remembered for next time.

**Text size:** **Compact**, **Balanced** (the default) or **Large**. Every text in the tool uses one of six sizes (page titles, section headings, tabs and tags, body text, hints, codes), and the setting changes all of them at once, in every layout and dialog. The window rebuilds right away, like a theme change.

**Language:** **Automatic** (the default) follows the Windows display language when the tool has it, and English otherwise. Or pick **English**, **Polski**, **Deutsch** or **Français**. The window switches right away, like a theme change; open windows and messages already shown stay in the old language. File and folder names (`_board_defaults`, sticker pack folders, the game's files) never change.

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

**Left panel: Stickers | Textures | Effects**
- **Stickers:** your sticker packs are listed at the top. Each pack is a folder inside the `stickers` folder next to the tool, and a **Starter** pack of 24 original stickers is added the first time.
  - Drag a sticker onto the 3D board (or the flat texture below it) to place it there, or click it to add it in the middle.
  - **+ New** creates a pack. The **⋯** menu (or right-clicking a pack) renames, deletes, exports or imports packs.
  - **Export pack as .zip** makes a file you can share. **Import pack from .zip** (or dropping a .zip on the panel) adds someone else's pack. Only images are taken from the zip, re-saved as PNG, so nothing else in the file is used.
  - **Add…** or dropping images adds them to the selected pack (to **My stickers** when **All stickers** is shown). Right-click a sticker to move it to another pack or remove it.
- **Effects:** sliders from 0 to 100 %, previewed live on the 3D board.
  - **Board finish** goes over the whole board: **Grip tape** (sandpaper grain), **Matte grain**, **Worn edges** (the grip tape wears off from the outline, most at the nose and tail, and shows the bare maple wood underneath), **Faded** (sun-bleached) and **Gloss** (highlight streaks).
  - **Selected sticker:** **Shadow**, **White border** (a die-cut vinyl edge), **Raised** (embossed), **Worn** (scuffed and peeling) and **Holographic** (rainbow foil). **Remove** clears the selected sticker's effects. Duplicating a sticker keeps its effects.
  - **Sticker colour:** **Hue** turns the sticker's colours around the colour wheel, **Saturation** makes it more or less colourful (0 % is black and white), and **Tint** colours it with one colour (click the swatch to pick it; it starts as your wheel colour). Use it to make Starter stickers match your board. **Reset** puts the original colours back.
  - Effects are painted into the texture, so the game shows them too. They look the same from every angle and don't react to light, because the game uses only the board's color texture.
- **Textures:** click a base texture to put it under your stickers: the board's own art, or Black, Black stripes, Carbon, Checker, Blueprint grid, Sunset, Hazard, Camo, Grain, Flames or Maple wood. **Tint** recolors the base. **Add…** puts your own images in the `textures` folder.

**Center: the board**
- **Place stickers** mode: click a sticker on the board to select it, then drag to move it. It follows the cursor on the deck's surface. The mouse wheel scales it around the cursor and Shift+wheel rotates it. Dragging an empty part of the deck rotates the board.
- **View / colors** mode: dragging always rotates the board.
- In both modes, clicking the wheels, trucks, screws or border changes that color. The colors are the same ones as in the Boards tab.
- Below the 3D view is the flat texture. The dimmed area doesn't show on the top of the deck, and each layer is outlined.
- Images from disk: **Image…**, or drop files on the board (needs `tkinterdnd2`). Wide, board-shaped images cover the whole deck; other images become stickers where you drop them.
- **Text…** adds a text layer: type one or more lines, pick a font (the fonts installed on your PC), a colour and an outline, with a live preview. Double-click the layer or use **Edit text…** to change it later, even after saving with editable layers.
- **Shape ▾** adds a shape in your wheel colour: **Racing stripes** and **Center stripe** run along the whole deck; **Circle**, **Ring**, **Star**, **Triangle**, **Diamond**, **Chevron** and **Rounded bar** are placed like stickers. **Edit colour…** (or double-click) changes the colour, and the Effects tab works on them too.

**Right panel: layers, colors, save**
- **Layers:** reorder (Up / Down), show or hide, duplicate, delete and set the opacity. Fill / Fit / Rotate 90° / Flip work on the selected layer.
- **Mirror ▾** puts a copy of the selected layer at the other end (**Nose & tail**: turned around, like the board itself) or on the other side (**Both sides**). Drag either copy and both move together, symmetrically. Duplicating keeps the mirror.
- **Board colors → Suggest…** picks colour sets from the artwork on the deck (the main colour, the darkest and lightest, and the most vivid accents) for the border, under, wheels and truck. Click a set to use it; Ctrl+Z goes back.
- **Undo / Redo** (Ctrl+Z / Ctrl+Y) cover every change, including the base texture and colors.
- **Save decorations…** opens a window with two choices:
  - **Override selected board** writes the design into that board.
  - **Save to another board** keeps the selected board as it is and writes the design into a board you pick. STUNTBOOST loads a fixed set of boards (0–100), so the design replaces that board rather than adding a new one.
  - **Also update the thumbnail** makes the board's thumbnail from the new design.
  - **Keep layers editable after saving** stores the base and layers in `_board_defaults\decor\`. Next time you open Decorate on that board, the stickers are still separate and movable, and text and shapes can still be edited. If the texture was changed in another way since, the stored layers are ignored.
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
| Double-click a text or shape layer in the Layers list | Edit its text / colour |
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
| `_board_defaults\decor\<board>.xnb\` | Editable layers of a decorated board (base image, sticker images, placement, effects, colours, mirror, text and shape settings) |
| `stickers\<pack>\` (next to the tool) | Your sticker packs. The Starter pack is added the first time. |
| `textures\` (next to the tool) | Your own base textures |
| `%APPDATA%\XNB Board Tool\settings.json` | Your layout, theme, language, gallery cards-per-row and drawer width |
| `%APPDATA%\XNB Board Tool\gpu_start.marker` | Exists only while the graphics card is being started. If it's still there at the next start, the last start crashed, and the GPU isn't tried again until you tick the option in Settings. |
| `%LOCALAPPDATA%\XNB Board Tool\startup.log` | What happened during the last start (for bug reports). Rewritten at every start. |
| `%LOCALAPPDATA%\XNB Board Tool\cache\` | Small gallery card images and colors, one subfolder per content folder. Rebuilt automatically when a board changes. |

All of them can be deleted safely (but deleting `stickers` or `textures` removes your packs and textures). Deleting the game-folder files only loses the ability to revert; deleting settings.json resets the layout, theme and language; deleting the cache only makes the next start a little slower.

## Safety

- The tool **does not** connect to the internet, run other programs or touch system folders, and it needs no administrator rights.
- It only writes the `.xnb` files you change, their backups, the `_board_defaults` folder, PNG files you export, sticker packs and textures in the `stickers` and `textures` folders next to the tool (or in `%APPDATA%\XNB Board Tool` if that folder isn't writable), a small settings file in `%APPDATA%\XNB Board Tool`, and a cache and the start-up log in `%LOCALAPPDATA%\XNB Board Tool`.
- Files are written safely through a temp file and swap, so a crash or power cut can't leave a half-written game file.
- Damaged or malformed `.xnb` files are rejected instead of being loaded.

## Tips and troubleshooting

- **Close the game** before changing textures.
- **Steam "Verify integrity of game files"** restores the original textures. Your `_board_defaults` and `.bak` files let you reapply your changes afterwards.
- **"compressed XNB files are not supported"** means the file uses LZX/LZ4 compression. Decompress it with an XNB tool first.
- **3D view looks wrong, or the tool closes when the 3D view appears:** untick **Draw the 3D board on the graphics card** in Settings. If the tool closes before you can reach Settings, it uses the processor automatically on the next start. You can also start it with the environment variable `XNB_NO_GPU=1`. Updating the graphics driver usually fixes these problems.
- **The tool doesn't open (it shows in Task Manager but no window appears):** every start writes `%LOCALAPPDATA%\XNB Board Tool\startup.log`. If the window isn't up after 30 seconds, the log also records what the tool is stuck on, so end the process and send that file with your bug report. If a start fails with an error, a message box says so. After a start that didn't finish, the next start is a **safe start**: English, with the 3D board drawn by the processor, for that session only. You can also ask for one by starting the tool with `--safe`.
- **Drag & drop doesn't work:** install `tkinterdnd2` (`pip install tkinterdnd2`) and restart the tool.

## Requirements

- Windows 10/11. The script also runs on Linux and macOS with Python and Tk.
- Python 3.9+ with Tkinter
- [Pillow](https://pypi.org/project/pillow/)
- [numpy](https://pypi.org/project/numpy/) (for the 3D preview)
- Optional: a graphics card with OpenGL 3.3 (most PCs from the last ten years or so) for the faster 3D preview. Nothing extra to install; without it the processor draws the board.
- [tkinterdnd2](https://pypi.org/project/tkinterdnd2/) (optional, for drag & drop)
- [qoi](https://pypi.org/project/qoi/) (optional, for faster loading). The tool checks it on start and falls back to its built-in decoder if it doesn't work correctly.

## Project structure

```
xnb_board_tool_v2.py        launcher (run this)
build_exe.py / .bat         Windows build
check_translations.py       checks the translations against the texts in the code
ARCHITECTURE.md             how the code is organised (start here to change something)
CONTRIBUTING.md             setting up, testing, translating and releasing
tests/                      fake game generator, library tests and UI scenarios
xnb_board_tool/
  common.py                 errors, size limits, safe file writes
  diag.py                   start-up log, hang report, safe start
  i18n.py                   interface languages: _() / _n() lookups, plural rules, Windows language
  locales/                  pl.py, de.py, fr.py: {English text: translation}
  qoi.py                    QOI image codec (uses the qoi package if available)
  xnb.py                    XNB reading/writing (Texture2D, QOI, fonts, models)
  defaults.py               saved defaults and status hashing
  boards.py                 board scanning and board colors
  caches.py                 in-memory texture cache and on-disk gallery cache
  imageops.py               image fitting, rotation, thumbnails
  speedmeter.py             speedometer rendering, as the game draws it
  hud_recolor.py            speedometer bar recolouring
  hud_generate.py           generated speedometer bar textures
  hud_text.py               CMS / MMS text maker
  board3d.py                skateboard model, camera / lighting, software (numpy) 3D renderer
  gpu3d.py                  the same renderer on the graphics card (OpenGL 3.3 through ctypes)
  settings.py               themes, layouts, saved settings
  stickers.py               sticker packs on disk, .zip import / export
  basetex.py                base textures for decorating (built-in patterns, your images)
  layers.py                 layers, composing, editable-layer project files
  effects.py                sticker effects, sticker recolouring and the board finish
  textshapes.py             text layers (installed fonts) and simple shapes
  colorsuggest.py           board colour sets picked from the artwork
  icon.py                   the app's logo (exe icon and window / taskbar icon)
  assets/stickers/Starter/  the built-in Starter sticker pack
  gui/
    base.py                 Tk setup and shared widgets
    dialogs.py              Settings and Adjust image windows
    layouts.py              Studio / Gallery / Classic layouts, rebuilding the window
    shop.py                 Skate shop layout: the Wall, the Bench and the deck fan
    shop_settings.py        the Settings page of the Skate shop layout
    preview3d.py            3D preview panel
    speedmeter_tab.py       Speedmeter tab
    speed_shop.py           Speedmeter bench of the Skate shop layout
    speed_tools.py          speedometer bar texture and text makers
    decorate.py             Decorate (Advanced) and the Save decorations window
    app.py                  main window: state, loading, file actions
```

The core modules have no GUI code, so they can also be used from other scripts:

```python
from xnb_board_tool import scan, read_texture_palette
```

## Translations

The interface texts are written in English in the code, inside `_("...")`. Each language is one file in `xnb_board_tool/locales/` that maps the English text to the translation:

```python
T = {
    "Save decorations…": "Zapisz dekoracje…",
    "{n} layer": ["{n} warstwa", "{n} warstwy", "{n} warstw"],   # plural forms
}
```

- Keep the `{placeholders}` exactly as they are; they are filled in by the tool. A text with a broken placeholder falls back to English instead of breaking anything.
- Plural texts list one form per plural form of the language: Polish has three (1 / 2–4 / 5+), German and French two.
- A text missing from a file is shown in English.
- `python check_translations.py` lists missing, unused and broken entries for every language. Run it after changing texts in the code.
- To add a language, copy one of the files, translate it, and add it to `LANGS` and `load_catalog()` in `xnb_board_tool/i18n.py` (and its Windows language id to `detect()`).

## Credits

Designed and created by Mariusz Jarotek. Coded with the help of Claude AI by Anthropic.

## Disclaimer

This is a fan-made modding tool and is not affiliated with the developers of STUNTBOOST. Back up your files and use it at your own risk. Share only artwork you have the right to share.

## License

<!-- Choose a license, e.g. MIT: https://choosealicense.com/licenses/mit/ -->
TBD
