# PR: fix(web): sanitize quoted html tag attributes and preserve bold whitespace

## Summary

- Two display-pipeline defects in `web/lib/markdown-display.ts` allowed unsafe markup to survive the Markdown display escaping pass and corrupted visible text during malformed-strong-emphasis repair.
- `escapeUnknownHtmlTagsForDisplay` stopped its tag scan at the first `>`, even inside a quoted attribute value. As a result `<iframe srcdoc="<script>…">` was never recognized as a tag and reached `rehype-raw`/`parse5` as a live iframe, and `<a title="a>b" onclick="…">` was truncated at the quoted `>` so the `on*=` handler fell outside the `sanitizeAllowedHtmlTag` sanitization pass — both are XSS bypass channels.
- `repairMalformedStrongEmphasis` replaced the whitespace run moved out of a closing `**` marker with a single space, silently dropping tabs and repeated spaces from the visible text.
- Adds `web/tests/lib/markdown-display-security.test.ts` (12 tests) locking both invariants: unknown/unsafe tags stay inert (escaped into code spans, no event handlers, no `srcdoc`), and emphasis repair keeps the marker-stripped visible text byte-identical.

## Root cause

`HTML_LIKE_TAG_REGEX` used `[^<>]*?` for the tag interior, which is not quote-aware: a quoted attribute value containing `<` or `>` either broke the match (tag never recognized, so never escaped) or ended the opening tag early at a quoted `>` (attributes after it escaped the per-tag sanitizer). Attribute values therefore need to be scanned as atomic units.

`MALFORMED_STRONG_EMPHASIS_REGEX` moved the whitespace inside a closing `**` marker outside of it via a hardcoded single-space replacement (`**$1** `) instead of preserving the captured run, so the repair changed the rendered text it was supposed to only re-format. (PR #786 introduced the repair; this keeps its behavior but stops it from rewriting whitespace.)

## Changes

- `web/lib/markdown-display.ts` (+11/−2, net +9 logic+comments):
  - `HTML_LIKE_TAG_REGEX`: tag interior is now `(?:[^<>"']|"[^"]*"|'[^']*')*?` — quoted attribute values participate as whole units, so unknown tags are matched in full and escaped into code spans, and handlers hidden behind a quoted `>` stay inside the sanitized tag.
  - `MALFORMED_STRONG_EMPHASIS_REGEX`: the whitespace run inside a closing `**` is captured (`([ \t]+)`) and restored verbatim after the marker (`**$1**$2`); the marker-stripped visible text is now character-for-character identical before and after repair.
- `web/tests/lib/markdown-display-security.test.ts` (+222): security suite asserting via `outsideCodeSpans`/`assertInertAgainstHtml` that live tags, event handlers, and `srcdoc` cannot escape, plus repair idempotence and visible-text conservation cases.

## Tests

All commands run on this branch rebased on the current `dev` tip (`ef2d9e5c3`, v1.6.12):

- `cd web && npm run test:node` → **1246 tests / 1246 pass / 0 fail**
- `cd web && node -r ./scripts/register-node-test-aliases.cjs --test dist/node-tests/tests/lib/markdown-display-security.test.js` → **12 tests / 12 pass / 0 fail**
- `cd web && node -r ./scripts/register-node-test-aliases.cjs --test dist/node-tests/tests/markdown-display.test.js` → **56 tests / 56 pass / 0 fail**
- `cd web && npm run lint` → **0 errors, 49 warnings** (all pre-existing on `dev`; none introduced here)
- `cd web && npm run typecheck` → **passed** (exit 0)
- Red-green cross-check: with `web/lib/markdown-display.ts` reverted to the `dev` baseline, the full node suite reports **1246 tests / 1242 pass / 4 fail** — exactly the four new security tests (srcdoc iframe escaping, quoted-`>` handler sanitization, percent-decoded markup inertness, bold whitespace conservation). All 1246 pass with this change.

## Related issue

None — found by an internal audit of the Markdown display pipeline; no upstream issue or PR covers quote-aware tag scanning or `srcdoc` escaping as of 2026-10-03 (PR #786 is the earlier strong-emphasis repair this builds on).
