# DeepTutor Containerization

This document covers deploying DeepTutor from a container image: the
recommended `docker run` path, the hardened rootless-Podman path with a
read-only root filesystem, runtime configuration, the optional PocketBase
sidecar, and the security notes that motivate the default posture.

For PyPI / source installs, see the main [README.md](../README.md). This
file is only about running the published image.

---

## Overview

The published `ghcr.io/hkuds/deeptutor` image runs both the FastAPI
backend (`:8001`) and the Next.js frontend (`:3782`) under `supervisord`
inside a single container, on top of `python:3.11-slim`. There is one
data tree (`/app/data` inside the container) that holds settings,
workspaces, memory, knowledge bases, and logs. Bind-mount that tree to
the host to make state survive container restarts.

The image is built so it works under three deployment shapes:

1. **`docker run`** — the easy path. Rootful, writable rootfs, single
   bind mount on `/app/data`.
2. **`docker compose`** (`docker-compose.yml`) — same image plus the
   PocketBase sidecar and the sandbox-runner sidecar. Still rootful,
   writable rootfs.
3. **`podman compose -f compose.yaml`** — the hardened path. Rootless
   (`userns_mode: keep-id`), read-only rootfs, tmpfs in place of writable
   system dirs, bind mount on `./data`.

The architectural change that makes shape 3 work is that URL knowledge
no longer lives in the frontend bundle. Concretely:

- The bundle is built with no `NEXT_PUBLIC_API_BASE` placeholder and no
  `sed -i` of the build output. `web/lib/api.ts` exports `apiUrl` and
  `wsUrl` as one-line pass-throughs, so the browser fetches relative
  paths through the frontend (`:3782/api/...`).
- `web/proxy.ts` catches `/api/*` and `/ws/*` and rewrites them to
  `DEEPTUTOR_API_BASE_URL` at request time. That env var is set by the
  container entrypoint on every start, read from
  `data/user/settings/system.json`.
- `start-frontend.sh` is now 12 lines: it sets `PORT`/`HOSTNAME` and
  `exec`s `node /app/web/server.js`. No mutations of the bundle.
- `supervisord` runs as root (PID 1) and drops each program (backend,
  frontend) to a non-root `deeptutor` user (UID 1000) via its per-program
  `user=` directive, so the app processes stay non-root. With
  `userns_mode: keep-id` on the host that UID maps to your host UID; with a
  regular `docker run` it's a normal unprivileged user inside the container.

The full per-installation guide follows.

---

## Docker (default)

The simplest possible deployment. One container, one volume, two port
mappings.

```bash
docker run --rm --name deeptutor \
  -p 127.0.0.1:3782:3782 \
  -v deeptutor-data:/app/data \
  ghcr.io/hkuds/deeptutor:latest
```

Open <http://127.0.0.1:3782>. The container creates
`/app/data/user/settings/*.json` on first boot; configure model providers
from the Web Settings page. Config, API keys, logs, workspace files,
memory, and knowledge bases persist in the `deeptutor-data` named volume.

Notes:

- **Only `3782` needs to be published.** The browser talks exclusively to
  the frontend origin (`:3782`); all `/api/*` and `/ws/*` traffic is
  forwarded to the FastAPI backend **inside the container** by the Next.js
  middleware (`web/proxy.ts`), which reads `DEEPTUTOR_API_BASE_URL`
  (`http://localhost:8001` by default) at request time. You do **not** need
  to expose `:8001` to the host for the UI to work. Publishing `:8001`
  (`-p 127.0.0.1:8001:8001`) is optional — handy only for hitting the API
  directly (curl, scripts) or debugging.
- **Different host ports:** change the left side of each `-p host:container`
  mapping (e.g. `-p 127.0.0.1:8088:3782`). If you change container-side
  ports in `data/user/settings/system.json` (`backend_port`,
  `frontend_port`), restart the container and update the right side of
  each mapping to match.
- **Detached:** add `-d`, then `docker logs -f deeptutor` to follow,
  `docker stop deeptutor` to stop, `docker rm deeptutor` before reusing
  the name. The `deeptutor-data` volume keeps your settings and workspace
  across restarts.

### Remote / reverse-proxy deployments

For the common **single-container** case (this image), you do **not** need
to configure an API base at all. The browser issues relative `/api/*` and
`/ws/*` requests against whatever origin serves the UI
(`https://deeptutor.example.com`), and the in-container Next.js middleware
forwards them to the backend on `localhost:8001`. Just point your reverse
proxy / TLS terminator at the published `:3782` and you're done.

