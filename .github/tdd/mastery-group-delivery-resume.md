# Grouped-card delivery and exact pending-card resume

## Reproduction

The finish guard recognized `1. A question?` but allowed `### 1. Topic`
followed by a question in the next paragraph. A reply could solicit several
answers without calling mastery_quiz. Existing pending cards also lacked a
direct re-presentation action, encouraging reconstruction in prose.

Tests use generic synthetic topics and isolated stores. No private learner
transcript, external provider inference or live learning-state edit is included.

## RED / GREEN

RED checkpoint 7e16a93a: 10 intended failures, 11 passes on the clean contribution.
The root integration additionally reproduced the original captured shape before
the fix, without exporting its content.

GREEN on the clean contribution: 131 focused tests in 18.53s (21 delivery,
31 grouped interaction, 79 existing capability neighbors). Separate root
source-integrated scope: 137 passed in 25.89s. Counts overlap and are not
coverage percentages or a global-suite assertion.

One actual MessageList DOM test passed in clean and root worktrees: resumed
card and cumulative partial-grade receipt in one new message restore the saved
answer/graded lock with older history absent, keep the remaining item editable,
submit only that item and filter private extra fields. Existing frontend
behavior is reused; no new production UI surface is added.

## Invariants and review

- Exact current parent ID and eligible status are checked inside register_question.
- Historical/stale/answered/terminal IDs and fresh-contract/resume conflicts reject.
- Existing replies, results, question identity and credit are preserved.
- Committed but ungraded answers require grading first; no invented UI verdict.
- Stored partial results replay through a public-field allowlist, not private keys.
- Explicit assessment intent plus multiple question-bearing numbered blocks
  triggers correction; ordinary explanations and quoted/code examples do not.
- The same existing card builder, delivery callback and tool metadata are used.

Independent state/security review found no blocking issue. The separate local
preparation bridge validates remaining saved source snapshots; that bridge is
not copied into this native contribution.

## Limits

The textual guard is defense in depth, not universal semantic intent detection.
This fixes registered delivery/resumption, not question selection from a requested
reference bank, semantic answer grading, or all model teaching decisions.
No live-model benchmark, full coverage or billing-savings claim is made.
