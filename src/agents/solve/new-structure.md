# Solve Agent Refactor: Plan -> ReAct -> Write

## Design Principles

- **Single pipeline**: every problem follows the same overall flow
- **Global planning first**: use a high-level plan to avoid purely local ReAct behavior
- **Step-level ReAct**: each plan step gathers evidence through iterative `think -> act -> observe`
- **Adaptive planning**: simple questions naturally produce short plans, while complex questions produce longer plans
- **No separate summary agent**: the solver reads raw retrieved evidence directly

## Overall Flow

```text
User Question
    │
    ▼
Phase 1: PLAN
  PlannerAgent analyzes the question and outputs ordered steps
    │
    ▼
Phase 2: SOLVE
  For each step:
    SolverAgent runs a ReAct loop
    THINK  -> What information is still missing?
    ACT    -> rag_search / web_search / code_execute / done / replan
    OBSERVE -> Write tool output into the scratchpad
    Repeat until the step is done
    │
    ▼
Phase 3: WRITE
  WriterAgent produces the final answer from the full scratchpad
```

## The Three Agents

### PlannerAgent

PlannerAgent decomposes the user question into ordered sub-goals.

Typical output:

```json
{
  "analysis": "Brief problem analysis",
  "steps": [
    { "id": "S1", "goal": "Clarify the mathematical definition", "tools_hint": ["rag"] },
    { "id": "S2", "goal": "Work through the derivation", "tools_hint": ["rag", "code"] },
    { "id": "S3", "goal": "Verify with an example", "tools_hint": ["code"] }
  ]
}
```

Key ideas:

- A step is a verifiable sub-goal, not a single tool call
- `tools_hint` is advisory rather than binding
- The planner replaces explicit routing logic with plan-level adaptation

### SolverAgent

SolverAgent works on one current step at a time and performs iterative evidence gathering.

Typical loop output:

```json
{
  "thought": "I still need the formal definition, so I should search the textbook first.",
  "action": "rag_search",
  "action_input": "linear convolution definition formula",
  "self_note": "Found the exact definition and formula; enough evidence for this step."
}
```

Key ideas:

- The same agent handles retrieval decisions, query reformulation, and evidence assessment
- `done` marks the current step as complete
- `replan` requests that the planner revise the remaining steps
- `self_note` is the compact information bridge between steps
- Tool execution itself is a pure function call and does not consume an extra LLM call

### WriterAgent

WriterAgent converts the full scratchpad into the final answer.

Inputs:

- the original user question
- the complete scratchpad
- user preferences such as language or detail level

Outputs:

- structured Markdown
- inline citations derived from scratchpad sources

## Unified Memory: Scratchpad

The scratchpad replaces multiple older memory structures with one shared record.

```text
Scratchpad
├── question
├── plan
│   ├── analysis
│   └── steps[{id, goal, tools_hint, status}]
├── entries
│   └── [{step_id, round, thought, action, action_input, observation, self_note, sources, timestamp}]
└── metadata
    ├── total_llm_calls
    ├── total_tokens
    ├── start_time
    └── plan_revisions
```

### Context Compression Strategy

As the scratchpad grows, context is compressed hierarchically:

- Current-step entries keep full `thought`, `action`, and `observation`
- Completed steps are compressed to `thought + action + self_note`
- Older steps may be reduced further to a short `self_note` summary

Raw observations are still preserved on disk, so the writer can recover detailed evidence when needed.

## Replanning

Replanning happens only when the solver explicitly requests it.

```text
SolverAgent emits action = "replan"
    ↓
PlannerAgent receives:
  - the original question
  - the current scratchpad
  - the solver's replanning reason
    ↓
PlannerAgent revises the remaining steps
```

Typical triggers:

- the original interpretation of the problem turns out to be wrong
- the knowledge base lacks crucial information and the flow should switch to web search
- completed steps already cover future goals and the plan can be simplified

## Tool Layer

The tool layer is execution-only and does not perform additional reasoning.

| Action | Function | Returns |
|--------|----------|---------|
| `rag_search` | Search the knowledge base | retrieved content and source metadata |
| `web_search` | Search the web | web results and URLs |
| `code_execute` | Run sandboxed Python | execution output and artifact paths |
| `done` | Mark the step complete | none |
| `replan` | Request a revised plan | none |

Tool outputs are truncated to a reasonable size before being stored as observations.

## Mapping from the Older Design

| Older component | New component | Change |
|----------------|---------------|--------|
| `InvestigateAgent` | `SolverAgent` | merged |
| `NoteAgent` | removed | replaced by `self_note` |
| `ManagerAgent` | `PlannerAgent` | simplified |
| `SolveAgent` | `SolverAgent` | merged |
| `ToolAgent` | removed | solver reads raw results directly |
| `SolveNoteAgent` | removed | replaced by replanning |
| `ResponseAgent` | `WriterAgent` | simplified |
| `PrecisionAnswerAgent` | `WriterAgent` | merged |
| `InvestigateMemory` / `SolveMemory` / `CitationMemory` | `Scratchpad` | unified |

## Expected Benefits

Compared with the older multi-agent solve stack, this design:

- reduces redundant summarization calls
- keeps planning and solving tightly connected
- preserves direct access to raw evidence
- lowers the total number of LLM calls for medium-complexity problems

## Additional Notes

- Streaming output can expose SolverAgent thoughts and WriterAgent drafts in real time
- The same three-stage pattern can be reused in other research-style agents by swapping prompts and tools
- Query rewriting is handled naturally inside SolverAgent reasoning instead of a dedicated module
