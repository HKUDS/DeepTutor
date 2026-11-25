---
title: 桌面版本
description: Open DeepTutor 的四个下载文件，以及各版本的数据和日志路径。
quadrant: reference
---

Open DeepTutor 是 macOS 和 Windows 上双击打开的应用。首次启动会安装自带运行时，在本机回环上启动服务，并打开 Web 界面。打包和签名留在仓库的 `apps/desktop/README.md`。

## 下载

每个版本发布四个文件。`<version>` 是该构建自带的 DeepTutor 版本。

| 目标 | 应用 | 下载 |
| --- | --- | --- |
| `macos-arm64` | Apple Silicon 版 Open DeepTutor for MacOS | `Open-DeepTutor-MacOS-Apple-Silicon-v<version>.dmg` |
| `macos-x64` | Intel 版 Open DeepTutor for MacOS | `Open-DeepTutor-MacOS-Intel-v<version>.dmg` |
| `windows-x64` | Open DeepTutor for Windows | `Open-DeepTutor-Windows-v<version>-Setup.exe` 和 `Open-DeepTutor-Windows-v<version>-Portable.zip` |

GitHub Release 同时保留最新文件的无版本别名。安装步骤在[桌面端教程](/zh-cn/get-started/desktop/)。

## 数据与日志

| | macOS | Windows |
| --- | --- | --- |
| 数据 | `~/Library/Application Support/Open DeepTutor/workspace/data` | `%LOCALAPPDATA%\Open DeepTutor\workspace\data` |
| 运行时 | `…/Open DeepTutor/runtimes/<runtime-id>` | `%LOCALAPPDATA%` 下的同一路径 |
| 日志 | `…/Open DeepTutor/logs/runtime.log` | `%LOCALAPPDATA%` 下的同一路径 |

退出应用会停掉它自己启动的服务，不会停掉另外运行的 `deeptutor start`。