You only need to set an API base for a **split deployment** where the
backend runs in a separate container. Edit `data/user/settings/system.json`
on the host (inside the `deeptutor-data` volume — `docker volume inspect
deeptutor-data` to find its mountpoint) and set the in-network address the
frontend container uses to reach the backend container:

```json
{
  "next_public_api_base": "http://backend:8001"
}
```

The entrypoint reads this on every start and exports
`DEEPTUTOR_API_BASE_URL` for `proxy.ts` (precedence: `next_public_api_base`,
then `next_public_api_base_external`, then `http://localhost:8001`). Note
that because the proxy is **server-side**, `DEEPTUTOR_API_BASE_URL` is the
address the frontend *server* uses to reach the backend — not a URL the
browser ever sees. `public_api_base` is accepted as a compatibility alias
and normalized into `next_public_api_base_external` on save.

CORS uses frontend **origins**, not API URLs. With auth disabled,
DeepTutor permits normal HTTP/HTTPS browser origins by default. With
auth enabled, add exact frontend origins:

```json
{
  "cors_origins": ["https://deeptutor.example.com"]
}
```

### Host LLM providers (Ollama / LM Studio / llama.cpp / vLLM / Lemonade)

Inside Docker, `localhost` is the container itself, not your host
machine. To reach a model service running on the host, use the host
gateway (recommended):

```bash
docker run --rm --name deeptutor \
  -p 127.0.0.1:3782:3782 -p 127.0.0.1:8001:8001 \
  --add-host=host.docker.internal:host-gateway \
  -v deeptutor-data:/app/data \
  ghcr.io/hkuds/deeptutor:latest
```

Then in **Settings → Models**, point the provider Base URL at
`host.docker.internal`:

- Ollama LLM: `http://host.docker.internal:11434/v1`
- Ollama embedding: `http://host.docker.internal:11434/api/embed`
- LM Studio: `http://host.docker.internal:1234/v1`
- llama.cpp: `http://host.docker.internal:8080/v1`
- Lemonade: `http://host.docker.internal:13305/api/v1`

Docker Desktop (macOS/Windows) usually resolves `host.docker.internal`
without `--add-host`. On Linux, the flag is the portable way.

**Linux alternative — host networking:** add `--network=host` and drop
the `-p` flags. The container shares the host network directly, so open
<http://127.0.0.1:3782> (or the `frontend_port` in `system.json`), and
host services can be reached with normal localhost URLs.

In host-network mode the processes bind directly on the host interfaces
(there is no `-p 127.0.0.1:` prefix to scope them). To keep them off the
LAN, set `BACKEND_HOST=127.0.0.1` and `FRONTEND_HOST=127.0.0.1` — they
override uvicorn's `--host` and Next.js's `HOSTNAME` (both default to
`0.0.0.0`). Only use these with `--network=host`: in bridge mode binding
to loopback breaks the published `-p` port forward.

---

## Podman / rootless / read-only rootfs

For users who want the strongest default posture — rootless, with a
read-only root filesystem — `compose.yaml` is the supported starting
point. It pulls the same `ghcr.io/hkuds/deeptutor:latest` image and
relies on the entrypoint chown + supervisord's per-program privilege drop,
the URL-forwarding `proxy.ts`, and host-side bind mounts to make it all work.

```bash
cp .env.example .env       # then edit if needed
podman compose -f compose.yaml up -d
podman compose -f compose.yaml ps
podman compose -f compose.yaml logs -f deeptutor
```

Verify rootless is active (`podman info | grep -i rootless` should
report `true`).

What `compose.yaml` does, and why:

- **`read_only: true` on every service.** The container's rootfs is
  read-only. The only writable surface is the `tmpfs:` mounts listed
  per service plus the bind-mounted `./data` directory.
- **`userns_mode: keep-id`.** The container's UID 0 maps to your host
  UID; the container's UID 1000 (the `deeptutor` user inside the image)
  maps to your host UID 1000 (which most distros reserve for the first
  human user). The `:U` suffix on every volume mount tells podman to
  chown the bind-mount target to that mapped UID.
- **`tmpfs:` mounts for the system dirs the runtime expects to write.**
  `/tmp` (Python/Node scratch), `/run` and `/var/run` (pidfiles),
  `/var/log`, `/root`, `/home`. Sizes are intentionally generous; trim
  to taste.
