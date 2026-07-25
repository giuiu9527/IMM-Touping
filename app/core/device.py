# -*- coding: utf-8 -*-
"""设备模型。"""
from dataclasses import dataclass


@dataclass
class Device:
    serial: str                 # adb 序列号（无线设备形如 192.168.1.5:5555）
    state: str = "device"       # device / offline / unauthorized
    model: str = ""             # 手机型号
    name: str = ""              # 显示名（默认为型号，用户可改）

    @property
    def is_wireless(self) -> bool:
        return ":" in self.serial

    @property
    def is_online(self) -> bool:
        return self.state == "device"

    @property
    def display_name(self) -> str:
        return self.name or self.model or self.serial

    @property
    def conn_type(self) -> str:
        return "无线" if self.is_wireless else "USB"
