---
name: pdf
description: Read, extract (text/tables), create, merge/split/rotate, watermark, encrypt,
  fill, and render-to-image .pdf files. Use whenever the user uploads a .pdf or asks to
  produce, edit, or pull data out of one.
tags:
- tool
- office
requires:
  sandbox: shell
---

# PDF

Work PDFs in the sandbox with preinstalled Python libs. Pick the library by task:

- **Extract** text/tables/layout/word-coordinates → `pdfplumber`; quick raw text or page ops → `pypdf`.
- **Merge / split / rotate / crop / watermark / encrypt / metadata** → `pypdf`.
- **Fill forms** → `pypdf` (fillable AcroForm fields) or annotation overlay (flat forms).
- **Create from scratch** → `reportlab`.

Write a short Python snippet and run it via `exec`. Save outputs to the workspace dir.
After `exec` completes, use the Generated artifacts URL from the tool result in the final answer so the user can download the PDF.

## Extract text and tables (pdfplumber)

```python
import pdfplumber
with pdfplumber.open("in.pdf") as pdf:
    for i, page in enumerate(pdf.pages, 1):
        print(f"--- page {i} ---")
        print(page.extract_text() or "")        # layout-aware text
        for t in page.extract_tables():          # list of tables; each is list[row]
            for row in t:
                print(row)
```

Tables → DataFrame/Excel:
```python
import pdfplumber, pandas as pd
frames = []
with pdfplumber.open("in.pdf") as pdf:
    for page in pdf.pages:
        for t in page.extract_tables():
            if t and len(t) > 1:
                frames.append(pd.DataFrame(t[1:], columns=t[0]))
if frames:
    pd.concat(frames, ignore_index=True).to_excel("tables.xlsx", index=False)
```

Messy tables: pass strategies, or crop a region with `page.within_bbox((x0, top, x1, bottom))` first:
```python
ts = {"vertical_strategy": "lines", "horizontal_strategy": "lines",
      "snap_tolerance": 3, "intersection_tolerance": 15}
page.extract_tables(ts)
```

For very large PDFs where you only need raw text, `pypdf`'s `page.extract_text()` is lighter.

## Scanned / image-only PDFs (be honest)

If `extract_text()` returns empty or garbage (e.g. `(cid:NN)` runs) the page is scanned. **No OCR engine (tesseract) is installed and network is off**, so you cannot recover that text. Say so plainly and stop — do not fabricate content or attempt `pip install`.

## Merge / split / rotate / crop / metadata (pypdf)

```python
from pypdf import PdfReader, PdfWriter

# Merge
w = PdfWriter()
for f in ["a.pdf", "b.pdf"]:
    for p in PdfReader(f).pages:
        w.add_page(p)
w.write("merged.pdf")

# Split: one file per page
r = PdfReader("in.pdf")
for i, p in enumerate(r.pages, 1):
    w = PdfWriter(); w.add_page(p); w.write(f"page_{i}.pdf")

# Rotate page 0 by 90 degrees clockwise
r = PdfReader("in.pdf"); w = PdfWriter()
r.pages[0].rotate(90); w.add_page(r.pages[0]); w.write("rotated.pdf")
```

- **Metadata**: `PdfReader("in.pdf").metadata` (`.title`, `.author`, ...).
- **Crop**: set `page.mediabox.left/bottom/right/top` (points, origin y=0 at bottom).
- **Encrypt**: `w = PdfWriter(clone_from=PdfReader("in.pdf")); w.encrypt("userpw", "ownerpw"); w.write("enc.pdf")`.
- **Decrypt**: `r = PdfReader("enc.pdf"); r.decrypt("pw")` if `r.is_encrypted`, then read/copy pages.

Watermark (stamp one page over every page):
```python
from pypdf import PdfReader, PdfWriter
wm = PdfReader("stamp.pdf").pages[0]
r = PdfReader("in.pdf"); w = PdfWriter()
for p in r.pages:
    p.merge_page(wm); w.add_page(p)
w.write("stamped.pdf")
```

## Create PDFs (reportlab)

Flowing document (preferred for text/reports/tables — handles pagination):
```python
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle

styles = getSampleStyleSheet()
story = [Paragraph("Report Title", styles["Title"]), Spacer(1, 12),
         Paragraph("Body text. " * 20, styles["Normal"])]
data = [["Product", "Q1", "Q2"], ["Widgets", "120", "135"]]
tbl = Table(data)
tbl.setStyle(TableStyle([
    ("BACKGROUND", (0, 0), (-1, 0), colors.grey),
    ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
    ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
]))
story += [Spacer(1, 12), tbl]
SimpleDocTemplate("out.pdf", pagesize=letter).build(story)
```

Absolute placement (labels at fixed coordinates): use `canvas.Canvas("out.pdf", pagesize=letter)`, `c.drawString(x, y, "...")` (origin bottom-left, points), `c.showPage()` per page, `c.save()`.

### Non-Latin text (Chinese / Japanese / Korean, Cyrillic, …)

reportlab's built-in fonts (Helvetica/Times/Courier) carry **zero CJK glyphs**, so any 中文/日本語/한국어 renders as empty boxes (□) baked permanently into the PDF. reportlab never auto-discovers system fonts — you MUST register a font that has the glyphs and set it on every style. **Whenever the document may contain non-Latin text, register a CJK font first** (it also covers Latin, so it is safe to use as the only font):

