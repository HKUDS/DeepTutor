# SAGE Memory Companion — DeepTutor Integration Plan

## Motivation

DeepTutor's per-learner memory layer (`SUMMARY.md` + `PROFILE.md`,
`MemoryService`, `MemoryConsolidator`) is excellent at capturing what
*one* student knows and prefers. It is also intentionally local — there is
no story for **cross-tutor knowledge sharing** today. As DeepTutor scales
into classrooms, deployments, and individual tutors who each run their own
instance, every tutor re-discovers the same pedagogical lessons in
isolation:

> "Students confuse `dx` with `Δx` when first introduced to differentials."
> "Visual derivations of definite integrals improve retention vs. symbolic ones."
> "When a learner asks about Fourier transforms, anchor on time → frequency before touching complex exponentials."

These are institutional insights — they should be *shared* across
deployments without leaking individual user data. That's the gap
[SAGE](https://github.com/l33tdawg/sage) fills: a governed, BFT-consensus
memory layer with confidence scoring, decay, and per-agent identity.

This PR ships an **additive plugin** that gives DeepTutor an external
long-term memory companion. It is orthogonal to `MemoryService` and does
not modify a single line of the existing per-learner memory code.

## Architecture diff

### What's added (Python plugin in `deeptutor/plugins/`, plus the new web surface)

```
deeptutor/plugins/__init__.py            (NEW)  Plugin namespace docstring.
deeptutor/plugins/loader.py              (NEW)  Generic manifest.yaml-driven plugin loader.
                                                  AGENTS.md already documents this file as
                                                  the plugin discovery entry point — both
                                                  CapabilityRegistry.load_plugins and
                                                  /api/plugins/list reference it but it
                                                  hadn't been implemented yet.
deeptutor/plugins/sage/manifest.yaml     (NEW)  Plugin metadata + hook declarations.
deeptutor/plugins/sage/__init__.py       (NEW)
deeptutor/plugins/sage/client.py         (NEW)  Singleton wrapper around sage-agent-sdk.
                                                  Adapted from RAPTOR / Aether (~250 LOC).
deeptutor/plugins/sage/capability.py     (NEW)  BaseCapability subclass + pre/post hooks.
deeptutor/plugins/sage/README.md         (NEW)  Install / enable / disable / env vars.
deeptutor/plugins/sage/tests/__init__.py (NEW)
deeptutor/plugins/sage/tests/test_sage_capability.py (NEW)
deeptutor/api/routers/plugins_sage.py    (NEW)  /api/v1/plugins/sage/{status,toggle} —
                                                  status probe + best-effort runtime
                                                  enable/disable for the Playground tile.
tests/api/test_plugins_sage_router.py    (NEW)  Backend tests for the status endpoint
                                                  (4 mocked-client cases).
web/components/plugins/SagePluginTile.tsx (NEW) Status tile rendered inside the Playground
                                                  page. Connected / Disabled / Disconnected /
                                                  Not configured states. "Open SAGE Dashboard"
                                                  link only when Connected. Best-effort toggle.
INTEGRATION_PLAN.md                      (NEW)  This document.
```

**Edits to pre-existing files (kept tiny on purpose, ~7 lines total):**

* `deeptutor/api/main.py` — import `plugins_sage` and register it under the
  `/api/v1/plugins` prefix (2 lines).
* `web/app/(workspace)/playground/page.tsx` — import `SagePluginTile` and
  render it once, just below the page header (5 lines).

### What's untouched (zero surgery)

| Subsystem                      | Why we left it alone                                            |
| ------------------------------ | --------------------------------------------------------------- |
| `deeptutor/services/memory/`   | Per-learner SUMMARY/PROFILE — completely orthogonal to SAGE.    |
| `deeptutor/agents/solve/main_solver.py` | Reads `UnifiedContext.memory_context`; we append, never replace. |
| `deeptutor/runtime/orchestrator.py`     | Already publishes `CAPABILITY_COMPLETE` — we just subscribe.   |
| `deeptutor/runtime/registry/capability_registry.py` | Already calls `deeptutor.plugins.loader.discover_plugins`; we just provide that module. |
| `deeptutor/api/routers/plugins_api.py`  | Already calls `discover_plugins()`; the SAGE plugin shows up in `/plugins/list` automatically. |
| `BaseCapability` protocol      | Unchanged. We wrap registered *instances*, not the protocol.     |
| `pyproject.toml` dependencies  | `sage-agent-sdk` is **not** added to any `[project.optional-dependencies]` — it is loaded lazily and only required when the user opts in. |

The diff outside `plugins/` is exactly **0 lines**.

### Web Playground Surface

The Next.js Playground page (`web/app/(workspace)/playground/page.tsx`)
already fetches `/api/v1/plugins/list` to enumerate tools + capabilities,
but plugins themselves were never rendered visually. We added a single
status tile so SAGE has a discoverable presence in the UI:

* **`web/components/plugins/SagePluginTile.tsx`** — fetches
  `/api/v1/plugins/sage/status`, derives one of four states (Connected,
  Disabled, Disconnected, Not configured) and renders a compact card with a
  status badge, the SAGE node URL, the agent_id when known, an "Open SAGE
  Dashboard" link (only when Connected, points at `${SAGE_URL}/ui/`), and a
  best-effort Enable/Disable toggle. Errors degrade to a muted card — the
  tile must never throw and break the rest of the Playground.
* **`deeptutor/api/routers/plugins_sage.py`** — the backend probe. `GET
  /sage/status` returns `{enabled, reachable, agent_id, node_url,
  sdk_installed, plugin_loaded, detail}`. `POST /sage/toggle` flips the
  in-process `SAGE_ENABLED` env var and asks `capability.install_hooks` /
  `uninstall_hooks` to react. The toggle is *not* persisted — restart with
  the env var set in your shell for a permanent change. The README notes
  this caveat.
* **i18n** — strings are wrapped in `t(...)` but no zh-CN entries are
  shipped in this PR. `react-i18next` falls back to the English key text
  (the project sets `keySeparator: false` and uses English keys as ids),
  matching the rest of Playground's untranslated strings.

### Runtime flow

```
                      ┌───────────────────────┐
   user turn  ──────► │  ChatOrchestrator     │  (unchanged)
                      └──┬──────────────────┬─┘
                         │                  │
              ┌──────────▼─────────┐        │
              │  CapabilityRegistry │       │
              │  load_builtins()    │       │
              │  load_plugins()  ◄──┼── SAGE plugin loaded here.
              └──────────┬──────────┘       │   Its __init__ wraps
                         │                  │   deep_solve + deep_research
                         ▼                  │   with a recall pre-hook
        ┌────────────────────────────────┐  │   and subscribes the
        │  Wrapped capability.run        │◄─┘   EventBus listener.
        │  (deep_solve, deep_research)   │
        │   1. SAGE.recall(prompt)       │      Recall block is APPENDED
        │      → memory_context          │      to context.memory_context;
        │   2. original.run(...)         │      MemoryService stays primary.
        └────────────┬───────────────────┘
                     │
                     ▼
        ┌────────────────────────────────┐
        │  EventBus.publish(             │  (unchanged)
        │    CAPABILITY_COMPLETE)        │
        └────────────┬───────────────────┘
                     │
                     ▼
        ┌────────────────────────────────┐
        │  SAGE plugin listener          │
        │   SAGE.remember(...)           │   Compact observation:
        │   domains:                     │     prompt + capability +
        │     deeptutor-pedagogy         │     tools_used + success.
        │     deeptutor-{subject}        │     Full agent_output is
        │     deeptutor-tutor-{learner}  │     NEVER stored.
        └────────────────────────────────┘
```

## Opt-in story

A single env var controls everything:

```bash
export SAGE_ENABLED=true        # opt in
export SAGE_URL=http://localhost:8080   # default
```

* Without `SAGE_ENABLED=true`, the plugin loads but installs no hooks. Its
  capability still appears in `deeptutor plugin list`, but reports
  `enabled=false` and does nothing.
* When `SAGE_ENABLED=true` but the SAGE node is unreachable / `sage-agent-sdk`
  isn't installed, every recall/remember returns an empty result and logs
  at `INFO` once. DeepTutor turns continue normally.
* Recall is best-effort: any exception in the recall hook is swallowed and
  the underlying capability still runs unmodified.
* Remember is fire-and-forget: the EventBus listener catches every
  exception so a SAGE outage cannot break the chat turn.

## Graceful degradation matrix

| State                                  | Behaviour                                              |
| -------------------------------------- | ------------------------------------------------------ |
| `SAGE_ENABLED` unset / not truthy      | Plugin loaded but inert. No hooks. No SDK import.      |
| `SAGE_ENABLED=true`, SDK not installed | One INFO log, hooks installed but every call is a no-op. |
| `SAGE_ENABLED=true`, SAGE node down    | Hooks installed; recall returns `[]`, remember warns once and returns `{}`. Capability turn unaffected. |
| Recall raises mid-turn                 | Caught + logged, original `run()` proceeds with empty SAGE block. |
| Remember raises post-turn              | Caught in EventBus listener; never propagates out.     |

## What gets stored in SAGE

Per-turn observation (one per domain — pedagogy, subject, learner-tutor):

```
[deeptutor:deep_solve] success=ok tools=rag,reason prompt=walk me through integration by parts
```

* No agent output.
* No conversation history.
* No PII beyond whatever the user typed in their prompt.
* Capped at ~400 chars.

## Prior art (same shape, already shipped)

| Host project | Plugin location                          | PR / commit                                           |
| ------------ | ---------------------------------------- | ----------------------------------------------------- |
| RAPTOR       | `core/sage/`                              | l33tdawg/raptor — singleton + sync-pipeline hook      |
| Aether       | `core/sage_client.py` + multi-pass hooks  | l33tdawg/aether — same wrapper, async pipeline        |
| pentagi v2   | `integrations/sage/`                      | vxcontrol/pentagi — Go bridge mirroring this shape    |
| Level Up     | `integrations/levelup/sage_bridge.py`     | l33tdawg/sage `integrations/levelup/`                 |

All four ship as additive plugins with the same env-driven opt-in story
and graceful no-op behaviour. This PR is the fifth.

## Tests

```bash
pytest deeptutor/plugins/sage/tests -v
```

The suite mocks `sage_sdk` via `sys.modules`, so it runs without the SDK
package installed and without a live SAGE node. Coverage:

1. Plugin manifest is discoverable via `discover_plugins()`.
2. Capability class loads via `load_plugin_capability()`.
3. With `SAGE_ENABLED` unset, the plugin is a strict no-op.
4. With `SAGE_ENABLED=true`, recall is invoked pre-`deep_solve` and
   `memory_context` is enriched.
5. With `SAGE_ENABLED=true`, `CAPABILITY_COMPLETE` triggers a `propose()`
   call across all expected domain tags, and the agent output never leaks
   into stored content.
6. The plugin's own `run()` reports status correctly in both states.

## What's intentionally NOT in this PR

To keep the surface tight, this PR does **not**:

* Add `sage-agent-sdk` to any `requirements.txt` / `pyproject.toml` extra.
  Users opting in install it themselves: `pip install sage-agent-sdk`.
* Modify `MemoryService` or `MemoryConsolidator`.
* Touch the orchestrator, the registry implementations, or the EventBus.
* Add new capabilities beyond the `sage_memory` status probe.
* Add UI surface in `web/`.

Each of those is a separate, opt-in follow-up if maintainers want it.
