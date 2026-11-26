---
title: 更新日志
description: DeepTutor 最近五个版本里，使用者能直接看到的变化。
quadrant: reference
---

下面只记录使用 DeepTutor 的人能注意到的变化。名称和日期以 [`assets/releases/`](https://github.com/HKUDS/DeepTutor/tree/dev/assets/releases) 为准。完整说明和更早版本在 [GitHub Releases](https://github.com/HKUDS/DeepTutor/releases)。

## v1.7.4 — 2026-11-20

macOS 和 Windows 的桌面安全更新。应用用一把新的公钥校验运行时更新。如果本机保存的运行时仍由已停用的密钥签名，应用会先备份工作区，再安装这个版本自带的、已通过校验的运行时。

请安装 v1.7.4 应用本身。更早的桌面版本仍信任已停用的密钥。[发布说明](https://github.com/HKUDS/DeepTutor/blob/v1.7.4/assets/releases/ver1-7-4.md) · [v1.7.4](https://github.com/HKUDS/DeepTutor/releases/tag/v1.7.4)

## v1.7.3 — 2026-11-16

阅读增加连续缩放，批注更稳定。书籍编辑可以在应用前先看 diff。搜索新增 DeepSeek、SpecStream 和 SearchApi。已配置的 Agent Client Protocol 进程可以作为本地子智能体被咨询。练习和精通之路保留更多上下文。安装更新的桌面应用时，会试用它自带的核心，并可以回滚。

[Release](https://github.com/HKUDS/DeepTutor/releases/tag/v1.7.3)

## v1.7.2 — 2026-11-06

GitHub Release 同时提供 Apple 芯片和 Intel 的 Mac 安装包，以及 Windows 安装包和便携 ZIP。可以朗读选中的文字。模型配置、精通之路、检索和更新更可靠。

[Release](https://github.com/HKUDS/DeepTutor/releases/tag/v1.7.2)

## v1.7.1 — 2026-11-01

Open DeepTutor 桌面预览首次覆盖 Apple 芯片、Intel 和 Windows。增加更多界面语言、密码修改、经过检查的视频课，以及更多提供方。已有运行时数据留在原地。

[Release](https://github.com/HKUDS/DeepTutor/releases/tag/v1.7.1)

## v1.7.0 — 2026-10-28

模块化安装：`deeptutor[full]` 是 Web 应用，`deeptutor` 是核心 CLI 和 SDK。这一版带来学习工作区、带 Dito 的块式笔记本，以及有旁白的视频课。完整应用升级时保留原来的运行时家目录。

[Release](https://github.com/HKUDS/DeepTutor/releases/tag/v1.7.0)

## 更早的版本

v1.7.0 之前的版本列在 [GitHub Releases](https://github.com/HKUDS/DeepTutor/releases)。仓库里的副本在 `assets/releases/past_releases/`。
