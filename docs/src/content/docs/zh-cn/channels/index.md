---
title: 创建一个伙伴
description: 创建一个伙伴，先在应用里对话，再让一个渠道送出一条回复。
quadrant: how-to
---

伙伴是和[对话](/zh-cn/learning-workspace/chat/)同一套聊天循环上的持久同伴。它有自己的灵魂、资料库和记忆。渠道只是把这个循环送到外部应用。

伙伴曾经是单独的 TutorBot 引擎，使用 `deeptutor bot` 命令和 YAML 渠道。那些地址会重定向到这里。现在同伴以限定范围的一轮对话运行，渠道是伙伴界面里的卡片。

## 创建一个并送出一条消息

1. 打开 **伙伴**，选择 **New partner**。
2. 填写 **Identity**（名称和默认回复语言）和 **Soul**（角色和语气）。第一条回复使用这个灵魂。
3. 在 **Mind** 里选一个模型。第一条回复成功之前先不要打开额外工具。
4. 在 **Library** 里把一个小知识库或技能复制进私人资料库，或绑定一个已有工作区。完成向导。
5. 打开伙伴的 **Chat** 标签，发一个问题。它按你写的灵魂回答之后，再继续。
6. 打开 **Channels**，只启用一个渠道并保存。**Allow From** 里填你自己的发送者 id。这次测试保持 **Send Progress** 和 **Send Tool Hints** 打开。
7. 从那个应用发一条消息。回复应该出现在伙伴 Chat 标签里的同一条线程中。

卡片上的字段名在[渠道 schema](/zh-cn/channels/schema/)。在[国内 IM](/zh-cn/channels/domestic/)或[海外 IM](/zh-cn/channels/international/)里选择应用。

你创建的伙伴归你所有。管理员可以把一个伙伴分配给其他人；他们可以对话，看不到凭据。每个人有自己的会话和关系记忆。

## 另见

- [我的智能体](/zh-cn/customize/agents/) — 从普通对话里咨询一个伙伴
- [记忆](/zh-cn/learning-workspace/memory/) — 伙伴能读和能写的范围
