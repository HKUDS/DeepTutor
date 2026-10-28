# Module boundary review — 2026-10-28

Reviewed against local `dev` at `e347c0c2e017248d08297c0cf00f5c55f79747fe`.

## Resolved issues

- Parsing imported the knowledge indexing journal even for plain-text parsing.
  Parsing now owns the progress protocol/context; knowledge keeps compatibility
  exports and supplies the journal implementation.
- Research and Questions prepared PageIndex tools without a knowledge base.
  They now prepare these tools only for an explicitly selected, enabled KB.
  Research credentials no longer import the knowledge-source adapter.
- Calendar unconditionally read Mastery storage. Mastery projections are now
  optional; calendar events, practice projections and automations remain usable.
- Knowledge Frontier needs both Research and Knowledge. Its tool contribution
  declares both availability requirements instead of exposing a broken tool.
- Books' standard quiz/visual blocks and source grounding now have explicit
  dependencies. Optional notebook, audio-note and Manim integrations reject
  unavailable modules with actionable hints. Core suggestions/diagnostics work
  without Memory/Knowledge.
- Word/Excel creation and practice imports/exports also need python-docx and
  openpyxl. These remain core dependencies, independent of Parsing.
- Malformed selection is rejected before pip runs. A failed selection write after
  installation rolls back added packages. Enable rejects mismatched versions.
  Locks cover both the interpreter and shared deployment state.
- Installation, plugin and Manim cancellation share process-tree cleanup;
  Windows uses taskkill /T /F instead of killing only the parent.

## Validation

- Expanded Python regression: 3,979 passed, 61 skipped.
- Final cancellation/module/plugin/renderer/launcher checks: 236 passed.
- Fresh-process assembly for all 25 modules prohibits imports of unrelated
  modules. Independent Core, Parsing, Research, Question, Calendar and API paths
  are exercised; Parsing includes a repeated cache read.
- 26 wheels built with no overlapping installed files.
- Disposable wheel environment: core chat and durable replay, Word/Excel file
  generation, Solve install/run/uninstall/reinstall, independent Parsing,
  Research and Calendar, then individual removal while Solve remains usable.
  Retained data hashes and pip check passed. Model responses use a local fixture.
- Web typecheck and module tests passed; production Web build was validated during
  implementation. Architecture/import contracts, Ruff, generated requirements,
  repository hygiene and README structure checks passed.

Executed locally on macOS / Python 3.13. Windows cleanup command construction is
covered by tests; an actual Windows host was not used. CI has an extended wheel
lifecycle job for Python 3.11 and 3.13. No packages were published.
