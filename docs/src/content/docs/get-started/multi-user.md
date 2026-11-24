---
title: Multi-User Deployment
description: Flip on authentication and DeepTutor turns into a multi-tenant deployment with per-user isolated workspaces and admin-curated resources.
quadrant: how-to
---

Flip on authentication and DeepTutor turns into a multi-tenant deployment with **per-user isolated workspaces** and **admin-curated resources**. The first person to register becomes the admin and configures models, API keys, and knowledge bases on behalf of everyone else. Subsequent accounts are created by the admin (invite-only), each gets their own scoped chat history / memory / notebooks / knowledge bases and private personal books. They see assigned LLMs, KBs, and skills; partners they build or receive; and admin-shared books at the granted read or edit level.

## Quick start (5 steps)

```bash
# 1. Enable auth in data/user/settings/auth.json:
#    {"enabled": true, "token_expire_hours": 24, "cookie_secure": false}
#    Use cookie_secure=true for HTTPS deployments where Web and API are cross-site.

# 2. Restart the web stack.
deeptutor start

# 3. Open http://localhost:3782/register and create the first account.
#    The first registration is the only public one; that user becomes admin
#    and the /register endpoint is closed automatically afterward.

# 4. As admin, navigate to /admin/users → "Add user" to provision teammates.

# 5. For each user, click the slider icon → assign resource grants, then set
#    Book access (personal creation, default access, and per-book read/edit).
#    Save. The user can now sign in and start working.
```


## What the admin sees

- **Full Settings page** at `/settings` — manage reusable vendor Connections and profiles for LLM, Task Models, embedding, search, TTS, STT, image, and video services. Task Models handle conversation titles, Home starting points, reading helpers, and Math Animator/Video Lesson repairs; an empty task service inherits the LLM.
- **User management** at `/admin/users` — create Standard, Learner, or Custom accounts (or import them from a CSV), then promote, demote, or delete them, singly or in a batch. Learner creation initializes the restricted learning grant and profile; the public `/register` endpoint closes once the first admin exists, and further accounts use the admin-only API.
- **Grant editor** — for each non-admin user, pick the LLM models, knowledge bases, skills, and partners they may use, restrict the system tools (web search, paper search, …), MCP tools, and installed CLI apps to a whitelist, and switch code execution off entirely. Tool whitelists follow the same semantics as partner configs: *Default* allows everything, *Custom* is an explicit whitelist. Grants carry **logical IDs only**; API keys never cross the grant boundary.
- **Book access editor** — allow personal book creation, set the default for shared admin books (`none` or `read`), and override each to `none`, `read`, or collaborative `edit`. Shared deletion is never delegated; progress, bookmarks, quiz attempts, captures, and Page Chat links remain private.
- **Hub skill installs** — `POST /api/multi-user/admin/skills/install` (admin-only) imports a skill from an external hub such as ClawHub into the admin catalog. Install ≠ assign: the skill stays invisible to other users until a grant assigns it, so the admin can vet it first. Every install is recorded in the audit trail.
- **Audit trail** — every grant change and assigned-resource access is appended to `data/system/audit/usage.jsonl`.

## What ordinary users get

