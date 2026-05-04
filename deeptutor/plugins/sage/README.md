# SAGE Memory Companion (`deeptutor/plugins/sage/`)

Drop-in plugin that gives DeepTutor an **external long-term memory companion**
backed by a [SAGE](https://github.com/l33tdawg/sage) node.

| What it does                  | What it doesn't do                                      |
| ----------------------------- | ------------------------------------------------------- |
| Recalls cross-session pedagogy + subject memories into `deep_solve` / `deep_research` prompts (appended to `UnifiedContext.memory_context`). | Touches the existing per-learner memory layer (`SUMMARY.md`, `PROFILE.md`, `MemoryService`, `MemoryConsolidator`) — those keep working byte-for-byte. |
| Stores one compact observation per `CAPABILITY_COMPLETE` event under `deeptutor-pedagogy`, `deeptutor-{subject}`, `deeptutor-tutor-{learner_id}`. | Stores full agent outputs / conversation transcripts. Only the prompt + capability + tools-used go in. |
| Opts in via a single env var. Graceful no-op when SAGE is down. | Adds new dependencies to default installs — `sage-agent-sdk` is loaded lazily. |

## Why it's worth shipping

DeepTutor already has excellent **per-learner** memory. SAGE is **orthogonal**:
it lets *every tutor instance / classroom / deployment* share consensus-validated
pedagogical lessons (e.g. "students confuse `dx` with `Δx` when first
introduced to differentials") without leaking individual user data — only
distilled observations cross instances.

This is the same shape we shipped against
[RAPTOR](https://github.com/l33tdawg/raptor),
[pentagi v2](https://github.com/vxcontrol/pentagi),
[Aether](https://github.com/l33tdawg/aether), and Level Up: an
**additive plugin**, no surgery on the host.

## Install

```bash
# 1. Install the SAGE Python SDK (lazy import — only loaded when enabled)
pip install sage-agent-sdk

# 2. Make sure DeepTutor is installed normally
pip install -e ".[server]"

# 3. (optional) Run a SAGE node — defaults to http://localhost:8080
#    See https://github.com/l33tdawg/sage for one-liner Docker deployment.
```

The plugin auto-registers via `deeptutor.plugins.loader.discover_plugins`. No
code change is needed in your DeepTutor app.

## Enable

```bash
export SAGE_ENABLED=true
export SAGE_URL=http://localhost:8080         # default
export SAGE_AGENT_KEY=/path/to/agent.key      # optional; auto-generated under ~/.sage/agents/deeptutor-instance/ if missing
```

Then start DeepTutor as usual. On first capability run you should see in
the logs:

```
INFO  deeptutor.plugins.sage.capability: SAGE plugin hooks installed (pre-run wrapped=2, event=CAPABILITY_COMPLETE)
```

## Disable

Just unset `SAGE_ENABLED` (or set it to `false`/`0`). The plugin becomes a
strict no-op — no recall, no remember, no EventBus listener active. The
`sage_memory` capability still appears in `deeptutor plugin list` but its
`run()` reports `enabled=false`.

To rip the plugin out entirely, delete `deeptutor/plugins/sage/`. Nothing
else in the codebase references it.

## Environment variables

| Var                              | Default                  | Purpose                                                |
| -------------------------------- | ------------------------ | ------------------------------------------------------ |
| `SAGE_ENABLED`                   | _unset_                  | `true`/`1`/`yes` enables hooks. Anything else = no-op. |
| `SAGE_URL`                       | `http://localhost:8080`  | Base URL of the SAGE node.                             |
| `SAGE_AGENT_KEY`                 | _unset_                  | Path to an existing agent identity file.               |
| `SAGE_HOME`                      | `~/.sage`                | Base dir used when generating an agent key.            |
| `SAGE_TIMEOUT`                   | `10`                     | Per-request timeout in seconds.                        |
| `SAGE_DEEPTUTOR_DOMAIN_PREFIX`   | `deeptutor`              | Domain-tag prefix for SAGE memories.                   |

## Architecture

```
                      ┌───────────────────────┐
   user turn  ──────► │  ChatOrchestrator     │
                      │  (deeptutor.runtime)  │
                      └──┬──────────────────┬─┘
                         │                  │
              ┌──────────▼─────────┐        │
              │  CapabilityRegistry │       │
              │  load_builtins()    │       │
              │  load_plugins()  ◄──┼── SAGE plugin loaded here
              └──────────┬──────────┘       │
                         │                  │
                         ▼                  │
        ┌────────────────────────────────┐  │
        │  Wrapped capability.run        │◄─┘ pre-run hook
        │  (deep_solve, deep_research)   │
        │   1. SAGE.recall(prompt)       │
        │      append to memory_context  │
        │   2. original.run(...)         │  ← unchanged
        └────────────┬───────────────────┘
                     │
                     ▼
        ┌────────────────────────────────┐
        │  EventBus.publish(             │
        │    CAPABILITY_COMPLETE)        │
        └────────────┬───────────────────┘
                     │
                     ▼
        ┌────────────────────────────────┐
        │  SAGE plugin listener          │
        │   SAGE.remember(...)           │
        │   domains:                     │
        │     deeptutor-pedagogy         │
        │     deeptutor-{subject}        │
        │     deeptutor-tutor-{learner}  │
        └────────────────────────────────┘
```

## Tests

```bash
pytest deeptutor/plugins/sage/tests -v
```

The tests mock the SDK (`sage_sdk` is monkey-patched into `sys.modules`), so
they run without a live SAGE node and without the SDK package installed.
