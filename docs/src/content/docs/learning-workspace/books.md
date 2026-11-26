---
title: Books
description: Compile your knowledge bases, notebooks, question banks, and chat history into interactive living books — with quizzes, animations, interactive widgets, diagrams, and a per-page chat.
quadrant: how-to
---

Interactive Book turns your materials into a **living book** — not a static PDF, but a reading environment built from typed blocks you can quiz against, watch as animation, manipulate as a live widget, and chat about page by page.

## Where it is

Open **Learning → Books** from the left sidebar. Personal books and permitted admin-shared books appear together. Learner accounts need explicit Books access; shared titles also require book permissions. **New book** appears only when personal creation is allowed.

![Books in the active workspace](/screenshots/dev/books.png)

## Creation flow

1. If **New book** is available, open **Book → New book**.
2. Choose a **topic** and **sources** — Knowledge Bases, Notebooks, Question Bank, or Chat history.
3. Review the generated **proposal** (chapter outline) before compiling. The editor shows a **live per-chapter cost estimate** derived from the compiler templates and updates it as you add, remove, or retype chapters. Choose which generated content types are allowed, then select **Generate all chapters** or **First chapter only** — only the former queues the whole spine.
4. Let the engine generate page plans and blocks per chapter.
5. Read, annotate, quiz yourself, or chat alongside the pages.

Compilation outlives the request that starts it: `confirm_spine` returns as soon as the page shells exist while the work it queued runs for minutes, and the event stream is owned per *book*, so you can watch the book being written and it survives a refresh or a reconnect.

Books track source **fingerprints**, so if a knowledge base changes after compilation, maintenance commands can report the drift (see below).

## The reading experience

A book chapter is built from **typed blocks**. The point is that each block is the *right* medium for the idea — a concept becomes a quiz, a derivation becomes an animation, a process becomes an interactive widget.

**Quiz & flash-card blocks** turn a section into active recall. Answers stay hidden until you reveal them, and the per-page outline on the right keeps long chapters navigable.

![Book page with a quiz](/screenshots/dev/book-quiz.png)

**Animation blocks** embed a rendered visual right in the page — including Manim video when the add-on is installed — useful when a derivation is easier to *watch* than to read.


**Interactive blocks** are live HTML widgets. Here, a slider changes the sampling-frequency ratio in real time — the reader learns by manipulating the model, not just reading about it.

Figure and interactive blocks use the same `deeptutor.visualization/v1` result envelope and sandboxed viewer as Home's Visualize capability. That keeps SVG, Mermaid, charts, and HTML interactions consistent between generated pages and standalone visualizations.

![Interactive book page](/screenshots/dev/book-widget.png)

**Diagram blocks** render Mermaid/concept graphs inline, and every page has a **Page Chat** — ask a question about exactly what you're reading and get an answer grounded in that page.


Visited pages, bookmarks, and quiz attempts roll up into a completion score and weak chapters. Select a passage to send it to a reviewable **Learning capture inbox**, where you approve or reject what should become study material. Any book exports to Markdown. Pausing a long compile persists first, cancels queued and in-flight work, and keeps completed pages; refreshes and restarts stay paused until you explicitly resume.

For an admin-shared book, the canonical chapter content stays in the admin workspace while each reader's progress, bookmarks, quiz attempts, learning captures, and Page Chat links remain private in that reader's workspace.

## Authoring and customizing

Personal books and shared books with **edit** access are editable, not frozen. Use **Insert block** to add a block anywhere in a chapter — and pick its type from the full palette: text, callout, quiz, code, timeline, flash cards, figure, interactive, animation, deep dive, and user note. Read-only shared books omit these authoring controls.


With edit access, hover a block to **move, regenerate, delete, or switch type**. **Edit text** appears only for text and callout prose; user notes have their own editor, while structured blocks must be regenerated. Shared edits use revision checks: refresh after a collaborator wins a conflict. Shared deletion remains admin-only.


## Good source choices

| Source | Use when |
| --- | --- |
| **Knowledge Base** | You want grounded textbook/paper content. |
| **Notebook** | You have curated notes or prior summaries. |
| **Question Bank** | You want practice-centered pages. |
| **Chat History** | You want to turn a tutoring session into study material. |

## Maintenance

```bash
deeptutor book list
deeptutor book health <book_id>
deeptutor book refresh-fingerprints <book_id>
```

## Scope and a useful first book

Books live in the selected workspace. Create `Probability essentials`, select the lecture KB and saved records you actually want it to use, and inspect the chapter spine before compiling. Start with the first chapter when you want to check depth, notation and source coverage before generating the whole book. Read a page, ask its tutor about one unclear step, and keep a concise explanation in Favorites. Use Practice for recall and Mastery Path when your goal is demonstrated ability rather than finishing pages.

Source pickers may retain **Notebook** terminology for saved Favorites collections. These are distinct from the editable Learning notebook at `/co-writer`. A generated book is a new authored resource; source selection does not guarantee every statement is correct. Review citations and compare important claims with the originals.

## See also

- [Knowledge Center](/learning-workspace/knowledge/) — build the document libraries a book is compiled from
- [Home](/learning-workspace/chat/) — discuss book pages in context
- [CLI commands](/developers/reference/cli/) — book maintenance commands
