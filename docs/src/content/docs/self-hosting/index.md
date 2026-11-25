---
title: Runtime home
description: Where a self-hosted DeepTutor keeps settings, workspaces, and account data.
quadrant: explanation
---

Every install path lands in the same runtime home. Settings live in `data/user/settings/` under the directory you launch from, or under `DEEPTUTOR_HOME` / `deeptutor start --home` when you set one. Knowledge bases, memory, Partner runtime state, multi-user accounts, and audit logs live in that same `data/` tree. Persist the tree, and persist any content-workspace directories you configured separately.

The runtime home is the deployment storage root. It is separate from the workspaces you select inside the app. Home, Learning, and Resources follow the active workspace. Partners and Personalization stay with the account.

Process environment variables override only a few startup values, such as the ports passed to `deeptutor start`. Podman host-port mappings live in `.env.example`, not in the application settings files.

## Install paths

| Path | When it fits | Page |
| --- | --- | --- |
| PyPI | Published packages, full app after 1.7.0 | [PyPI](/self-hosting/pypi/) |
| Source | Current dev checkout | [From source](/self-hosting/source/) |
| Docker | One published container | [Docker tutorial](/get-started/docker/) and [operations](/self-hosting/docker/) |
| CLI only | No web frontend | [CLI only](/self-hosting/cli-only/) |
| Desktop | Double-click app on macOS or Windows | [Desktop editions](/self-hosting/desktop/) |

Desktop and Docker quickstarts stay under [Get started](/get-started/). This section is the deployment map.
