---
title: Troubleshooting
description: Common errors across install paths, with copy-pasteable fixes.
---

If your install isn't behaving, run `deeptutor doctor` first — it reports what is missing or misconfigured. Then find your symptom below. Errors are grouped by category.

## Ports and processes

### `Address already in use :3782` (or :8001)

Something else is bound to the port. Find it:

```bash
# macOS
lsof -i :3782

# Linux
ss -ltnp | grep :3782

# Windows PowerShell
Get-NetTCPConnection -LocalPort 3782
```

Kill it, or change the DeepTutor port by re-running the setup wizard or editing `data/user/settings/system.json`:

```bash
deeptutor init
```

```json
{
  "backend_port": 18001,
  "frontend_port": 4000
}
```

For a one-off process override, export environment variables in the shell before starting DeepTutor: `BACKEND_PORT=18001 FRONTEND_PORT=4000 deeptutor start`.

If you're using Docker, override the docker-specific ports instead:

```bash
DEEPTUTOR_DOCKER_FRONTEND_PORT=4000
DEEPTUTOR_DOCKER_BACKEND_PORT=18001
```

### Backend starts but frontend can't reach it

The frontend proxies `/api/*` and `/ws/*` to the backend server-side, so when
you serve DeepTutor under a different hostname (cloud deployment, LAN access,
reverse proxy) the browser just uses the frontend origin — point clients and any
reverse proxy at the frontend port and you're done. No API base to configure.

You only need an explicit API base for a **split deployment**, where the backend
runs separately from the frontend. Open **Settings -> Network** or set
`next_public_api_base` in `data/user/settings/system.json` to the in-network
address the frontend server uses to reach the backend, then restart:

```json
{
  "next_public_api_base": "http://backend:8001"
}
```

`next_public_api_base_external` (and its alias `public_api_base`) are accepted as
lower-precedence fallbacks.

If auth is enabled and the frontend origin differs from the API origin, also
set exact CORS origins:

```json
{
  "cors_origins": ["https://deeptutor.example.com"]
}
```

## LLM / Embedding providers

### `HTTPError 401 Unauthorized` during provider probe

The provider rejected your API key. Common gotchas:

- **OpenAI**: starts with `sk-` (project keys start with `sk-proj-`)
- **Anthropic**: starts with `sk-ant-`
- **Azure OpenAI**: enter **API Version** in the active profile under Settings → Language models
- **Google Gemini**: starts with `AIza`
- **Ollama / local OpenAI-compatible**: leave the API key blank or use `none`, set the base URL like `http://localhost:11434/v1`

Re-run `deeptutor init` to re-enter the key, or edit `data/user/settings/model_catalog.json` directly.

### `Failed to fetch /models` during setup

DeepTutor pings the provider's model-list endpoint to populate the model dropdown. If your network blocks it, you'll see this warning — it's **non-fatal**. The wizard falls back to a hardcoded list of common models and continues.

### `host.docker.internal` not resolving (Docker + local Ollama)

| Host OS | Use |
|---------|-----|
| macOS, Windows | `http://host.docker.internal:11434/v1` |
| Linux | `http://172.17.0.1:11434/v1` *(docker0 bridge)* or the host's LAN IP |

Linux users can also add `host.docker.internal` manually:

```yaml
# docker-compose.ghcr.yml
services:
  deeptutor:
    extra_hosts:
      - "host.docker.internal:host-gateway"
```

### `Embedding dimension mismatch` when querying a KB

You re-indexed a KB with a different embedding model. The cached dimension no longer matches.

Fix: in the Web UI, navigate to **Knowledge → select KB → Index versions → Re-index now**. Re-indexing isn't exposed as a CLI command.

### Embedding endpoint URL keeps coming back wrong

Embedding adapters use the profile's **Base URL** verbatim, so enter the full endpoint under Settings → Embedding models, not just the API root:

