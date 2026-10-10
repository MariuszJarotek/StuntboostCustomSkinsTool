"""XNB Board Texture Tool - edit STUNTBOOST board and speedometer textures.

The library parts (formats, defaults, renderers) work without the GUI:

    from xnb_board_tool import load_texture, save_texture
"""
from __future__ import annotations

__version__ = "1.3.2"

from .common import *  # noqa: F401,F403
from .qoi import *  # noqa: F401,F403
from .xnb import *  # noqa: F401,F403
from .defaults import *  # noqa: F401,F403
from .boards import *  # noqa: F401,F403
from .caches import *  # noqa: F401,F403
from .imageops import *  # noqa: F401,F403
from .speedmeter import *  # noqa: F401,F403
from .board3d import *  # noqa: F401,F403
from .settings import *  # noqa: F401,F403
