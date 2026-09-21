# Knowledge migration guide

This guide covers moving existing notes from Obsidian, Hermes, or another
Markdown-based tool into DeepTutor. It matches the v1.6.0 Knowledge Center.

## Choose a migration path

| Path | What DeepTutor keeps | Best fit | Trade-off |
| --- | --- | --- | --- |
| Connect an Obsidian vault | A live pointer to the vault | Continue using Obsidian as the source of truth | The vault is not copied into a vector index, so it is not a RAG corpus |
| Import an indexed knowledge base | Markdown and other supported files copied into `raw/`, then indexed | Search a copied corpus with the selected retrieval engine | Later changes in the original notes are not automatically imported |

DeepTutor has no dedicated one-click Hermes importer. Export Hermes notes as
Markdown and follow the imported knowledge base path. Check the export in your
note tool first; DeepTutor does not convert proprietary formats.

## Prepare the source

1. Make a complete backup of the source vault or export before connecting or
   importing it.
2. Export notes as `.md` or `.markdown`. Include linked image and document
   assets when your note tool offers that option.
3. If the app exports HTML or another format, convert it to Markdown outside
   DeepTutor, inspect a sample, and verify that links and attachments still
   resolve.
4. Choose one of the two routes in the table above. You can use both: connect
   the live Obsidian vault for note work, and import a copy when you want a
   retrievable index.

## Connect Obsidian

Use this path when Obsidian remains your primary editor and you want DeepTutor
to browse and add to the same notes.

1. In DeepTutor, open **Knowledge Center**, choose **Create KB**, then select
   **Link existing** and **Obsidian**.
2. Enter the absolute path to the vault folder that the DeepTutor server can
   reach, for example `/Users/example/Documents/MyVault`. Do not enter a path
   from another machine.
3. Give the knowledge base a distinct name and connect it.
4. Select that KB in Chat. Obsidian tools then operate on the selected vault.

DeepTutor creates a pointer rather than an upload or index. It recognizes
Markdown notes, follows vault links and tags, and ignores `.obsidian`,
`.trash`, and `.git` internals. Writes are additive: notes can be created,
appended, or given frontmatter properties, but the assistant does not delete or
rewrite existing note bodies. Deleting the knowledge base removes only the
DeepTutor pointer; the vault remains untouched.

For a self-hosted container, mount the host vault so the same path is visible
inside the server container, then connect the server-visible path. A path valid
only on the host is not enough.

To get semantic retrieval over a copy of Obsidian notes, import that copy as a
separate indexed knowledge base. Keep the connected vault for live editing so
the two uses stay clear.

## Import Markdown or Hermes notes

Use this path when you want a copied, indexed corpus. The source notes stay in
their original location.

### Web

1. Export the notes and assets to a local Markdown folder.
2. In DeepTutor, open **Knowledge Center** and choose **Create KB**.
3. Select **Create new** and a retrieval engine. LlamaIndex is the default;
   choose another engine only when its trade-offs fit the corpus.
4. Upload files, a folder, or a `.zip` archive.
5. Wait for parsing and indexing to finish, then confirm a few representative
   notes are retrievable before deleting any source backup.

A **folder upload** preserves its relative directory structure. A `.zip`
archive is expanded defensively: nested directories are flattened, unsupported
members are skipped, hidden and system entries are skipped, and duplicate
basenames after flattening are skipped. Prefer a folder upload when note titles
repeat in different folders or the folder hierarchy is meaningful.

The upload UI reports the supported extensions and per-file limit. The current
Markdown extensions are `.md` and `.markdown`; other supported text, document,
spreadsheet, presentation, EPUB, image, and source formats are accepted by the
same upload policy.

### CLI

From an export directory:

```bash
deeptutor kb create hermes-notes --docs-dir /path/to/hermes-export
```

For a single file or later additions:

```bash
deeptutor kb create one-note --doc /path/to/note.md
deeptutor kb add hermes-notes --docs-dir /path/to/more-notes
```

The CLI recursively collects supported files from `--docs-dir`, then copies
each matched file into the top level of the KB's `raw/` directory. Because a
duplicate filename can overwrite an earlier copy, prefer the web folder upload
when filenames repeat or hierarchy is meaningful. Use `deeptutor kb list` and
`deeptutor kb info hermes-notes` to confirm creation and document counts.

## Verify the migration

- Open a small, medium, and deeply nested sample note and check that text,
  links, and asset references remain readable.
- For an indexed KB, run representative searches for exact note names, phrases,
  and concepts. Confirm the cited source points to the expected note.
- For Obsidian, search a note, follow a link or backlink, create a scratch
  note, and then delete that scratch note from Obsidian.
- Keep the original backup until retrieval quality and asset references are
  confirmed.
