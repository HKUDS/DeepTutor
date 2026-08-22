# Fork-local feature contract

This file is owned by this fork. Do not include it in upstream PRs unless the
upstream maintainers explicitly ask for it. Before merging upstream, every
`active` item below must still have its routes, data contract, and regression
tests intact.

## Status ledger

- `active`
  - Kids standalone experience and its child-facing API under `/api/v1/kids`.
  - Parent management API under `/api/v1/kids-admin`.
  - `AUTH_ALLOW_REGISTRATION` and the persisted `auth.allow_registration` setting.
- `upstream-v1.5.16`
  - MarginNote 4 connected knowledge base type.
  - Device pairing, one-time device tokens, incremental sync, heartbeat, and revoke.
  - Seven read-only MN4 tools for search, object reading, type listing, document
    children, links, tags, and mindmap cards.
  - Exclusion of MarginNote libraries from generic `rag_search` sweeps.
- `parked`
  - Local MN4 write-back experiments and review UI work.
  - Chrome/MarginNote realtime probe and sync-coordinator work.
  - Historical preservation worktrees not merged into this integration branch.
- `forbidden-regression`
  - Removing or weakening Kids child session authentication.
  - Removing parent PIN verification or its rate limiting.
  - Exposing child library, EPUB, progress, quiz, asset, or interactive-book
    routes outside their profile/session contract.
  - Deleting Kids regression tests or reducing guided-learning coverage.
  - Routing MarginNote libraries through generic RAG instead of their own tools.

## Kids capability promise

The active Kids feature set is a coherent product, not a demo:

- Standalone child entry (`/kids`, `/kids/p/{profileId}`) with device tokens and
  parent unlock/exit verification.
- Parent profile management, book assignment, interactive-book assignment, and
  learning reports.
- Per-profile library isolation, reading progress, quiz scores, star awards, and
  interactive-book progress.
- Authorized EPUB delivery and navigation mapped to backend reading sections.
- Visible-page text extraction for narration and guided questions.
- Progressive word hints, word exploration, bilingual pronunciation, and shared
  speech playback state.
- Age-band story comprehension quizzes with deterministic fallback, age-aware
  cache invalidation, and exactly three presented questions.
- Interactive book pages, markdown/callout/media/code blocks, safe asset
  delivery, interactive widgets, and page quizzes.

## Regression gates

Run these before releasing or merging upstream changes into this fork:

```bash
.venv/bin/python -m pytest \
  tests/test_local_feature_contract.py \
  tests/immersive_reading/test_kids_reading_endpoints.py \
  tests/immersive_reading/test_kids_interactive_books.py \
  tests/immersive_reading/test_kids_quiz_cache.py \
  tests/api/test_marginnote4_router.py \
  tests/capabilities/marginnote4 \
  tests/knowledge/test_marginnote4_kb.py
cd web && npm run test:node
```

For a release candidate, also run `cd web && npm run build`, the Kids Playwright
golden path, and the upstream v1.5.16 gateway test set.

## Upstream contribution workflow

1. Keep the working tree clean before an upstream merge. Commit valuable WIP or
   create a preservation branch first.
2. Add fork-local value to this ledger and bind it to at least one regression
   test before it depends on that value.
3. Split upstream-ready work into independently reviewable units. Open an issue
   for the problem and contract first, then submit backend, frontend, and
   tests/docs PRs separately.
4. Do not send this ledger, private Kids product flows, or unauthorized local
   configuration in upstream PRs.
5. Continue MN4 write-back as a separate Phase 2 chain; do not mix it with a
   release upgrade or read-only bridge fixes.

## MarginNote 4 v1.5.16 usage

The upstream release includes the server bridge and web management UI, not the
MarginNote 4 add-on artifact. To use it:

1. Create a MarginNote 4 knowledge base.
2. Open the library's Devices tab and pair a device.
3. Copy the one-time token immediately.
4. Enter the token in the MarginNote 4 add-on on the paired device.
5. Let the add-on call heartbeat and sync; notes, excerpts, cards, and mindmap
   nodes arrive incrementally into DeepTutor's store.

A real-device check is blocked until an MN4 add-on artifact is available; server
pairing and simulated device sync are covered by tests.
