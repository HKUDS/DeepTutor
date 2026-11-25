---
title: DeepTutor CLI
description: 在终端里驱动 DeepTutor 的所有能力 —— 交互式 REPL、单次执行、Agent 交接。
quadrant: how-to
---

DeepTutor 是围绕 **agent-native CLI** 设计的：核心运行时在终端里都有对应入口，turn 执行可以流式输出 JSON 给程序消费，自动化 surface 集中在一份 skill 文档里，AI 代理读完就能自驱。部分浏览器优先的工作流（比如 学习笔记本编辑、Memory Workbench）仍然在 Web UI 或 HTTP API 里。

本章节包括：

- [**命令参考**](/zh-cn/developers/reference/cli/) —— 每个顶层命令和子命令的 flag、schema、示例
- [**交互式 REPL**](/zh-cn/developers/guides/repl/) —— 在长会话里用 `/slash` 命令操作
- [**代理交接**](/zh-cn/developers/guides/agent-handoff/) —— 让 Claude Code / Codex / OpenCode / Hermes 来驱动 `deeptutor`
- [**服务端 API**](/zh-cn/developers/reference/http-api/) —— `deeptutor serve` 暴露的 HTTP / WebSocket 表面

当前 dev 使用仓库根目录中的源码安装流程。使用 1.7.x 模块家族时，裸 `deeptutor` 提供 core 聊天和 SDK；其他命令需要对应功能模块或 `[full]`。运行前用 `deeptutor module list` 和 `deeptutor plugin list` 检查可用范围。

## 快速一览

```bash
# 装包（从 Get Started 选一种路径）
python -m pip install -r requirements/full.txt
python -m pip install -e . --no-deps

# 配置
deeptutor init

# 交互式 chat
deeptutor chat

# 单次执行，agent 风格
deeptutor run deep_solve "求 sin(x²) 的导数" --tool reason --format json

# 管理知识库
deeptutor kb create physics --doc chapter1.pdf
deeptutor kb search physics "什么是角动量？"

# 运行一个 Partner
deeptutor partner create my-bot --soul "Socratic 数学导师"

# 看三层记忆
deeptutor memory show L3
```

## 为什么是 CLI 优先

终端体验 **和 AI 代理拿到的体验是同一份**。你在 `deeptutor chat` 里写一条 turn，背后的 `TurnRequest` schema 和你把 `SKILL.md` 丢给 Claude Code / Codex 后他们发出的请求是一模一样的。

这意味着：

- 核心学习流程都可以在终端里驱动；浏览器独占的编辑和管理面板通过 Web UI / API 暴露状态
- `deeptutor run --format json` 每行一个 JSON 事件；数据检查类命令 `kb list`、`kb search`、`session show`、`notebook show` 等也都能输出 JSON
- Session 跨 turn 持久化 —— 你可以在 Web、REPL、单次 `run` 之间切换并续上之前的上下文
- 自动化进入点（turns / KB / session / notebook / memory / Partners / config / plugin / provider / book）都在 CLI 上

## 顶层命令地图

