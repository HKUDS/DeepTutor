---
title: 该用哪种生成
description: Visualize、Math Animator 和 Video Lesson 分别解决什么样的观看需求。
quadrant: explanation
---

DeepTutor 有三种生成器。它们共用对话线程和模型，回答的是不同的事。

| 生成器 | 你想要 | 得到什么 |
| --- | --- | --- |
| [Visualize](/zh-cn/multimodal-studio/visualize/) | 一张能读的图：曲线、示意图、一小页可交互内容 | 线程里的 SVG、Mermaid、Chart.js 或 HTML |
| [Math Animator](/zh-cn/multimodal-studio/math-animator/) | 必须动起来的推导或几何作图 | Manim 视频或分镜 |
| [Video Lesson](/zh-cn/multimodal-studio/video-lesson/) | 一段可以播放、带字幕的短课 | 浏览器里的课程，旁白可选 |

Visualize 也可以把数学动画交给 Manim 渲染器。主题本身是数学、并且要看过程时，走 Math Animator。Video Lesson 是一节课，不是一张图：它写出序列、检查渲染，再在浏览器里播放。

三种都是同一个[智能体循环](/zh-cn/learning-workspace/agent-loop/)上的能力。缺少系统工具（LaTeX、ffmpeg，或源码安装所需的 Node）会让渲染停住，并不会改变你该选哪一种生成器。
