---
title: Immersive Reading
description: Read documents or media beside the thread — verified citations jump to source units or transcript timestamps, explicit navigation can highlight quotes, and PDF highlights export as real annotations.
quadrant: how-to
---

Immersive Reading puts documents or media beside the conversation. The assistant cites **source units** — PDF pages, EPUB chapters, slides, or extracted sections — as `[p.N]`; timed media uses transcript timestamps such as `[MM:SS]` or `[H:MM:SS]`. Verified document locators become links that switch material and jump to the source; quote highlighting uses `reader_goto`. Media tutoring relies on transcripts, not video frames. Without a transcript, playback still works, but the assistant cannot ground explanations in the spoken content.

It is a capability, not a separate app: everything Chat can do still works in a reading turn.

## Where it is

Open **Learning → Immersive Reading** from the sidebar (or visit `/learning/reading`). Its route opens a **collection** library; open one to place its material beside the reading companion.

![Reading collections](/screenshots/dev/reading.png)

The companion is Home's chat surface assembled for reading: it reuses the message list, composer, Activity drawer, and conversation outline instead of maintaining a separate chat implementation. Only the open material, selection, linked conversations, and page-aware prompt stay local.

Create a **New collection** with one or several materials, or reopen one. Materials appear as tabs; switching tabs moves the reader and the assistant's active source together, and you can add more without leaving.

Materials are stored per user and content-addressed, so adding the same source again can reuse one copy of the extraction and keep the marks you already made on it.

Web links are cleaned into stored snapshots rather than rendered as a live third-party page. A refetch creates an immutable prior revision, and captured images are served back through authenticated, MIME-checked asset routes. That keeps old citations reviewable even after the source site changes.

| | |
| --- | --- |
| **Accepts** | PDF, EPUB (including browser-zipped `.epub.zip` folders), Word, spreadsheet, slide, Markdown, text, and HTML files; audio and video files; and links to web pages, YouTube, or Bilibili — not standalone images |
| **Size limit** | 200 MB per document |
| **Faithful source view** | PDF and EPUB keep their source views; audio and video use media players; other formats use reflowable extracted text |
| **Not accepted** | A scanned, image-only document. It is rejected with an explanation instead of opening as an empty reader — run it through OCR first, or index it in a knowledge base with a parsing engine that does OCR. |

## Reading with the assistant

Once a material is open, ask about it. Resize the navigator, reader, and companion to suit the task; panel widths are remembered. Companion focus gives the conversation extra room while keeping the material alongside it.

![A demonstration primer open in Reading](/screenshots/dev/reading-detail.png)

Three things make the answer grounded rather than merely confident:

- **The assistant addresses the document the way you do.** A PDF keeps physical pages, an EPUB keeps its spine and chapters, slides keep their positions, extracted formats use sections, and media uses timed transcript segments. Every unit has a **locator**, and every tool takes or returns one — page numbers are literal for PDFs, while other formats use their own source-aware position.
- **A reading turn keeps the whole chat surface.** Web search, code execution, and your other knowledge bases are still there; the eight reading tools are *added* to them, never substituted. Comparing what a paper claims against what the web says is one turn, not two.
- **Grounding does not depend on the model choosing to read.** Before the model runs at all, DeepTutor runs your own question against the open document and hands the top hits to the turn. Weak models under native tool calling often never call a read tool; this way they still start from the right source unit.

That pre-pass is a plain search, so it adds no extra LLM round. Its deterministic retrieval behavior can be tested directly.

### What the assistant can actually do

| Tool | What it is for |
| --- | --- |
| `reading_list_tabs` | List the materials in the current collection, including which tab is active and each source's status. |
| `reading_switch_tab` | Switch the active material tab before the assistant reads or compares another source. |
| `material_outline` | A format-aware document outline, including PDF bookmarks and EPUB navigation or spine titles. |
| `search_material` | Full-text search over the open document. Every hit already carries its locator. |
| `read_material` | Read specific units in full, by locator. |
| `view_figure` | Inspect one named stored figure through a vision model when its caption is not enough. |
| `reader_goto` | Scroll *your* reader to a locator and highlight a quote there. |
| `reader_annotate` | Leave a highlight or note on a verified passage, as the assistant. |

