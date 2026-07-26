# -*- coding: utf-8 -*-
"""投屏进程管理。

- 独立窗口(solo)：单台，高分辨率、大窗口。
- 群控窗口(group)：多台，中分辨率、小窗口，自动平铺成网格。

每台设备同一模式只保留一个进程；关闭窗口后进程自然退出，会被清理。
以后要接入“嵌入式网格”等新投屏方式，只需在这里加一个 launch_* 方法。
"""
import math
import subprocess
from typing import Dict, List

from .. import config

_NO_WINDOW = 0x08000000


class ScrcpyManager:
    def __init__(self, scrcpy_exe: str, settings: config.Settings):
        self.scrcpy_exe = scrcpy_exe
        self.settings = settings
        # key: (serial, mode) -> Popen
        self._procs: Dict[tuple, subprocess.Popen] = {}
        # 屏幕可用区域，由 UI 传入（避开任务栏）
        self.screen_w = 1920
        self.screen_h = 1040

    # ---------- 基础 ----------
    def set_screen(self, w: int, h: int):
        self.screen_w, self.screen_h = w, h

    def _cleanup(self):
        dead = [k for k, p in self._procs.items() if p.poll() is not None]
        for k in dead:
            self._procs.pop(k, None)

    def is_running(self, serial: str, mode: str = None) -> bool:
        self._cleanup()
        if mode:
            return (serial, mode) in self._procs
        return any(s == serial for (s, _m) in self._procs)

    def running(self):
        """返回当前所有投屏窗口 [(serial, mode), ...]，mode 为 'solo'/'group'/'record'。"""
        self._cleanup()
        return list(self._procs.keys())

    # ---------- 录屏 ----------
    def list_encoders(self, serial: str, timeout: float = 15):
        """查询设备支持的视频编码器，返回 [(codec, encoder, is_hw), ...]。"""
        import re
        try:
            p = subprocess.run([self.scrcpy_exe, "-s", serial, "--list-encoders"],
                               capture_output=True, text=True, encoding="utf-8",
                               errors="replace", timeout=timeout, creationflags=_NO_WINDOW)
            out = (p.stdout or "") + (p.stderr or "")
        except Exception:
            return []
        result = []
        for line in out.splitlines():
            m = re.search(r"--video-codec=(\S+)\s+--video-encoder=(\S+)", line)
            if m and "alias for" not in line:      # 别名跳过，避免重复
                result.append((m.group(1), m.group(2), "(hw)" in line))
        return result

    def is_recording(self, serial: str) -> bool:
        self._cleanup()
        return (serial, "record") in self._procs

    def start_record(self, device, out_path: str, rec: dict) -> bool:
        """后台录制到 out_path（无可见窗口）。rec 为录制参数字典。"""
        key = (device.serial, "record")
        self._cleanup()
        if key in self._procs:
            return False
        bits = max(1, int(rec["bitrate_mbps"] * 1_000_000))   # Mbps -> bps，支持小数
        cmd = [
            self.scrcpy_exe, "-s", device.serial,
            "--record", out_path,
            "--video-bit-rate", str(bits),
            "--max-fps", str(rec["fps"]),
            "--video-codec", rec["video_codec"],
        ]
        if rec.get("video_encoder"):
            cmd += ["--video-encoder", rec["video_encoder"]]
        if rec.get("max_size"):
            cmd += ["--max-size", str(rec["max_size"])]
        if rec.get("audio", True):
            cmd += ["--audio-codec", rec.get("audio_codec", "opus"),
                    "--audio-source", rec.get("audio_source", "playback")]
        else:
            cmd += ["--no-audio"]
        if rec.get("time_limit"):
            cmd += ["--time-limit", str(rec["time_limit"])]
        cmd += [
            "--window-title", f"__rec_{device.serial}",
            "--window-borderless",
            "--window-x", "-3000", "--window-y", "-3000",
            "--window-width", "240", "--window-height", "480",
        ]
        self._procs[key] = subprocess.Popen(cmd, creationflags=_NO_WINDOW)
        return True

    def stop_record(self, serial: str, timeout: float = 6.0) -> bool:
        """干净停止录制：发 WM_CLOSE 让 scrcpy 收尾写入索引，保证 mp4 可播放。"""
        import time
        from . import embed
        key = (serial, "record")
        p = self._procs.get(key)
        if not p:
            return False
        hwnd = embed.find_hwnd_by_title(f"__rec_{serial}", timeout=1.5)
        if hwnd:
            embed.close(hwnd)
        for _ in range(int(timeout * 10)):
            if p.poll() is not None:
                break
            time.sleep(0.1)
        if p.poll() is None:            # 兜底：收尾超时才硬停
            p.terminate()
        self._procs.pop(key, None)
        return True

    def _build_base(self, serial: str, res_key: str, flu_key: str, title: str) -> List[str]:
        max_size = config.RESOLUTION_PRESETS[res_key]
        bitrate, fps = config.FLUIDITY_PRESETS[flu_key]
        cmd = [
            self.scrcpy_exe, "-s", serial,
            "--video-bit-rate", bitrate,
            "--max-fps", str(fps),
            "--window-title", title,
        ]
        if max_size:
            cmd += ["--max-size", str(max_size)]
        if self.settings.auto_screen_off:
            cmd.append("--turn-screen-off")
        # 不转发鼠标悬停(仅移动不点击)：避免鼠标划过就误操作手机
        cmd.append("--no-mouse-hover")
        return cmd

    def _spawn(self, key: tuple, cmd: List[str]):
        # 同 key 已在跑就不重复开
        self._cleanup()
        if key in self._procs:
            return
        self._procs[key] = subprocess.Popen(cmd, creationflags=_NO_WINDOW)

    # ---------- 独立窗口 ----------
    def launch_solo(self, device, name: str = None):
        s = self.settings
        key = (device.serial, "solo")
        self._cleanup()
        if key in self._procs:
            return
        w = s.solo_window_size
        h = int(w * 1.9)  # 竖屏手机大致比例，scrcpy 会按真实比例自适应
        display = name or device.display_name
        cmd = self._build_base(device.serial, s.solo_resolution, s.solo_fluidity,
                               f"独立 · {display}")
        cmd += [
            "--window-width", str(w),
            "--window-height", str(h),
            "--audio-source", "playback",       # 使用 playback 避免 output 默认源 -33dB 声音衰减
            "--audio-codec", "opus",           # opus 格式响度更佳
        ]
        # creationflags=_NO_WINDOW：隐藏黑色的 CMD 控制台终端窗口，只留下 scrcpy 原生画面窗口
        self._procs[key] = subprocess.Popen(cmd, creationflags=_NO_WINDOW)

    # ---------- 群控窗口（嵌入软件网格） ----------
    def start_embed_process(self, device, x=-3000, y=-3000, w=300, h=570):
        """启动一个无边框 scrcpy 供嵌入，返回窗口标题(用于查找句柄)。

        默认开在屏幕外(-3000)：避免嵌入前在桌面闪一下；由 UI 找到句柄后 set_owner 再定位进格子。
        """
        s = self.settings
        title = f"__grp_{device.serial}"
        key = (device.serial, "group")
        self._cleanup()
        if key in self._procs:
            return title            # 已在跑
        cmd = self._build_base(device.serial, s.group_resolution, s.group_fluidity, title)
        cmd += ["--window-borderless", "--no-audio",
                "--window-x", str(int(x)), "--window-y", str(int(y)),
                "--window-width", str(int(w)), "--window-height", str(int(h))]
        if not s.direct_control:
            cmd.append("--no-control")
        self._procs[key] = subprocess.Popen(cmd, creationflags=_NO_WINDOW)
        return title

    def start_solo_embed_process(self, device, x=300, y=200, w=360, h=640):
        """启动无边框独立投屏进程供嵌入（独立窗口画质），返回窗口标题。"""
        s = self.settings
        title = f"__solo_{device.serial}"
        key = (device.serial, "solo")
        self._cleanup()
        if key in self._procs:
            return title
        cmd = self._build_base(device.serial, s.solo_resolution, s.solo_fluidity, title)
        cmd += ["--window-borderless",
                "--window-x", str(int(x)), "--window-y", str(int(y)),
                "--window-width", str(int(w)), "--window-height", str(int(h))]
        self._procs[key] = subprocess.Popen(cmd, creationflags=_NO_WINDOW)
        return title

    # ---------- 群控窗口（桌面平铺，备用） ----------
    def launch_group(self, devices: list):
        """把多台设备平铺成网格。"""
        online = [d for d in devices if d.is_online]
        if not online:
            return
        s = self.settings
        tile_w = s.group_window_size
        tile_h = int(tile_w * 1.9)
        cols = max(1, self.screen_w // (tile_w + 6))
        for idx, d in enumerate(online):
            row, col = divmod(idx, cols)
            x = col * (tile_w + 6)
            y = row * (tile_h + 30)
            # 超出屏幕高度就回到顶部继续叠（避免完全看不到）
            if y + tile_h > self.screen_h:
                y = (y % max(1, self.screen_h - tile_h))
            cmd = self._build_base(d.serial, s.group_resolution, s.group_fluidity,
                                   f"[群控] {d.display_name}")
            cmd += ["--window-x", str(x), "--window-y", str(y),
                    "--window-width", str(tile_w), "--window-height", str(tile_h)]
            if not s.direct_control:
                cmd.append("--no-control")
            if s.borderless:
                cmd.append("--window-borderless")
            self._spawn((d.serial, "group"), cmd)

    # ---------- 关闭 ----------
    def stop(self, serial: str, mode: str = None):
        self._cleanup()
        for key in list(self._procs.keys()):
            s, m = key
            if s == serial and (mode is None or m == mode):
                try:
                    self._procs[key].terminate()
                except Exception:
                    pass
                self._procs.pop(key, None)

    def stop_all(self):
        # 先干净收尾所有录制，避免 mp4 损坏
        for serial, mode in list(self._procs.keys()):
            if mode == "record":
                self.stop_record(serial)
        for p in self._procs.values():
            try:
                p.terminate()
            except Exception:
                pass
        self._procs.clear()
