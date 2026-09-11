# MinerU multi-format integration design

## Context

Issue #1087 correctly points out that current DeepTutor documentation and the
`MinerUParser` adapter expose PDF only, while current MinerU supports PDF,
images, DOCX, PPTX, and XLSX. Merely updating the docs would leave Office files
blocked by the parser adapter and standalone images routed around the parser in
two of the three knowledge-base pipelines.

## Goals

- Expose the exact current MinerU local input set: PDF, PNG, JPEG/JPG, JP2,
  WEBP, GIF, BMP, TIFF, DOCX, PPTX, and XLSX.
- Make those inputs work through the shared `ParseService` in local CLI and
  mineru.net cloud modes.
- Route standalone images through MinerU when MinerU is active, so OCR and
  structured content are available consistently to LightRAG, GraphRAG, and
  LlamaIndex.
- Preserve existing public PDF entry points and exam-paper behavior.
- Fail clearly when the detected legacy `magic-pdf` command is asked to parse
  anything other than PDF.

## Non-goals

- Supporting legacy DOC/PPT/XLS inputs that the current local `mineru` CLI
  does not advertise.
- Changing the PDF-only question/exam upload contract.
- Replacing image-native multimodal ingestion when a non-image-capable parser
  is active.
- Adding MinerU as an in-process Python dependency; the supported deployment
  boundaries remain the external CLI and the hosted cloud API.

## Design

The MinerU engine owns a canonical immutable format set. Its generic adapter
calls a new document-named backend function. The existing
`parse_pdf_to_workdir` and `parse_pdf_with_mineru` functions remain as wrappers
for compatibility with imports, tests, and the exam-paper flow.

The local runner passes every supported source to the modern `mineru -p ...
-o ...` contract unchanged. If auto-detection selects `magic-pdf`, or an
explicit configured executable is named `magic-pdf`, non-PDF input is rejected
before spawning the subprocess with an actionable upgrade message. Output is
still normalized into `<output>/<source stem>` so the cache loader remains
format-agnostic.

The cloud client keeps the same mineru.net v4 batch-upload protocol while
generalizing source names and errors. It sends the original filename, which is
how the service determines the file type, and continues to upload unsigned raw
bytes without a Content-Type header as required by the signed URL.

`ParseService.supports(source, engine=...)` supplies one shared capability
check. GraphRAG routes supported images into document parsing instead of
skipping them. LlamaIndex parses supported images first and uses the resulting
text/assets; when the active engine does not support images, its existing
direct multimodal image-node path is unchanged. LightRAG already calls
`ParseService` for every staged source and needs no routing change.

Static settings copy and documentation are updated to describe the real
format set. Runtime readiness remains separate from format support.

## Error handling and compatibility

- Unsupported suffixes still fail in `ParseService` before readiness checks.
- Legacy `magic-pdf` receives PDFs exactly as before and never receives a new
  input type it cannot handle.
- Existing PDF-named functions are retained and delegate to the generic
  implementation.
- Cache keys remain byte- and parser-signature-based; no migration is needed.
- A parsed image with no textual or structured output is treated as an empty
  parse, matching existing document semantics.

## Verification

- Unit-test the advertised extension set.
- Exercise generic local parsing with an Office input and assert the exact CLI
  argv and normalized output.
- Assert legacy `magic-pdf` rejects non-PDF without spawning a process.
- Exercise cloud submission with a non-PDF filename and archive loading.
- Test GraphRAG and LlamaIndex image routing for both image-capable and
  image-incapable active parsers.
- Re-run the existing MinerU, parsing, and RAG suites, followed by repository
  Python and web quality gates.
