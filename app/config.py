# -*- coding: utf-8 -*-
"""全局配置与投屏参数预设。

所有可调项集中在这里，UI 只读写 Settings，core 层只读预设，
以后加新参数在这里扩展即可。
"""
import json
import os
import sys
from dataclasses import dataclass, asdict, field

# 根目录：打包成 exe 后用 exe 所在目录（scrcpy/、settings.json 等都放它旁边）；
# 源码运行时用项目目录。
if getattr(sys, "frozen", False):
    ROOT = os.path.dirname(sys.executable)
else:
    ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRCPY_DIR = os.path.join(ROOT, "scrcpy")
SCRCPY_EXE = os.path.join(SCRCPY_DIR, "scrcpy.exe")
ADB_EXE = os.path.join(SCRCPY_DIR, "adb.exe")
# 图标（放在 app/ 目录下，源码和打包都能找到）
_APP_DIR = os.path.dirname(os.path.abspath(__file__))
ICON_ICO = os.path.join(_APP_DIR, "imm.ico")
ICON_PNG = os.path.join(_APP_DIR, "imm.png")
# 应用信息
APP_NAME = "IMM投屏"
APP_VERSION = "0.1.23"
GITHUB_OWNER = "giuiu9527"           # 在线更新查这个账户的 releases
GITHUB_REPO = "IMM-Touping"          # 仓库名，发布时确认

SETTINGS_PATH = os.path.join(ROOT, "settings.json")
DEVICES_PATH = os.path.join(ROOT, "devices.json")
RECORDS_DIR = os.path.join(ROOT, "records")     # 默认存软件目录下（可在设置里改）

# 分辨率预设 -> scrcpy --max-size（限制画面最长边像素，0 表示原生不限制）
RESOLUTION_PRESETS = {"高": 1280, "中": 800, "低": 560}

# 流畅度预设 -> (码率, 最大帧率)
FLUIDITY_PRESETS = {
    "高": ("8M", 60),
    "中": ("4M", 30),
    "低": ("2M", 15),
}

# 下拉框可选项顺序
RESOLUTION_CHOICES = ["高", "中", "低"]
FLUIDITY_CHOICES = ["高", "中", "低"]

# 录制相关可选项
VIDEO_CODEC_CHOICES = ["h264", "h265", "av1"]
AUDIO_CODEC_CHOICES = ["aac", "opus", "flac"]
RECORD_FORMAT_CHOICES = ["mp4", "mkv"]
AUDIO_SOURCE_CHOICES = ["playback", "output", "mic"]   # playback 最响(默认)
MAXSIZE_CHOICES = ["原画", "1080", "720", "480"]   # “原画”表示不限制(0)
FPS_CHOICES = ["60", "30", "25", "15"]
BITRATE_CHOICES = ["16M", "8M", "4M", "2M"]


def maxsize_to_int(label: str) -> int:
    """把“原画/1080/...”转成 --max-size 的数值(原画=0=不限)。"""
    return 0 if label in ("原画", "0", "") else int(label)


def int_to_maxsize(v: int) -> str:
    return "原画" if not v else str(v)


