# -*- coding: utf-8 -*-
"""Windows 原生窗口悬浮嵌入辅助（用 ctypes，不依赖 pywin32）。

做法（见 AI_NOTES 坑#1）：**不把 scrcpy 窗口 SetParent 成真子窗口**（那样 SDL 会纯黑），
而是用 `SetWindowLongPtr(GWLP_HWNDPARENT)` 把它设成主窗口的“从属窗口(owned window)”，
仍是顶层窗口(渲染正常)，再用 `SetWindowPos` 定位到软件网格的格子上。
"""
import time
import ctypes
from ctypes import wintypes

user32 = ctypes.windll.user32

GWLP_HWNDPARENT = -8
GWL_EXSTYLE = -20
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_APPWINDOW = 0x00040000
GA_ROOT = 2
SW_HIDE = 0
SW_SHOWNA = 8                  # 显示但不激活、不改 Z 序
SW_SHOWNOACTIVATE = 4          # 显示但不抢焦点（独立窗口恢复时重新显示 scrcpy 用）
SWP_NOACTIVATE = 0x0010
SWP_NOZORDER = 0x0004
SWP_SHOWWINDOW = 0x0040
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


# 把窗口设为某窗口的“从属窗口”：始终显示在其上、随其最小化，但不裁剪、渲染正常。
_SetOwner = getattr(user32, "SetWindowLongPtrW", user32.SetWindowLongW)
_SetOwner.restype = ctypes.c_void_p
_SetOwner.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_void_p]


def root_hwnd(hwnd):
    """取某个窗口所属的顶层窗口句柄。"""
    return user32.GetAncestor(hwnd, GA_ROOT)


def set_owner(child_hwnd, owner_hwnd):
    """让 child 从属于 owner（owned window，非子窗口）。"""
    _SetOwner(child_hwnd, GWLP_HWNDPARENT, owner_hwnd)


def place(child_hwnd, x, y, w, h):
    """定位并显示，不抢焦点、不改层级（避免把主窗口顶到独立窗口之上）。"""
    if w > 0 and h > 0:
        user32.SetWindowPos(child_hwnd, 0, int(x), int(y), int(w), int(h),
                            SWP_NOACTIVATE | SWP_SHOWWINDOW | SWP_NOZORDER)


def raise_over(child_hwnd, x, y, w, h):
    """提到最前并定位（会改层级）。用于接管前先把画面显示出来，避免黑屏等待。"""
    if w > 0 and h > 0:
        user32.SetWindowPos(child_hwnd, 0, int(x), int(y), int(w), int(h),
                            SWP_NOACTIVATE | SWP_SHOWWINDOW)   # HWND_TOP，抬到最前


user32.BeginDeferWindowPos.restype = ctypes.c_void_p
user32.BeginDeferWindowPos.argtypes = [ctypes.c_int]
user32.DeferWindowPos.restype = ctypes.c_void_p
user32.DeferWindowPos.argtypes = [ctypes.c_void_p, wintypes.HWND, wintypes.HWND,
                                  ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                  ctypes.c_uint]
user32.EndDeferWindowPos.argtypes = [ctypes.c_void_p]


def batch_place(items):
    """一次性(原子)定位多个窗口，拖动时更跟手、不闪。items=[(hwnd,x,y,w,h),...]"""
    items = [it for it in items if it[0] and it[3] > 0 and it[4] > 0]
    if not items:
        return
    hdwp = user32.BeginDeferWindowPos(len(items))
    if not hdwp:
        for h, x, y, w, ht in items:
            place(h, x, y, w, ht)
        return
    flags = SWP_NOACTIVATE | SWP_SHOWWINDOW | SWP_NOZORDER
    for h, x, y, w, ht in items:
        hdwp = user32.DeferWindowPos(hdwp, h, None, int(x), int(y), int(w), int(ht), flags)
        if not hdwp:
            return
    user32.EndDeferWindowPos(hdwp)


user32.GetWindowLongW.restype = ctypes.c_long
user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
user32.SetWindowLongW.restype = ctypes.c_long
user32.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_long]


def hide_from_taskbar(hwnd):
    """把窗口改成“工具窗口”，使其不在任务栏显示（录制用的隐藏窗口不该占任务栏图标）。

    改扩展样式后需 hide→show 一次让任务栏刷新；窗口本在屏幕外(-3000)，无可见闪烁。
    """
    ex = user32.GetWindowLongW(hwnd, GWL_EXSTYLE) & 0xFFFFFFFF
    ex = (ex & ~WS_EX_APPWINDOW) | WS_EX_TOOLWINDOW
    ex_signed = ex - 0x100000000 if ex & 0x80000000 else ex
    user32.SetWindowLongW(hwnd, GWL_EXSTYLE, ex_signed)
    user32.ShowWindow(hwnd, SW_HIDE)
    user32.ShowWindow(hwnd, SW_SHOWNA)


def close(child_hwnd):
    user32.PostMessageW(child_hwnd, WM_CLOSE, 0, 0)
