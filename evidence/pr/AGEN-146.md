# PR: test(web): cover memory-graph pure functions (parseDoc/splitRef/buildGraph)

`web/lib/memory-graph.ts` — the pure data layer behind the memory-graph workbench view — had 0% line coverage (314 missing lines, internal coverage-audit gap #10). None of its three exported pure functions (`parseDoc`, `splitRef`, `buildGraph`) was executed by any test, so the markdown-citation parsing contract, the surface-reference grammar, and the concentric-layout geometry that the React + Cytoscape component relies on were all unverified. This PR adds 30 unit tests locking those contracts without touching any product code.

## Summary

- Adds `web/tests/lib/memory-graph.test.ts` (30 cases, +431 lines).
- No product code is modified and no dependency is added: the file uses the native `node:test` runner with `node:assert/strict` and runs as part of the existing `test:node` suite.
- Full `test:node` suite grows from 1234 to **1264 pass / 0 fail** (no regression, ~1.2s).

## Root cause

An internal coverage audit ranked this module among the top gaps (314 missing lines / 0% coverage). `parseDoc` accepts arbitrarily malformed markdown (empty input, prose without bullets, duplicated markers, CRLF line endings, empty or orphaned footnote payloads, legacy bullets without footnotes), `splitRef` defines a `surface:entityId` grammar with several illegal shapes (missing/leading/trailing/multiple colons), and `buildGraph` derives the whole canvas topology from possibly-empty snapshots and cross-surface references. None of these paths had a single assertion, so any regression in marker dedupe, footnote resolution, edge classification (strong vs soft), adjacency symmetry, or in-canvas coordinate bounding would have gone unnoticed.

## Changes

- `web/tests/lib/memory-graph.test.ts` (new): 30 tests in three arms —
  - **`parseDoc` (malformed & boundary input)**: empty content, whitespace-only, prose without bullets; multiple H1 titles; duplicated markers dedupe to the first payload; CRLF line endings; empty footnote payload (`[^1]:`) drops the marker; orphan markers and unknown labels resolve to placeholder stubs; legacy bullets without footnotes; footnote table parsed after entries.
  - **`splitRef` (illegal refs)**: missing colon, empty string, leading/trailing colon, and multi-colon refs keep the remainder in `entityId`.
  - **`buildGraph` (geometry & topology)**: empty snapshot yields the 17-cluster layout (3 L3 + 7×2 L1/L2), 7 hidden anchors (radius 0), 0 edges, and an empty but annotatable slice; cross-surface references produce strong edges (L2→L1, L3→concrete L2) and soft edges (L3→surface anchor) with a symmetric adjacency table; invalid refs produce no edge and never throw; duplicate ids within a surface dedupe; custom layout center is honored; node coordinates stay bounded within the canvas and the node→cluster mapping stays consistent.
- The file uses the `.test.ts` extension (collected by the `test:node` suite) rather than `.spec.ts` (reserved for the jsdom/vitest rendering suite), matching the repo's existing convention for pure-function unit tests.

## Tests

All commands below pass on this branch (rebased onto the current `dev` tip `ef2d9e5c3`, v1.6.12; run from `web/`):

- `npm run test:node` → **1264 tests / 1264 pass / 0 fail** (~1.2s; baseline without this file: 1234 pass)
- `node -r ./scripts/register-node-test-aliases.cjs --test dist/node-tests/tests/lib/memory-graph.test.js` → **30 tests / 30 pass / 0 fail** (~45ms, after the suite's `tsc` build)
- `npm run typecheck` → passed (0 errors)
- `npx eslint tests/lib/memory-graph.test.ts` → 0 errors / 0 warnings
- `npx prettier --check tests/lib/memory-graph.test.ts` → all matched files use Prettier code style
- `python3 scripts/check_workspace_hygiene.py` && `python3 scripts/check_repo_hygiene.py` (repo root) → Repository hygiene check passed

Not covered here: visual/interactive mounting of the `MemoryGraph.tsx` component (React state + Cytoscape canvas). The tested functions are pure and rendering-decoupled; component-level behavior stays with the jsdom spec suite.

## Related issue

No upstream issue tracks this coverage gap; this PR comes from an internal coverage audit of the lowest-covered modules. "Related to" only — it adds tests exclusively and fixes nothing by itself.
