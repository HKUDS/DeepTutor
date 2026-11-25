---
title: Python SDK
description: 在异步 Python 应用中直接嵌入 DeepTutor 的回合、会话、能力与笔记本运行时。
quadrant: tutorial
---

`DeepTutorApp` 是 DeepTutor 稳定的进程内 Python facade。它暴露 CLI 所用的同一套回合 payload 与运行时 contract，无需另行启动 CLI，也不必通过 HTTP API 发送请求。你的应用本来就在 Python 中运行，并且需要原生访问流式事件、会话、能力元数据或笔记本时，就适合使用它。

## 前置条件

使用 Python 3.11–3.14，安装 DeepTutor，并初始化一份与 CLI 相同的运行时工作区：

```bash
python -m pip install -r requirements/full.txt
python -m pip install -e . --no-deps
deeptutor init --home /path/to/workspace
```

用 `DEEPTUTOR_HOME=/path/to/workspace` 运行程序；若不设置该变量，DeepTutor 会使用当前工作目录。SDK 与 `deeptutor chat`、`deeptutor run` 读取同一套 `data/user/settings/` 提供商与运行时配置，因此开始回合前要先配好可用模型。

## 运行一个回合

```python
import asyncio

from deeptutor.app import DeepTutorApp, TurnRequest


async def main() -> None:
    app = DeepTutorApp()
    session, turn = await app.start_turn(
        TurnRequest(
            content="Explain the Fourier transform in one paragraph.",
            capability="chat",
        )
    )

    answer = ""
    async for event in app.stream_turn(turn["id"]):
        if event["type"] == "result":
            answer = (event.get("metadata") or {}).get("response", "")

    print(answer)
    print("session:", session["id"])


asyncio.run(main())
```

`TurnRequest` 还可接收 session ID、启用的工具、知识库、语言、能力配置、笔记本/历史引用、伙伴组引用、附件与技能。

## 可用操作

| 范围 | 方法 |
| --- | --- |
| 回合生命周期 | `start_turn()`、`stream_turn()`、`cancel_turn()`、`submit_user_reply()`、`regenerate_last_turn()` |
| 会话 | `list_sessions()`、`get_session()`、`rename_session()`、`delete_session()`、`get_active_turn()` |
| 能力 | `resolve_capability()`、`get_capability_contract()`、`get_capability_contracts()`、`get_capability_availability()` |
| 笔记本 | `list_notebooks()`、`create_notebook()`、`get_notebook()`，以及记录的新增/更新/删除/引用方法 |

回合与会话方法是异步的；能力发现与笔记本方法是同步的。

## SDK、CLI 还是 API？

`deeptutor run --format json` 会创建同样的 `DeepTutorApp` 与 `TurnRequest`，再把每个 `stream_turn()` 项序列化成一行 NDJSON。它的无头模式会为空等候中的 `ask_user` 自动提交空回复；SDK 调用方则自行决定何时调用 `submit_user_reply()`。

Shell pipeline 与 agent 交接选 **CLI**，进程内异步集成选 **Python SDK**；如果 DeepTutor 需要作为独立服务运行，或客户端不是 Python，则选 **HTTP / WebSocket API**。

## 另见

- [代理交接](/zh-cn/developers/guides/agent-handoff/)——以 NDJSON 消费同一条事件流
- [服务端 API](/zh-cn/developers/reference/http-api/)——跨进程或网络连接
- [命令参考](/zh-cn/developers/reference/cli/)——配置并检查共享工作区
