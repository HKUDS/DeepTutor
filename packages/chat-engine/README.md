# Experimental TypeScript chat engine

This package owns the chat/partner **agent loop, Chat Completions model calls,
stream decoding, source investigation, conversation projection, history budgets,
rolling summaries, stateless text service calls and tool-batch execution** in the `typescript-native` profile. It runs in a private
Node child of DeepTutor. The Python application still owns authentication, durable
turns, session storage, capability admission, partner channels and unmigrated tools.
The browser protocol and stored session format remain compatible.

## Run and roll back

Node 22+ is required. There are no production npm dependencies.

```sh
cd packages/chat-engine
npm ci
npm test
cd ../..
DEEPTUTOR_CHAT_ENGINE=typescript-native deeptutor start
```

| Profile | Execution |
| --- | --- |
| `python` (default) | Reference Python scheduler and effects; Python-only installs work |
| `typescript` | Phase-one TS scheduler, Python model/context/tool effects |
| `typescript-native` | Native TS execution for admitted providers, compatibility execution for others |

Select a profile and restart to change engines. No data migration is needed.
`DEEPTUTOR_NODE_EXECUTABLE` selects Node. A missing build or failed worker fails
clearly; the engine never silently replays an in-flight turn in Python. This source
experiment is not yet packaged in Python wheels.

Native admission currently covers standard, single-key OpenAI-compatible **Chat
Completions** providers, including the configured DeepSeek model. Responses API,
provider-specific wire formats, managed/OAuth authentication, key pools, Azure,
and custom proxy/CA/TLS settings use compatibility execution, selected before
effects. The result reports `execution_runtime` and a `compatibility_reason` when
applicable. This is a deliberate compatibility boundary, not full provider parity.

## Module boundaries

```text
CLI / WebSocket / Partner channels
           │
Python TurnApplicationService — durable journal, auth, scopes, branch selection
           │
Native seed + scoped application ports
           │
TS NativeSession
   ├── core/run-loop       pure scheduling, budgets, pause and settlement
   ├── context/            history selection, summary, request projection
   ├── providers/          HTTP, SSE, usage, cancellation and admission limits
   └── tools/              batch orchestration and native implementations
           │
Python checkpoint/event ports and individual legacy-tool calls
```

| Module | Responsibility |
| --- | --- |
| `src/core/` | Scheduler contracts and state transitions; no I/O or provider dependencies |
| `src/native/` | Per-turn session and streamed model-round lifecycle |
| `src/context/` | Complete history groups, summaries, snapshots, tool/image replay and budget projection |
| `src/providers/` | Bounded HTTP/SSE parsing, provider compatibility and shared concurrency limits |
| `src/tools/` | Admission, deduplication, private-field filtering, execution and result ordering |
| `src/transport/stdio.ts` | Multiplexed private IPC, cancellation and backpressure |
| `deeptutor/runtime/ts_engine/` | Worker lifecycle, preflight provider routing and tool-free completion adapter |
| `deeptutor/agents/loop/native_seed.py` | Server-owned scopes, admitted tools, prompt fragments and initial seed |
| `deeptutor/agents/loop/native_adapter.py` | Application checkpoints/events, capability policy and scoped legacy tools |
| `deeptutor/agents/loop/native_tools.py`, `native_memory.py` | Server-owned model/source/memory grants |
| `deeptutor/capabilities/explore_context/native.py` | Source admission and thinking-only events for the shared TS investigation loop |
| `deeptutor/services/llm/provider_core/typescript_provider.py` | Existing service API backed by native text transport; rich-request preflight |
| `deeptutor/services/session/native_history.py` | Selected-branch rows and successful summary persistence |

Native tools: `workspace_list`, `workspace_read`, `workspace_search`, `read_skill`,
`ask_user`, `read_source`, `reason`, `brainstorm`, `read_memory`, and `partner_read`.
Workspace paths remain confined to an admitted root; skills, source IDs and memory
roots are supplied by the scoped application, never selected by model-supplied
private arguments. Memory reads are live, read-only and limited to the four L3
documents (2 MiB per file). Partner shared/relationship memory remains separated.
Plugin replacements and custom capability augmentation retain their implementation.

`reason` and `brainstorm` reuse the native provider with server-selected prompts and
parameters; observations never stream into the main answer and subcall usage is
included. Attached-source investigation reuses `NativeSession` with a read-only
`read_source` surface and a five-round budget. It emits thinking/trace events only
and never overwrites the answer's transcript. A failed investigation may try a
read-only, tool-free native briefing; it never falls through to Python model I/O.

Stateless text calls through the services LLM factory also use TS on supported
profiles, including suggestions and memory-extraction model calls. The Python
feature still owns its workflow and writes. Image requests, tools/provider-state
replay, SDK-specific request options, prompt caching and model-prefix rewrites
retain SDK compatibility, selected **before** a request. Native retries are owned
by Node and respect service retry delays; no Python retry follows a partial result.

`ask_user` normalization and draft streaming run in TS; the application retains
waiting and resume. Writes, sandbox execution, RAG/media processing, notebook and
calendar stores, MCP, channel delivery and domain-specific tool policies remain
scoped application ports. TS owns batch orchestration for those tools too.

Context projection is separate from durable history: compaction cannot erase the
record of completed effects. A failed/incomplete summary does not advance the
watermark. Token budgeting uses a conservative **character estimate**, including
image allowances; provider usage remains authoritative for billing. This estimate
is not an exact tokenizer and can retain fewer turns than the reference path.

