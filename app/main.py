# -*- coding: utf-8 -*-
"""程序入口。

运行：python -m app.main   （在项目根目录）
或双击 run.bat
"""
import os
import sys
import ctypes
import tkinter.messagebox as mb

# 允许直接 `python app/main.py` 运行
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _enable_dpi():
    """开启 PerMonitorV2 高 DPI 感知：4K/高缩放屏字体清晰。

    必须用 PMv2（context = -4）：它支持“高感知窗口托管低感知子窗口”，
    会自动缩放被托管的 scrcpy 画面而不销毁它；老的 PM v1 / 系统感知会杀掉
    被 set_owner 的 scrcpy 悬浮窗口，导致群控黑屏/消失。
    """
    try:
        if ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)):
            return
    except Exception:
        pass
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


_enable_dpi()

from app import config
from app.ui.main_window import App


def main():
    if not os.path.exists(config.SCRCPY_EXE) or not os.path.exists(config.ADB_EXE):
        mb.showerror("缺少引擎",
                     f"未找到投屏引擎，请确认 scrcpy 目录存在：\n{config.SCRCPY_DIR}")
        return
    App().run()


if __name__ == "__main__":
    main()
