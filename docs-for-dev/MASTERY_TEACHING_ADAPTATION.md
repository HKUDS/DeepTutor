# Mastery teaching adaptation — design

Status: design (not implemented beyond layer 1 evidence)
Scope: how the mastery tutor decides *how* to teach — depth, framing, examples —
from what the learner actually does, and how that adapts over time.

Related code (today):

- `deeptutor/learning/question_profile.py` — question-type signals
- `deeptutor/learning/storage.py` — `mastery_reply_feedback`, learner profile, teaching observations
- `deeptutor/capabilities/mastery/tools.py` — `mastery_status`, `mastery_profile`
- `deeptutor/capabilities/mastery/prompts/{en,zh}/mastery_loop.yaml` — the tutor playbook
- `web/components/space/learning/MasteryStudy.tsx` — study screen, reply likes

Reference (Hermes self-evolution, read-only): `/Users/ceshi/PycharmProjects/hermes-agent`

- `agent/background_review.py` — post-turn fork that decides whether to save/update skills or memory
- `agent/curator.py` — inactivity-triggered maintenance; deterministic lifecycle + opt-in LLM pass
- `agent/curator_backup.py` — snapshot + rollback
- `tools/skill_ledger.py` — per-mutation audit ledger + single-edit rollback
- `tools/skill_usage.py`, `tools/skill_provenance.py` — telemetry and write-origin provenance
- `agent/learning_mutations.py`, `agent/learning_graph.py` — learner-visible "journey"

---

## 1. Problem

The tutor knows *who* the learner is (`learner_profile`) and which teaching moves
helped per knowledge point (`teaching_observations`). It does not yet turn the
learner's **history of questions** into a strategy for the next explanation.

Observed failures (from real sessions):

- Terms are used before they are defined; the learner asks "what does this mean"
  repeatedly.
- A design topic starts from a JSON schema instead of a data-flow skeleton, so the
  learner gets stuck on fields.
- One paragraph introduces a dozen new terms.
- Examples are too abstract, or at the wrong granularity for the learner's level.
- A design task gets rules, then "now design it" — with no skeleton to fill.
- Five blocks are taught, then one quiz; nothing is checked along the way.

These are **strategy** failures, not knowledge failures. They cannot be fixed by
adding more content; they need the tutor to choose a different *approach*.

## 2. Goals / non-goals

Goals:

1. Deterministic, inspectable evidence about the learner's questions and reactions.
2. A per-turn strategy decision the model makes from that evidence — not a rigid
   lookup table.
3. A bounded, reviewable way for the strategy itself to improve over time.
4. Everything reversible and learner-visible.

Non-goals:

- No auto-rewrite of the system prompt or the tutor playbook from a single turn.
- No LLM-judged "learning" without deterministic evidence.
- No claim that adaptation improves outcomes until an ablation says so.

## 3. Current state (implemented)

| Piece | Where | What it gives |
|---|---|---|
| Learner profile | `mastery_status.learner_profile` | prior knowledge, target level, time budget, preferences, teaching strategy, notes |
| Teaching guidance | `teaching_guidance()` | path teaching preferences + per-point observations |
| Question profile | `mastery_status.question_profile` | question-kind counts, dominant kinds, `signals`, recent excerpts |
| Reply likes | `mastery_status.reply_feedback`, 👍 on replies | which explanations the learner marked as good |

`question_profile` is computed deterministically from the learner's own messages
of the path's most recent sessions (bounded, cached). It classifies into:
`definition / mechanism / procedure / comparison / debugging / application / confusion`.

Today the playbook maps each `signal` to a fixed move (e.g. `define_terms` → term
trio). **This document proposes replacing that lookup with a principle the model
reasons from.**

## 4. Architecture: three layers

```
Layer 3  Strategy evolution   (bounded, reviewed, reversible)
         per-path strategy note  ── curator proposes ── review gate ── apply
                    ▲                                              │
Layer 2  Per-turn strategy    model reads evidence + principles, chooses approach,
         (judgment)           records the outcome
                    ▲
Layer 1  Evidence             question kinds · likes · observations · profile
         (deterministic)      immutable inputs, computed server-side
```

The layers are deliberately separated:

- **Layer 1 never changes.** Evidence is a fact, not an opinion.
- **Layer 2 is a judgment.** The model chooses the approach this turn from the
  evidence and a small set of principles. A current explicit request outranks any
  historical signal.
- **Layer 3 is a slow loop.** Only when evidence accumulates does the system
  propose a durable change to *how* it teaches this learner — and only through a
  review gate, with versions and rollback.

## 5. Layer 1 — evidence

Already built, plus two additions:

