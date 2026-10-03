# PR: fix(co-writer): keep placeholder row and warn when DOCX table row parsing fails

## Summary

- `deeptutor/co_writer/docx_converter.py` silently dropped a table row when `_cell_text` raised while parsing its cells (`except Exception: continue`), so a malformed DOCX table lost content in the exported markdown with no trace.
- This PR logs a structured warning (table ordinal `table #N` + row number `row #M` + exception summary) and keeps a `(unparseable row)` placeholder cell in the table instead of dropping the row.
- Normal-row parsing, empty-row filtering, and table width alignment are unchanged; the fix only affects the previously-silent failure path.
- Adds 2 regression tests (unit-level via `_table_to_markdown`, end-to-end via `docx_to_markdown` with a patched `python-docx` document).

## Root cause

`_table_to_markdown` wrapped cell extraction in a bare `except Exception: continue`. A row whose cells raise (e.g. a structurally broken grid) therefore vanished from the converted markdown, making "why is this table missing a row?" impossible to debug from logs and silently discarding user content.

## Changes

- `deeptutor/co_writer/docx_converter.py` (+34/−3):
  - `docx_to_markdown` numbers tables in document order and passes the ordinal through to `_block_to_markdown` / `_table_to_markdown`.
  - `_table_to_markdown` now enumerates rows; on a parsing exception it logs `WARNING` with `table #N row #M` context (e.g. `DOCX table #1 row #2 could not be parsed; kept a placeholder row (...)`) and appends a single `(unparseable row)` placeholder cell, so the row stays visible and column alignment of surrounding rows is unaffected.
  - Placeholder is plain English text that markdown renderers will not mistake for a link reference.
- `tests/api/test_co_writer.py` (+83/−1): 2 new tests — `test_table_to_markdown_warns_and_keeps_placeholder_for_unparseable_row` (fake table with one bad row; asserts warning text with row context and placeholder cell in output) and `test_docx_to_markdown_bad_table_row_warns_and_keeps_placeholder` (patched document; asserts `table #1 row #2` context and placeholder via `caplog`).

## Tests

All commands run on a branch based on the current `dev` tip (`ef2d9e5c3`, v1.6.12):

- `python -m pytest tests/api/test_co_writer.py -k "unparseable_row or bad_table_row"` → **2 passed**, 34 deselected
- `python -m pytest tests/api/test_co_writer.py -k docx` → **12 passed**, 24 deselected
- `python -m pytest tests/ -k docx` → **26 passed, 1 skipped**, 8039 deselected (skip is a pre-existing optional-dependency skip, unrelated)
- `python -m pytest tests/api/test_co_writer.py` → **36 passed**
- Red-green check: with the source restored to the pre-fix state, the 2 new tests fail (1 `TypeError` on the new `table_ordinal` parameter, 1 `AssertionError` on the missing placeholder row), confirming they pin the fix.
- `ruff check deeptutor/co_writer/docx_converter.py tests/api/test_co_writer.py` → All checks passed
- `pre-commit run --files deeptutor/co_writer/docx_converter.py tests/api/test_co_writer.py` → all hooks Passed (ruff, ruff format, mypy, bandit, detect-secrets, hygiene)

## Related issue

None — no existing upstream issue covers DOCX table row parsing failures. Found during an internal audit of silent `except: continue` sites in the co-writer DOCX converter. This change makes the failure diagnosable and keeps user content visible; it does not attempt to repair unparseable rows, so it is related to (not a complete fix for) robustness of DOCX table conversion.
