# IMM投屏 — AI / 开发者交接文档

> 给接手本项目的 AI 或开发者。**先读完"核心难点与硬约束",那一节是踩了十几轮才摸清的坑，改动前务必看，否则很容易把已修好的东西改坏。**

---

## 1. 项目是什么

Windows 桌面工具，用于**多台安卓手机的投屏 / 群控 / 录屏**。定位：仿"极限投屏"，非网页、要稳定、要简单、留好扩展接口。给非技术用户用（打包成免安装 exe）。

- 底层引擎：官方 **scrcpy + adb**（放在 `scrcpy/` 目录，含 `scrcpy.exe`、`adb.exe`）。投屏/录制的真正工作全部由 scrcpy 完成，我们**不自己解码视频**。
- 上层：**Python 3.12 + Tkinter + ttkbootstrap（cosmo 亮色主题）+ tkinterdnd2（拖入）**。
- 仓库：https://github.com/loadingkuu/IMM-Touping （账号 loadingkuu，默认分支 master）。
- 用户 GitHub 账号：loadingkuu；本机 gh 已登录（有 repo/workflow 权限）。
- **配套手机端**：AutoX.js 脚本（自动看课 + 触发本软件录制），见下方 **第 10 节**。

> ⚠️ **别再往 PyQt6 迁移**（有人试过，已回退）。教训：PyQt6 的 `createWindowContainer`/`SetParent` 会把 scrcpy 窗口变真子窗口 → **SDL 纯黑**（正是坑#1）；且"子线程里 `QTimer.singleShot`"不触发（QTimer 需所在线程有事件循环），导致接管逻辑不跑、画面飘在软件外。Tkinter 版这些都已趟平，**保持 Tkinter**。

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
- **网格边界**：`grid_frame` 必须 `grid_propagate(False)`，不能被内部格子反向撑宽；每次定位原生窗口还要经 `_visible_video_rect` 校验，格子不完全在网格可视区则隐藏窗口。owned window 不会被 Tk 自动裁剪，这是防止画面越界的必要保护。
- **偶发黑屏**：scrcpy 在屏外/被遮挡时 SDL 会暂停渲染，搬进来后不一定立刻重绘。对策：`_nudge_overlay` 改 1px 尺寸多次触发 WM_SIZE 唤醒重绘（群控 `_attach` 里 300~3200ms 分 5 次）。
- **独立投屏**：独立投屏已切回原生 scrcpy 窗口（`launch_solo`），不进行 Win32 嵌套/`set_owner`。启动时需带 `creationflags=_NO_WINDOW` 隐藏黑色的 CMD 控制台，并加上 `--audio-source=playback` 解决默认 `output` 衰减 -33dB 导致声音过小的坑。
- **独立投屏互斥**：产品规则为同一时间只保留一个独立投屏。`App.solo_mirror` 启动新设备前会调用 `ScrcpyManager.stop_other_solos` 关闭旧的独立 scrcpy 进程。

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
- `subfolder_by_device`（默认 True）：开启后视频将自动按机器编码/编号分类落盘到各自独立子目录（如 `records/01-标签/`），防止多设备录像混杂。
- `devices.json`（`config.DeviceBook`）：每设备的标签(多个)、编号、录制覆盖(record)。
- 都存在 `config.ROOT`（源码=项目目录，打包=exe 目录）。

## 7.5 本地控制 API（手机 autox.js 自动录制，v0.1.18 新增）

给手机端脚本（autox.js）一个"喊话"电脑的通道，实现**自动开录/停录/OCR后改名归档**。核心在 `app/core/apiserver.py`，接进 `App`（`main_window.py`）。

- **连通**：`adb reverse`。`_sync` 里对每台在线设备起后台线程调 `api.sync(online)`；`ApiServer` 给每台设备分配一个电脑侧唯一端口并执行 `adb -s <serial> reverse tcp:8300 tcp:<pc端口>`。手机脚本永远访问 `127.0.0.1:8300`（**所有手机同一份、写死、零配置**），电脑按"请求到达哪个 pc 端口"反查是哪台设备 → **无需手机上报身份，无伪造问题**。每台设备一个 `ThreadingHTTPServer`（绑 127.0.0.1，只有本机+被 reverse 的那台手机能访问）。
- **接口**（GET/POST 均可，参数走 query 或 body）：`/ping` `/status`、`/record/start?name=`、`/record/stop?name=`、`/record/rename?name=&folder=&src=`。全部返回 JSON `{ok,...}`。`dispatch` 在 `App._api_dispatch`。
- **命名**：手机端**直接读无障碍节点拿课名，无需 OCR**。正常路径在**进课前**读目录页列表项 `id=tv_title`（如 `031.…常见公式 .sz`，去掉尾部 ` .sz`），开录时 `start?name=真名` 一步到位、**不留临时名**；读不到才退回结束态读播放页顶栏 `id=title`，`stop?name=` 触发 **stop+改名一步到位**（`api_stop_record` 内部调 `api_rename`）。都读不到才落成临时名 `未命名-NN-时间`。`/record/rename` 保留供手动/归档到子文件夹用（`api_rename` 带去重、路径消毒、跨盘兜底）。当前录制文件按 serial 记在 `self._rec_files`（手动录制也记，改名接口对二者通用）。
- **线程模型（重要）**：`api_*` 方法跑在 ApiServer 后台线程，只做非 UI 活（起停 scrcpy 子进程、移动文件、读写 `recording/_rec_*`）；动 UI 一律 `root.after(0,...)` 调回主线程（与 `_poll` 既有写法一致）。停录 `stop_record` 会阻塞到干净收尾，放在后台线程里不卡 UI。
- **开关**：`Settings.api_enabled/api_phone_port(8300)/api_pc_port(8300)`。关掉后 `sync` 会拆掉所有 reverse+监听。`_on_close` 里 `api.stop_all()`。
- **手机端**（仓库 `gitee.com/iuiu9527/sz` 的 `autox_ui.js`）：`recStart()/recStop()/recRename()` 三个封装；主循环 `netcardProcessor` 里"进入本节课横屏播放→recStart"、"本节课判定播完→recStop（在 finishCourse 前）"，`endProgram/restartCycle` 兜底停录。网络异常全吞，绝不影响看课主流程。改这个文件要 push 到 Gitee 才对所有手机生效（见其项目 README）。

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
| 多设备 APK 并行安装 / 操作日志名称 | `app/ui/actions.py`（安装日志显示“编号 + 标签”） |
| 手机端控制 API（自动录制/改名） | `app/core/apiserver.py` + `App._api_dispatch/api_*`（见 7.5） |
| 按设备编号/标签分文件夹存录像 | `App._device_records_dir`（`settings.subfolder_by_device`，默认开；设置→存储可关） |
| 配套手机端 autox.js 脚本 | 见第 10 节 |