- **Isolated workspace** under `data/users/<uid>/` — their own chat history (`chat_history.db`), memory, notebooks, and personal knowledge bases. Only a Docker content workspace is shared.
- **Read-only access** to admin-assigned knowledge bases and skills, surfaced inline next to their own resources with an "Assigned by admin" badge.
- **Scoped shared-book access** — an allowed admin book may be read-only or collaboratively editable, while its canonical content stays shared and each reader's progress, bookmarks, quiz attempts, captures, and Page Chat links stay private.
- **Redacted Settings page** — theme, language, granted-model summaries, private **OpenAI Codex** sign-in, a Learner profile for learner accounts, and Guardian management when authorized. API keys, base URLs, and provider endpoints are never returned for non-admin requests.
- **Scoped LLM** — chat turns are routed through the admin-assigned model. If no LLM is granted, the turn is rejected up-front (no silent fallback to the admin's keys).
- **Scoped tools** — the composer, the `/settings/tools` page, and every turn only expose the system tools, MCP tools, and CLI apps inside the user's grant whitelist; code execution honors the per-user switch on top of the deployment sandbox policy.

## Workspace layout

Everything lives under `data/` — one tree to mount and back up:

```text
data/
├── user/                        # Admin workspace (settings, API keys, admin tasks)
├── system/
│   ├── auth/users.json          # Hashed credentials, roles, per-user book ACL
│   ├── auth/auth_secret         # JWT signing secret (auto-generated)
│   ├── auth/device_credentials.json # Revocable learner-device credentials
│   ├── guardians.json           # Guardian ↔ learner authorizations
│   ├── grants/<uid>.json        # Per-user resource grants (admin-managed)
│   ├── audit/usage.jsonl        # Audit trail
│   └── user-secrets/<owner>/    # Per-owner credentials (Codex OAuth tokens)
├── cli-apps/                    # Installed CLI apps (read-only in the sandbox)
├── users/<uid>/
│   ├── user/
│   │   ├── chat_history.db
│   │   ├── settings/interface.json
│   │   └── workspace/{chat,co-writer,book,...}
│   ├── memory/
│   └── knowledge_bases/...
└── partners/<id>/               # Partner workspaces
```

Deployments upgraded from the pre-v1.5 layout (a sibling `multi-user/` directory next to `data/`) are migrated automatically on first start: `multi-user/_system` moves to `data/system`, each `multi-user/<uid>` to `data/users/<uid>`.

## Configuration reference

| Setting | Required | Description |
|---------|----------|-------------|
| `data/user/settings/auth.json: enabled` | Yes | Set to `true` to enable multi-user auth. Default `false` (single-user mode — admin paths everywhere). |
| `data/system/auth/auth_secret` | Recommended | JWT signing secret. Auto-generated on first authenticated boot if missing. |
| `data/user/settings/auth.json: token_expire_hours` | No | JWT lifetime; defaults to `24`. |
| `data/user/settings/auth.json: cookie_secure` | HTTPS / cross-site auth | Set `true` to use `SameSite=None; Secure` cookies. Keep `false` for local HTTP. |
| `data/user/settings/auth.json: username` / `password_hash` | No | Optional headless single-user bootstrap credential. Leave blank when using browser registration. |
| `data/user/settings/system.json` | No | `deeptutor start` derives frontend auth flags, public API base, and CORS origins from runtime settings. |

## Important caveats

> ⚠️ **PocketBase mode (`integrations.pocketbase_url` set) is single-user only.** The default PocketBase schema has no `role` field on `users` (every login resolves to `role=user`, no admin can be created), so although session rows are now scoped by `user_id`, PocketBase still can't back a true multi-user install. Multi-user deployments must keep `integrations.pocketbase_url` blank and use the default JSON/SQLite backend.

> ⚠️ **Single-process bootstrap.** The first-user-becomes-admin promotion is protected by an in-process `threading.Lock`. Enable auth, start one backend process, and register the first admin before adding workers. The registration endpoint rejects requests while `auth.json.enabled=false`.

## Production checklist

- ✅ Set a strong `auth_secret` and back it up
- ✅ Set `cookie_secure: true` in `auth.json` to require HTTPS for the session cookie
- ✅ Put DeepTutor behind a reverse proxy (Caddy, nginx, Traefik) with TLS termination, pointed at the frontend port (the frontend proxies `/api/*` to the backend internally — no API base needed unless backend and frontend run separately)
- ✅ Set `cors_origins` to the exact frontend origin when auth is enabled and Web/API are cross-origin
- ✅ Back up `data/` regularly — accounts, grants, and every workspace live under this one tree
- ✅ Docker: keep the `./data:/app/data` volume from `docker-compose.yml`. The sandbox runner no longer mounts `data/user/workspace` or `data/users`: it now gets `/workspace` read-only plus a writable `/workspace/outputs`, and `DEEPTUTOR_RUNNER_ALLOWED_WORKDIRS=/workspace/outputs` rejects any other workdir. `data/system`, `data/users`, and admin `data/user/settings` are no longer visible to it
- ✅ Docker: all three Compose files set `DEEPTUTOR_WORKSPACE_ROOT=/workspace`, so every account — admin or not — is locked to that one shared content workspace, not `data/users/<uid>/user/workspace`

## Caddyfile example

```text
deeptutor.example.com {
    reverse_proxy localhost:3782
}
```

The frontend forwards `/api/*` and `/ws/*` to the backend itself, so a single
`reverse_proxy` at the frontend port is all you need. Then in
`data/user/settings/system.json` you only set CORS (no API base for this
single-host setup):

```json
{
  "cors_origins": ["https://deeptutor.example.com"]
}
```

Only a **split deployment** (backend on a separate host/container) needs an API
base — set `next_public_api_base` to the in-network backend address; it's read
server-side by the frontend proxy, not sent to the browser. `public_api_base`
and `next_public_api_base_external` are accepted as lower-precedence fallbacks.

And in `data/user/settings/auth.json`:

```json
{
  "enabled": true,
  "token_expire_hours": 24,
  "cookie_secure": true
}
```

## Common errors

### `404 /register` after enabling auth

The frontend bundle may be cached. With Docker, recreate the container. From source, restart `deeptutor start` after editing `auth.json`.

### First login works but no admin link

Confirm `data/system/auth/users.json` has `"role": "admin"` on the first user. If not, manually set it and restart.

### Every request returns 401 after a restart

`auth_secret` was lost or regenerated, so existing tokens no longer decode. There is no dedicated error for this: the failure is swallowed and surfaces as a plain 401. Restore the secret from backup, or accept the regenerated one and ask all users to log in again.

## Headless single-user bootstrap

For automation where no human can register in a browser, set credentials directly in `auth.json`:

```json
{
  "enabled": true,
  "username": "alice",
  "password_hash": "<bcrypt-hash>",
  "token_expire_hours": 24
}
```

Generate the hash:

```python
import bcrypt
print(bcrypt.hashpw(b"your-password", bcrypt.gensalt()).decode())
```

Then `deeptutor start` and log in with `alice` + your-password.

More fixes: [**Troubleshooting**](/get-started/troubleshooting/).
