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

## Resuming MinerU cloud PDF slices

Large cloud PDFs are sliced using `engines.mineru.max_pages_per_part` in
Document Parsing settings (default 180; clamped to 1–200). This advanced setting
is preserved when saving the legacy MinerU settings form. Local parsing and
small/non-PDF inputs keep their existing behavior.

Merged content-list `page_idx` values refer to the original PDF, including
nested blocks. For example, page index 0 of the second 180-page slice becomes
180. Invalid local indices fail the parse instead of silently mislabeling
source pages. Other per-part diagnostic artifacts retain their original local
numbering and `partNN_` filename prefix.

Completed slice archives are saved under the active workspace's parse cache in
`.mineru-segments/`, outside disposable failed-parse directories. Retrying the
same source and parser settings reuses completed slices; a changed document,
endpoint, model, language, OCR/formula/table setting, or slice size starts a new
checkpoint set. API tokens and signed URLs are never written to checkpoints.
Each archive is SHA-256 checked before reuse; an incomplete or corrupt checkpoint
is downloaded again. Concurrent jobs may still duplicate a cloud request, but
checkpoint writes are atomic. Cache write failures do not fail a successful parse.

These archives contain parsed document content, images, and any source copies
returned by MinerU, just like the normal parse cache. They are retained until the workspace cache is cleared; deleting
`.mineru-segments/` while no parse is running only discards resumable progress.
This change versions the cloud parser signature so older merged page indices
are not reused from the normal parse cache. Existing knowledge-base indexes
need an explicit rebuild to consume corrected pages.