| Provider | Wrong | Right |
|----------|-------|-------|
| OpenAI | `https://api.openai.com/v1` | `https://api.openai.com/v1/embeddings` |
| Cohere | `https://api.cohere.com` | `https://api.cohere.com/v2/embed` |
| Jina | `https://api.jina.ai/v1` | `https://api.jina.ai/v1/embeddings` |

## Knowledge Bases

### KB stuck in `indexing` state

Indexing happens in a background task. Check logs:

```bash
tail -f data/user/logs/deeptutor.jsonl | grep -i kb
```

Common causes: embedding provider returned 429 (rate limit — retry with smaller batches), embedding host unreachable (check connection), or PDF parser failed (check the file isn't password-protected).

### Reindex doesn't fix dimension mismatch

If the dimension mismatch error persists after reindex, the KB store may have a stale config file. From the CLI:

```bash
deeptutor kb delete physics --force
deeptutor kb create physics --doc chapter1.pdf
```

## Multi-user

### `401 Unauthorized` on every API call after restart

`data/system/auth/auth_secret` was lost or regenerated, invalidating every JWT.

Fix: restore `data/system/auth/auth_secret` from backup, or accept the new secret and ask all users to log in again. Project-root `.env` files are not auto-loaded by the runtime.

### First user wasn't promoted to admin

Edit `data/system/auth/users.json`, set `"role": "admin"` for the user, restart.

### Login works but redirects back to `/login`

The auth cookie isn't being set, usually because:

1. `auth.json: cookie_secure=false` on a cross-site HTTPS deployment — set it `true` and restart so the cookie uses `SameSite=None; Secure`
2. `auth.json: cookie_secure=true` during local HTTP testing — set it `false`
3. The browser blocks third-party cookies and you're on a subdomain — serve frontend and API from the same hostname (e.g., both at `deeptutor.example.com`, frontend on `/`, API proxied at `/api/`)

## Docker

### Container exits immediately

```bash
docker logs deeptutor | tail -30
```

For a source-tree Compose deployment, keep the `./data:/app/data` bind mount and check host-path permissions before retrying through the wrapper:

```bash
mkdir -p data
python scripts/docker_compose.py up -d
```

### Container is `Running` but `unhealthy`

The healthcheck probes the backend from inside the container and has a 60-second start period. If startup takes longer, the container can become `unhealthy`.

If it stays unhealthy, run the image's healthcheck directly and inspect container logs:

```bash
docker exec deeptutor python /app/healthcheck.py
docker logs deeptutor | tail -40
```

### npm install times out during build

The Next.js dep tree is large. Bump npm's network timeout:

```bash
npm config set fetch-timeout 600000
```

The official `Dockerfile` already sets this — only matters if you're building locally.

## Python install

### `Microsoft Visual C++ 14.0 is required` (Windows)

A dependency has fallen back to a Windows source build. Install [**Build Tools for Visual Studio**](https://visualstudio.microsoft.com/visual-cpp-build-tools/) with the "Desktop development with C++" workload, then retry the install.

### `libolm not found` (Matrix E2EE only)

```bash
# macOS
brew install libolm

# Debian / Ubuntu
sudo apt install libolm-dev

# Reinstall the matrix-e2e extra
python scripts/install_extras.py matrix-e2e
```

### `pip install` is glacially slow

Use a local PyPI mirror or wheelhouse if you're on a slow connection. For China-based users:

```bash
pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple
```

### Conda environment activated but `python` still points elsewhere

PATH ordering can shadow conda's python. Verify:

```bash
which python
# /Users/you/miniconda3/envs/deeptutor/bin/python
```

If not, run `conda activate deeptutor` in a fresh shell.

## Frontend

### Frontend shows a blank page

Open the browser dev tools (⌥⌘I) and check the Console tab. Common causes:

- **CORS errors** — frontend at one origin, backend at another, and the backend isn't on the allowed-origins list. Edit `data/user/settings/system.json` and add your frontend origin to `cors_origins`.
- **404 on `/_next/...`** — the static bundle wasn't built. From source: `cd web && npm run build`.
- **Backend not reachable** — verify `curl http://localhost:8001/` returns JSON.

### "Failed to fetch" toast on every page

Same as above — usually backend isn't running or CORS / API base URL mismatch. Check the Network tab to see what URL the request goes to.

## Partners & channels

### Partner channel grayed out in the Channels panel / "missing SDK"

When a channel's SDK can't be imported, the Partners **Channels** panel disables that channel and shows the import error (e.g. `No module named 'lark_oapi'`); starting the partner from the CLI reports the same error. Install the missing dependency set, then restart DeepTutor:

```bash
python scripts/install_extras.py partners           # all built-in channel SDKs (source install)
pip install -U "deeptutor[partners]"   # same, for the PyPI install
python scripts/install_extras.py matrix             # Matrix channel; ".[matrix-e2e]" for encrypted rooms (needs libolm)
```

For current `dev`, source CLI users use the same checkout and source dependency flow as Web users. `deeptutor-cli` is now a metadata-only core alias. Do not install its legacy editable packaging directory; use the source helper or generated requirements:

```bash
python -m pip install -r requirements/partners.txt
```

The channel comes back once the package is installed and the server restarted.

### Partner connects but doesn't respond

Check `allow_from` in the channel card:

```yaml
weixin:
  enabled: true
  allow_from:               # empty = deny everyone
    - "*"                    # allow all
    # - "sender-id"          # or specific user/chat ids after testing
```

By default `allow_from: []` denies everyone — you have to explicitly opt users in.

### Channel disconnects after a few minutes

Long-poll / WebSocket connections drop occasionally. The channel manager auto-reconnects with backoff, but if you see frequent drops:

- Check network stability between the host and the gateway provider
- For WeChat, confirm `state_dir` is writable and persisted
- For Teams/webhook-style channels, confirm the public callback URL reaches the configured host/port/path
- For Matrix, verify the homeserver is not aggressively timing out

See [**Partners & Channels**](/partners/) and the [**Channel Matrix**](/partners/channels/) for channel-specific debugging.

## Memory / RAG accuracy

### Chat ignores the attached KB

Make sure:

1. Check the active KBs: untouched conversations inherit ready workspace assignments or the default KB; explicit choices, including none, override inheritance.
2. The `rag` tool is context-gated and absent from Settings → Tools; attach a KB that uses it (PageIndex uses its own tools)
3. The KB has `status: ready` (not still indexing) — check via `deeptutor kb list`

### `read_memory` returns empty

`read_memory` concatenates the four L3 documents:

- `preferences` is written directly by `write_memory`
- `recent`, `profile`, and `scope` are consolidated only from the Memory Workbench

No every-N-turn scheduler fills them automatically.

Run **Update** there, or call the API with the required layer, key, and mode:

```bash
curl -X POST http://localhost:8001/api/memory/runs/start \
  -H 'Content-Type: application/json' \
  -d '{"layer":"L3","key":"recent","mode":"update"}'
```

### Memory writes are getting flagged as `unsafe_text`

`write_memory` accepts preference text from 1 to 240 characters. There is no `unsafe_text` result or content-safety filter; shorten text that exceeds the limit.

## Still stuck?

- Ask on [Discord](https://discord.gg/eRsjPgMU4t)
- File a bug at [github.com/HKUDS/DeepTutor/issues](https://github.com/HKUDS/DeepTutor/issues)
- Long-form question? Open a [Discussion](https://github.com/HKUDS/DeepTutor/discussions)

When asking for help, include:

- Your install path (PyPI / From Source / Docker / CLI-Only)
- Output of `deeptutor config show`
- Last 40 lines of `data/user/logs/deeptutor.jsonl`
- For Docker: `docker logs deeptutor | tail -40`
