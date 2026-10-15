"""GPU renderer for the 3D board preview: OpenGL 3.3 through ctypes, no extra packages.

board3d.render_board() does the camera, lighting and culling maths (shared with the CPU
renderer) and hands the visible triangles to this module, which rasterizes them on the
graphics card and returns the same image and per-pixel data the CPU renderer makes.

All OpenGL work happens on one dedicated thread that owns the context: callers on any
thread queue a job and wait for its result. If anything here fails (no OpenGL 3.3, driver
trouble, Remote Desktop, a virtual machine...), board3d falls back to the CPU renderer.

Contexts: Windows uses WGL on a hidden window, Linux uses EGL (Mesa or a vendor driver).
Other systems use the CPU renderer.
"""
from __future__ import annotations

from .i18n import _

import ctypes as C
import os
import queue
import re
import sys
import threading
from typing import Optional

_WIN = sys.platform == "win32"
_FT = C.WINFUNCTYPE if _WIN else C.CFUNCTYPE

# ---- OpenGL constants ----
GL_TEXTURE_2D, GL_TEXTURE0 = 0x0DE1, 0x84C0
GL_TEXTURE_MIN_FILTER, GL_TEXTURE_MAG_FILTER, GL_NEAREST = 0x2801, 0x2800, 0x2600
GL_TEXTURE_WRAP_S, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE = 0x2802, 0x2803, 0x812F
GL_RGB8UI, GL_RGBA8, GL_RGBA32F, GL_DEPTH_COMPONENT32F = 0x8D7D, 0x8058, 0x8814, 0x8CAC
GL_RGB = 0x1907
GL_RGB_INTEGER, GL_RGBA_INTEGER, GL_RGBA, GL_DEPTH_COMPONENT = 0x8D98, 0x8D99, 0x1908, 0x1902
GL_UNSIGNED_BYTE, GL_FLOAT, GL_SHORT = 0x1401, 0x1406, 0x1402
GL_R32I, GL_R8UI, GL_R32F, GL_INT = 0x8235, 0x8232, 0x822E, 0x1404
GL_RED_INTEGER, GL_RED = 0x8D94, 0x1903
GL_UNPACK_ALIGNMENT, GL_PACK_ALIGNMENT = 0x0CF5, 0x0D05
GL_FRAMEBUFFER, GL_FRAMEBUFFER_COMPLETE = 0x8D40, 0x8CD5
GL_COLOR_ATTACHMENT0, GL_COLOR_ATTACHMENT1, GL_DEPTH_ATTACHMENT = 0x8CE0, 0x8CE1, 0x8D00
_ATT = [GL_COLOR_ATTACHMENT0 + k for k in range(5)]
GL_COLOR, GL_DEPTH = 0x1800, 0x1801
GL_DEPTH_TEST, GL_LESS, GL_CULL_FACE, GL_BLEND, GL_DITHER, GL_SCISSOR_TEST = \
    0x0B71, 0x0201, 0x0B44, 0x0BE2, 0x0BD0, 0x0C11
GL_VERTEX_SHADER, GL_FRAGMENT_SHADER = 0x8B31, 0x8B30
GL_COMPILE_STATUS, GL_LINK_STATUS, GL_INFO_LOG_LENGTH = 0x8B81, 0x8B82, 0x8B84
GL_ARRAY_BUFFER, GL_STREAM_DRAW, GL_TRIANGLES = 0x8892, 0x88E0, 0x0004
GL_VENDOR, GL_RENDERER, GL_VERSION, GL_MAX_TEXTURE_SIZE = 0x1F00, 0x1F01, 0x1F02, 0x0D33

_u, _i, _f, _p = C.c_uint, C.c_int, C.c_float, C.c_void_p
_SIGS = {
    "glGetString": (C.c_char_p, [_u]), "glGetError": (_u, []),
    "glGetIntegerv": (None, [_u, C.POINTER(_i)]),
    "glViewport": (None, [_i, _i, _i, _i]),
    "glEnable": (None, [_u]), "glDisable": (None, [_u]), "glDepthFunc": (None, [_u]),
    "glDepthMask": (None, [C.c_ubyte]),
    "glClearBufferfv": (None, [_u, _i, C.POINTER(_f)]),
    "glGenTextures": (None, [_i, C.POINTER(_u)]), "glDeleteTextures": (None, [_i, C.POINTER(_u)]),
    "glBindTexture": (None, [_u, _u]), "glActiveTexture": (None, [_u]),
    "glTexImage2D": (None, [_u, _i, _i, _i, _i, _i, _u, _u, _p]),
    "glTexParameteri": (None, [_u, _u, _i]), "glPixelStorei": (None, [_u, _i]),
    "glGenFramebuffers": (None, [_i, C.POINTER(_u)]), "glBindFramebuffer": (None, [_u, _u]),
    "glFramebufferTexture2D": (None, [_u, _u, _u, _u, _i]),
    "glCheckFramebufferStatus": (_u, [_u]),
    "glDrawBuffers": (None, [_i, C.POINTER(_u)]), "glReadBuffer": (None, [_u]),
    "glReadPixels": (None, [_i, _i, _i, _i, _u, _u, _p]),
    "glCreateShader": (_u, [_u]),
    "glShaderSource": (None, [_u, _i, C.POINTER(C.c_char_p), C.POINTER(_i)]),
    "glCompileShader": (None, [_u]), "glGetShaderiv": (None, [_u, _u, C.POINTER(_i)]),
    "glGetShaderInfoLog": (None, [_u, _i, C.POINTER(_i), C.c_char_p]),
    "glCreateProgram": (_u, []), "glAttachShader": (None, [_u, _u]),
    "glLinkProgram": (None, [_u]), "glGetProgramiv": (None, [_u, _u, C.POINTER(_i)]),
    "glGetProgramInfoLog": (None, [_u, _i, C.POINTER(_i), C.c_char_p]),
    "glUseProgram": (None, [_u]), "glGetUniformLocation": (_i, [_u, C.c_char_p]),
    "glUniform1i": (None, [_i, _i]), "glUniform1f": (None, [_i, _f]),
    "glUniform2f": (None, [_i, _f, _f]), "glUniform3f": (None, [_i, _f, _f, _f]),
    "glGenVertexArrays": (None, [_i, C.POINTER(_u)]), "glBindVertexArray": (None, [_u]),
    "glGenBuffers": (None, [_i, C.POINTER(_u)]), "glBindBuffer": (None, [_u, _u]),
    "glBufferData": (None, [_u, C.c_ssize_t, _p, _u]),
    "glVertexAttribPointer": (None, [_u, _i, _u, C.c_ubyte, _i, _p]),
    "glEnableVertexAttribArray": (None, [_u]),
    "glDrawArrays": (None, [_u, _i, _i]), "glFinish": (None, []),
}


