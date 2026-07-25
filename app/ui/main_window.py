# -*- coding: utf-8 -*-
"""主窗口：现代深色界面（ttkbootstrap）。

左侧控制面板 + 右侧嵌入式投屏网格。设备连上自动出现在网格里。
标签：单击=激活(移到最前并高亮)，双击设备行=编辑标签/编号。
"""
import os
import re
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


class SoloWindow(tb.Toplevel):
    """独立投屏窗口：顶部手势导航按钮 + 嵌入的 scrcpy 画面。"""
    def __init__(self, app, device):
        super().__init__(app.root)
        self.app = app
        self.device = device
        self.hwnd = None
        name = app.book.name(device.serial, device.model or device.serial)
        self.title(f"独立 · {name}")
        w = app.settings.solo_window_size
        self.geometry(f"{w + 24}x{int(w * 1.9) + 56}")
        center_window(self)
        self.protocol("WM_DELETE_WINDOW", self._close)

        bar = tb.Frame(self)
        bar.pack(fill=X, pady=2)
        for text, code in [("← 返回", KEY_BACK), ("● 桌面", KEY_HOME), ("▣ 多任务", KEY_RECENT)]:
            tb.Button(bar, text=text, bootstyle="info-outline",
                      command=lambda c=code: app._send_key_one(device, c)).pack(side=LEFT, padx=3, pady=2)

        self.video = tk.Frame(self, bg="black")
        self.video.pack(fill=BOTH, expand=True)
        self.bind("<Configure>", self._reposition)

        title = app.scrcpy.start_solo_embed_process(device)

        def find():
            h = embed.find_hwnd_by_title(title)
            time.sleep(1.5)
            self.after(0, lambda: self._attach(h))
        threading.Thread(target=find, daemon=True).start()

    def _attach(self, h):
        if not h or not self.winfo_exists():
            return
        embed.set_owner(h, embed.root_hwnd(int(self.winfo_id())))
        self.hwnd = h
        self._reposition()

    def _reposition(self, _=None):
        if self.hwnd and self.video.winfo_ismapped():
            embed.place(self.hwnd, self.video.winfo_rootx(), self.video.winfo_rooty(),
                        self.video.winfo_width(), self.video.winfo_height())

    def _close(self):
        self.app.scrcpy.stop(self.device.serial, "solo")
        self.app.solo_windows.pop(self.device.serial, None)
        self.destroy()


