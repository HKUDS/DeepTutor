---
title: Docker
description: Option 3 — one container for the full Web app, from the GHCR image.
quadrant: tutorial
---

One container for the full Web app. Images on GitHub Container Registry:

- `ghcr.io/hkuds/deeptutor:latest` — current stable release
- `ghcr.io/hkuds/deeptutor:<version>` — exact release; pre-releases receive only a versioned tag and never update `latest`

## Run

```bash
docker run --rm --name deeptutor \
  -p 127.0.0.1:3782:3782 \
  -v deeptutor-data:/app/data \
  ghcr.io/hkuds/deeptutor:latest
```

> **Only `3782` needs to be published.** The browser talks exclusively to the frontend origin; the Next.js middleware (`web/proxy.ts`) forwards every `/api/*` and `/ws/*` request to the FastAPI backend **inside the container**, so you don't expose `8001` to the host for the UI to work. Publishing it (`-p 127.0.0.1:8001:8001`) is optional — handy only for hitting the API directly with curl or scripts.

Open <http://127.0.0.1:3782>. The container creates `/app/data/user/settings/*.json` on first boot; configure model providers from the Web Settings page. Config, API keys, logs, the default content workspace, memory, knowledge bases, and Partner workspaces (`data/partners/<id>/`) all persist in the `deeptutor-data` volume. Optional extras belong on the deployment, not in a shell: set `DEEPTUTOR_EXTRAS` (and `DEEPTUTOR_APT_PACKAGES`), and every container re-applies them at start.

## Next

Host folders, detached mode, reverse proxies, local models, and upgrades are on [Docker operations](/self-hosting/docker/).

- [**Explore DeepTutor**](/learning-workspace/)
