---
name: docx
description: Read, create, or edit Microsoft Word .docx files — extract/summarize
  text and tables, generate reports/letters/memos with headings, tables, images, TOC
  and page numbers, do find-and-replace, or apply tracked changes (redlines) and comments.
  Use whenever the user has a .docx or wants a Word deliverable. Not for PDF, .xlsx,
  .pptx, or Google Docs.
tags:
- tool
- office
requires:
  sandbox: shell
---

# DOCX (Microsoft Word)

A `.docx` is a ZIP of XML parts. Body text lives in `word/document.xml`. Two tiers:

- **Default — `python-docx`** (preinstalled): create, read, and simple edits. Use for almost everything.
- **Advanced — raw OOXML via `zipfile`**: only for what python-docx cannot express — tracked changes (redlines), comments, and exact-fidelity edits that must preserve every untouched byte. See [Raw OOXML](#raw-ooxml-advanced).

Work in the current directory (uploaded files land here). Write output to a new filename; don't overwrite the source.
After `exec` completes, use the Generated artifacts URL from the tool result in the final answer so the user can download the document.

## Read / extract

```python
from docx import Document
doc = Document("in.docx")
text = "\n".join(p.text for p in doc.paragraphs)      # body paragraphs
for tbl in doc.tables:                                 # tables
    for row in tbl.rows:
        print([c.text for c in row.cells])
```

`doc.paragraphs` skips text inside tables, headers/footers, and text boxes — iterate `doc.tables` and `doc.sections[i].header/.footer` for those. Each paragraph's style: `p.style.name` (e.g. `"Heading 1"`).

To read **tracked changes**, parse the XML directly — `python-docx` ignores `<w:ins>`/`<w:del>`:

```python
import zipfile, re
xml = zipfile.ZipFile("in.docx").read("word/document.xml").decode("utf-8")
# inserted text = <w:ins>…<w:t>…  deleted = <w:del>…<w:delText>…
print(re.findall(r"<w:t[^>]*>(.*?)</w:t>", xml))
```

## Create

```python
from docx import Document
from docx.shared import Pt, Inches, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH

doc = Document()                                  # default template page size
doc.add_heading("Quarterly Report", level=0)      # 0 = title; 1..9 = H1..H9
p = doc.add_paragraph("Intro paragraph. ")
run = p.add_run("Bold tail."); run.bold = True
doc.add_paragraph("First item", style="List Bullet")   # real list style, never a "• " literal
doc.add_paragraph("Step one", style="List Number")

# Table — header row + data
tbl = doc.add_table(rows=1, cols=2); tbl.style = "Light Grid Accent 1"
tbl.rows[0].cells[0].text, tbl.rows[0].cells[1].text = "Metric", "Value"
for k, v in [("Revenue", "1.2M"), ("Growth", "15%")]:
    c = tbl.add_row().cells; c[0].text, c[1].text = k, v

doc.add_picture("chart.png", width=Inches(5))     # image, scaled to width
doc.add_page_break()
doc.save("out.docx")
```

Rules:
- **Never type bullet/number characters** (`•`, `1.`) into text — use `style="List Bullet"`/`"List Number"`. Only list styles defined in the doc's template are available.
- **No `\n` inside a run** — each visual line is its own `add_paragraph`.
- **Built-in style names must match the template** (e.g. `"Heading 1"`, `"List Bullet"`); a wrong name raises `KeyError`.
- Units: `Pt`, `Inches`, `Cm` from `docx.shared`. Colors: `RGBColor(0x1F,0x4E,0x79)`.

### Page setup, headers/footers, page numbers

```python
from docx.shared import Inches
sec = doc.sections[0]
sec.page_width, sec.page_height = Inches(8.5), Inches(11)   # Letter
sec.top_margin = sec.bottom_margin = Inches(1)
sec.header.paragraphs[0].text = "Confidential"
```

Page-number fields aren't in the python-docx API; inject the field XML into a footer run:

```python
from docx.oxml.ns import qn
from docx.oxml import OxmlElement
def add_page_number(paragraph):
    for t in ("begin", "instr", "end"):
        r = OxmlElement("w:r")
        if t == "instr":
            fld = OxmlElement("w:instrText"); fld.set(qn("xml:space"), "preserve"); fld.text = "PAGE"
        else:
            fld = OxmlElement("w:fldChar"); fld.set(qn("w:fldCharType"), t)
        r.append(fld); paragraph._p.append(r)
add_page_number(doc.sections[0].footer.paragraphs[0])
```

A clickable **Table of Contents** is also a field; Word shows "right-click → Update Field" until refreshed. Same pattern with `instrText` = `TOC \o "1-3" \h \z \u`.

## Edit existing (simple)

`python-docx` preserves the rest of the document; mutate then save under a new name.

```python
doc = Document("in.docx")
# Find-and-replace, keeping each run's formatting:
for p in doc.paragraphs:
    if "{{CLIENT}}" in p.text:
        for r in p.runs:
            r.text = r.text.replace("{{CLIENT}}", "Acme Co")
doc.save("out.docx")
```

Gotcha: Word splits text across runs, so a phrase may not live in one `run.text` even though `p.text` shows it whole. If the placeholder spans runs, set `p.runs[0].text = p.text.replace(...)` and clear the rest (`for r in p.runs[1:]: r.text = ""`) — this collapses formatting to the first run, acceptable for plain placeholders. For exact-fidelity edits, use the raw-OOXML tier.

## .doc → .docx and PDF export (LibreOffice, optional)

Legacy binary `.doc` can't be read by python-docx, and there is no built-in PDF export. Both need LibreOffice, which is often **absent** — probe first and degrade with a clear note if missing:

```bash
command -v soffice >/dev/null && soffice --headless --convert-to docx legacy.doc || echo "soffice unavailable — cannot convert .doc; ask user for a .docx"
command -v soffice >/dev/null && soffice --headless --convert-to pdf out.docx   || echo "soffice unavailable — cannot export PDF"
```

Network egress is off — never `pip install` or download. If a needed tool is absent, say so and stop, don't improvise.

## Raw OOXML (advanced)

Only when python-docx can't express it: **tracked changes, comments, exact-fidelity edits.** Workflow: read the XML part → edit it as text → re-zip every original member, rewriting only the changed part.

```python
import zipfile
src, dst = "in.docx", "out.docx"
with zipfile.ZipFile(src) as z: xml = z.read("word/document.xml").decode("utf-8")
xml = xml.replace("OLD", "NEW")          # or splice tracked-change elements (below)
with zipfile.ZipFile(src) as zin, zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as zout:
    for item in zin.infolist():
        data = xml.encode("utf-8") if item.filename == "word/document.xml" else zin.read(item.filename)
        zout.writestr(item, data)
```

Critical traps (these silently corrupt the file or lose text):
- **`xml:space="preserve"`** on any `<w:t>`/`<w:delText>` with leading/trailing whitespace, or Word strips the space.
- **Don't pretty-print** into text nodes — added newlines/indent inside `<w:t>` become visible spaces. Edit the XML as a string; never reserialize the whole tree with indentation.
- **Keep parts consistent**: new image/part → add its `<Relationship>` in `word/_rels/document.xml.rels` *and* a content type in `[Content_Types].xml`, or the doc opens "corrupt."
- **Unique IDs**: every `w:id` on `<w:ins>`/`<w:del>`/comments must be unique in the file. `w14:paraId`/`w16cid:durableId` must be `< 0x7FFFFFFF` (8-digit hex).
- **Element order in `<w:pPr>`**: `pStyle`, `numPr`, `spacing`, `ind`, `jc`, then `rPr` last.

### Tracked changes (redlines)

Use a consistent author (default `"Claude"` unless the user names one) and ISO date. Replace the **whole `<w:r>`** with siblings — never nest change tags inside a run — and copy the original `<w:rPr>` into the new runs to keep formatting.

```xml
<!-- change "30 days" → "60 days" -->
<w:r><w:t xml:space="preserve">The term is </w:t></w:r>
<w:del w:id="1" w:author="Claude" w:date="2026-01-01T00:00:00Z">
  <w:r><w:delText>30</w:delText></w:r></w:del>
<w:ins w:id="2" w:author="Claude" w:date="2026-01-01T00:00:00Z">
  <w:r><w:t>60</w:t></w:r></w:ins>
<w:r><w:t xml:space="preserve"> days.</w:t></w:r>
```

- Inside `<w:del>` use `<w:delText>` (not `<w:t>`); inside `<w:ins>` never use `<w:delText>`.
- **Deleting a whole paragraph**: also mark its paragraph mark — add `<w:del .../>` inside `<w:pPr><w:rPr>` — or accepting changes leaves an empty paragraph.
- **Reject another author's insertion**: nest your `<w:del>` *inside* their `<w:ins>`. **Restore their deletion**: add a new `<w:ins>` *after* their `<w:del>` — never edit their tags.

### Comments

Comments live in a separate `word/comments.xml` part (create it + its relationship in `word/_rels/document.xml.rels` + a content-type override if absent). In `document.xml`, the anchor markers `<w:commentRangeStart w:id="N"/>` and `<w:commentRangeEnd w:id="N"/>` are **siblings of `<w:r>`, never inside one**; follow the end marker with `<w:r><w:rPr><w:rStyle w:val="CommentReference"/></w:rPr><w:commentReference w:id="N"/></w:r>`. This is fiddly — verify the output opens in Word.

## Verify before returning

Always confirm the file reopens cleanly — a silent corruption is the most common failure:

```python
from docx import Document
d = Document("out.docx"); print(len(d.paragraphs), "paragraphs OK")
```

For raw-OOXML edits also run `python -c "import zipfile; zipfile.ZipFile('out.docx').testzip()"` and well-formedness-check each edited XML part with `lxml.etree.parse`.
