# How the XNB Board Tool works

This is the map for anyone who wants to change the code. The user guide is [README.md](README.md); how to set
up, test and release is in [CONTRIBUTING.md](CONTRIBUTING.md).

Every function and class in the code has a docstring that says what it does. This file explains how the pieces
fit together, so you know which docstring to read.

## The big picture

```
xnb_board_tool_v2.py         launcher: run_gui(folder)
└── xnb_board_tool/          the library: files, images, rendering. No Tk in here.
    └── gui/                 the Tk window. Uses the library, never the other way round.
```

The library can be used from any script (`from xnb_board_tool import load_texture, save_texture, scan`), and
the tests in `tests/test_core.py` do exactly that.

## The game files

STUNTBOOST is a MonoGame game. Its content files are `.xnb` containers:

| What | Where (under `Content/`) | Format |
|---|---|---|
| Board texture (the artwork) | `Models/Resources/Board/<n>.xnb` | QOI image inside XNB (`BytingPipeline.QoiReader`) |
| Board thumbnail (board shop) | `Models/Resources/Board/<n>Thumbnail.xnb` | same |
| 3D board model | `Models/Export/Board.xnb` + `Board.bin.xnb` | glTF JSON + binary buffer inside XNB |
| Speedometer | `Textures/HUD/SpeedMeter/{Texture,BarBeginning,Block,CMS,MMS}.xnb` | QOI or MonoGame `Texture2D` |

- `xnb.py` reads and writes the XNB container. `load_texture()` returns a `TexData` (image + how it was
  stored); `save_texture()` writes a new image back the same way, keeps a one-time `.bak` and writes
  atomically. Compressed XNBs (LZX/LZ4) are not supported.
- `qoi.py` is the QOI codec (uses the fast `qoi` package when it is installed and works).
- **Board colours** are not separate files: they are the first 4 pixels of the texture's top row
  (border, under, wheels, truck). See `boards.read_palette` / `apply_palette`.
- `boards.scan()` finds the boards in a folder (texture + thumbnail pairs, or glTF board models).

## Stock copies ("defaults")

Before changing anything the user can save a **stock copy** of each file. `defaults.py` keeps them in a
`_board_defaults/` folder next to the boards:

- `<file>.json`: metadata (date, how it was stored, pixel hash)
- `<file>.default.png` (QOI files, when the PNG is not much bigger) or `<file>.default.xnbdef` (exact copy)
- `_hash_cache.json`: pixel hashes by size + mtime, so statuses are fast on the next start
- `decor/<file>/`: the editable layers of a decorated board (written by `layers.py`)

`file_status()` gives `"def"` (matches stock), `"mod"` (changed) or `"none"` (no stock copy).
`board_status()` combines the texture and thumbnail statuses. The Wall filters (All / Custom / Stock /
No backup) are these statuses.

## Library modules

