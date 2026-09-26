# Workspace isolation implementation audit

Verified on 2026-09-19. The local production instance was rebuilt and restarted
at http://localhost:3784 (API :8000). No remote deployment was performed.

## Implemented contract

- Ordinary chat, Books, Mastery Path, Reading, Watching: materials, sessions,
  progress, quiz results, generated files and caches belong to a workspace.
- Unselected/default workspace retains historical paths and data. Previous
  folder bindings are preserved for audit and adopted into default once.
- Custom data lives under `.deeptutor/data/` inside its registered folder;
  presented outputs remain under `outputs/`.
- Memory, credentials, account settings and workspace registry remain global.
- Authenticated ownership and workspace scope are checked independently.
  HTTP selectors must agree; WebSockets capture scope at connection time.
- SDK and CLI can explicitly select a registered workspace. Background writers
  retain their original scope. Account changes discard inherited workspace scope.
- Task-scoped URLs and full navigation between content stores clear caches. Text and attachment drafts are keyed by account, workspace and
  page, and stored before switching.
- Shared admin books/knowledge bases retain their grant policy. Personal learning
  state is workspace-specific. Moving a granted admin catalogue is blocked until
  grants are resolved; exports remain possible.
- Settings → Personal → Data Migration discovers supported stores and historical
  roots, previews dependency closure, exports ZIPs, migrates verified snapshots,
  retains recovery journals and recovers interrupted transfers.
- SQLite backup includes WAL content. Numeric IDs are preserved. Nonempty target
  features and conflicting IDs block migration; initialized empty databases do
  not. Explicit output exports include orphaned files.
- Referenced courses, historical request snapshots, quiz followups, attachments
  and published blobs participate in migration. PocketBase conversations and
  the accompanying local SQLite quiz store move together.
- Cross-process activity leases exclude migrations from app writes and archive
  changes. Startup migrations skip pending recovery. Recovery settings remain
  accessible when an active workspace is unavailable.

## Task assignment and navigation correction

- The sidebar no longer selects a global data scope. Chat assigns a workspace
  in its composer; all four learning introductions offer selection and creation.
- Task URLs own scope. A previous tab selection cannot silently scope a new
  homepage, settings page or task. Cross-store navigation disposes UI runtimes;
  within-feature routes retain explicit scope, including first-turn bindings.
- Session and learning navigation explicitly aggregate this account's stores,
  tag each result with its origin, and preserve that origin for opens/mutations.
  Content APIs and history-as-context pickers remain strictly workspace-local.
- Suggestion material collection runs off the event loop. Background and manual
  refresh share one job per store, with a 35-second total deadline; the client
  has cancellation, a 40-second deadline and distinct empty/error states.
- Starter generation requests no hidden reasoning for its short output budget.
  The live model previously exhausted all 500 completion tokens on reasoning
  (`finish_reason=length`, zero answer characters); with this call-specific
  setting it returned three valid suggestions (`finish_reason=stop`).

## Verification evidence

- Task-navigation correction: 55 backend tests, 52 rendered frontend tests,
  and 29 route tests passed. Typecheck, dependency boundaries, contract generation,
  locale parity and the production build passed.
- Browser regression on an isolated runtime verified cross-workspace history,
  opening a default transcript from a custom learning page, learning start
  selection, in-composer creation and unsent draft transfer. Empty workspaces
  render a terminal no-history message; model failures have a retry control.

- Latest boundary regression: 94 passed (workspace, application, WebSocket
  binding and shared-book suites).
- CLI/application checks: 45 passed. PocketBase/usage checks: 12 passed;
  final PocketBase migration rerun: 4 passed. Migration/HTTP checks: 17 passed.
- Earlier larger runtime/partner regression: 159 passed; broader workspace and
  runtime regression: 132 passed. Counts overlap and are not additive.
- TypeScript typecheck, ESLint, generated contract check and production builds
  passed. Locale parity passed; the repository-wide i18n audit still reports
  existing missing keys/UI literal notices.
- Frontend workspace suite: 18 passed.
- Real browser QA in an isolated data home: A/B learning dashboards and chat
  lists, full four-feature migration with two conversations, ZIP download and
  archive integrity (14 entries), text and attachment draft restoration.
- Actual WebSocket against the QA backend rejects continuation of a conversation
  owned by a different workspace with `start_turn_rejected`.
- Crash tests cover partial copy, session commit and recovery. These exercise
  failure paths without interrupting user data.
- Production smoke check: 1,037 default conversations and 5 books retained;
  no pending recovery; Chinese migration page works. A real default-book preview
  found 172 dependent conversations and correctly refused the already populated
  destination without changing data. Ports 3024/8024 and QA
  build directories were cleaned up.
- Private full-data backup verified with SHA-256 and tar listing:
  `/Users/frank/HKUDS/DeepTutor-backups/workspace-isolation-20260919-023534/`.

Browser artifacts are under `output/playwright/`: `workspace-migration-production.png`,
`workspace-attachment-restored.png`, and `workspace-draft-restored.png`.

## Deliberate limits

- Feature migration is an aggregate transfer, not a merge of independently
  populated feature databases. Conflicting numeric IDs are refused, not remapped.
- Unsupported historical formats are preserved as archives, not automatically
  interpreted as current learning records. Discovery is confined to registered
  account/workspace roots; it does not search arbitrary disks.
- PocketBase behavior is covered by repository test doubles, including mixed
  local quiz storage. No live external PocketBase service was available for QA.
- Recovery copies consume disk space and are retained. External programs that
  bypass the app's leases must be stopped while migrating.
- Switching drafts are local browser data; they are not cross-device draft sync.
- Workspace partitioning is application-level data organization. Shared admin
  resources, memory and account-level usage/settings keep their stated scope.
- The preexisting ownerless turn dated 2026-08-30 was settled through the
  application cancel command (`worker_lost`). Messages and all 1,037 sessions
  remain; there are now no nonterminal turns blocking default-store migration.
