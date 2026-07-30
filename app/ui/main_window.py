# -*- coding: utf-8 -*-
"""主窗口：现代深色界面（ttkbootstrap）。

左侧控制面板 + 右侧嵌入式投屏网格。设备连上自动出现在网格里。
标签：单击=激活(移到最前并高亮)，双击设备行=编辑标签/编号。
"""
import os
import re
import sys
import threading
import datetime
import tkinter as tk
from tkinter import messagebox
import ttkbootstrap as tb
from ttkbootstrap.constants import LEFT, RIGHT, X, Y, BOTH, W

import webbrowser
from .. import config
from ..core.adb import Adb
from ..core.scrcpy import ScrcpyManager
from ..core.apiserver import ApiServer
from ..core import embed, updater
from ..core.features import all_features
from . import actions  # noqa: F401  导入即注册内置功能
from .actions import handle_dropped_files
from .settings_dialog import SettingsDialog
from .util import center_window, bind_recursive

try:
    from tkinterdnd2 import TkinterDnD, DND_FILES
    _HAS_DND = True
except Exception:
    _HAS_DND = False

import time

THEME = "cosmo"          # 亮色现代主题
FONT = "微软雅黑"

# 手机导航按键
KEY_BACK, KEY_HOME, KEY_RECENT = 4, 3, 187

# 编辑弹窗里标签块的配色（循环）
TAG_COLORS = ["#3a6ea5", "#2e8b57", "#a0522d", "#8a2be2", "#b8860b", "#008b8b"]


def tag_color(text):
    return TAG_COLORS[hash(text) % len(TAG_COLORS)]


class EditDeviceDialog(tb.Toplevel):
    """修改设备标签(可多个) / 编号。"""
    def __init__(self, master, cur_tags, cur_number, on_ok, on_record=None):
        super().__init__(master)
        self.title("修改设备")
        self.resizable(False, False)
        self.transient(master)
        self.on_ok = on_ok
        self.on_record = on_record
        self.tags = list(cur_tags)

        tb.Label(self, text="标签（可多个，单击标签可设为主标签）").pack(
            anchor=W, padx=12, pady=(12, 4))
        self.chip_area = tb.Frame(self)
        self.chip_area.pack(fill=X, padx=12)

        add = tb.Frame(self)
        add.pack(fill=X, padx=12, pady=8)
        self.v_new = tk.StringVar()
        e = tb.Entry(add, textvariable=self.v_new, width=18)
        e.pack(side=LEFT)
        e.bind("<Return>", lambda ev: self._add())
        tb.Button(add, text="添加标签", bootstyle="info-outline",
                  command=self._add).pack(side=LEFT, padx=6)

        num = tb.Frame(self)
        num.pack(fill=X, padx=12, pady=(0, 8))
        tb.Label(num, text="编号：").pack(side=LEFT)
        self.v_num = tk.StringVar(value=str(cur_number))
        tb.Entry(num, textvariable=self.v_num, width=8).pack(side=LEFT)

        bar = tb.Frame(self)
        bar.pack(fill=X, padx=12, pady=(4, 12))
        tb.Button(bar, text="确定", bootstyle="success",
                  command=self._ok).pack(side=RIGHT, padx=4)
        tb.Button(bar, text="取消", bootstyle="secondary-outline",
                  command=self.destroy).pack(side=RIGHT)
        if self.on_record:
            tb.Button(bar, text="该设备录制设置", bootstyle="info-outline",
                      command=self.on_record).pack(side=LEFT)

        self._render_chips()
        center_window(self)
        e.focus_set()
        self.grab_set()

    def _render_chips(self):
        for w in self.chip_area.winfo_children():
            w.destroy()
        if not self.tags:
            tb.Label(self.chip_area, text="(暂无标签，默认显示型号)",
                     bootstyle="secondary").pack(side=LEFT)
        for t in self.tags:
            c = tag_color(t)
            chip = tk.Frame(self.chip_area, bg=c)
            chip.pack(side=LEFT, padx=2, pady=2)
            tk.Label(chip, text=t, bg=c, fg="white", font=(FONT, 9)).pack(side=LEFT, padx=(5, 0))
            tk.Button(chip, text="×", bg=c, fg="white", bd=0, font=(FONT, 9),
                      activebackground=c, cursor="hand2",
                      command=lambda x=t: self._remove(x)).pack(side=LEFT)

    def _add(self):
        t = self.v_new.get().strip()
        if t and t not in self.tags:
            self.tags.append(t)
        self.v_new.set("")
        self._render_chips()

    def _remove(self, t):
        if t in self.tags:
            self.tags.remove(t)
        self._render_chips()

    def _ok(self):
        try:
            num = int(self.v_num.get())
        except ValueError:
            num = 0
        self.on_ok(self.tags, num)
        self.destroy()


class UpdateDialog(tb.Toplevel):
    """自动更新：下载新版(带进度) -> 替换 -> 重启。"""
    def __init__(self, app, info):
        super().__init__(app.root)
        self.app = app
        self.info = info
        self.title("软件更新")
        self.resizable(False, False)
        self.transient(app.root)
        tb.Label(self, text=f"发现新版本 v{info['version']}（当前 v{config.APP_VERSION}）",
                 font=(FONT, 11, "bold")).pack(padx=24, pady=(18, 6))
        self.status = tb.Label(self, text="点击「立即更新」自动下载并重启", bootstyle="secondary")
        self.status.pack(padx=24)
        self.pb = tb.Progressbar(self, length=340, mode="determinate")
        self.pb.pack(padx=24, pady=12)
        bar = tb.Frame(self)
        bar.pack(padx=24, pady=(0, 18), fill=X)
        self.btn = tb.Button(bar, text="立即更新", bootstyle="success", command=self._start)
        self.btn.pack(side=RIGHT, padx=4)
        tb.Button(bar, text="以后再说", bootstyle="secondary-outline",
                  command=self.destroy).pack(side=RIGHT)
        center_window(self)
        self.grab_set()

    def _start(self):
        self.btn.configure(state="disabled")
        threading.Thread(target=self._worker, daemon=True).start()

    def _worker(self):
        import tempfile
        tmp = os.path.join(tempfile.gettempdir(), "imm_update.zip")

        def prog(done, total):
            pct = int(done * 100 / total) if total else 0
            self.after(0, lambda: (self.pb.configure(value=pct),
                                   self.status.configure(text=f"下载中… {pct}%")))
        try:
            updater.download(self.info["asset_url"], tmp, prog)
        except Exception as e:
            self.after(0, lambda: (self.status.configure(text=f"下载失败：{e}"),
                                   self.btn.configure(state="normal")))
            return
        self.after(0, lambda: self._apply(tmp))

    def _apply(self, tmp):
        self.status.configure(text="正在替换并重启…")
        try:
            updater.apply_update(tmp, config.ROOT, os.path.basename(sys.executable))
        except Exception as e:
            self.status.configure(text=f"更新失败：{e}")
            self.btn.configure(state="normal")
            return
        self.app.scrcpy.stop_all()
        self.app.root.after(400, lambda: os._exit(0))   # 退出，让脚本替换文件后重启


