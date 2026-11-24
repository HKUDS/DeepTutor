---
title: Command Reference
description: Common deeptutor commands — flags, output schemas, examples.
---

This page documents commonly used `deeptutor` subcommands and flags. For interactive REPL usage, see [**Interactive REPL**](/cli/chat-repl/). For automation patterns, see [**Agent handoff**](/cli/agent-handoff/).

## `deeptutor run` — single-turn capability execution

Run one capability turn and exit. The fundamental "do-something" command for agents and scripting.

```bash
deeptutor run <capability> "<message>" [options]
```

Built-ins: `chat`, `ask_questions`, `deep_solve`, `deep_question`, `deep_research`, `visualize`, `math_animator`, `mastery_path`, `immersive_reading`, `video_lesson` (alias `lesson`), and `audio_overview` (aliases `audio-overview`, `overview`).

### Flags

| Flag | Type | Default | What it does |
|------|------|---------|--------------|
| `--session <id>` | string | *(new)* | Resume an existing session |
| `-t / --tool <name>` | repeatable | `[]` | Select from the eight user-toggleable tools; context/capability gates still apply |
| `--kb <name>` | repeatable | `[]` | Attach a Knowledge Base |
| `--notebook-ref <id[:record,...]>` | repeatable | `[]` | Attach notebook records |
| `--history-ref <session_id>` | repeatable | `[]` | Reference a prior session |
| `-l / --language <code>` | string | `en` | Response language |
| `--config <key=value>` | repeatable | `[]` | Per-capability config override |
| `--config-json <json>` | string | — | Base config as JSON; repeated `--config key=value` flags override matching keys |
| `-f / --format <value>` | string | `rich` | Exactly `json` emits NDJSON; every other value uses rich output |

### Examples

```bash
# Simple chat turn
deeptutor run chat "Explain quantum entanglement in plain English"

# Deep Solve with reasoning + auto-mounted RAG against a KB
deeptutor run deep_solve "Find d/dx [sin(x²)]" --tool reason --kb math

# Generate 5 quiz questions
deeptutor run deep_question "Linear algebra eigenvectors" \
  --config num_questions=5 --config difficulty=hard

# Deep Research, JSON stream
deeptutor run deep_research "What's new in retrieval-augmented generation?" \
  --tool web_search --kb papers \
  --config mode=report --config depth=standard \
  --format json

# Resume a session
deeptutor run chat "Continue from where we left off" --session sess_abc123
```

### Output — `--format rich` (default)

Rich Markdown. Deep Solve has one `responding` stage; chat hides its banner. Sample:

```text
  ✻ thinking…
  ● rag(query=chain rule, kb_name=math)
  │ Chain rule: d/dx[f(g(x))] = f'(g(x)) · g'(x)
  └ #1 rag — +5 more lines; run /show 1 to expand

  ✻ thinking…

The derivative of sin(x²) is:

**2x · cos(x²)**

[dim]session=sess_abc123 turn=turn_xyz789 capability=deep_solve rounds=2 tools=1[/]
```

### Output — `--format json`

One JSON object per line. Useful for piping into other tools:

```text
{"type": "stage_start", "stage": "responding"}
{"type": "tool_call", "content": "rag", "metadata": {"args": {"query": "chain rule", "kb_name": "math"}}}
{"type": "tool_result", "content": "Chain rule: ...", "metadata": {"tool": "rag"}}
{"type": "content", "content": "The derivative of sin(x²) is **2x · cos(x²)**", "metadata": {"call_id": "round-2", "trace_kind": "llm_chunk"}}
{"type": "progress", "content": "", "metadata": {"call_id": "round-2", "trace_kind": "call_status", "call_state": "complete", "call_role": "finish"}}
{"type": "stage_end", "stage": "responding"}
{"type": "result", "metadata": {"response": "The derivative of sin(x²) is **2x · cos(x²)**"}}
{"type": "done", "session_id": "sess_abc123", "turn_id": "turn_xyz789", "metadata": {"status": "completed"}}
```

Event types: `stage_start`, `stage_end`, `thinking`, `observation`, `content`, `tool_call`, `tool_result`, `progress`, `sources`, `result`, `error`, `session`, `session_meta`, `done`, `wait_for_input`.

## `deeptutor chat` — interactive REPL

Drop into an interactive chat session with `/slash` commands for in-session configuration.

```bash
deeptutor chat [options]
```

Options mirror the turn-shaping flags from `run`: `--session`, `--tool / -t`, `--capability / -c`, `--kb`, `--notebook-ref`, `--history-ref`, `--language / -l`, `--config`, and `--config-json`. Full walkthrough at [**Interactive REPL**](/cli/chat-repl/).

