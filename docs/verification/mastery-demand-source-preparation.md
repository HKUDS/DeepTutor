# Demand-driven source preparation follow-up

Follow-up to #1902, stacked on the source/semantic assessment work in #1953.
This branch adds source delivery and teaching-record safeguards; it does not
replace the existing lesson preparation, retrieval, assessment or registry owners.

## Contract

- The Mastery loop checks the current authorized cached packet before each model
  request. Cache misses and administrative feedback never automatically start
  preparation/model calls. The existing `mastery_prepare_lesson` tool owns paid work.
- A stale/changed packet offers explicit focused preparation on current authorized
  materials; it is not a permanent tutoring refusal or a reason to demand re-upload.
  Access, source identity and unreadability constraints remain enforced.
- Ready partial evidence supports its useful teaching slice. It does not establish
  full objective coverage or independently authorize an arbitrary assessment.
- Explicit successful preparation binds the teaching objective in the current turn;
  advancing the policy objective invalidates that binding. Model-supplied private
  callbacks cannot replace the runtime binder.
- The native pre-request seam also runs on forced finish. Real source failures
  propagate rather than being converted into an empty successful fallback.
- Prepared page pixels are transient, bounded to two views and subordinate to newer
  tool-retrieved images. Other prepared pages remain source anchors, not claims of
  current pixel inspection. Tool pairs and original learner messages are preserved.
- Durable packet markers survive normalization so later turns can replace historical
  packets while keeping the correct archive boundary. No global history truncation
  or additional context router is introduced.
- `mastery_note_explained` revalidates the current source evidence inside its existing
  transaction and records `coverage: partial`, without grades/mastery credit.

The public-delivery quote/receipt enforcement from #1952 remains a separate,
complementary contribution. This branch does NOT claim it proves that explanation
text was visibly delivered. Its generic `explained` navigation stage is retained;
the new coverage field explicitly prevents a full-objective coverage claim.
No Chinese prompts, profile/memory projection features, or user settings changed.

## Evidence

- Cache/demand tests initially failed: 11 failures, one existing tool case passed.
- Real selected-PDF teaching-record tests initially failed twice: unprepared
  teaching was accepted and partial coverage was absent.
- Native request-boundary tests initially failed five times: the hook never ran,
  failures could be bypassed and the durable packet marker was lost.
- The first hook implementation exposed the forced-finish catch swallowing real
  source failures; both ordinary-round and forced-finish paths now preserve them.
- Final targeted suite: **85 passed** across demand preparation, native request
  boundary, and physical source-page/source-guard tests. All model/retrieval responses are deterministic
  fakes; PDF page identity and rendering use synthetic files in temporary stores.
- Additional checks cover same-turn explicit recovery, focus expiry, literal learner
  quotations and archive boundaries, current access revocation, partial teaching,
  unchanged paid-call count, tool image precedence and absence of durable pixels.

An optional broader run had 268 passing tests and two unrelated failures. Both
also fail on the unchanged semantic parent: the cold-start partial-stream timeout/
event-observation test, and a summary test requiring uninitialized `agents.yaml`
in a fresh contribution worktree. No production workaround was added for either.
Ruff and `git diff --check` pass for the changed Python/source/test files.
