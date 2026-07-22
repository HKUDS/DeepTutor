# DeepTutor CLI Skill

> Teach your AI agent to configure, manage, and use DeepTutor — an intelligent learning platform — entirely through the command line.

## When to Use

Use this skill when the user wants to:
- Set up or configure DeepTutor
- Chat with DeepTutor or run a capability (deep solve, quiz generation, deep research, visualize, math animation, mastery path)
- Create, manage, or search knowledge bases
- Create, manage, or run Partners (IM-connected companions)
- Search, install, or manage skills from a hub (ClawHub)
- Inspect or maintain interactive Books
- View or manage learning memory, sessions, or notebooks
- Start the DeepTutor API server or the full Web app

## Prerequisites

- Python 3.11+
- DeepTutor installed: `pip install deeptutor` for the full Web app, `pip install deeptutor-cli` for CLI-only, or `pip install -e .` from a source checkout
- Run `deeptutor init` for first-time interactive setup. It walks a guided wizard (ports → LLM → embedding → search → review) and writes the same settings as the Web Settings page under `data/user/settings`. Add `--cli` to skip the ports step for CLI-only use, or `--home <path>` to target a specific workspace.

## Commands

### Chat & Capabilities

```bash
# Interactive REPL
deeptutor chat
deeptutor chat --capability deep_solve --kb my-kb --tool rag --tool web_search

# One-shot capability execution
deeptutor run chat "Explain Fourier transform"
deeptutor run deep_solve "Solve x^2 = 4" --tool rag --kb textbook
deeptutor run deep_question "Linear algebra" --config num_questions=5
deeptutor run deep_research "Attention mechanisms" --kb papers --config mode=report --config depth=standard
deeptutor run visualize "Plot the unit circle"
deeptutor run math_animator "Visualize a Fourier series"

# Capabilities accepted by `run` / `chat -c`:
#   chat, deep_solve, deep_question, deep_research, visualize, math_animator, mastery_path

# Options for `run`:
#   --session <id>         Resume existing session
#   --tool/-t <name>       Enable tool (repeatable)
#   --kb <name>            Knowledge base (repeatable)
#   --notebook-ref <ref>   Notebook reference, "<notebook_id>:<rec1>,<rec2>" (repeatable)
#   --history-ref <id>     Referenced session id (repeatable)
#   --language/-l <code>   Response language (default: en)
#   --config <key=value>   Capability config (repeatable)
#   --config-json <json>   Capability config as JSON
#   --format/-f <fmt>      Output format: rich | json (default: rich)
```

`deeptutor chat` accepts the same `--session / --tool / --kb / --notebook-ref / --history-ref / --language / --config / --config-json` options, plus `--capability/-c <name>` to set the initial capability.

**Tools** for `--tool` / `-t`: user-toggleable tools are `brainstorm`, `web_search`, `paper_search`, `reason`, `geogebra_analysis`, `imagegen`, and `videogen`. Context-gated tools (`rag`, `code_execution`, `read_source`, `web_fetch`, `github`, `ask_user`, …) auto-mount when their context is present, but can also be force-enabled with `--tool`. Run `deeptutor plugin list` for the full registered set.

### Knowledge Bases

```bash
deeptutor kb list [--format rich|json]              # List all knowledge bases
deeptutor kb info <name>                            # Show knowledge base details (JSON)
deeptutor kb create <name> --doc file.pdf           # Create from documents (--doc/-d repeatable)
deeptutor kb create <name> --docs-dir ./papers      # ...or from a directory of documents
deeptutor kb add <name> --doc more.pdf              # Add documents incrementally
deeptutor kb search <name> "query text" [--mode hybrid] [--format rich|json]
deeptutor kb set-default <name>                     # Set as default KB
deeptutor kb delete <name> [--force]                # Delete a knowledge base
```

### Partners

Partners are IM-connected learning companions (the former "TutorBot").

```bash
deeptutor partner list                              # List all partners
deeptutor partner create <id> -n "My Tutor"         # Create and start a new partner
#   -n/--name <text>   Display name
#   -s/--soul <md>     Soul markdown (the persona)
#   -m/--model <id>    Model override
deeptutor partner start <id>                        # Start a partner
deeptutor partner stop <id>                         # Stop a running partner
```

