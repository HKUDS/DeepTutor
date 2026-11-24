---
title: CLI-Only Install
description: Run current dev from the terminal without frontend setup; understand source CLI and the modular core wheels.
quadrant: how-to
---

For current `dev`, CLI use from source installs the main project and skips frontend Node/npm setup. A checkout contains all modules, so it still needs `requirements/full.txt`. The minimal 1.7.x core wheel supplies chat and SDK separately from feature modules; `deeptutor-cli` is a metadata-only core alias. Do not use the old editable `packaging/deeptutor-cli` project.

## Install

```bash
git clone --branch dev https://github.com/HKUDS/DeepTutor.git
cd DeepTutor

# Create a venv (macOS / Linux)
# Windows PowerShell:
#   py -3.11 -m venv .venv-cli ; .\.venv-cli\Scripts\Activate.ps1
python3 -m venv .venv-cli && source .venv-cli/bin/activate
python -m pip install --upgrade pip

python -m pip install -r requirements/full.txt
python -m pip install -e . --no-deps
deeptutor init --cli
deeptutor chat
```

`deeptutor init --cli` shares the same `data/user/settings/` layout as the full app but:

- **Skips** the backend / frontend port prompts
- **Defaults the embedding picker to the current provider, or OpenAI** (press `s` to skip if you do not need `deeptutor kb …` or RAG tools)
- Keeps Search optional — skip the provider picker if you do not need Web Search
- Still writes the core settings plus `document_parsing.json`, `pageindex.json`, `ima.json`, `llamaindex.json`, `graphrag.json`, and `lightrag.json`
- Still prompts for the active LLM provider and model

## When to use this

- You're running DeepTutor as a tool inside another agent's harness (Claude Code, Codex, OpenCode, etc.)
- Headless server / VM with no browser
- You want a fast install with no Node.js toolchain

## Common commands

```bash
deeptutor chat                                          # interactive REPL
deeptutor chat --capability deep_solve --kb my-kb
deeptutor run chat "Explain Fourier transform"
deeptutor run deep_solve "Solve x^2 = 4" --kb my-kb
deeptutor kb create my-kb --doc textbook.pdf
deeptutor memory show
deeptutor config show
```

Full surface: [**DeepTutor CLI**](/cli/).

## Source CLI and minimal core are different installs

The source path above exposes the same modules as the source Web app; it simply does not build or launch the frontend. Commands such as KB, notebook, memory, Partner, and advanced capabilities rely on their installed dependencies and enabled modules. It is not a smaller legacy CLI distribution.

| Installation | Included | How to inspect |
| --- | --- | --- |
| **Current source checkout** | Checked-in modules; full Python dependencies; no Node/npm required for terminal use | `deeptutor module list`, `deeptutor plugin list` |
| **1.7.x bare core wheel** | Shared runtime, chat, ask_questions, CLI, SDK, settings, and sessions | Add same-version feature wheels as needed |
| **1.7.x full profile** | Core plus Web/API and the standard feature modules | Install `[full]` from PyPI, or matching local wheels |

For example, `deep_solve` needs Solve; knowledge bases need Knowledge and configured retrieval services; Partners needs its module and channel SDKs. `--tool` accepts the eight user-toggleable tools only. Attach a KB with `--kb` and retrieval mounts according to context; `--tool rag` does not enable it.

To add Web to this source installation, install Node.js 22 LTS, run `npm ci --legacy-peer-deps` in `web/`, and use `deeptutor start` with the same runtime home. For a minimal wheel environment using local builds, build and install the matching family as described in [Modules](https://github.com/HKUDS/DeepTutor/blob/dev/docs-for-dev/MODULES.md).

## Adding optional channel dependencies

Stop DeepTutor before changing modules or dependencies. From the repository root, use the source helper:

```bash
python scripts/install_extras.py partners
python scripts/install_extras.py matrix       # plain Matrix rooms
# For encrypted Matrix rooms, install system libolm first:
python scripts/install_extras.py matrix-e2e
python -m pip check
deeptutor module list
```

Restart using the same `DEEPTUTOR_HOME`. Account Partner state is stored under `data/partners/<id>/`; choosing a content workspace for the Partner is separate from its runtime home. Channel credentials and private relationship histories remain Partner state. See [Partners](/explore/partners/).

## Use it from another agent

The CLI is **agent-native**. `deeptutor run --format json` emits one JSON event per line, and data-inspection commands such as `kb list`, `kb search`, `session show`, and `notebook show` expose JSON where implemented — useful for piping into another agent's harness.

Hand the [`SKILL.md`](https://github.com/HKUDS/DeepTutor/blob/main/SKILL.md) at the project root to any tool-using LLM and it can drive DeepTutor on its own. See [**Agent handoff**](/cli/agent-handoff/) for the patterns.

## Updating

```bash
cd DeepTutor
git pull
python -m pip install -r requirements/full.txt
python -m pip install -e . --no-deps
python -m pip check
deeptutor module list
```

## Common errors

### `deeptutor: command not found` after install

The console script wasn't placed on PATH. Verify the venv is activated, or call it directly:

```bash
python -m deeptutor_cli.main chat
```

### `ModuleNotFoundError: No module named 'fastapi'` when running `deeptutor serve`

The source flow above includes server dependencies, so this indicates an environment mismatch: check the active Python environment and reinstall `requirements/full.txt`. In a minimal wheel environment, add the matching Server module.

### Partner channel commands say an SDK is missing

Stop DeepTutor, then add the Partner dependency group from the source root:

```bash
python scripts/install_extras.py partners
```

More: [**Troubleshooting**](/get-started/troubleshooting/).

## Next

- [**DeepTutor CLI**](/cli/) — full CLI reference
- [**Agent handoff**](/cli/agent-handoff/) — let your agent drive
- [**Partners & Channels**](/partners/) — run a Partner from CLI
