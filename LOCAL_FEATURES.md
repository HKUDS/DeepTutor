# Fork-local feature contract

This file is owned by this fork. Do not include it in upstream PRs unless the
upstream maintainers explicitly ask for it. Before merging upstream, every
`active` item below must still have its routes, data contract, and regression
tests intact.

## Status ledger

- `active`
  - Learning Accounts on the shared `deeptutor.reading` / `ReaderPane` stack,
    with server-enforced surfaces, assigned materials, upload policy, locked
    persona, and per-account Reading extension allowlists.
  - Schema-driven `deeptutor.reading_extensions`, neutral idempotent learning
    records, and the `deeptutor migrate kids-to-learning` copy migration with
    one-time activation codes. Extensions never inject frontend JavaScript.
  - Kids standalone experience and its child-facing API under `/api/v1/kids`.
  - Parent management API under `/api/v1/kids-admin`.
  - `AUTH_ALLOW_REGISTRATION` and the persisted `auth.allow_registration` setting.
  - Partner Feishu/Lark and WeCom QR-code channel onboarding with short-lived
    credentials, administrator-only routes, masked responses, and explicit apply.
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
- `retiring-after-migration-observation`
  - Standalone Kids profiles, device tokens, parent PIN entry, duplicated EPUB
    viewer, and Kids progress stores. They remain available during this release
    candidate so rollback is possible; after migration acceptance `/kids`
    becomes read-only for one release, then these paths are removed.
- `forbidden-regression`
  - Removing or weakening Kids child session authentication.
  - Removing parent PIN verification or its rate limiting.
  - Exposing child library, EPUB, progress, quiz, asset, or interactive-book
    routes outside their profile/session contract.
  - Deleting Kids regression tests or reducing guided-learning coverage.
  - Moving Kids reward rules, reward persistence, or reward copy back into the
    core Kids product.
  - Routing MarginNote libraries through generic RAG instead of their own tools.

## Kids capability promise

The active Kids feature set is a coherent product, not a demo:

- Standalone child entry (`/kids`, `/kids/p/{profileId}`) with device tokens and
  parent unlock/exit verification.
- Parent profile management, book assignment, interactive-book assignment, and
  learning reports.
- Per-profile library isolation, reading progress, quiz scores, and
  interactive-book progress.
- The fork-local `deeptutor.kids_reward_providers` extension point. Core emits
  only neutral learning events; an optional provider owns its reward ledger,
  idempotency, copy, snapshot, and persistence. No default reward package ships
  with the core application. A provider failure must never block reading or
  quiz submission.
- A fork-local switch-time Kids dual-track sync tool. It merges learning facts
  between the legacy checkout and this extension build while preserving and
  restoring legacy star fields. It is not a live shared database; both UIs must
  be stopped while it runs.
- Authorized EPUB delivery and navigation mapped to backend reading sections.
- Visible-page text extraction for narration and guided questions.
- Source-grounded current-page concept learning with progressive reflection
  support for Chinese readers.
- Progressive word hints, word exploration, bilingual pronunciation, and shared
  speech playback state.
- Age-band story comprehension quizzes with deterministic fallback, age-aware
  cache invalidation, and exactly three presented questions.
- Interactive book pages, markdown/callout/media/code blocks, safe asset
  delivery, interactive widgets, and page quizzes.

## Kids Reading roadmap

The fork-local direction is to productize the child-facing experience as
**Kids Reading** while retaining DeepTutor's ordinary-account architecture.
The internal protocol and grant field remain `reading_extensions`; the product
name does not introduce a second child identity system.

### Architectural alignment: #992-#995 Learner Account

An audit of upstream `main` and `dev` confirms that issues #992-#995
("Learner Account") do not invent a new identity or parallel storage system,
but rather formalize DeepTutor's existing multi-user and runtime foundations:

```text
Old Kids Subsystem Approach:
  DeepTutor -> KidsProfile -> Kids Library / Kids Progress / Kids Session

Converged Learner Architecture (#992-#995):
  User (role="user") -> Learner Configuration (LearnerProfile, LearningPolicy, Guardian Auth)
                     -> Existing Shared Runtime (Workspace, Grants v2, ReadingStore, LearningStore, Audit)
```

#### Upstream infrastructure status vs #992-#995 requirements

