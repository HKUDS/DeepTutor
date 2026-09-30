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

## Optional image-description batches

The existing LlamaIndex image-description pass can send multiple images per
vision request. Set `image_description_batch_size` through
`PUT /api/knowledge-bases/rag-pipelines/llamaindex/config`, for example:

```json
{"image_description_batch_size": 4}
```

The default is `1`, preserving individual requests; accepted values are clamped
to 1–8. Concurrency limits count batches when enabled, and the existing timeout
covers the whole batch including any split attempts. Returned captions are
matched by explicit IDs, never by response order. Malformed JSON/ID maps and
explicit context overflow split into smaller groups, eventually using the
existing single-image prompt. A group of N images makes at most 2N−1 completion
calls, with provider retries disabled for this mode. Authentication and rate
limits stop queued groups in the job; other API/transport errors do not split.

This only affects subsequently processed images in the existing LlamaIndex
description pass. It does not enable descriptions for structured source visuals
or alter reading-material captions. Batches use a different structured prompt
and do not reuse the independent single-image caption cache. Setting the size
back to `1` restores the normal single-image path. The model must support
multiple image blocks; unsupported API responses are reported without a burst
of fallback requests.
