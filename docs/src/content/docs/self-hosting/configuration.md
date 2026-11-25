---
title: Configuration files
description: The settings JSON files a deployment actually reads, and the keys the setup capability may write.
quadrant: reference
---

DeepTutor reads configuration from `data/user/settings/*.json` inside the runtime home. A process environment variable overrides only a few startup values. Podman host-port mappings are the variables in `.env.example`.

## Files the app reads

| File | What it holds |
| --- | --- |
| `interface.json` | Personal interface choices, including language and theme. |
| `system.json` | Ports and the server-side API base. `next_public_api_base` is the address the frontend server uses to reach the backend. `cors_origins` lists page origins allowed to call the API when auth is on. |
| `document_parsing.json` | The document parsing engine. |
| `model_catalog.json` | Provider profiles and the selected models. |
| `auth.json` | Multi-user auth. `enabled`, `token_expire_hours`, and `cookie_secure` are the switch documented in [Multi-user](/self-hosting/multi-user/). |

The screen that edits these values is [Settings](/self-hosting/settings/).

## Keys the setup capability may write

These rows come from `deeptutor/services/config/settings_spec.py`. They are the knobs that capability is allowed to change. They are not a dump of every JSON field. Secrets are not in this table; credentials are entered in the Settings card.

| Key | Area | Scope | Effect |
| --- | --- | --- | --- |
| `interface.language` | interface | personal | instant |
| `interface.response_language` | interface | personal | instant |
| `interface.theme` | interface | personal | instant |
| `document_parsing.engine` | parsing | global | instant; already parsed documents keep their text until re-upload |
| `catalog.llm` | models | global | instant, after a connectivity probe |
| `catalog.embedding` | models | global | reindex, after a connectivity probe |
| `catalog.search` | models | global | instant |
| `web_fetch.backend` | models | global | instant |

Personal rows live in the caller's `interface.json`. Global rows live in the shared deployment settings and are administrator-only.
