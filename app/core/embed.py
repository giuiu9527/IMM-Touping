# -*- coding: utf-8 -*-
"""Windows 原生窗口嵌入辅助（用 ctypes，不依赖 pywin32）。

把 scrcpy 的画面窗口 SetParent 到软件里的某个 Tk 容器中，
从而实现“手机屏幕嵌在软件网格里”的效果（类似极限投屏）。
"""
import time
import ctypes
from ctypes import wintypes

user32 = ctypes.windll.user32

# 显式声明原型，避免 ctypes 按 Python int 猜类型导致 32 位溢出
user32.GetWindowLongW.restype = ctypes.c_long
user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
user32.SetWindowLongW.restype = ctypes.c_long
user32.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_long]

GWL_STYLE = -16
GWLP_HWNDPARENT = -8
GA_ROOT = 2
SW_SHOWNOACTIVATE = 4
SWP_NOACTIVATE = 0x0010
SWP_NOZORDER = 0x0004
SWP_SHOWWINDOW = 0x0040
WS_CHILD = 0x40000000
WS_POPUP = 0x80000000
WS_CAPTION = 0x00C00000
WS_THICKFRAME = 0x00040000
WS_BORDER = 0x00800000
WM_CLOSE = 0x0010

WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)


def find_hwnd_by_title(title: str, timeout: float = 10.0):
    """按精确标题轮询查找窗口句柄，找不到返回 None。"""
    found = []

    def _cb(hwnd, _lparam):
        n = user32.GetWindowTextLengthW(hwnd)
        buf = ctypes.create_unicode_buffer(n + 1)
        user32.GetWindowTextW(hwnd, buf, n + 1)
        if buf.value == title:
            found.append(hwnd)
            return False
        return True

    cb = WNDENUMPROC(_cb)
    end = time.time() + timeout
    while time.time() < end:
        found.clear()
        user32.EnumWindows(cb, 0)
        if found:
            return found[0]
        time.sleep(0.1)
    return None


def _to_signed32(v):
    v &= 0xFFFFFFFF
    return v - 0x100000000 if v & 0x80000000 else v


def embed(child_hwnd, parent_hwnd):
    """把 child 变成 parent 的子窗口，去掉标题栏/边框。"""
    style = user32.GetWindowLongW(child_hwnd, GWL_STYLE) & 0xFFFFFFFF
    style = (style & ~WS_POPUP & ~WS_CAPTION & ~WS_THICKFRAME & ~WS_BORDER) | WS_CHILD
    user32.SetWindowLongW(child_hwnd, GWL_STYLE, _to_signed32(style))
    user32.SetParent(child_hwnd, parent_hwnd)


def move(child_hwnd, x, y, w, h):
    if w > 0 and h > 0:
        user32.MoveWindow(child_hwnd, int(x), int(y), int(w), int(h), True)


# ---- 悬浮覆盖方案：把窗口设为主窗口的“从属窗口”，仍是顶层(渲染正常) ----
_SetOwner = getattr(user32, "SetWindowLongPtrW", user32.SetWindowLongW)
_SetOwner.restype = ctypes.c_void_p
_SetOwner.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_void_p]


def root_hwnd(hwnd):
    """取某个窗口所属的顶层窗口句柄。"""
    return user32.GetAncestor(hwnd, GA_ROOT)


def set_owner(child_hwnd, owner_hwnd):
    """让 child 从属于 owner：始终显示在 owner 之上、随 owner 最小化，但不裁剪、渲染正常。"""
    _SetOwner(child_hwnd, GWLP_HWNDPARENT, owner_hwnd)


def place(child_hwnd, x, y, w, h):
    """定位并显示，不抢焦点、不改变层级(避免把主窗口顶到独立窗口之上)。"""
    if w > 0 and h > 0:
        user32.SetWindowPos(child_hwnd, 0, int(x), int(y), int(w), int(h),
                            SWP_NOACTIVATE | SWP_SHOWWINDOW | SWP_NOZORDER)


def close(child_hwnd):
    user32.PostMessageW(child_hwnd, WM_CLOSE, 0, 0)
