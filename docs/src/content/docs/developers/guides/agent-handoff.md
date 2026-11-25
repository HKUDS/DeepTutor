---
title: Agent Handoff
description: Hand the deeptutor CLI to Claude Code, Codex, OpenCode, Hermes, or any tool-using LLM — and let them drive.
quadrant: how-to
---

DeepTutor was designed to be **driven by other agents**. Turn execution can emit structured JSON, sessions can be resumed across processes, and the supported surface is documented in a single skill file that any tool-using LLM can read and act on.

This page is the playbook for that.

## The fundamental pattern

The root [`SKILL.md`](https://github.com/HKUDS/DeepTutor/blob/main/SKILL.md) is a concise handover with setup checks and command examples. It directs agents to `deeptutor plugin list` for current capabilities and tool availability. Use `--help` for installed command options and this page for JSON. `--tool` affects only user-toggleables; `rag` and `exec` auto-mount when eligible.

Hand `SKILL.md` to your agent of choice and it will be able to:

- Run capabilities (`deep_solve`, `deep_research`, `deep_question`, …)
- Manage Knowledge Bases (`kb create`, `kb search`, `kb add`)
- Drive long, multi-turn sessions with `--session` continuity
- Pipe JSON output into downstream tools
- Switch capabilities and tools mid-task

## Claude Code

[Claude Code](https://docs.claude.com/en/docs/claude-code) reads `SKILL.md` files automatically when they appear in the project root.

```bash
cd /your-project
# DeepTutor's SKILL.md lives in DeepTutor/SKILL.md; copy or symlink it:
ln -s /path/to/DeepTutor/SKILL.md ./SKILL.md

# Or, easier: include it via Claude Code's allowed-skills config
```

Once Claude Code sees `SKILL.md`, it understands the CLI. You can prompt it naturally:

```text
> Build me a study plan for the next two weeks on linear algebra. Use DeepTutor:
> create a KB from the PDFs in ./textbooks/, then generate 10 quiz questions
> spread across three difficulty levels.
```

Claude Code will translate that into:

```bash
deeptutor kb create linalg --docs-dir ./textbooks/

# First quiz call — start a new session and capture its id from the
# 'done' event so the next two turns can reuse it.
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

It uses `--session` to keep all three quiz turns linked.

### Wiring the deeptutor CLI into a Claude Code subagent

If you want a dedicated "study agent" in Claude Code that always uses `deeptutor`:

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

## Codex (OpenAI Codex CLI)

Codex follows a similar pattern. Drop `SKILL.md` in the project root and prompt:

```text
codex "Read SKILL.md, then run a deep research turn on transformer attention mechanisms. Use the 'papers' knowledge base if it exists; if not, just web search."
```

For OAuth-enabled providers (like OpenAI Codex itself), DeepTutor has a built-in login command:

```bash
deeptutor provider login openai-codex
# Opens a browser for OAuth, stores the token in workspace
```

After that, you can use OpenAI Codex via DeepTutor with the resulting token.

## OpenCode

[OpenCode](https://opencode.ai) works the same way. Add the project's `SKILL.md`:

```bash
opencode init
ln -s /path/to/DeepTutor/SKILL.md ./SKILL.md
opencode "Plan a study session on quantum mechanics using deeptutor"
```

## Hermes / generic agent frameworks

For agent frameworks that don't natively understand `SKILL.md` (LangChain agents, AutoGen, custom loops), expose `deeptutor` as a tool definition. A minimal LangChain wrapper:

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

Then your agent loop can use it directly.

## The session-handoff pattern

The most powerful pattern: have an agent **chain capability calls within one session** so each new turn inherits the context of the previous one.

```bash
# Step 1 — research
SESSION_ID=$(deeptutor run deep_research "Survey 2026 papers on RAG" \
  --tool web_search --kb papers \
  --config mode=report --config depth=standard \
  --format json | \
  jq -r 'select(.type=="done") | .session_id')

# Step 2 — summarize (same session, different capability)
deeptutor run chat "Summarize the top three findings as bullet points" \
  --session "$SESSION_ID" --format json

# Step 3 — quiz (same session)
deeptutor run deep_question "The findings from this session" \
  --session "$SESSION_ID" \
  --config num_questions=5 \
  --format json
```

Each step inherits:

- The full chat history
- The same session identity and conversation branch

Each `run` sends its own selections: omitted flags become `tools=[]`, `knowledge_bases=[]`, and `language="en"`, replacing session preferences. Repeat `--tool`, `--kb`, and `--language` when needed; conversation context remains stateful.

## JSON event parsing

Parse `--format json` line-by-line. Headless `ask_user` pauses receive an automatic empty reply. A minimal Python consumer:

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

Or with `jq`:

```bash
# Get the final answer
deeptutor run chat "Hello" --format json | \
  jq -r 'select(.type == "result") | .metadata.response // empty'

# Get the session id
deeptutor run chat "Hello" --format json | \
  jq -r 'select(.type=="done") | .session_id'

# Stream stages as they finish
deeptutor run deep_research "..." \
  --config mode=report --config depth=quick \
  --format json | \
  jq -r 'select(.type=="stage_end") | "Stage finished: " + .stage'
```

## What goes in your SKILL.md, exactly

The shipped [`SKILL.md`](https://github.com/HKUDS/DeepTutor/blob/main/SKILL.md) covers:

1. **When to Use** — what kinds of user requests should trigger DeepTutor
2. **Prerequisites** — Python 3.11+, install path, `deeptutor init`
3. **Commands** — Chat & Capabilities, Knowledge Bases, Partners, Skills, Books, Memory, Sessions, Notebooks, Providers, System
4. **REPL Slash Commands** — the commands available inside `deeptutor chat`
5. **Typical Workflows** — end-to-end recipes an agent can replay

It's compact and written for one-shot ingestion — most tool-using agents (Claude Sonnet/Opus, GPT-4/5, Gemini Pro) can absorb it in one read.

## Provider tokens for cloud agents

DeepTutor can run local CLI commands without a browser, but model/search features call out to the providers you configure. If your agent is running in a sandboxed environment, make sure these are reachable:

| Provider | Endpoint to allow |
|----------|-------------------|
| OpenAI | `api.openai.com:443` |
| Anthropic | `api.anthropic.com:443` |
| Google Gemini | `generativelanguage.googleapis.com:443` |
| Azure OpenAI | `<your-resource>.openai.azure.com:443` |
| Local Ollama / vLLM | The endpoint configured in `data/user/settings/model_catalog.json` or process env |

For RAG-heavy workflows, also allow whatever search provider you've configured (Tavily, Brave, Jina, Serper, Perplexity, SearXNG, or DuckDuckGo).

## See also

- [**Commands**](/developers/reference/cli/) — full CLI reference
- [**Interactive REPL**](/developers/guides/repl/) — for human-driven sessions
- [**Memory**](/learning-workspace/memory/) — how persistent state flows through sessions
