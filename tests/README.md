# Tests

By default nothing here needs the game: `fixture.py` generates a fake STUNTBOOST folder (40 boards and the
speedometer textures, drawn by code, nothing taken from the game) in a temporary folder for every run.

To test on your own boards instead, including the 3D model, pass `--game <board folder>` to `run_ui.py` (or set
`XNB_TEST_GAME`). `gamecopy.py` then copies the boards, speedometer and model into a temporary folder, leaving
out stock copies and `.bak` files, so your game folder is only read and never changed.

| File | What it is |
|---|---|
| `fixture.py` | builds a fake game folder: boards (QOI in XNB, like the game) and speedometer textures |
| `gamecopy.py` | with `--game`: copies your boards, speedometer and model into a temporary folder |
| `test_core.py` | fast library tests, no window. `python tests/test_core.py` or `python -m pytest tests` |
| `run_ui.py` | opens the real window and runs a scenario from `scenarios/` |
| `scenarios/*.txt` | UI scenarios |
| `shots/` | screenshots the scenarios take (created when they run; not kept in git) |

## UI scenarios

```
python tests/run_ui.py --all                             every scenario on fake boards, each in a fresh window
python tests/run_ui.py --all --game "D:\...\Board"      the same on a copy of your own boards
python tests/run_ui.py tests/scenarios/02_deck_fan.txt   one scenario
python tests/run_ui.py SCENARIO --delay 3000             slower PC: wait longer between steps
```

The exit code is 0 when everything passed. Settings go to a temporary folder, so your own settings are not
changed. On Linux without a screen, start a virtual one first (`Xvfb :99 &` then `DISPLAY=:99 python ...`).

### Writing a scenario

A scenario is Python split into **steps** by lines that hold only `---`. After each step the runner lets Tk
work for `--delay` ms (1.5 s by default), so loading and redraws finish before the next step looks at them.
Steps share variables and can use:

- `app`: the running App. Call its methods the way a click would (`app.select(3)`, `app.shop_show("bench")`,
  `app._shop_tool_set("stock")`). The docstrings in `gui/` tell you what each method does.
- `base`: `xnb_board_tool.gui.base` (`base.root` is the window).
- `BOARDS`: the board folder that was opened.
- `shot("name.png")` or a line `SHOT name.png`: screenshot of the window into `tests/shots/`.

Use `assert` to check things; a failing assert, an exception in a step, or an exception in any Tk callback
fails the scenario. Example:

```python
# Selecting a deck puts it on the bench
kids = [int(k) for k in app.tree.get_children()]
app.select(kids[5]); app.shop_show("bench")
---
assert app.sel == kids[5] and app.shop_page == "bench"
SHOT bench.png
```

Scenarios should not depend on board numbers (fake boards and real games differ): pick decks by position, e.g.
`kids = [int(k) for k in app.tree.get_children()]` then `app.select(kids[3])`. Neither the fake game nor the copy has stock
copies, so every deck starts as "no backup" until a scenario saves one (`app.save_all_defaults(confirm=False)`).
