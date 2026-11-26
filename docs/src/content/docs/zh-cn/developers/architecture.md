---
title: 架构
description: 一次 turn 如何进入 DeepTutor，并到达工具或能力。
quadrant: explanation
---

DeepTutor 有三个入口：CLI、WebSocket API 和 Python SDK。三者都进入 turn 应用服务。服务先把 turn 持久化，再由 turn 引擎把一份规范化的上下文交给选中的能力。默认能力是 `chat`。

```text
CLI  |  WebSocket /ws  |  Python SDK
              |
         Turn 应用服务
              |
          Turn 引擎
          /        \
      工具注册表    能力注册表
```

工具是模型在一轮里调用的单个函数。能力是接管这一轮的多阶段流程，例如 `deep_solve`、`deep_research` 和 `visualize`。已注册的名称、阶段和 CLI 别名在[能力参考](/zh-cn/developers/reference/capabilities/)。

正在运行的 turn 在 `WS /ws` 上使用 [Turn 协议](/zh-cn/developers/reference/turn-protocol/)。套接字以外的 HTTP 路由见 [HTTP API](/zh-cn/developers/reference/http-api/)。

实现布局、测试和模块归属留在仓库的[架构笔记](https://github.com/HKUDS/DeepTutor/blob/dev/docs-for-dev/ARCHITECTURE.md)。本站不发布那套内部文档。
