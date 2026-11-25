---
title: Memory
description: Inspectable personalization — an L1 workspace mirror, L2 per-surface summaries, L3 cross-surface synthesis, and a Memory Graph of the references between them.
quadrant: explanation
---

Memory is DeepTutor's **inspectable** personalization system. It is deliberately *not* a hidden vector store — it is a three-layer pipeline you can read, curate, and audit. Claims sit beside their workspace-entity or source-surface references, whose precision is visible rather than overstated.

## Where it is

Open **Personalization → Memory** from the left sidebar. The overview presents all three layers at a glance, with a live count for each, plus **Refresh**, **Memory settings**, and the entry into the **Memory Graph**.

![Memory overview](/screenshots/dev/memory.png)

## The three layers

Memory rises from live workspace entities to synthesized knowledge. Each layer is a different level of abstraction over what persists.

| Layer | Tag | Storage | Role |
| --- | --- | --- | --- |
| **L1 · Workspace mirror** | LIVE | workspace + `snapshot/<surface>/` | Current entities on each surface. **Refresh** stores fingerprints, labels, `last_refresh`, and append-only changes. |
| **L2 · Per-surface summaries** | CURATED | `L2/<surface>.md` | Surface facts extracted from live L1 entities, citing the entities behind them. |
| **L3 · Cross-surface synthesis** | SYNTHESIS | `L3/<profile\|recent\|scope\|preferences>.md` | Update and Audit synthesize profile, recent, and scope from L2. Chat writes Preferences only through `write_memory`. |

Memory spans `chat`, `notebook`, `quiz`, `kb`, `book`, partner, and `cowriter`. L2 can cite a specific L1 entity, while current L3 citations usually name an entire L2 surface. Preferences follow explicit chat writes. The references remain inspectable, but their granularity differs.

## The Memory Graph

The graph places the automatically synthesized L3 slots — profile, recent, and scope — at the centre, **L2 facts in the middle, and live L1 entities outside**. Hover to preview; click to lock and highlight available links. Preferences is not plotted.

![Memory graph](/screenshots/dev/memory-graph.png)

L2-to-L1 links can target a cited entity. Current L3 references name a surface, so the graph draws a soft link to its L2 cluster, not an exact end-to-end chain. Use it to locate supporting areas and inspect their facts and entities.

Update, Audit, and Dedup budgets are **Settings → Memory**. See [Settings](/self-hosting/settings/). `deeptutor memory show` prints a layer; the flags are in the [command reference](/developers/reference/cli/).

## Good practice

- Keep memory on for long-running learning workflows — that's when it pays off.
- Review L3 when DeepTutor's tone or assumptions feel off; for the synthesized slots, the graph shows available supporting surfaces and entities.
- Refresh L1 to record what changed in the workspace; L2 Update reads the current workspace snapshot directly.
- In multi-user mode, non-admin users have private Partner relationship memory; the Partner also reads the interacting user's shared memory and writes only its relationship memory.

## Account-level personalization, workspace-aware evidence

Memory is under **Personalization**, so switching workspaces does not create a new personal identity. Its workspace mirror and source references still describe concrete material: distinguish a preference that should travel with you from a project-specific fact. Workspace instructions are the better place for rules such as “Use the notation in this course”; memory preferences fit lasting choices such as “Ask me to attempt a problem before giving the solution.”

Try stating a preference explicitly in Chat, then inspect Memory to verify what was saved. Open the cited source when a summary is surprising, and correct the relevant document or preference rather than assuming every synthesis is current. A saved favorite keeps source content; a learning journal tracks mission and handoff; memory summarizes personalization. None of these is a substitute for checking the original evidence.

## See also

- [Home](/learning-workspace/chat/) — the loop that reads and writes memory
- [Partners](/channels/) — how a partner's memory relates to yours
- [Settings](/self-hosting/settings/) — the full control plane