- **No named volumes.** Podman auto-creates named volumes with the
  userns-mapped root (UID 100000), so 755 perms + wrong owner =
  `PermissionError` on the first JSON write. Bind mounts on a host
  directory you own work cleanly.
- **Loopback-only port bindings.** `127.0.0.1:` prefix on every `ports:`
  entry. Drop the prefix to expose on all interfaces.
- **No sandbox-runner sidecar.** The `docker-compose.yml` shape includes
  a hardened sidecar that runs untrusted model-generated code in a
  least-privileged container. The podman shape does not — the main app
  falls back to `bwrap` (Linux, if installed in the image) or the
  restricted subprocess backend controlled by
  `sandbox_allow_subprocess` in `system.json`.

### Running outside `compose.yaml`

`compose.yaml` is a starting point, not the only shape. The same
invariants apply if you want to drive `podman run` directly:

```bash
mkdir -p data/user/settings
echo '{}' > data/user/settings/system.json

podman run --rm -d --name deeptutor \
  -p 127.0.0.1:8001:8001 \
  -p 127.0.0.1:3782:3782 \
  -v $(pwd)/data:/app/data:U \
  --read-only \
  --tmpfs /tmp:size=512m,mode=1777 \
  --tmpfs /run:size=32m,mode=0755 \
  --tmpfs /var/run:size=8m,mode=0755 \
  --tmpfs /var/log:size=64m,mode=0755 \
  --tmpfs /root:size=16m,mode=0700 \
  --tmpfs /home:size=16m,mode=0755 \
  --userns=keep-id \
  ghcr.io/hkuds/deeptutor:latest
```

After the container is up, the backend and frontend always run as the
non-root `deeptutor` user (UID 1000) — `podman exec deeptutor ps -o user,pid,comm`
shows the `uvicorn`/`node` children as `deeptutor`. `supervisord` itself
(PID 1) runs as whatever UID the runtime started it with: root under rootful
Docker/Podman, or the host user under rootless podman + `userns_mode: keep-id`.

### Supervisord pidfile

