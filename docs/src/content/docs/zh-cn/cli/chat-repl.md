---
title: 交互式 REPL
description: 一个长时间运行的终端 chat 会话，内嵌 /slash 命令用于切换 capability、tool、KB 等。
---

`deeptutor chat` 进入一个交互式 REPL —— 适合 **探索性工作**、**多轮调试** 以及 **手动驱动 DeepTutor**（而不是用 `run` 一条条发命令）。

## 启动

```bash
# 默认 —— chat capability，无 KB，无额外 tool
deeptutor chat

# 预挂载一个 KB，并预开一个用户可切换的 tool
deeptutor chat --kb physics --tool reason

# 以特定 capability 启动（比如固定用 Deep Solve）
deeptutor chat --capability deep_solve

# 续上一个旧 session
deeptutor chat --session sess_abc123

# 通过 flag 传偏好（和 run 一样）
deeptutor chat --language zh --kb papers --history-ref sess_old_xyz
```

## REPL 长什么样

```text
┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ DeepTutor CLI                                                      ┃
┃ Type a message to chat. Ctrl-C interrupts a running turn. Commands:┃
┃   /quit  /session  /status  /new  /clear                          ┃
┃   /regenerate (alias /retry) — re-run the last user message       ┃
┃   /tool on|off <name>                                             ┃
┃   /cap <name>                                                     ┃
┃   /kb <name>|none                                                 ┃
┃   /history add <id> | /history clear                              ┃
┃   /notebook add <ref> | /notebook clear                           ┃
┃   /show last|<n> — expand a tool result or captured thinking      ┃
┃   /refs  /config show|set|clear                                   ┃
┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛
[dim]session=(new) capability=chat tools=[] kb=[] history=[] notebook_refs=[] language=en config={}[/]
You> _
```

底部那行灰色状态显示下一轮 turn 会带过去的所有东西：session id、capability、tools、挂载的 KB、history reference、notebook reference、语言和 config。

## 一个典型会话

```text
You> 什么是链式法则？

  ✻ thinking…
**链式法则** 说的是：对一个复合函数 `f(g(x))` 求导时，你需要把……相乘

[dim]session=sess_abc123 turn=turn_xyz789 capability=chat[/]

You> /tool on reason
[dim]session=sess_abc123 capability=chat tools=[reason] kb=[] ...[/]

You> /kb math
[dim]session=sess_abc123 capability=chat tools=[reason] kb=[math] ...[/]

You> 用教材第 3 章的一个例题讲讲

  ✻ thinking…
  ● rag(query=chain rule worked example, kb_name=math)
  │ Example: differentiate sin(x²) using the chain rule...
  └ #1 rag — +3 more lines

  ✻ thinking…
教材第 3 章里的例子：

设 `y = sin(x²)`。令 `u = x²`……

You> /quit
$
```

## 所有 slash 命令

### Session

| 命令 | 作用 |
|------|------|
| `/quit` | 退出 REPL |
| `/session` | 打印当前 session id |
| `/status` | 打印当前整个回合状态——capability、tool、知识库、语言、config |
| `/new`（或 `/clear`） | 开一个新 session，清掉当前 id |
| `/regenerate`（或 `/retry`） | 用 capability 默认值重跑最后一条 user 消息；不会转发当前 `/config` 覆盖 |

### Capability 切换

| 命令 | 作用 |
|------|------|
| `/cap <name>` | 切到另一个 capability |

合法名称：`chat`、`ask_questions`、`deep_solve`、`deep_question`、`deep_research`、`visualize`、`math_animator`、`mastery_path`、`immersive_reading`、`video_lesson`、`audio_overview`。CLI 别名也认——`ask`、`solve`、`quiz`、`research`、`viz`、`animate`、`mastery`、`reading` / `read`、`lesson`、`audio-overview` / `overview`。

注意 `immersive_reading` 在 CLI 上跑的是没有阅读器的那套循环：CLI 既没有可滚动的视口，也没有可操作的选区，所以这个模式请在 Web 界面用（见[沉浸式阅读](/zh-cn/explore/reading/)）。

```text
You> /cap deep_solve
[dim]capability=deep_solve ...[/]
You> 求 d/dx [sin(x²)]
```

### Tool

```text
/tool on <name>     # 下一轮开启某个 tool
/tool off <name>    # 关掉
```