_SOFTWARE = ("llvmpipe", "softpipe", "swrast", "software rasterizer", "gdi generic",
             "microsoft basic render")


class GpuError(RuntimeError):
    """The graphics card cannot be used (no driver, too old OpenGL, a driver error...). The app falls back to the
    CPU renderer and shows the message.
    """
    pass


class _GL:
    """OpenGL functions, looked up through the context's get_proc."""

    def __init__(self, get_proc):
        """Looks up every OpenGL function the renderer uses (see _SIGS); raises GpuError when one is missing."""
        for name, (res, args) in _SIGS.items():
            addr = get_proc(name)
            if not addr:
                raise GpuError(f"OpenGL function {name} is missing")
            setattr(self, name, _FT(res, *args)(addr))


# ---------------------------------------------------------------- contexts
class _WglContext:
    """Windows: a hidden window with an OpenGL context (owned by the GPU thread)."""

    def __init__(self):
        """Creates a hidden window and an OpenGL 3.3 core context on it with WGL (Windows). Raises GpuError when
        the driver offers no such context.
        """
        from ctypes import wintypes as W
        self.W = W
        user32 = C.WinDLL("user32", use_last_error=True)
        gdi32 = C.WinDLL("gdi32", use_last_error=True)
        k32 = C.WinDLL("kernel32", use_last_error=True)
        self.gl = gl = C.WinDLL("opengl32", use_last_error=True)
        self.user32 = user32

        WNDPROC = C.WINFUNCTYPE(W.LPARAM, W.HWND, W.UINT, W.WPARAM, W.LPARAM)
        user32.DefWindowProcW.restype = W.LPARAM
        user32.DefWindowProcW.argtypes = [W.HWND, W.UINT, W.WPARAM, W.LPARAM]

        class WNDCLASSW(C.Structure):
            """The Win32 WNDCLASSW structure (for registering the hidden window's class)."""
            _fields_ = [("style", W.UINT), ("lpfnWndProc", WNDPROC), ("cbClsExtra", C.c_int),
                        ("cbWndExtra", C.c_int), ("hInstance", W.HINSTANCE), ("hIcon", W.HICON),
                        ("hCursor", W.HANDLE), ("hbrBackground", W.HBRUSH),
                        ("lpszMenuName", W.LPCWSTR), ("lpszClassName", W.LPCWSTR)]

        class PFD(C.Structure):
            """The Win32 PIXELFORMATDESCRIPTOR structure (the window's pixel format)."""
            _fields_ = [("nSize", W.WORD), ("nVersion", W.WORD), ("dwFlags", W.DWORD),
                        ("iPixelType", C.c_ubyte), ("cColorBits", C.c_ubyte)] + \
                       [(n, C.c_ubyte) for n in (
                           "cRedBits", "cRedShift", "cGreenBits", "cGreenShift", "cBlueBits",
                           "cBlueShift", "cAlphaBits", "cAlphaShift", "cAccumBits", "cAccumRedBits",
                           "cAccumGreenBits", "cAccumBlueBits", "cAccumAlphaBits", "cDepthBits",
                           "cStencilBits", "cAuxBuffers", "iLayerType", "bReserved")] + \
                       [("dwLayerMask", W.DWORD), ("dwVisibleMask", W.DWORD), ("dwDamageMask", W.DWORD)]

        k32.GetModuleHandleW.restype = W.HMODULE
        k32.GetModuleHandleW.argtypes = [W.LPCWSTR]
        k32.GetProcAddress.restype = C.c_void_p
        k32.GetProcAddress.argtypes = [W.HMODULE, C.c_char_p]
        user32.RegisterClassW.restype = W.ATOM
        user32.RegisterClassW.argtypes = [C.POINTER(WNDCLASSW)]
        user32.CreateWindowExW.restype = W.HWND
        user32.CreateWindowExW.argtypes = [W.DWORD, W.LPCWSTR, W.LPCWSTR, W.DWORD, C.c_int, C.c_int,
                                           C.c_int, C.c_int, W.HWND, W.HMENU, W.HINSTANCE, W.LPVOID]
        user32.GetDC.restype = W.HDC
        user32.GetDC.argtypes = [W.HWND]
        user32.PeekMessageW.argtypes = [C.POINTER(W.MSG), W.HWND, W.UINT, W.UINT, W.UINT]
        user32.TranslateMessage.argtypes = [C.POINTER(W.MSG)]
        user32.DispatchMessageW.argtypes = [C.POINTER(W.MSG)]
        user32.DispatchMessageW.restype = W.LPARAM
        gdi32.ChoosePixelFormat.argtypes = [W.HDC, C.POINTER(PFD)]
        gdi32.SetPixelFormat.argtypes = [W.HDC, C.c_int, C.POINTER(PFD)]
        gl.wglCreateContext.restype = C.c_void_p
        gl.wglCreateContext.argtypes = [W.HDC]
        gl.wglMakeCurrent.argtypes = [W.HDC, C.c_void_p]
        gl.wglDeleteContext.argtypes = [C.c_void_p]
        gl.wglGetProcAddress.restype = C.c_void_p
        gl.wglGetProcAddress.argtypes = [C.c_char_p]

        hinst = k32.GetModuleHandleW(None)
        self._proc = WNDPROC(lambda h, m, w, l: user32.DefWindowProcW(h, m, w, l))  # keep alive
        self._wc = wc = WNDCLASSW()
        wc.style = 0x0020                                   # CS_OWNDC
        wc.lpfnWndProc = self._proc
        wc.hInstance = hinst
        wc.lpszClassName = "XNBBoardToolGL"
        if not user32.RegisterClassW(C.byref(wc)) and C.get_last_error() != 1410:  # already exists
            raise GpuError(f"RegisterClass failed ({C.get_last_error()})")
        self.hwnd = user32.CreateWindowExW(0, "XNBBoardToolGL", "XNB Board Tool GL", 0x80000000,  # WS_POPUP
                                           0, 0, 16, 16, None, None, hinst, None)
        if not self.hwnd:
            raise GpuError(f"CreateWindowEx failed ({C.get_last_error()})")
        self.hdc = user32.GetDC(self.hwnd)
        pfd = PFD()
        pfd.nSize, pfd.nVersion = C.sizeof(PFD), 1
        pfd.dwFlags = 0x04 | 0x20 | 0x01                     # draw to window, OpenGL, double buffer
        pfd.iPixelType, pfd.cColorBits, pfd.cDepthBits, pfd.cStencilBits = 0, 32, 24, 8
        fmt = gdi32.ChoosePixelFormat(self.hdc, C.byref(pfd))
        if not fmt or not gdi32.SetPixelFormat(self.hdc, fmt, C.byref(pfd)):
            raise GpuError(f"no OpenGL pixel format ({C.get_last_error()})")
        self.ctx = gl.wglCreateContext(self.hdc)
        if not self.ctx or not gl.wglMakeCurrent(self.hdc, self.ctx):
            raise GpuError(f"wglCreateContext failed ({C.get_last_error()})")
        self._k32, self._glmod = k32, k32.GetModuleHandleW("opengl32.dll")
        # old drivers give an OpenGL 1.x/2.x context here; ask for a 3.3 core context then
        if _version(self.get_proc) < (3, 3):
            addr = gl.wglGetProcAddress(b"wglCreateContextAttribsARB")
            if addr not in (None, 0, 1, 2, 3, 0xFFFFFFFF, 0xFFFFFFFFFFFFFFFF):
                make = C.WINFUNCTYPE(C.c_void_p, W.HDC, C.c_void_p, C.POINTER(C.c_int))(addr)
                attrs = (C.c_int * 7)(0x2091, 3, 0x2092, 3, 0x9126, 0x1, 0)   # 3.3 core
                ctx2 = make(self.hdc, None, attrs)
                if ctx2:
                    gl.wglMakeCurrent(None, None)
                    gl.wglDeleteContext(self.ctx)
                    self.ctx = ctx2
                    gl.wglMakeCurrent(self.hdc, self.ctx)
        self._msg = W.MSG()

    def get_proc(self, name: str):
        """The address of an OpenGL function: wglGetProcAddress for newer functions, opengl32.dll for the OpenGL
        1.1 ones it does not return.
        """
        b = name.encode()
        addr = self.gl.wglGetProcAddress(b)
        if addr in (None, 0, 1, 2, 3, 0xFFFFFFFF, 0xFFFFFFFFFFFFFFFF):
            addr = self._k32.GetProcAddress(self._glmod, b)     # OpenGL 1.1 functions
        return addr

    def pump(self):
        """Handle the hidden window's messages, so system broadcasts never wait on it."""
        u = self.user32
        while u.PeekMessageW(C.byref(self._msg), None, 0, 0, 1):          # PM_REMOVE
            u.TranslateMessage(C.byref(self._msg))
            u.DispatchMessageW(C.byref(self._msg))