| Module | Job |
|---|---|
| `common.py` | `XnbError`, size limits, `atomic_write` |
| `diag.py` | start-up log, hang report, safe start after a crash (see "Start-up" below) |
| `i18n.py` + `locales/` | translations: `_()`, `_n()`, `N_()` (see "Translations") |
| `settings.py` | themes (`THEMES`), layouts, text sizes, `settings.json`; the live colour table `C` |
| `caches.py` | `TEXCACHE` (recent decoded textures, about 24 MB, LRU) and `CardCache` (gallery cards on disk) |
| `imageops.py` | fitting/rotating an image into a texture size, thumbnails |
| `board3d.py` | board model, camera, the numpy software renderer, picking texels under the mouse |
| `gpu3d.py` | the same renderer in OpenGL 3.3 through ctypes, on its own thread; falls back to `board3d` |
| `speedmeter.py` | draws the in-game speedometer exactly as the game's code does |
| `hud_recolor.py`, `hud_generate.py`, `hud_text.py` | speedometer tools: recolour the bar, generate bar textures, make CMS/MMS text |
| `stickers.py` | sticker packs on disk, zip import/export |
| `basetex.py` | base textures for Decorate (built-in patterns, the user's images) |
| `layers.py` | Decorate layers, composing them into the texture, the editable-project files |
| `effects.py` | per-layer effects (shadow, die-cut border, ...), recolouring, the board finish |
| `textshapes.py` | text layers (system fonts) and shapes |
| `colorsuggest.py` | board colour sets picked from the artwork |
| `icon.py` | the app logo |

### Speedometer maths (speedmeter.py)

It follows the game's `SE.SpeedMeter.DrawInner` and the SpeedMeter shader: blocks every 164 px, bar length
41 px per cm/s, the bar texture is screen-mapped and scrolls 0.3 px per bar pixel (max 930), only its lower
rows are reached, and it is mirrored past its edges. If the game changes, this is the file to update.

## The GUI

### One App, many mixins

`gui/app.py` defines

```python
class App(LayoutsMixin, ShopMixin, ShopSettingsMixin, Preview3DMixin,
          SpeedmeterMixin, SpeedToolsMixin, SpeedShopMixin, DecorateMixin):
```

Each mixin lives in its own file and adds methods to the one `App` object; they all share `self`. So
`self.boards`, `self.sel`, `self.tex`, `self.pal` are visible everywhere. Prefixes tell you where a name comes
from:

| Prefix | File | Part of the window |
|---|---|---|
| *(none)* | `app.py` | state, loading, the board list, file actions (replace, export, revert, save colours) |
| `_layout_*`, `_gal_*` | `layouts.py` | Studio / Gallery / Classic layouts, header, `rebuild()` |
| `shop_*`, `_shop_*`, `_car_*` | `shop.py` | Skate shop layout: the Wall, the Bench, the deck fan |
| `_shop_settings_*` | `shop_settings.py` | the Settings page of the Skate shop layout |
| `v3_*`, `_v3_*` | `preview3d.py` | the 3D preview panel |
| `sm_*`, `_sm_*` | `speedmeter_tab.py` | Speedmeter tab (all layouts) |
| `sms_*`, `_sms_*` | `speed_shop.py` | Speedmeter bench in the Skate shop layout |
| `_bt_*`, `_tx_*` | `speed_tools.py` | speedometer bar-texture and text makers |
| `dc_*`, `_dc_*` | `decorate.py` | Decorate (called "Advanced" on the Bench) |

`gui/base.py` creates the Tk root and the fonts (`F`), and holds the shared widgets: `FlatButton`,
`SegButton`, `Slider`, `Scroll`, `Preview`, `button()`, `label()`, `more_button()`. `gui/dialogs.py` has the
Settings window and the Adjust-image editor.

### Layouts share widget names

Every layout builds widgets with the **same attribute names** (`self.title_lbl`, `self.tex_prev`,
`self.pal_widgets`, `self.b_tex_replace`, ...). That is why the actions in `app.py` work in every layout
without knowing which one is shown. When you add a widget that `app.py` touches, create it in every layout
(or guard with `hasattr`).

### Themes and rebuilding

Colours come from `settings.C` (a dict filled by `set_theme()`), fonts from `base.F`. Widgets read them when
they are built, so changing the theme, layout, language or text size calls `rebuild()` (`layouts.py`): it
saves what the user was doing into `self._keep`, destroys the window content, and builds it again. If you add
UI state that should survive a theme change, add it to `_keep` in `rebuild()` and read it back when building.

The Skate shop themes (`concrete`, `blueprint`) also define `ink` / `onink` for the black rails and tags;
`shop.ink()` falls back to the text colour for themes without them.

### The Skate shop layout (default)

- **Header**: the shop sign, Decks / Speedmeter tabs, folder chip, Settings.
- **The Wall** (`shop_show("wall")`): every deck hanging on rails, filtered by status (`_shop_set_filter`).
- **The Bench** (`shop_show("bench")`): one deck. The title row has the Wall button, the deck tag
  (`DeckTag`), the filter tags and the **deck fan** (`_car_*`). Below it the tools: General, Advanced
  (= Decorate) and Stock (compare with the stock copy).
- **The deck fan** draws the decks of the current filter as a ring hanging from a pivot far above the
  window. `_car_shown()` is the list of decks in the fan; when the filter hides the deck on the bench it stays
  in the fan as a *guest* (`_car_guest()`, drawn dashed). Changing the filter never changes the deck on the
  bench; it plays the "drawer" animation (`_shop_filter_swap`). Rotated deck images are cached per 1°.
  Constants `CAR_*` at the top of the section set its size and speed.

### Threads

Tk may only be used from the main thread. Background work goes through queues that the main thread polls:

| Worker | Started in | Result picked up by |
|---|---|---|
| Board statuses, list strips, gallery cards | `App._start_worker` | `App._poll` (every 60 ms) |
| Loading the selected board | `App._load_current` | `App._load_poll` |
| Pre-loading the neighbours | `App._prefetch_loop` | (only fills `TEXCACHE`) |
| 3D preview frames | `Preview3DMixin` | its own `after()` poll |
| Decorate 3D frames | `decorate.Renderer` | `DecorateMixin._dc_poll` |
| Speedometer preview | `speedmeter_tab.py` | its own `after()` poll |
| OpenGL | `gpu3d.py` (one thread owns the GL context) | called synchronously through a queue |

Each job carries a generation number (`self.gen`, `self._load_gen`); results from an older generation (the
user already moved on) are dropped. Follow the same pattern for new background work.

### Start-up

`gui.run_gui()` → `diag.start()` (writes `startup.log`, arms the hang detector) → `base.init()` (Tk root,
fonts) → `App()`. If the previous start never finished, `diag.SAFE` is set: English and CPU 3D. The GPU
renderer runs a self-test and falls back to the CPU on any driver trouble; `XNB_NO_GPU=1` turns it off.

## Translations

All user-visible text is English in the code, wrapped in `_("...")`, `_n("one", "many", n)` or `N_("...")`
(`N_` marks a text for translation without translating it yet, for tables built at import time). Placeholders
use names: `_("Board {name}", name=b.name)`. Each language is `locales/<code>.py` with a dict
`{English: translation}` (plural texts map to a list of forms). Missing texts show in English.

`python check_translations.py` lists missing, unused and broken entries. See CONTRIBUTING.md for the workflow.

## Where to start for common changes

| I want to ... | Look at |
|---|---|
| support a new texture format | `xnb.py` (`load_texture`, `save_texture`) |
| change how boards are found | `boards.scan` |
| add a setting | `settings.py` (default, `load_settings`, `save_settings`), `gui/dialogs.py` and `gui/shop_settings.py` |
| add a theme | `settings.THEMES` + `THEME_NAMES` (every key of an existing theme is needed) |
| change the Wall or the Bench | `gui/shop.py` (sections are marked with `# ---- the Wall`, `the Bench`, `the deck fan`) |
| add a Decorate effect | `effects.py` (the effect), `gui/decorate.py` `_dc_build_effects` (the slider) |
| add a built-in base texture | `basetex.BUILTIN` |
| change the speedometer preview | `speedmeter.py` |
