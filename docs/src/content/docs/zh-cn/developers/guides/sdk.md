---
title: Python SDK
description: 在异步 Python 程序里发起一次 DeepTutor 回合，并边生成边读到回答。
quadrant: tutorial
---

`DeepTutorApp` 是跑在你这个进程里的 Python 入口。一次回合（turn）就是一次请求，加上它结束前返回的事件。SDK 用的请求内容和 CLI 相同。它不会另外启动 CLI，也不会把请求走 HTTP 发出去。程序本身是 Python，又想在同一个进程里拿到事件、会话或笔记本时，用它。

## 前置条件

使用 Python 3.11–3.14，安装 DeepTutor，并初始化一份与 CLI 相同的运行时工作区：

```bash
python -m pip install -r requirements/full.txt
python -m pip install -e . --no-deps
deeptutor init --home /path/to/workspace
```

用 `DEEPTUTOR_HOME=/path/to/workspace` 运行程序。不设置这个变量时，DeepTutor 使用当前工作目录。SDK 和 `deeptutor chat`、`deeptutor run` 读的是同一套 `data/user/settings/` 里的提供方和运行时文件。开始回合前先配好一个能用的模型，否则这次调用没有模型可以回答。

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

跑完后，终端会打印那段说明，以及一个会话 id。用这个 id 可以再打开同一段对话。

`TurnRequest` 还可以带上 session ID、启用的工具、知识库、语言、能力配置、笔记本或历史引用、伙伴组引用、附件和技能。这里的能力（capability）是这次回合要用的流程，例如 `chat`。

## 可用操作

| 范围 | 方法 |
| --- | --- |
| 回合生命周期 | `start_turn()`、`stream_turn()`、`cancel_turn()`、`submit_user_reply()`、`regenerate_last_turn()` |
| 会话 | `list_sessions()`、`get_session()`、`rename_session()`、`delete_session()`、`get_active_turn()` |
| 能力 | `resolve_capability()`、`get_capability_contract()`、`get_capability_contracts()`、`get_capability_availability()` |
| 笔记本 | `list_notebooks()`、`create_notebook()`、`get_notebook()`，以及记录的新增、更新、删除和引用方法 |

回合和会话的方法是异步的，调用时要 await。查能力和操作笔记本的方法会马上返回。

## SDK、CLI 还是 API？

`deeptutor run --format json` 会创建同样的 `DeepTutorApp` 和 `TurnRequest`，再把每个 `stream_turn()` 项写成一行 NDJSON。回合停在 `ask_user` 时，这条无界面命令会替你交一份空回复。在 SDK 里，由你决定什么时候调用 `submit_user_reply()`。

要在 shell 里串命令，或把事件流交给另一个 agent，用 **CLI**。调用留在你的 Python 进程里，用 **Python SDK**。DeepTutor 要单独跑成一个服务，或者调用方不是 Python，用 **HTTP / WebSocket API**。

## 另见

- [代理交接](/zh-cn/developers/guides/agent-handoff/)——以 NDJSON 消费同一条事件流
- [服务端 API](/zh-cn/developers/reference/http-api/)——跨进程或网络连接
- [命令参考](/zh-cn/developers/reference/cli/)——配置并检查共享工作区
