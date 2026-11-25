---
title: 桌面端快速上手
description: 安装 Open DeepTutor，接上一个语言模型，发出第一条消息。
quadrant: tutorial
---

Open DeepTutor 是桌面应用。第一次打开时，它会解开自带的 Python 和 Node 运行时，在这台电脑上启动服务，然后显示工作区。你不用自己再装 Python、Node 或源码。

## 1. 下载这台电脑对应的应用

| 这台电脑 | 下载 |
| --- | --- |
| Apple 芯片的 Mac | [macOS（Apple 芯片）版 Open DeepTutor](https://github.com/HKUDS/DeepTutor/releases/latest/download/Open-DeepTutor-MacOS-Apple-Silicon.dmg) |
| Intel 芯片的 Mac | [macOS（Intel）版 Open DeepTutor](https://github.com/HKUDS/DeepTutor/releases/latest/download/Open-DeepTutor-MacOS-Intel.dmg) |
| Windows | [Windows 版 Open DeepTutor](https://github.com/HKUDS/DeepTutor/releases/latest/download/Open-DeepTutor-Windows-Setup.exe) |

打开刚下载的文件。在 Mac 上，把应用拖进“应用程序”。在 Windows 上，把安装向导走完。安装包没有签名，SmartScreen 会让你确认；选择继续运行。完成后，应用程序列表里能看到 **Open DeepTutor**。

Windows 便携 ZIP 在[同一个 Release](https://github.com/HKUDS/DeepTutor/releases/latest) 上。这篇教程用的是上面的安装包。

## 2. 等到工作区打开

启动 **Open DeepTutor**。第一次启动会先解开自带运行时，再打开 DeepTutor 窗口。侧栏里能看到主页时，就可以继续。如果过了几分钟还停在启动画面，退出再打开一次。

## 3. 接上一个语言模型

语言模型负责写回复。提供方是托管这个模型的厂商，或者你本机已经在跑的服务。这一步是让 DeepTutor 有一个能调用的模型。

1. 打开 **设置 → 模型与服务**。
2. 添加一个语言模型 profile。用你已经有的密钥，或者一个已经在运行的本地服务。profile 就是这份连接：哪个提供方、哪个模型、密钥或地址。
3. 选择 **Test**。测试通过，说明这个 profile 能完成一次最小调用。
4. 选择 **Apply**。这个 profile 已保存，下一条消息可以用它。

嵌入、搜索和语音可以以后再加。[提供方与模型](/zh-cn/get-started/providers/) 列出这些服务和提供方目录。

## 4. 发出一条消息

打开 **主页 → 对话**。提一个具体问题，例如：“用一段话解释采样定理，然后给我两道题。”

对话里出现回复，这篇教程就完成了。

## 数据放在哪里

笔记、对话和设置都留在应用自己的工作区目录里。换一个新版本的应用，不会换掉这个目录。

| 系统 | 工作区数据 |
| --- | --- |
| macOS | `~/Library/Application Support/Open DeepTutor/workspace/data` |
| Windows | `%LOCALAPPDATA%\Open DeepTutor\workspace\data` |

## 下一步

- [串起一次完整学习](/zh-cn/learning-workspace/) — 一个主题、一份材料、一个问题。
- [更新日志](/zh-cn/get-started/changelog/) — 替换旧版桌面应用前先看这里。v1.7.4 更换了运行时签名密钥，需要安装这个版本的应用本身，而不是把更新导入旧版本。