1. `question_profile` (built).
2. `reply_feedback` (built).
3. `teaching_observations` / `teaching_preferences` (built) — extend the recorded
   vocabulary with *strategy outcomes*, not just "confused / helped":
   - `strategy` = the approach used this block (`framework_first` / `question_driven`
     / `detail_first` / `term_trio` / `worked_example` / `fill_in_template` …)
   - `outcome` = `helped` / `not_helped` / `unknown`
   - `evidence` = a verbatim learner quote (already required by `apply_teaching_updates`)
4. **Strategy usage counters** (new, sidecar — mirrors Hermes `.usage.json`): how
   often each strategy was used on this path, and how often it was followed by a
   like or a "helped" observation. Kept out of learner-authored text.

Invariants:

- Raw evidence is never rewritten by a later pass (Hermes: immutable trajectories).
- Classification is deterministic; no LLM judge at this layer.

## 6. Layer 2 — per-turn strategy (judgment, not lookup)

Replace the `signals → action` list with:

- **Signals** (facts) — still returned.
- **A principle** — the model decides, guided by a short state → approach table:

| Learner state | Approach |
|---|---|
| Unfamiliar domain, task is to design something | **Framework first**: give the skeleton, then fill it in |
| Has strong intuition, one point is unclear | **Question driven**: start from that point |
| Task is to understand an internal mechanism | **Detail first**: smallest example outward |

Additional principles:

- Terms: first appearance gets *definition + role here + whether precise recall matters*.
- At most two new terms per block.
- Examples match the granularity in `learner_profile`.
- Design knowledge points get a fill-in skeleton, not just rules.
- After one connected block, a one-sentence recall check (unscored).

Hard rule that stays hard: the mastery gate (`mastery_grade` / `mastery_assess`)
is unchanged; nothing here grants mastery.

The model records what it chose and whether it worked via `teaching_observations`
(and the learner can like a reply). That record is what Layer 3 consumes.

## 7. Layer 3 — strategy evolution (Hermes-style, bounded)

The durable artifact is a **per-path strategy note**: a short, learner-visible list
of statements about how this learner is best taught. Example:

```
- 先给数据流骨架，再落到字段（证据：2 次“字段太多” + 1 次没听懂）
- 术语用三件套；只对“要精确掌握”的词要求记忆
- 例子用「能看懂、能改写」的代码粒度
```

### 7.1 Lifecycle

```
observe (Layer 1)
   → propose      background review, evidence-gated (≥ N independent signals)
   → review       independent reviewer pass: cites real evidence? contradicts gate/rules?
   → apply        versioned write; snapshot taken first
   → observe      usage + likes feed back
   → stale / archive / rollback
```

### 7.2 Trigger

Mirrors Hermes' background review + curator:

- **Post-turn review (cheap, opt-in):** after a settled study turn, a background
  pass may propose a strategy-note change. It runs under a bounded tool whitelist
  and never touches the main conversation.
- **Evidence gate:** a proposal is only *allowed* when supported by ≥ N independent
  signals (default: 2 observations or 1 like + 1 observation). One hard turn never
  changes the strategy.
- **Idle consolidation (curator):** when the path is idle, stale entries are marked
  stale and then archived; never deleted.

### 7.3 Review gate

An independent reviewer (separate call, separate context) accepts or rejects:

- Rejects if the proposal cites evidence that does not exist, or contradicts the
  gate rules or an explicit learner request.
- Rejected proposals are returned as feedback to the proposer (Hermes: 3 rounds of
  review before acceptance).
- The reviewer is a gate, not a rubber stamp; a rejection is a normal outcome.

### 7.4 Storage (proposal)

New tables in the learning store (one DB, same migration style as
`mastery_reply_feedback`):

```
mastery_strategy_notes (
  path_id, note_id, body, revision,
  status ('active'|'stale'|'archived'),
  created_by ('agent'|'learner'),
  pinned INTEGER,
  created_at, updated_at,
  PRIMARY KEY(path_id, note_id)
)

mastery_strategy_versions (      -- every applied change, for rollback
  path_id, note_id, revision, body,
  evidence_json, review_json, actor,
  created_at,
  PRIMARY KEY(path_id, note_id, revision)
)

mastery_strategy_ledger (        -- JSONL-style audit, content-addressed
  id, path_id, note_id, op, before_hash, after_hash, actor, created_at
)
```

Provenance: `created_by` distinguishes agent-authored notes from learner-authored
ones. **A learner-edited note is never auto-overwritten** (Hermes `skill_provenance`).

### 7.5 Rollback