```python
import os
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

def register_cjk_font(name="CJK"):
    # TrueType ONLY — reportlab cannot embed CFF/OpenType outlines, so a .otf
    # like Noto Sans CJK fails with "postscript outlines are not supported".
    for path in [
        "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",        # Linux sandbox (fonts-wqy-zenhei)
        "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
        "/System/Library/Fonts/STHeiti Light.ttc",             # macOS
        "/System/Library/Fonts/Hiragino Sans GB.ttc",
        "/System/Library/Fonts/Supplemental/Songti.ttc",
        "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
        "C:/Windows/Fonts/msyh.ttc",                           # Windows
    ]:
        if os.path.exists(path):
            try:
                pdfmetrics.registerFont(TTFont(name, path, subfontIndex=0))
                return name
            except Exception:
                continue
    raise RuntimeError("No CJK-capable TrueType font found — do not emit tofu; say so.")

font = register_cjk_font()
styles = getSampleStyleSheet()
for s in styles.byName.values():                 # make the CJK font the default everywhere
    s.fontName = font
# Tables don't read the stylesheet — set the font in the TableStyle too:
#   ("FONTNAME", (0, 0), (-1, -1), font)
# Canvas: c.setFont(font, size) before every drawString.
```

If `register_cjk_font` raises (no font on the host), do **not** ship a tofu PDF — tell the user the sandbox lacks a CJK font instead of producing garbage.

Gotcha: even with a good font, reportlab still needs markup for subscripts/superscripts. In `Paragraph` use `Paragraph("H<sub>2</sub>O", styles["Normal"])`, `x<super>2</super>`.

Markdown/HTML → PDF needs an external converter (`soffice`/`pandoc`) that is usually absent — `command -v soffice` / `command -v pandoc` and degrade to building the PDF directly with reportlab if neither is present.

## Fill forms (pypdf)

First detect whether the PDF has real fillable (AcroForm) fields:
```python
from pypdf import PdfReader
fields = PdfReader("form.pdf").get_fields()
print("fillable" if fields else "flat (no fields)")
```

**Fillable** — inspect field names/types, then fill and write:
```python
from pypdf import PdfReader, PdfWriter
r = PdfReader("form.pdf")
for name, f in r.get_fields().items():
    print(name, f.get("/FT"), f.get("/_States_"))   # /Tx text, /Btn checkbox/radio, /Ch choice

w = PdfWriter(clone_from=r)
values = {"first_name": "Bart", "agree": "/Yes"}     # checkbox/radio: use its on-state, NOT True/False
for page in w.pages:
    w.update_page_form_field_values(page, values, auto_regenerate=False)
w.set_need_appearances_writer(True)                  # force viewers to render the values
w.write("filled.pdf")
```
Checkbox/radio values are on-state strings, not booleans — read the field's `/_States_` (e.g. `/Yes`, `/On`); `/Off` clears it.

**Flat form (no fields)** — overlay text with `FreeText` annotations at PDF coordinates. Get real coordinates from the layout with pdfplumber instead of guessing:
```python
import pdfplumber
with pdfplumber.open("form.pdf") as pdf:
    pg = pdf.pages[0]
    for wd in pg.extract_words():     # each has x0, top, x1, bottom (TOP-left origin!)
        print(wd["text"], wd["x0"], wd["top"])
    for rc in pg.rects:               # small squares are likely checkboxes
        print("rect", rc["x0"], rc["top"], rc["x1"], rc["bottom"])
```
pdfplumber `top` is measured from the page top; pypdf rects are bottom-left, so convert: `pdf_y = page_height - top`. Place text just right of the matching label:
```python
from pypdf import PdfReader, PdfWriter
from pypdf.annotations import FreeText
r = PdfReader("form.pdf"); w = PdfWriter(); w.append(r)
h = float(r.pages[0].mediabox.height)
top = 700  # pdfplumber 'top' of the label's row
w.add_annotation(page_number=0, annotation=FreeText(
    text="Smith", rect=(255, h - top - 14, 720, h - top),   # (x0, y0, x1, y1)
    font="Helvetica", font_size="10pt", font_color="000000",
    border_color=None, background_color=None))
w.write("filled.pdf")
```
Verify: re-open the output and re-read `get_fields()` values (fillable) or re-extract text (overlay) to confirm the values landed.

## Page → image rendering (PyMuPDF)

`PyMuPDF` (imported as `fitz`, preinstalled) rasterizes pages — useful to inspect a PDF visually or to hand a page to an image-capable step. No external tools needed (poppler / pdf2image are absent; don't reach for them).

```python
import fitz  # PyMuPDF
doc = fitz.open("in.pdf")
for i, page in enumerate(doc, 1):
    page.get_pixmap(dpi=150).save(f"page_{i}.png")   # higher dpi = sharper + larger
```

`fitz` also extracts text (`page.get_text()`) and can render a sub-region via `page.get_pixmap(clip=fitz.Rect(x0, y0, x1, y1))`. It does **not** OCR — a rendered scanned page is still just pixels (see Scanned PDFs above).
