---
title: 数学动画
description: 在对话里渲染一段 Manim 数学动画。
quadrant: how-to
---

**Math Animator**（`math_animator`）为一则推导或作图写一个 Manim 场景，并渲染成视频或分镜。执行渲染的这台电脑需要 LaTeX 和 ffmpeg。桌面端安装不附带这两个工具。

源码或 PyPI 安装里，渲染器来自 `math-animator` extra。见[从源码安装](/zh-cn/self-hosting/source/#可选的安装-extras)。

## 渲染一段动画

1. 在这台电脑的终端里确认 `latex` 和 `ffmpeg` 可以运行。
2. 打开[对话](/zh-cn/learning-workspace/chat/)，选择 **Math Animator**。
3. 只描述一个变换。例如：“把 sin(x²) 的导数按链式法则逐步动画，最后停在表达式上。”
4. 等到线程里出现视频或分镜。播放一次，核对每一步和代数一致。

因为缺少某个可执行文件而失败时，装上它，再发送同一个请求。不要靠换成另一种生成器来躲开缺失的工具。

## 另见

- [可视化](/zh-cn/multimodal-studio/visualize/) — 一张静止的图
- [该用哪种生成](/zh-cn/multimodal-studio/)
