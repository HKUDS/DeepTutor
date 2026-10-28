# dt-exp integration verification

Desktop application integration, 2026-10-12.

## Baseline and scope

`dt-exp` starts from latest local `dev`, `3cbecb247`. Its tree was verified byte-for-byte equal to the earlier local-dev snapshot `172a4d49b`; the feature commit was replayed onto the actual dev commit. Work continues in `/Users/frank/HKUDS/DeepTutor`.

The production app uses its existing pages, stores, settings and agent engine. Four sidebar categories group Home, Partners, Learning and Resources. Category switches preserve the working page. Learning creation opens the original feature flows. The former `/preview` remains a separate prototype reference with isolated fixtures; production routes do not use its transport.

## Data compatibility

- No storage-schema migration, record-ID rewrite, directory relocation, or destructive data conversion was introduced by the navigation change.
- Learning navigation reads each existing workspace and preserves its origin on every link. Duplicate book/question IDs in separate workspaces remain separate records.
- Practice navigation reads compact question metadata through the existing recycle predicate; answers, attempt state and attachments remain in their original store.
- Partner and group navigation uses existing visibility and actor-scoped session stores. Archived transcripts remain available in original history pages.
- Session selection uses the existing continuity API; explicit manual changes update the URL so refresh resumes the selected session.
- Learning-account restrictions remain enforced. The additive aggregate GET filters each allowed source before reading it; other dashboard operations stay gated.
- Original settings, history organization, rename/pin/archive operations, workspaces, reading state and feature detail views remain available.

## Runtime separation

Preview: `http://127.0.0.1:4180/chat`; API: `http://127.0.0.1:8016`.
All browser verification used `DEEPTUTOR_HOME=/tmp/deeptutor-dt-exp-runtime`, separate from normal user data. Test records are named with 验证. No credentials or user library were copied into this runtime. It has no configured LLM, so live generation/provider behavior was not exercised.

## Browser verification

Verified against a production build, with desktop layouts at 1280 and 1440 CSS pixels:

- Four-category switching preserves open work; real category lists load from the API.
- Original Settings sections remain complete; switching the isolated UI language to Chinese and applying changes succeeds.
- Resources retains history, notebooks, journal, questions, knowledge bases, personas, skills, MCP, CLI apps and memory.
- A reading collection created in the UI persists and can be reopened from Learning after reload.
- Existing practice record opens the original exercise UI; submitting its correct answer shows the original grading result.
- Books and Mastery creation open the original configuration/source-selection workflows.
- Partner navigation opens an existing JSONL transcript with its original body. Configure remains complete.
- Group session deep links select the exact stored discussion and load its history.
- Task Board creates a real card and persists its move into Doing.
- Co-Writer creates a real draft, edits Markdown, updates the preview, and reports saved state.
- Dito defaults to Auto while retaining the original manual capability menu.

Evidence: `dt-exp-practice.png`, `dt-exp-partners.png`, `dt-exp-writer.png` and `dt-exp-home.png` in this directory. Older JPGs document the earlier frontend prototype, not the integrated application's data.

## Automated verification

- Full WebUI Vitest baseline: 149 files, 663 tests passed; new session/navigation regression tests were additionally run after integration fixes.
- Node suite: 1,303 tests passed.
- Backend workspace + multi-user suites: 474 tests passed; after adding the HTTP policy regression, the focused compatibility/policy suite passed all 7 tests.
- Type checking, API contract regeneration/check, dependency architecture, i18n checks and Ruff passed.
- Full ESLint has no errors; existing and prototype translation warnings remain.
- Production build succeeds; all existing route JS budgets pass after deferring unused sidebar panels/history code. Budgets were not raised.

## Known limits

Model-backed generation, external channels and integrations require their normal configuration and were not live-tested in the isolated runtime. This iteration uses the existing chat/tool loop for Auto; it does not claim to add a new cross-capability autonomous planning engine. Mobile refinement was explicitly deferred by the user.


## Sidebar refinement, 2026-10-12

