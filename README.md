# XNB Board Texture Tool

A small desktop tool for swapping skateboard textures in **STUNTBOOST** (and other MonoGame / XNA games that store images in `.xnb` files).

Pick a board, drop in any PNG or JPG, choose the board's colors, and the tool writes a game-ready `.xnb` for you. Backups and one-click revert are built in.

<img width="2559" height="1389" alt="StuntboostCustomSkinsTool" src="https://github.com/user-attachments/assets/b4f0b37e-168d-489a-bcb1-6815f1437dc3" />

---

## Features

- **Board browser:** lists every board in the content folder with a mini preview and a status marker.
  - 🟢 matches the saved default
  - 🟧 modified
  - ⭕ no default saved yet
- **Replace by drag & drop or file picker:** accepts PNG, JPG, BMP, TGA, GIF and WEBP.
- **Adjust before applying:** every new image opens an editor where you can drag to position it, zoom with the mouse wheel, choose **Fill / Fit / Stretch**, rotate (90° steps or any angle), flip, and pick a color or transparency for uncovered areas. A dimmed border shows what will be cut off. The result always has the original texture size, so the game gets exactly what it expects.
- **Board colors:** pick the border, under, wheels and truck colors with a color picker, or type `#rrggbb` / `r,g,b`. The tool writes them into the texture for you. You can copy and paste a color set between boards, and the colors are kept when you replace the artwork.
- **Thumbnails:** replace the thumbnail separately, or generate it from the board texture with one click.
- **Defaults and revert:** snapshot the current images as "defaults" and restore them exactly at any time. A `.bak` backup is also made before a file is first overwritten.
- **Export to PNG:** pull any board texture or thumbnail out of the game as a normal image.
- **Fast:** board statuses are checked in the background and cached, so large folders open instantly the second time.

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

1. Go to [Releases](../../releases) and download `XNB-Board-Tool-v1.0.0-windows.zip`.
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
   pip install pillow
   pip install tkinterdnd2   # optional, enables drag & drop
   ```
3. Run the tool:
   ```bash
   python xnb_board_tool_v2.py
   ```
   It asks for the content folder on start. You can also pass the folder directly:
   ```bash
   python xnb_board_tool_v2.py "Driver:\SteamLibrary\steamapps\common\STUNTBOOST\Content\Models\Resources\Board"
   ```

### Building the Windows version

You only need this if you want to build the release yourself. It requires Python 3.9+ from python.org on Windows.

1. Put `build_exe.bat` and `build_exe.py` next to `xnb_board_tool_v2.py`.
2. Double-click `build_exe.bat`. It installs PyInstaller, Pillow and tkinterdnd2, then builds the app.
3. The results are in the `dist` folder:
   - `dist\XNB Board Tool\`: the app folder
   - `dist\XNB-Board-Tool-v1.0.0-windows.zip`: the same folder zipped, ready to upload to a GitHub release

To make a single `.exe` instead, run `build_exe.bat --onefile`. Single-file builds are flagged by antivirus much more often, because they unpack themselves to a temp folder on every start. That's why the folder build is the default.

For further development:

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

### Board colors

The first four pixels of the texture's top row hold the board's colors:

| Pixel (x, y) | Part |
|---|---|
| `0, 0` | Border |
| `1, 0` | Under (bottom of the deck) |
| `2, 0` | Wheels |
| `3, 0` | Truck |

Example

<img width="325" height="310" alt="Pixel_Colors" src="https://github.com/user-attachments/assets/90afa051-1d06-4415-b6a2-52ab5f04225d" />
<img width="325" height="310" alt="skateboard_details_colors" src="https://github.com/user-attachments/assets/85bee722-2652-4758-9b08-ab46cb4daffd" />

The tool edits these pixels for you, so you don't need an image editor. Copy produces text like `#d02020, #c8b400, #40c060, #4050c0` that you can share with other players. Paste reads it back.

### Keyboard shortcuts

| Keys | Action |
|---|---|
| Ctrl+O | Open content folder |
| Ctrl+← / Ctrl+→ | Previous / next board |
| Enter (in the filter box) | Jump to the first matching board |
| Esc (in the filter box) | Clear the filter |

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

All of them can be deleted safely. You only lose the ability to revert.

## Safety

- The tool **does not** connect to the internet, run other programs or touch system folders, and it needs no administrator rights.
- It only writes the `.xnb` files you change, their backups, the `_board_defaults` folder, and PNG files you export.
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
- [tkinterdnd2](https://pypi.org/project/tkinterdnd2/) (optional, for drag & drop)

## Disclaimer

This is a fan-made modding tool and is not affiliated with the developers of STUNTBOOST. Back up your files and use it at your own risk. Share only artwork you have the right to share. Created with usage of claude.ai

## License

GPL-3.0 license
