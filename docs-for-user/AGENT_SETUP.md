# Set Up and Troubleshoot DeepTutor with Your Agent

This guide is for an external agent installing, configuring, and verifying
DeepTutor for a user, or investigating problems in an existing installation.
For an existing problem, start with [Troubleshooting](#6-troubleshooting) rather
than repeating installation. Read [SKILL.md](../SKILL.md) for the CLI overview. You need
terminal and file access; this flow does not require MCP or an agent-specific
plugin.

## 1. Establish the target

Ask only for missing information and continue independent preparation while
waiting:

- Installation folder and any existing DeepTutor checkout.
- Full Web app or CLI-only; default to the full app for the README setup prompt.
- LLM provider, exact model ID, and any custom/local endpoint.
- Credential source: an existing environment variable, a private local file
  the user identifies, or provider login. Do not ask for keys in chat.
- Whether knowledge bases/RAG are needed now; these also require embedding.
  Search is optional.

Reuse suitable checkouts/environments and preserve local edits and settings.
Use the user's existing `DEEPTUTOR_HOME`, or choose a runtime home explicitly.
It owns `data/`; it is not the `data/` directory itself or the Content Workspace
used for learning materials.

## 2. Clone and install

For a new full-app source installation (macOS/Linux example):

```bash
git clone https://github.com/HKUDS/DeepTutor.git
cd DeepTutor
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .
cd web
npm ci --legacy-peer-deps
cd ..
```

Use Python **3.11–3.14** and **Node.js 22 LTS** for this flow. Check the actual
interpreter before creating the environment; `python3` may be older. On
Windows, use a supported `py -3.X` and `.venv\Scripts\Activate.ps1`. If shell
state does not persist between tool calls, invoke the environment's Python
and `deeptutor` by absolute path and pass environment variables to each process.

For CLI-only, replace the editable install with
`python -m pip install -e ./packaging/deeptutor-cli` and skip Node/npm. CLI-only
is currently installed from source. A packaged full app can use
`python -m pip install deeptutor` without cloning; it includes Web assets. Check
that installed version's `--help`: the non-interactive commands below are
available in the checkout containing this guide and releases that include it.

## 3. Initialize without prompts

Keep the same runtime home for initialization, configuration, diagnostics, and
startup. This example uses the checkout root; use the existing home instead
when the user has one:

```bash
export DEEPTUTOR_HOME="$PWD"
deeptutor init --non-interactive
deeptutor config providers
```

`init --non-interactive` creates missing defaults without selecting a model or
contacting a provider and preserves saved settings. `--cli` is also accepted;
no wizard runs in either mode. Initialization alone does not establish model
readiness.

`config providers` prints supported LLM, embedding, and search providers with
default endpoints and LLM API formats as JSON. Use its provider IDs. `init`,
`config apply`, and `config show` also accept `--home PATH`; for other commands
use `DEEPTUTOR_HOME` consistently.

## 4. Apply configuration

Write a UTF-8 JSON file such as `setup.json`, replacing the model placeholder
with the user's choice:

```json
{
  "llm": {
    "provider": "openai",
    "model": "YOUR_MODEL_ID",
    "api_key_env": "DEEPTUTOR_SETUP_LLM_KEY"
  },
  "system": {
    "backend_port": 8001,
    "frontend_port": 3782
  }
}
```

The variable named by `api_key_env` must exist in the CLI process's environment.
Read it from the user's authorized source without echoing it. The JSON contains
a variable name, not a literal key. Resolved keys are saved in DeepTutor's
private settings for later launches. Project-root `.env` files are not loaded
automatically.

```bash
deeptutor config apply setup.json --check
deeptutor config apply setup.json
deeptutor config show
```

`--check` validates input, providers, named credentials, endpoints, and port
conflicts without writing settings or contacting providers. Both modes
emit JSON; invalid input exits with code 2. Application selects a dedicated
**Agent Setup** profile for each supplied service. Repeating it updates those
same profiles; other profiles and omitted services/settings are preserved.
Supply complete profiles, including credential references, each time. Port
changes take effect on restart.

| Section | Required fields | Optional fields |
| :--- | :--- | :--- |
| `llm` | `provider`, `model` | `base_url`, `api_key_env`, `api_version`, `api_format` |
| `embedding` | `provider`, `model` | `base_url`, `api_key_env`, `api_version`, positive integer `dimension` |
| `search` | `provider` | `base_url`, `api_key_env` |
| `system` | At least one port | `backend_port`, `frontend_port` (integers 1–65535, distinct) |

Remote key-authenticated LLM/embedding providers require `api_key_env`; local,
OAuth, and `custom` endpoints may omit it. Search requirements come from
`config providers`. Providers without default endpoints require `base_url`.
LLM API formats are `auto`, `openai_chat`, `openai_responses`, and `anthropic`,
subject to the provider's supported list. Unknown fields, literal `api_key`
fields, and credentials in URLs are rejected. Advanced settings and other
service types remain available in Web Settings.

For knowledge bases/RAG, also configure an accessible embedding model. For example:

```json
{
  "embedding": {
    "provider": "openai",
    "model": "text-embedding-3-small",
    "api_key_env": "DEEPTUTOR_SETUP_EMBEDDING_KEY",
    "dimension": 1536
  },
  "search": { "provider": "duckduckgo" }
}
```

Embedding `base_url` is the full endpoint, such as
`https://api.openai.com/v1/embeddings`; the catalog normalizes it as the Web UI
does. Changing an existing KB's embedding model/dimensions requires planning
a rebuild. Omit search when unnecessary, or choose `none` to disable it.
DuckDuckGo needs no key; availability depends on the user's network.

For local Ollama, use `{"llm":{"provider":"ollama","model":"YOUR_LOCAL_MODEL"}}`
and verify that Ollama is running and the model is available.

For OAuth, apply the provider ID/model from `config providers`, then use its
existing login command in the same runtime home. The user completes any login
interaction:

```bash
deeptutor provider login openai-codex
# Other supported flows: github-copilot, codebuddy
```

OpenAI Codex uses DeepTutor's own OAuth credentials; the external agent's login
is not automatically reused. Login does not select a model.

## 5. Verify and start

```bash
deeptutor doctor --format json
deeptutor doctor --online --format json
```

The first checks local readiness; the second makes a small real model request
and may incur provider usage. Inspect exit status and required failures. Fix
actionable failures and rerun affected checks. Saved settings alone are not
proof of readiness. The LLM probe does not verify optional embedding: when RAG
is requested, also test its connection in Settings and ingest/search a small
user-approved document.

For the full app:

```bash
deeptutor start --detach --no-browser
```

Read the actual launcher URLs, verify backend `/health/ready`, and confirm the
frontend responds. Defaults are backend `http://127.0.0.1:8001` and frontend
`http://127.0.0.1:3782`; use the reported ports if different. Inspect launcher
logs on failure. Choose free ports through `config apply` instead of stopping
unrelated processes. For CLI-only, skip Web startup; a short
`deeptutor run chat` with `--format json` can verify turn execution if needed.

Finish with the checkout/environment, runtime home, provider/model without
credentials, passed checks, Web URL or CLI invocation, and any remaining user
action. Include `deeptutor stop` with the same home for a detached app. If
credentials or network access prevent verification, state the exact unfinished
step instead of declaring setup complete.

## 6. Troubleshooting

Use the following approach to investigate the user's symptom. Choose checks
based on evidence; there is no need to run every command for every problem.

1. **Identify the running instance and reproduce the symptom.** Establish the
   installation method, installed version or source commit, active Python
   environment, runtime home, and actual service URLs. For Docker, distinguish
   container paths/ports from host paths/ports. Ask for the failing action,
   expected result, approximate time, and relevant recent changes. Confirm
   that your CLI checks target the same instance, account, and workspace as
   the user; a healthy second installation tells you little about the failure.

2. **Collect the smallest useful evidence.** Use `config show` and `doctor`
   for configuration/readiness, `doctor --online` for a real LLM request, or
   `doctor runtime` for turn coordination, session storage, and migration
   preflight. Add `--format json` to either doctor mode. Inspect individual
   checks: top-level `ok: true` can coexist with optional failures such as RAG.
   A passing LLM probe does not prove that embedding, search, tools, or the
   browser's connection work.

3. **Follow the failing operation across its boundaries.** Start from the
   visible symptom and determine how far the operation got: browser → API →
   turn/capability → provider, tool, or storage. Inspect browser console and
   network errors for UI problems, and correlate server logs by time and
   `request_id`, `session_id`, or `turn_id` when present. For detached launches,
   check `<runtime-home>/data/user/runtime/launcher.log`; application logs
   normally live in `data/user/logs/deeptutor.jsonl`, subject to logging settings.
   Container deployments may also require container output. Read a narrow
   relevant excerpt and remove credentials and private content before sharing.

4. **Test one hypothesis at a time.** Reduce the failing action to a small
   reproduction and compare a working path with the failing one. For example,
   a successful CLI turn with a failing Web turn directs attention toward the
   browser/API path, provided both use equivalent settings and context. Use
   `--help`, `plugin info`, and the checked-out code to continue investigating.
   The root `AGENTS.md` maps the architecture; useful starting points include
   `deeptutor_cli/`, `deeptutor/api/`, `deeptutor/runtime/`,
   `deeptutor/capabilities/`, `deeptutor/services/`, and `web/`. Match source to
   the installed version before drawing conclusions.

5. **Make a focused fix and verify the original action.** Preserve existing
   data and configuration; avoid blanket reinstalls, resets, or KB rebuilds
   as exploratory steps. Rerun the user's failing operation after the change,
   not only a general health check. Report observations separately from
   hypotheses. If unresolved, provide a concise handoff: environment/version,
   reproduction, expected versus actual behavior, relevant redacted errors,
   checks already tried, and the next useful investigation.