## `deeptutor init` — guided setup wizard

```bash
deeptutor init                # Full setup (asks ports + LLM + embedding + search)
deeptutor init --cli          # CLI-only (skips port questions)
deeptutor init --home /path   # Use a non-default workspace
```

See [**Get Started**](/get-started/) for the full walkthrough.

## `deeptutor doctor` — is this workspace ready?

Answers one question before you go looking for a symptom: can DeepTutor
start a session here? Everything is read from local settings, so the
default run touches no network.

```bash
deeptutor doctor                  # Read local settings only
deeptutor doctor --online         # Also send one small request to the provider
deeptutor doctor --format json    # The same report, machine-readable (--format / -f)
deeptutor doctor runtime          # Different report: v2 turn coordination + repository
```

Six checks run. These four checks are normally **required**: `LLM configuration`, `LLM
credentials`, `LLM endpoint`, and `Runtime storage` (the data root is
writable). `RAG prerequisites` is optional and reports failures as `WARN`.
`Provider response` is optional while skipped, but an attempted `--online`
probe is required: failure reports `FAIL` and makes the command exit 1.

| Status | Means |
|:---|:---|
| `PASS` | The check succeeded. |
| `FAIL` | A required check failed — fix this before starting. |
| `WARN` | An optional check failed; the feature it covers is unavailable. |
| `SKIP` | Nothing to check (no KBs configured, or `--online` not passed). |

**Exit code is 1 when any required check failed**, so `deeptutor doctor`
works as a gate in a container entrypoint or CI step. `--format json`
prints `{"ok", "online", "checks": [{"key", "label", "status", "detail",
"required"}]}` — read `ok` rather than parsing the table.

## `deeptutor start` / `deeptutor serve`

```bash
# Launch both backend + frontend (blocking; Ctrl+C stops both)
deeptutor start
deeptutor start --home /path
deeptutor start --dev                   # Frontend HMR instead of a production build
deeptutor start --detach                # Background; stop it later with deeptutor stop

# Backend only
deeptutor serve --host 0.0.0.0 --port 8001
deeptutor serve --reload                # Hot reload on file changes (dev only)
```

## `deeptutor kb` — Knowledge Base management

### `kb list`

```bash
deeptutor kb list                # Rich table
deeptutor kb list --format json    # --format / -f
```

JSON output:

```json
[
  {
    "name": "physics",
    "status": "ready",
    "documents": 12,
    "rag_provider": "llamaindex",
    "is_default": true
  },
  {
    "name": "math",
    "status": "indexing",
    "documents": 4,
    "rag_provider": "llamaindex",
    "is_default": false
  }
]
```

### `kb info <name>`

```bash
deeptutor kb info physics
```

Returns the KB's metadata, document list, statistics, and indexing state.

### `kb create <name>`

```bash
# Single document
deeptutor kb create physics --doc chapter1.pdf       # --doc / -d

# Multiple documents
deeptutor kb create physics --doc chapter1.pdf --doc chapter2.pdf --doc exercises.docx

# Entire directory
deeptutor kb create textbooks --docs-dir ./my-pdfs

deeptutor kb connect-kiwix wiki --server-url http://localhost:8080 --zim-name wikipedia_en
```

`kb create` supports text, PDF, Office, and EPUB; images require multimodal embedding and LLM support. `connect-kiwix` links a server ZIM without copying or indexing.

### `kb add <name>`

Incrementally add documents to an existing KB:

```bash
deeptutor kb add physics -d chapter3.pdf
deeptutor kb add physics --docs-dir ./supplements
```

### `kb delete <name>`

```bash
deeptutor kb delete physics              # Asks for confirmation
deeptutor kb delete physics --force      # Skip confirmation (--force / -f)
```

### `kb set-default <name>`

```bash
deeptutor kb set-default physics
```

This marks the workspace default. The CLI REPL still starts without a KB and sends only `--kb` or `/kb` selections.

### `kb search <name> <query>`

```bash
deeptutor kb search physics "What is angular momentum?"
deeptutor kb search physics "..." --mode hybrid --format json  # --format / -f
```

`--mode` is engine-specific: LlamaIndex ignores it; LightRAG=`naive|local|global|hybrid|mix` (default `hybrid`); GraphRAG=`local|global|drift|basic` (default `local`).

### `kb add-github-source <name>`

Register Markdown from a repository as a tracked source:

```bash
deeptutor kb add-github-source physics --repo owner/repo \
  --branch main --path docs/ --glob '*.md'
```

