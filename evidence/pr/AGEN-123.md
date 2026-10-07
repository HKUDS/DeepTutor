# PR: test(web): smoke ChatWorkspace empty home, streaming turn, failure banner

`web/features/chat/components/ChatWorkspace.tsx` — the >3000-line main chat workspace — had no component-level tests (0% coverage: 0/1074 statements, 0/947 lines; gap #2 of the coverage audit's Top 15). This PR adds `web/tests/chat/ChatWorkspace.smoke.spec.tsx` with 4 Vitest component smoke tests covering the empty-session home, the send path, the full streaming turn lifecycle, and failure banners. No product code is changed.

## Summary

- Add `web/tests/chat/ChatWorkspace.smoke.spec.tsx` (+462 lines): 4 component smoke tests for `ChatWorkspace.tsx`:
  1. **Empty-session home**: greeting hero + starter suggestions + idle composer render; mount boots `newSession({ workspaceId: null })`; export/save controls start disabled; `setActiveSessionId` is reported to the shell.
  2. **Send path**: submitting from the composer assembles the expected `sendMessage("Explain photosynthesis", [], { _course_id: "", ... }, ...)` call.
  3. **Streaming turn lifecycle** (mock `ChatStateAdapter` injecting events): `sent` → `streaming` (message list and composer both flag streaming; incremental content lands on the assistant row's events) → `done` (flags reset, no error banner).
  4. **Failure banners**: `submissionFailed` → `role="alert"` banner ("Couldn't reach the server...") with a Resend action that calls `resendLastMessage`; the `submissionNeedsReview` variant renders different copy and no Resend; a URL session load failure ends in a retryable terminal state where Retry re-calls `loadSession`.

## Root cause

No product defect. A coverage audit identified `ChatWorkspace.tsx` as the Top-15 gap #2 with 0% coverage (1074 missing statements): the chat core's empty-state rendering, `newSession` bootstrapping, send parameter assembly, and the sent→streaming→done turn lifecycle had no regression protection, so a refactor that broke any of these contracts would pass the existing suite unnoticed. This PR closes that gap with isolated component smoke tests only (assertions target semantic roles, names, testids, and spy calls — no brittle class matching).

## Changes

- New file `web/tests/chat/ChatWorkspace.smoke.spec.tsx` (+462 lines).
- Zero product-code changes (`web/features/`, `web/app/`, and all other product paths untouched).
- Full isolation: `ChatStateAdapter` is mocked at the component boundary; heavy children (composer, message list, dynamic pickers) are capture-style stubs — no network access, no backend, no LLM calls.

## Tests

All commands run on a branch based on the current `dev` tip (`ef2d9e5c3`, v1.6.12):

- `npm --prefix web run test:unit -- tests/chat/ChatWorkspace.smoke.spec.tsx` → **4/4 passed** (1 file)
- `npm --prefix web run test:unit` → **475/475 passed** (114 files; baseline 113 files / 471 tests + 1 file / 4 tests)
- `npm --prefix web run typecheck` → clean, 0 errors
- `npm --prefix web run lint` → 0 errors (the new test file has 0 warnings)
- `npm --prefix web run architecture:check` → no dependency violations (888 modules)
- `npm --prefix web run test:node` → **1234/1234 passed**
- `npm --prefix web run i18n:check` → parity + audit OK
- `ChatWorkspace.tsx` coverage: **0% → 47.39% statements (509/1074), 50.26% lines (476/947)** (v8 coverage measured in the originating audit run)

## Related issue

Related to the ChatWorkspace component coverage gap identified in an internal coverage audit. No upstream issue exists yet; this PR is standalone test hardening with no behavior change.
