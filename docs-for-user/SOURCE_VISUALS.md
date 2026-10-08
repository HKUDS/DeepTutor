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
All supported extracted images are retained, each image is limited to 5 MiB,
and at most two retrieved images are sent in one model continuation. The
document retention count is independent of this model request budget. There is
no document figure-count ceiling or KB-wide 16 MiB manifest ceiling. Unreadable
manifests fail writes explicitly and remain preserved.

Current extraction coverage depends on the selected parser. MinerU can emit
structured PDF figures. PyMuPDF4LLM can emit PDF and EPUB images when image
extraction is enabled, but its Markdown output does not supply page boxes.
The default text only parser and the current Docling adapter do not emit
source image assets. Images that are only vector drawing commands, or pages
that require OCR when no usable OCR engine is configured, may be absent.
Other RAG providers do not yet index this visual manifest for semantic discovery.
Exact visual and PDF page inspection is independent of the embedding engine.

## Exact figures, original pages and coverage

In a KB's Files view, select a document and expand **Source visual coverage**.
It shows retained figures, paginated original-image links, and known skipped,
failed or unverified extraction locations. A parser returning no images never
establishes that a document has no visual information. The report describes
extraction; it does not certify index readiness or every visual in the book.

The existing `rag` tool also accepts `source_path`, `figure`, `asset_id`, `page`,
`region` and `source_hash`. Use `kb_files` to obtain an exact document path.
Figure and table references keep their type and number; English/Chinese labels
are equivalent. A label shared by different sources is ambiguous and requires
selection. For concept discovery, use the existing semantic retrieval and, when
needed, a query in the source language. Keep the resulting document, section,
caption and page together instead of treating a similar figure as a match.

For vector drawings, sparse captions or layout-dependent tables, inspect a PDF
page directly. Exact printed-reference discovery scans only a selected unlocked
PDF, up to 2000 pages; multiple mentions remain page choices. A known page can
be selected independently of that discovery limit. Rendering reads the original
PDF locally, without OCR/model downloads or a cloud call. Full pages preserve
layout; normalized `region=[x0,y0,x1,y1]` crops spend the bounded pixel budget on
more detail. Parser-supplied panel groups on one PDF page resolve to the complete
page. Structured table headers/cells/units and notes remain text evidence when
supplied; the original page is available for verification.

Page inspection supports PDFs up to 512 MiB, with at most 8 million rendered
pixels and 5 MiB image bytes. Locked/damaged PDFs, invalid regions and unreadable
labels have explicit limitations. Other formats retain supported extracted
images and original-document access; PDF rendering is not silently applied to
them. Increased rendering scale does not recover information absent from a scan.

Each explanation includes original pixels and a source location. Captions and
page text are distinguished from observed image facts. Re-retrieve the same
immutable `asset_id` for detailed follow-ups; `source_hash` protects page links.
Compatible reindexing keeps older asset IDs available. Changed or missing sources
are reported, and an old reference is never redirected to new material. Compare
two sources in separate bounded calls. If either evidence cannot be inspected,
select a page/region, clarify the source, or state that a supported comparison
cannot be made. No whole-book image upload or mandatory external enrichment is
required.

Synthetic regression fixtures contain 100 source figures plus vector, structured
table and multi-panel pages. Expected early/middle/late references, Chinese-to-
English figure labels, headers/units/notes, original bytes, ambiguous matches,
unavailable pixels and changed-source abstentions are checked independently of
language-model fluency.


## Source-grounded practice and learning evidence

In Guided Learning, request explanation, practice or review explicitly. An
explanation-only turn need not pose a question; `mastery_note_explained` records
what was taught without granting mastery. Deferring an objective preserves it
as unfinished. For goals that require visual understanding, outline objectives
can declare `required_visual_tasks`: `identification`, `relationship`,
`table_graph` or `comparison`. Generic text scores cannot satisfy those visual
requirements. The objective view shows the remaining independent evidence.