The `[supervisord]` section carries **no `user=` directive**, so supervisord
runs as PID 1's UID and never tries to drop its own privilege; only its child
programs are dropped to `deeptutor` via the per-program `user=` directives.
Pinning `user=root` here (an earlier design) broke rootless keep-id, where
PID 1 is the non-root host user and lacks `CAP_SETUID`: supervisord refuses to
drop privilege and exits at startup with `Can't drop privilege as nonroot
user` (see supervisord's `options.py`).

The pidfile is written to **`/tmp/supervisord.pid`**. `/tmp` is `mode=1777`
(world-writable) in every run configuration above, so the pidfile is writable
whether PID 1 is root or the host UID, and regardless of who owns `/var/run`.
An earlier build pointed the pidfile at the root-owned `/var/run/supervisord.pid`;
under rootless keep-id the non-root PID 1 couldn't write it and logged a
cosmetic `CRIT could not write pidfile` on every start. Putting it in `/tmp`
removes that dependency on the `/var/run` owner and mode entirely.

---

## Runtime configuration

Almost everything you tune lives under `data/user/settings/` inside the
data tree. The container entrypoint unsets a list of related env vars
(`BACKEND_PORT`, `FRONTEND_PORT`, `NEXT_PUBLIC_API_BASE`,
`NEXT_PUBLIC_API_BASE_EXTERNAL`, `AUTH_ENABLED`, `POCKETBASE_URL`, etc.)
on every start and re-exports values from the JSONs. So: edit the JSONs,
restart, do **not** try to drive these with compose env vars.

| File | Purpose |
|:---|:---|
| `system.json` | Backend/frontend ports, public API base, CORS, SSL verification, attachment directory |
| `auth.json` | Optional auth toggle, username, password hash, token/cookie settings |
| `integrations.json` | Optional PocketBase and sidecar integration settings |
| `model_catalog.json` | LLM, embedding, and search provider profiles; API keys; active models |
| `interface.json` | UI language / theme / sidebar preferences |
| `main.yaml` | Runtime behavior defaults and path injection |
| `agents.yaml` | Capability/tool temperature and token settings |

The two settings most relevant to a fresh install:

- **`system.json` → `next_public_api_base`** (in-network) and
  **`next_public_api_base_external`** (cloud/external override). The
  entrypoint reads these and exports `DEEPTUTOR_API_BASE_URL`, which
  `web/proxy.ts` consumes. `public_api_base` is accepted as a
  compatibility alias and is normalized into
  `next_public_api_base_external` on save.
- **`system.json` → `backend_port` / `frontend_port`**. The container
  ports the supervisor binds inside the container. If you change these,
  update the right side of every `-p host:container` mapping (or the
  `HOST_PORT_*` env var that `compose.yaml` reads) to match.

Project-root `.env` files are intentionally ignored as application
config. The Web **Settings** page is the recommended editor for the
JSON/YAML files; deep links to each section live in the page sidebar.

---

## PocketBase

PocketBase is an optional auth + storage sidecar. Activate it by setting
`integrations.pocketbase_url` to `http://pocketbase:8090` in
`data/user/settings/integrations.json` and bringing the `pocketbase`
service up alongside the main `deeptutor` service. With it running, the
main app stores user accounts and sessions in PocketBase instead of
falling back to the SQLite single-user layout.

The `pocketbase` service in `compose.yaml` (and the corrected mount in
`docker-compose.yml`) bind-mounts three subdirectories of `./data` —
`/pb_data`, `/pb_public`, `/pb_hooks` — matching the upstream
`ghcr.io/muchobien/pocketbase:latest` image's entrypoint, which uses
absolute paths. The earlier `docker-compose.yml` example mounted
`/pb/pb_data` and crashed on first start with
`mkdir /pb_data: read-only file system`; this PR fixes that.

PocketBase stays a single-user integration — keep
`integrations.pocketbase_url` blank for multi-user deployments unless
you've wired up an external user store.

---

## Troubleshooting

**`CRIT could not write pidfile /var/run/supervisord.pid` on container start.**
Only on images built before the pidfile moved to `/tmp/supervisord.pid`
(`mode=1777`, always writable); current images don't emit it. The supervised
children come up either way — the line was always cosmetic. Fix: pull a
current image (or, on an old one, set the `/var/run` tmpfs to `mode=1777`).

**Page loads but Settings says "Backend unreachable".** The UI reaches the
backend through the in-container proxy, not a host port, so this is almost
always a backend that failed to start (check `docker logs deeptutor` for the
`[program:backend]` lines) or a wrong `DEEPTUTOR_API_BASE_URL` in a split
deployment — **not** a missing `:8001` host mapping (which the UI does not
need).

**`Cannot connect to the Docker daemon` on a podman host.** Run
`systemctl --user start podman.socket` (rootless) or set
`DOCKER_HOST=unix:///run/user/$UID/podman/podman.sock` for the
`docker-compose` CLI to use the podman socket.

**`Permission denied` on first JSON write under a named volume.** This
is the userns-mapped root problem; switch to a bind mount on a host
directory you own, or use `:U` on the volume mount.

**`sed -i` errors on a fresh image.** There shouldn't be any — the
runtime no longer mutates the bundle. The URL is forwarded at request
time. If you see one, you are probably on an older image; pull
`ghcr.io/hkuds/deeptutor:latest` again.

**Settings page won't accept the API base URL.** Open
`data/user/settings/system.json` on the host and set
`next_public_api_base_external` directly. The page UI is wired to
`public_api_base` (the legacy alias) and the legacy field will be
renormalized on save.

---

## Security notes

- The image drops privileges to a non-root `deeptutor` user (UID 1000)
  before starting `supervisord`. Anything that runs as root is the
  entrypoint, the chown, and the env-var export.
- `read_only: true` plus `tmpfs:` for the expected writable system
  directories means the container's root filesystem is immutable at
  runtime. A process that tries to write outside the listed tmpfs
  paths or the bind-mounted `./data` tree will fail.
- `userns_mode: keep-id` on the host means a container escape lands
  with your host user's permissions, not root.
- The sandbox-runner sidecar (in `docker-compose.yml`, **not** in
  `compose.yaml`) is the strongest posture for untrusted model-generated
  code: a sandbox escape lands in a stripped, unprivileged container
  with no app secrets, not in the main app. The podman shape trades that
  for the rootless-podman shape; the main app falls back to `bwrap` or
  the restricted subprocess backend controlled by
  `sandbox_allow_subprocess`.
- Auth (`data/user/settings/auth.json` → `auth_enabled = true`) gates
  `/api/*` and `/ws/*` via the `dt_token` cookie. `web/proxy.ts` reads
  `DEEPTUTOR_AUTH_ENABLED` (exported by the entrypoint on every start)
  to decide whether to require the cookie.
- CORS uses frontend **origins**, not API URLs. With auth enabled, set
  `cors_origins` in `system.json` to the exact frontend origins the
  deployment serves.