`--repo / -r` is required; `--branch / -b` defaults to `main`, `--path / -p` defaults to the repository root, and `--glob / -g` defaults to `*.md`.

### `kb remove-github-source <name>`

```bash
deeptutor kb remove-github-source physics --source-id <id>
```

`--source-id / -s` identifies the registered source.

### `kb add-web-source <name>`

Register a bounded documentation-site crawl:

```bash
deeptutor kb add-web-source physics --url https://docs.example.com \
  --max-depth 3 --max-pages 200
```

`--url / -u` is required; crawl depth defaults to `3` and the page budget to `200`.

### `kb remove-web-source <name>`

```bash
deeptutor kb remove-web-source physics --source-id <id>  # --source-id / -s
```

### `kb list-sources <name>`

```bash
deeptutor kb list-sources physics
```

Lists the registered GitHub and web sources with their latest status and synced file/page counts.

### `kb sync <name>`

```bash
deeptutor kb sync physics
```

Immediately syncs every enabled GitHub and web source, showing its status and available change counts.

### Re-indexing

Re-indexing isn't a CLI command — it's done from the **Web UI** (Knowledge → pick KB → **Index versions** tab → **Re-index**). Useful after changing embedding models.

## `deeptutor skill` — skill library & hubs

`deeptutor skills` is a top-level alias for `deeptutor skill`. DeepTutor ships with **EduHub** — its open skill registry — built in, so there's nothing to configure: a bare slug or an `eduhub:` prefix resolves to it (`clawhub:` is also built in).

```bash
deeptutor skill list                              # Local skills, with hub provenance
deeptutor skill search "socratic tutor" --hub eduhub --limit 10
deeptutor skill install eduhub:socratic-tutor     # Verify → fetch → register
deeptutor skill install socratic-tutor@1.2.0      # Bare slug defaults to eduhub; @ pins a version
deeptutor skill install clawhub:gh-release-notes  # Other hubs resolve via their prefix
deeptutor skill remove socratic-tutor
```

Not a DeepTutor user? EduHub is a standalone, ClawHub-compatible registry — any skill-capable agent (Claude Code, Codex, …) can use it through the `eduhub` CLI: `npx eduhub skills install socratic-tutor`.

Hub references use `<hub>:<slug>[@version]` or the owner-qualified `<hub>:<owner>/<slug>[@version]`. Every install runs the same import gate: the hub's security verdict is checked first (flagged packages are refused unless you pass `--allow-unverified`), archives are extracted with zip-slip / zip-bomb guards, support files pass a text/script suffix whitelist so binaries never land in the workspace, and `always:` frontmatter is stripped so a downloaded package can't inject itself into every system prompt. Provenance (hub, version, verdict) is recorded in `.hub-lock.json` beside the skill.

`install` flags: `--name` installs under a different local name, `--force` replaces an existing skill, `--allow-unverified` proceeds past a suspicious verdict.

### Publishing your own

The same CLI is the authoring side of a hub. `login` opens a browser authorisation and stores the token locally; `publish` uploads a skill directory; `update` is the maintenance loop.

```bash
deeptutor skill login --no-browser                 # Print the auth URL instead of opening it
deeptutor skill publish ./my-skill --version 1.1.0 --token "$TOKEN" --yes
deeptutor skill update ./my-skill                  # Directory is optional; publish or roll back
deeptutor skill logout
```

All four take `--hub <name>` to target a hub other than the default. `publish` also takes `--slug`, `--track`, `--token`, and `--yes / -y`; `update [directory]` accepts `--token` if you would rather not keep a stored login.

Additional registries — or overriding a built-in, e.g. pointing `eduhub` at a self-hosted mirror — are declared in `settings/skill_hubs.json`: `type: "clawhub"` points at any compatible HTTP API, `type: "command"` wraps a fetch CLI that drops the package into `{dest}`, and `"default"` chooses the hub used for bare slugs. In a multi-user deployment this host CLI operates the admin workspace: an installed skill stays invisible to other users until a grant assigns it. By contrast, an authenticated user's Web **Install** action writes to that caller's private skill library; admin-assigned skills remain grant-scoped and read-only.

## `deeptutor session` — session inspection

### `session list`

```bash
deeptutor session list --limit 20
```

### `session show <id>`

```bash
deeptutor session show sess_abc123                 # Rich
deeptutor session show sess_abc123 --format json   # Full JSON
```

JSON output (truncated):

```json
{
  "id": "sess_abc123",
  "title": "Chain rule explanation",
  "capability": "chat",
  "status": "completed",
  "messages": [
    {"role": "user", "content": "..."},
    {"role": "assistant", "content": "..."}
  ],
  "preferences": {
    "tools": ["rag", "reason"],
    "knowledge_bases": ["math"],
    "language": "en"
  },
  "created_at": "2026-05-21T14:23:01Z",
  "updated_at": "2026-05-21T14:24:38Z"
}
```

