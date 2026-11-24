---
title: Get Started
description: DeepTutor ships four install paths — PyPI, From Source, Docker, and CLI-Only. Pick the one that fits.
---

DeepTutor ships **four installation paths**. They share one runtime-home layout: settings live in `data/user/settings/` under the directory you launch from (or under `DEEPTUTOR_HOME` / `deeptutor start --home` if you set one explicitly). Knowledge bases, memory, Partner runtime state, multi-user accounts, and audit logs also live under the same `data/` tree, so persist that tree and any separately configured content-workspace directories. The runtime home is the deployment storage root; it is distinct from the workspaces selected inside the app.

For the full app, the recommended flow is **pick a runtime-home directory → install → `deeptutor init` → `deeptutor start`**.

## Pick a path

| Option | When to use | Page |
|--------|-------------|------|
| **PyPI** | Published packages; full app uses [full] in 1.7.0 | [**Install from PyPI**](/get-started/pypi/) |
| **From Source** | Current dev, local development, optional hot reload | [**Install from Source**](/get-started/from-source/) |
| **Docker** | Production deployments, hosted hosts, persistent volumes | [**Docker**](/get-started/docker/) |
| **CLI Only** | Headless server, agent harness, no Web UI needed | [**CLI-Only Install**](/get-started/cli-only/) |

> **1.7.0 installation:** `deeptutor[full]` installs the Web app; bare `deeptutor` installs core CLI/SDK. Stop DeepTutor before changing modules and keep feature wheels at the core version. For development, use the source instructions or [build local wheels](https://github.com/HKUDS/DeepTutor/blob/dev/docs-for-dev/MODULES.md). Back up your runtime home before upgrading older installations.

## Minimum requirements

| Component | Version |
|-----------|---------|
| Python | **3.11–3.14** |
| Node.js | **20+** (PyPI) / **22 LTS** (from source, matches CI + Docker) |
| RAM | Depends on the selected models and workload |
| Disk | Depends on install extras and workspace data |

You'll also need an **LLM provider**. Hosted services usually require an API key; local providers such as Ollama, LM Studio, llama.cpp, and vLLM can run without one. An embedding provider is optional unless you plan to use Knowledge Bases.

## What gets bound

After `deeptutor start`, two services come up:

| Service | Default port |
|---------|--------------|
| FastAPI backend | `8001` |
| Next.js frontend | `3782` |

Both are overridable via `data/user/settings/system.json` or during `deeptutor init`.

## After install

Once you can reach `http://localhost:3782/`:

- [**Explore DeepTutor**](/explore/) — start with workspaces, then Home, Learning, Resources, Partners, and Personalization
- [**DeepTutor CLI**](/cli/) — drive core runtime and workspace operations from the terminal
- [**Partners: channels**](/partners/) — connect autonomous tutors to WeChat, WeCom, QQ, Telegram, Slack, Feishu, and more
- [**Multi-User Deployment**](/get-started/multi-user/) — host DeepTutor for a team

If something breaks, jump to [**Troubleshooting**](/get-started/troubleshooting/).