class _EglContext:
    """Linux: an off-screen EGL context (works with Mesa and vendor drivers, with or without X)."""

    def __init__(self):
        """Creates an off-screen OpenGL 3.3 core context with EGL (Linux): tries the default display, then Mesa's
        surfaceless platform. Raises GpuError when none works.
        """
        egl = None
        for lib in ("libEGL.so.1", "libEGL.so"):
            try:
                egl = C.CDLL(lib)
                break
            except OSError:
                pass
        if egl is None:
            raise GpuError("libEGL not found")
        self.egl = egl
        egl.eglGetProcAddress.restype = C.c_void_p
        egl.eglGetProcAddress.argtypes = [C.c_char_p]
        egl.eglGetDisplay.restype = C.c_void_p
        egl.eglGetDisplay.argtypes = [C.c_void_p]
        egl.eglInitialize.argtypes = [C.c_void_p, C.POINTER(C.c_int), C.POINTER(C.c_int)]
        egl.eglChooseConfig.argtypes = [C.c_void_p, C.POINTER(C.c_int), C.POINTER(C.c_void_p),
                                        C.c_int, C.POINTER(C.c_int)]
        egl.eglCreateContext.restype = C.c_void_p
        egl.eglCreateContext.argtypes = [C.c_void_p, C.c_void_p, C.c_void_p, C.POINTER(C.c_int)]
        egl.eglCreatePbufferSurface.restype = C.c_void_p
        egl.eglCreatePbufferSurface.argtypes = [C.c_void_p, C.c_void_p, C.POINTER(C.c_int)]
        egl.eglMakeCurrent.argtypes = [C.c_void_p, C.c_void_p, C.c_void_p, C.c_void_p]
        egl.eglBindAPI.argtypes = [C.c_uint]
        displays = []
        try:
            displays.append(egl.eglGetDisplay(None))
        except Exception:
            pass
        addr = egl.eglGetProcAddress(b"eglGetPlatformDisplayEXT")
        if addr:
            f = C.CFUNCTYPE(C.c_void_p, C.c_int, C.c_void_p, C.c_void_p)(addr)
            displays.append(f(0x31DD, None, None))           # EGL_PLATFORM_SURFACELESS_MESA
        last = "no EGL display"
        for d in displays:
            if not d:
                continue
            ma, mi = C.c_int(), C.c_int()
            if not egl.eglInitialize(d, C.byref(ma), C.byref(mi)) or not egl.eglBindAPI(0x30A2):
                last = "eglInitialize failed"
                continue
            cfg, n = C.c_void_p(), C.c_int()
            attrs = (C.c_int * 5)(0x3040, 0x0008, 0x3033, 0x0001, 0x3038)   # OpenGL, pbuffer
            if not egl.eglChooseConfig(d, attrs, C.byref(cfg), 1, C.byref(n)) or n.value < 1:
                last = "no EGL config"
                continue
            ctx = egl.eglCreateContext(d, cfg, None, (C.c_int * 7)(0x3098, 3, 0x30FB, 3, 0x30FD, 1, 0x3038))
            surf = egl.eglCreatePbufferSurface(d, cfg, (C.c_int * 5)(0x3057, 1, 0x3056, 1, 0x3038))
            if ctx and surf and egl.eglMakeCurrent(d, surf, surf, ctx):
                self.display, self.ctx, self.surf = d, ctx, surf
                break
            last = "eglCreateContext failed"
        else:
            raise GpuError(last)
        self._libgl = None
        for lib in ("libOpenGL.so.0", "libGL.so.1"):
            try:
                self._libgl = C.CDLL(lib)
                break
            except OSError:
                pass

    def get_proc(self, name: str):
        """The address of an OpenGL function through eglGetProcAddress, falling back to libGL's own symbols."""
        addr = self.egl.eglGetProcAddress(name.encode())
        if not addr and self._libgl is not None:
            try:
                addr = C.cast(getattr(self._libgl, name), C.c_void_p).value
            except AttributeError:
                addr = None
        return addr

    def pump(self):
        """Nothing to do on Linux (Windows needs its hidden window's messages handled)."""
        pass


