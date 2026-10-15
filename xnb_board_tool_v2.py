#!/usr/bin/env python3
"""
XNB Board Texture Tool - starts the app.

Edits the board textures, thumbnails, board colours and speedometer of the game STUNTBOOST: replace images,
decorate a board in 3D with stickers, text and effects, keep stock copies and revert to them.

Usage:
    pip install pillow numpy
    pip install qoi tkinterdnd2      # optional: faster loading, drag & drop
    python xnb_board_tool_v2.py [content_folder]

This file only starts the GUI. The code lives in the xnb_board_tool package:
    README.md          what the tool does and how to use it
    ARCHITECTURE.md    how the code is organised
    CONTRIBUTING.md    setting up, testing, translating and releasing
"""
from __future__ import annotations

import sys

from xnb_board_tool import *  # noqa: F401,F403  (the library API, handy for scripting)
from xnb_board_tool.gui import run_gui

if __name__ == "__main__":
    run_gui(sys.argv[1] if len(sys.argv) > 1 else None)
