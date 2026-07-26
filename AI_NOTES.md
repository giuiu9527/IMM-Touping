# IMM投屏 — AI / 开发者交接文档

> 给接手本项目的 AI 或开发者。**先读完"核心难点与硬约束",那一节是踩了十几轮才摸清的坑，改动前务必看，否则很容易把已修好的东西改坏。**

---

## 1. 项目是什么

Windows 桌面工具，用于**多台安卓手机的投屏 / 群控 / 录屏**。定位：仿"极限投屏"，非网页、要稳定、要简单、留好扩展接口。给非技术用户用（打包成免安装 exe）。

- 底层引擎：官方 **scrcpy + adb**（放在 `scrcpy/` 目录，含 `scrcpy.exe`、`adb.exe`）。投屏/录制的真正工作全部由 scrcpy 完成，我们**不自己解码视频**。
- 上层：**Python 3.12 + Tkinter + ttkbootstrap（cosmo 亮色主题）+ tkinterdnd2（拖入）**。
- 仓库：https://github.com/loadingkuu/IMM-Touping （账号 loadingkuu，默认分支 master）。
- 用户 GitHub 账号：loadingkuu；本机 gh 已登录（有 repo/workflow 权限）。

## 2. 运行

源码运行（开发）：
```bash
pip install -r requirements.txt   # ttkbootstrap, tkinterdnd2
python -m app.main
```
手机需开 USB 调试并授权。scrcpy 目录必须存在。

## 3. 目录结构与分层

```
app/
├── main.py             # 入口。开机先 _enable_dpi()（见坑#1），再 App().run()
├── config.py           # 全部配置/预设/版本号/仓库信息 + Settings/DeviceBook 持久化
├── core/
│   ├── adb.py          # adb 封装：设备列表/装apk/推文件/shell/reboot/分辨率/编码器
│   ├── device.py       # Device 数据类
│   ├── scrcpy.py       # 投屏进程管理：群控嵌入/独立嵌入/录制，命令拼装
│   ├── embed.py        # Win32(ctypes)：找窗口/set_owner/定位/批量定位/提到最前
│   ├── updater.py      # 在线更新：查Release/下载/生成替换脚本
│   └── features.py     # 功能注册表（@register 加按钮，主界面自动出）
└── ui/
    ├── main_window.py  # 主窗口 App + SoloWindow + UpdateDialog + EditDeviceDialog
    ├── settings_dialog.py  # 投屏设置 + 每设备录制设置(DeviceRecordDialog) + 录制字段构建器
    ├── actions.py      # 发送文件/安装APK/Adb命令（注册的功能）
    └── util.py         # center_window / bind_recursive
scrcpy/                 # 引擎（.gitignore 排除，发布包里另附）
imm.py                  # PyInstaller 打包入口（=python -m app.main）
settings.json/devices.json/records/  # 运行时生成（gitignore）
```

**扩展新功能**：在 `app/ui/actions.py` 写函数并 `@register("id","按钮名",order=N)`，主界面工具栏自动出现按钮，handler 收到 `app`（能拿 `app.selected_devices()`/`app.adb`/`app.log(...)`）。可调参数加进 `config.Settings`（自动存 settings.json）。

---

## 4. ⚠️ 核心难点与硬约束（最重要，改动前必读）

