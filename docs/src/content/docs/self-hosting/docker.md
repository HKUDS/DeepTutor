---
title: Docker operations
description: Volumes, ports, reverse proxies, local models, and upgrades for the published container.
quadrant: how-to
---

The first-run command stays on the [Docker tutorial](/get-started/docker/). This page is the rest of the deployment.

## Select a host content workspace

By default content workspace storage lives inside the `deeptutor-data` volume. To use a folder on the host instead, mount it at the stable container path `/workspace` and lock DeepTutor to it:

```bash
mkdir -p "$PWD/deeptutor-workspace/outputs"
docker run --rm --name deeptutor \
  -p 127.0.0.1:3782:3782 \
  -v deeptutor-data:/app/data \
  -v "$PWD/deeptutor-workspace:/workspace" \
  -e DEEPTUTOR_WORKSPACE_ROOT=/workspace \
  -e DEEPTUTOR_WORKSPACE_ALLOWED_ROOTS=/workspace \
  ghcr.io/hkuds/deeptutor:latest
```

Create `outputs/` yourself before the first run — otherwise Docker creates the bind source as root and the unprivileged app cannot write into it.

The container always sees `/workspace`, so paths stay portable across hosts. This deployment root constrains every account. Managed workspaces use account-scoped directories under `outputs/.deeptutor/chat/`; **Settings → Workspace** manages their identities and storage without exposing private runtime settings.

With Compose, set `DEEPTUTOR_WORKSPACE_HOST=/absolute/host/folder` before `python scripts/docker_compose.py up -d`; the helper creates the folder and its `outputs/` for you. Omit it to keep `./data/user/workspace`.

## Detached mode

Add `-d` to run in the background:

```bash
docker run -d --name deeptutor \
  -p 127.0.0.1:3782:3782 \
  -v deeptutor-data:/app/data \
  ghcr.io/hkuds/deeptutor:latest

docker logs -f deeptutor      # follow logs
docker stop deeptutor         # stop
docker rm deeptutor           # remove (volume persists)
```

The `deeptutor-data` volume keeps your settings and default content workspace across `stop` / `rm` cycles. To truly start over: `docker volume rm deeptutor-data`.

## Remote Docker / reverse proxy

The browser only ever talks to the frontend origin (`:3782`); the in-container
Next.js middleware forwards `/api/*` and `/ws/*` to the backend on
`localhost:8001` server-side. So for the common **single-container** case you do
**not** need to configure an API base at all — just point your reverse proxy /
TLS terminator at the published `:3782`:

```text
deeptutor.example.com {
    reverse_proxy localhost:3782
}
```

You only need an API base for a **split deployment**, where the backend runs in a
separate container or host. Set it in `data/user/settings/system.json` in the
mounted volume to the in-network address the **frontend server** uses to reach
the backend — it's read server-side by the proxy, not sent to the browser:

```json
{
  "next_public_api_base": "http://backend:8001"
}
```

`next_public_api_base_external` (and its alias `public_api_base`) are accepted as
lower-precedence fallbacks and normalized on save.

CORS only matters with auth enabled and a cross-origin frontend: `cors_origins`
lists the frontend page origins allowed to call the backend. With auth disabled,
DeepTutor permits normal HTTP/HTTPS browser origins by default.

```json
{
  "cors_origins": ["https://deeptutor.example.com"]
}
```

## Different host ports

Change the left side of the `-p host:container` mapping:

```bash
docker run --rm --name deeptutor \
  -p 127.0.0.1:8088:3782 \
  -v deeptutor-data:/app/data \
  ghcr.io/hkuds/deeptutor:latest
```

Add `-p 127.0.0.1:8089:8001` as well if you also want the API exposed on the host. If you change container-side ports in `/app/data/user/settings/system.json`, restart and update the right side of each mapping to match.

## Connecting to a local LLM (Ollama / LM Studio / llama.cpp / vLLM)

Inside Docker, `localhost` is the container itself, not your host machine. To reach a model service running on the host, use the host gateway:

```bash
docker run --rm --name deeptutor \
  -p 127.0.0.1:3782:3782 \
  --add-host=host.docker.internal:host-gateway \
  -v deeptutor-data:/app/data \
  ghcr.io/hkuds/deeptutor:latest
```

Then in **Settings → LLM** (or **Embedding**), point the provider Base URL at `host.docker.internal`:

| Service | Base URL |
|---------|----------|
| Ollama LLM | `http://host.docker.internal:11434/v1` |
| Ollama embedding | `http://host.docker.internal:11434/api/embed` |
| LM Studio | `http://host.docker.internal:1234/v1` |
| llama.cpp | `http://host.docker.internal:8080/v1` |

Docker Desktop (macOS / Windows) usually resolves `host.docker.internal` **without** `--add-host`. On Linux, the flag is the portable way to create that hostname on modern Docker Engine.

### Linux alternative — host networking

Add `--network=host` and drop the `-p` flags:

```bash
docker run --rm --name deeptutor \
  --network=host \
  -v deeptutor-data:/app/data \
  ghcr.io/hkuds/deeptutor:latest
```

The container shares the host network directly, so open <http://127.0.0.1:3782> (or the `frontend_port` in `system.json`), and host services can be reached with normal localhost URLs like `http://127.0.0.1:11434/v1`.

> Host networking exposes container ports directly on the host and may conflict with existing services.

## Updating

```bash
docker pull ghcr.io/hkuds/deeptutor:latest
docker rm -f deeptutor 2>/dev/null
docker run --rm --name deeptutor \
  -p 127.0.0.1:3782:3782 \
  -v deeptutor-data:/app/data \
  ghcr.io/hkuds/deeptutor:latest
```

The volume persists — your settings, KBs, memory all survive the upgrade.

**Settings → About** identifies the Docker image and can check whether a newer release exists, but container replacement remains a deployment action: pull the new image and recreate the container as shown above. DeepTutor never upgrades packages inside the running container.

## Common errors

### `Bind for 0.0.0.0:3782 failed: port is already allocated`

```bash
lsof -i :3782          # macOS
ss -ltnp | grep :3782  # Linux
```

Kill the conflicting process, or choose different host ports in your `-p` mapping.

### Container exits immediately

```bash
docker logs deeptutor | tail -30
```

An invalid LLM credential is caught and logged as a warning; it does **not** make backend startup fail. If the container exited, look in the log for a different fatal error. Once the Web UI is available, correct the credential under **Settings → Models & services**.

### Frontend loads but API calls fail (split deployment)

With the single-container image this shouldn't happen — the in-container proxy
forwards `/api/*` to the backend automatically. If you run a **split
deployment** with the backend in a separate container or host, set
`next_public_api_base` in `data/user/settings/system.json` (inside the volume) to
the in-network address the frontend server uses to reach the backend, then
restart.

### Multi-user mode in Docker

Just toggle auth in the volume's `data/user/settings/auth.json` (`"enabled": true`) and restart. The container picks it up. See [**Multi-User Deployment**](/self-hosting/multi-user/) for the full setup.

More: [**Troubleshooting**](/self-hosting/troubleshooting/).

## Next

- [**Multi-User Deployment**](/self-hosting/multi-user/) — team setup
- [**Explore DeepTutor**](/explore/) — tour the running app
