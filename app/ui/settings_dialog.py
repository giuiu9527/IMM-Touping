# -*- coding: utf-8 -*-
"""投屏设置对话框（现代深色主题）。对应参考软件的“投屏设置”面板。"""
import threading
import tkinter as tk
from tkinter import filedialog
import ttkbootstrap as tb
from ttkbootstrap.constants import LEFT, RIGHT, X, BOTH, W, E

from .. import config
from .util import center_window

FONT = "微软雅黑"


# ---- 通用录制字段构建器（全局设置面板与每设备设置面板共用） ----
def build_record_fields(parent, cfg, cached_encoders):
    """在 parent 里构建全套录制字段，返回一个可 .get_cfg() 的收集器。"""
    v = {}
    tb.Label(parent, text="分辨率上限").grid(row=0, column=0, sticky=W, padx=10, pady=6)
    v["max_size"] = tk.StringVar(value=config.int_to_maxsize(cfg["max_size"]))
    tb.Combobox(parent, textvariable=v["max_size"], values=config.MAXSIZE_CHOICES,
                width=12).grid(row=0, column=1, columnspan=2, sticky=E, padx=10, pady=6)

    tb.Label(parent, text="视频比特率").grid(row=1, column=0, sticky=W, padx=10, pady=6)
    v["bitrate_mbps"] = tk.StringVar(value=str(cfg["bitrate_mbps"]))
    br = tb.Frame(parent); br.grid(row=1, column=1, columnspan=2, sticky=E, padx=10, pady=6)
    tb.Entry(br, textvariable=v["bitrate_mbps"], width=8).pack(side=LEFT)
    tb.Label(br, text="M（可小数）").pack(side=LEFT, padx=4)

    tb.Label(parent, text="帧率").grid(row=2, column=0, sticky=W, padx=10, pady=6)
    v["fps"] = tk.StringVar(value=str(cfg["fps"]))
    tb.Combobox(parent, textvariable=v["fps"], values=config.FPS_CHOICES,
                width=12).grid(row=2, column=1, columnspan=2, sticky=E, padx=10, pady=6)

    tb.Label(parent, text="视频编码").grid(row=3, column=0, sticky=W, padx=10, pady=6)
    init = (f"{cfg['video_codec']} & {cfg['video_encoder']}"
            if cfg.get("video_encoder") else f"{cfg['video_codec']}（自动）")
    v["_codec"] = tk.StringVar(value=init)
    tb.Combobox(parent, textvariable=v["_codec"], width=32, state="readonly",
                values=["h264（自动）", "h265（自动）", "av1（自动）"] + list(cached_encoders)
                ).grid(row=3, column=1, columnspan=2, sticky=E, padx=10, pady=6)

    tb.Label(parent, text="录制格式").grid(row=4, column=0, sticky=W, padx=10, pady=6)
    v["fmt"] = tk.StringVar(value=cfg["fmt"])
    tb.Combobox(parent, textvariable=v["fmt"], values=config.RECORD_FORMAT_CHOICES,
                state="readonly", width=12).grid(row=4, column=1, columnspan=2, sticky=E, padx=10, pady=6)

    v["audio"] = tk.BooleanVar(value=cfg["audio"])
    tb.Checkbutton(parent, text="录制声音", variable=v["audio"], bootstyle="round-toggle"
                   ).grid(row=5, column=0, columnspan=3, sticky=W, padx=10, pady=6)

    tb.Label(parent, text="音频编码").grid(row=6, column=0, sticky=W, padx=10, pady=6)
    v["audio_codec"] = tk.StringVar(value=cfg["audio_codec"])
    tb.Combobox(parent, textvariable=v["audio_codec"], values=config.AUDIO_CODEC_CHOICES,
                state="readonly", width=12).grid(row=6, column=1, columnspan=2, sticky=E, padx=10, pady=6)

    tb.Label(parent, text="时长上限(秒,0=不限)").grid(row=7, column=0, sticky=W, padx=10, pady=6)
    v["time_limit"] = tk.StringVar(value=str(cfg["time_limit"]))
    tb.Entry(parent, textvariable=v["time_limit"], width=10).grid(
        row=7, column=1, columnspan=2, sticky=E, padx=10, pady=6)
    return v