- Partner preview is capped at three avatars in one row; group preview is capped at two rows. Each section retains its total, full-list link and creation action. Conversations scroll independently beneath fixed headings, with title and owner on separate lines.
- Verified against isolated API data with 8 partners, 6 groups and 36 conversations, including a 1280 × 600 desktop viewport. End/Home and Show more keep the sidebar at y=0; all 36 histories remain reachable. Searching Paul finds a partner outside the initial preview. Full-list anchors land on the respective partner/group sections.
- Learning begins with one All learning row containing the original creation menu. Records show local-calendar groups and right-aligned relative timestamps. Last-active and creation-time ordering use the original data timestamps; search covers titles, workspace names and learning types. The sorting preference persists locally.
- Verified creation-time ordering, search, Escape to clear, switching categories without losing ordering, and the original four learning creation options. Six isolated reading records exercise distinct creation/activity dates and all date groups.
- Next dynamic components without a loading option can suspend to the outer workspace layout. Local Suspense boundaries now contain sidebar and feature loading; category switches use a transition and retain visited panels. Removed the repeated whole-category fade and chat greeting fade. Saved sidebar width restores before paint.
- Recent navigation snapshots remain visible during background refresh and are cleared on authentication changes. A regression verifies that an in-flight response cannot restore the previous account cache after invalidation.
- Validation: 152 Vitest files / 671 tests and 1,303 Node tests pass. Production build, type checking, i18n, dependency architecture and all existing route budgets pass. Targeted ESLint has no errors (existing logo-alt warnings remain).
- Evidence: dt-exp-learning-navigation.png and dt-exp-partner-navigation.png. Test records remain isolated under /tmp/deeptutor-dt-exp-runtime; no production data schema or records were changed.

## Navigation identity and shared page chrome, 2026-10-13

- Added Projects above workspace folders, matching Recent's visual hierarchy. Folder ordering, collapse, move/rename actions and five-row conversation limits remain intact.
- Replaced the expanding, icon-only category pills with four stable, labelled destinations. Active state uses the selected DeepTutor theme color, a quiet tint and an animated position marker. Keyboard navigation, search, collapsed rail and retained category state are unchanged.
- Added shared PageToolbar chrome: 52px minimum height, 20px desktop gutters, compact identity/breadcrumbs on the left and contextual actions on the right. FeaturePage/Settings page headers render their actual actions into a stable slot outside the scrollport, retaining React context and handlers. Secondary section headings stay with their content.
- Applied the toolbar to chat, reading, mastery, writing, partner/group conversations, books, notebooks, knowledge-base details and Whisper. Partner local views now use a separate row. Settings, libraries, task board and other FeaturePage consumers inherit the same frame. Reader/editor pane controls stay local.
- Browser QA: 1280 × 720 desktop and 1280 × 600 with a 220px sidebar. All four category labels fit; partner, group and session sections remain visible. Learning creation opens its original modal; notebook creation opens its original form; existing partner transcript and saved writing document display correctly; Settings retains its sections. Resource-page toolbar stays at y=0 / height=52 while content scrolls. A fresh tab against the final production build has no console errors.
- Validation: 153 Vitest files / 672 tests; 1,303 Node tests; production build/type checking, i18n checks, dependency architecture and existing route budgets pass. Targeted ESLint reports no errors; five pre-existing warnings remain. Regression coverage checks that moved page actions keep their providers/state and unmount cleanly during page changes.
- Evidence: dt-exp-page-chrome-home.png, dt-exp-page-chrome-learning.png, dt-exp-page-chrome-writer.png. Three empty projects were added only to the isolated /tmp runtime to exercise the section heading. No storage format, backend contract or real user records changed.

## Restore the lighter visual baseline, 2026-10-13

- Supersedes the shared page chrome and colored category treatment above, following visual feedback. Restored the pre-chrome page titles, whitespace, native workspace toolbars and single-row neutral category navigation from `2358b8d40`. Removed the extra fixed header/portal layer, added dividers and separate partner tab row.
- Kept the Projects heading and translations. The only other visual differences from that baseline are 10px category corners and 19px icons. Partner/group limits, retained navigation, learning search and timestamp ordering remain unchanged.
- Browser verification on the production preview: learning records and original four-option creation dialog render correctly; Home shows Projects and Recent; partner/group/session sections remain visible together, and the existing partner transcript opens with its original toolbar. No console errors were captured in the fresh preview tab.
- Validation: 152 Vitest files / 671 tests and 1,303 Node tests pass. Production build including TypeScript and all existing route budgets pass. Targeted ESLint reports no errors, with six existing warnings. No backend or data changes.
- Current evidence: `dt-exp-light-learning.png` and `dt-exp-light-home.png`. The earlier page-chrome images document the superseded design.
