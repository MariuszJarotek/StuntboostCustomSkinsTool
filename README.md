# XNB Board Texture Tool

A desktop tool for making your own skateboards in **STUNTBOOST**: new artwork, board colours, stickers, text
and effects, and a restyled speedometer. It also works with other MonoGame / XNA games that store images in
`.xnb` files.

Pick a deck, drop in any PNG or JPG or decorate it with stickers, choose its colours, and the tool writes a
game-ready `.xnb` for you. Every deck can go back to the original with one click.

! Tool created with usage of Claude AI: Code and Translations !

VirusTotal scan link - https://www.virustotal.com/gui/file/4e01c164e1638d4efd62473e45b83aa4ee3250b9f8f7414f24d9864e527f755d?nocache=1

<img width="2559" height="1390" alt="StuntboostBoardTool" src="https://github.com/user-attachments/assets/ffd3212d-3e59-49de-b211-d3a685f5f0ea" />

---

## Features

- **The Wall:** every deck of the game hanging on rails in its own art, labelled **Stock**, **Custom** or
  **No backup**, with filters and a search.
- **New artwork:** drop in PNG, JPG, BMP, TGA, GIF or WEBP, then position, zoom, rotate and flip it in the
  **Adjust image** window. The result always has the size the game expects.
- **Board colours:** click a part of the deck (border, under, wheels, truck) and pick a colour, or take one
  suggested from your artwork. Copy and paste a colour set between decks.
- **Advanced:** stickers, images, text and shapes as layers on the 3D board, base textures (carbon, camo,
  flames…), sticker effects (shadow, die-cut border, holographic…) and a finish for the whole deck (grip tape,
  worn edges, gloss…). A Starter pack of 24 stickers is included; make your own packs and share them as .zip.
- **Stock:** your deck next to the original, with every difference listed, and one click to put it back.
- **Speedmeter:** restyle the HUD speedometer with a live in-game preview: recolour or redraw the bar texture
  and make new unit text.
- **3D preview** on the game's own skateboard model, drawn on the graphics card when there is one.
- **Four languages** (English, Polski, Deutsch, Français), four layouts, four themes and three text sizes.
- **Safe:** a `.bak` backup before the first change, stock copies to go back to, and files are written so a
  crash can never leave half a file. Nothing is sent anywhere; the tool has no network code.
- **Fast:** decks load in the background, the next and previous ones are preloaded, statuses and pictures are
  cached on disk, and large folders open instantly the second time.

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

## A tour of the tool

The tool opens in the **Skate shop** layout. The tour follows the order you will usually work in:

**The Wall → Bench: General → Advanced → Stock → Speedmeter: Parts → Bar texture → Text → Settings**

Everything hangs from the line along the top of the window: the **Decks** and **Speedmeter** tabs on the left,
and on the right the **game-folder chip** (e.g. *STUNTBOOST · 101 DECKS · 3 CUSTOM · 2 UNSAVED*) and
**Settings**. Click the folder chip for the full path, **Change folder…**, **Copy path** and **Save all as stock**.

### First start

1. The tool asks for the folder with the boards: `Content\Models\Resources\Board` inside the game folder,
   for example `E:\SteamLibrary\steamapps\common\STUNTBOOST\Content\Models\Resources\Board`.
   The speedometer and the 3D board model are found from there automatically.
2. It offers to **save the current boards as stock**. Click **Yes**. This keeps a copy of every original deck,
   so you can always go back. (You can also do it later with **Save all as stock** in the folder chip.)

### 1. The Wall

Every deck of the game hangs on rails, in its own art and border colour, with its number and a label:

<img width="2559" height="1394" alt="MainWindow" src="https://github.com/user-attachments/assets/fbccd1c9-0e91-4f15-b8a2-1a6590c37a43" />

| Label | Meaning |
|---|---|
| **Stock** (green) | The deck is the same as its saved stock copy |
| **Custom** | The deck was changed since its stock copy was saved |
| **No backup** | No stock copy saved yet |

- The tags at the top filter the Wall: **All**, **Custom**, **Stock**, **No backup**, each with its count.
- Type in **Filter boards…** to find a deck by its number.
- Point at a deck and it lifts off the rail; **click it to put it on the Bench**.
- The black **On the bench** bar at the bottom tells you what isn't in the game yet (colours not written,
  decks with unsaved stickers) and takes you there.