def collect_record_fields(v):
    """从 build_record_fields 的 vars 收集成 cfg 字典。"""
    codec_val = v["_codec"].get().strip()
    if "&" in codec_val:
        c, e = codec_val.split("&", 1)
        vc, ve = (c.strip() or "h264"), e.strip().split("(")[0].strip()
    else:
        vc, ve = (codec_val.split("（")[0].split("(")[0].strip() or "h264"), ""

    def _i(s, d):
        try:
            return int(str(s).strip())
        except Exception:
            return d

    def _f(s, d):
        try:
            return float(str(s).strip())
        except Exception:
            return d
    return dict(
        max_size=config.maxsize_to_int(v["max_size"].get()),
        bitrate_mbps=_f(v["bitrate_mbps"].get(), 8.0),
        fps=_i(v["fps"].get(), 60),
        video_codec=vc, video_encoder=ve,
        fmt=v["fmt"].get(),
        audio=v["audio"].get(),
        audio_codec=v["audio_codec"].get(),
        time_limit=_i(v["time_limit"].get(), 0),
    )


class DeviceRecordDialog(tb.Toplevel):
    """每台设备的独立录制设置。关闭独立开关则跟随通用设置。"""
    def __init__(self, master, name, base_cfg, override, cached_encoders, on_save):
        super().__init__(master)
        self.title(f"录制设置 · {name}")
        self.resizable(False, False)
        self.transient(master)
        self.on_save = on_save
        cfg = dict(base_cfg)
        if override:
            cfg.update(override)
        self.use_var = tk.BooleanVar(value=(override is not None))
        tb.Checkbutton(self, text="此设备使用独立录制设置（关闭则跟随通用设置）",
                       variable=self.use_var, bootstyle="round-toggle").pack(
                       anchor=W, padx=12, pady=(12, 4))
        body = tb.Frame(self)
        body.pack(fill=BOTH, padx=4, pady=4)
        self.v = build_record_fields(body, cfg, cached_encoders)
        bar = tb.Frame(self)
        bar.pack(fill=X, padx=12, pady=(4, 12))
        tb.Button(bar, text="保存", bootstyle="success", command=self._save).pack(side=RIGHT, padx=4)
        tb.Button(bar, text="取消", bootstyle="secondary-outline", command=self.destroy).pack(side=RIGHT)
        center_window(self)
        self.grab_set()

    def _save(self):
        cfg = collect_record_fields(self.v) if self.use_var.get() else None
        self.on_save(cfg)
        self.destroy()