### 坑#1 —— 群控/独立"把手机画面嵌进软件网格"的实现方式
- 群控里每个手机画面是一个**独立的原生 scrcpy 窗口**，用 Win32 **`SetWindowLongPtr(GWLP_HWNDPARENT)` 把它设成主窗口/独立窗口的"从属窗口(owned window)"**（见 `embed.set_owner`），再用 `SetWindowPos` 定位到格子上。**绝不能用 `SetParent` 变真子窗口** —— 那样 SDL 渲染会变纯黑。
- **DPI**：用 `SetProcessDpiAwarenessContext(-4)`（PerMonitorV2，见 `main.py._enable_dpi`）。PMv2 能正确托管低感知的 scrcpy 子窗口（自动缩放，不销毁）。**别用老的 `SetProcessDpiAwareness(1或2)`**——那会把被从属化的 scrcpy 窗口几秒内杀掉导致黑屏。这是 4K/高缩放屏字体清晰的前提。
- **接管时机**：找到 scrcpy 窗口后要**等一会儿再 set_owner**（太早接管会崩），且多台设备要**错开逐台启动**（`_sync` 里 `after(i*1800, ...)`），同时启动会互相抢占崩溃。
- **格子尺寸必须按手机真实屏幕比例**：scrcpy 会把窗口自动调成手机画面比例，若格子比例不对就会错位/留黑边。见 `_tile_dims`/`_ratios`（用 `adb.get_resolution`）。
- **偶发黑屏**：scrcpy 在屏外/被遮挡时 SDL 会暂停渲染，搬进来后不一定立刻重绘。对策：`_nudge_overlay` 改 1px 尺寸多次触发 WM_SIZE 唤醒重绘（群控 `_attach` 里 300~3200ms 分 5 次）。
- **独立投屏**：独立投屏已切回原生 scrcpy 窗口（`launch_solo`），不进行 Win32 嵌套/`set_owner`，彻底解决部分设备挪动窗口黑屏的问题，渲染最稳定流畅。

### 坑#2 —— 录制声音过小（花了两版才定位）
- **不是编码问题**（aac/opus 都试过）。真凶是**音频源**：scrcpy 默认 `--audio-source=output`(REMOTE_SUBMIX) 在部分机型(如 OnePlus LE2100)被衰减约 **33dB**（实测 RMS -59 vs escrcpy -26 dBFS）。
- **改用 `--audio-source=playback`(AudioPlaybackCapture)** 才和 escrcpy 一样响。已做成 `record_audio_source` 设置，默认 playback。
- 顺带：opus 比 aac 稍响；opus 需 mkv 容器。默认 h264+mkv+opus+playback。
- 排查手段：`pip install av numpy`，PyAV 解码测 RMS/峰值（**仅分析用；打包时务必 `--exclude-module numpy --exclude-module av`，否则 exe 白涨 10MB**）。

### 坑#3 —— 录制的干净收尾
- 录制 = scrcpy `--record 文件`（escrcpy 底层同款）。停止**必须发 WM_CLOSE**让 scrcpy 自己收尾写索引（mp4 的 moov）；**硬杀进程会损坏文件**。见 `scrcpy.stop_record`（找窗口→WM_CLOSE→等退出→兜底 terminate）。
- 每设备可有独立录制参数（存 devices.json 的 record 字段，`book.record_override`），无则用通用 `settings.record_config()`。命名模板 `Recording-{num2}-{firsttag}-{time}`，占位符见 `_record_path`。

### 坑#4 —— 设备编号
- 编号要**连续不重复**：自定义了编号的占它的号，其余按序填补空缺（`_sync` 里的分配算法 → `self._numbers`）。**列表、群控网格(`_reflow`)、格子标题、文件名、错开启动都必须用同一套 `_display_number`/`_numbers`**（曾经只改了列表没改网格，导致网格乱序）。显示补零两位。

### 坑#5 —— 设备列表定时闪烁
- 轮询(每4s)不要无脑重建列表。`_sync` 用**内容签名**比较，只有设备/状态/编号/标签/录制变化时才 `_render_list`（见 `_list_sig`）。型号查询也要缓存(`_models`)减少 adb 调用。

### 坑#6 —— 鼠标/声音的群控体验
- 群控加 **`--no-audio`**（多台一起放声音很吵）。
- 群控/独立加 **`--no-mouse-hover`**（鼠标划过不误操作，必须点击才生效）。见 `_build_base` 和 `start_embed_process`。

### 坑#7 —— 拖动窗口不流畅
- 根因是"贴原生窗口"架构：Tk 界面和 N 个原生 scrcpy 窗口不同步。**不是 Python 的锅**。
- 已优化：`embed.batch_place` 用 `DeferWindowPos` 一次性原子移动所有窗口；主窗口 `<Configure>` 做防抖(`_on_configure`→`after(16,...)`)。
- **要真正丝滑得换架构**：不贴原生窗口，而是自己接 scrcpy 视频流、解码 H.264、渲染进软件画布。工作量大，未做。

---

## 5. 打包与发布流程