| Component / Requirement | Upstream `main`/`dev` Status | Implementation & Local Contract |
| ----------------------- | ---------------------------- | ------------------------------- |
| Identity model (`admin/user` only) | Complete | `Role = Literal["admin", "user"]`; no special child role |
| Independent user workspaces | Complete | Filesystem isolation under `data/users/<user_id>/` |
| Tool grant allowlists | Complete | Grants v2 `enabled_tools` filter |
| MCP / CLI / exec restrictions | Complete | Deny-by-default for non-admin (`mcp_tools`, `cli_apps`, `exec_enabled`) |
| Resource & material assignment | Complete | Admin API grants for models, KBs, skills; assigned KBs are read-only (403) |
| Server-side turn enforcement | Complete | `tool_access.py` and `turn_runtime` filter every turn payload |
| Usage & administration audit | Complete | `audit/usage.jsonl` logs actor, target, action, timestamp |
| Isolated Reading Store | Complete | Workspace-scoped `ReadingStore` (`deeptutor/reading/store.py`) |
| Reading Agent safety context | Complete | Server binds `reading_material_id` / viewport; deterministic locator pre-pass |
| Grounding on turn regenerate | Complete | Turn snapshot stores `readingMaterialId` to prevent silent ungrounding |
| Learning & Mastery persistence | Complete | Workspace-scoped SQLite database (`<workspace>/learning/mastery.sqlite3`) |
| `learner preset` | Pending | Preset expansion into grant / policy rules |
| `learning_policy` schema | Pending | Server-enforced account policy structure |
| Guardian -> Learner delegation | Pending | Parent-child authorization abstraction over existing grant APIs |
| Age / grade `LearnerProfile` | Pending | Metadata for age-banded prompt adaptation |
| Capability whitelist | Incomplete | Account-level capability allowlisting |
| Reading Extensions policy | Blocked on #970 | Upstream PR #970 (Safe Reading Extension Protocol) is open/unmerged |

### Delivery phases

1. **Now: keep Kids Reading inside DeepTutor.** Learners remain ordinary
   `role="user"` accounts with a server-enforced learning policy, assigned
   materials, and per-account Reading extension allowlists. The public child
   surface is named Kids Reading, but storage, identity, authorization, and
   progress continue to use the shared DeepTutor contracts.
2. **Short term: isolate Kids Reading Essentials.** Keep the schema-only
   read-aloud, guided-learning, vocabulary, translation, and quiz actions in
   `packages/deeptutor-reading-essentials`, and keep that package independent
   of legacy `/kids` profile routes, Kids admin routes, local migration code,
   reward providers, and private deployment configuration.
3. **After Reading extension protocol stabilization:** publish the essentials
   package separately, likely as `deeptutor-reading-essentials` or
   `kids-reading-essentials`. This split is appropriate only once protocol
   versioning, entry-point compatibility, security boundaries, tests, release
   automation, and a compatibility matrix are documented. Track upstream
   reading-extension protocol PR #970 before finalizing the public contract.
4. **Upstream #992-#995 landing & legacy retirement:** As upstream #992-#995
   merges into `main`/`dev`, replace fork-local `kids-to-learning` migration
   shims, standalone profile/PIN tables, and `/api/v1/kids` routes with official
   `LearnerProfile`, `LearningPolicy`, and `Guardian` delegation APIs.
5. **Later: consider a full Kids Reading application repository only if it
   becomes a standalone product.** A separate app must not fork the account,
   bookshelf, progress, guardian authorization, or reading-security model until
   there is an explicit product decision to operate and support it as a
   separate child-facing deployment.

Do not move the fork-local legacy Kids routes, Kids-to-Learning migration,
parent PIN/device flows, dual-track sync details, local reward providers, or
child data/deployment assumptions into the public essentials package.
## Regression gates

Follow `DEVELOPMENT_WORKFLOW.md` for branching, isolated worktrees, ports,
verification, and local product deployment before merging or releasing.

Run these before releasing or merging upstream changes into this fork:

```bash
.venv/bin/python -m pytest \
  tests/test_local_feature_contract.py \
  tests/multi_user/test_learning_policy.py \
  tests/multi_user/test_kids_to_learning_migration.py \
  tests/reading/test_extensions.py \
  tests/immersive_reading/test_kids_reading_endpoints.py \
  tests/immersive_reading/test_kids_interactive_books.py \
  tests/immersive_reading/test_kids_quiz_cache.py \
  tests/immersive_reading/test_kids_learn.py \
  tests/immersive_reading/test_kids_learn_endpoints.py \
  tests/immersive_reading/test_kids_rewards.py \
  tests/scripts/test_kids_dual_track_sync.py \
  tests/cli/test_plugin_cli.py \
  tests/api/test_partners_router.py \
  tests/services/partners/test_channel_onboarding.py \
  tests/services/partners/test_feishu_domain_initialization.py \
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
