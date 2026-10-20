# Source-bound semantic assessment

This contribution is stacked on `contrib/mastery-grouped-assessment` at
`6532c8c2` (PR #1943). It ports selected assessment symbols from the local
integration workspace, not whole shared service/tool files.

## Guarantees

- Exact verified choices/equivalents stay local. Other answered free-form
  leaves share one bounded semantic request, using original authorized PDF
  pixels when needed; image fallback is disabled.
- Question contracts bind objective, question, options, key, rubric and fresh
  source evidence. Citation quotes must exist. Original-exam provenance is
  conservative; choice keys are not inferred from an isolated letter.
- Await happens outside the store transaction. Commit rechecks the original
  interaction/answer/objective fingerprint, lifecycle, source access and digest.
- Provider errors write no grade. Uncertain answers are nonfinal and may be
  explicitly revised; final siblings cannot be changed. Group children do not
  create additional active-question rows or duplicate mastery credit.
- Partial is distinct from incorrect in attempts, evidence, scheduler quality,
  question-bank entries, native cards and tutor seeds. Corrections reassess the
  saved raw learner answer, discard old key-derived aliases and repair receipts.
- Qualitative assessment uses the actual runtime learner message, never the
  model's passed flag. Native selected-model ContextVar routing is retained.
- Single and grouped grading failures emit recovery events, preserving drafts.

## Source dependencies

`lesson_evidence.py` supplies actual preparation, bounded targeted repair,
validated cached full/partial packets and selected-source scope. `source_pages.py`
supplies physical locators, hashes, bounded rendering and legacy BM25 page
sidecars. Four small LlamaIndex owner changes preserve physical PDF documents,
persist page catalogs and scope retrieval before searching. No alternate
renderer, fake verification flag, OCR migration or global model override exists.

The explicit `mastery_prepare_lesson` tool is registered and mounted. The
automatic cache-delivery pipeline and taught-state source guard are a separate
stacked source-preparation follow-up, not silently copied into this slice.
Tests specific to those unported owners and the separate legacy URL alias
migration are intentionally not included. New references use native route
parameters `source_path`, `source_hash`, `page`, `region`.

## Validation

All tests use temporary synthetic records and offline provider stubs. No learner
data was changed; no backend restart or provider-cost call was made by this port.

- Initial root RED: missing semantic implementation; longer correct paraphrase,
  nonfinal revisions, partial outcomes and provider failure contracts failed.
- Additional RED: single-card runtime failure variants produced zero recovery
  events (3 failed, 3 passed); after fix runtime suite **20 passed**.
- Additional RED: qualitative question-bank result argument was missing (2
  failed); after fix root semantic suite **20 passed**.
- Native backend: semantic assessment, source bridge, source pages, visual
  workflow, mastery tools, group runtime and capability suites **280 passed**;
  after adding the two qualitative-bank regressions the affected semantic/tools
  suites **100 passed**.
- Native DOM: `npm run test:unit -- tests/mastery-question-group.spec.tsx
  tests/question-bank-picker.spec.tsx` **20 passed**. Covers uncertain leaf
  revisions, final sibling locks, single clarification retry and typed badges.
- Native `npm run typecheck`: passed.
- Scoped Ruff and `git diff --check`: passed.

Parent review separately ran two controlled model probes: four text decisions
and one original synthetic-pixel table decision. Those integration observations
are not substituted for the deterministic regression suite above.

## Port boundaries

Service: grade/evaluate/repair/qualitative paths, group merge/result/leaf paths,
question registration/answer revision, evidence update and mastery calculation.
Tools: prepare/quiz/grade/assess/repair and qualitative-bank projection only.
Loop: raw-message injection for those tools and `_grade_seed` only. Runtime:
`_grade_submitted_card_answer` failure projection only. UI: typed result helpers,
cards, receipt/rejection projection, bank badges and six partial translations.
Profile, intake, memory, broad teaching guidance and delivery recovery edits
remain in their separate contributions.

## Practice-card interface follow-up

The quiz schema and grouped finish nudge now accurately allow practice cards for
all objective types. Both single and grouped CONCEPT / DESIGN cards explicitly
retain the separate qualitative gate. No credit policy was changed. A new
three-case regression first failed on the obsolete descriptions/missing grouped
notice, while already proving six correct concept/design attempts did not open
either gate. After the wording fix: root concept-contract/tools suites 83 passed;
native concept-contract/runtime/capability suites 101 passed; scoped Ruff and
diff checks passed.
