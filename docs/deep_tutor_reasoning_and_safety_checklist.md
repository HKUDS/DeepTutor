# DeepTutor Reasoning & Safety Checklist

This checklist aims to ensure pedagogical safety and reasoning robustness during multi-turn tutoring sessions.

## 1. Typical Failure Modes
- **Constraint Loss**: Forgetting earlier pedagogical boundaries (e.g., "don't give the answer yet").
- **Retrieval Drift**: Using low-quality or off-topic knowledge base snippets.
- **Overconfidence**: Asserting facts without clear grounding in the retrieved material.

## 2. Debugging Steps
- [ ] Check prompt logs for lost context.
- [ ] Verify RAG retrieval scores and snippet relevance.
- [ ] Ensure model output includes citations from the Knowledge Base.

## 3. Issue Reporting
When opening an issue, please include:
- Tools used during the failure.
- Anonymized conversation trace.
- Retrieved snippets that led to the error.
