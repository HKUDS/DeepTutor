---
title: Install from PyPI
description: Understand the published package layout, the modular full profile, and migration while preserving runtime data.
---

This page explains the **1.7.0** modular family and migration from the **1.6.15** package layout. Choose the full profile for the Web app or core for terminal chat. For current development features, use [Install from Source](/get-started/from-source/) or build a complete matching local wheel family in a separate environment.

The 1.6.15 full package includes the Web app and CLI. In 1.7.0, **`deeptutor` is core CLI/SDK**, **`deeptutor-cli` is a compatibility alias**, and **`deeptutor[full]` selects the full Web application**. Feature wheels must match the core version. Use Python 3.11–3.14 and Node.js 22 LTS for the current development setup.

## Install

```bash
mkdir -p my-deeptutor && cd my-deeptutor
python -m pip install "deeptutor[full]==1.7.0"
deeptutor init     # prompts for ports + LLM provider + optional embedding/search
deeptutor start    # starts backend + frontend; keep the terminal open
```

`deeptutor init` prompts for:

- **Backend port** (default `8001`)
- **Frontend port** (default `3782`)
- **LLM provider** / base URL / API key / model
- **Optional embedding provider** for Knowledge Base / RAG
- **Optional search provider** for Web Search

After `deeptutor start`, open the frontend URL printed in the terminal — by default <http://127.0.0.1:3782>. Press `Ctrl+C` in that terminal to stop both backend and frontend.

> Skipping `deeptutor init` is fine for a quick trial; the app boots with default ports and empty model settings. Configure them later in **Settings → Models & services**: Providers, Language models, Task Models, Embedding, Search, Voice, and Multimodal generation.

## Modular installation after publication

For the 1.7.0 wheel family, choose the required installation profile in a separate wheel environment:

```bash
python -m pip install "deeptutor[full]==1.7.0"  # Web + CLI + feature modules
# Or core only:
python -m pip install "deeptutor==1.7.0"
```

When migrating an old `deeptutor-cli` install, stop DeepTutor, back up its runtime home, and uninstall the old alias **before** installing the new family: `python -m pip uninstall deeptutor-cli`. Its legacy wheel owns files that the new core needs. Preserve `DEEPTUTOR_HOME`, then check `python -m pip check` and `deeptutor module list` before restarting. Upgrading bare core alone does not retain the full application profile.

## Trying pre-releases

Plain `pip install -U deeptutor` stays on stable — PyPI skips pre-release versions (e.g. `1.X.0b0` betas) unless you opt in:

```bash
pip install --pre -U "deeptutor[full]"
# or pin an exact version:
pip install -U "deeptutor[full]==<version>"
```

## Optional extras

For the published 1.6.15 layout, the full PyPI wheel includes Web + CLI. The 1.7.0 family instead uses `[full]` for those modules. Add-ons install as extras — e.g. all built-in Partner channel SDKs (WeCom, QQ, Slack, Feishu, Telegram, DingTalk, …):

```bash
pip install -U "deeptutor[partners]"
```

The full extras table (`matrix`, `matrix-e2e`, `math-animator`, `dev`, `all`) is in [**Install from Source**](/get-started/from-source/#optional-install-extras) — the same extra names work against the PyPI package.

## Where things live

The workspace lives under the directory you launched from (the `data/` folder appears there on first start). Override with:

```bash
DEEPTUTOR_HOME=/opt/deeptutor deeptutor start
# or
deeptutor start --home /opt/deeptutor
```

Layout (created on first init):

```text
my-deeptutor/
└── data/
    ├── memory/
    └── user/
        ├── settings/
        │   ├── system.json
        │   ├── auth.json
        │   ├── integrations.json
        │   ├── interface.json
        │   ├── model_catalog.json
        │   ├── document_parsing.json
        │   ├── pageindex.json
        │   ├── ima.json
        │   ├── llamaindex.json
        │   ├── graphrag.json
        │   ├── lightrag.json
        │   ├── lightrag_server.json
        │   ├── main.yaml
        │   └── agents.yaml
        └── workspace/
```

See [**Configuration Reference**](#config-files-under-datausersettings) below for what each file controls.

## What `deeptutor` can do once installed

Pop into the CLI any time without leaving the workspace:

```bash
deeptutor chat                                          # interactive REPL
deeptutor run chat "Explain the Fourier transform"      # one-shot
deeptutor kb create my-kb --doc textbook.pdf            # build a KB
deeptutor memory show                                   # inspect memory
deeptutor config show                                   # current config
```

Full surface: [**DeepTutor CLI**](/cli/).

## Updating

```bash
pip install --upgrade "deeptutor[full]"
deeptutor start
```

Workspace is preserved across upgrades.

The browser's **Settings → About** page checks stable releases, but its automatic command upgrades bare core. For a full modular installation or migration from 1.6.15, stop the app and use the `[full]` command above; uninstall a legacy CLI package first. Preserve your runtime home and inspect `deeptutor module list`. Source and Docker installs follow their own update paths.

## Config files under `data/user/settings/`

Everything under `data/user/settings/` is plain JSON / YAML. The **Settings** page in the browser is the recommended editor.

| File | Purpose |
|------|---------|
| `model_catalog.json` | Connections and profiles for LLM, task, embedding, search, TTS, STT, image, and video services |
| `document_parsing.json`, `pageindex.json`, `ima.json`, `llamaindex.json`, `graphrag.json`, `lightrag.json`, `lightrag_server.json` | Document-parsing and Knowledge Base engine settings |
| `system.json` | Backend / frontend ports, public API base, CORS, SSL verification, attachment directory and upload/extraction limits |
| `auth.json` | Optional auth toggle, username, password hash, token / cookie settings |
| `integrations.json` | Optional PocketBase and sidecar integration settings |
| `interface.json` | UI and model output language / theme / sidebar preferences |
| `main.yaml` | Runtime behavior defaults and path injection |
| `agents.yaml` | Capability / tool temperature and token settings |

> Project-root `.env` is **not** read as an application config file. Configure providers from **Settings → Models & services** in the browser, or by editing `model_catalog.json` directly.

## Common errors

### `python: command not found` on macOS

```bash
python3 -m pip install -U "deeptutor[full]"
python3 -m deeptutor init   # or just `deeptutor init` if entry point is on PATH
```

### Node.js not on PATH

`deeptutor start` spawns the packaged Next.js server, which needs `node` on PATH. Install Node 22 LTS from <https://nodejs.org> or via `brew install node@22`.

### Port `3782` (or `8001`) already in use

```bash
lsof -i :3782          # macOS
ss -ltnp | grep :3782  # Linux
```

Kill it or change the port via `deeptutor init` re-run.

### LLM provider 401 Unauthorized

API key was rejected. Re-enter it in **Settings → Language models**, or:

```bash
deeptutor init   # re-runs the wizard, preserves the workspace
```

For more, see [**Troubleshooting**](/get-started/troubleshooting/).

## Next

- [**Explore DeepTutor**](/explore/) — tour the running app
- [**Multi-User Deployment**](/get-started/multi-user/) — turn it into a team server
