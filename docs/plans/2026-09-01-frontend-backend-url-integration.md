# Frontend, Backend, and URL Integration Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Integrate the completed frontend and backend refactors behind one
backend-owned contract, remove obsolete transport and URL surfaces, and prove
the combined application under single- and multi-worker gates.

**Architecture:** Preserve the backend application service and coordinator as
the execution authority, preserve the frontend feature/store split as the UI
authority, and generate the boundary between them from canonical Python. Use
an unversioned `/api`, `/ws`, `/files` topology; require protocol version 2.0 in
WebSocket envelopes; use explicit command acknowledgements for retryable
mutations.

**Tech Stack:** FastAPI, Pydantic v2, Redis Streams, SQLite WAL, Next.js 16,
React 19, TypeScript, Vitest, Playwright, import-linter, Ruff.

---

## Audit record

### Frontend task `01a05b7b-ecff-73b2-8ea9-7d39aea4009b`

Completed well:

- removed browser use of the old chat REST transport;
- introduced selector-based chat state and replay-aware transport;
- split Chat, Settings, Knowledge, Co-Writer, Reading, and runtime status into
  explicit feature boundaries;
- added TypeScript, architecture, rendered UI, build, route-budget,
  accessibility, visual, and multi-worker browser gates.

Still incomplete at integration time:

- generated OpenAPI came from the frontend branch's stale backend snapshot and
  still contained deleted chat session routes;
- the frontend created a second Python `TurnRequest` owner;
- queued mutations had neither stable IDs nor explicit acknowledgement;
- missing `protocol_version` was accepted and silently filled in;
- the capability UI fell back to hardcoded descriptors because the backend
  endpoint returned only names;
- `/home`, `/api/v1`, and Settings leaf routes remained; the direct
  `mastery_path` capability and browser workspace action were not clearly
  distinguished;
- real four-worker browser execution was registered but not run.

### Backend task `01a05b7c-1ca7-7773-b7af-0829de2cd43f`

Completed well:

- introduced a process-level application container and one turn application
  service for adapters;
- replaced process identity caching with stable store scope;
- added memory/Redis coordination, leases, fencing, command streams, recovery,
  event journaling, WAL repositories, and leader-owned background services;
- removed the old chat router and split the 3,500-line runtime into focused
  services behind a small facade;
- moved runtime implementations out of `core` and added dependency gates;
- added typed request validation, runtime health, real Redis tests, multi-process
  tests, and deployment worker settings.

Still incomplete at integration time:

- CI retained backend gates but replaced the frontend's complete gate;
- the browser-facing WebSocket adapter did not validate the exported protocol
  and did not emit its declared version;
- the public capability endpoint bypassed the new canonical catalog;
- stale runtime-topology copy still recommended deleted compatibility routes;
- the public contract did not explain that `mastery_path` remains a direct
  CLI/SDK capability while the browser uses `workspace_mode=mastery_path`;
- broad API paths remained on `/api/v1`, with two separate file namespaces;
- canary rollout and the real four-worker browser matrix remained external.

### URL task `01a05b7b-b358-72e0-89ad-61401f7941bb`

The task correctly selected unversioned canonical URLs and a breaking cleanup,
but neither implementation task applied the decision beyond deleting the old
chat router. The repository still exposed `/api/v1`, `/home`, singular resource
prefixes, RPC path verbs, duplicate Settings routes, and compatibility
browser workspace inference from `capability == "mastery_path"`.

## Non-functional acceptance

- **Correctness:** one active turn per session; no duplicate accepted mutation;
  no event gap after reconnect; generated schemas match the running app.
- **Scalability:** four Uvicorn workers with Redis; 200 sessions and 1,000 turns
  remain the coordinator stress target.
- **Reliability:** owner loss becomes a retryable `worker_lost` failure; browser
  recovery never treats an arbitrary event as command acknowledgement.
- **Security:** route migration must preserve auth dependencies; schemas and
  runtime status must not expose Redis URLs, tokens, or passwords.
- **Maintainability:** core cannot depend on adapters; frontend page modules
  stay thin; old route strings and retired transport imports are blocked.
- **Operations:** release remains gated by the real 4-worker browser suite and a
  1 -> 2 -> 4 worker canary.

## Task 1: Integrate without mutating source worktrees

**Files:** Git state only.

1. Snapshot the dirty backend workspace on an isolated integration branch.
2. Verify status, tracked diff, and untracked-file hashes match the source.
3. Merge `codex/frontend-stabilization-v2` with a three-way merge.
4. Resolve ownership: backend contracts, frontend pages/state, additive CI.
5. Run `git diff --check` and commit the integration checkpoint.

## Task 2: Establish one request and wire contract

**Files:**

- Modify: `deeptutor/core/turn_request.py`
- Modify: `deeptutor/app/contracts.py`
- Modify: `deeptutor/api/contracts/turn_protocol.py`
- Modify: `deeptutor/api/contracts/export.py`
- Test: `tests/api/test_frontend_contract_export.py`

1. Add typed nested request value objects to `core`.
2. Make `app.contracts` a re-export only.
3. Add command IDs, command acknowledgement, protocol error, recovering active
   state, and owner ID to wire models.
4. Make the exporter fail on duplicate operation IDs.
5. Write failing schema assertions, run them, implement, and rerun.

## Task 3: Enforce the protocol in the WebSocket adapter

**Files:**

- Modify: `deeptutor/api/routers/unified_ws.py`
- Test: `tests/api/test_unified_ws_turn_runtime.py`

1. Write tests for missing/future version rejection and v2 responses.
2. Validate every command through the discriminated Pydantic union.
3. Strip wire-only fields before invoking `TurnApplicationService`.
4. Emit versioned `command_ack`, `protocol_error`, active-turn, pong, and replay
   frames.