### Skills

Install and manage skills, including packages from external hubs (ClawHub).
Hub refs use `<hub>:<slug>[@version]` (the hub prefix defaults to `clawhub`).

```bash
deeptutor skill search "flashcards" [--hub clawhub] [--limit 10]
deeptutor skill install clawhub:some-skill[@1.2.0] [--name local-name] [--force] [--allow-unverified]
deeptutor skill list                                # List local skills (with hub provenance)
deeptutor skill remove <name>                       # Remove a user-layer skill
```

### Books

Maintenance commands for the BookEngine (authoring/reading is via the Web app).

```bash
deeptutor book list                                 # List all books (flags stale pages)
deeptutor book health <book_id>                     # Inspect KB drift + log.md health
deeptutor book refresh-fingerprints <book_id>       # Re-snapshot KB fingerprints
```

### Memory

```bash
deeptutor memory show [<target>]    # target: L3 (all global docs, default) | L2 (all surfaces) | a doc name (e.g. profile, chat)
deeptutor memory clear [<target>]   # target: all (default) | trace (all L1) | a surface name (clears that surface's L1)
#   --force/-f   Skip confirmation
```

### Sessions

```bash
deeptutor session list [--limit 20]                 # List sessions
deeptutor session show <id> [--format rich|json]    # View session messages
deeptutor session open <id>                         # Resume session in the REPL
deeptutor session rename <id> --title "..."         # Rename a session
deeptutor session delete <id>                       # Delete a session
```

### Notebooks

```bash
deeptutor notebook list                             # List notebooks
deeptutor notebook create <name> [--description "..."]
deeptutor notebook show <notebook_id> [--format rich|json]
deeptutor notebook add-md <notebook_id> <file.md> [--title "..."] [--type chat|question|research|solve]
deeptutor notebook replace-md <notebook_id> <record_id> <file.md>
deeptutor notebook remove-record <notebook_id> <record_id>
```

### Providers

```bash
deeptutor provider login openai-codex               # OAuth login for OpenAI Codex
deeptutor provider login github-copilot             # Validate an existing Copilot auth session
```

### System

```bash
deeptutor config show                               # Print resolved configuration
deeptutor plugin list                               # List registered tools and capabilities
deeptutor plugin info <name>                         # Show a tool/capability's schema + availability
deeptutor serve [--host 0.0.0.0] [--port 8001] [--reload]   # Start the API server
deeptutor start [--home <path>]                     # Launch backend + frontend together
deeptutor init [--cli] [--home <path>]              # Create/update workspace settings
```

## REPL Slash Commands

Inside `deeptutor chat`, use these:

| Command | Effect |
|:---|:---|
| `/quit` | Exit REPL |
| `/session` | Show current session id |
| `/status` | Print the current REPL state |
| `/new` or `/clear` | Start a new session context |
| `/regenerate` or `/retry` | Re-run the last user message |
| `/tool on\|off <name>` | Toggle a tool |
| `/cap <name>` | Switch capability |
| `/kb <name>\|none` | Set or clear knowledge base |
| `/history add <id>` / `/history clear` | Manage history references |
| `/notebook add <ref>` / `/notebook clear` | Manage notebook references |
| `/show last\|<n>` | Expand a captured tool result or thinking block |
| `/refs` | Show all active references |
| `/config show\|set\|clear` | Manage capability config |

## Typical Workflows

**First-time setup:**
```bash
cd DeepTutor
pip install -e .
deeptutor init        # Interactive guided setup (add --cli for CLI-only)
```

**Daily learning:**
```bash
deeptutor chat --kb textbook --tool rag --tool web_search
```

**Build a knowledge base from documents:**
```bash
deeptutor kb create physics --doc ch1.pdf --doc ch2.pdf
deeptutor run chat "Explain Newton's third law" --kb physics --tool rag
```

**Generate quiz questions:**
```bash
deeptutor run deep_question "Thermodynamics" --kb physics --config num_questions=5
```

**Run the full Web app locally:**
```bash
deeptutor start       # backend + frontend; Ctrl+C to stop
```
