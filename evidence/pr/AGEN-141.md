# PR: fix(rag): log image progress callback failures instead of swallowing them

## Summary

- `LlamaIndexDocumentLoader._describe_one` invoked the optional `image_progress_callback` inside a `finally` block wrapped in `except Exception: pass`. A progress sink that raises (e.g. a broken UI progress handler during knowledge-base initialization) therefore vanished silently: no log line, no trace, and indexing progress tracking looked stuck for no diagnosable reason.
- This PR replaces the bare `pass` with a `logger.warning` that includes the `completed`/`total` counters and the exception summary. The exception is still NOT re-raised: concurrent image description and the surrounding batch load continue exactly as before, and return values / exception semantics are 100% preserved.
- No image payload data is logged — only the progress numbers and the exception text.

## Root cause

During parallel image description, `_describe_one` reports per-image progress via `image_progress_callback(completed, total)` (wired through `pipeline.py` from `deeptutor/knowledge/initializer.py`'s `_on_image_progress`). The call site caught `Exception` and discarded it, so a failing progress sink was indistinguishable from "no progress happening". Silent-swallow audit of the RAG pipelines flagged this as the only remaining `except Exception: pass` on a progress hook.

## Changes

- `deeptutor/services/rag/pipelines/llamaindex/document_loader.py` (+7): capture the exception and log one warning per failed callback invocation, e.g. `Image progress callback failed (completed=1, total=4): <exc>`. Control flow, return values, and concurrency behavior unchanged.
- `tests/services/rag/test_llamaindex_document_loader.py` (+61): new `test_loader_logs_and_continues_when_image_progress_callback_fails` — loads a two-image batch with a callback that raises on `completed=1`; asserts the callback is still invoked for every image (`[(1, 2), (2, 2)]`), both `ImageNode`s are still produced, and the warning (including the callback's error text) is captured via `caplog`. Uses stub embedding/vision clients — no network access.

## Tests

All commands run on a branch based on the current `dev` tip (`ef2d9e5c3`, v1.6.12):

- `python -m pytest tests/services/rag/test_llamaindex_document_loader.py -v` → **16 passed** (15 pre-existing + 1 new)
- `python -m pytest tests/services/rag/test_llamaindex*` → **75 passed** (all LlamaIndex pipeline/loader tests)
- `python -m pytest tests/services/rag` → **623 passed, 31 skipped, 12 failed** — the 12 failures are pre-existing environment failures on unmodified `dev` (missing local `data/user/settings/main.yaml` in the test workspace; `test_embedding_binding` ×6, `test_graphrag_pipeline` ×3, `test_lightrag_roles` ×3) and fail identically on the base commit without this change.
- Red-green check: with the product-code change reverted (plain `dev` state), the new test fails exactly at the warning assertion (`AssertionError: assert 'Image progress callback failed' in ''`), confirming it pins the fix.
- `ruff check` + `ruff format --check` on both files → All checks passed / already formatted
- `pre-commit run --files <both files>` → all hooks Passed
- `python scripts/check_architecture.py` → Architecture boundaries: OK; `python scripts/check_workspace_hygiene.py` → passed

## Related issue

Related to none — found during an internal error-handling audit of silent `except: pass` sites in the RAG pipelines; no upstream issue tracks this behavior.