| 组 | 用途 | 最常用 |
|----|------|--------|
| `deeptutor init` | 引导式初始化向导 | `deeptutor init --cli` |
| `deeptutor doctor` | 检查工作区是否已经可以开始一轮会话 | `deeptutor doctor --online` |
| `deeptutor start` | 同时启动后端 + 前端 | `deeptutor start` |
| `deeptutor serve` | 仅启动后端（`:8001` 上的 FastAPI） | `deeptutor serve --host 0.0.0.0` |
| `deeptutor chat` | 交互式 REPL | `deeptutor chat --kb physics` |
| `deeptutor run` | 单次 capability 执行 | `deeptutor run deep_solve "..."` |
| `deeptutor kb` | 知识库管理 | `deeptutor kb create / list / search` |
| `deeptutor skill` / `skills` | Skill 库与 hub 安装 | `deeptutor skill search / install / list` |
| `deeptutor session` | session 查看 | `deeptutor session list / show <id>` |
| `deeptutor notebook` | notebook 记录 | `deeptutor notebook create / add-md` |
| `deeptutor memory` | 三层记忆存储 | `deeptutor memory show L3` |
| `deeptutor partner` | Partner 生命周期 | `deeptutor partner create / start / stop`（`create` 会写配置并启动） |
| `deeptutor config` | 查看运行时配置 | `deeptutor config show` |
| `deeptutor module` | 检查及管理可选功能模块 | `deeptutor module list / enable / disable` |
| `deeptutor plugin` | capability / tool 注册表 | `deeptutor plugin list` |
| `deeptutor provider` | provider 认证流程 | `deeptutor provider login openai-codex` |
| `deeptutor book` | Knowledge Books（引导式学习） | `deeptutor book list / health` |

完整参考见 [**命令参考**](/zh-cn/developers/reference/cli/)。

## 两种使用方式

### 方式 1 —— 交互式

适合探索性的、多轮的工作：

```text
$ deeptutor chat --kb physics
┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ DeepTutor CLI                                                  ┃
┃ Type a message. /quit /tool /cap /kb /history /show /refs     ┃
┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛
You> 用一个具体例子讲一下链式法则
```

完整说明：[**交互式 REPL**](/zh-cn/developers/guides/repl/)。

### 方式 2 —— Agent 风格单次执行

适合自动化、CI、AI 代理 harness：

```bash
deeptutor run deep_solve "求 [[4,1],[2,3]] 的特征值" \
  --tool reason \
  --format json | jq -r 'select(.type == "result") | .metadata.response // empty'
```

每行 JSON 是一个事件 —— `stage_start`、`content`、`tool_call`、`tool_result`、`thinking`、`done`。可以管道给下游 agent，或者用 `jq` 提取最终答案。

完整说明：[**代理交接**](/zh-cn/developers/guides/agent-handoff/)。

## 状态存在哪里

所有 CLI 命令操作的是 **和 Web UI 同一个工作区**。默认情况下，运行时数据存在你启动 DeepTutor 时所在目录下的 `data/` 里。可以用 `DEEPTUTOR_HOME=/path`、`deeptutor init --home /path` 或 `deeptutor start --home /path` 覆盖。

## `--help` 永远在一个 flag 之外

每个命令都支持 `--help`：

```text
$ deeptutor --help

 Usage: deeptutor [OPTIONS] COMMAND [ARGS]...

 DeepTutor CLI – agent-first interface for capabilities, tools, and knowledge.

╭─ Commands ───────────────────────────────────────────────────────────────────╮
│ doctor     Check whether DeepTutor is ready to start a session.              │
│ init       Create or update data/user/settings for this workspace.           │
│ run        Run any capability in a single turn (agent-first entry point).    │
│ start      Launch backend + frontend together. Source installs default to    │
│            production.                                                       │
│ serve      Start the DeepTutor API server.                                   │
│ partner    Manage partners (IM-connected companions).                        │
│ chat       Interactive chat REPL.                                            │
│ kb         Manage knowledge bases.                                           │
│ skill      Manage skills and install from hubs (ClawHub, …).                 │
│ skills     Manage skills and install from hubs (ClawHub, …).                 │
│ memory     View and manage lightweight memory.                               │
│ plugin     List plugins.                                                     │
│ config     Inspect configuration.                                            │
│ session    Manage shared sessions.                                           │
│ notebook   Manage notebooks and imported markdown records.                   │
│ provider   Manage provider OAuth login.                                      │
│ book       Manage interactive Books (BookEngine).                            │
╰──────────────────────────────────────────────────────────────────────────────╯
```

每个子命令也一样：

```text
$ deeptutor run --help
$ deeptutor kb create --help
$ deeptutor partner start --help
```
