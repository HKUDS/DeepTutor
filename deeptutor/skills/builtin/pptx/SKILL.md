---
name: pptx
description: Read, create, or edit PowerPoint .pptx decks — build slides from an outline,
  extract slide text/speaker notes, edit shapes/tables/charts, replace images, or
  export to PDF/images. Use whenever a .pptx (or .ppt) file is an input or output,
  or the user mentions a deck, slides, or a presentation.
tags:
- tool
- office
requires:
  sandbox: shell
---

# pptx

Work with PowerPoint `.pptx` files using **python-pptx** (preinstalled). A `.pptx`
is a ZIP of XML parts; python-pptx handles the structure so you rarely touch XML.
Drop to raw OOXML only for the few things the library can't express (see Advanced).

All work happens in the sandbox `exec` shell, in the current workspace dir where
uploaded files land. Write a short Python heredoc or temp `.py` and run it.
After `exec` completes, use the Generated artifacts URL from the tool result in
the final answer so the user can download the deck.

## Mental model
- A presentation has **slides**; each slide is built from a **layout**; layouts
  live on **slide masters**. Layouts define **placeholders** (title, body,
  picture, etc.) by `idx` and type.
- A slide holds **shapes**: placeholders, text boxes, pictures, tables, charts.
- Shapes with text expose `.text_frame` → `.paragraphs` → `.runs`. A run is the
  unit that carries formatting (font, size, bold, color).
- Units are EMU. Use the helpers: `from pptx.util import Inches, Pt, Emu`.

## Read / extract
```python
from pptx import Presentation
prs = Presentation("deck.pptx")
print(len(prs.slides), prs.slide_width, prs.slide_height)  # EMU dims

for i, slide in enumerate(prs.slides, 1):
    print(f"--- slide {i} (layout: {slide.slide_layout.name}) ---")
    for shape in slide.shapes:
        if shape.has_text_frame:
            print(shape.text_frame.text)          # \n-joined paragraphs
        elif shape.has_table:
            for row in shape.table.rows:
                print([c.text for c in row.cells])
    if slide.has_notes_slide:
        notes = slide.notes_slide.notes_text_frame.text
        if notes:
            print("NOTES:", notes)
```
Iterate `slide.placeholders` to see placeholder `idx` / `placeholder_format.type`.
For a fast text-only dump, just collect `shape.text_frame.text` across slides.

## Create from an outline
List the layouts first — indices vary by template. With the default template,
layout 0 = Title, 1 = Title+Content, 5 = Title Only, 6 = Blank.
```python
from pptx import Presentation
from pptx.util import Inches, Pt

prs = Presentation()  # or Presentation("template.pptx") to inherit a theme
for idx, lay in enumerate(prs.slide_layouts):
    print(idx, lay.name, [(p.placeholder_format.idx, p.name) for p in lay.placeholders])

# Title slide
s = prs.slides.add_slide(prs.slide_layouts[0])
s.shapes.title.text = "My Deck"
s.placeholders[1].text = "Subtitle"      # idx from the listing above

# Title + bullets
s = prs.slides.add_slide(prs.slide_layouts[1])
s.shapes.title.text = "Agenda"
tf = s.placeholders[1].text_frame
tf.text = "First point"                    # first paragraph
for line, lvl in [("Second", 0), ("Sub-point", 1)]:
    p = tf.add_paragraph(); p.text = line; p.level = lvl

prs.save("out.pptx")
```
Always set text via placeholders/shapes — never hand-write bullet glyphs (`•`);
indentation/bullets come from the layout via `paragraph.level`.

Add a free text box or picture on any slide:
```python
tb = s.shapes.add_textbox(Inches(1), Inches(1), Inches(8), Inches(1))
r = tb.text_frame.paragraphs[0].add_run(); r.text = "Hi"; r.font.size = Pt(28); r.font.bold = True
s.shapes.add_picture("logo.png", Inches(0.5), Inches(0.5), height=Inches(1))  # omit w to keep ratio
```

## Edit existing
Edit at the **run** level to preserve a run's formatting; rewriting
`text_frame.text` collapses to one run and drops inline formatting.
```python
for slide in prs.slides:
    for shape in slide.shapes:
        if not shape.has_text_frame: continue
        for para in shape.text_frame.paragraphs:
            for run in para.runs:
                if "{{NAME}}" in run.text:
                    run.text = run.text.replace("{{NAME}}", "Frank")
```
To delete a shape/placeholder: `sp = shape._element; sp.getparent().remove(sp)`.
If the template has more slots than your data, remove the extra shapes entirely
rather than leaving empty placeholders.

### Replace an image in place (keep size/position)
python-pptx has no direct setter; swap the bytes of the related image part. Read
the picture's `r:embed` rId off its `<a:blip>`, then overwrite the part's blob.
```python
from pptx.oxml.ns import qn
for shape in slide.shapes:
    if shape.shape_type == 13:  # MSO_SHAPE_TYPE.PICTURE
        blip = shape._element.find(".//" + qn("a:blip"))
        rid = blip.get(qn("r:embed"))
        with open("new.png", "rb") as f:
            shape.part.related_part(rid)._blob = f.read()
```

