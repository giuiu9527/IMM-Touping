# -*- coding: utf-8 -*-
"""UI 小工具。"""


def center_window(win):
    """把窗口移动到屏幕中央（略偏上，视觉更居中）。"""
    win.update_idletasks()
    w = win.winfo_width() or win.winfo_reqwidth()
    h = win.winfo_height() or win.winfo_reqheight()
    sw = win.winfo_screenwidth()
    sh = win.winfo_screenheight()
    x = max(0, (sw - w) // 2)
    y = max(0, (sh - h) // 3)
    win.geometry(f"+{x}+{y}")


def bind_recursive(widget, sequence, func):
    """把事件绑定到控件本身及其所有子控件（用于右键菜单覆盖整行）。"""
    widget.bind(sequence, func)
    for child in widget.winfo_children():
        bind_recursive(child, sequence, func)
