# Solve Module - Context Engineering Audit

This document audits the current `src/agents/solve/` pipeline from a context-engineering perspective. It explains what each LLM call sees, how information flows through the system, and where compression or missing context may affect quality.

## 0. Architecture Overview

```text
Pipeline: Plan -> ReAct -> Write

Phase 1: PlannerAgent.process()          -> plan
Phase 2: SolverAgent.process() x N       -> entries
Phase 3: WriterAgent.process()           -> final_answer
          WriterAgent.process_iterative() -> detailed + concise answer

Memory: Scratchpad (plan + entries + sources + metadata)
```

## 1. PlannerAgent

### When it is called

- at the beginning of solving, for the initial plan
- later, when `SolverAgent` emits a `replan` action

### Main context fields

| Context slot | Source | Description | Static or dynamic |
|--------------|--------|-------------|-------------------|
| `system_prompt` | `prompts/en/planner_agent.yaml` | role, rules, JSON output format | static |
| `question` | `MainSolver.solve(question)` | full user question | dynamic |
| `tools_description` | `ToolRegistry.build_planner_description()` | available tool descriptions | dynamic |
| `scratchpad_summary` | current scratchpad state | empty on the first plan, summarized progress on replans | dynamic |

### Main strengths

- Minimal context on the first call keeps planning focused
- Tool descriptions are injected explicitly
- Replanning can use compact summaries of previous work

### Main gaps

- No prior multi-turn dialogue history
- No explicit knowledge-base metadata
- No personalization injected at planning time
- Replanning relies on compressed `self_note` summaries rather than full observations

## 2. SolverAgent

### When it is called

- once per ReAct round for each plan step, up to `max_react_iterations`

### Main context fields

| Context slot | Source | Description |
|--------------|--------|-------------|
| `system_prompt` | `prompts/en/solver_agent.yaml` | action schema and decision rules |
| `question` | original user input | repeated every round |
| `plan` | `Scratchpad._format_plan()` | full plan with step statuses |
| `current_step` | current `PlanStep` | current sub-goal |
| `step_history` | `Scratchpad.build_solver_context()` | full current-step history, including observations |
| `previous_knowledge` | `Scratchpad.build_solver_context()` | compressed notes from previous steps |

### Compression behavior

- `step_history` for the current step keeps full observations
- `previous_knowledge` is compressed with `self_note`
- when token pressure increases, previous-step summaries are reduced further

### Main strengths

- The current step has access to raw tool outputs
- Cross-step knowledge is preserved through `self_note`
- The agent can decide whether to continue, finish, or replan

### Main risks

- Current-step history has no hard compression cap
- The full question and plan are repeated every round
- Code observations may include long code blocks and long outputs
- There is little quality signaling about whether retrieved evidence is strong or weak

## 3. WriterAgent

WriterAgent has two practical modes:

- **Simple mode**: one call that writes the final answer directly
- **Iterative mode**: multiple draft-building calls plus one concise-answer pass

### Simple mode context

| Context slot | Source | Description |
|--------------|--------|-------------|
| `system_prompt` | `writer_agent.yaml` | formatting, structure, and citation rules |
| `question` | original user input | full question |
| `scratchpad_content` | `Scratchpad.build_writer_context()` | plan and selected entries |
| `sources` | `Scratchpad.format_sources_markdown()` | deduplicated citation list |
| `preference` | `MemoryReader.get_writer_context()` | memory-based preference summary |
| `language` | config | output language |

### Iterative mode context

Each draft round uses:

- the original question
- the previous draft
- new evidence for the current step
- the source list
- the output language

The final concise pass uses:

- the original question
- the detailed draft
- the output language

### Main strengths

- Writer context has token budgeting and progressive compression
- Iterative drafting reduces the need for one giant single-shot prompt
- Simple mode can inject personalization

### Main risks

- Iterative drafts can grow continuously and exhaust context
- Iterative mode currently omits the preference injection used by simple mode
- Source lists are repeated across iterative calls
- Step evidence can still be very large if an observation is long

## 4. Code Generation

When SolverAgent chooses `code_execute`, `MainSolver._generate_code()` triggers another LLM call.

### Current context

| Context slot | Source | Description |
|--------------|--------|-------------|
| `system_prompt` | hard-coded prompt | Python code generation instructions |
| `user_prompt` | solver `action_input` | natural-language description of the intended code |

### Main issue

Code generation gets much less context than the main solve loop:

- it does not see the full question
- it does not see the current step goal explicitly
- it does not see prior evidence unless that information was packed into `action_input`

## 5. Scratchpad

### Structure

```text
Scratchpad
├── question
├── plan
│   ├── analysis
│   └── steps[{id, goal, tools_hint, status}]
├── entries[{step_id, round, thought, action, action_input, observation, self_note, sources, timestamp}]
└── metadata{total_llm_calls, total_tokens, start_time, plan_revisions}
```

### Compression levels

| Level | Typical use | Kept content | Discarded content |
|-------|-------------|--------------|-------------------|
| `L0` | current solver step | full entry | nothing |
| `L1` | normal writer context | plan + action + observation + self_note | thought |
| `L2` | previous-step knowledge | step goal + self_notes | observation, thought, action_input |
| `L3` | over-budget fallback | pipe-separated self_notes | most other details |

### Token budgets

| Scenario | Budget |
|----------|--------|
| `build_solver_context` | about 6,000 tokens |
| `build_writer_context` | about 12,000 tokens |
| observation truncation | based on `solve.observation_max_tokens` |

## 6. External Context Sources

### Tool observations

- `rag_search`: retrieved answer text plus source metadata
- `web_search`: synthesized web answer plus URLs and titles
- `code_execute`: code, stdout/stderr, and artifact paths

### Personalization

- Injected into `WriterAgent.process()` through `MemoryReader.get_writer_context()`
- Not currently injected into `PlannerAgent`
- Not currently injected into `SolverAgent`
- Not currently injected into iterative writer calls

## 7. Main Improvement Areas

### Redundant context

- the full question is repeated in every solver round
- the full plan is repeated in every solver round
- iterative writer calls repeatedly include large source lists

### Missing context

- code generation lacks broader problem context
- the planner does not know much about KB structure or available document types
- iterative writer calls do not include personalization
- the system has no built-in multi-turn dialogue history for follow-up questions

### Compression risks

- current-step history may become too large
- iterative drafts can grow without enough pruning
- aggressive compression may remove details the writer still needs

## 8. Why `self_note` Matters

`self_note` is the key bridge between steps. It is currently the main compact signal passed from:

- SolverAgent to later SolverAgent steps
- SolverAgent to PlannerAgent during replanning

Its quality directly affects plan revisions, cross-step continuity, and information retention.

## 9. Typical Token Pattern

For a representative medium-complexity problem with 3 plan steps and about 2 ReAct rounds per step:

- planner calls stay relatively small
- later solver rounds become expensive because they include full observations
- writer calls are usually the largest single prompts

In practice, most token pressure comes from raw tool outputs and iterative draft growth rather than the planning stage itself.

*Last updated: 2026-02-10*
