# DeepTutor Long-Horizon Reasoning and Safety Checklist

This guide is a practical debugging checklist for tutoring scenarios that involve multi-turn reasoning, retrieval, and tool calls.

Use it when:
- the assistant loses earlier constraints in long conversations,
- retrieval drifts away from the actual learning goal,
- responses sound overconfident despite weak evidence,
- feedback is not clearly grounded in retrieved material.

## 1) Typical Failure Modes

| Failure mode | Typical symptom | Why it matters |
|:--|:--|:--|
| Context drift in long-horizon reasoning | The tutor ignores earlier assumptions, constraints, or student level | Can produce contradictory guidance and confuse learners |
| Retrieval drift / low-quality evidence | Retrieved snippets are off-topic, stale, or unreliable | Reduces factual quality and pedagogical trust |
| Overconfidence with weak evidence | The tutor gives strong recommendations without enough support | Encourages incorrect understanding and unsafe decisions |
| Ungrounded tutoring feedback | Feedback references conclusions but not traceable evidence | Makes it hard for students and maintainers to verify claims |

## 2) Symptom -> Likely Causes -> Recommended Checks

### A. Context drift in long-horizon reasoning

- Symptom:
  - Later answers conflict with earlier user constraints.
  - Prior assumptions disappear after multiple tool calls.
- Likely causes:
  - Prompt window pressure or missing summary checkpoints.
  - Important constraints not persisted in system/session memory.
- Recommended checks:
  - Review conversation trace near the first turn where behavior diverges.
  - Verify whether key constraints are repeated in planner/task prompts.
  - Confirm memory/profile updates include learning goals and boundaries.

### B. Retrieval drift / low-quality evidence

- Symptom:
  - Retrieved chunks are weakly related to the current question.
  - The model cites snippets that do not support the answer.
- Likely causes:
  - Query expansion mismatch with student intent.
  - Embedding/search config mismatch (provider/model/dimension/index config).
  - Missing quality filters or poor source curation.
- Recommended checks:
  - Log top-k retrieval results with scores and source metadata.
  - Compare user query vs retrieval query after rewrite/expansion.
  - Validate embedding + index compatibility and reranking settings.

### C. Overconfidence with weak evidence

- Symptom:
  - Definitive wording where evidence is sparse or conflicting.
  - No uncertainty language when confidence should be low.
- Likely causes:
  - Prompting does not require uncertainty calibration.
  - Missing guardrails for "insufficient evidence" behavior.
- Recommended checks:
  - Check generation prompts for explicit uncertainty and citation rules.
  - Verify fallback behavior when retrieval confidence is low.
  - Add assertions in tests for "unknown/needs-evidence" responses.

### D. Ungrounded tutoring feedback

- Symptom:
  - Feedback appears generic, with no clear source references.
  - Student cannot inspect why a recommendation was made.
- Likely causes:
  - Missing citation policy or evidence rendering path.
  - UI/response layer drops source references.
- Recommended checks:
  - Inspect response payloads for source IDs/citations.
  - Verify frontend rendering keeps source traces visible.
  - Check that tool outputs are passed through without truncating references.

## 3) Quick Debugging Checklist

Before opening an issue or diagnosing a regression, collect:
- tool/capability path used (Chat / Deep Solve / Research / Quiz / TutorBot),
- model + provider settings (LLM, embedding, search),
- anonymized conversation trace for the failing turns,
- retrieval snippets (top-k items + scores + sources),
- exact prompts or prompt templates involved (if shareable),
- expected behavior vs actual behavior,
- environment details (OS, Python version, backend, GPU if relevant).

## 4) Issue Report Template (Copy/Paste)

```md
### Failure mode
- [ ] Context drift
- [ ] Retrieval drift / weak evidence
- [ ] Overconfidence with weak evidence
- [ ] Ungrounded feedback

### What happened
- Expected:
- Actual:

### Minimal reproduction
1.
2.
3.

### Configuration
- Mode/Capability:
- LLM provider + model:
- Embedding provider + model:
- Search provider:
- Backend (if applicable):

### Evidence bundle
- Conversation trace (anonymized):
- Retrieved snippets (top-k + score + source):
- Relevant logs/errors:
```

## 5) Operational Notes

- Keep student privacy first: redact personal or sensitive data before sharing traces.
- Prefer deterministic reproductions with the smallest possible prompt/input set.
- When uncertain, mark uncertainty explicitly in outputs rather than forcing a confident answer.
