# StandaloneComposer smoke coverage — 2026-10-03

Closes the 0% statement-coverage gap on `web/components/chat/home/StandaloneComposer.tsx`
(395/395 statements missed, Top-3 entry in `evidence/coverage-2026-10-02/frontend/summary.md`
on branch `audit/coverage-gaps-20261003`).

## What was added

- `web/tests/chat/StandaloneComposer.smoke.spec.tsx` — 4 vitest tests driving the
  composer's own state pool through the `onSend` prop it hands to `ChatComposer`
  (shell stubbed, pickers and network modules mocked):

| # | Behavior pinned | Guard under test |
|---|---|---|
| 1 | Empty / whitespace-only input never submits | `!content.trim() && !hasReferences` early return |
| 2 | Text submits once with the full payload; a follow-up empty send stays refused | submission shape + one-shot state consumption |
| 3 | Send locked while `isStreaming` | `isStreaming && !awaitingUserReply` early return |
| 4 | ask_user answer passes the lock | `awaitingUserReply` exception |

## Numbers

| Run | Command (from `web/`) | Result |
|---|---|---|
| New file | `npx vitest run tests/chat/StandaloneComposer.smoke.spec.tsx` | 1 file / **4 passed** (0.6s) |
| Full unit suite | `npx vitest run` | 114 files / **475 passed** (18.9s), 0 failed |

Other checks: `eslint tests/chat/StandaloneComposer.smoke.spec.tsx` clean;
`npm run typecheck` clean. No product code changed — the diff adds the test file
and this evidence only.

## Deviation from the card

The card named `StandaloneComposer.smoke.test.tsx`; the web vitest config only
collects `tests/**/*.spec.ts(x)`, so a `.test.tsx` file would never run
(verified: `vitest run` reports "No test files found"). The file is therefore
`StandaloneComposer.smoke.spec.tsx`, matching repo convention.

## Files

- `vitest-smoke-run.txt` — targeted run output
- `vitest-full-run.txt` — full suite output
