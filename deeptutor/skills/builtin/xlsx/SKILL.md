---
name: xlsx
description: Read, create, or edit Excel spreadsheets (.xlsx/.xlsm) — sheet data,
  formulas, styles, charts, multi-sheet workbooks — and bulk .csv/.tsv tables; use
  whenever a spreadsheet is the input or the deliverable (extract/analyze data, add
  columns/formulas/formatting/charts, clean messy tables, build from scratch), but
  not for Google Sheets API or Word/PDF/script outputs.
tags:
- tool
- office
requires:
  sandbox: shell
---

# Excel (.xlsx) workbooks

Work in the workspace dir (where uploads land) by writing short Python run via
`exec`. Two libraries, both preinstalled — pick by task:
After `exec` completes, use the Generated artifacts URL from the tool result in
the final answer so the user can download the workbook.

- **pandas** — bulk tabular read/write/analysis. Use for "load this sheet,
  compute, dump a table". Drops all formatting and formulas.
- **openpyxl** — cells, formulas, styles, charts, merged cells, multi-sheet,
  number formats. Use whenever formatting, formulas, or fidelity matter.

## THE critical gotcha: openpyxl writes formulas but never computes them

`ws["B10"] = "=SUM(B2:B9)"` stores the formula *string*. openpyxl has no formula
engine — the cached value stays empty (or stale, on an edited file). So:

- A workbook you create/edit with openpyxl opens fine in Excel/LibreOffice (they
  recompute on open), but its cached values are wrong until then.
- Anything reading cached values first — `data_only=True`, another
  pandas/openpyxl pass, or a downstream tool — sees blanks/stale data.

Pick by what the deliverable needs:

1. **Static numbers (most common).** If the user just needs correct values and
   the sheet need not stay live, compute in Python and write the **number**, not
   a formula string: `ws["B10"] = sum(c.value for c in ws["B2:B9"][0])`. Correct
   immediately, no recalc needed.
2. **Live model** (formulas that recompute on the user's later edits). Write real
   formulas, and reference cells not literals (`=B5*(1+$B$6)`, not `=B5*1.05`).
   openpyxl can't set the cached value too, so either recalc with LibreOffice if
   present (gate it — often absent):
   ```bash
   command -v soffice >/dev/null && \
     soffice --headless --convert-to xlsx --outdir /tmp out.xlsx \
       >/dev/null 2>&1 && cp /tmp/out.xlsx out.xlsx
   ```
   `--convert-to xlsx` reopens and recalculates, repopulating cached values. If
   `soffice` is missing, say so and warn the user the formulas populate when they
   open the file in Excel — never assume soffice exists.

## Reading

```python
import pandas as pd
df = pd.read_excel("in.xlsx")                          # first sheet
sheets = pd.read_excel("in.xlsx", sheet_name=None)     # dict of all sheets
df = pd.read_excel("in.xlsx", dtype={"id": str})       # stop id->float coercion
```

To read **computed results** of formulas (not the formula text), use openpyxl
with `data_only=True` — returns the value Excel last cached:

```python
from openpyxl import load_workbook
wb = load_workbook("in.xlsx", data_only=True)
val = wb["Sheet1"]["B10"].value     # None if Excel never opened/saved the file
```

Gotcha: never `save()` a workbook loaded with `data_only=True` — that discards
every formula permanently (verified: the cell becomes `None`). Load twice if you
need both formulas and values.

Large file: `load_workbook(path, read_only=True)` streams rows cheaply.

## Creating

```python
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment

wb = Workbook(); ws = wb.active; ws.title = "Summary"
ws.append(["Region", "Sales"])              # header row
for r in [("West", 120), ("East", 95)]:
    ws.append(r)
ws["B4"] = "=SUM(B2:B3)"                     # see formula gotcha above

ws["A1"].font = Font(bold=True)
ws["A1"].fill = PatternFill("solid", fgColor="DDDDDD")
ws["A1"].alignment = Alignment(horizontal="center")
ws["B2"].number_format = "#,##0"            # thousands separator
ws.column_dimensions["A"].width = 18
ws.freeze_panes = "A2"                       # freeze header
wb.create_sheet("Detail")                    # second sheet
wb.save("out.xlsx")
```

Bulk data is faster via pandas, then style with openpyxl after:
```python
df.to_excel("out.xlsx", index=False, sheet_name="Data")
```

## Editing (preserve existing formatting)

`load_workbook` keeps styles, formulas, merged cells, charts intact — edit only
what you touch. Do NOT round-trip through pandas to preserve formatting (pandas
rewrites the whole sheet, losing styles).

```python
from openpyxl import load_workbook
wb = load_workbook("in.xlsx")               # keep formulas (data_only=False)
ws = wb["Sheet1"]
ws["C2"] = "Updated"
wb.save("in.xlsx")
```

Match the file's existing conventions (font, number formats, colors) rather than
imposing new ones — an established template wins over any default.

When inserting/deleting rows or columns (`ws.insert_rows`, `ws.delete_cols`),
openpyxl does **not** rewrite formulas that reference shifted cells. Re-point
affected formulas yourself, or avoid structural shifts in formula-heavy sheets.

## Charts

```python
from openpyxl.chart import BarChart, Reference
ch = BarChart(); ch.title = "Sales"
data = Reference(ws, min_col=2, min_row=1, max_row=3)   # include header for title
cats = Reference(ws, min_col=1, min_row=2, max_row=3)
ch.add_data(data, titles_from_data=True); ch.set_categories(cats)
ws.add_chart(ch, "E2")
```
LineChart / PieChart / ScatterChart follow the same shape.

## Verifying you produced clean output

After writing, reload and scan for error strings — these mean broken formulas
that recalc surfaced (`#REF!` bad reference, `#DIV/0!` zero denominator,
`#VALUE!` type mismatch, `#NAME?` unknown function, `#N/A`):

```python
from openpyxl import load_workbook
wb = load_workbook("out.xlsx", data_only=True)
errs = [f"{s}!{c.coordinate}={c.value}"
        for s in wb.sheetnames for row in wb[s].iter_rows() for c in row
        if isinstance(c.value, str) and c.value.startswith("#")]
print(errs or "clean")
```
This only catches errors in *cached* values. If you wrote formulas and couldn't
recalc (no soffice), cached values are blank, so the check is meaningful only
after a recalc or after Excel opens the file. Writing computed numbers (option 1)
sidesteps this.

## CSV / TSV

```python
df = pd.read_csv("in.csv")                   # sep="\t" for TSV
df.to_csv("out.csv", index=False)
```
For messy input (junk rows, header not on row 1, ragged columns): inspect raw
lines first, then `pd.read_csv(..., skiprows=, header=, usecols=, on_bad_lines="skip")`.

## Raw OOXML (rarely needed)

openpyxl covers essentially all xlsx features; reach for raw XML only for the
narrow cases it can't express (e.g. preserving an exotic part it drops on
re-save). An .xlsx is a ZIP: `xl/workbook.xml`, `xl/worksheets/sheet1.xml`,
`xl/sharedStrings.xml`, plus `[Content_Types].xml` and `_rels/`. Unzip with
stdlib `zipfile`, edit the part, re-zip — keep `[Content_Types].xml` and every
`.rels` consistent, keep IDs unique, and don't pretty-print into value-bearing
text nodes. Correctness check = it opens in Excel with no repair prompt.
