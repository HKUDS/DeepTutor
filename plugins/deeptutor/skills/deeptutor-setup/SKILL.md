---
name: deeptutor-setup
description: >-
  Install, configure, verify and troubleshoot DeepTutor for a user: source or
  pip install (1.7.0 modular packages), DEEPTUTOR_HOME, non-interactive init,
  config apply with credential env references, OAuth provider login, doctor
  checks, starting the Web app, and upgrading from 1.6.x. Use when setting up
  DeepTutor or diagnosing a broken installation.
---

# Setting up DeepTutor

Reference: `docs-for-dev/AGENT_SETUP.md` (authoritative; read it for edge
cases), `docs-for-dev/MODULES.md`.

## Before you start

Ask only for what's missing: install folder or existing checkout, full Web
app vs CLI-only, target version/branch, LLM provider and exact model ID,
where the credential lives (env var, private file, or provider login; never
ask for keys in chat), and whether knowledge bases (needs embedding) or
search are needed. Reuse existing checkouts and `DEEPTUTOR_HOME`; preserve
local edits and settings.

## Install

```bash
# packages (1.7.0 layout)
python -m pip install "deeptutor[full]"         # bare "deeptutor" = core CLI/SDK only

# or source, current dev
git clone --branch dev https://github.com/HKUDS/DeepTutor.git && cd DeepTutor
python3 -m venv .venv && source .venv/bin/activate
python -m pip install -r requirements/full.txt && python -m pip install -e . --no-deps
(cd web && npm ci --legacy-peer-deps)           # Web UI only; Node.js 22 LTS
```

Python 3.11-3.14. Upgrading from 1.6.15: stop DeepTutor, back up the
runtime home, `pip uninstall deeptutor-cli` first, then install
`"deeptutor[full]==1.7.0"`, keeping the same `DEEPTUTOR_HOME`.

## Configure without prompts

```bash
export DEEPTUTOR_HOME="$PWD"          # or the user's existing home; use it for every command
deeptutor init --non-interactive
deeptutor config providers            # provider IDs, endpoints, API formats (JSON)
```

`setup.json` references credentials by env var name, never literal keys:

```json
{
  "llm": {"provider": "openai", "model": "YOUR_MODEL_ID", "api_key_env": "DEEPTUTOR_SETUP_LLM_KEY"},
  "system": {"backend_port": 8001, "frontend_port": 3782}
}
```

```bash
deeptutor config apply setup.json --check   # validates, no writes or network
deeptutor config apply setup.json
deeptutor config show                       # credentials redacted
```

Ollama: `{"llm":{"provider":"ollama","model":"..."}}`. OAuth providers:
`deeptutor provider login openai-codex` (also `github-copilot`,
`codebuddy`); the user completes the login.

## Verify and start

```bash
python -m pip check
deeptutor module list                    # installed / enabled / ready are separate
deeptutor doctor --format json
deeptutor doctor --online --format json  # real (billable) LLM request
deeptutor start --detach --no-browser    # backend :8001, frontend :3782 by default
deeptutor stop
```

Check backend `/health/ready` and that the frontend responds. For CLI-only,
verify with `deeptutor run chat "Reply with a short greeting." --format json`.
Don't run CLI turns against a home while a detached `deeptutor start` is
running on it (fails as `worker_lost` / `Turn event conflict`).

Report what was verified, the runtime home, provider/model (no secrets),
the URL or CLI command, and any unfinished step. Saved settings are not
proof of readiness.

## Troubleshooting

Confirm you're checking the same instance, home and ports as the user, then
collect minimal evidence: `config show`, `doctor`, `doctor --online`,
`doctor runtime`. Follow the failing operation browser -> API -> turn ->
provider/tool/storage, using `data/user/runtime/launcher.log` and
`data/user/logs/deeptutor.jsonl`.
