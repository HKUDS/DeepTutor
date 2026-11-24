---
title: Install from Source
description: Option 2 — clone, install editable, hot-reload the frontend. For contributors and power users.
quadrant: how-to
---

For development against a checkout. Use **Python 3.11–3.14** and **Node.js 22 LTS** to match CI and Docker.

## Install

```bash
git clone --branch dev https://github.com/HKUDS/DeepTutor.git
cd DeepTutor

# Create a venv (macOS / Linux)
# Windows PowerShell:
#   py -3.11 -m venv .venv ; .\.venv\Scripts\Activate.ps1
python3 -m venv .venv && source .venv/bin/activate
python -m pip install --upgrade pip

# Install backend + frontend deps
python -m pip install -r requirements/full.txt
python -m pip install -e . --no-deps
( cd web && npm ci --legacy-peer-deps )

deeptutor init
deeptutor start --dev
```

`deeptutor start` builds the local `web/` frontend for production once and reuses it; `--dev` runs Next.js with HMR. Config layout, ports, and `Ctrl+C` match the [**PyPI install**](/get-started/pypi/).

Before changing modules or dependency groups, stop DeepTutor. Check `python -m pip check` and `deeptutor module list` after installation. In source, `module enable/disable` controls assembly; installing or uninstalling module wheels is reserved for a separate wheel environment. Keep the same runtime home when restarting.

## Conda instead of venv

```bash
conda create -n deeptutor python=3.11
conda activate deeptutor
python -m pip install --upgrade pip
# ...then continue with `pip install -r requirements/full.txt`, `pip install -e . --no-deps` and `npm ci`
```

## Optional install extras

Current `dev` exposes all source modules. Install `requirements/full.txt`, then register the editable source with `--no-deps`; do not overlay feature wheels on the checkout. Add optional dependencies with the source helper from the repository root:

```bash
python scripts/install_extras.py dev             # tests / lint tools
python scripts/install_extras.py partners        # all Partner channel SDKs (incl. wecom-aibot-sdk)
python scripts/install_extras.py matrix          # Matrix channel without E2EE / libolm
python scripts/install_extras.py matrix-e2e      # Matrix E2EE; requires libolm
python scripts/install_extras.py math-animator   # Manim addon; requires LaTeX / ffmpeg / system libs
```

Compose them: `python scripts/install_extras.py dev,partners,math-animator`.

The remote MCP client is part of the core full and CLI-only installs; it does not require the `partners` extra.

Module manifests own dependencies; generated `requirements/*.txt` support source, Docker, and CI installs. Extra templates live under `tool.deeptutor.optional-dependencies`; the helper expands internal module references into source dependencies. Common groups include:

| Extra | What it adds | Requirements mirror |
|-------|--------------|---------------------|
| `cli` | Compatibility extra — CLI deps, already included in the default install | `requirements/cli.txt` |
| `server` | API server module; included in full source requirements | `requirements/server.txt` |
| `partners` | Every built-in Partner channel SDK (`wecom-aibot-sdk`, `qq-botpy`, `slack-sdk`, `lark-oapi`, `python-telegram-bot`, `dingtalk-stream`, …) | `requirements/partners.txt` |
| `tutorbot` | Legacy alias for `partners`, kept for one release | — |
| `matrix` | Matrix (Element) channel, non-E2EE — works without libolm | `requirements/matrix.txt` |
| `matrix-e2e` | Matrix E2EE add-on — needs the system **libolm** library | `requirements/matrix-e2e.txt` |
| `math-animator` | Manim addon — needs LaTeX, pkg-config, cairo, cmake, ffmpeg | `requirements/math-animator.txt` |
| `graphrag` | The GraphRAG retrieval engine — knowledge-graph indexing, LLM-heavy; Python 3.11–3.13 | — |
| `rag-lightrag` | The LightRAG retrieval engine — graph + vector; parsing is selected separately | — |
| `rag-rerank` | Optional cross-encoder reranking for LlamaIndex; Python 3.11–3.13 | — |
| `video-learning` | Compatibility entry for Reading; absent from bare core | — |
| `parse` | Every optional document-parsing engine at once | — |
| `parse-docling` | Docling parsing — structured layout/table conversion | — |
| `parse-markitdown` | markitdown parsing — lightweight, broad formats → Markdown | — |
| `parse-pymupdf4llm` | PyMuPDF4LLM parsing — PDF / e-book / XPS / images / text → Markdown, no downloads | — |
| `parse-liteparse` | LiteParse parsing — lightweight structured parsing | — |
| `codebuddy` | The CodeBuddy / WorkBuddy provider SDK | — |
| `guard` | Optional HTTP request screening; disabled until `security_guard.enabled` is set | `requirements/guard.txt` |
| `dev` | pytest / pre-commit / lint & security tooling | `requirements/dev.txt` |
| `all` | full + Manim + development dependencies (select Matrix E2EE separately) | — |