### 2. The Bench: General

The deck you picked is now on the bench.

<img width="2559" height="1390" alt="The Bench General" src="https://github.com/user-attachments/assets/433c5cc5-1bd1-49c7-a294-75bc2fc4f304" />

**The title row**
- **‹ Wall** (or Esc) goes back to the Wall.
- The **deck tag** shows the deck's number and its status (Stock / Custom / No backup).
- The filter tags work like on the Wall.
- **The deck fan** on the right shows the other decks spread like a hand of cards. Click one to put it on the
  bench, use the **‹ ›** bars at both sides, or scroll the mouse wheel over the fan. It never ends: after the
  last deck comes the first. Changing the filter lifts the fan away and brings it back with only those decks;
  the deck on the bench stays put (with a dashed outline if the filter doesn't include it).

**The stage** on the left shows the deck:
- **3D**: the deck on the game's own skateboard model. Drag to turn it, scroll to zoom, use **3/4**, **Top**,
  **Bottom** and **Side** for fixed views. **Screws** and **Outline** show or hide those.
- **Top & bottom**: both sides of the deck, flat, side by side.

In both views, **click a part of the deck** (border, under, wheels, truck) to paint it.

**The General sheet** on the right has three sections:
- **Artwork**: the deck's texture. **Replace image…** (or drop an image on it) opens the **Adjust image**
  window: drag to position, scroll to zoom, choose **Fill / Fit / Stretch**, rotate, flip, and pick a colour
  for any uncovered area, then **Apply**. **Export PNG…** saves the artwork as a normal image, and
  **Open other .xnb…** opens any texture file. Tick **Keep these colors when replacing the texture image** to
  keep the deck's colours when you put in new art.
- **Paint**: the four board colours. Pick a part, then a colour (click the swatch or type `#rrggbb`). The
  round swatches below are colours taken from your artwork. **Copy** / **Paste** move a colour set between
  decks.
- **Thumbnail**: the small picture the game shows in the board shop. **Generate from texture** makes it from
  the artwork; **Replace…** and **Export PNG…** work as for the artwork.

New colours stay on screen until you click **Save board** in the bar at the bottom; **Revert** drops them.

### 3. Advanced

Click **Advanced** under the title row to decorate the deck. The Bench turns into the decorating view;
**General** or **Stock** takes you straight back, and unsaved work stays with its deck while you look at
others.

<img width="2559" height="1391" alt="The Bench Advanced" src="https://github.com/user-attachments/assets/d7534c93-6b1d-40ab-a4d7-49c0b986f104" />

**Left: Stickers | Textures | Effects** (the **«** button folds the panel away; drag its edge to resize it)
- **Stickers**: your sticker packs and their stickers. Drag a sticker onto the deck, or click it to add it in
  the middle. **+ New** makes a pack and **Add…** (or dropping images) fills it. The **⋯** menu next to
  **+ New** renames, deletes, exports or imports packs; export a pack as a **.zip** to share it, and import
  (or drop) someone else's .zip. Right-click a sticker to move it to another pack or remove it. Each pack is a
  folder in `stickers` next to the tool; the **Starter** pack of 24 stickers is added the first time.
- **Textures**: a base under your stickers: the board's own art, or Black, Black stripes, Carbon, Checker,
  Blueprint grid, Sunset, Hazard, Camo, Grain, Flames or Maple wood. **Tint** recolours it. **Add…** adds your
  own images (kept in `textures` next to the tool).
- **Effects** (0–100 %, shown live):
  - **Board finish** for the whole deck: **Grip tape**, **Matte grain**, **Worn edges** (the maple wood shows
    through at the nose and tail), **Faded** and **Gloss**.
  - **Selected sticker**: **Shadow**, **White border** (die-cut vinyl), **Raised**, **Worn** and
    **Holographic**.
  - **Sticker colour**: **Hue**, **Saturation** and **Tint**, to make stickers match your deck.

**Middle: the deck**, flat and in 3D side by side. Stickers can be moved on either.
- **Place stickers**: click a sticker to select it and drag to move it; it follows the deck's surface. Mouse
  wheel scales it, Shift+wheel rotates it. Right-drag turns the board.
- **View / colors**: dragging always turns the board.
- Clicking the wheels, trucks, screws or border changes that colour.

**Right: Layers and Board colors**
- **+ Image**, **+ Text** and **+ Shape** add a layer. Text uses any font installed on your PC, with colour,
  outline and a live preview. Shapes: racing stripes, center stripe, circle, ring, star, triangle, diamond,
  chevron and rounded bar.
- Select a layer to get its tools: **Fill** / **Fit**, **Rotate 90°**, **Flip**, **Duplicate**, **Delete**,
  **Order** (up / down), **Mirror** (a copy at the nose and tail, or on both sides; drag either and both
  move), **Opacity**, and **Edit…** for text and shapes.
- **Board colors → Suggest…** offers colour sets picked from your design.
- **Undo** / **Redo** sit in the title row (Ctrl+Z / Ctrl+Y) and cover every change.

**The bar at the bottom** shows the base texture and what isn't saved yet, with **Clear all**, **Revert** and
**Save board…**. Saving asks:
- **Override selected board**, or **Save to another board** (STUNTBOOST has a fixed set of boards, 0–100, so
  a design replaces a board rather than adding one).
- **Also update the thumbnail**.
- **Keep layers editable after saving**: the stickers stay separate and movable the next time you open the
  deck in Advanced (stored in `_board_defaults\decor\`).

Effects are painted into the texture, so the game shows them too.

### 4. Stock

Click **Stock** to compare the deck with its saved stock copy.

<img width="2557" height="1390" alt="The Bench Stock" src="https://github.com/user-attachments/assets/1cfa38b7-5ea1-43b9-b753-cec768148b84" />

- The stage shows **Now** (what the game shows) next to **Stock**, top and bottom. A tag counts the
  differences and lists them (e.g. *Border · was #d82020*, *The artwork differs from stock*).
  **Show what changed** outlines the changed parts.
- On the right: when the stock was saved and how it is stored, then
  **Put the whole deck back to stock** (texture and thumbnail), **Only the texture** or **Only the thumbnail**.
- **Make this the new stock → Save as stock…** keeps the deck as it is now as the version you go back to.

### 5. Speedmeter: Parts

Click **Speedmeter** in the header. The files are found in `Content\Textures\HUD\SpeedMeter`.

<img width="2559" height="1390" alt="Speedmeter Parts" src="https://github.com/user-attachments/assets/c8bcdded-4440-4fdc-872c-22a344bc5964" />

The big **in-game preview** draws the speedometer exactly the way the game does. Under it:
- **Speed** and **Charge** sliders (the charge is the black blocks of potential speed ahead of the bar), and
  **Precise (MM/S)** to switch the unit.
- **▶ Play run** (or Space) plays a run from 0 to your speed and back.
- **Game / Dark / Checker** above the preview change its backdrop.

**Parts** lists the five files the speedometer is made of:

| Part | File | What it is |
|---|---|---|
| Bar texture | `Texture.xnb` | The colour/pattern seen through the whole bar |
| Bar beginning | `BarBeginning.xnb` | The first section of the bar, above the unit text |
| Block | `Block.xnb` | Repeated to make the bar longer |
| CM/S text | `CMS.xnb` | The unit text (normal mode) |
| MM/S text | `MMS.xnb` | The unit text (precise mode) |

Pick one to see it, then **Replace image…**, **Export PNG…** or **Revert to default**.

How the game uses the bar texture (good to know when designing one):
- It's mapped to the **screen**, not to each block: the blocks are windows onto one long strip.
- Only the **lower rows** (about 68–154) are reached, and past the texture's edges it is **mirrored**.
- It **scrolls left** as the speed rises (0.3 px per bar pixel, up to 930 px), so the left part shows at low
  speeds and the middle and right as the bar fills. The highlighted box shows what is visible at the current
  speed.

### 6. Bar texture

<img width="2559" height="1391" alt="Speedmeter Bar Texture" src="https://github.com/user-attachments/assets/ac6ce24e-9613-4aa8-b5c3-1820cd4739f8" />

Two ways to get a new bar texture, as two big tabs:
- **Recolor mine** keeps your texture's light, shade and details and gives it new colours: presets
  (**Original**, **Fire**, **Ice**, **Toxic**, **Gold**, **Violet**, **Mono**, **Sunset**, **Neon**,
  **From deck**), then **Shift colors** (Hue, Saturation, Brightness) or **New colors** (three colours by shade
  or along the bar).
- **Make new** draws a new texture from a style: **Solid**, **Gradient**, **Speed zones**, **Chevrons**,
  **Checker**, **Carbon**, **Rainbow** or **Deck art**, with its colours (or **Colors from deck**), where the
  last colour is reached, and **Shine** for a round, lit look.

**Before** and **After** show the texture; **Save as PNG…** saves the result as an image.

### 7. Text

<img width="2559" height="1391" alt="Speedmeter Text" src="https://github.com/user-attachments/assets/9d51e1d1-4c28-4bcb-8080-4c52db14a2bf" />

The **Text maker** makes new unit text for under the bar:
- **Quick text**: **SPEED**, **KM/H**, **MPH**, **BOOST**, **GO!** or **Original**, or type your own for
  **Normal (CM/S)** and **Precise (MM/S)**.
- **Font**: the fonts as cards with a sample in their own lettering, or **Font file…** for a .ttf / .otf.
- **Size**, **Slant**, **Letter spacing**, **Weight** and **Align**.

Only the label changes; the numbers stay in cm/s (mm/s in precise mode).

Changes to the bar texture and the text stay on screen (the preview shows them) until you click
**Write to game** in the bar at the bottom; **Reset** drops them. A `.bak` backup is kept, and
**Revert to default** in Parts brings the original back. Every slider has ◀ ▶ arrows at its ends for fine
steps.

### 8. Settings

Click **Settings** in the header. Every change is used right away; **Done** or Esc closes the page.

<img width="2559" height="1391" alt="Settings" src="https://github.com/user-attachments/assets/7ed16cc8-d7f2-404e-ab86-2c951c7c82ed" />


- **Layout**: **Skate shop** (this tour), **Studio** (big 3D view in the middle, board list on the left),
  **Gallery** (every board as a card with its 4 colours) or **Classic** (texture and 3D side by side). The other
  layouts have the same tools; Advanced is called **Decorate** there.
- **Theme**: **Dark**, **Light**, **Concrete** (warm concrete, ink black and orange, made for the Skate shop)
  or **Blueprint** (its dark counterpart: navy drafting paper and amber).
- **Language**: **Automatic** follows the Windows display language, or pick **English**, **Polski**,
  **Deutsch** or **Français**.
- **Text size**: **Compact**, **Balanced** or **Large**, for every text in the tool.
- **Game folder**: where the boards are, how many decks were found, and **Change folder…**.
- **3D preview**: untick **Draw the 3D board on the graphics card (GPU)** if the 3D view looks wrong or the
  tool closes when it appears; the processor then draws it.
- **Credits**: who made the tool.

## Board colors

The first four pixels of the texture's top row hold the board's colors:

| Pixel (x, y) | Part |
|---|---|
| `0, 0` | Border |
| `1, 0` | Under (bottom of the deck) |
| `2, 0` | Wheels |
| `3, 0` | Truck (and screws) |

The tool edits these pixels for you, so you don't need an image editor. Copy produces text like `#d02020, #c8b400, #40c060, #4050c0` that you can share with other players. Paste reads it back.

## Keyboard shortcuts

| Keys | Action |
|---|---|
| Ctrl+O | Change the folder for the open tab (boards or speedmeter) |
| Ctrl+← / Ctrl+→ | Previous / next deck |
| Mouse wheel over the deck fan | Previous / next deck |
| Esc | Back from the Bench to the Wall; closes Settings |
| Enter (in the filter box) | Jump to the first matching board |
| Esc (in the filter box) | Clear the filter |
| Space (Speedmeter) | Play / stop a run |

In **Advanced**:

| Keys / mouse | Action |
|---|---|
| Drag a sticker on the deck | Move it |
| Mouse wheel / Shift+wheel over the selected sticker | Scale / rotate it around the cursor |
| Right-drag (or drag an empty spot) | Rotate the board |
| Click a wheel, truck, screw or the border | Change that color |
| R / F | Rotate 90° / flip the selected sticker |
| Delete, Ctrl+D | Delete / duplicate the selected sticker |
| Double-click a text or shape layer | Edit its text / colour |
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
    decorate.py             Advanced (Decorate in the other layouts) and the Save decorations window
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
GNU General Public License
