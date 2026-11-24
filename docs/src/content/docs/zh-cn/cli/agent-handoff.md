---
title: 代理交接
description: 把 deeptutor CLI 交给 Claude Code、Codex、OpenCode、Hermes 或任何会用 tool 的 LLM —— 让它们来驱动。
quadrant: how-to
---

DeepTutor 从设计之初就是为了 **被其他 agent 驱动** 的：turn 执行可以输出结构化 JSON，session 能跨进程恢复，受支持的 surface 都集中在一个 skill 文件里 —— 任何会用 tool 的 LLM 读完就能直接上手。

这一页就是那套 playbook。

## 基本套路

根目录 [`SKILL.md`](https://github.com/HKUDS/DeepTutor/blob/main/SKILL.md) 是精简交接，含安装检查与示例，并让 agent 用 `deeptutor plugin list` 发现当前 capability 与工具。选项查 `--help`，JSON 查本页。`--tool` 只影响用户 toggle；`rag`、`exec` 满足条件才自动挂载。

把 `SKILL.md` 丢给你选的 agent，它就能：

- 跑 capability（`deep_solve`、`deep_research`、`deep_question`、……）
- 管理知识库（`kb create`、`kb search`、`kb add`）
- 用 `--session` 跑长程多轮会话
- 把 JSON 输出管道给下游工具
- 在一个任务中途切换 capability 和 tool

## Claude Code

[Claude Code](https://docs.claude.com/en/docs/claude-code) 看到项目根目录有 `SKILL.md` 时会自动读它。

```bash
cd /your-project
# DeepTutor 的 SKILL.md 在 DeepTutor/SKILL.md；复制或软链过来：
ln -s /path/to/DeepTutor/SKILL.md ./SKILL.md

# 或者更简单：通过 Claude Code 的 allowed-skills 配置带进来
```

一旦 Claude Code 看到 `SKILL.md`，它就理解 CLI 了。你可以自然语言提示：

```text
> 给我做一个未来两周关于线性代数的学习计划。用 DeepTutor：
> 从 ./textbooks/ 里的 PDF 创建一个 KB，然后出 10 道测验题，
> 分布在三个难度上。
```

Claude Code 会把它翻译成：

```bash
deeptutor kb create linalg --docs-dir ./textbooks/

# 第一次出题 —— 开一个新 session，从 'done' 事件里抓 session id，
# 后两轮复用它。
SESSION_ID=$(deeptutor run deep_question "Linear algebra fundamentals" \
  --kb linalg \
  --config num_questions=4 --config difficulty=easy \
  --format json | jq -r 'select(.type=="done") | .session_id')

deeptutor run deep_question "Linear algebra eigenvectors" \
  --kb linalg --session "$SESSION_ID" \
  --config num_questions=3 --config difficulty=medium

deeptutor run deep_question "Linear algebra advanced theorems" \
  --kb linalg --session "$SESSION_ID" \
  --config num_questions=3 --config difficulty=hard
```

它用 `--session` 把三轮出题串在一起。

### 把 deeptutor CLI 接成 Claude Code 的 subagent

如果你想在 Claude Code 里有一个固定的 "学习 agent"，永远走 `deeptutor`：

```yaml
# .claude/agents/study-agent.yaml
name: study-agent
description: Use this agent for any learning, study planning, or quiz generation task. It drives DeepTutor.
tools: [Bash, Read, Write]
system_prompt: |
  You are a study planner. You have access to the `deeptutor` CLI via the Bash tool.
  Read SKILL.md before doing anything else. Then build study plans, generate quizzes,
  and run research turns by calling `deeptutor run <capability> "..."` with the right
  flags. Always pass `--format json` for parsing.
```

## Codex（OpenAI Codex CLI）

Codex 走类似的套路。把 `SKILL.md` 放到项目根目录，然后提示：

```text
codex "Read SKILL.md, then run a deep research turn on transformer attention mechanisms. Use the 'papers' knowledge base if it exists; if not, just web search."
```

对于走 OAuth 的 provider（比如 OpenAI Codex 自己），DeepTutor 内置了登录命令：

```bash
deeptutor provider login openai-codex
# 浏览器打开做 OAuth，token 存到工作区
```

之后就可以用拿到的 token 通过 DeepTutor 使用 OpenAI Codex。

## OpenCode

[OpenCode](https://opencode.ai) 同样的玩法。把项目的 `SKILL.md` 加进来：

```bash
opencode init
ln -s /path/to/DeepTutor/SKILL.md ./SKILL.md
opencode "Plan a study session on quantum mechanics using deeptutor"
```

## Hermes / 通用 agent 框架

对于原生不认 `SKILL.md` 的 agent 框架（LangChain agent、AutoGen、自定义 loop），把 `deeptutor` 包成一个 tool 定义就行。一个最小化的 LangChain 封装：

```python
from langchain.tools import Tool
import subprocess
import json

def deeptutor_run(args_json: str) -> str:
    args = json.loads(args_json)
    cmd = [
        "deeptutor", "run",
        args["capability"],
        args["message"],
        "--format", "json",
    ]
    for tool in args.get("tools", []):
        cmd.extend(["--tool", tool])
    for kb in args.get("knowledge_bases", []):
        cmd.extend(["--kb", kb])
    if args.get("session_id"):
        cmd.extend(["--session", args["session_id"]])
    for key, value in args.get("config", {}).items():
        cmd.extend(["--config", f"{key}={json.dumps(value)}"])

    result = subprocess.run(cmd, capture_output=True, text=True)
    return result.stdout

deeptutor_tool = Tool(
    name="deeptutor_run",
    description=(
        "Run a DeepTutor capability. Args: JSON object with "
        "{capability, message, tools, knowledge_bases, session_id, config}. "
        "Returns one JSON event per line."
    ),
    func=deeptutor_run,
)
```

然后你的 agent loop 就可以直接用了。

## Session 交接 pattern

最强的一种用法：让 agent **在同一个 session 里串起多次 capability 调用**，让每个新的 turn 继承前一个的上下文。

```bash
# Step 1 —— 研究
SESSION_ID=$(deeptutor run deep_research "Survey 2026 papers on RAG" \
  --tool web_search --kb papers \
  --config mode=report --config depth=standard \
  --format json | \
  jq -r 'select(.type=="done") | .session_id')

# Step 2 —— 总结（同一 session，不同 capability）
deeptutor run chat "Summarize the top three findings as bullet points" \
  --session "$SESSION_ID" --format json

# Step 3 —— 出题（同一 session）
deeptutor run deep_question "The findings from this session" \
  --session "$SESSION_ID" \
  --config num_questions=5 \
  --format json
```

每一步都会继承：

- 完整对话历史
- 相同的 session 身份与对话分支

每次 `run` 都发送自己的选择：省略 flag 就是 `tools=[]`、`knowledge_bases=[]`、`language="en"`，会覆盖 session 偏好。需要时重复 `--tool`、`--kb`、`--language`；对话上下文仍有状态。

## JSON 事件解析

`--format json` 按行解析；无头 `ask_user` 暂停会自动收到空回复。最小 Python 消费者：

```python
import json
import subprocess

proc = subprocess.Popen(
    ["deeptutor", "run", "deep_solve", "Find d/dx [sin(x²)]",
     "--tool", "reason", "--format", "json"],
    stdout=subprocess.PIPE,
    text=True,
)

answer = ""
for line in proc.stdout:
    event = json.loads(line)
    if event["type"] == "result":
        answer = event.get("metadata", {}).get("response", "")
    elif event["type"] == "tool_call":
        print(f"→ Tool: {event['content']}({event['metadata']['args']})")
    elif event["type"] == "error":
        print(f"× Error: {event['content']}")
        break
    elif event["type"] == "done":
        session_id = event["session_id"]
        break
```

或者用 `jq`：

```bash
# 拿到最终答案
deeptutor run chat "Hello" --format json | \
  jq -r 'select(.type == "result") | .metadata.response // empty'

# 拿到 session id
deeptutor run chat "Hello" --format json | \
  jq -r 'select(.type=="done") | .session_id'

# 流式打印每个 stage 完成的瞬间
deeptutor run deep_research "..." \
  --config mode=report --config depth=quick \
  --format json | \
  jq -r 'select(.type=="stage_end") | "Stage finished: " + .stage'
```

## 你的 SKILL.md 里到底放什么

仓库内置的 [`SKILL.md`](https://github.com/HKUDS/DeepTutor/blob/main/SKILL.md) 覆盖：

1. **When to Use** —— 哪些用户请求应该触发 DeepTutor
2. **Prerequisites** —— Python 3.11+、安装方式、`deeptutor init`
3. **Commands** —— Chat & Capabilities、Knowledge Bases、Partners、Skills、Books、Memory、Sessions、Notebooks、Providers、System
4. **REPL Slash Commands** —— `deeptutor chat` 内部可用的命令
5. **Typical Workflows** —— 一组 agent 可以照着复刻的端到端 recipe

整份篇幅紧凑，按 "一次吞下去" 写的 —— 主流会用 tool 的 agent（Claude Sonnet/Opus、GPT-4/5、Gemini Pro）读一遍就能上手。

## 给云端 agent 准备的 provider token

DeepTutor 本地 CLI 命令不需要浏览器，但模型 / 搜索功能会去访问你配的 provider。如果你的 agent 跑在沙箱环境里，确认下面这些是可达的：

| Provider | 需要放行的 endpoint |
|----------|---------------------|
| OpenAI | `api.openai.com:443` |
| Anthropic | `api.anthropic.com:443` |
| Google Gemini | `generativelanguage.googleapis.com:443` |
| Azure OpenAI | `<your-resource>.openai.azure.com:443` |
| 本地 Ollama / vLLM | `data/user/settings/model_catalog.json` 或进程环境变量里配的 endpoint |

如果是 RAG 密集型工作流，还要放行你配置的搜索 provider（Tavily、Brave、Jina、Serper、Perplexity、SearXNG 或 DuckDuckGo）。

## 另见

- [**命令参考**](/zh-cn/cli/commands/) —— 完整 CLI 参考
- [**交互式 REPL**](/zh-cn/cli/chat-repl/) —— 人工驱动的会话
- [**Memory**](/zh-cn/explore/memory/) —— 持久状态怎么在 session 之间流动