class SettingsDialog(tb.Toplevel):
    def __init__(self, master, settings: config.Settings, on_save=None,
                 list_encoders=None, refresh_encoders=None):
        super().__init__(master)
        self.title("投屏设置")
        self.settings = settings
        self.on_save = on_save
        self.list_encoders = list_encoders         # 回调：返回缓存的编码器列表
        self.refresh_encoders = refresh_encoders   # 回调：强制重新检测
        self.resizable(False, False)
        self.transient(master)
        self._build()
        center_window(self)
        self.grab_set()
        if self.list_encoders:                     # 打开即自动检测（用缓存，很快）
            self._detect_encoders(force=False)

    def _combo(self, parent, row, label, value, choices):
        tb.Label(parent, text=label).grid(row=row, column=0, sticky=W, padx=10, pady=8)
        var = tk.StringVar(value=value)
        tb.Combobox(parent, textvariable=var, values=choices, state="readonly",
                    width=8).grid(row=row, column=1, sticky=E, padx=10, pady=8)
        return var

    def _slider(self, parent, row, label, value, lo, hi):
        tb.Label(parent, text=label).grid(row=row, column=0, sticky=W, padx=10, pady=8)
        var = tk.IntVar(value=value)
        val_lbl = tb.Label(parent, width=6, bootstyle="info")
        val_lbl.grid(row=row, column=2, padx=(0, 10))

        def _upd(_=None):
            val_lbl.config(text=f"{var.get()}px")
        tb.Scale(parent, from_=lo, to=hi, variable=var, orient="horizontal",
                 length=180, command=lambda e: _upd()).grid(row=row, column=1, sticky=E, padx=10, pady=8)
        _upd()
        return var

    def _switch(self, parent, row, label, value):
        var = tk.BooleanVar(value=value)
        tb.Checkbutton(parent, text=label, variable=var, bootstyle="round-toggle").grid(
            row=row, column=0, columnspan=3, sticky=W, padx=10, pady=6)
        return var

    def _opt(self, parent, row, label, value, choices, editable=False, width=14):
        tb.Label(parent, text=label).grid(row=row, column=0, sticky=W, padx=10, pady=7)
        var = tk.StringVar(value=str(value))
        tb.Combobox(parent, textvariable=var, values=choices,
                    state="normal" if editable else "readonly",
                    width=width).grid(row=row, column=1, columnspan=2, sticky=E, padx=10, pady=7)
        return var

    def _entry(self, parent, row, label, value, width=18):
        tb.Label(parent, text=label).grid(row=row, column=0, sticky=W, padx=10, pady=7)
        var = tk.StringVar(value=str(value))
        tb.Entry(parent, textvariable=var, width=width).grid(
            row=row, column=1, columnspan=2, sticky=E, padx=10, pady=7)
        return var

    def _build(self):
        s = self.settings
        nb = tb.Notebook(self)
        nb.pack(fill=BOTH, expand=True, padx=12, pady=12)

        f1 = tb.Frame(nb)
        nb.add(f1, text="  独立窗口  ")
        self.v_solo_res = self._combo(f1, 0, "独立窗口分辨率", s.solo_resolution, config.RESOLUTION_CHOICES)
        self.v_solo_flu = self._combo(f1, 1, "独立窗口流畅度", s.solo_fluidity, config.FLUIDITY_CHOICES)
        self.v_solo_size = self._slider(f1, 2, "独立窗口尺寸", s.solo_window_size, 240, 900)

        f2 = tb.Frame(nb)
        nb.add(f2, text="  群控窗口  ")
        self.v_grp_res = self._combo(f2, 0, "群控窗口分辨率", s.group_resolution, config.RESOLUTION_CHOICES)
        self.v_grp_flu = self._combo(f2, 1, "群控窗口流畅度", s.group_fluidity, config.FLUIDITY_CHOICES)
        self.v_grp_size = self._slider(f2, 2, "群控窗口尺寸", s.group_window_size, 160, 500)
        self.v_direct = self._switch(f2, 3, "群控窗口可直接控制", s.direct_control)

        # ---- 录制 ----
        f4 = tb.Frame(nb)
        nb.add(f4, text="  录制  ")
        self.v_rec_size = self._opt(f4, 0, "分辨率上限", config.int_to_maxsize(s.record_max_size),
                                    config.MAXSIZE_CHOICES, editable=True)
        # 比特率：数字 + 单位 M，支持小数
        tb.Label(f4, text="视频比特率").grid(row=1, column=0, sticky=W, padx=10, pady=7)
        self.v_rec_bitrate = tk.StringVar(value=str(s.record_bitrate_mbps))
        brow = tb.Frame(f4)
        brow.grid(row=1, column=1, columnspan=2, sticky=E, padx=10, pady=7)
        tb.Entry(brow, textvariable=self.v_rec_bitrate, width=8).pack(side=LEFT)
        tb.Label(brow, text="M（可小数，如 0.5）").pack(side=LEFT, padx=4)

        self.v_rec_fps = self._opt(f4, 2, "帧率", s.record_fps, config.FPS_CHOICES, editable=True)
        # 视频编码：可检测设备实际编码器
        tb.Label(f4, text="视频编码").grid(row=3, column=0, sticky=W, padx=10, pady=7)
        init_codec = (f"{s.record_video_codec} & {s.record_video_encoder}"
                      if s.record_video_encoder else f"{s.record_video_codec}（自动）")
        self.v_rec_vcodec = tk.StringVar(value=init_codec)
        crow = tb.Frame(f4)
        crow.grid(row=3, column=1, columnspan=2, sticky=E, padx=10, pady=7)
        self.cb_codec = tb.Combobox(crow, textvariable=self.v_rec_vcodec, width=34, state="readonly",
                                    values=["h264（自动）", "h265（自动）", "av1（自动）"])
        self.cb_codec.pack(side=LEFT)
        tb.Button(crow, text="重新检测", bootstyle="info-outline", width=8,
                  command=lambda: self._detect_encoders(force=True)).pack(side=LEFT, padx=4)

        self.v_rec_format = self._opt(f4, 4, "录制格式", s.record_format, config.RECORD_FORMAT_CHOICES)
        self.v_rec_audio = self._switch(f4, 5, "录制声音", s.record_audio)
        self.v_rec_acodec = self._opt(f4, 6, "音频编码", s.record_audio_codec, config.AUDIO_CODEC_CHOICES)
        self.v_rec_limit = self._entry(f4, 7, "时长上限(秒，0=不限)", s.record_time_limit, width=10)

        # ---- 存储 ----
        f5 = tb.Frame(nb)
        nb.add(f5, text="  存储  ")
        tb.Label(f5, text="录屏保存目录（空=默认 records/）").grid(row=0, column=0, columnspan=3, sticky=W, padx=10, pady=(8, 2))
        self.v_dir = tk.StringVar(value=s.records_dir)
        tb.Entry(f5, textvariable=self.v_dir, width=30).grid(row=1, column=0, sticky=W, padx=10)
        tb.Button(f5, text="浏览", bootstyle="info-outline", command=self._pick_dir).grid(row=1, column=1, padx=2)
        tb.Button(f5, text="打开目录", bootstyle="secondary-outline", command=self._open_dir).grid(row=1, column=2, padx=2)
        self.v_naming = self._entry(f5, 2, "文件命名模板", s.naming_template, width=30)
        tb.Label(f5, text="可用占位符：{num}序号  {time}时间  {tags}标签  {model}型号  {serial}序列号",
                 bootstyle="secondary", wraplength=380, justify="left").grid(
                 row=3, column=0, columnspan=3, sticky=W, padx=10, pady=(2, 8))

        # ---- 通用 ----
        f3 = tb.Frame(nb)
        nb.add(f3, text="  通用  ")
        self.v_screenoff = self._switch(f3, 0, "自动息屏（投屏时关闭手机屏幕）", s.auto_screen_off)
        self.v_automir = self._switch(f3, 1, "自动投屏（设备连上就自动嵌入网格）", s.auto_mirror)

        bar = tb.Frame(self)
        bar.pack(fill=X, padx=12, pady=(0, 12))
        tb.Button(bar, text="保存", bootstyle="success", command=self._save).pack(side=RIGHT, padx=4)
        tb.Button(bar, text="取消", bootstyle="secondary-outline", command=self.destroy).pack(side=RIGHT)

    def _pick_dir(self):
        d = filedialog.askdirectory(title="选择录屏保存目录")
        if d:
            self.v_dir.set(d)

    def _open_dir(self):
        import os
        d = self.v_dir.get().strip() or config.RECORDS_DIR
        os.makedirs(d, exist_ok=True)
        try:
            os.startfile(d)
        except Exception:
            pass

    def _detect_encoders(self, force=False):
        fn = self.refresh_encoders if (force and self.refresh_encoders) else self.list_encoders
        if not fn:
            return
        cur = self.v_rec_vcodec.get()
        if force:
            self.v_rec_vcodec.set("检测中...")

        def worker():
            opts = fn() or []

            def apply():
                if not self.cb_codec.winfo_exists():   # 对话框已关就别再动控件
                    return
                base = ["h264（自动）", "h265（自动）", "av1（自动）"]
                vals = base + opts
                self.cb_codec.configure(values=vals)
                # 保持当前选择；强制检测且原来是占位则选第一个
                if self.v_rec_vcodec.get() == "检测中...":
                    self.v_rec_vcodec.set(cur if cur in vals else (opts[0] if opts else "h264（自动）"))
            self.after(0, apply)
        threading.Thread(target=worker, daemon=True).start()

    def _parse_codec(self, val):
        val = (val or "").strip()
        if "&" in val:
            c, e = val.split("&", 1)
            return (c.strip() or "h264"), e.strip().split("(")[0].strip()
        c = val.split("（")[0].split("(")[0].strip()
        return (c or "h264"), ""

    def _to_int(self, s, default=0):
        try:
            return int(str(s).strip())
        except Exception:
            return default

    def _to_float(self, s, default=8.0):
        try:
            return float(str(s).strip())
        except Exception:
            return default

    def _save(self):
        s = self.settings
        s.solo_resolution = self.v_solo_res.get()
        s.solo_fluidity = self.v_solo_flu.get()
        s.solo_window_size = self.v_solo_size.get()
        s.group_resolution = self.v_grp_res.get()
        s.group_fluidity = self.v_grp_flu.get()
        s.group_window_size = self.v_grp_size.get()
        s.direct_control = self.v_direct.get()
        s.auto_screen_off = self.v_screenoff.get()
        s.auto_mirror = self.v_automir.get()
        # 录制
        s.record_max_size = config.maxsize_to_int(self.v_rec_size.get())
        s.record_bitrate_mbps = self._to_float(self.v_rec_bitrate.get(), 8.0)
        s.record_fps = self._to_int(self.v_rec_fps.get(), 60)
        s.record_video_codec, s.record_video_encoder = self._parse_codec(self.v_rec_vcodec.get())
        s.record_format = self.v_rec_format.get()
        s.record_audio = self.v_rec_audio.get()
        s.record_audio_codec = self.v_rec_acodec.get()
        s.record_time_limit = self._to_int(self.v_rec_limit.get(), 0)
        # 存储
        s.records_dir = self.v_dir.get().strip()
        s.naming_template = self.v_naming.get().strip() or "{num}_{time}_{tags}"
        s.save()
        if self.on_save:
            self.on_save()
        self.destroy()