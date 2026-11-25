---
title: 视频课
description: 生成一节带字幕、在浏览器里播放的课。
quadrant: how-to
---

**Video Lesson**（`video_lesson`）写出一节短课，检查渲染，再在浏览器里连字幕一起播放。旁白使用设置里的语音合成提供方；没有设置时使用 Edge。

源码安装需要渲染这台机器上有 Node.js 22 或更新版本，以及 npm。桌面应用已经带有 Node。

## 生成一节课

1. 打开[对话](/zh-cn/learning-workspace/chat/)，选择 **Video Lesson**。
2. 只写一个概念和时长。例如：“给一年级讲三分钟采样定理。打开字幕。带一个数字例题。”
3. 等到播放器出现在线程里。完整看一遍。
4. 如果你需要声音而这节课是静音的，在 **设置 → 模型与服务** 里配置语音合成，再生成一次。

你能在线程里看完，并且字幕和画面一致，这节课就完成了。

## 另见

- [该用哪种生成](/zh-cn/multimodal-studio/)
- [提供方与模型](/zh-cn/get-started/providers/) — 语音合成和其他模型 profile 在一起
