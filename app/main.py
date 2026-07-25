# -*- coding: utf-8 -*-
"""程序入口。

运行：python -m app.main   （在项目根目录）
或双击 run.bat
"""
import os
import sys
import tkinter.messagebox as mb

# 允许直接 `python app/main.py` 运行
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# 注意：不要在这里开启进程级 DPI 感知。
# 实测进程一旦 DPI-aware，被本程序“从属化(SetParent/set_owner)”的 scrcpy 悬浮窗口
# 会在几秒内被系统销毁，导致群控画面消失。字体清晰度改用其它方式处理。

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
