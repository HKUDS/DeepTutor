# Dito frontend preview QA — four-category desktop iteration

Result: verified for the local frontend prototype scope.

Preview: http://127.0.0.1:4173/preview#learning

Branch: `codex/dito-frontend-prototype`

## Scope and references

The user requested desktop browser work first. This iteration reorganizes the
existing WebUI around Home, Partners, Learning and Resources. Backend execution
and mobile refinement are outside this iteration.

References are the user's three Notion sidebar captures (b205598c, 4a06d37e,
d449b5d3) and read-only inspection of their existing Notion Chrome tab. Its
Home/Conversation/Meeting navigation was inspected and returned to Home.
The source conversation sidebar and the rendered Partners screenshot were
opened in the same comparison input. This is an adaptation for DeepTutor,
not a pixel-identical clone or a claim about Notion's source code.

## Implemented behavior

- Four top categories use a selected icon-and-label pill, keyboard navigation,
  quiet hover states and reduced-motion support. Switching a category changes
  the sidebar while preserving the open working document.
- Home exposes Dito, task board, Co-Writer and agents.
- Partners exposes configured companions, groups and independent sessions.
  Local configuration, group creation and example conversations persist.
- Learning exposes existing records and four creation choices: book, mastery,
  practice and immersive reading. New items are explicitly local drafts with
  editable titles and notes; they are not falsely presented as generated courses.
- Resources reuses the original Learning Space dashboard and category taxonomy.
  Detail pages are generic local previews, not the original full resource CRUD.
- Sidebar width, selection, subtle transitions and icon alignment are scoped to
  the prototype. The full desktop layout was inspected at 1440 × 960.

## Reused WebUI

- AppShell, SidebarShell, resize hook, existing theme/preferences.
- FeaturePage, PageHeader, LearningShell and LearningCardContent.
- StandaloneComposer / ChatComposer and its existing menus.
- ReadingProvider, ReaderPane, AnnotationList and reading controls.
- CoWriterWorkspace editor, preview, local saving and Markdown export.
- MasteryQuestionCard, MarkdownRenderer, Dialog and Tooltip.
- PartnerAvatar, SpaceDashboard and AgentsHub.
- Original Kanban page extracted unchanged into a reusable KanbanBoard;
  its normal route re-exports that component.

Shared component changes are optional props with existing defaults retained.
No backend or dependency changes were made. Primary checkout sources were not
modified. The worktree reuses the primary checkout's installed node_modules.

## Desktop evidence

- [Learning with persistent records](artifacts/dito-preview/learning-v2.jpg)
- [Partners, groups and sessions](artifacts/dito-preview/partners-v2.jpg)

Prior-iteration evidence remains available for the reused reader and writer:

- [Reader with Dito](artifacts/dito-preview/reader-desktop.jpg)
- [Existing Co-Writer](artifacts/dito-preview/writer-desktop.jpg)

No critical clipping or alignment issues remained in the scoped visual review.
The full framer-motion component initially conflicted with strict LazyMotion;
using its lightweight `m` component resolved that runtime error. Later browser
checks showed no new application errors.

## Functional verification

Verified through browser interaction in this iteration:

- Four-category switching, arrow-key selection, sidebar collapse and expansion.
- Switching sidebar category preserves the open reading document.
- Create a book draft, edit title/notes, reload, and recover the same record.
- Configure partners; create a two-member group and a separate group session;
  send an example message and see the session title update in the sidebar.
- Load the original task board; create a task and move it to Doing.
- Load original AgentsHub and original resource dashboard categories.
- Reopen the reader at its saved chapter, open the existing writer and return.
- Open a sample book's second chapter, render its formula.
- Answer the original practice card and see completed status in Learning.

Earlier iteration verification also covered reading highlights, annotation
navigation, quoted reading context and Co-Writer editing/save/reload/export.

Engineering checks on the final code:

- `npm run typecheck`: passed.
- `npm run architecture:check`: passed, 921 modules / 2919 dependencies.
- Targeted ESLint `--quiet`: passed. Chinese-only prototype copy still has
  the repository's normal i18n warnings.
- `git diff --check`: passed.
- Existing sidebar defaults, lazy history, task-board, Co-Writer integration
  and lazy notebook tests: 5 files, 12 tests passed.

## Prototype boundaries

`demo-transport.ts` intercepts API requests only on `/preview` and stores local
fixtures under `deeptutor.dito-preview.v1.*`. Normal routes retain their normal
transport. Task-board streaming is disabled only for this preview; normal
callers keep existing behavior.

Dito and partner replies are fixed examples. Models, external partner channels,
backend capability execution, parsing and real content generation are not
connected. Learning creation saves a draft. Resource details and totals remain
prototype fixtures; adding a detail entry does not update the dashboard totals.
Unsupported server operations return an explanatory response.

To restart from this worktree's `web/` directory:

```sh
npm run dev -- --webpack --hostname 127.0.0.1 --port 4173
```