5. Verify cancel, reply, input, recovery, and bad-command paths.

## Task 4: Make browser command recovery truly idempotent

**Files:**

- Modify: `web/contracts/parse/turn-command.ts`
- Modify: `web/contracts/parse/turn-event.ts`
- Modify: `web/features/chat/transport/TurnRuntimeClient.ts`
- Test: `web/tests/turn-protocol-parser.test.ts`
- Test: `web/tests/turn-runtime-client.test.ts`

1. Write a reconnect test proving unrelated stream events do not acknowledge a
   command.
2. Write a matching-ack test proving the command is then removed.
3. Attach one stable ID before first send and retain it across generations.
4. Require protocol version on all parsed server frames.
5. Parse pong, active-turn, command-ack, protocol-error, and stream frames as
   distinct envelopes.

## Task 5: Expose the real capability catalog and separate capability from workspace

**Files:**

- Modify: `deeptutor/api/routers/capabilities.py`
- Modify: `deeptutor/runtime/bootstrap/builtin_capabilities.py`
- Modify: `deeptutor/runtime/request_contracts.py`
- Modify: `deeptutor_cli/main.py`
- Modify: `web/features/capabilities/presentation.tsx`
- Modify: `web/lib/mastery-session.ts`
- Test: `tests/api/test_capabilities_router.py`
- Test: `web/tests/capability-catalog.test.ts`
- Test: `web/tests/mastery-session.test.ts`

1. Return ID, kind, availability, manifest, and config schema from the backend.
2. Preserve `mastery_path` registration and its CLI/SDK alias: it is the direct
   Guided Learning entry point and owns leases outside the browser runtime.
3. Keep it out of the browser action chooser, where Mastery is a workspace and
   per-turn actions are Chat, Quiz, Research, and similar capabilities.
4. Preserve `mastery_path_id` and workspace mode as product/domain data.
5. Remove capability-based legacy browser workspace inference.
6. Assert the direct capability appears in the backend catalog but is not
   offered as a nested browser action.

## Task 6: Apply the unversioned canonical transport topology

**Files:**

- Modify: `deeptutor/api/main.py`
- Modify: API clients under `web/lib`, `web/features`, and `web/hooks`
- Modify: API and browser tests under `tests` and `web/tests`
- Modify: `web/lib/proxy-policy.ts` and `web/proxy.ts`

1. Add route-surface tests that reject `/api/v1` and require `/api`.
2. Migrate REST clients and mounts atomically from `/api/v1` to `/api`.
3. Mount the turn WebSocket at `/ws`.
4. Move output and attachment delivery to `/files/outputs` and
   `/files/attachments`.
5. Remove exporter or proxy exceptions that name old paths.
6. Add a whole-repository source guard for obsolete transport paths.

## Task 7: Apply canonical browser page URLs

**Files:**

- Move: `web/app/(workspace)/home/[[...sessionId]]/page.tsx` to
  `web/app/(workspace)/chat/[[...sessionId]]/page.tsx`
- Modify: `web/lib/mastery-session.ts`
- Modify: sidebar, handoff, launch-intent, and route-controller modules/tests
- Modify: Settings navigation and route-budget/audit configuration

1. Write route tests for `/chat/{sessionId}` and product-specific session URLs.
2. Replace `/home` navigation with `/chat` and remove `/?session=` parsing.
3. Change mastery session URLs to
   `/mastery/{pathId}/sessions/{sessionId}`.
4. Change reading session URLs to
   `/reading/{workspaceId}/sessions/{sessionId}`.
5. Make `/settings#section` canonical and delete leaf page routes after all
   navigation points use fragments.
6. Update static-page, route-budget, Playwright, and sidebar expectations.

## Task 8: Normalize resource namespaces without compatibility aliases

**Files:** `deeptutor/api/main.py`, affected routers, typed clients, and tests.

1. Freeze the old-to-new route matrix from the running OpenAPI document.
2. Normalize top-level nouns: `/api/books`, `/api/notebooks`,
   `/api/knowledge-bases`, `/api/mastery-paths`, `/api/personas`, and
   `/api/documents`.
3. Keep `/api/reading` as a bounded-context namespace because it owns several
   resource collections (workspaces, materials, annotations, vocabulary, and
   read-aloud jobs); do not misrepresent the whole subsystem as one collection.
4. Replace `/list` and `/create` with collection GET/POST.
5. Place non-CRUD operations under `/actions/{verb}` where a resource state
   transition cannot express the intent.
6. Regenerate clients only after route tests pass.
7. Reject every removed route with 404; do not add aliases.

## Task 9: Regenerate contracts and combine release gates

**Files:**

- Modify: `.github/workflows/tests.yml`
- Regenerate: `web/contracts/schema/*.json`
- Regenerate: `web/contracts/generated/*.ts`

1. Run Python contract tests and repair route operation IDs at their source.
2. Run `python scripts/export_frontend_contracts.py`.
3. Run `npm run contracts:generate` and `npm run contracts:check`.
4. Keep import-linter, AST architecture, Redis, Python 3.11-3.14, full frontend
   check, browser audit, and conditional four-worker browser jobs together.

## Task 10: Verify and release

1. Run focused Python and Node tests after each task.
2. Run `ruff check`, `ruff format --check`, `lint-imports`, and architecture
   checks.
3. Run full Python tests with Redis.
4. Run `npm run check`, critical Playwright, and UI audit.
5. Run the registered 12-case four-worker browser suite against a real fixture.
6. Canary one, two, then four workers; confirm zero old URLs, command duplicates,
   event gaps, credential logs, and duplicate background leaders.

The implementation branch may be merged only after Tasks 1-9 pass locally.
Task 10's real fixture and canary remain release-environment gates.
