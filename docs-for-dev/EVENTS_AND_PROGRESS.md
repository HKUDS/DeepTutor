# Events, durable replay and indexing progress

[Handbook](README.md) · [Architecture](ARCHITECTURE.md) · [Indexing recovery](INDEXING_RECOVERY.md)

Different event systems have different persistence guarantees. Start with
the operation being diagnosed; a process-local notification is not a durable
turn journal.

| Flow | Main owners | What to inspect |
| --- | --- | --- |
| Model turn | [Application service](../deeptutor/app/service.py), [turn runtime](../deeptutor/services/session/turn_runtime.py), [StreamBus](../deeptutor/runtime/stream_bus.py) | Submission identity, persisted sequence, replay cursor, terminal event |
| Multi-worker coordination | [Coordinator](../deeptutor/runtime/coordination/) | Lease owner, fencing, cancellation notification, recovery |
| Knowledge ingestion | [Progress tracker](../deeptutor/knowledge/progress_tracker.py), [indexing journal](../deeptutor/knowledge/indexing_run.py) | Task identity, source outcomes, publication state, last activity |
| Knowledge UI transport | [Progress ports](../deeptutor/knowledge/progress_events.py), [broadcaster](../deeptutor/api/utils/progress_broadcaster.py), [task stream](../deeptutor/api/utils/task_log_stream.py) | Snapshot, WebSocket progress, SSE logs/terminal state |
| Process notifications | [EventBus](../deeptutor/events/event_bus.py) | Current publishers/subscribers; process lifetime |

## Turn lifecycle

The application service coordinates admission and execution through the shared
session store and runtime. Each execution has a per-turn stream bus; events
must enter the persistence/replay path before adapters deliver them to
consumers. A browser disconnect does not by itself prove the turn failed or
authorize a second execution. Recovery must distinguish an active lease from
a lost worker and preserve terminal state.

When changing streaming, test duplicate submission, reconnect after partial
output, replay after a terminal event, cancellation and worker loss. Preserve
event IDs/sequences and existing projection rules instead of treating arrival
order or rendered text as the durable source of truth. Protocol types live in
[`core/stream.py`](../deeptutor/core/stream.py); the frontend consumes the
contracts under [`web/contracts/`](../web/contracts/).

One worker can use the memory coordinator. More than one backend worker
requires Redis coordination, configured through `system.backend_workers` and
`integrations.turn_coordination`. The
[settings validator](../deeptutor/runtime/coordination/settings.py) rejects
multiple workers with a memory coordinator and rejects Redis without a URL.
Redis is the coordination/notification layer; it does not replace the session
store. `deeptutor doctor runtime --format json` reports runtime diagnostics.

## Knowledge-base progress

`ProgressTracker` persists snapshots and emits through injected progress
ports. The API installs the WebSocket/SSE ports; domain code must not import
FastAPI to report progress. CLI/SDK execution can still persist progress
without a browser broadcaster.

The knowledge router exposes a progress WebSocket and task-log SSE stream.
[`useKnowledgeProgress`](../web/hooks/useKnowledgeProgress.ts) combines them,
tracks the expected task, and reconciles terminal state. Preserve workspace
scope and task identity when reconnecting or applying a snapshot. Logs and
percentage estimates are observations, not proof that an index was published.

The [indexing journal](INDEXING_RECOVERY.md) records source-level success,
failure and interrupted work. Completion must agree with persisted publication;
a parser reaching its last batch is insufficient. Rebuilds must not replace a
queryable version with a partial candidate. For parsing checkpoints and exact
source locators, also read [source visuals](SOURCE_VISUALS.md).

## Debugging sequence

1. Identify the account, workspace, session/turn or KB/task ID and time window.
2. Check durable status first, then the coordinator/worker and transport.
3. Compare the browser's cursor/task identity to the server's persisted state.
4. Reproduce dropped connections, old snapshots and duplicate frames with
   fixtures. Do not repair progress by overwriting success fields manually.
5. Verify terminal state after reopening, not only while the original browser
   connection remains alive.

Relevant suites include [application tests](../tests/app/),
[coordination tests](../tests/runtime/coordination/),
[knowledge tests](../tests/knowledge/), and
[knowledge progress WebSocket tests](../tests/api/test_knowledge_progress_ws.py).