def _version(get_proc) -> tuple:
    """The OpenGL version of the current context as (major, minor); (0, 0) when it cannot be read."""
    f = _FT(C.c_char_p, C.c_uint)(get_proc("glGetString"))
    v = (f(GL_VERSION) or b"").decode("ascii", "replace")
    m = re.search(r"(\d+)\.(\d+)", v)
    return (int(m.group(1)), int(m.group(2))) if m else (0, 0)


# ---------------------------------------------------------------- shaders
_VS1 = b"""#version 330 core
layout(location = 0) in vec3 a_pos;     // screen x, screen y (pixels), view depth
layout(location = 1) in vec2 a_uv;
layout(location = 2) in vec3 a_flat;    // shade, part id, depth offset (screws)
uniform vec2 u_size;
out vec2 v_uv;
out float v_depth;
flat out vec3 v_flat;
void main() {
    // screen row 0 -> bottom of the GL image, so glReadPixels returns rows top to bottom
    vec2 ndc = vec2(a_pos.x / u_size.x * 2.0 - 1.0, a_pos.y / u_size.y * 2.0 - 1.0);
    gl_Position = vec4(ndc * a_pos.z, 0.0, a_pos.z);   // w = depth: perspective-correct like the CPU
    v_uv = a_uv;
    v_depth = a_pos.z;
    v_flat = a_flat;
}
"""