### Tables and charts
```python
from pptx.util import Inches
tbl = s.shapes.add_table(rows=2, cols=2, left=Inches(1), top=Inches(1),
                         width=Inches(6), height=Inches(2)).table
tbl.cell(0,0).text = "Header"

from pptx.chart.data import CategoryChartData
from pptx.enum.chart import XL_CHART_TYPE
cd = CategoryChartData(); cd.categories = ["Q1","Q2","Q3"]
cd.add_series("Sales", (4.5, 5.5, 6.2))
s.shapes.add_chart(XL_CHART_TYPE.COLUMN_CLUSTERED, Inches(1), Inches(1),
                   Inches(8), Inches(4.5), cd)
```

## Design (only when the user wants a polished deck, not a data dump)
- Pick a topic-specific palette and one accent; don't default to generic blue.
  One color should dominate. Dark title/closing slides, light content slides.
- Vary layouts across slides (two-column, stat callout, quote, section divider) —
  repeating one bullet layout reads as low-effort. Give most slides a visual
  element (image/chart/shape), not just title + bullets.
- Type scale: title 36-44pt, section headers 20-24pt, body 14-16pt. Bold headers
  and inline labels. Left-align body; center only titles. Keep >=0.5in margins.
- Set `text_frame.word_wrap = True` and watch for overflow; long replacement text
  may spill. After rendering (see Export), inspect the images critically — assume
  there are overlap/overflow/contrast bugs and fix them before declaring done.

## Export to PDF / images (optional, needs LibreOffice)
```bash
command -v soffice >/dev/null || { echo "soffice not available — cannot export"; exit 0; }
soffice --headless --convert-to pdf out.pptx
command -v pdftoppm >/dev/null && pdftoppm -jpeg -r 150 out.pdf slide && ls -1 "$PWD"/slide-*.jpg
```
Read the printed JPG paths with your image-view capability to verify visually.
Re-run conversion after every edit — the PDF won't reflect a changed `.pptx`
otherwise. If `soffice` (or `pdftoppm`) is absent, say so and skip export; do NOT
pip-install.

## .ppt → .pptx
Legacy `.ppt` is a different binary format — python-pptx cannot open it. Convert
first if `soffice` exists, else tell the user it can't be processed:
```bash
command -v soffice >/dev/null && soffice --headless --convert-to pptx old.ppt || echo "need soffice for .ppt"
```

## Advanced: raw OOXML (last resort)
Use only for things python-pptx can't do (e.g. exact-fidelity slide duplication,
gradient fills, theme color edits, untyped XML elements). python-pptx already
exposes each shape's XML via `shape._element` (lxml) — prefer surgical lxml edits
there over a full unzip when you can. For part-level surgery, unzip → edit the
XML part → re-zip with stdlib `zipfile`.

Package map: slide order in `ppt/presentation.xml` `<p:sldIdLst>`; slides in
`ppt/slides/slideN.xml` with rels in `ppt/slides/_rels/slideN.xml.rels`; layouts/
masters under `ppt/slideLayouts`, `ppt/slideMasters`; media in `ppt/media/`;
part types in `[Content_Types].xml`.

Critical invariants if you add/edit parts by hand — break one and PowerPoint
reports the file as corrupt:
- Every new part is declared in `[Content_Types].xml` (an `<Override>` for slides;
  a `<Default>` per media extension like png/jpeg).
- Every cross-part link goes through a `_rels/*.rels` `<Relationship>`; r:id refs
  in XML must resolve. Adding a slide means: write the part + its `.rels`, add the
  content-type override, add a `<Relationship>` in `presentation.xml.rels`, and a
  `<p:sldId>` in `<p:sldIdLst>`.
- IDs must be unique: `<p:sldId>` ids, and shape ids (`<p:cNvPr id=...>`) within a
  slide. `sldLayoutId`/`sldMasterId` are globally unique.
- Whitespace: any `<a:t>` with leading/trailing spaces needs `xml:space="preserve"`.
- Parse/serialize with lxml or `defusedxml`; never naive string munging that
  mangles namespaces or pretty-prints into text nodes.

Minimal text edit by zip surgery (zip members can't be overwritten in place —
rebuild the archive, swapping the one part):
```python
import zipfile
target = "ppt/slides/slide1.xml"
with zipfile.ZipFile("in.pptx") as zin:
    xml = zin.read(target).decode().replace("Old title", "New title")
    with zipfile.ZipFile("out.pptx", "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.namelist():
            zout.writestr(item, xml.encode() if item == target else zin.read(item))
```

## Verify before done
Reopen the output with `Presentation("out.pptx")` and assert slide count / key
text — a clean reopen catches most corruption. For decks meant to look good,
also export and visually inspect (above). Check templates for leftover
placeholder text (`xxxx`, `lorem`, `[insert ...]`) and fix before declaring done.
