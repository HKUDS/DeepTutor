# Source visuals in knowledge bases

DeepTutor can retain extracted source images when a PDF or EPUB parser emits
image files. The KB stores verified parser-extracted PNG, JPEG, GIF, or WebP
bytes with a deterministic asset ID, document hash, parser identity, source
locator, caption and nearby text. Structured parser blocks also preserve a page
index and bounding box
when available. The visual record lives under the KB's `visual_assets/`
directory, separate from the vector index. The access checked API route
`/api/knowledge-bases/{kb_name}/visual-assets/{asset_id}` serves those exact
bytes, and deleting a raw source file removes its visual assets.

The LlamaIndex KB pipeline indexes a text record for each source visual, so a
text embedding model can retrieve it by its caption and context. When `rag`
retrieves that record in the chat loop, a vision capable answer model receives
the verified image pixels in its next request. A text only model receives the
caption and context with an explicit warning that it has not seen the pixels.
At most 64 images per document are retained, each image is limited to 5 MiB,
and at most two retrieved images are sent in one model continuation.

Current extraction coverage depends on the selected parser. MinerU can emit
structured PDF figures. PyMuPDF4LLM can emit PDF and EPUB images when image
extraction is enabled, but its Markdown output does not supply page boxes.
The default text only parser and the current Docling adapter do not emit
source image assets. Images that are only vector drawing commands, or pages
that require OCR when no usable OCR engine is configured, may be absent.
Other RAG providers do not yet index this visual manifest. Interactive
exercises, visual annotations, and mastery updates are separate future work.

## Tiny scanned PDF pages with MinerU

Some scanned PDFs encode a full-resolution page in an unusually small physical
page box. MinerU's official cloud backend can optionally enlarge these pages in
a temporary upload copy. The original file, page order, compressed image bytes,
and soft masks are preserved; language, OCR, model, formula, and table settings
remain as configured. This is a geometry workaround, not a guarantee of better
OCR or preservation of arbitrary interactive PDF semantics.

The option defaults to off. An administrator can enable it through the existing
`PUT /api/settings/document-parsing` endpoint with this partial payload:

```json
{"engines": {"mineru": {"normalize_tiny_scans": true}}}
```

Use `false` to disable it. The option also lives at
`engines.mineru.normalize_tiny_scans` in `document_parsing.json`. Enabling it
changes the cloud parse-cache signature; old parses remain intact. Existing
indexes are not rebuilt automatically. The optional
`deeptutor[parse-pymupdf4llm]` extra provides the required PyMuPDF dependency.

Only text-free pages below 144 points on their longest side, with a
high-resolution image covering at least 80% of the page at an apparent density
of at least 1200 DPI, qualify. The longest side is scaled to 768 points.
Rotated, cropped, annotated, vector-bearing, or non-default UserUnit pages are
left unchanged. Local MinerU, custom cloud endpoints, normal PDFs, and non-PDF
inputs keep their existing behavior. Temporary copies are removed after success
or failure, and upload is refused if compressed image streams change.