---

## 10. 配套手机端项目：AutoX.js 自动看课脚本（"auto 库"）

本软件有一个**配套的手机端项目**：跑在安卓上的 AutoX.js 脚本，自动化操作 App「深造播放器」自动看课，并在**进/出每节课时通过本软件的控制 API 触发录制**。两个项目一个在电脑（本仓库）、一个在手机（下面的 Gitee 仓库），靠 `adb reverse` 联动（见 7.5）。

### 10.1 仓库与文件
- **仓库**：Gitee **私有** `https://gitee.com/iuiu9527/sz`（分支 `master`）。本机可带令牌克隆/推送（令牌是用户私有，**不要写进任何公开处**）。
- **主文件 `autox_ui.js`**：全部逻辑 + 设置界面。**权威源**，手机实际拉取的就是它。
- **热更新加载器 `loader.js`**：打进 APK 当 main.js；启动时用令牌走 Gitee API 拉 `autox_ui.js` 并 `eval` 运行，离线用本地缓存。**改一处=所有手机下次开 App 自动更新，不用重打包。**
- **版本号**：`autox_ui.js` 顶部 `SCRIPT_VERSION`，显示在界面顶部状态栏右侧。**每次改脚本务必 +**，用户靠它确认手机是否拉到最新。
- 另有 `项目说明_README.md`（讲自动看课本身的坑）、`更新日志.md`。

### 10.2 更新流程（接手 AI 照做）
1. 克隆 `iuiu9527/sz`（带令牌），编辑 `autox_ui.js`。
2. **把 `SCRIPT_VERSION` 往上加一位**（如 `v1.0.0 · 日期-当日第N次`）。
3. `git commit`（作者用 `iuiu9527 <iuiu9527@gitee.com>`）→ `git push origin master`。
4. 手机重开 loader 版 App 即拉到最新（顶部版本号可核对）。
- ⚠️ 仓库私有的原因：`autox_ui.js` 的 `DEFAULTS` 含**明文邮箱授权码/PushPlus 令牌**，绝不能放公开仓库，也别复述这些值。

### 10.3 录制联动（脚本里怎么调本软件）—— 与 7.5 对应
- 手机脚本封装了 `recCall/recStart/recStop/recRename`（网络异常全吞，绝不影响看课主流程）。
- 主循环 `netcardProcessor`：进课前在目录页读 `id("tv_title")` 课名 → 进课横屏播放时 `recStart`（用真名直接命名，无需临时名）→ 本节课判定播完、`finishCourse` 前 `recStop`；`endProgram/restartCycle` 兜底停录。
- **课名直读无障碍节点，无需 OCR**：目录页列表项 `id=tv_title`（如 `031.…公式 .sz`，去掉尾部 ` .sz`），退回播放页顶栏 `id=title`。
- 电脑侧对应接口/命名/落盘见 **7.5**；录像默认按设备落到 `records/编号-标签/`（`subfolder_by_device`）。

### 10.4 深造 App 关键控件（排查用）
- 包名 `com.supermedia.mediaplayer`。课名节点 `id=title`(播放页顶栏) / `id=tv_title`(目录列表项)。
- 结束判定：`rl_control + start 且无 backward_15`（暂停时 backward_15 仍在，靠它区分"暂停/播完"，别删这个复检）。默认结束确认等待 `endWaitSec`=5 秒（老版是 600 秒=10 分钟，已改）。

---

**一句话总结给接手的 AI**：这是个"Python(Tkinter) 壳 + scrcpy 内核 + Win32 贴窗口"的多设备投屏工具，外加一个手机端 AutoX.js 脚本（Gitee `iuiu9527/sz`）自动看课并经 `adb reverse` 触发录制。90% 的坑都在"如何把 scrcpy 原生窗口稳定地嵌进软件、别黑屏别崩溃别错位"和"scrcpy 参数（音频源/编码/鼠标）"上——改这两块前务必先看第 4 节；**别再迁 PyQt6**（见第 1 节警告）。手机端联动看 7.5 + 第 10 节。