## Failure and resource behavior

- One worker per Python event loop, at most 128 admitted runs; queues, frames,
  response bodies, tool arguments and concurrent model operations are bounded.
- Native IPC carries prompts, credentials and results through private pipes.
  It must never be logged. The child receives a minimal environment; API keys
  are scoped to each request, not inherited as global worker credentials.
- Events are acknowledged after application publication, providing backpressure.
  Adjacent content/thinking deltas coalesce within 16 ms or 8 KiB; first tokens,
  trace changes and tool/status boundaries flush immediately. Deferred answers
  also use bounded chunks. Tool results reach the UI in completion order while
  model history retains source order. Each completed result updates the application
  checkpoint before its completion event, preserving finished work on cancellation.
- Truncated model output cannot execute any tool in that batch, even if one
  argument object is valid JSON. Pausing and rebinding tools retain special order.
- HTTP connect/read inactivity is bounded at 90 seconds. Partial model output
  is never retried automatically. Cancellation interrupts network work and pending
  host calls. User waits have no artificial model-response timeout.
- Worker loss fails active turns without replaying effects. The durable journal
  retains application-persisted events. Interim model checkpoints update Python's
  turn runtime; SQLite persistence still belongs to the application lifecycle, so
  this is **not** a per-tool crash-durable transaction log. Interrupted calls carry
  explicit unknown-outcome placeholders. Automatic crash-resume is not implemented.
- Idle workers exit after 30 seconds with no active work, releasing their memory.
  Waiting for user input counts as active work. The next turn pays worker startup.
- Native model limits are shared by provider identity within a worker. Python
  compatibility traffic has its own limiter. This is not a distributed rate quota.
- Model-tool admission and required fields are checked; tool implementations retain
  argument validation. A general JSON Schema validator is not yet part of this package.

The native API profile lazily loads existing router groups using the generated
`deeptutor/api/router_index.json`; authentication/dependencies and OpenAPI remain
those of the original routers. A stale source fingerprint falls back to eager
registration. Regenerate after router edits with the project's Python environment:

```sh
python scripts/build_router_index.py
```

The native path also avoids loading the Python OpenAI SDK and tokenizer for simple
chat, source investigation, reasoning tools, history summaries, titles and admitted
text services. Reading embedding configuration no longer imports embedding adapters
or their SDKs during background catalog scans. The lean Node HTTP transport uses bounded
keep-alive pools; it does not add a second HTTP client SDK. Loading other features
can still increase the Python process memory.

## Pi source review

Reviewed the full checkout of [Pi](https://github.com/earendil-works/pi/tree/482c1381a00d8d00bc81697e4a980c593db6803e)
with focused inspection of agent-core, provider/stream utilities, durable compaction,
and coding-agent session/compaction boundaries. This is a source comparison, not
a Pi runtime performance benchmark. No Pi dependency or copied implementation was added.

Concrete rules adopted in this iteration:

1. Reject an entire tool batch after truncated model output
   ([agent loop](https://github.com/earendil-works/pi/blob/482c1381a00d8d00bc81697e4a980c593db6803e/packages/agent/src/agent-loop.ts)).
2. Publish concurrent tool results promptly while retaining model transcript order
   ([tool orchestration tests](https://github.com/earendil-works/pi/blob/482c1381a00d8d00bc81697e4a980c593db6803e/packages/agent/test/agent-loop.test.ts)).
3. Accept only clean, nonempty, tool-free summaries before moving the durable
   watermark ([durable compaction](https://github.com/earendil-works/pi/blob/482c1381a00d8d00bc81697e4a980c593db6803e/packages/durable/src/harness/compaction.ts)).

Pi also separates model conversion from application messages and loads providers
lazily; those principles align with this package's projection and adapter boundaries.
Its schema validation, queued steering and durable per-tool task model are useful
next boundaries, but importing the complete harness would duplicate current
persistence and introduce provider SDK dependencies. Those need separate measured
migrations. DeepTutor's account/workspace scopes and event backpressure remain here.

## Validation and measurement

```sh
cd packages/chat-engine && npm test
cd ../..
DEEPTUTOR_CHAT_ENGINE=typescript pytest -q tests/agents/chat \
  tests/runtime/test_ts_engine.py tests/services/partners/test_partner_runtime.py \
  tests/capabilities/test_partner_group_capability.py \
  tests/capabilities/test_mastery_loop_pipeline.py
DEEPTUTOR_CHAT_ENGINE=python pytest -q tests/runtime/test_native_engine.py \
  tests/api/test_router_loader.py tests/app/test_turn_application_service.py \
  tests/api/test_unified_ws_turn_runtime.py tests/capabilities/test_explore_context_capability.py \
  tests/services/llm tests/services/embedding
python scripts/check_architecture.py
```

Native tests use real Node pipes and a local HTTP model fixture, and cover concurrent
scope isolation, cancellation, worker loss, partial streams, truncation, history
watermarks, workspace confinement, ask-user drafts and ordering. Router tests compare
eager/lazy auth, dependency overrides, route behavior, WebSockets and OpenAPI.

Compare profiles with the **same project Python environment**, clean test homes,
the same mock-provider delay, and process-tree RSS including Node. Report cold
startup/first response, warm response and post-idle memory separately. Lazy imports
and removing duplicate Python SDK/tokenizer lifetimes explain most observed gains;
a language change alone does not remove model network latency. The prior branch's
notification wakeups, idle GC and plugin discovery optimizations benefit both profiles.