_FS1 = b"""#version 330 core
in vec2 v_uv;
in float v_depth;
flat in vec3 v_flat;
uniform usampler2D u_tex;
uniform vec2 u_range;                   // near, far (view depth)
layout(location = 0) out vec4 o_base;   // shaded color (0..255 floats), shade
layout(location = 1) out vec4 o_aux;    // texel x, texel y, part id, depth
void main() {
    ivec2 ts = textureSize(u_tex, 0);
    int tu = clamp(int(v_uv.x * float(ts.x)), 0, ts.x - 1);    // nearest, like the game
    int tv = clamp(int(v_uv.y * float(ts.y)), 0, ts.y - 1);
    vec3 t = vec3(texelFetch(u_tex, ivec2(tu, tv), 0).rgb);
    float d = v_depth - v_flat.z;
    o_base = vec4(t * v_flat.x, v_flat.x);
    o_aux = vec4(float(tu), float(tv), v_flat.y, d);
    gl_FragDepth = clamp((d - u_range.x) / (u_range.y - u_range.x), 0.0, 1.0);
}
"""

_VS2 = b"""#version 330 core
void main() {                           // one triangle covering the whole image
    vec2 p = vec2(float((gl_VertexID << 1) & 2), float(gl_VertexID & 2));
    gl_Position = vec4(p * 2.0 - 1.0, 0.0, 1.0);
}
"""

_FS2 = b"""#version 330 core
uniform sampler2D u_base;
uniform sampler2D u_aux;
uniform vec3 u_bg;
uniform float u_thr;
uniform int u_outline;
// written in the exact formats the app keeps, so reading them back needs no conversion
layout(location = 0) out vec4 o_color;  // final r, g, b (whole 0..255 levels, stored exactly)
layout(location = 1) out int o_texel;   // texel x | y << 16 as two int16 (-1 = background)
layout(location = 2) out uint o_part;   // part id (0 = background)
layout(location = 3) out float o_shade; // lighting factor
layout(location = 4) out uint o_edge;   // 1 = outline pixel
void main() {
    ivec2 p = ivec2(gl_FragCoord.xy);
    ivec2 sz = textureSize(u_aux, 0);
    vec4 a = texelFetch(u_aux, p, 0);
    vec4 b = texelFetch(u_base, p, 0);
    vec3 c = a.z > 0.5 ? b.rgb : u_bg;
    bool edge = false;
    if (u_outline != 0) {
        // outline where the part changes or the depth jumps, as the CPU renderer does
        for (int dy = -1; dy <= 1; dy++) {
            for (int dx = -1; dx <= 1; dx++) {
                ivec2 q = p + ivec2(dx, dy);
                if ((dx == 0 && dy == 0) || q.x < 0 || q.y < 0 || q.x >= sz.x || q.y >= sz.y) continue;
                vec4 n = texelFetch(u_aux, q, 0);
                if ((a.z > 0.5 || n.z > 0.5) && (a.z != n.z || abs(a.w - n.w) > u_thr)) edge = true;
            }
        }
    }
    if (edge) c *= 0.18;
    bool board = a.z > 0.5;
    o_color = vec4(clamp(floor(c), 0.0, 255.0) / 255.0, 1.0);
    int tx = board ? int(a.x) : -1;
    int ty = board ? int(a.y) : -1;
    o_texel = int((uint(ty) << 16) | (uint(tx) & 0xFFFFu));
    o_part = uint(a.z);
    o_shade = board ? b.a : 0.0;
    o_edge = edge ? 1u : 0u;
}
"""


