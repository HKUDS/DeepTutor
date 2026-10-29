# DeepTutor developer and agent handbook

Start here to install, diagnose, or change DeepTutor. This handbook describes
the **1.7.0 source tree**; use the documentation from the same tag when working
on another release. The version authority is
[`deeptutor/__version__.py`](../deeptutor/__version__.py). Commands below run
from the repository root unless a page says otherwise.

## Choose a reading path

| Your task | Read in order | Completion evidence |
| --- | --- | --- |
| Install and configure the app | [Agent setup](AGENT_SETUP.md) → [Storage](DATA_STORAGE.md) | Dependencies, module readiness, actual model response, reachable app |
| Fix an existing installation | [Setup troubleshooting](AGENT_SETUP.md#6-troubleshooting) → the relevant topic below | Original failing action works in the same instance and workspace |
| Develop a change | [Development](DEVELOPMENT.md) → [Architecture](ARCHITECTURE.md) → [Testing](TESTING.md) | Focused regression and applicable project checks |
| Add a tool or capability | [Tool and capability contracts](TOOLS_AND_CAPABILITIES.md) → [Modules](MODULES.md) | Registration, availability, execution and terminal-result tests |
| Build a third-party extension | [Plugins](PLUGINS.md) → [Runnable Learning Echo example](examples/learning_echo/README.md) | Wheel, manifest, approval, worker and frontend checks |
| Investigate streaming or memory | [Events and progress](EVENTS_AND_PROGRESS.md) → [Runtime design](RUNTIME_DESIGN.md) | Persistence/replay and cancellation evidence |
| Deploy or upgrade | [Modules](MODULES.md) → [Containers](CONTAINERIZATION.md) → [Storage](DATA_STORAGE.md) | Matching versions, retained data, readiness and a representative turn |

For a terminal-capable agent, read this index, [AGENTS.md](../AGENTS.md), and
the task's guide before editing. [SKILL.md](../SKILL.md) is the compact CLI
reference. Inspect the checkout, working-tree changes, Python environment and
runtime home before following an example. Keep existing user data and
credentials separate from disposable test fixtures. Diagnose a failing
installation before deciding to reinstall it.

## Topic map

### Runtime and extension development

- [Architecture and source owners](ARCHITECTURE.md): entry points, durable
  turns, frontend boundaries and configuration.
- [Tools and capabilities](TOOLS_AND_CAPABILITIES.md): single-shot tools,
  turn-owning pipelines, context gates and result envelopes.
- [Modules](MODULES.md): distribution ownership, installation and lifecycle.
- [Plugins](PLUGINS.md): manifests, review, workers, HTTP and static pages.
- [Reading extensions](READING_EXTENSIONS.md): verified selection context and
  bounded results.
- [Events and progress](EVENTS_AND_PROGRESS.md): turn replay versus indexing
  progress and process-local notifications.
- [Runtime design](RUNTIME_DESIGN.md): lazy loading, isolated parsing, private
  model history and prompt-cache observability.
- [Remote Hermes backend](remote-hermes-backend.md): gateway protocol and
  Connected Agents integration.

### Storage, deployment and feature contracts

- [Data storage](DATA_STORAGE.md) and [workspaces](workspaces.md): runtime
  home, account/workspace scope, backups, resource assignment and migration.
- [Containerization](CONTAINERIZATION.md) and [request screening](SECURITY_GUARD.md):
  deployment configuration, OAuth callback ports and proxy boundaries.
- [Knowledge migration](KNOWLEDGE_MIGRATION.md), [indexing recovery](INDEXING_RECOVERY.md),
  and [source visuals](SOURCE_VISUALS.md): ingestion, publication, original
  evidence and visual assessment.
- [Scientific research](SCIENTIFIC_RESEARCH.md): paper tools, evidence and MCP
  authorization.
- [Practice](PRACTICE.md): question imports, review records and scheduling.
- [Video learning](watching-workspace.md) and [voice](VOICE_CONFIGURATION.md):
  Reading media migration, captions, speech adapters and verification.
- [Answer-quality diagnosis](REASONING_SAFETY_CHECKLIST.md): reproducible
  retrieval, citation, context and assessment failures.

## Keeping this handbook useful

Keep one canonical page for each contract and link to it. Each topic should
point to its implementation owners or regression tests. Update affected
examples when commands, routes, ownership or storage change; generated schemas
and module manifests take precedence over prose. Record what a check proves,
including provider/network or platform limits.

Keep task plans, one-off test counts, screenshots, private paths, downloaded
reference repositories and unrelated product research out of this handbook.
Use PRs or local ignored output for execution evidence. A design proposal is
not current behavior until its implementation can be located and verified.