### `session open <id>` / `session delete <id>` / `session rename <id> --title <title>`

```bash
deeptutor session open sess_abc123                    # Resume in REPL
deeptutor session rename sess_abc123 --title "Calculus review"
deeptutor session delete sess_abc123
```

## `deeptutor notebook` — notebook records

```bash
# Create a notebook
deeptutor notebook create research-notes --description "Daily reading log"

# Add a markdown record
deeptutor notebook add-md research-notes paper-summary.md \
  --title "Attention is all you need" --type research

# Replace a record's content
deeptutor notebook replace-md research-notes rec_abc123 updated-summary.md

# Remove a record
deeptutor notebook remove-record research-notes rec_abc123

# Inspect
deeptutor notebook list
deeptutor notebook show research-notes --format json
```

`show --format` is `rich|json`; types: `chat`, `question`, `research`, `solve`, `co_writer`, `tutorbot`, `reading`, `video_learning`.

## `deeptutor memory` — three-layer memory

DeepTutor stores user memory in three layers (see [**Memory**](/explore/memory/) for the deep dive):

- **L1** — raw event trace per surface (chat, notebook, quiz, etc.)
- **L2** — per-surface curated markdown summaries
- **L3** — cross-surface profile (recent, profile, scope, preferences)

### `memory show [target]`

```bash
deeptutor memory show                # Default: L3 concatenated
deeptutor memory show L3
deeptutor memory show L2             # List all L2 surfaces
deeptutor memory show profile        # A specific L3 doc
deeptutor memory show chat           # A specific L2 surface doc
```

### `memory clear [target]`

```bash
deeptutor memory clear all --force         # --force / -f; ⚠️ wipes L1+L2+L3
deeptutor memory clear trace               # Only L1
deeptutor memory clear chat                # Only L1 trace for the chat surface
```

### Forcing a consolidation pass

Manual consolidation isn't a CLI command — open an L2/L3 document in the Web UI (for example `/memory/l2/chat`), choose **Update memory**, then **Run**; or use the HTTP API:

```bash
curl -X POST http://localhost:8001/api/memory/runs/start \
  -H 'Content-Type: application/json' \
  -d '{"layer":"L2","key":"chat","mode":"update"}'
```

## `deeptutor partner` — Partner lifecycle

```bash
deeptutor partner list

deeptutor partner create math-tutor \
  -n "Math Mentor" \
  -s "Socratic tutor specializing in algebra and calculus" \
  -m gpt-4o

deeptutor partner stop math-tutor
deeptutor partner start math-tutor
```

Subcommands: `list`, `create`, `start`, `stop`. `create` writes partner config and attempts to start the partner. The Web UI is the recommended place to configure channel schemas, assets, tools, and secrets; the CLI is best for listing, creating, starting, and stopping.

Partners run inside `data/partners/<partner_id>/workspace/`. See [**Partners & Channels**](/partners/) for channel setup.

## `deeptutor config show`

```bash
deeptutor config show
```

Sample output:

```json
{
  "ports": {
    "backend": 8001,
    "frontend": 3782
  },
  "llm": {
    "binding_hint": "openai",
    "provider": "openai",
    "provider_mode": "standard",
    "model": "gpt-4o",
    "base_url": "https://api.openai.com/v1",
    "api_version": null,
    "extra_headers": {},
    "api_key": "***"
  },
  "embedding": {
    "status": "configured",
    "binding_hint": "openai",
    "provider": "openai",
    "provider_mode": "standard",
    "model": "text-embedding-3-large",
    "base_url": "https://api.openai.com/v1/embeddings",
    "api_version": null,
    "extra_headers": {},
    "dimension": 3072,
    "api_key": "***"
  },
  "search": {
    "provider": "tavily",
    "requested_provider": "tavily",
    "status": "ok",
    "fallback_reason": null,
    "base_url": "",
    "proxy": null,
    "api_key": "***"
  },
  "language": "en",
  "tools": ["rag", "web_search", "exec", "reason"]
}
```

API keys and extra-header values are masked.

## `deeptutor module` — optional feature modules

```bash
deeptutor module list
deeptutor module disable solve --dry-run
deeptutor module disable solve
deeptutor module enable solve
# In a separate wheel environment:
deeptutor module install solve --wheelhouse dist/modules
deeptutor module uninstall solve --dry-run
```

