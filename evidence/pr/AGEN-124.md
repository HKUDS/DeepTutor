# PR: test: unit-cover the quiz-judge WebSocket router (9.4% → 100%)

`deeptutor/api/routers/quiz_judge.py` — the WebSocket router that judges learner quiz answers with an LLM — had only 9.4% line coverage (192 of 212 statements missing): judge-prompt assembly, image MIME handling, multimodal attachment degradation, the three verdict flows, and the disconnect/cleanup contract were essentially untested. This PR adds 52 unit tests that take the module to 100% line coverage without touching any product code.

## Summary

- Adds `tests/api/routers/test_quiz_judge_unit.py` (52 cases) plus the missing `tests/api/routers/__init__.py` package marker.
- No product code is modified; the LLM is mocked at `quiz_judge.llm_stream`, so no real provider call is ever made and the suite runs offline in ~0.6s.
- Module line coverage goes from 9.4% (192 missing) to **100% (212/212 statements, 0 missing)**.

## Root cause

An internal coverage audit (top-15 lowest-covered modules) ranked this router #3. Because the judging loop drives a WebSocket, is async, and depends on an LLM stream, it was never exercised by the HTTP-oriented test suite — leaving prompt assembly (which embeds question, options, reference answer, explanation and user answer into provider prompts) and the cleanup ordering (stop pulling the LLM stream on disconnect, close the socket, reset the per-user context) unverified.

## Changes

- `tests/api/routers/test_quiz_judge_unit.py` (new): 52 tests organized around the router's real seams —
  - **Prompt assembly**: bilingual (zh/en) question + options + reference answer + explanation + user answer, image hints for single/multiple images, option-rendering tolerance, `_guess_image_mime` extension table.
  - **Multimodal content**: base64 → data-URL with MIME, `AttachmentStore` URL resolution, parse-failure/exception fallback to URL passthrough; vision vs. plain-text model branches.
  - **Verdicts**: correct / incorrect / multi-answer (multi_choice with several correct options) streamed through the `started → text… → done` frames via Starlette's `TestClient`; empty chunks are not forwarded.
  - **Disconnect & cleanup**: a mid-stream disconnect stops pulling from the LLM stream (exact consumed-chunk assertion), then closes the socket and calls `reset_current_user` exactly once; close/reset exceptions are swallowed; plus timeout, stream-exception, invalid JSON, missing question, empty answer, auth failure, and early-disconnect branches.
  - **Language fallback**: unknown locale → UI language → `en` fallback.
  - **Image form normalization**: legacy and current image payload shapes.
- `tests/api/routers/__init__.py` (new): empty package marker so `tests/api/routers` is importable as a package.

## Tests

All commands below pass on this branch (rebased onto the current `dev` tip `ef2d9e5c3`, v1.6.12; fresh checkout bootstrapped with the same minimal `data/user/settings/main.yaml` + `model_catalog.json` that CI's `tests.yml` creates):

- `python -m pytest tests/api/routers/test_quiz_judge_unit.py -q` → **52 passed in 0.67s**
- `coverage run --source=deeptutor.api.routers.quiz_judge -m pytest tests/api/routers/test_quiz_judge_unit.py -q && coverage report -m` → **212 stmts, 0 miss, 100%** (baseline on `dev`: 9.4%, 192 missing)
- `python -m pytest tests/api tests/i18n -q` → **829 passed, 5 warnings in 19.25s** (subsystem regression)
- `ruff check tests/api/routers/test_quiz_judge_unit.py tests/api/routers/__init__.py` → All checks passed
- `ruff format --check tests/api/routers/test_quiz_judge_unit.py tests/api/routers/__init__.py` → 2 files already formatted

The LLM mock records every call, so prompt-content assertions inspect the exact strings handed to the provider — they do not depend on fragile log-substring matching.

## Related issue

No upstream issue tracks this coverage gap; this PR comes from an internal coverage audit of the lowest-covered modules. "Related to" only — it adds tests exclusively and fixes nothing by itself.