class SoloWindow(tb.Toplevel):
    """独立投屏窗口：顶部手势导航按钮 + scrcpy 画面浮在上方。

    不使用 set_owner（会导致某些设备上 SDL 渲染变黑），
    改为让 scrcpy 窗口作为独立顶层窗口浮在 video 区域上方，
    通过 <Configure>/<FocusIn>/<Map>/<Unmap> 事件同步位置和可见性。
    """
    def __init__(self, app, device):
        super().__init__(app.root)
        self.app = app
        self.device = device
        self.hwnd = None
        self._minimized = False
        name = app.book.name(device.serial, device.model or device.serial)
        self.title(f"独立 · {name}")
        w = app.settings.solo_window_size
        ratio = app._ratios.get(device.serial) or 0.462   # 按手机真实比例，减少黑边
        self.geometry(f"{w + 24}x{int(w / ratio) + 56}")
        center_window(self)
        self.protocol("WM_DELETE_WINDOW", self._close)

        bar = tb.Frame(self)
        bar.pack(fill=X, pady=2)
        for text, code in [("← 返回", KEY_BACK), ("● 桌面", KEY_HOME), ("▣ 多任务", KEY_RECENT)]:
            tb.Button(bar, text=text, bootstyle="info-outline",
                      command=lambda c=code: self._on_nav(c)).pack(side=LEFT, padx=3, pady=2)

        self.video = tk.Frame(self, bg="black")
        self.video.pack(fill=BOTH, expand=True)
        self.bind("<Configure>", self._on_configure)
        self.bind("<FocusIn>", self._on_focus)
        self.bind("<Map>", self._on_map)
        self.bind("<Unmap>", self._on_unmap)

        # 直接在视频区所在屏幕位置启动 scrcpy
        self.update_idletasks()
        vx, vy = self.video.winfo_rootx(), self.video.winfo_rooty()
        vw, vh = self.video.winfo_width(), self.video.winfo_height()
        title = app.scrcpy.start_solo_embed_process(device, vx, vy, max(100, vw), max(100, vh))

        def find():
            h = embed.find_hwnd_by_title(title)
            if not h:
                return
            time.sleep(0.3)          # 等 SDL 初始化
            self.after(0, lambda: self._attach(h))
        threading.Thread(target=find, daemon=True).start()

    def _attach(self, h):
        if not h or not self.winfo_exists():
            return
        self.hwnd = h
        # 不调 set_owner —— 直接把 scrcpy 窗口 raise 到 video 区域上方
        self._raise_to_video()

    def _raise_to_video(self):
        """把 scrcpy 窗口提到最前，精确覆盖 video 区域。"""
        if not (self.hwnd and self.winfo_exists() and self.video.winfo_ismapped()):
            return
        v = self.video
        embed.raise_over(self.hwnd, v.winfo_rootx(), v.winfo_rooty(),
                         v.winfo_width(), v.winfo_height())

    def _on_configure(self, _=None):
        """窗口移动/调整大小时，同步 scrcpy 位置。"""
        if self.hwnd and not self._minimized:
            # 防抖：用 after_idle 合并高频事件
            self.after_idle(self._raise_to_video)

    def _on_focus(self, _=None):
        """点击导航按钮等操作后，独立窗口获得焦点，需要把 scrcpy 重新提到上方。"""
        if self.hwnd and not self._minimized:
            self.after(30, self._raise_to_video)

    def _on_nav(self, keycode):
        """导航按钮回调：先发按键，再把 scrcpy 提回最前。"""
        self.app._send_key_one(self.device, keycode)
        if self.hwnd:
            self.after(80, self._raise_to_video)

    def _on_unmap(self, _=None):
        """独立窗口最小化时，一起隐藏 scrcpy。"""
        self._minimized = True
        if self.hwnd:
            embed.user32.ShowWindow(self.hwnd, 0)      # SW_HIDE

    def _on_map(self, _=None):
        """独立窗口恢复时，重新显示并定位 scrcpy。"""
        self._minimized = False
        if self.hwnd:
            embed.user32.ShowWindow(self.hwnd, embed.SW_SHOWNOACTIVATE)
            self.after(50, self._raise_to_video)

    def _close(self):
        self.hwnd = None                               # 先置空，阻止事件回调
        self.app.scrcpy.stop(self.device.serial, "solo")
        self.app.solo_windows.pop(self.device.serial, None)
        self.destroy()