**打包（PyInstaller，onedir）**：
```bash
pip install pyinstaller
python -m PyInstaller --noconfirm --clean --onedir --windowed --name IMM-Touping \
  --collect-all tkinterdnd2 --collect-all ttkbootstrap \
  --exclude-module numpy --exclude-module av imm.py
cp -r scrcpy dist/IMM-Touping/scrcpy      # 把引擎放进去
```
- **必须 onedir，不要 onefile**：onefile 每次启动解压 DLL 到临时 `_MEI`，更新快速重启时会撞车 → "Failed to load Python DLL"。onedir 无此问题、启动更快。
- `config.ROOT` 打包后 = `dirname(sys.executable)`（exe 旁），scrcpy/settings.json/records 都放那。

**发布**：升 `config.APP_VERSION` → 提交推送 → 打包 → 打 zip（**顶层目录名用纯英文** `IMM-Touping-vX.Y.Z`，中文会干扰更新时 xcopy；排除 settings/devices/debug）→ `gh release create vX.Y.Z zip --notes-file 文件`。
- **gh 的 --notes 别在 bash 里用反引号/`$()`**（会被 shell 执行），用 `--notes-file` 或注意转义。
- **Release 资产名必须含 "portable" 且 ASCII**：updater 靠名字里的 "portable" 匹配下载直链；中文名会被 GitHub 吞成 `IMM.-...zip`。

## 6. 在线更新机制（updater.py）

- 启动静默检查 + 左上「检查更新」。`check_update` 查 releases/latest 比版本，返回 portable zip 直链。
- 打包版走 `UpdateDialog`（进度条）下载 → `apply_update`：解压到临时目录 → 生成后台 bat → `os._exit(0)` 退出本程序。
- **bat 关键点（v0.1.6 修）**：**用 `taskkill /F` 强制结束旧进程再 xcopy 覆盖**（别用"循环等进程退出"，onefile 双进程会死等卡黑框）；`CREATE_NEW_CONSOLE` 显示"正在更新"；`(goto) 2>nul & del "%~f0"` 自删。
- **注意**：更新逻辑本身有 bug 的旧版无法自更新到修复版，需让用户手动下载一次；打包结构变化(onefile↔onedir)那一版也建议手动下载一次。

## 7. 配置与持久化

- `settings.json`（`config.Settings`）：投屏/录制/存储/窗口记忆等。`load()` 只取已知字段（向前兼容），并跑 `_migrate()`（一次性迁移，如旧 aac→opus）。加新字段直接在 dataclass 加默认值即可。
- `devices.json`（`config.DeviceBook`）：每设备的标签(多个)、编号、录制覆盖(record)。
- 都存在 `config.ROOT`（源码=项目目录，打包=exe 目录）。

## 8. 已知限制 / 可做的改进

- 拖动流畅度天花板在"贴原生窗口"架构（见坑#7）。想彻底解决要做"解码进画布"。
- 横屏手机在竖屏独立窗口里会有上下黑边（窗口按物理比例，横屏内容需手动拖窗口）。
- 偶发个别设备黑屏已用多次重绘唤醒缓解，但极端慢的设备仍可能短暂黑。
- 自动更新目前是"下载整包覆盖"，没有增量。
- 录制音频源 `playback` 少数 App 会 opt-out(捕获不到)，可切 `output`。

## 9. 关键文件速查

| 需求 | 看哪 |
|---|---|
| 改参数/预设/版本号/仓库 | `app/config.py` |
| 投屏/录制命令拼装 | `app/core/scrcpy.py` |
| 嵌入/定位/DPI 相关 Win32 | `app/core/embed.py` + `main.py._enable_dpi` |
| 主界面/群控网格/独立窗口/编号/防闪/更新弹窗 | `app/ui/main_window.py` |
| 设置面板/每设备录制/编码器检测 | `app/ui/settings_dialog.py` |
| 在线更新 | `app/core/updater.py` |
| 加新功能按钮 | `app/ui/actions.py` + `features.py` |

---

**一句话总结给接手的 AI**：这是个"Python 壳 + scrcpy 内核 + Win32 贴窗口"的多设备投屏工具。90% 的坑都在"如何把 scrcpy 原生窗口稳定地嵌进软件、别黑屏别崩溃别错位"和"scrcpy 参数（音频源/编码/鼠标）"上。改这两块前，务必先看第 4 节。