Ask for practice on an exact original figure or page from an attached KB. The
tutor retrieves its pixels, then poses a `mastery_quiz` with a `visual` context.
The question card displays the original evidence and document/page links.
Numbered-label identification, source-backed relationship questions, table or
graph interpretation and bounded two-source comparisons are supported. No
automatic segmentation, invented label masks or generated replacement diagram
is used. A source image that fails to load disables submission while still
allowing the learner to skip or ask for help.

The reference key uses canonical source terminology and a supporting caption,
explanation or page quote. Explicitly verified equivalent terms, including
other languages, can answer the same question. Choice questions distinguish
supported wrong answers; unknown free-text wording asks for clarification
instead of fuzzy keyword grading. Uncertain/conflicting keys, inaccessible or
changed sources, and missing model-input pixels remain ungraded and create no
negative mastery or retention evidence. A figure URL or a declared vision
capability is insufficient: the active loop checks matching image bytes in the
accepted provider request, including actual text-only fallback.

Visible/unknown answer cues are guided practice, with assistance retained and
weaker review evidence. They do not demonstrate independent mastery. A full
page that exposes the reference answer stays guided; a verified original-page
region can support independent interpretation when the answer cue is outside
the view, with the full source retained for reference verification. Recent
assistance, repeated answer-key exposure and help given after a question also
remain distinguishable through the existing retention session boundary.

Use **Review or challenge this assessment** to request source review. Existing
`mastery_repair_question` invalidates a faulty assessment and recomputes its
mastery/error/review effects. Correcting a visual key also requires source
support; a challenge alone never grants mastery. Manual learner overrides retain
their separate provenance. Source/figure identity, objective, task, cues/help,
answer and attempt identity survive restart. A transport retry records one
attempt; a new question records new evidence. Outline replacement preserves
trusted objective identity rather than transferring an achievement by title or
position. Unassessed, explained, assisted and independently demonstrated work
remain distinct.

Regression workflows use independently specified synthetic numbered figures,
relationships and table values, including equivalent-language answers, wrong
choices, ungraded ambiguity, repair, deferral, repeat submissions, outline
replacement, source changes and restart. This supported set provides explicit
recovery for uncertainty rather than promising unrestricted grading of every
image or arbitrary prose answer.

## Token estimates for image requests

When the provider returns usage, DeepTutor uses those reported counters. When
usage is absent, the conversation statistics are marked as estimates. The
fallback counts serialized text at roughly 3.5 characters per token and adds
1,024 tokens per structured image block. It excludes image URLs and Base64
payloads from the text estimate, so the encoded file size does not inflate the
counter into millions of tokens.

The image allowance is a rough placeholder, independent of resolution, detail,
model and provider; it is not a billing calculation. Each model call in a turn
still counts its own input, including any replayed images. Existing stored
estimates are not rewritten by this change, and conversation content is kept.

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

## Retrying local MinerU documents

Local MinerU retries restart the interrupted document from its beginning;
the CLI does not expose a reliable checkpoint inside an inference call.
Compatible completed document parses remain reusable after retry or restart,
including when only the embedding configuration changes. Empty or unreadable
cached output is reparsed rather than accepted as complete.

New local output is checked for usable markdown or content blocks before it
replaces an existing parse. Failed attempts retain their artifacts for
diagnosis. Within the workspace parse cache these are moved to hidden
`.failed-` directories beside the affected signature, outside the next retry's
working directory. They are never treated as completed cache entries. Clearing
the workspace parse cache also removes these diagnostic artifacts. An interrupted
local child process is stopped before the caller starts another attempt.

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
and cache complete, successful groups separately from independent single-image
captions. The digest includes ordered image contents and metadata, prompts,
model identity, and retry policy. Failed, incomplete, or canceled groups are
not cached; successful split groups can be reused. Setting the size
back to `1` restores the normal single-image path. The model must support
multiple image blocks; unsupported API responses are reported without a burst
of fallback requests.