class App:
    def __init__(self):
        self.settings = config.Settings.load()
        self.book = config.DeviceBook()
        self.adb = Adb(config.ADB_EXE)
        self.scrcpy = ScrcpyManager(config.SCRCPY_EXE, self.settings)
        # 本地控制 API（手机端 autox.js 经 adb reverse 调用，自动录制/停止/改名归档）
        self.api = ApiServer(self.adb, self._api_dispatch,
                             phone_port=self.settings.api_phone_port,
                             base_pc_port=self.settings.api_pc_port)
        self.api.enabled = self.settings.api_enabled

        self.root = TkinterDnD.Tk() if _HAS_DND else tk.Tk()
        self.style = tb.Style(THEME)
        self.colors = self.style.colors
        try:      # 配合 PMv2 DPI 感知，按屏幕 DPI 缩放，字体清晰且大小正常
            self.root.tk.call("tk", "scaling", self.root.winfo_fpixels("1i") / 72.0)
        except Exception:
            pass
        # 亮色界面下各处颜色（tk 原生控件需手动上色）
        self.C_GRID = "#e9ecef"       # 右侧网格背景
        self.C_TILE_BORDER = "#c4cad2"
        self.C_HEADER = "#f4f6f8"      # 格子标题栏
        self.C_TAG_OFF_BG = "#e2e6ea"  # 未激活标签
        self.C_TAG_OFF_FG = "#495057"
        self.root.title(f"{config.APP_NAME} v{config.APP_VERSION}")
        # 设置窗口图标（分别精准加载 48x48 大图标与 16x16 小图标，彻底消除任务栏模糊拉伸）
        try:
            if os.path.exists(config.ICON_ICO):
                self.root.iconbitmap(config.ICON_ICO)
                import ctypes
                u32 = ctypes.windll.user32
                hwnd = embed.root_hwnd(int(self.root.winfo_id()))
                # 48x48 用于任务栏/Alt+Tab 大图标
                hicon_big = u32.LoadImageW(0, config.ICON_ICO, 1, 48, 48, 0x0010)
                if hicon_big:
                    u32.SendMessageW(hwnd, 0x0080, 1, hicon_big)
                # 16x16 用于标题栏小图标
                hicon_small = u32.LoadImageW(0, config.ICON_ICO, 1, 16, 16, 0x0010)
                if hicon_small:
                    u32.SendMessageW(hwnd, 0x0080, 0, hicon_small)
            if os.path.exists(config.ICON_PNG):
                _icon = tk.PhotoImage(file=config.ICON_PNG)
                self.root.iconphoto(True, _icon)
                self._icon_img = _icon      # 防止被 GC 回收
        except Exception:
            pass
        if self.settings.window_geometry:            # 恢复上次窗口大小/位置
            try:
                self.root.geometry(self.settings.window_geometry)
            except Exception:
                self.root.geometry("1160x740")
                center_window(self.root)
            if self.settings.window_maximized:
                self.root.state("zoomed")
        else:
            self.root.geometry("1160x740")
            center_window(self.root)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        self.devices = []
        self.check_vars = {}
        self.tiles = {}
        self.recording = set()          # 正在录制的设备序列号
        self._rec_files = {}            # serial -> 当前/最近一次录制文件路径（供 API 改名归档）
        self._rec_ids = {}              # serial -> 本次录制 id（供 API 定位）
        self.solo_windows = {}          # serial -> SoloWindow
        self._rec_labels = []           # REC 指示灯(做呼吸动画)
        self._ratios = {}               # serial -> 屏幕宽/高比例(格子按此贴合)
        self._numbers = {}              # serial -> 显示编号(连续不重复)
        self._models = {}               # serial -> 型号(缓存，避免每次轮询都查)
        self._list_sig = None           # 列表内容签名，用于避免无变化时重建(防闪)
        self._encoder_cache = []        # 编码器检测缓存
        self._known_serials = set()
        self._last_cols = 0
        os.makedirs(config.RECORDS_DIR, exist_ok=True)

        self._build_ui()
        self.root.bind("<Configure>", self._on_configure)
        if _HAS_DND:
            self.root.drop_target_register(DND_FILES)
            self.root.dnd_bind("<<Drop>>", self._on_drop)

        self.adb.start_server()
        self._poll()
        self._pulse_rec()                                  # REC 呼吸动画
        self.root.after(2500, self._check_update_async)   # 启动后静默检查更新

    # ---------------- 布局 ----------------
    def _build_ui(self):
        paned = tb.Panedwindow(self.root, orient="horizontal")
        paned.pack(fill=BOTH, expand=True, padx=8, pady=8)
        left = tb.Frame(paned, width=300)
        left.pack_propagate(False)
        paned.add(left, weight=0)
        right = tb.Frame(paned)
        paned.add(right, weight=1)
        self._build_left(left)
        self._build_right(right)

    def _section(self, parent, title):
        lf = tb.Labelframe(parent, text=title, bootstyle="secondary")
        lf.pack(fill=X, pady=(0, 6))
        lf.columnconfigure(0, weight=1)
        lf.columnconfigure(1, weight=1)
        lf.columnconfigure(2, weight=1)
        return lf

    def _build_left(self, left):
        top = tb.Frame(left)
        top.pack(fill=X, pady=(0, 8))
        tb.Label(top, text=config.APP_NAME, font=(FONT, 15, "bold"),
                 bootstyle="primary").pack(side=LEFT)
        tb.Label(top, text=f"v{config.APP_VERSION}", bootstyle="secondary").pack(side=LEFT, padx=4)
        tb.Button(top, text="检查更新", bootstyle="link",
                  command=lambda: self._check_update_async(manual=True)).pack(side=RIGHT)

        s1 = self._section(left, "投屏")
        for i, (text, bs, cmd) in enumerate([
                ("群控投屏", "success", self.group_mirror),
                ("全部投屏", "primary", self.mirror_all),
                ("停止全部", "danger", self.stop_all)]):
            tb.Button(s1, text=text, bootstyle=bs, command=cmd
                      ).grid(row=0, column=i, padx=3, pady=4, sticky="ew")
        tb.Button(s1, text="投屏设置", bootstyle="secondary-outline", command=self.open_settings
                  ).grid(row=1, column=0, columnspan=2, padx=3, pady=(0, 4), sticky="ew")
        tb.Button(s1, text="刷新", bootstyle="secondary-outline", command=self._poll
                  ).grid(row=1, column=2, padx=3, pady=(0, 4), sticky="ew")

        # 手机导航：发按键给“选中的设备”（没选就发给全部在线）
        s2 = self._section(left, "手机导航（发给选中设备）")
        for i, (text, code, name) in enumerate([
                ("← 返回", KEY_BACK, "返回"),
                ("● 桌面", KEY_HOME, "桌面"),
                ("▣ 多任务", KEY_RECENT, "多任务")]):
            tb.Button(s2, text=text, bootstyle="info-outline",
                      command=lambda c=code, n=name: self._send_key(c, n)
                      ).grid(row=0, column=i, padx=3, pady=4, sticky="ew")

        s4 = self._section(left, "文件 / 命令")
        for i, f in enumerate(all_features()):
            tb.Button(s4, text=f.label, bootstyle="secondary",
                      command=lambda ff=f: ff.handler(self)
                      ).grid(row=0, column=i, padx=3, pady=4, sticky="ew")

        head = tb.Frame(left)
        head.pack(fill=X, pady=(4, 2))
        self.select_all_var = tk.BooleanVar()
        tb.Checkbutton(head, text="全选", variable=self.select_all_var,
                       bootstyle="round-toggle", command=self._toggle_all).pack(side=LEFT)
        tb.Label(head, text="设备列表", bootstyle="secondary").pack(side=LEFT, padx=8)

        card = tb.Frame(left, bootstyle="light")
        card.pack(fill=BOTH, expand=True, pady=2)
        canvas = tk.Canvas(card, highlightthickness=0, bg=self.colors.bg, width=280)
        sb = tb.Scrollbar(card, orient="vertical", command=canvas.yview, bootstyle="round")
        self.list_frame = tb.Frame(canvas)
        self.list_frame.bind("<Configure>",
                             lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        _win = canvas.create_window((0, 0), window=self.list_frame, anchor="nw")
        # 让内部行随画布宽度铺满，REC 才能真正靠到最右
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(_win, width=e.width))
        canvas.configure(yscrollcommand=sb.set)
        canvas.pack(side=LEFT, fill=BOTH, expand=True)
        sb.pack(side=RIGHT, fill=Y)

        tb.Label(left, text="日志", bootstyle="secondary").pack(anchor=W, pady=(6, 0))
        self.log_text = tk.Text(left, height=6, state="disabled", wrap="word",
                                bg=self.colors.inputbg, fg=self.colors.fg,
                                relief="flat", borderwidth=0, font=(FONT, 9))
        self.log_text.pack(fill=X, pady=(0, 4))
        self.status = tb.Label(left, text="", bootstyle="inverse-primary", anchor=W)
        self.status.pack(fill=X, side="bottom")

    def _build_right(self, right):
        bar = tb.Frame(right)
        bar.pack(fill=X, pady=(0, 6))
        tb.Label(bar, text="投屏画面", font=(FONT, 12, "bold")).pack(side=LEFT)
        tb.Button(bar, text="＋", bootstyle="secondary", width=3,
                  command=lambda: self._nudge_tile_size(40)).pack(side=RIGHT, padx=2)
        tb.Button(bar, text="－", bootstyle="secondary", width=3,
                  command=lambda: self._nudge_tile_size(-40)).pack(side=RIGHT, padx=2)
        tb.Label(bar, text="格子大小", bootstyle="secondary").pack(side=RIGHT, padx=(0, 4))

        self.grid_frame = tk.Frame(right, bg=self.C_GRID)
        self.grid_frame.pack(fill=BOTH, expand=True)
        self.grid_frame.bind("<Configure>", self._on_grid_resize)

    # ---------------- 设备轮询 ----------------
    def _poll(self):
        def worker():
            devs = self.adb.list_devices()
            for d in devs:
                if d.is_online:
                    if d.serial in self._models:          # 用缓存，避免每次轮询都查
                        d.model = self._models[d.serial]
                    elif not d.model:
                        d.model = self.adb.get_model(d.serial)
                        if d.model:
                            self._models[d.serial] = d.model
            self.root.after(0, lambda: self._sync(devs))
        threading.Thread(target=worker, daemon=True).start()
        self.root.after(4000, self._poll)

    def _sync(self, devs):
        # 分配显示编号：自定义编号的用自定义，其余按序填补空缺，保证连续不重复
        devs.sort(key=lambda d: (self.book.number(d.serial, 9999), d.serial))
        claimed = {self.book.number(d.serial, 0) for d in devs if self.book.number(d.serial, 0)}
        self._numbers = {}
        nxt = 1
        for d in devs:
            n = self.book.number(d.serial, 0)
            if n:
                self._numbers[d.serial] = n
            else:
                while nxt in claimed:
                    nxt += 1
                self._numbers[d.serial] = nxt
                claimed.add(nxt)
                nxt += 1
        devs.sort(key=lambda d: self._numbers[d.serial])
        self.devices = devs
        online = {d.serial for d in devs if d.is_online}
        new = online - self._known_serials
        if self.settings.auto_mirror:
            # 逐台错开启动，避免多台 scrcpy 同时启动互相抢占而崩溃
            for i, d in enumerate([x for x in devs if x.serial in new]):
                self.root.after(i * 1800, lambda dev=d: self._embed_device(dev))
        self._known_serials = online
        # 同步本地控制 API 的 adb reverse/监听（会调 adb，放后台线程避免卡 UI）
        threading.Thread(target=lambda: self.api.sync(online), daemon=True).start()
        for serial in list(self.recording):
            if serial not in online:      # 设备拔出，scrcpy 会自行收尾录制
                self.recording.discard(serial)
        for serial in list(self.tiles.keys()):
            if serial not in online:
                self._remove_tile(serial)
        # 仅在列表内容真正变化时才重建，避免每次轮询闪烁
        sig = tuple((d.serial, d.state, self._numbers.get(d.serial),
                     d.serial in self.recording, tuple(self._device_tags(d)))
                    for d in devs)
        if sig != self._list_sig:
            self._list_sig = sig
            self._render_list(devs)
        else:
            self._update_status()
        self._reflow()

    # ---------------- 标签 ----------------
    def _device_tags(self, d):
        return self.book.tags(d.serial) or [d.model or d.serial]

    def _render_tag_chips(self, parent, tags, on_click=None, font_size=9):
        """第一个标签=激活态(高亮蓝)，其余为静默灰。"""
        for i, t in enumerate(tags):
            active = (i == 0)
            bg = self.colors.primary if active else self.C_TAG_OFF_BG
            fg = "#ffffff" if active else self.C_TAG_OFF_FG
            font = (FONT, font_size, "bold" if active else "normal")
            lbl = tk.Label(parent, text=t, bg=bg, fg=fg, font=font,
                           padx=6, pady=1, cursor="hand2" if on_click else "arrow")
            lbl.pack(side=LEFT, padx=1)
            if on_click:
                lbl.bind("<Button-1>", lambda e, tag=t: on_click(tag))

    def _activate_tag(self, device, tag):
        tags = self._device_tags(device)
        if tag in tags:
            tags.remove(tag)
            tags.insert(0, tag)
            self.book.set(device.serial, tags=tags)
            self._render_list(self.devices)
            self._update_tile_header(device.serial)

    # ---------------- 设备列表 ----------------
    def _render_list(self, devs):
        for w in self.list_frame.winfo_children():
            w.destroy()
        new_vars = {}
        for idx, d in enumerate(devs):
            num = self._display_number(d)
            row = tb.Frame(self.list_frame)
            row.pack(fill=X, pady=2, padx=2)
            var = self.check_vars.get(d.serial, tk.BooleanVar())
            new_vars[d.serial] = var
            tb.Checkbutton(row, variable=var, bootstyle="round-toggle",
                           command=self._update_status).pack(side=LEFT, padx=(2, 4))
            tb.Label(row, text=f"{num:02d}", width=2, bootstyle="info").pack(side=LEFT)
            self._render_tag_chips(
                row, self._device_tags(d),
                on_click=lambda tag, dev=d: self._activate_tag(dev, tag))
            if not d.is_online:
                tb.Label(row, text="离线", bootstyle="danger").pack(side=LEFT, padx=2)
            if d.serial in self.recording:
                rec = tk.Label(row, text="● REC", fg="#ff2d2d", bg=self.colors.bg,
                               font=(FONT, 8, "bold"))
                rec.pack(side=RIGHT, padx=6)
                self._rec_labels.append(rec)
            dbl = lambda e, dev=d: self._edit_device(dev)
            row.bind("<Double-Button-1>", dbl)
            # 右键菜单（整行含子控件都能触发）
            bind_recursive(row, "<Button-3>", lambda e, dev=d: self._device_menu(e, dev))
        self.check_vars = new_vars
        self._update_status()

    def _update_status(self):
        self.status.config(text=f" 总数 {len(self.devices)}   在线 {len(self._known_serials)}   "
                                f"投屏 {len(self.tiles)}   已选 {len(self.selected_devices())}")

    def _edit_device(self, device):
        cur_tags = self.book.tags(device.serial)
        cur_num = self.book.number(device.serial, 0)

        def _ok(tags, num):
            self.book.set(device.serial, tags=tags, number=num)
            self.log(f"已修改: 编号{num} {' '.join(tags)}")
            self._sync(self.devices)
            if device.serial in self.tiles:
                self._update_tile_header(device.serial)
        EditDeviceDialog(self.root, cur_tags, cur_num, _ok,
                         on_record=lambda: self._open_device_record(device))

    def _open_device_record(self, device):
        from .settings_dialog import DeviceRecordDialog
        name = self.book.name(device.serial, device.model or device.serial)

        def _save(cfg):
            self.book.set_record_override(device.serial, cfg)
            self.log(f"{name} 录制设置：{'独立' if cfg else '跟随通用'}")
        DeviceRecordDialog(self.root, name, self.settings.record_config(),
                           self.book.record_override(device.serial),
                           self._encoder_options(False), _save)

    # ---------------- 设备右键菜单 ----------------
    def _device_menu(self, event, device):
        m = tk.Menu(self.root, tearoff=0)
        m.add_command(label="独立投屏", command=lambda: self.solo_mirror(device))
        m.add_command(label="修改标签 / 编号", command=lambda: self._edit_device(device))
        m.add_command(label="该设备录制设置", command=lambda: self._open_device_record(device))
        m.add_separator()
        m.add_command(label="设备信息", command=lambda: self._show_device_info(device))
        m.add_command(label="重启手机", command=lambda: self._reboot_device(device))
        try:
            m.tk_popup(event.x_root, event.y_root)
        finally:
            m.grab_release()

    def _reboot_device(self, device):
        name = self.book.name(device.serial, device.model or device.serial)
        if not messagebox.askyesno("重启手机", f"确定要重启【{name}】吗？"):
            return
        threading.Thread(target=lambda: (self.adb.reboot(device.serial),
                                         self.log(f"已发送重启: {name}")), daemon=True).start()

    def _show_device_info(self, device):
        name = self.book.name(device.serial, device.model or device.serial)

        def worker():
            p = self.adb.getprops(device.serial, [
                "ro.product.brand", "ro.product.model", "ro.build.version.release",
                "ro.build.version.sdk", "ro.product.cpu.abi"])
            ok_sz, size = self.adb.shell(device.serial, "wm size")
            ok_bt, bat = self.adb.shell(device.serial, "dumpsys battery | grep level")
            info = {
                "名称": name,
                "序列号": device.serial,
                "连接方式": device.conn_type,
                "品牌": p.get("ro.product.brand", ""),
                "型号": p.get("ro.product.model", ""),
                "Android": f'{p.get("ro.build.version.release","")}  (SDK {p.get("ro.build.version.sdk","")})',
                "CPU架构": p.get("ro.product.cpu.abi", ""),
                "分辨率": size.replace("Physical size:", "").strip() if ok_sz else "-",
                "电量": (bat.split(":")[-1].strip() + "%") if (ok_bt and ":" in bat) else "-",
            }
            self.root.after(0, lambda: self._show_info_dialog(name, info))
        threading.Thread(target=worker, daemon=True).start()

    def _show_info_dialog(self, name, info):
        dlg = tb.Toplevel(self.root)
        dlg.title(f"设备信息 · {name}")
        dlg.resizable(False, False)
        dlg.transient(self.root)
        f = tb.Frame(dlg)
        f.pack(fill=BOTH, expand=True, padx=18, pady=14)
        for i, (k, v) in enumerate(info.items()):
            tb.Label(f, text=k, bootstyle="secondary", width=8, anchor=W).grid(
                row=i, column=0, sticky=W, padx=6, pady=4)
            tb.Label(f, text=v or "-").grid(row=i, column=1, sticky=W, padx=6, pady=4)
        tb.Button(dlg, text="关闭", bootstyle="secondary-outline",
                  command=dlg.destroy).pack(pady=(0, 14))
        center_window(dlg)
        dlg.grab_set()

    # ---------------- 在线更新 ----------------
    def _check_update_async(self, manual=False):
        def worker():
            info = updater.check_update(config.GITHUB_OWNER, config.GITHUB_REPO, config.APP_VERSION)

            def show():
                if info:
                    frozen = getattr(sys, "frozen", False)
                    if frozen and info.get("asset_url"):
                        UpdateDialog(self, info)         # 打包版：自动下载+重启
                    elif messagebox.askyesno("发现新版本",
                                             f"有新版本 v{info['version']}（当前 v{config.APP_VERSION}）。\n是否打开下载页面？"):
                        webbrowser.open(info["html_url"])
                elif manual:
                    messagebox.showinfo("检查更新", f"当前已是最新版本 v{config.APP_VERSION}")
            self.root.after(0, show)
        threading.Thread(target=worker, daemon=True).start()

    def _toggle_all(self):
        val = self.select_all_var.get()
        for var in self.check_vars.values():
            var.set(val)
        self._render_list(self.devices)

    def selected_devices(self):
        return [d for d in self.devices
                if self.check_vars.get(d.serial) and self.check_vars[d.serial].get()]

    # ---------------- 嵌入式网格 ----------------
    def _tile_size(self):
        w = self.settings.group_window_size
        return w, int(w * 1.9)

    def _device_ratio(self, serial):
        r = self._ratios.get(serial)
        return r if r else 0.462        # 默认竖屏比例

    def _tile_dims(self, serial):
        """按手机真实屏幕比例算格子画面尺寸，scrcpy 才能刚好填满不错位。"""
        w = self.settings.group_window_size
        return w, int(w / self._device_ratio(serial))

    def _resize_tile(self, serial):
        tile = self.tiles.get(serial)
        if not tile:
            return
        w, h = self._tile_dims(serial)
        tile["video"].configure(width=w, height=h)
        self._last_cols = 0
        self.root.update_idletasks()
        self._reflow()
        self._position_overlay(serial)

    def _nudge_tile_size(self, delta):
        new = max(160, min(600, self.settings.group_window_size + delta))
        if new == self.settings.group_window_size:
            return
        self.settings.group_window_size = new
        self.settings.save()
        self._apply_tile_size()

    def _apply_tile_size(self):
        for serial, tile in self.tiles.items():
            tw, th = self._tile_dims(serial)
            tile["video"].configure(width=tw, height=th)
        self._last_cols = 0
        self.root.update_idletasks()
        self._reflow()
        for serial in self.tiles:
            self._position_overlay(serial)
            self._update_tile_header(serial)

    def _embed_device(self, device):
        if not device.is_online or device.serial in self.tiles:
            return
        tw, th = self._tile_dims(device.serial)
        frame = tk.Frame(self.grid_frame, bg=self.C_TILE_BORDER,
                         highlightthickness=1, highlightbackground=self.C_TILE_BORDER)
        header = tk.Frame(frame, bg=self.C_HEADER)
        header.pack(fill=X)
        video = tk.Frame(frame, width=tw, height=th, bg="black")
        video.pack()
        video.pack_propagate(False)
        video.bind("<Configure>", lambda e, s=device.serial: self._position_overlay(s))
        footer = tk.Frame(frame, bg=self.C_HEADER)
        footer.pack(fill=X)
        tk.Button(footer, text="↗ 独立", font=(FONT, 8), bd=0,
                  bg=self.C_HEADER, fg=self.colors.primary,
                  activebackground=self.colors.primary, activeforeground="#fff",
                  cursor="hand2",
                  command=lambda dev=device: self.solo_mirror(dev)).pack(side=RIGHT, padx=2)
        tk.Button(footer, text="⟳ 重连", font=(FONT, 8), bd=0,
                  bg=self.C_HEADER, fg=self.colors.primary,
                  activebackground=self.colors.primary, activeforeground="#fff",
                  cursor="hand2",
                  command=lambda dev=device: self._reconnect_device(dev)).pack(side=RIGHT, padx=2)
        recbtn = tk.Button(footer, text="● 录制", font=(FONT, 8), bd=0,
                           bg=self.C_HEADER, fg="#888", activebackground="#e03131",
                           activeforeground="#fff", cursor="hand2",
                           command=lambda dev=device: self._toggle_record(dev))
        recbtn.pack(side=LEFT, padx=2)

        self.tiles[device.serial] = {"frame": frame, "video": video, "device": device,
                                     "header": header, "recbtn": recbtn, "hwnd": None}
        self._update_tile_header(device.serial)
        self.root.update_idletasks()
        self._reflow()

        title = self.scrcpy.start_embed_process(device)
        self.log(f"投屏: {self.book.name(device.serial, device.display_name)}")

        def find_and_attach():
            if device.serial not in self._ratios:      # 先拿手机真实比例，贴合格子
                res = self.adb.get_resolution(device.serial)
                if res and res[1]:
                    self._ratios[device.serial] = res[0] / res[1]
                    self.root.after(0, lambda: self._resize_tile(device.serial))
            hwnd = embed.find_hwnd_by_title(title)
            time.sleep(1.5)   # 等 scrcpy 窗口/渲染器初始化完成，过早接管会导致它崩溃
            self.root.after(0, lambda: self._attach(device.serial, hwnd))
        threading.Thread(target=find_and_attach, daemon=True).start()

    def _attach(self, serial, hwnd):
        tile = self.tiles.get(serial)
        if not tile:
            return
        if not hwnd:
            self.log(f"[提示] 未捕获到投屏窗口: {serial}")
            return
        embed.set_owner(hwnd, self._owner_hwnd())
        tile["hwnd"] = hwnd
        self._position_overlay(serial)
        # 多次触发 SDL 重绘，尽量避免偶发黑屏(慢的设备需要更多次)
        for i, t in enumerate((300, 600, 1200, 2000, 3200)):
            self.root.after(t, lambda s=serial, dh=(2 if i % 2 == 0 else 0):
                            self._nudge_overlay(s, dh))

    def _nudge_overlay(self, serial, dh):
        tile = self.tiles.get(serial)
        if not tile or not tile["hwnd"] or not tile["video"].winfo_ismapped():
            return
        v = tile["video"]
        embed.place(tile["hwnd"], v.winfo_rootx(), v.winfo_rooty(),
                    v.winfo_width(), v.winfo_height() + dh)

    def _owner_hwnd(self):
        return embed.root_hwnd(int(self.root.winfo_id()))

    def _position_overlay(self, serial):
        """把 scrcpy 悬浮窗口精确定位到格子的画面区域(屏幕绝对坐标)。"""
        tile = self.tiles.get(serial)
        if not tile or not tile["hwnd"]:
            return
        v = tile["video"]
        if not v.winfo_ismapped():
            return
        embed.place(tile["hwnd"], v.winfo_rootx(), v.winfo_rooty(),
                    v.winfo_width(), v.winfo_height())

    def _on_configure(self, _event=None):
        # 防抖：拖动时 <Configure> 每秒触发几十次，合并到约 60fps，避免卡顿
        if getattr(self, "_repos_pending", False):
            return
        self._repos_pending = True
        self.root.after(16, self._flush_overlays)

    def _flush_overlays(self):
        self._repos_pending = False
        self._position_all_overlays()

    def _position_all_overlays(self, _event=None):
        # 一次性批量移动所有画面窗口，拖动更跟手、不闪
        items = []
        for tile in self.tiles.values():
            v = tile.get("video")
            if tile.get("hwnd") and v and v.winfo_ismapped():
                items.append((tile["hwnd"], v.winfo_rootx(), v.winfo_rooty(),
                              v.winfo_width(), v.winfo_height()))
        embed.batch_place(items)

    def _update_tile_header(self, serial):
        tile = self.tiles.get(serial)
        if not tile:
            return
        dev = tile["device"]
        header = tile["header"]
        for w in header.winfo_children():
            w.destroy()
        num = self._display_number(dev)
        tk.Label(header, text=f"{num:02d}", bg=self.C_HEADER, fg=self.colors.primary,
                 font=(FONT, 8, "bold")).pack(side=LEFT, padx=(4, 2))
        tags = self._device_tags(dev)
        fs = 9 if len(tags) <= 2 else 8 if len(tags) <= 4 else 7 if len(tags) <= 6 else 6
        self._render_tag_chips(header, tags, font_size=fs,
                               on_click=lambda tag, d=dev: self._activate_tag(d, tag))
        if serial in self.recording:
            rec = tk.Label(header, text="● REC", bg=self.C_HEADER, fg="#ff2d2d",
                           font=(FONT, 8, "bold"))
            rec.pack(side=RIGHT, padx=4)
            self._rec_labels.append(rec)
        header.bind("<Double-Button-1>", lambda e, d=dev: self._edit_device(d))

    def _reconnect_device(self, device):
        """重连单台群控画面：停掉旧 scrcpy + 移除黑屏格子，稍等再重开。
        用于设备重启后画面黑屏（重启时 scrcpy 在设备没就绪时接管导致的黑屏）。"""
        serial = device.serial
        self._remove_tile(serial)
        self.log(f"重连: {self.book.name(serial, device.display_name)}")

        def redo():
            cur = next((d for d in self.devices if d.serial == serial and d.is_online), None)
            if cur:
                self._embed_device(cur)
            else:
                self.log(f"重连失败: {serial} 当前不在线")
        # 稍等让旧进程/窗口彻底退出，并给刚重启的设备一点就绪时间
        self.root.after(1200, redo)

    def _remove_tile(self, serial):
        tile = self.tiles.pop(serial, None)
        if tile:
            tile["frame"].destroy()
        self.scrcpy.stop(serial, "group")
        self._reflow()

    def _reflow(self):
        tw, th = self._tile_size()
        avail = max(1, self.grid_frame.winfo_width())
        cols = max(1, avail // (tw + 6))
        ordered = sorted(self.tiles.items(),
                         key=lambda kv: self._numbers.get(kv[0], 9999))
        for i, (serial, tile) in enumerate(ordered):
            r, c = divmod(i, cols)
            tile["frame"].grid(row=r, column=c, padx=2, pady=2, sticky="n")
        self.root.after_idle(self._position_all_overlays)

    def _on_grid_resize(self, event):
        tw, _ = self._tile_size()
        cols = max(1, event.width // (tw + 6))
        if cols != self._last_cols:
            self._last_cols = cols
            self._reflow()

    # ---------------- 投屏动作 ----------------
    def solo_mirror(self, device):
        if not device.is_online:
            messagebox.showwarning("投屏", f"{device.display_name} 不在线")
            return
        num = self._display_number(device)
        name = f"{num:02d}"                            # 独立窗口标题只显示编号
        if self.scrcpy.is_running(device.serial, "solo"):
            self.log(f"独立投屏已在运行: {name}")
            return
        self.log(f"独立投屏: {name}")

        def worker():
            # 按手机当前横竖屏定窗口大小：短边=solo_window_size，长边按画面比例自适应
            w0 = self.settings.solo_window_size
            win_w, win_h = w0, int(w0 * 1.9)           # 拿不到朝向就按竖屏默认
            sz = self.adb.get_current_size(device.serial)
            if sz and sz[0] and sz[1]:
                cw, ch = sz
                lo, sh = max(cw, ch), min(cw, ch)
                if cw > ch:                            # 横屏：短边是高
                    win_w, win_h = round(w0 * lo / sh), w0
                else:                                  # 竖屏：短边是宽
                    win_w, win_h = w0, round(w0 * lo / sh)
            self.scrcpy.launch_solo(device, name=name, win_w=win_w, win_h=win_h)
        threading.Thread(target=worker, daemon=True).start()

    def _send_key_one(self, device, code):
        threading.Thread(target=lambda: self.adb.shell(device.serial, f"input keyevent {code}"),
                         daemon=True).start()

    def group_mirror(self):
        devs = self.selected_devices() or [d for d in self.devices if d.is_online]
        for d in devs:
            self._embed_device(d)

    def mirror_all(self):
        for d in self.devices:
            if d.is_online:
                self._embed_device(d)

    def stop_all(self):
        for serial in list(self.tiles.keys()):
            self._remove_tile(serial)
        self.scrcpy.stop_all()
        self.log("已停止全部投屏")
        self._render_list(self.devices)

    # ---------------- 手机导航（发按键给设备） ----------------
    def _send_key(self, code, name):
        devs = self.selected_devices() or [d for d in self.devices if d.is_online]
        if not devs:
            self.log(f"{name}: 没有在线设备")
            return

        def worker():
            for d in devs:
                self.adb.shell(d.serial, f"input keyevent {code}")
            self.log(f"{name} → {len(devs)} 台")
        threading.Thread(target=worker, daemon=True).start()

    # ---------------- 录屏 ----------------
    def _safe_name(self, s):
        return re.sub(r'[\\/:*?"<>|\s]+', "_", s).strip("_") or "device"

    def start_record_selected(self):
        devs = self.selected_devices() or [d for d in self.devices if d.is_online]
        devs = [d for d in devs if d.is_online and d.serial not in self.recording]
        if not devs:
            self.log("录制: 没有可录制的设备（或已在录制中）")
            return
        for i, d in enumerate(devs):     # 错开启动，避免多台同时抢占
            self.root.after(i * 800, lambda dev=d: self._do_start_record(dev))

    def _display_number(self, device):
        """有效编号（连续不重复），由 _sync 统一分配。"""
        return self._numbers.get(device.serial, 1)

    def _record_config(self, device):
        """该设备的有效录制参数：有独立设置用自己的，否则用通用设置。"""
        return self.book.record_override(device.serial) or self.settings.record_config()

    def _device_records_dir(self, device_or_serial):
        """获取该设备的录像保存目录（开启按机器编码分文件夹时，放 records/01-标签/ 下）。"""
        root = self.settings.effective_records_dir()
        if not self.settings.subfolder_by_device:
            return root
        if isinstance(device_or_serial, str):
            serial = device_or_serial
            dev = self._device_by_serial(serial)
        else:
            dev = device_or_serial
            serial = dev.serial if dev else ""
        if not serial and not dev:
            return root

        num = self._display_number(dev) if dev else self.book.number(serial, 0)
        num_str = f"{num:02d}" if num else "00"
        tags = self.book.tags(serial) if serial else []
        if tags:
            tag_str = self._safe_name(tags[0])
            folder_name = f"{num_str}-{tag_str}" if tag_str else num_str
        else:
            folder_name = num_str
        sub_dir = os.path.join(root, self._safe_name(folder_name))
        os.makedirs(sub_dir, exist_ok=True)
        return sub_dir

    def _record_path(self, device, rec):
        s = self.settings
        num = self._display_number(device)
        tags = self._device_tags(device)      # 第一个是当前激活标签
        tokens = {
            "num": str(num or ""),
            "num2": f"{num:02d}" if num else "00",
            "time": datetime.datetime.now().strftime("%Y%m%d%H%M%S"),
            "tags": self._safe_name(" ".join(tags)),
            "firsttag": self._safe_name(tags[0]) if tags else "",
            "model": self._safe_name(device.model or ""),
            "serial": device.serial,
        }
        template = s.naming_template or "Recording-{num2}-{firsttag}-{time}"
        try:
            name = template.format(**tokens)
        except Exception:      # 模板写错就退回默认
            name = f"Recording-{tokens['num2']}-{tokens['firsttag']}-{tokens['time']}"
        name = self._safe_name(name) or "record"
        d = self._device_records_dir(device)
        return os.path.join(d, f"{name}.{rec.get('fmt', 'mp4')}")

    def _do_start_record(self, device):
        name = self._safe_name(self.book.name(device.serial, device.model or device.serial))
        rec = self._record_config(device)
        path = self._record_path(device, rec)
        if self.scrcpy.start_record(device, path, rec):
            self.recording.add(device.serial)
            self._rec_files[device.serial] = path
            self._rec_ids[device.serial] = datetime.datetime.now().strftime("%Y%m%d%H%M%S%f")[:-3]
            self.log(f"● 开始录制: {name}")
            self._refresh_rec_ui(device.serial)

    def stop_record_selected(self):
        sel = self.selected_devices()
        targets = [d for d in (sel or self.devices) if d.serial in self.recording]
        if not targets:      # 没选中在录的，就停全部在录的
            targets = [d for d in self.devices if d.serial in self.recording]
        if not targets:
            self.log("录制: 当前没有在录制的设备")
            return
        for d in targets:
            self._stop_one_record(d)

    def _stop_one_record(self, device):
        serial = device.serial
        name = self.book.name(serial, device.model or serial)

        def worker():
            self.scrcpy.stop_record(serial)      # 阻塞直到干净收尾
            self.recording.discard(serial)
            self.root.after(0, lambda: (self.log(f"■ 已保存: {name}"),
                                        self._refresh_rec_ui(serial)))
        threading.Thread(target=worker, daemon=True).start()

    def _toggle_record(self, device):
        if device.serial in self.recording:
            self._stop_one_record(device)
        else:
            self._do_start_record(device)

    # REC 呼吸动画：颜色在亮红-暗红之间循环
    _REC_COLORS = ["#ff2d2d", "#ff6b6b", "#ffb3b3", "#ff6b6b"]

    def _pulse_rec(self):
        self._rec_labels = [l for l in self._rec_labels if l.winfo_exists()]
        phase = getattr(self, "_rec_phase", 0)
        col = self._REC_COLORS[phase % len(self._REC_COLORS)]
        self._rec_phase = phase + 1
        for l in self._rec_labels:
            try:
                l.config(fg=col)
            except Exception:
                pass
        self.root.after(450, self._pulse_rec)

    def _refresh_rec_ui(self, serial):
        tile = self.tiles.get(serial)
        if tile and tile.get("recbtn"):
            rec = serial in self.recording
            tile["recbtn"].config(text="■ 停止" if rec else "● 录制",
                                  fg="#e03131" if rec else "#888")
        if serial in self.tiles:
            self._update_tile_header(serial)
        self._render_list(self.devices)

    def open_records_folder(self):
        d = self.settings.effective_records_dir()
        os.makedirs(d, exist_ok=True)
        try:
            os.startfile(d)
        except Exception as e:
            self.log(f"打开文件夹失败: {e}")

    # ---------------- 本地控制 API（手机端 autox.js 调用） ----------------
    # 说明：以下方法运行在 ApiServer 的后台线程里（非 Tk 主线程）。
    #   - 只做“非 UI”的活（起停 scrcpy 子进程、移动文件、读写 self.recording/_rec_* 字典）；
    #   - 需要动 UI 的一律用 self.root.after(0, ...) 调回主线程（与 _poll 的既有写法一致）。
    def _device_by_serial(self, serial):
        for d in self.devices:
            if d.serial == serial:
                return d
        return None

    def _api_record_path(self, device, rec, name=""):
        """API 录制的落盘路径。name 留空时用临时名（待 OCR 识别后再改名归档）。"""
        d = self._device_records_dir(device)
        ext = rec.get("fmt", "mp4")
        if name:
            base = self._safe_name(name)
        else:
            num = self._display_number(device)
            ts = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
            base = f"未命名-{num:02d}-{ts}"       # 临时名，/record/rename 时再改
        return os.path.join(d, f"{base}.{ext}")

    def _api_dispatch(self, serial, action, params):
        """ApiServer 的统一入口：serial 由“请求到达哪个端口”反查得到，可信。"""
        if action in ("", "ping"):
            return {"ok": True, "serial": serial,
                    "app": config.APP_NAME, "version": config.APP_VERSION,
                    "recording": serial in self.recording}
        if action == "status":
            return {"ok": True, "recording": serial in self.recording,
                    "id": self._rec_ids.get(serial, ""),
                    "file": self._rec_files.get(serial, "")}
        if action == "record/start":
            return self.api_start_record(serial, params.get("name", ""))
        if action == "record/stop":
            return self.api_stop_record(serial, params.get("name", ""))
        if action == "record/rename":
            return self.api_rename(serial, params.get("name", ""),
                                   params.get("folder", ""),
                                   params.get("src", "") or params.get("id", ""))
        return {"ok": False, "error": "未知接口: " + action}

    def api_start_record(self, serial, name=""):
        dev = self._device_by_serial(serial)
        if not dev or not dev.is_online:
            return {"ok": False, "error": "设备不在线"}
        if serial in self.recording:
            return {"ok": False, "error": "已在录制中",
                    "id": self._rec_ids.get(serial, ""),
                    "file": self._rec_files.get(serial, "")}
        rec = self._record_config(dev)
        path = self._api_record_path(dev, rec, name)
        if not self.scrcpy.start_record(dev, path, rec):
            return {"ok": False, "error": "启动录制失败"}
        rid = datetime.datetime.now().strftime("%Y%m%d%H%M%S%f")[:-3]
        self.recording.add(serial)
        self._rec_files[serial] = path
        self._rec_ids[serial] = rid
        self.root.after(0, lambda: (self.log(f"● [API] 开始录制 {os.path.basename(path)}"),
                                    self._refresh_rec_ui(serial)))
        return {"ok": True, "id": rid, "file": path}

    def api_stop_record(self, serial, name=""):
        if serial not in self.recording:
            return {"ok": False, "error": "当前未在录制",
                    "id": self._rec_ids.get(serial, ""),
                    "file": self._rec_files.get(serial, "")}
        self.scrcpy.stop_record(serial)          # 阻塞直到干净收尾（保证文件可播放）
        self.recording.discard(serial)
        path = self._rec_files.get(serial, "")
        rid = self._rec_ids.get(serial, "")
        self.root.after(0, lambda: (self.log(f"■ [API] 已保存 {os.path.basename(path)}"),
                                    self._refresh_rec_ui(serial)))
        result = {"ok": True, "id": rid, "file": path}
        if name:                                 # 停录时就带了名字 = stop + rename 一步到位
            rn = self.api_rename(serial, name, "", path)
            if rn.get("ok"):
                result["file"] = rn["file"]
            else:
                result["rename_error"] = rn.get("error", "")
        return result

    def api_rename(self, serial, name="", folder="", src=""):
        """改名并（可选）归档到 records 下的子文件夹。供 OCR 识别出内容后回调。"""
        if serial in self.recording:
            return {"ok": False, "error": "仍在录制，请先停止"}
        if not name:
            return {"ok": False, "error": "name 不能为空"}
        path = src or self._rec_files.get(serial, "")
        if not path or not os.path.exists(path):
            return {"ok": False, "error": "找不到录制文件"}
        dev = self._device_by_serial(serial)
        dev_dir = self._device_records_dir(dev or serial)
        target_dir = os.path.join(dev_dir, self._safe_name(folder)) if folder else dev_dir
        os.makedirs(target_dir, exist_ok=True)
        ext = os.path.splitext(path)[1]
        stem = self._safe_name(name)
        newpath = os.path.join(target_dir, stem + ext)
        i = 1
        while os.path.exists(newpath) and os.path.abspath(newpath) != os.path.abspath(path):
            newpath = os.path.join(target_dir, f"{stem}-{i}{ext}")
            i += 1
        try:
            os.replace(path, newpath)            # 同盘=改名/移动
        except OSError:
            import shutil                         # 跨盘兜底
            shutil.move(path, newpath)
        if self._rec_files.get(serial) == path:
            self._rec_files[serial] = newpath
        self.root.after(0, lambda: self.log(f"✎ [API] 归档 {os.path.basename(newpath)}"))
        return {"ok": True, "file": newpath}

    # ---------------- 其它 ----------------
    def _encoder_options(self, force=False):
        """检测在线设备支持的视频编码器（带缓存，避免每次都查）。"""
        if self._encoder_cache and not force:
            return self._encoder_cache
        devs = [d for d in self.devices if d.is_online]
        if not devs:
            return self._encoder_cache
        out = []
        for c, e, hw in self.scrcpy.list_encoders(devs[0].serial):
            out.append(f"{c} & {e}" + ("  (hw)" if hw else "  (sw)"))
        if out:
            self._encoder_cache = out
        return out

    def open_settings(self):
        def _saved():
            self.log("设置已保存")
            self._apply_tile_size()
            # 让手机控制API的开关/端口改动立即生效（端口变了要重挂 reverse）
            self.api.enabled = self.settings.api_enabled
            self.api.phone_port = self.settings.api_phone_port
            online = {d.serial for d in self.devices if d.is_online}

            def _rebuild_api():
                self.api.stop_all()
                self.api.sync(online)
            threading.Thread(target=_rebuild_api, daemon=True).start()
        SettingsDialog(self.root, self.settings, on_save=_saved,
                       list_encoders=lambda: self._encoder_options(False),
                       refresh_encoders=lambda: self._encoder_options(True))

    def _on_drop(self, event):
        paths = self.root.tk.splitlist(event.data)
        handle_dropped_files(self, list(paths))

    def log(self, msg):
        def _append():
            self.log_text.config(state="normal")
            self.log_text.insert("end", msg + "\n")
            self.log_text.see("end")
            self.log_text.config(state="disabled")
        self.root.after(0, _append)

    def _on_close(self):
        try:      # 记住窗口大小/位置；最大化时保留上次的正常尺寸
            if self.root.state() == "zoomed":
                self.settings.window_maximized = True
            else:
                self.settings.window_maximized = False
                self.settings.window_geometry = self.root.geometry()
            self.settings.save()
        except Exception:
            pass
        try:
            self.api.stop_all()
        except Exception:
            pass
        self.scrcpy.stop_all()
        self.root.destroy()

    def run(self):
        self.root.mainloop()