当前合法 toggle 与 Web 界面完全相同：`brainstorm`、`web_search`、`paper_search`、`zotero_search`、`reason`、`geogebra_analysis`，以及配好生成模型后的 `imagegen` / `videogen`。`rag`、`exec`、`read_memory`、`web_fetch`、`write_note`、`cron` 等上下文门控 tool 不能用 `/tool` 强开，只会在条件满足时自动挂载。

### 知识库

```text
/kb <name>          # 挂载一个 KB（替换当前挂载）
/kb none            # 卸载
```

### History reference

告诉模型有哪些历史 session 应该当作上下文（不用复制粘贴）：

```text
/history add sess_prior_xyz
/history clear
```

这是搭建跨 session 上下文的方式 —— 做 "接着上次的研究继续" 类的 turn 非常合适。

### Notebook reference

从你的 notebook 里带入特定记录：

```text
/notebook add <notebook-id>:a3f9c1e2,7c1b0d45
/notebook clear
```

### Config 覆盖

对后续 turn 生效的 per-capability config：

```text
/config show                       # 打印当前 config
/config set num_questions 5
/config set difficulty=hard
/config set difficulty hard
/config clear                      # 重置为默认值
```

举例，以 `--capability deep_question` 启动：

```text
You> /config set num_questions 8
You> /config set question_types '["short_answer","mcq"]'
You> 出几道关于线性回归的题
```

### 查看 tool 结果

Tool 结果截为前 10 行 / 每行 240 字符；thinking 折叠成提示。两者共用 `/show` 序号：

```text
/show last          # 最后一条 tool 结果或 thinking 块
/show 3             # 本 session 的第 3 个捕获块
```

两类合计最多缓存 32 条。

### `/refs`

打印下一轮 turn 会带过去的所有内容：

```text
You> /refs
[bold]Current state:[/]
  session     sess_abc123
  capability  chat
  tools       [rag, reason]
  kb          [physics, math]
  history     [sess_old_xyz]
  notebooks   [<notebook-id>:a3f9c1e2]
  language    en
  config      {"difficulty": "hard", "num_questions": 5}
```

## REPL 里的流式渲染怎么工作

每一轮 turn 按 stage 渲染。你会按顺序看到：

| 标记 | 含义 |
|------|------|
| `▶ <stage>` | 非 chat stage 开始；chat 隐藏 `responding` |
| `  ✻ thinking…` | 推理已捕获，可用 `/show` 查看 |
| `  ● <tool>(...)` | 正在调用某个 tool |
| `  │ <line>` | 一行 tool 输出 |
| `  └ #N <tool> — +M more lines; run /show N to expand` | tool 结果被截断 |
| *普通文本* | 渲染后的最终 markdown 回复 |

`ask_user` 弹卡；`answer>` 回复继续，Ctrl-C 中止。

## 小贴士

### 多行输入

要发多行消息（代码片段、长 prompt），每行末尾加一个反斜杠 `\` 再回车：

```text
You> Please review this Python code:\
def fib(n):\
    if n < 2: return n\
    return fib(n-1) + fib(n-2)
```

### 会话中途切 capability

一个 session 内可以自由切换 capability —— DeepTutor 会保留对话上下文。一种常见 pattern：

```text
You> /cap deep_research
You> /config set mode=report
You> /config set depth=standard
You> 调研一下 2024–2026 年关于 RAG 的论文
[一个很长的研究 turn]

You> /config clear
You> /cap chat
You> 现在写一个 3 段总结，目标读者是非技术背景的人

You> /cap deep_question
You> /config set num_questions 5
You> 基于这些论文出几道测验题
```

三个 turn 共享上下文；切换不兼容 capability schema 前先清空 config。

### 导出会话日志

Session 存在共享的 session 数据库里。要导出一份干净的 markdown 文字稿：

```bash
deeptutor session show sess_abc123 --format json | \
  jq -r '.messages[] | "**" + .role + "**: " + .content + "\n"' > transcript.md
```

### 从 REPL → notebook

某个 turn 觉得不错？存进 notebook：

```bash
# REPL 里
You> /quit

# 然后在 shell 里把 assistant 最后一条消息抓出来
deeptutor session show sess_abc123 --format json | \
  jq -r '.messages[-1].content' > my-answer.md

deeptutor notebook add-md <notebook-id> my-answer.md --title "Chain rule explanation"
# <notebook-id> 是 `deeptutor notebook list` 里那个 8 位 id，不是 notebook 名称
```

## 另见

- [**命令参考**](/zh-cn/cli/commands/) —— `run`、`kb`、`partner` 等完整参考
- [**代理交接**](/zh-cn/cli/agent-handoff/) —— 让 agent 替你来做这些
