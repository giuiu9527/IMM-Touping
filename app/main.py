# -*- coding: utf-8 -*-
"""程序入口（Tkinter 版界面）。

运行：python -m app.main （在项目根目录）或双击 run.bat。
注意：PyQt6 版界面在 app/ui/qt_main_window.py，如需切换在本文件末尾改用 QtMainWindow 即可。
"""
import os
import sys
import ctypes
import tkinter.messagebox as mb

# 允许直接 `python app/main.py` 运行
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _enable_dpi():
    """开启 PerMonitorV2 高 DPI 感知，并注册 AppUserModelID 保证任务栏图标清晰。

    坑#1：Tkinter 版必须在建窗口前设 PerMonitorV2(-4)，否则被从属化的 scrcpy 窗口会被杀→黑屏。
    """
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("loadingkuu.imm_touping.app.v0")
    except Exception:
        pass
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

# 全局日志：未捕获异常写入 app.log，方便排查
import logging
import traceback

LOG_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app.log")
logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    encoding="utf-8",
)


def log_uncaught_exceptions(exctype, value, tb):
    err_msg = "".join(traceback.format_exception(exctype, value, tb))
    logging.critical(f"Uncaught exception:\n{err_msg}")
    print(err_msg, file=sys.stderr)


sys.excepthook = log_uncaught_exceptions

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