`list` reports installed, enabled, and ready states separately. Stop DeepTutor before module changes. Source checkouts support enable/disable, while install/uninstall require a wheel environment to protect tracked files. Dependencies constrain removal and disabling; inspect the dry-run plan before changing a shared deployment. Keep feature wheels at the core version and use `python -m pip check` after package changes.

## `deeptutor plugin` — registry inspection

```bash
deeptutor plugin list                  # Capabilities, tools, and plugin packages
deeptutor plugin info deep_solve       # Single capability
deeptutor plugin info rag              # Single tool
deeptutor plugin state                 # Installed/catalog/approval state
deeptutor plugin search                # Vendored catalog (currently empty)
deeptutor plugin show your-plugin      # Full package metadata
# Install a reviewed wheel, inspect its permissions, then approve and enable:
deeptutor plugin install ./plugin.whl --sha256 SHA256
deeptutor plugin approve your-plugin
deeptutor plugin enable your-plugin
deeptutor plugin disable your-plugin
deeptutor plugin rollback your-plugin  # Restore previous managed version
deeptutor plugin uninstall your-plugin
```

`plugin info <capability>` returns:

```json
{
  "name": "deep_solve",
  "description": "Multi-step problem solving driven by the chat agent loop.",
  "cli_aliases": ["solve"],
  "stages": ["responding"],
  "tools_used": ["solve_plan", "solve_finish_step", "solve_replan", "rag", "exec", "geogebra_analysis", "reason"],
  "config_defaults": {},
  "availability": {
    "available": true,
    "install_hint": ""
  }
}
```

## `deeptutor provider` — auth flows

For providers that use OAuth or special token flows:

```bash
deeptutor provider login openai-codex       # Browser OAuth against your ChatGPT plan
deeptutor provider login github-copilot     # GitHub device login + Copilot access check
deeptutor provider login codebuddy          # Aliases: codebuddy-code, workbuddy
```

## `deeptutor book` — Knowledge Books (Guided Learning)

```bash
deeptutor book list

# Health-check a book (KB drift + log staleness)
deeptutor book health book_abc123

# Re-snapshot fingerprints to clear "stale page" warnings
deeptutor book refresh-fingerprints book_abc123
```

Books are the storage layer for **Guided Learning** journeys. See [**Interactive Book**](/explore/book/).

## `deeptutor workspace` — Content Workspace

```bash
# Where is it, is it usable, how strong is the write boundary
deeptutor workspace show

# Point DeepTutor at an existing folder (must already exist)
deeptutor workspace set /absolute/path/to/my-folder

# Back to the built-in default
deeptutor workspace reset
```

The content workspace is the one folder agents may read; everything they create lands in its `outputs/`. `show` prints the path, its status, and the output security level — the strength of the boundary that keeps execution out of the rest of the folder. On Docker and server deployments the path is fixed at startup and `set` is refused. See [**Chat workspace**](/explore/chat-workspace/).

## Common output schemas

### TurnRequest (what `run` sends internally)

```python
class TurnRequest(BaseModel):
    content: str
    capability: str | None = "chat"
    session_id: str | None = None
    tools: list[str] | None = None
    knowledge_bases: list[str] = Field(default_factory=list)
    language: str | None = None
    config: dict[str, Any] = Field(default_factory=dict)
    notebook_references: list[NotebookReference] = Field(default_factory=list)
    history_references: list[str] = Field(default_factory=list)
    partner_group_references: list[dict[str, Any]] = Field(default_factory=list)
    attachments: list[OutgoingAttachment] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
```

### Stream event types

| Event | When | Fields |
|-------|------|--------|
| `stage_start` | A pipeline stage begins | `stage`, `metadata` |
| `stage_end` | Stage finishes | `stage` |
| `content` | User-facing markdown chunk | `content` |
| `thinking` | Reasoning | `content` |
| `observation` | Observation | `content` |
| `progress` | Status | `content` |
| `tool_call` | Invocation | `content`, `metadata.args` |
| `tool_result` | Return | `content`, `metadata.tool` |
| `sources` | Sources | `metadata.sources` |
| `result` | Result | `metadata` |
| `error` | Error | `content` |
| `session` | Identity | `metadata` |
| `session_meta` | Metadata update | `metadata` |
| `done` | Complete | top-level ids, `metadata.status` |
| `wait_for_input` | Input pause | `content` |

## See also

- [**Interactive REPL**](/cli/chat-repl/) — using `deeptutor chat` day-to-day
- [**Agent handoff**](/cli/agent-handoff/) — letting Claude Code / Codex drive the CLI
- [**Server API**](/cli/server-api/) — the HTTP / WebSocket surface from `deeptutor serve`
