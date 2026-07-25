# -*- coding: utf-8 -*-
"""在线更新检查：查询 GitHub 最新 Release，比较版本号。"""
import json
import urllib.request


def _ver_tuple(v):
    v = (v or "").strip().lstrip("vV")
    parts = []
    for x in v.split("."):
        num = "".join(ch for ch in x if ch.isdigit())
        parts.append(int(num) if num else 0)
    return tuple(parts)


def _is_newer(remote, local):
    return _ver_tuple(remote) > _ver_tuple(local)


def check_update(owner, repo, current_version, timeout=8):
    """返回 (最新版本号, 下载页URL) 如果有更新；否则返回 None。网络异常也返回 None。"""
    url = f"https://api.github.com/repos/{owner}/{repo}/releases/latest"
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "IMM-Touping-Updater",
            "Accept": "application/vnd.github+json",
        })
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.load(r)
    except Exception:
        return None
    tag = data.get("tag_name", "")
    if tag and _is_newer(tag, current_version):
        return tag.lstrip("vV"), data.get("html_url", f"https://github.com/{owner}/{repo}/releases")
    return None
