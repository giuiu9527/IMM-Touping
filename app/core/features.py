# -*- coding: utf-8 -*-
"""功能注册表 —— 为“以后加功能”预留的扩展点。

新功能只要写一个函数并 @register 注册，主界面工具栏会自动出现按钮，
不用改主窗口代码。函数签名统一为 fn(ctx)，ctx 见 main_window.FeatureContext。
"""
from dataclasses import dataclass, field
from typing import Callable, List


@dataclass
class Feature:
    id: str
    label: str          # 按钮文字
    handler: Callable    # fn(ctx)
    order: int = 100     # 排序，越小越靠前


_REGISTRY: List[Feature] = []


def register(id: str, label: str, order: int = 100):
    def deco(fn):
        _REGISTRY.append(Feature(id=id, label=label, handler=fn, order=order))
        return fn
    return deco


def all_features() -> List[Feature]:
    return sorted(_REGISTRY, key=lambda f: f.order)
