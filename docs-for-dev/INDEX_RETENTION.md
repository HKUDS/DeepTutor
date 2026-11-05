# Index version retention and catalog latency

Full LlamaIndex rebuilds publish immutable `version-N` snapshots. Keeping every
snapshot indefinitely increases storage use and the work done by catalog probes.
Splitting original PDFs does not address this catalog cost.

In the knowledge-base detail page, open **Index versions → Clean up old index
versions**. Preview the count and reclaimable space, then confirm deletion. The
operation keeps the two newest published snapshots **per embedding signature**,
including signatures belonging to previously selected models. Raw documents,
unknown/legacy/non-LlamaIndex layouts and unfinished candidates are untouched.
Version names found in saved account/workspace SQLite conversation and learning
records are conservatively protected across all KBs. Unreadable history fails
closed. Exported references outside these stores are not discoverable; retain
their versions using the offline command's `--protect-version` option instead.

Cleanup shares a cross-process lease with LlamaIndex indexing and retrieval. A
busy KB rejects cleanup; another operation cannot start during deletion. A
preview fingerprint is checked again at confirmation, so changed versions or
saved references require a new preview. Cleanup is manual, not an automatic
side effect of listing, rebuilding or upgrading.

For offline maintenance, stop API workers, partners and indexers first:

```bash
python scripts/prune_kb_versions.py /path/to/knowledge_bases/example
python scripts/prune_kb_versions.py /path/to/knowledge_bases/example --protect-version version-3 --apply --offline
```

The offline command does not discover saved references automatically; supply
`--protect-version` for pinned snapshots or use the history-aware UI. Back up the
data directory before permanent removal. Do not delete entire `.deeptutor`
directories: they contain application data, not just caches.

The docstore-count cache is enabled automatically and retains up to 4096 integer
counts keyed by path, size and modification time. It retains no JSON payloads.
Newest-ready probes stop after finding a usable version, and scoped catalog
queries avoid opening unrelated workspace managers. These changes address both
the initial scan and cache thrashing when more than 128 versions are present.