# ---------------------------------------------------------------- renderer
class GpuRenderer:
    """Owns the OpenGL thread; render() can be called from any thread."""

    def __init__(self):
        """Starts the GPU thread, waits (up to 15 s) for it to set up OpenGL, then runs a self test. Raises
        GpuError (or the setup's error) when the card cannot be used.
        """
        self._q: queue.Queue = queue.Queue()
        self._ready = threading.Event()
        self._err: Optional[BaseException] = None
        self.name = ""
        threading.Thread(target=self._main, name="xnb-gpu", daemon=True).start()
        if not self._ready.wait(15):
            raise GpuError(_("the graphics driver did not respond"))
        if self._err is not None:
            raise self._err
        self._self_test()

    def _self_test(self):
        """Draws a tiny known scene and checks every output exactly; a driver that gets any of it
        wrong is not used (the CPU renderer takes over)."""
        import numpy as np
        tex = np.zeros((2, 2, 3), np.uint8)
        tex[0, 1] = (100, 150, 250)                     # texel x=1, y=0
        tri = [[0, 0], [8, 0], [0, 8]]                  # covers pixels with x + y < 7 (top left)
        verts = np.array([p + [5.0, 0.75, 0.25, 0.5, 2, 0] for p in tri], np.float32)
        out = self.render(verts, tex, 8, 8, (20.0, 21.0, 24.0), True, 1.0, 4.0, 6.0, True)
        f, tx = out["frame"], out["texel"]
        checks = [
            tuple(f[1, 3]) == (50, 75, 125),            # inside: texel * shade, rounded down
            tuple(f[6, 5]) == (20, 21, 24),             # outside: background (also: not upside down)
            int(out["oid"][1, 3]) == 2 and int(out["oid"][6, 5]) == 0,
            tuple(tx[1, 3]) == (1, 0) and tuple(tx[6, 5]) == (-1, -1),
            abs(float(out["shade"][1, 3]) - 0.5) < 1e-6,
            not out["edge"][1, 1] and not out["edge"][6, 5] and bool(out["edge"].any()),
        ]
        if not all(checks):
            raise GpuError(f"self-test failed {[i for i, ok in enumerate(checks) if not ok]}")

    # -- the GPU thread
    def _main(self):
        """The GPU thread: creates the context and the shaders, then runs the jobs that _call() queues, one at a
        time, keeping the window's messages flowing in between.
        """
        try:
            self.ctx = _WglContext() if _WIN else _EglContext()
            ver = _version(self.ctx.get_proc)
            if ver < (3, 3):
                raise GpuError(_("OpenGL {version} (3.3 needed)", version=f"{ver[0]}.{ver[1]}"))
            self.gl = _GL(self.ctx.get_proc)
            self._setup()
        except BaseException as e:      # noqa: BLE001 - reported to the caller
            self._err = e
            self._ready.set()
            return
        self._ready.set()
        while True:
            try:
                job = self._q.get(timeout=0.05)
            except queue.Empty:
                self.ctx.pump()
                continue
            fn, args, box, ev = job
            try:
                box.append(fn(*args))
            except BaseException as e:   # noqa: BLE001
                box.append(e)
            ev.set()
            self.ctx.pump()

    def _call(self, fn, *args):
        """Runs fn(*args) on the GPU thread and returns its result (or raises its error). Gives up with GpuError
        after 30 s.
        """
        box, ev = [], threading.Event()
        self._q.put((fn, args, box, ev))
        if not ev.wait(30):
            raise GpuError(_("the graphics driver stopped responding"))
        if isinstance(box[0], BaseException):
            raise box[0]
        return box[0]

    # -- GL helpers (GPU thread only)
    def _program(self, vs, fs):
        """Compiles and links a vertex + fragment shader pair; raises GpuError with the driver's log on failure.
        """
        g = self.gl
        prog = g.glCreateProgram()
        for kind, src in ((GL_VERTEX_SHADER, vs), (GL_FRAGMENT_SHADER, fs)):
            sh = g.glCreateShader(kind)
            g.glShaderSource(sh, 1, (C.c_char_p * 1)(src), None)
            g.glCompileShader(sh)
            ok = C.c_int()
            g.glGetShaderiv(sh, GL_COMPILE_STATUS, C.byref(ok))
            if not ok.value:
                raise GpuError("shader: " + self._log(sh, g.glGetShaderiv, g.glGetShaderInfoLog))
            g.glAttachShader(prog, sh)
        g.glLinkProgram(prog)
        ok = C.c_int()
        g.glGetProgramiv(prog, GL_LINK_STATUS, C.byref(ok))
        if not ok.value:
            raise GpuError("link: " + self._log(prog, g.glGetProgramiv, g.glGetProgramInfoLog))
        return prog

    def _log(self, obj, getiv, getlog):
        """The info log of a shader or program (for error messages)."""
        n = C.c_int()
        getiv(obj, GL_INFO_LOG_LENGTH, C.byref(n))
        buf = C.create_string_buffer(max(1, n.value))
        getlog(obj, len(buf), None, buf)
        return buf.value.decode("utf-8", "replace").strip()

    def _gen(self, fn):
        """Calls a glGen* function for one object and returns its id."""
        v = C.c_uint()
        fn(1, C.byref(v))
        return v.value

    def _tex(self, internal, fmt, typ, W, H, data=None):
        """Creates a 2D texture with nearest filtering and clamped edges, optionally filled with data."""
        g = self.gl
        t = self._gen(g.glGenTextures)
        g.glBindTexture(GL_TEXTURE_2D, t)
        for k, v in ((GL_TEXTURE_MIN_FILTER, GL_NEAREST), (GL_TEXTURE_MAG_FILTER, GL_NEAREST),
                     (GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE), (GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE)):
            g.glTexParameteri(GL_TEXTURE_2D, k, v)
        g.glTexImage2D(GL_TEXTURE_2D, 0, internal, W, H, 0, fmt, typ, data)
        return t

    def _setup(self):
        """Sets up everything once: refuses software OpenGL (unless XNB_GPU_ALLOW_SOFTWARE=1), builds both shader
        programs, the vertex buffer and the board texture, and reads the maximum texture size.
        """
        g = self.gl
        self.name = (g.glGetString(GL_RENDERER) or b"OpenGL").decode("utf-8", "replace").strip()
        # software OpenGL (no real driver) runs on the processor anyway: the CPU renderer is
        # tuned for that, so it is used instead. XNB_GPU_ALLOW_SOFTWARE=1 allows it (for testing).
        if any(w in self.name.lower() for w in _SOFTWARE) and \
                os.environ.get("XNB_GPU_ALLOW_SOFTWARE", "") in ("", "0"):
            raise GpuError(_("no graphics card driver ({name} is software OpenGL)", name=self.name))
        self.p1 = self._program(_VS1, _FS1)
        self.p2 = self._program(_VS2, _FS2)
        self.u1 = {n: g.glGetUniformLocation(self.p1, n.encode()) for n in ("u_size", "u_tex", "u_range")}
        self.u2 = {n: g.glGetUniformLocation(self.p2, n.encode())
                   for n in ("u_base", "u_aux", "u_bg", "u_thr", "u_outline")}
        self.vao1 = self._gen(g.glGenVertexArrays)
        self.vbo = self._gen(g.glGenBuffers)
        g.glBindVertexArray(self.vao1)
        g.glBindBuffer(GL_ARRAY_BUFFER, self.vbo)
        for loc, n, off in ((0, 3, 0), (1, 2, 12), (2, 3, 20)):
            g.glEnableVertexAttribArray(loc)
            g.glVertexAttribPointer(loc, n, GL_FLOAT, 0, 32, C.c_void_p(off))
        self.vao2 = self._gen(g.glGenVertexArrays)          # the full-screen pass needs no data
        self.board_tex = self._tex(GL_RGB8UI, GL_RGB_INTEGER, GL_UNSIGNED_BYTE, 1, 1,
                                   C.create_string_buffer(3))
        mx = C.c_int()
        g.glGetIntegerv(GL_MAX_TEXTURE_SIZE, C.byref(mx))
        self.max_size = mx.value or 4096
        self.size = None
        for cap in (GL_CULL_FACE, GL_BLEND, GL_DITHER, GL_SCISSOR_TEST):
            g.glDisable(cap)
        g.glPixelStorei(GL_UNPACK_ALIGNMENT, 1)
        g.glPixelStorei(GL_PACK_ALIGNMENT, 1)
        self._check("setup")

    def _targets(self, W, H):
        """Makes (or remakes, when the size changes) the off-screen render targets for a W x H frame: pass 1 writes
        colour, texel and depth; pass 2 writes the final frame, texel, part id, shade and outline.
        """
        if self.size == (W, H):
            return
        g = self.gl
        if self.size is not None:
            ids = (C.c_uint * len(self.targets))(*self.targets)
            g.glDeleteTextures(len(self.targets), ids)
        base = self._tex(GL_RGBA32F, GL_RGBA, GL_FLOAT, W, H)
        aux = self._tex(GL_RGBA32F, GL_RGBA, GL_FLOAT, W, H)
        depth = self._tex(GL_DEPTH_COMPONENT32F, GL_DEPTH_COMPONENT, GL_FLOAT, W, H)
        color = self._tex(GL_RGBA8, GL_RGBA, GL_UNSIGNED_BYTE, W, H)
        texel = self._tex(GL_R32I, GL_RED_INTEGER, GL_INT, W, H)
        part = self._tex(GL_R8UI, GL_RED_INTEGER, GL_UNSIGNED_BYTE, W, H)
        shade = self._tex(GL_R32F, GL_RED, GL_FLOAT, W, H)
        edge = self._tex(GL_R8UI, GL_RED_INTEGER, GL_UNSIGNED_BYTE, W, H)
        self.targets = (base, aux, depth, color, texel, part, shade, edge)
        if self.size is None:
            self.fbo1, self.fbo2 = self._gen(g.glGenFramebuffers), self._gen(g.glGenFramebuffers)
        for fbo, atts in ((self.fbo1, ((GL_COLOR_ATTACHMENT0, base), (GL_COLOR_ATTACHMENT1, aux),
                                       (GL_DEPTH_ATTACHMENT, depth))),
                          (self.fbo2, tuple(zip(_ATT, (color, texel, part, shade, edge))))):
            g.glBindFramebuffer(GL_FRAMEBUFFER, fbo)
            for att, t in atts:
                g.glFramebufferTexture2D(GL_FRAMEBUFFER, att, GL_TEXTURE_2D, t, 0)
            st = g.glCheckFramebufferStatus(GL_FRAMEBUFFER)
            if st != GL_FRAMEBUFFER_COMPLETE:
                raise GpuError(f"framebuffer incomplete (0x{st:x})")
        self.size = (W, H)

    def _check(self, where):
        """Raises GpuError when OpenGL reported an error (`where` names the step)."""
        err = self.gl.glGetError()
        if err:
            raise GpuError(f"OpenGL error 0x{err:x} ({where})")

    def _render(self, verts, texa, W, H, bg, outline, thr, near, far, want_info):
        """Draws one frame on the GPU thread: uploads the texture and triangles, pass 1 rasterises the board, pass
        2 adds the background and outline, then reads the results back into numpy arrays (see render()).
        """
        import numpy as np
        g = self.gl
        if max(W, H) > self.max_size or max(texa.shape[:2]) > self.max_size:
            raise GpuError(_("image larger than the graphics card allows"))
        self._targets(W, H)
        th, tw = texa.shape[:2]
        g.glActiveTexture(GL_TEXTURE0)
        g.glBindTexture(GL_TEXTURE_2D, self.board_tex)
        g.glTexImage2D(GL_TEXTURE_2D, 0, GL_RGB8UI, tw, th, 0, GL_RGB_INTEGER, GL_UNSIGNED_BYTE,
                       texa.ctypes.data)
        g.glBindVertexArray(self.vao1)
        g.glBindBuffer(GL_ARRAY_BUFFER, self.vbo)
        g.glBufferData(GL_ARRAY_BUFFER, verts.nbytes, verts.ctypes.data if len(verts) else None,
                       GL_STREAM_DRAW)
        g.glViewport(0, 0, W, H)
        # pass 1: triangles -> shaded color, texel, part, depth
        g.glBindFramebuffer(GL_FRAMEBUFFER, self.fbo1)
        g.glDrawBuffers(2, (C.c_uint * 2)(GL_COLOR_ATTACHMENT0, GL_COLOR_ATTACHMENT1))
        g.glClearBufferfv(GL_COLOR, 0, (C.c_float * 4)(0, 0, 0, 0))
        g.glClearBufferfv(GL_COLOR, 1, (C.c_float * 4)(-1, -1, 0, 1e9))
        g.glDepthMask(1)
        g.glClearBufferfv(GL_DEPTH, 0, (C.c_float * 1)(1.0))
        g.glEnable(GL_DEPTH_TEST)
        g.glDepthFunc(GL_LESS)
        g.glUseProgram(self.p1)
        g.glUniform2f(self.u1["u_size"], float(W), float(H))
        g.glUniform1i(self.u1["u_tex"], 0)
        g.glUniform2f(self.u1["u_range"], float(near), float(far))
        if len(verts):
            g.glDrawArrays(GL_TRIANGLES, 0, len(verts))
        # pass 2: background, outline, final 8-bit color
        g.glDisable(GL_DEPTH_TEST)
        g.glBindFramebuffer(GL_FRAMEBUFFER, self.fbo2)
        g.glDrawBuffers(5, (C.c_uint * 5)(*_ATT))
        g.glUseProgram(self.p2)
        base, aux = self.targets[0], self.targets[1]
        g.glActiveTexture(GL_TEXTURE0)
        g.glBindTexture(GL_TEXTURE_2D, base)
        g.glActiveTexture(GL_TEXTURE0 + 1)
        g.glBindTexture(GL_TEXTURE_2D, aux)
        g.glUniform1i(self.u2["u_base"], 0)
        g.glUniform1i(self.u2["u_aux"], 1)
        g.glUniform3f(self.u2["u_bg"], *bg)
        g.glUniform1f(self.u2["u_thr"], float(thr))
        g.glUniform1i(self.u2["u_outline"], 1 if outline else 0)
        g.glBindVertexArray(self.vao2)
        g.glDrawArrays(GL_TRIANGLES, 0, 3)
        g.glActiveTexture(GL_TEXTURE0)
        # read back (each straight into the numpy array the app keeps)
        def read(k, shape, dtype, fmt, typ):
            """Reads one render target back into a new numpy array of the given shape and type."""
            arr = np.empty(shape, dtype)
            g.glReadBuffer(_ATT[k])
            g.glReadPixels(0, 0, W, H, fmt, typ, arr.ctypes.data)
            return arr
        # plain RGB bytes and single-channel reads only: formats every driver handles
        out = {"frame": read(0, (H, W, 3), np.uint8, GL_RGB, GL_UNSIGNED_BYTE)}
        if outline:
            out["edge"] = read(4, (H, W), np.uint8, GL_RED_INTEGER, GL_UNSIGNED_BYTE).view(bool)
        if want_info:
            out["texel"] = read(1, (H, W), np.int32, GL_RED_INTEGER, GL_INT).view(np.int16).reshape(H, W, 2)
            out["oid"] = read(2, (H, W), np.uint8, GL_RED_INTEGER, GL_UNSIGNED_BYTE)
            out["shade"] = read(3, (H, W), np.float32, GL_RED, GL_FLOAT)
        self._check("render")
        return out

    def render(self, verts, texa, W, H, bg, outline, thr, near, far, want_info):
        """verts: float32 (n*3, 8) = screen x, y, depth, u, v, shade, part id, depth offset.
        Returns {'frame': HxWx3 uint8, 'edge': HxW bool (if outline), and with want_info
        'texel': HxWx2 int16 (-1 = background), 'oid': HxW uint8, 'shade': HxW float32}."""
        return self._call(self._render, verts, texa, int(W), int(H), bg, outline, thr, near, far,
                          want_info)