Search is layered cheapest-first and reports which layer fired, so the model can tell a verbatim hit from a loose one: `exact`, then `normalised` (whitespace collapsed and punctuation-insensitive, so a quote copied out of a PDF still matches text that wrapped mid-phrase), then a term-overlap ranking that keeps a natural-language question from returning nothing.

The outline jumps by structure, places your saved bookmarks above the document outline, and remembers the last locator or EPUB position. Previous/next controls show the exact unit being entered, while extracted text reports its current font scale and line width alongside persistent typeface and colour controls. Optional Reading extensions receive only verified visible text or selections, run within bounds, and return structured results.

:::note
`reader_goto` moves the reader even when the quote cannot be verified at that locator — asking a question in Chinese about an English paper produces a translated quote that will never match, and refusing to scroll would make the reader useless in exactly that case. Annotation stays strict: a mark is only written where its quote really is.
:::

## Marking up as you read

Select a passage to highlight or underline it and optionally attach a note to that quote. Marks come in five colours and two visual styles, and the list between the reader and the thread indexes them by locator — page, chapter, slide, or section.

Selecting a passage also makes it the subject of your next message, so "explain this" means *this*, without quoting it back.

### Taking your marks with you

Export from the reader's toolbar:

- **Annotated PDF** — the original file with *real* PDF annotations written into it. It opens with the highlights intact in Preview, Acrobat, or Chrome, so your reading survives leaving DeepTutor. Available for documents that kept their original bytes, which today means PDFs.
- **Markdown** — the marks themselves in locator order, each with its quote and note. Works for every format, and is what you actually want to paste into your own notes.

## How it fits the rest of DeepTutor

- **A reading material is not a knowledge base.** Nothing is chunked, embedded, or indexed. A document lives in a few hundred unit files, and a linear scan of that is milliseconds — with the advantage that every hit keeps its exact source locator, which a vector store does not.
- **Reach for a knowledge base instead** when you want one question answered across many documents, or when you want the material to stay available to Book, Learning notebook, and Partners. Reach for Immersive Reading when you are reading *this* document and want its current page, chapter, slide, or section preserved — including real physical page numbers for PDFs.
- **Reading conversations belong to their workspace.** They group under that workspace in the sidebar, and reopening one returns to `/learning/reading/<workspaceId>/sessions/<sessionId>` so the reader, active material, outline, and citations stay attached instead of being dropped on Home.

## CLI

```bash
deeptutor run immersive_reading "Summarise the method section"
```

The mode is available on the CLI (aliases `reading` and `read`), but the reader is a web surface — a CLI turn has no viewport to scroll and no selection to act on.

## Keep collection and workspace separate

A reading collection belongs inside the selected content workspace. Create a collection such as `Week 3 — spectral analysis`, add the lecture PDF and a related article, then open a material. Ask “What assumption justifies the step on this page?” or select the actual passage. Keep source navigation and citations visible while checking the answer. A collection can have several conversations without becoming another top-level workspace.

Use Favorites to preserve a useful result, and the Learning notebook to write your synthesis. For a video, check that its transcript is available before asking about its spoken argument. Changing a media tab changes the active material; it does not give the tutor visual access to video frames. If you want a planned route through the topic, hand the clarified goal to Mastery Path.

## See also

- [Home](/learning-workspace/chat/) — the loop this capability runs on
- [Knowledge Center](/learning-workspace/knowledge/) — index a corpus instead of reading one document
- [Resources](/learning-workspace/resources/) — save what you found into a notebook
- [Server API](/developers/reference/http-api/#immersive-reading) — the `/api/reading` surface
