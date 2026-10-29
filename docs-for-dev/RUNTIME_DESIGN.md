# Runtime design: activation, workers and model history

[Handbook](README.md) · [Architecture](ARCHITECTURE.md) · [Events](EVENTS_AND_PROGRESS.md)

This page retains implemented decisions from earlier design notes. It describes
current boundaries; historical memory measurements and one-machine test counts
are not performance guarantees.

## Lazy activation

Tool/capability catalogs use import-light descriptors. Registry inspection must
not eagerly import unused providers, parsers or optional modules. Registries
load implementations on demand; module selection and plugin approval remain
effective at activation. Compatibility exports may use lazy wrappers to retain
existing import paths.

The frontend similarly defers settings editors. Preserve anchor/navigation
activation and authentication single-flight behavior when changing loading.
Verify with import-boundary tests and frontend route budgets, not only a warm
process timing. Source owners: [registries](../deeptutor/runtime/registry/),
[module assembly](../deeptutor/modules/), and [settings](../web/features/settings/).

## Short-lived parsing workers

Heavy synchronous extraction can retain native-library memory in a long-lived
API process even when run in a thread. The
[isolated-worker boundary](../deeptutor/runtime/isolated_worker.py) launches a
short-lived interpreter through
[`worker_process.py`](../deeptutor/runtime/worker_process.py), using an internal
importable callable and private temporary input/result files.

This is trusted internal IPC. Its serialized Python objects are not an API for
untrusted upload or network input. Clients cannot select an arbitrary callable.
The child process boundary releases its memory on exit, but is not by itself an
OS security sandbox for untrusted code.

Timeout and cancellation must terminate and join the process tree before
returning. Concurrency is bounded by `DEEPTUTOR_ISOLATED_WORKERS` (default two);
call sites can override the default timeout. Keep platform-specific cleanup
and result/error restoration covered by
[worker tests](../tests/runtime/test_isolated_worker.py). Parser failures must
remain distinguishable from empty successful extraction.

## Private model history

Display messages and provider-ready model history serve different purposes.
[`model_history.py`](../deeptutor/services/session/model_history.py) retains a
versioned private `model_turn` with prepared input, snapshots, model/tool
messages, replay metadata and request fingerprints. Public session responses
and exports redact it. Legacy rows without valid model metadata retain their
display-history fallback.

The shared loop appends changing runtime facts as named snapshots while
keeping standing instructions stable. Replacing one snapshot changes that
section; it must not reinterpret source material as system policy. Tool
availability, workspace paths and resource permissions still come from their
normal authorities.

Retention/compaction must keep a model turn's tool calls and results together.
Interrupted tools get an explicit unavailable-outcome result rather than a
fabricated successful response. Route changes remove incompatible private
provider replay fields while retaining public evidence. Changes must preserve
stored conversation content and account/workspace isolation.

## Cache evidence

Request-cache diagnostics compare canonical request fingerprints and unchanged
prefix messages. They do not prove that a provider served cached tokens.
Actual provider usage counters are the evidence for billed/cache-hit behavior;
route changes, eviction, tool changes and compaction can invalidate reuse.

Start with [model-history regressions](../tests/services/session/test_model_history.py)
and [request-cache tests](../tests/services/llm/test_request_cache.py). The
opt-in [prompt-cache integration test](../tests/integration/test_prompt_cache.py)
uses synthetic inputs with the configured real provider:

```bash
DEEPTUTOR_CACHE_E2E=1 python -m pytest tests/integration/test_prompt_cache.py -q
```

This can incur provider usage. A passing synthetic cache probe is not a
production latency or cost benchmark, and stage-specific pipelines may have
different history contracts from the shared chat loop.