@dataclass
class Settings:
    # 独立窗口（单台重点控制）
    solo_resolution: str = "高"
    solo_fluidity: str = "高"
    solo_window_size: int = 480          # 独立窗口宽度(px)，高度按手机比例自适应

    # 群控窗口（多台平铺）
    group_resolution: str = "中"
    group_fluidity: str = "中"
    group_window_size: int = 300         # 群控每个窗口宽度(px)

    # 开关
    auto_screen_off: bool = False        # 自动息屏（投屏时关闭手机屏幕省电）
    auto_mirror: bool = True             # 自动投屏（设备连上就自动嵌入网格）
    direct_control: bool = True          # 群控窗口是否可直接鼠标控制
    borderless: bool = False             # 群控窗口无边框（更像网格）

    # 录制设置（影响录屏质量）
    record_max_size: int = 0             # 分辨率上限，0=原画
    record_bitrate_mbps: float = 8.0     # 视频比特率(Mbps，支持小数如 0.5)
    record_fps: int = 60                 # 帧率
    record_video_codec: str = "h264"     # 视频编码 h264/h265/av1
    record_video_encoder: str = ""       # 具体编码器(空=自动选)，如 c2.qti.avc.encoder
    record_format: str = "mkv"           # 容器格式 mp4/mkv（opus 需 mkv）
    record_audio: bool = True            # 是否录制声音
    record_audio_codec: str = "opus"     # 音频编码：opus 比 aac 更大声（和 escrcpy 一致）
    record_audio_source: str = "playback"  # 音频源：playback 比 output 大很多（和 escrcpy 一致）
    record_time_limit: int = 0           # 录制时长上限(秒)，0=不限

    # 存储设置
    records_dir: str = ""                # 录屏保存目录，空=默认 records/
    naming_template: str = "Recording-{num2}-{firsttag}-{time}"   # 文件命名模板
    subfolder_by_device: bool = True     # 是否按机器编码/编号独立保存到子文件夹（如 records/01-标签/）

    # 本地控制 API（供手机端 autox.js 通过 adb reverse 调用，自动录制/停止/改名归档）
    api_enabled: bool = True             # 是否开启本地控制 API
    api_phone_port: int = 8300           # 手机侧固定端口（脚本写死 127.0.0.1:该端口）
    api_pc_port: int = 8300              # 电脑侧起始端口，每台设备顺延分配一个专属端口

    # 窗口记忆
    window_geometry: str = ""            # 上次窗口大小/位置，如 1160x740+100+50
    window_maximized: bool = False       # 上次是否最大化

    # 内部：一次性迁移标记
    audio_default_migrated: bool = False  # 把旧的 aac 默认迁移到更大声的 opus

    def _migrate(self):
        changed = False
        if not self.audio_default_migrated:
            if self.record_audio_codec == "aac":     # 旧默认 aac 偏小声，换成 opus
                self.record_audio_codec = "opus"
                if self.record_format == "mp4":
                    self.record_format = "mkv"        # opus 需要 mkv 容器
            self.audio_default_migrated = True
            changed = True
        if changed:
            self.save()

    def effective_records_dir(self):
        return self.records_dir or RECORDS_DIR

    def record_config(self):
        """通用录制参数（字典），供每设备覆盖时做基准。"""
        return dict(
            max_size=self.record_max_size,
            bitrate_mbps=self.record_bitrate_mbps,
            fps=self.record_fps,
            video_codec=self.record_video_codec,
            video_encoder=self.record_video_encoder,
            fmt=self.record_format,
            audio=self.record_audio,
            audio_codec=self.record_audio_codec,
            audio_source=self.record_audio_source,
            time_limit=self.record_time_limit,
        )

    def save(self):
        with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
            json.dump(asdict(self), f, ensure_ascii=False, indent=2)

    @classmethod
    def load(cls):
        if os.path.exists(SETTINGS_PATH):
            try:
                with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
                    data = json.load(f)
                # 只取已知字段，向前兼容新增/删除字段
                known = {k: v for k, v in data.items() if k in cls.__annotations__}
                obj = cls(**known)
                obj._migrate()
                return obj
            except Exception:
                pass
        return cls()


class DeviceBook:
    """记录用户自定义的设备名称和编号（按序列号持久化到 devices.json）。"""

    def __init__(self):
        self.data = {}   # serial -> {"name": str, "number": int}
        self.load()

    def load(self):
        if os.path.exists(DEVICES_PATH):
            try:
                with open(DEVICES_PATH, "r", encoding="utf-8") as f:
                    self.data = json.load(f)
            except Exception:
                self.data = {}

    def save(self):
        with open(DEVICES_PATH, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)

    def tags(self, serial, default=None):
        """返回标签列表。兼容旧版单个 name 字段。"""
        rec = self.data.get(serial, {})
        if "tags" in rec:
            return list(rec["tags"])
        if rec.get("name"):
            return [rec["name"]]
        return list(default) if default else []

    def name(self, serial, default=""):
        """把标签拼成一行显示。"""
        t = self.tags(serial)
        return "  ".join(t) if t else default

    def number(self, serial, default=0):
        n = self.data.get(serial, {}).get("number")
        return n if n else default

    def set(self, serial, tags=None, number=None):
        rec = self.data.setdefault(serial, {})
        if tags is not None:
            rec["tags"] = list(tags)
            rec.pop("name", None)          # 迁移掉旧字段
        if number is not None:
            rec["number"] = number
        self.save()

    def record_override(self, serial):
        """该设备的独立录制参数(dict)；None 表示用通用设置。"""
        return self.data.get(serial, {}).get("record")

    def set_record_override(self, serial, cfg):
        rec = self.data.setdefault(serial, {})
        if cfg is None:
            rec.pop("record", None)
        else:
            rec["record"] = dict(cfg)
        self.save()
