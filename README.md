# IMM投屏

多台安卓手机投屏 / 群控 / 录屏 控制面板。底层用官方 **scrcpy + adb**（稳定成熟），
上层是 Python + ttkbootstrap 现代界面，不依赖网页。

当前版本：**v0.1.26**

## 功能

- **群控网格**：手机连上电脑自动显示在右侧网格，实时画面、可直接鼠标控制；窗口缩放和 DPI 重算时不会将画面显示到软件边界外
- **独立投屏**：单台大窗口，顶部带 返回 / 桌面 / 多任务手势按钮；打开新设备时会自动关闭上一台独立投屏，点击已打开设备会将其置于最前
- **多标签 + 编号**：每台设备可挂多个标签（单击置顶激活），自定义编号
- **录屏**：每个格子独立录制按钮，mp4/mkv、可选编码器/码率/帧率、录声音；停止时干净收尾保证可播放
- **每设备独立录制设置**：某台设了就用自己的，没设跟随通用设置
- **发送文件 / 安装 APK**：支持选择和拖入两种方式；APK 会同时安装到所选设备，日志显示自定义编号与标签
- **Adb 命令**：对勾选设备批量执行
- **设备右键菜单**：独立投屏 / 改标签 / 录制设置 / 设备信息 / 重启手机
- **在线更新**：自动检查 GitHub 最新版本

## 运行

需要 Python 3.10+。

```bash
pip install -r requirements.txt
```

然后把官方 scrcpy（Windows 版）解压到项目下的 `scrcpy/` 目录（内含 `scrcpy.exe`、`adb.exe`），
双击 **`run.bat`** 或运行：

```bash
python -m app.main
```

> 发布页的 zip 已包含 scrcpy，下载解压即用，无需另配。

## 免安装版（推荐普通用户）

到 [Releases](https://github.com/giuiu9527/IMM-Touping/releases) 下载
`IMM-Touping-vX.Y.Z-portable.zip`，解压后双击 `IMM-Touping.exe` 即可，**无需装 Python**。
（exe 必须和同目录的 `scrcpy/` 一起，不要单独移动。）

## 自己打包 exe

```bash
pip install pyinstaller
python -m PyInstaller --noconfirm --clean --onefile --windowed --name IMM-Touping \
  --collect-all tkinterdnd2 --collect-all ttkbootstrap imm.py
```

产物在 `dist/IMM-Touping.exe`，把 `scrcpy/` 拷到它旁边即可运行。

## 手机准备

1. 开启「开发者选项 → USB 调试」
2. USB 连接电脑，手机弹授权时点「允许」
3. 软件里点「刷新」即可看到设备

## 录制说明

- 默认 **h264 + mkv + opus**：opus 比 aac 明显更大声（和 escrcpy 一致），mkv+h264 剪辑软件（含 LosslessCut）也能直接打开
- 若一定要 mp4，音频请选 aac（opus 不适合 mp4，且 aac 偏小声）
- h265 体积更小但兼容差
- 「设置→录制」可点「重新检测」列出手机实际支持的硬件/软件编码器
- 录屏默认存软件目录 `records/`，可在「设置→存储」自定义位置和命名模板

## 目录结构

```
app/
├── config.py            # 参数、版本、预设
├── core/                # adb / scrcpy / 嵌入 / 录制 / 更新
└── ui/                  # 主界面 / 设置 / 工具
scrcpy/                  # 投屏引擎（发布包内含）
```

## 致谢

- [scrcpy](https://github.com/Genymobile/scrcpy) — 投屏 / 录制内核
- [escrcpy](https://github.com/viarotel-org/escrcpy) — 录制参数设计参考