class App:
    def __init__(self):
        self.settings = config.Settings.load()
        self.book = config.DeviceBook()
        self.adb = Adb(config.ADB_EXE)
        self.scrcpy = ScrcpyManager(config.SCRCPY_EXE, self.settings)

        self.root = TkinterDnD.Tk() if _HAS_DND else tk.Tk()
        self.style = tb.Style(THEME)
        self.colors = self.style.colors
        # 亮色界面下各处颜色（tk 原生控件需手动上色）
        self.C_GRID = "#e9ecef"       # 右侧网格背景
        self.C_TILE_BORDER = "#c4cad2"
        self.C_HEADER = "#f4f6f8"      # 格子标题栏
        self.C_TAG_OFF_BG = "#e2e6ea"  # 未激活标签
        self.C_TAG_OFF_FG = "#495057"
        self.root.title(f"{config.APP_NAME} v{config.APP_VERSION}")
        self.root.geometry("1160x740")
        center_window(self.root)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        self.devices = []
        self.check_vars = {}
        self.tiles = {}
        self.recording = set()          # 正在录制的设备序列号
        self.solo_windows = {}          # serial -> SoloWindow
        self._encoder_cache = []        # 编码器检测缓存
        self._known_serials = set()
        self._last_cols = 0
        os.makedirs(config.RECORDS_DIR, exist_ok=True)

        self._build_ui()
        self.root.bind("<Configure>", self._position_all_overlays)
        if _HAS_DND:
            self.root.drop_target_register(DND_FILES)
            self.root.dnd_bind("<<Drop>>", self._on_drop)

        self.adb.start_server()
        self._poll()
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
        canvas.create_window((0, 0), window=self.list_frame, anchor="nw")
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
                if d.is_online and not d.model:
                    d.model = self.adb.get_model(d.serial)
            self.root.after(0, lambda: self._sync(devs))
        threading.Thread(target=worker, daemon=True).start()
        self.root.after(4000, self._poll)

    def _sync(self, devs):
        devs.sort(key=lambda d: self.book.number(d.serial, 9999))
        self.devices = devs
        online = {d.serial for d in devs if d.is_online}
        new = online - self._known_serials
        if self.settings.auto_mirror:
            # 逐台错开启动，避免多台 scrcpy 同时启动互相抢占而崩溃
            for i, d in enumerate([x for x in devs if x.serial in new]):
                self.root.after(i * 1800, lambda dev=d: self._embed_device(dev))
        self._known_serials = online
        for serial in list(self.recording):
            if serial not in online:      # 设备拔出，scrcpy 会自行收尾录制
                self.recording.discard(serial)
        for serial in list(self.tiles.keys()):
            if serial not in online:
                self._remove_tile(serial)
        self._render_list(devs)
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
            num = self.book.number(d.serial, idx + 1)
            row = tb.Frame(self.list_frame)
            row.pack(fill=X, pady=2, padx=2)
            var = self.check_vars.get(d.serial, tk.BooleanVar())
            new_vars[d.serial] = var
            tb.Checkbutton(row, variable=var, bootstyle="round-toggle").pack(side=LEFT, padx=(2, 4))
            tb.Label(row, text=str(num), width=2, bootstyle="info").pack(side=LEFT)
            self._render_tag_chips(
                row, self._device_tags(d),
                on_click=lambda tag, dev=d: self._activate_tag(dev, tag))
            if not d.is_online:
                tb.Label(row, text="离线", bootstyle="danger").pack(side=LEFT, padx=2)
            if d.serial in self.recording:
                tb.Label(row, text="● REC", bootstyle="danger",
                         font=(FONT, 8, "bold")).pack(side=RIGHT, padx=2)
            dbl = lambda e, dev=d: self._edit_device(dev)
            row.bind("<Double-Button-1>", dbl)
            # 右键菜单（整行含子控件都能触发）
            bind_recursive(row, "<Button-3>", lambda e, dev=d: self._device_menu(e, dev))
        self.check_vars = new_vars
        self.status.config(text=f" 总数 {len(devs)}   在线 {len(self._known_serials)}   "
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
            res = updater.check_update(config.GITHUB_OWNER, config.GITHUB_REPO, config.APP_VERSION)

            def show():
                if res:
                    ver, url = res
                    if messagebox.askyesno("发现新版本",
                                           f"有新版本 v{ver}（当前 v{config.APP_VERSION}）。\n是否打开下载页面？"):
                        webbrowser.open(url)
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

    def _nudge_tile_size(self, delta):
        new = max(160, min(600, self.settings.group_window_size + delta))
        if new == self.settings.group_window_size:
            return
        self.settings.group_window_size = new
        self.settings.save()
        self._apply_tile_size()

    def _apply_tile_size(self):
        tw, th = self._tile_size()
        for tile in self.tiles.values():
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
        tw, th = self._tile_size()
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

    def _position_all_overlays(self, _event=None):
        for serial in self.tiles:
            self._position_overlay(serial)

    def _update_tile_header(self, serial):
        tile = self.tiles.get(serial)
        if not tile:
            return
        dev = tile["device"]
        header = tile["header"]
        for w in header.winfo_children():
            w.destroy()
        num = self.book.number(serial, 0)
        if num:
            tk.Label(header, text=str(num), bg=self.C_HEADER, fg=self.colors.primary,
                     font=(FONT, 8, "bold")).pack(side=LEFT, padx=(4, 2))
        tags = self._device_tags(dev)
        fs = 9 if len(tags) <= 2 else 8 if len(tags) <= 4 else 7 if len(tags) <= 6 else 6
        self._render_tag_chips(header, tags, font_size=fs,
                               on_click=lambda tag, d=dev: self._activate_tag(d, tag))
        if serial in self.recording:
            tk.Label(header, text="● REC", bg=self.C_HEADER, fg="#e03131",
                     font=(FONT, 8, "bold")).pack(side=RIGHT, padx=3)
        header.bind("<Double-Button-1>", lambda e, d=dev: self._edit_device(d))

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
                         key=lambda kv: self.book.number(kv[0], 9999))
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
        win = self.solo_windows.get(device.serial)
        if win and win.winfo_exists():      # 已开就置前
            win.lift()
            win.focus_force()
            return
        self.solo_windows[device.serial] = SoloWindow(self, device)
        self.log(f"独立投屏: {self.book.name(device.serial, device.display_name)}")

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

    def _record_config(self, device):
        """该设备的有效录制参数：有独立设置用自己的，否则用通用设置。"""
        return self.book.record_override(device.serial) or self.settings.record_config()

    def _record_path(self, device, rec):
        s = self.settings
        num = self.book.number(device.serial, 0)
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
        d = s.effective_records_dir()
        os.makedirs(d, exist_ok=True)
        return os.path.join(d, f"{name}.{rec.get('fmt', 'mp4')}")

    def _do_start_record(self, device):
        name = self._safe_name(self.book.name(device.serial, device.model or device.serial))
        rec = self._record_config(device)
        path = self._record_path(device, rec)
        if self.scrcpy.start_record(device, path, rec):
            self.recording.add(device.serial)
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
        self.scrcpy.stop_all()
        self.root.destroy()

    def run(self):
        self.root.mainloop()
