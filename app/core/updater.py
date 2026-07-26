# -*- coding: utf-8 -*-
"""在线更新：检查 GitHub Release、下载新版、自动替换并重启。

自更新原理（Windows 下运行中的 exe 不能覆盖自己）：
下载 portable zip -> 解压到临时目录 -> 生成一个后台 bat ->
bat 等主程序退出后，用新文件覆盖安装目录，再启动新 exe。
"""
import os
import json
import zipfile
import tempfile
import subprocess
import urllib.request

_UA = {"User-Agent": "IMM-Touping-Updater", "Accept": "application/vnd.github+json"}
_NEW_CONSOLE = 0x00000010 | 0x00000200   # CREATE_NEW_CONSOLE | CREATE_NEW_PROCESS_GROUP


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
    """有更新则返回 {version, html_url, asset_url}；否则 None。asset_url 为免安装 zip 直链。"""
    url = f"https://api.github.com/repos/{owner}/{repo}/releases/latest"
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=_UA), timeout=timeout) as r:
            data = json.load(r)
    except Exception:
        return None
    tag = data.get("tag_name", "")
    if not (tag and _is_newer(tag, current_version)):
        return None
    asset_url = None
    for a in data.get("assets", []):
        name = a.get("name", "").lower()
        if name.endswith(".zip") and "portable" in name:
            asset_url = a.get("browser_download_url")
            break
    return {
        "version": tag.lstrip("vV"),
        "html_url": data.get("html_url", f"https://github.com/{owner}/{repo}/releases"),
        "asset_url": asset_url,
    }


def download(url, dest_path, progress_cb=None, timeout=60):
    """下载到 dest_path。progress_cb(done, total) 回调进度。"""
    req = urllib.request.Request(url, headers={"User-Agent": "IMM-Touping-Updater"})
    with urllib.request.urlopen(req, timeout=timeout) as r, open(dest_path, "wb") as f:
        total = int(r.headers.get("Content-Length", 0) or 0)
        done = 0
        while True:
            chunk = r.read(65536)
            if not chunk:
                break
            f.write(chunk)
            done += len(chunk)
            if progress_cb:
                progress_cb(done, total)


def apply_update(zip_path, install_dir, exe_name):
    """解压更新包并启动后台替换脚本；调用后应立即退出本程序。"""
    staging = tempfile.mkdtemp(prefix="imm_upd_")
    with zipfile.ZipFile(zip_path) as z:
        z.extractall(staging)
    # 定位含 exe 的源目录（zip 里一般是单个顶层文件夹）
    src = staging
    subdirs = [os.path.join(staging, e) for e in os.listdir(staging)
               if os.path.isdir(os.path.join(staging, e))]
    if len(subdirs) == 1 and os.path.exists(os.path.join(subdirs[0], exe_name)):
        src = subdirs[0]

    bat_path = os.path.join(tempfile.gettempdir(), "imm_apply_update.bat")
    bat = f"""@echo off
title 正在更新 IMM投屏
echo.
echo    正在更新到新版本，请稍候...
echo    完成后会自动重启，请勿关闭本窗口。
echo.
ping -n 3 127.0.0.1 >nul
taskkill /F /IM "{exe_name}" >nul 2>&1
ping -n 2 127.0.0.1 >nul
xcopy /E /Y /I "{src}\\*" "{install_dir}\\" >nul
start "" "{os.path.join(install_dir, exe_name)}"
rmdir /S /Q "{staging}" >nul 2>&1
(goto) 2>nul & del "%~f0"
"""
    with open(bat_path, "w", encoding="gbk", errors="replace") as f:
        f.write(bat)
    subprocess.Popen(["cmd", "/c", bat_path], creationflags=_NEW_CONSOLE, close_fds=True)
