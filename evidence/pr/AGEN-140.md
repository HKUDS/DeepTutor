# PR: fix(embedding): log progress callback failures instead of swallowing them

## Summary

- `EmbeddingClient.embed` and `embed_contents` wrap the per-batch `progress_callback` in `except Exception: pass`. When the progress sink (UI / task-log indexing progress) raises, the error vanishes: indexing keeps running but progress reads as stalled, with zero log trace — making KB index progress untrustworthy.
- This PR keeps the callback best-effort (an embedding run must never fail on UI feedback) but logs a `warning` with the batch context (`batch i/total`) and the underlying exception (`exc_info=True`), so a broken progress sink becomes visible and diagnosable instead of silent.
- Adds two focused async tests (one per method) using a mocked adapter: a raising callback still yields the full embedding result, and the failure is asserted in `caplog`.

## Root cause

Both batch loops call `progress_callback(i + 1, total_batches)` inside `try/except Exception: pass` (introduced with the progress callback in #268). The swallow was intended to protect the embedding run from UI-layer failures, but it also erased all evidence of them: the indexing pipeline continues while the progress chain is broken, and nothing in the logs explains why progress stopped advancing.

## Changes

- `deeptutor/services/embedding/client.py` (+17 net in the two hunks):
  - `embed` (:204 area): `except Exception: pass` → `except Exception as exc` + `self.logger.warning(f"Embedding progress callback failed (batch {i + 1}/{total_batches}): {exc}", exc_info=True)`.
  - `embed_contents` (:279 area): same replacement, same message shape, so a broken progress sink cannot stall multimodal indexing invisibly.
  - No behavioral change otherwise: the callback stays best-effort, batch delay / rate-limit handling / return values untouched.
- `tests/services/embedding/test_client_runtime.py` (+65):
  - `test_embed_progress_callback_failure_logged_and_not_fatal`: `_resolve_adapter_class` monkeypatched to a fake adapter; callback raises `RuntimeError("progress sink offline")`; asserts 3 vectors returned and a warning containing `progress callback` + `progress sink offline` on the `deeptutor.services.embedding.client` logger.
  - `test_embed_contents_progress_callback_failure_logged_and_not_fatal`: multimodal fake adapter variant; same assertions for the `embed_contents` loop.

## Tests

All commands run on a branch based on the current `dev` tip (`ef2d9e5c3`, v1.6.12); mocked adapters only, no real service calls:

- `python -m pytest tests/services/embedding/test_client_runtime.py -k "progress_callback" -v` → **2 passed, 18 deselected**
- `python -m pytest tests/services/embedding/ -q` → **141 passed**
- `python -m pytest tests/services/rag/test_llamaindex_embedding_failures.py tests/services/rag/test_llamaindex_embedding_roles.py tests/knowledge/test_manager_embedding_flags.py tests/services/config/test_embedding_runtime.py -q` → **45 passed** (downstream consumers unaffected)
- Red-green check (from the original development run): with the product-code change reverted, both new tests fail (embedding succeeds but no warning is logged), confirming they pin the fix.
- `ruff check deeptutor/services/embedding/client.py tests/services/embedding/test_client_runtime.py` → All checks passed

## Related issue

Related to #1612 (truthful/resumable indexing progress — this PR removes one source of silent progress-chain breakage, it does not implement resumability).
