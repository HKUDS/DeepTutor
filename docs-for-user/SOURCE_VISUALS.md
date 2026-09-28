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