_renderer: Optional[GpuRenderer] = None
_lock = threading.Lock()
crash_marker = None     # Path set by the app: exists only while the GPU is being started


def get() -> GpuRenderer:
    """The shared GPU renderer (started on first use); raises if the GPU can't be used.
    A graphics driver can crash the whole program, which Python cannot catch. So a marker file
    is written while the GPU starts and removed when it works (or fails normally): if it is still
    there at the next start, the last start crashed and the GPU is not tried again."""
    global _renderer
    with _lock:
        if _renderer is None:
            if not _WIN and not sys.platform.startswith("linux"):
                raise GpuError(_("not supported on this system"))
            mark = crash_marker
            if mark is not None and mark.exists():
                raise GpuError(_("the graphics driver crashed the program last time"))
            try:
                if mark is not None:
                    mark.parent.mkdir(parents=True, exist_ok=True)
                    mark.write_text("the GPU renderer was starting\n")
            except OSError:
                mark = None
            try:
                _renderer = GpuRenderer()
            finally:
                if mark is not None:
                    try:
                        mark.unlink()
                    except OSError:
                        pass
        return _renderer


def clear_crash_marker() -> None:
    """Lets the GPU be tried again (the Settings checkbox was ticked again)."""
    if crash_marker is not None:
        try:
            crash_marker.unlink()
        except OSError:
            pass


def existing() -> Optional[GpuRenderer]:
    """The GPU renderer if it was already started, else None (does not start it)."""
    return _renderer


__all__ = ["GpuRenderer", "GpuError", "get", "existing"]
