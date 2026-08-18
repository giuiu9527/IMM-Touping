# -*- coding: utf-8 -*-
"""内置功能实现（发送文件 / 安装APK / Adb命令）。

每个功能用 @register 注册，主窗口工具栏会自动生成按钮。
handler 统一接收 app（主窗口实例），可拿到 selected_devices()/adb/log 等。
新增功能照葫芦画瓢即可，无需改动主窗口。
"""
import os
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from tkinter import filedialog, simpledialog, messagebox

from ..core.features import register


# ---------- 公共：对选中设备批量执行 ----------
def _device_log_name(app, device):
    """日志统一显示用户设置的编号，便于和投屏格子一一对应。"""
    number = app._display_number(device)
    return f"{number:02d}"


def _for_selected(app, title, task, *, parallel=False):
    """task(device) -> (ok, msg)；后台线程执行，结果写日志。"""
    devices = app.selected_devices()
    if not devices:
        messagebox.showinfo(title, "请先在左侧勾选至少一台设备")
        return

    def worker():
        app.log(f"=== {title} 开始，共 {len(devices)} 台 ===")
        def report(d, result):
            ok, msg = result
            flag = "[OK]" if ok else "[X]"
            app.log(f"  {flag} {_device_log_name(app, d)}: {msg[:120]}")

        if parallel:
            # adb 对每个序列号分别启动一个进程，可安全并行传输/安装。
            with ThreadPoolExecutor(max_workers=len(devices)) as pool:
                futures = {pool.submit(task, d): d for d in devices}
                for future in as_completed(futures):
                    d = futures[future]
                    try:
                        report(d, future.result())
                    except Exception as exc:
                        report(d, (False, str(exc)))
        else:
            for d in devices:
                try:
                    report(d, task(d))
                except Exception as exc:
                    report(d, (False, str(exc)))
        app.log(f"=== {title} 完成 ===")

    threading.Thread(target=worker, daemon=True).start()


# ---------- 拖入分发：apk 安装，其它推送 ----------
def handle_dropped_files(app, paths):
    apks = [p for p in paths if p.lower().endswith(".apk")]
    files = [p for p in paths if not p.lower().endswith(".apk")]
    if apks and not app.selected_devices():
        messagebox.showinfo("拖入", "请先勾选要操作的设备")
        return
    for apk in apks:
        _install_apk_path(app, apk)
    for f in files:
        _push_file_path(app, f)


def _install_apk_path(app, apk):
    name = os.path.basename(apk)
    _for_selected(app, f"安装APK [{name}]",
                  lambda d: app.adb.install(d.serial, apk), parallel=True)


def _push_file_path(app, path):
    name = os.path.basename(path)
    _for_selected(app, f"发送文件 [{name}]",
                  lambda d: app.adb.push(d.serial, path))


# ---------- 注册的工具栏功能 ----------
@register("send_file", "发送文件", order=10)
def send_file(app):
    paths = filedialog.askopenfilenames(title="选择要发送到手机的文件")
    for p in paths:
        _push_file_path(app, p)


@register("install_apk", "安装APK", order=20)
def install_apk(app):
    paths = filedialog.askopenfilenames(title="选择APK", filetypes=[("APK", "*.apk")])
    for p in paths:
        _install_apk_path(app, p)


@register("adb_cmd", "Adb命令", order=30)
def adb_cmd(app):
    if not app.selected_devices():
        messagebox.showinfo("Adb命令", "请先勾选设备")
        return
    cmd = simpledialog.askstring("Adb命令", "输入要执行的 adb shell 命令：")
    if not cmd:
        return
    _for_selected(app, f"adb shell {cmd}",
                  lambda d: app.adb.shell(d.serial, cmd))
