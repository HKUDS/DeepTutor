---
title: Interactive REPL
description: A long-running terminal chat session with inline /slash commands for switching capabilities, tools, KBs, and more.
---

`deeptutor chat` opens an interactive REPL — useful for **exploratory work**, **multi-turn debugging**, and **driving DeepTutor with your hands** instead of with `run` calls.

## Launching

```bash
# Default — chat capability, no KBs, no extra tools
deeptutor chat

# Pre-attach a KB and pre-enable a user-toggleable tool
deeptutor chat --kb physics --tool reason

# Start in a specific capability (e.g., always use Deep Solve)
deeptutor chat --capability deep_solve

# Resume a prior session
deeptutor chat --session sess_abc123

# Hand it preferences via flags (same as run)
deeptutor chat --language zh --kb papers --history-ref sess_old_xyz
```

## What the REPL looks like

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

The dimmed status line shows everything that will be sent on your next turn: session id, capability, tools, attached KBs, history references, notebook references, language, and config.

## A typical session

```text
You> What is the chain rule?

  ✻ thinking…
The **chain rule** says that to differentiate a composite function `f(g(x))`, you multiply...

[dim]session=sess_abc123 turn=turn_xyz789 capability=chat[/]

You> /tool on reason
[dim]session=sess_abc123 capability=chat tools=[reason] kb=[] ...[/]

You> /kb math
[dim]session=sess_abc123 capability=chat tools=[reason] kb=[math] ...[/]

You> Now with a worked example from chapter 3 of the textbook

  ✻ thinking…
  ● rag(query=chain rule worked example, kb_name=math)
  │ Example: differentiate sin(x²) using the chain rule...
  └ #1 rag — +3 more lines

  ✻ thinking…
Here's the example from chapter 3:

Take `y = sin(x²)`. Let `u = x²`...

You> /quit
$
```

## All slash commands

### Session

| Command | Effect |
|---------|--------|
| `/quit` | Exit the REPL |
| `/session` | Print the current session id |
| `/status` | Print the whole current turn state — capability, tools, KBs, language, config |
| `/new` (or `/clear`) | Start a fresh session, clearing the id |
| `/regenerate` (or `/retry`) | Re-run the last user message with capability defaults; current `/config` overrides are not forwarded |

### Capability switching

| Command | Effect |
|---------|--------|
| `/cap <name>` | Switch to a different capability |

Valid names: `chat`, `ask_questions`, `deep_solve`, `deep_question`, `deep_research`, `visualize`, `math_animator`, `mastery_path`, `immersive_reading`, `video_lesson`, `audio_overview`. CLI aliases also work — `ask`, `solve`, `quiz`, `research`, `viz`, `animate`, `mastery`, `reading` / `read`, `lesson`, and `audio-overview` / `overview`.

Note that `immersive_reading` runs the loop without a reader: the CLI has no viewport to scroll and no selection to act on, so use it for the web UI (see [Immersive Reading](/explore/reading/)).

```text
You> /cap deep_solve
[dim]capability=deep_solve ...[/]
You> Find d/dx [sin(x²)]
```

### Tools

```text
/tool on <name>     # Enable a tool for next turn
/tool off <name>    # Disable it
```

Valid toggles are the same ones exposed in the Web UI — `brainstorm`, `web_search`, `paper_search`, `zotero_search`, `reason`, `geogebra_analysis`, and `imagegen` / `videogen` once a generation model is configured. `rag`, `exec`, `read_memory`, `web_fetch`, `write_note`, `cron`, and other context-gated tools cannot be forced with `/tool`; they mount automatically when their context calls for them.

### Knowledge Bases

```text
/kb <name>          # Attach a KB (replaces any current attachment)
/kb none            # Detach
```

### History references

Tell the model about prior sessions it should treat as context (without copy-pasting):

```text
/history add sess_prior_xyz
/history clear
```

This is how you build cross-session context — perfect for "follow-up" research turns.

### Notebook references

Bring in specific records from your notebooks:

```text
/notebook add my-notes:rec_abc123,rec_def456
/notebook clear
```

### Config overrides

Per-capability config that applies to subsequent turns:

```text
/config show                       # Print current config
/config set num_questions 5
/config set difficulty=hard
/config set difficulty hard
/config clear                      # Reset to defaults
```

For example, with `--capability deep_question`:

```text
You> /config set num_questions 8
You> /config set question_types '["short_answer","mcq"]'
You> Generate questions on linear regression
```

### Inspecting tool results

Tool results are truncated to the first 10 lines / 240 chars per line, while streamed thinking is collapsed to one indicator. Both kinds of captured block share `/show` indices:

```text
/show last          # Last tool result or thinking block
/show 3             # The third captured block in this session
```

Up to 32 tool results and thinking blocks are buffered together for expansion.

### `/refs`

Print everything that will go into the next turn:

```text
You> /refs
[bold]Current state:[/]
  session     sess_abc123
  capability  chat
  tools       [rag, reason]
  kb          [physics, math]
  history     [sess_old_xyz]
  notebooks   [my-notes:rec_abc123]
  language    en
  config      {"difficulty": "hard", "num_questions": 5}
```

## How streaming works in the REPL

Each turn is rendered stage by stage. You'll see, in order:

| Indicator | Meaning |
|-----------|---------|
| `▶ <stage>` | Non-chat stage begins; chat hides `responding` |
| `  ✻ thinking…` | Reasoning captured for `/show` |
| `  ● <tool>(...)` | A tool was just invoked |
| `  │ <line>` | A line of tool output |
| `  └ #N <tool> — +M more lines; run /show N to expand` | Tool result was truncated |
| *plain text* | Final markdown response, rendered |

`ask_user` displays a question card; `answer>` replies resume the turn, while Ctrl-C aborts it.

## Tips

### Multi-line input

For multi-line messages (code snippets, long prompts), end each line with a backslash `\` and press Enter:

```text
You> Please review this Python code:\
def fib(n):\
    if n < 2: return n\
    return fib(n-1) + fib(n-2)
```

### Switching capabilities mid-session

You can freely switch capabilities within a session — DeepTutor keeps the conversation context. A common pattern:

```text
You> /cap deep_research
You> /config set mode=report
You> /config set depth=standard
You> Survey recent papers on RAG (2024–2026)
[long research turn]

You> /config clear
You> /cap chat
You> Now write a 3-paragraph summary suitable for a non-technical audience

You> /cap deep_question
You> /config set num_questions 5
You> Generate quiz questions about those papers
```

All three turns share context; clear config before switching incompatible capability schemas.

### Saving the session log

Sessions are stored in the shared session database. To export a clean markdown transcript:

```bash
deeptutor session show sess_abc123 --format json | \
  jq -r '.messages[] | "**" + .role + "**: " + .content + "\n"' > transcript.md
```

### Going from REPL → notebook

Like a turn? Save it to a notebook:

```bash
# In the REPL
You> /quit

# Then from shell, capture the assistant's last message
deeptutor session show sess_abc123 --format json | \
  jq -r '.messages[-1].content' > my-answer.md

deeptutor notebook add-md my-notes my-answer.md --title "Chain rule explanation"
```

## See also

- [**Commands**](/cli/commands/) — full reference for `run`, `kb`, `partner`, etc.
- [**Agent handoff**](/cli/agent-handoff/) — letting an agent do this for you
