# -*- coding: utf-8 -*-
"""adb 命令封装。

统一在这里调用 adb.exe，其它模块不要直接拼 adb 命令，
方便以后统一加日志、超时、错误处理。
"""
import subprocess
from typing import List, Tuple

from .device import Device

# Windows 下隐藏子进程黑窗
_NO_WINDOW = 0x08000000


class Adb:
    def __init__(self, adb_exe: str):
        self.adb_exe = adb_exe

    # ---- 内部 ----
    def _run(self, args: List[str], serial: str = None, timeout: int = 30) -> Tuple[int, str]:
        cmd = [self.adb_exe]
        if serial:
            cmd += ["-s", serial]
        cmd += args
        try:
            p = subprocess.run(
                cmd, capture_output=True, text=True, encoding="utf-8",
                errors="replace", timeout=timeout, creationflags=_NO_WINDOW,
            )
            return p.returncode, (p.stdout or "") + (p.stderr or "")
        except subprocess.TimeoutExpired:
            return -1, "超时"
        except Exception as e:  # pragma: no cover
            return -1, str(e)

    # ---- 对外接口 ----
    def start_server(self):
        self._run(["start-server"], timeout=15)

    def list_devices(self) -> List[Device]:
        code, out = self._run(["devices"])
        devices = []
        for line in out.splitlines()[1:]:          # 跳过 "List of devices attached"
            line = line.strip()
            if not line or "\t" not in line:
                continue
            serial, state = line.split("\t")[:2]
            devices.append(Device(serial=serial.strip(), state=state.strip()))
        return devices

    def get_model(self, serial: str) -> str:
        code, out = self._run(["shell", "getprop", "ro.product.model"], serial=serial, timeout=8)
        return out.strip() if code == 0 else ""

    def install(self, serial: str, apk_path: str) -> Tuple[bool, str]:
        code, out = self._run(["install", "-r", apk_path], serial=serial, timeout=180)
        ok = code == 0 and "Success" in out
        return ok, out.strip()

    def push(self, serial: str, local_path: str, remote_dir: str = "/sdcard/Download/") -> Tuple[bool, str]:
        code, out = self._run(["push", local_path, remote_dir], serial=serial, timeout=300)
        return code == 0, out.strip()

    def connect(self, host_port: str) -> Tuple[bool, str]:
        code, out = self._run(["connect", host_port], timeout=15)
        return "connected" in out.lower(), out.strip()

    def shell(self, serial: str, command: str) -> Tuple[bool, str]:
        code, out = self._run(["shell", command], serial=serial, timeout=30)
        return code == 0, out.strip()

    def reboot(self, serial: str) -> Tuple[bool, str]:
        code, out = self._run(["reboot"], serial=serial, timeout=15)
        return code == 0, out.strip()

    def getprops(self, serial: str, keys) -> dict:
        """批量读取 getprop 值。"""
        result = {}
        for k in keys:
            ok, out = self.shell(serial, f"getprop {k}")
            result[k] = out.strip() if ok else ""
        return result
