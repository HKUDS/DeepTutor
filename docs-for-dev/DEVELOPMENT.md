# Developing DeepTutor

[Handbook](README.md) · [Architecture](ARCHITECTURE.md) · [Testing](TESTING.md)

## Prepare a source environment

Follow [Agent setup](AGENT_SETUP.md) for Python 3.11–3.14, Node.js 22 LTS,
provider configuration and readiness. A source checkout exposes all modules;
install its external dependencies before the editable core:

```bash
python -m pip install -r requirements/full.txt
python -m pip install -e . --no-deps
python scripts/install_extras.py dev
cd web
npm ci --legacy-peer-deps
cd ..
```

Use `scripts/install_extras.py` for optional source dependencies. Installing
feature wheels over an editable checkout can obscure source ownership; use a
separate environment for [wheel lifecycle testing](MODULES.md#validation).
System executables such as FFmpeg and LaTeX remain separate prerequisites for
the features that need them.

Inspect `git status`, the active branch and remotes before updating. Develop
against `dev`; follow [contribution policy](../CONTRIBUTING.md) for PR targets.
Reuse an appropriate task checkout or use a separate worktree when concurrent
work needs isolation. Preserve unrelated edits. Keep runtime data and test
outputs out of Git.

## Use a dedicated runtime home

`DEEPTUTOR_HOME` is the directory that owns `data/`, not `data/` itself. Pick
an explicit, private development home and use it for every command. For
example, in a fresh shell:

```bash
export DEEPTUTOR_HOME="$HOME/.local/share/deeptutor-dev"
deeptutor init --non-interactive
deeptutor config show
deeptutor module list
```

Do not point fixtures at an existing learner's runtime. A Content Workspace
is a separate storage and authorization scope; see [workspaces](workspaces.md).
The application does not automatically load the project's `.env` file.

## Run and inspect

For the combined launcher, use `deeptutor start` and read the actual URLs in
its output. For separate development processes, run the API and frontend in
two terminals with the same chosen runtime home:

```bash
# Terminal 1: API, with reload
deeptutor serve --host 127.0.0.1 --port 8001 --reload
```

```bash
# Terminal 2: frontend, from web/
DEEPTUTOR_API_BASE_URL=http://127.0.0.1:8001 npm run dev
```

Choose free ports; do not stop unrelated services. Confirm browser requests
reach the intended API through the frontend proxy. A listening frontend alone
does not establish provider, module or turn readiness. Use
`deeptutor doctor --format json` and the original user operation to verify.

## Make a change at its owner

1. Reproduce the behavior with a minimal synthetic fixture. Identify whether
   the owner is the adapter, shared runtime, capability, tool, feature store,
   provider, or frontend projection.
2. Read the nearest implementation and its tests. For API changes, follow
   request validation through authentication, account/workspace resolution,
   persistence, events and UI consumption.
3. Change that owner rather than adding a second runtime, path resolver,
   provider client or storage abstraction. Shared protocols stay import-light.
4. Update module declarations, request contracts, prompts and locale strings
   when affected. Regenerate derived files with their owning scripts.
5. Run [checks appropriate to the change](TESTING.md), reproduce the original
   action, and explain any validation limits in the PR.

Use explicit argument lists and `shell=False` for subprocesses; retain process
tree cleanup on cancellation. Resolve storage through the existing account
and workspace context rather than constructing a global data path. Never
return credentials or private provider-replay metadata to browser responses.

## Generated files and documentation

The repository intentionally tracks generated API contracts, requirement
files and dependency locks. Update their generators or authoritative inputs,
then regenerate. `web/.next*`, installed dependencies, bytecode, logs and
manual acceptance artifacts stay untracked.

Update the relevant handbook topic and README links when a public behavior
changes. Put reusable executable examples under this handbook's
[`examples/`](examples/learning_echo/README.md). Keep command examples usable
from the repository root and avoid personal machine paths.

### Conversation reasoning levels

Language-model settings can store `enabled_reasoning_efforts` on each model.
This list controls choices in the conversation composer, including Chat, Deep
Research, Question Generation, and Deep Solve; it does not set a fixed effort
for every request. An empty list leaves requests on the provider default. Interactive capability turns use provider defaults when no effort is selected;
background and indexing callers retain the legacy default. A conversation's explicit choice is checked against
the enabled list and any managed catalog declaration before dispatch. Manually
selecting a level is not evidence that an API endpoint supports it.

The language-model connection test also reads explicit reasoning-level metadata from
compatible provider model endpoints or the managed Codex catalog. Results show
their source and are offered for manual adoption into `enabled_reasoning_efforts`;
testing never changes the catalog automatically. Missing or unavailable metadata
is unknown, not an empty supported list. Built-in family guesses and successful
completion responses are not treated as provider declarations. No additional
per-level generation requests are sent. Read-only models keep their managed
settings flow.
The declared model levels stay visible. Adoption is limited to the active
transport's representable levels, which are shown separately when narrower,
so a binary thinking switch is not presented as several distinct efforts.
Background task-model diagnostics retain their separate, short connection probe.
Metadata is collected independently before the generation probe. If generation
fails, that failure remains visible while known, usable metadata can still be
adopted to help correct the settings.

For supported Anthropic effort-based families, explicit selections are sent as
`output_config.effort` alongside adaptive thinking. Budget-based or unknown
Anthropic families retain manual configuration; an unsupported effort capability
alone does not imply that thinking controls are unavailable.

Research and question-generation pipelines inherit the turn-scoped model config.
Existing step-specific recovery calls may lower reasoning when recovering from
an exhausted output budget; the conversation preference remains unchanged.