### System dependencies for some extras

| Extra | System library |
|-------|----------------|
| `matrix-e2e` | **libolm**: `brew install libolm` (macOS) / `sudo apt install libolm-dev` (Debian) |
| `math-animator` | **LaTeX + ffmpeg**: `brew install --cask mactex && brew install ffmpeg` (macOS) / `sudo apt install texlive-full ffmpeg` (Linux) |

## Frontend dependency tweaks

When you add or upgrade a frontend dependency:

```bash
cd web
npm install --legacy-peer-deps
# commit both web/package.json and web/package-lock.json
```

## Dev-server troubleshooting

**Stuck dev server:** if `deeptutor start --dev` reports an existing frontend that isn't responding, stop the PID it prints. If no Next.js process is actually running, the lock files are stale — remove them and retry:

```bash
rm -f web/.next/dev/lock web/.next/lock
deeptutor start --dev
```

## Hot reload

The backend supports `--reload`. Start backend and frontend in separate terminals for the best dev loop:

```bash
# Terminal A — backend with hot reload
python -m uvicorn deeptutor.api.main:app \
  --host 0.0.0.0 --port 8001 \
  --reload --reload-exclude "web/*" --reload-exclude "data/*"

# Terminal B — frontend dev server
cd web && npm run dev -- -p 3782
```

## Updating

```bash
git pull
python -m pip install -r requirements/full.txt
python -m pip install -e . --no-deps
python -m pip check
deeptutor module list
cd web && npm ci --legacy-peer-deps
```

If a release bumped settings schema, also re-run `deeptutor init` to fill in newly-introduced fields. Existing config is preserved.

**Settings → About** identifies this as a source checkout and reports the current Git revision, but it does not pull, merge, or overwrite your working tree. Update source installs explicitly with Git so local branches and uncommitted changes stay under your control.

## Common errors

### `error: Microsoft Visual C++ 14.0 is required` (Windows)

Some Python deps compile C extensions. Install [**Build Tools for Visual Studio**](https://visualstudio.microsoft.com/visual-cpp-build-tools/) with "Desktop development with C++".

### `libolm` not found (when `matrix-e2e` is installed)

```bash
brew install libolm                   # macOS
sudo apt install libolm-dev           # Debian / Ubuntu
python scripts/install_extras.py matrix-e2e
```

### `npm ci` slow or times out

```bash
npm config set fetch-timeout 600000
cd web && npm ci --legacy-peer-deps
```

### Backend `--reload` thrashes on every save

You forgot the `--reload-exclude` flags. Restart with:

```bash
python -m uvicorn deeptutor.api.main:app \
  --host 0.0.0.0 --port 8001 \
  --reload --reload-exclude "web/*" --reload-exclude "data/*"
```

More fixes: [**Troubleshooting**](/get-started/troubleshooting/).

## Next

- [**DeepTutor CLI**](/cli/) — drive the CLI from the same workspace
- [**Explore DeepTutor**](/explore/) — tour the running app
