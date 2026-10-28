# Notebook blocks and previews — visual acceptance, 2026-10-17

Final result: passed

## Evidence and scope

Source visual truth: user-provided Notion screenshots, especially:

- `/var/folders/b3/y5m8n_7d3k54k9zccynkn0d80000gn/T/codex-clipboard-eb096b9f-d151-44e1-adb1-c18797ca4cb3.png` — basic blocks and heading hierarchy.
- `/var/folders/b3/y5m8n_7d3k54k9zccynkn0d80000gn/T/codex-clipboard-5514480a-87f3-4a23-b289-153153e3b4fc.png` — task-list preview.
- `/var/folders/b3/y5m8n_7d3k54k9zccynkn0d80000gn/T/codex-clipboard-dc4eab6d-4993-40c1-a54d-758dfd151c62.png` — folding headings and columns.

Rendered implementation evidence:

- `/Users/frank/HKUDS/DeepTutor/artifacts/notes/text-preview.jpg`
- `/Users/frank/HKUDS/DeepTutor/artifacts/notes/mobile-final.jpg`
- `/Users/frank/HKUDS/DeepTutor/artifacts/notes/mobile-columns.jpg`

The implementation was inspected in the Codex in-app browser. Desktop capture is 1280 × 720 pixels, with a 1280 × 720 CSS viewport at 1×. Mobile content uses a 390 × 844 CSS iframe at 1× within the same desktop canvas; the capture shows its visible 720-pixel-tall region. This is a responsive browser check, not a native-phone test.

The primary Notion crop is 828 × 726 pixels, approximately 2× density inferred from text/control sizes; original CSS viewport and device pixel ratio were not supplied. Source and implementation were opened together in the same comparison input. Comparison concerns menu hierarchy, state clarity and preview fidelity; it does not claim pixel equality between different products, locales or screenshot scales. Focused menus and text samples are legible in the full captures, so no additional enlargement was needed.

State: light theme; desktop slash menu filtered to headings, Heading 2 selected by keyboard, preview visible; mobile document with long title, stacked columns, collapsed heading and table. Existing DeepTutor body/display typography and theme tokens are retained intentionally.

## Findings and iteration history

All observed P1/P2 items below were fixed and rechecked; no actionable P0/P1/P2 visual findings remain in these inspected states.

| Priority | Earlier finding and impact | Fix | Post-fix evidence |
| --- | --- | --- | --- |
| P1 | Generic samples made text/heading/list previews misleading. | Separate paragraph, heading levels 1–4, semantic ordered/bullet lists, completed task, quote, callout and toggle samples. AI change previews retain block and inline formatting. | `text-preview.jpg`; preview formatting regression test. |
| P2 | A long slash menu clipped its bottom controls. | Constrained popover height, scrolling list and non-scrolling footer. | `text-preview.jpg` shows the final row and close/select footer. |
| P2 | Columns had unequal intrinsic widths. | Equal flexible tracks with minimum width zero and a responsive stacked layout. | Desktop DOM measurement: two 388 px columns in an 804 px content area with a 28 px gap; `mobile-columns.jpg`. |
| P2 | Collapsing a heading did not hide descendants through the React wrapper. | Correct descendant visibility selector, stored collapsed state and expanded-state accessibility. | Fold action removed descendants from the accessibility tree; mobile capture shows collapsed heading above the table. |
| P2 | Long document titles were cut off on narrow screens. | Auto-growing textarea with content sizing; Enter blurs without interfering with IME composition. | `mobile-final.jpg` shows the full title wrapped over two lines. |

## Required fidelity surfaces

- **Fonts and typography:** DeepTutor's existing Geist body/Lora display system is retained. Heading previews visibly distinguish size and weight; body samples use readable line height. Mobile title wraps, including Chinese text. No attempt was made to infer Notion's exact font from the raster crop.
- **Spacing and layout:** Group labels, separators, aligned icon/label/shortcut columns, selected rows and a separate preview card follow the reference interaction structure. Menu stays inside the viewport; document columns stack at narrow width.
- **Colors and tokens:** Existing foreground, muted foreground, surface and border variables provide quiet separators and clear selected states. The light preview card is an intentional DeepTutor adaptation of Notion's dark card. New rich-block dark-theme states were not exhaustively visually checked.
- **Image quality and assets:** Text samples are real rendered content, not raster approximations. Standard lucide/react-icons assets are used for controls. This work does not replace any branded imagery; media-generation quality is outside this visual comparison.
- **Copy and content:** Block-specific sample content communicates the selected element. Menus support localized labels; the illustrated desktop sample uses English labels and Chinese document content. Generated learning content uses localized kind labels.

## Interaction and runtime checks

- Slash search, keyboard selection/preview, block handles, fold/unfold persistence, page persistence, desktop columns and narrow layout were checked in the browser.
- A real model turn read the note and proposed a change; accepting it persisted the result after reload. Automatic specialized-capability results are covered by mapping/conflict tests, not by live generation of every media type.
- Main workspace was integrated without replacing unrelated concurrent changes; the normal local app is available at `http://localhost:3784/co-writer`.
- Final integrated editor screenshot: `/Users/frank/HKUDS/DeepTutor/artifacts/notes/integrated-editor.jpg`. Existing notes render headings, quotes, lists and math. Console checked after the final reload: no new errors.
- Integration uncovered a Turbopack development HMR loop and stalled editor loading. The current local launcher was restarted with `IS_WEBPACK_TEST=1`, selecting the same webpack mode used for successful isolated verification. This is a process-level workaround; the default project bundler setting is unchanged.
- Legacy conversion also triggered React flushSync lifecycle warnings. Editor initialization now runs in a cancelable microtask after React commits. A fresh page load rendered the document and reported no new console errors. Temporary test servers were stopped and their copied model configuration removed.

## Validation and remaining limits

- Related backend regression suite: 180 passed, one warning.
- Integrated frontend suite: 11 passed. After final title/accessibility/formatting edits, focused suite: 7 passed; typecheck and scoped ESLint passed.
- Architecture check: no violations, 1,014 modules and 3,310 dependencies.
- Production build succeeded. Final small title/accessibility/copy edits were additionally checked by typecheck, lint, tests and the development browser.
- Performance-budget check is **not fully passing**: five route budgets already failed in a build of the pre-change working tree. The document editor route decreased from about 464 KB to 408 KB, within its 515 KB budget. Chat/reading integration adds some shared code; no budget thresholds were relaxed.
- This implements useful notebook blocks, workspace task views and learning integrations. It does not claim full Notion database, external integration or collaborative-editing parity.

## Implementation checklist

- [x] Correct text-block and AI change previews.
- [x] Grouped searchable insertion menu with visible footer and keyboard preview.
- [x] Folding headings, callouts, columns, table controls, contents, bookmarks, safe embeds and task views.
- [x] Preserve local edits on conflicting AI proposals or save revisions.
- [x] Integrate with the existing app and inspect desktop/narrow layouts.
- [x] Preserve evidence and document validation limits.

Final result: passed
