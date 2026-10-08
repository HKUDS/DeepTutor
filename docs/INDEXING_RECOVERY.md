# Long-document indexing and recovery

Each knowledge base records its latest indexing run in `.indexing-run.json`.
The Files/detail view exposes **Indexing recovery details**, including individual
source outcomes, current phase and phase-local counts, elapsed runtime, time
since output/activity, and time since measurable progress. A phase reaching its
last batch is not proof that the whole index is ready. Unknown work remains
unknown after interruption; it is never counted as a successful document.

`GET /api/knowledge-bases/{id}/indexing-readiness` performs a lightweight parser,
format and embedding-configuration check without downloading models or sending
a provider request. Readiness does not guarantee later downloads, available RAM
or GPU memory, nor a provider's runtime response. Runtime failures retain their
bounded, credential-redacted reasons in the durable run.

Retry uses the existing content-addressed parser cache: source bytes and parser
signature must match, and usable text or blocks must still exist. MinerU cloud
PDF slices reuse only validated checkpoints. Changing embeddings can reuse
parsing, but builds a separate index version for the new embedding signature.
Interrupted stages without a usable checkpoint restart; the journal itself is
not a second cache and does not fabricate partial embeddings.

Cancellation is task-specific and takes effect at a safe boundary. Managed
local MinerU processes also observe cancellation and fail after 600 seconds
without output or 7200 seconds total. Other synchronous engines cannot be
interrupted arbitrarily; cancellation remains pending until they return. A
stalled LlamaIndex executor is barred from overlapping same-process retries
until it actually exits, and cannot publish its candidate after losing ownership.

LlamaIndex rebuilds and incremental additions use fresh version directories.
A candidate stays unpublished until its persisted index reloads, its vectors
validate and a retrieval probe using a stored vector returns a node. Publication
metadata is written atomically. Source changes during indexing reject publication.
A failed or partial candidate does not overwrite a previous queryable version.
Completed and failed sources are reported separately, including partial success.
The durable journal is scoped to the active user/workspace knowledge base;
linked/read-only knowledge bases cannot be cancelled through mutation routes.
