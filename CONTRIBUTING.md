# Working on the XNB Board Tool

How to run, test, change and release the tool. Read [ARCHITECTURE.md](ARCHITECTURE.md) first for the map
of the code.

## Set up

1. Python 3.9 or newer **with Tkinter** (the python.org installer for Windows includes it; on Linux install
   `python3-tk`).
2. Install the packages:

   ```
   pip install pillow numpy
   pip install qoi tkinterdnd2      # optional: faster QOI, drag & drop
   pip install pytest               # optional: nicer test output
   ```

3. Run it:

   ```
   python xnb_board_tool_v2.py                       # asks for a folder
   python xnb_board_tool_v2.py "D:\...\Content\Models\Resources\Board"
   ```

No game files at hand? Make a fake game folder with generated boards and speedometer textures (made by code,
nothing from the game):

```
python tests/fixture.py C:\temp\fakegame --boards 40
python xnb_board_tool_v2.py C:\temp\fakegame\STUNTBOOST\Content\Models\Resources\Board
```

The fake game has no 3D model (that file belongs to the game), so the 3D views show "Board model not found".

**Never test changes on your only copy of the game files.** The tool keeps `.bak` copies and stock copies,
but use a copy of the folder anyway.

## Tests

| Command | What it checks | Needs a screen |
|---|---|---|
| `python tests/test_core.py` | file formats, stock copies, board colours, plural rules, translations | no |
| `python tests/run_ui.py --all` | the real window: layouts, deck fan, filters, Stock, Settings, Decorate, Speedmeter | yes |
| `python check_translations.py` | every text has a translation with the right placeholders | no |

By default the tests use fake boards from `tests/fixture.py`, so they need no game files. To check the 3D views
and your real boards too, add `--game <board folder>` (it is only read; the tests work on a copy in a temporary
folder). Run all three before a release. Details and how to write a UI scenario are in [tests/README.md](tests/README.md).

## Code style

- Every function, method and class has a docstring that says **what it does and why**, not how. Keep it true
  when you change the code: a wrong docstring is worse than none.
- Comments explain decisions that are not obvious from the code ("the game reads only the lower rows").
- Lines up to 120 characters. Plain Python, no type checker required (type hints where they help).
- No Tk code in the library (`xnb_board_tool/*.py`); the GUI (`xnb_board_tool/gui/`) may use the library.
- Write files with `common.atomic_write` so a crash never leaves half a file.
- Background threads never touch Tk widgets: put results on a queue and pick them up in an `after()` poll
  (see "Threads" in ARCHITECTURE.md).

## Adding or changing user-visible text

1. Write the English text in the code inside `_("...")`. Use named placeholders:
   `_("Saved {n} boards", n=count)`. For a count use `_n("{n} board", "{n} boards", count)`.
   For texts in tables built when the module is imported, use `N_("...")` and translate with `_()` where
   the text is shown.
2. Run `python check_translations.py`. It lists the new texts as *missing* for every language.
3. Add the translations to `xnb_board_tool/locales/pl.py`, `de.py`, `fr.py`. Plural texts are lists: Polish
   has three forms (1 / 2–4 / 5+), German and French two. Keep `{placeholders}` exactly as in English.
4. Run the check again until it says 0 missing, 0 wrong. Remove entries it lists as *unused*.

If you do not speak a language, leave the text missing: it shows in English until someone translates it.

To add a language: copy a locale file, translate it, add it to `LANGS` and `load_catalog()` in `i18n.py`, its
Windows language id to `detect()`, and its plural rule to `_plural_index()` and `FORMS` in
`check_translations.py` if it is not "one / many".

## Adding a theme

Copy an entry in `settings.THEMES`; every key must be present (the GUI reads them all). Add the name to
`THEME_NAMES`. Themes made for the Skate shop also set `ink` and `onink`. Check it in every layout with
`tests/scenarios/01_layouts_and_themes.txt` (add your theme to the loop).

## Adding a setting

1. Default value in `settings.SETTINGS` and in `load_settings()` (with validation), and the key in
   `save_settings()`.
2. A control in `gui/dialogs.py` (Settings window of the classic layouts) and `gui/shop_settings.py` (Settings
   page of the Skate shop).
3. If changing it needs the window rebuilt, go through `apply_settings()` in `gui/layouts.py`.

## Releasing

1. Set the new version in **one place**: `__version__` in `xnb_board_tool/__init__.py` (`build_exe.py` reads
   it from there). Update the version in README.md's download instructions.
2. Run the tests and `check_translations.py`.
3. On Windows: `build_exe.bat` (or `python build_exe.py`). It makes
   `dist\XNB-Board-Tool-v<version>-windows.zip`. See the docstring at the top of `build_exe.py` for the
   options and why the folder build is the default (fewer antivirus false positives).
4. Try the built exe on a copy of the game folder, then upload the zip to a GitHub release.