- Before any mutating pass, snapshot the path's strategy state.
- `rollback` restores a chosen revision (and is itself recorded, so it is undoable).
- Ledger entries are content-addressed so a single change can be reverted.

### 7.6 Safety invariants

- Only agent-created, unpinned notes are touched by the automatic pass.
- Never delete; archive only (restorable).
- Learner-authored edits are out of scope for automation.
- The pass never edits prompts, the playbook, or tools.
- Bounded tool whitelist; no main-conversation mutation.

## 8. Injection

`mastery_status` gains:

```
strategy_notes: [
  { note_id, body, status, pinned, created_by, updated_at }
]
```

The playbook reads `strategy_notes` as **standing guidance for this learner**,
below the current explicit request in precedence. The `question_profile.signals`
section becomes evidence + principle, not a lookup.

## 9. Learner-visible surface

A small "learning strategy" view (mirrors Hermes `hermes journey`):

- See the notes the tutor has learned about how to teach you.
- Edit or delete any of them; a delete archives (restorable).
- See which evidence produced a note.
- "Undo" the last change.

This is the difference between "the agent silently adapted" and "the learner owns
how they are taught".

## 10. API sketch

```
GET    /api/mastery-paths/topics/{path}/strategy            list notes
POST   /api/mastery-paths/topics/{path}/strategy            learner-authored note
PATCH  /api/mastery-paths/topics/{path}/strategy/{note_id}  learner edit
DELETE /api/mastery-paths/topics/{path}/strategy/{note_id}  archive
POST   /api/mastery-paths/topics/{path}/strategy/{note_id}/restore
POST   /api/mastery-paths/topics/{path}/strategy/{note_id}/rollback  restore a revision
GET    /api/mastery-paths/topics/{path}/strategy/{note_id}/history
```

The automatic proposal pass is internal (a background review), not a user-facing
endpoint; the learner can still trigger a manual review from the UI.

## 11. Measurement (required before any "better" claim)

Hermes' report is explicit: completing a self-update loop is not evidence that
downstream tasks improved. Same rule here.

Ablation campaign:

- Fixed, versioned task corpus (knowledge points + prompts), fixed model and
  provider, fixed tools, deterministic where possible.
- Arm A: strategy notes off (signals only). Arm B: strategy notes on.
- Metrics: mastery-gate attempts to pass, learner "I'm lost"/confusion rate,
  like rate, tokens, latency.
- Held-out split; enough repetitions for a confidence interval.
- Report "loop works" and "outcomes improve" as separate claims.

## 12. Migration / compatibility

- All new tables are additive (`CREATE TABLE IF NOT EXISTS`).
- Existing paths start with no strategy notes; behavior falls back to today's
  signals + principle.
- `teaching_observations` gains new keys but keeps the existing shape; old entries
  remain valid.
- The playbook change (lookup → principle) is a prompt edit, trivially revertible.

## 13. Milestones

1. **M1 — principle over lookup** (low risk, immediate): replace the hard signal
   mapping with the state → approach principle; record strategy outcomes.
2. **M2 — evidence completion**: strategy usage counters; `strategy` / `outcome`
   vocabulary in teaching observations.
3. **M3 — strategy notes (read)**: store + `mastery_status.strategy_notes` +
   learner-visible list.
4. **M4 — proposal + review gate**: evidence-gated background proposal, independent
   reviewer, versions, snapshot/rollback.
5. **M5 — ablation**: fixed corpus, on/off comparison, honest reporting.

## 14. Risks

| Risk | Mitigation |
|---|---|
| Strategy note drifts or overfits one turn | Evidence gate (≥ N signals); reviewer; versions |
| Model ignores notes | Precedence rule; notes are short and concrete |
| Learner edits overwritten | `created_by` provenance; automation never touches learner notes |
| Silent bad automation | Learner-visible, reversible; archive not delete |
| Prompt bloat | Notes are capped (e.g. ≤ 6, ≤ 1 line each) |
| False confidence | Ablation before claiming benefit |

## 15. Hermes cross-reference

| Hermes | DeepTutor equivalent |
|---|---|
| `agent/background_review.py` | post-turn strategy review pass |
| `agent/curator.py` | idle strategy consolidation (stale → archive) |
| `agent/curator_backup.py` | path strategy snapshot + rollback |
| `tools/skill_ledger.py` | `mastery_strategy_ledger` |
| `tools/skill_usage.py` | strategy usage counters |
| `tools/skill_provenance.py` | `created_by` / write-origin |
| `agent/learning_mutations.py`, `agent/learning_graph.py` | learner-visible strategy view |
| `BOOK_SELF_EVOLUTION_REPORT.md` limitation | ablation campaign (M5) |
