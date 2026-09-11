# Long-Horizon Reasoning and Safety Checklist

Use this checklist when a tutoring answer looks unreliable, changes assumptions midway, cites weak evidence, or fails to reflect the material a learner selected. It is intentionally diagnostic: it helps users collect useful evidence and helps maintainers distinguish a prompt problem, retrieval problem, context problem, or product bug.

## Quick Diagnostic Questions

1. What did the learner originally ask for, and which constraints or definitions still matter?
2. Which capability ran, which tools were enabled, and which tool calls actually happened?
3. Which knowledge base, attachment, reading selection, book, or web result did the answer rely on?
4. Did the answer quote, cite, or paraphrase concrete evidence, or did it only sound authoritative?
5. Was an earlier turn ignored, over-applied, or mixed with a different learner's context?
6. Did the model say what was unknown, uncertain, or outside the selected material?

## Failure Modes

| Failure mode | Common symptoms | Likely causes | Checks |
| --- | --- | --- | --- |
| Lost long-horizon constraints | Later steps forget an earlier definition, goal, notation, restriction, or correction | Context trimming, branch mixing, too many tool observations, insufficient restatement of constraints | Compare the final prompt's relevant history, session branch, and turn metadata; repeat the missing constraint in a new turn to see whether behavior changes |
| Retrieval drift | The answer is topical but uses unrelated sources or answers a neighboring question | Ambiguous query, stale index, mixed sources, broad top-k, missing reranking or source filter | Inspect tool inputs and retrieved chunk IDs; run the same question against one knowledge base or attachment at a time; rebuild or refresh a stale index |
| Weak-evidence overconfidence | A definitive answer, grade, diagnosis, or recommendation has no citation or ignores contradictions | No retrieval result, low-confidence match, model defaulting to prior knowledge, missing uncertainty instruction | Check whether retrieval returned empty or low-score results; ask for the exact supporting passage; retry with evidence-only instructions |
| Feedback not grounded in the material | Explanation, quiz answer, or correction disagrees with the uploaded course material | Wrong source selected, stale book page, mismatched citation locator, conflicting sources | Compare the cited locator, selected material, and current source version; verify page or chapter anchors and whether the source changed |

## Retrieval Failure Patterns

Check the patterns that best describe the observed behavior:

1. **No retrieval:** the tool was available but not called.
2. **Wrong scope:** retrieval searched another knowledge base, partner workspace, attachment, or user context.
3. **Stale source:** the document or index changed after retrieval artifacts were generated.
4. **Chunk boundary split:** a definition, table, proof, code block, or caption was cut in half.
5. **Near-topic drift:** chunks share vocabulary but answer a different question.
6. **Keyword mismatch:** the source uses different terminology from the learner's question.
7. **Translation mismatch:** a translated query and source language do not align.
8. **Duplicated chunks:** the same passage crowds out other relevant evidence.
9. **Over-broad top-k:** weak matches dilute a small number of strong matches.
10. **Missing rerank:** semantic first-stage candidates are not refined before use.
11. **Conflicting sources:** sources disagree and the model silently picks one.
12. **Unverified external source:** a web result is used without authority, date, or corroboration checks.
13. **Citation mismatch:** the statement and cited passage do not support each other.
14. **Locator mismatch:** a page, section, heading, or anchor points to the wrong location.
15. **Empty or filtered result:** access, parsing, MIME, language, or metadata filtering removed the needed chunk.
16. **Hallucinated evidence:** a quote, number, title, or citation is not present in any returned source.

## Evidence To Collect

Before opening an issue, prepare a minimal and privacy-safe report:

- DeepTutor version, operating system, Python and Node versions, and installation mode.
- Capability and model used, including whether reasoning effort or a model-specific setting was changed.
- Selected knowledge bases, attachments, Reading material, Book, or partner workspace, without uploading private documents unless they are safe to share.
- The relevant user request and assistant answer, with personal data removed.
- Tool names, arguments, result summaries, and citation IDs from the Activity panel or JSON run output.
- Retrieved snippets or citation locators needed to reproduce the mismatch.
- Whether retrying, selecting one source, rebuilding the index, or restating the constraint changes the result.
- Server logs around the request, with API keys, tokens, local paths, usernames, and personal content removed.

Avoid sharing credentials, private student work, personal identifiers, or confidential documents. A fabricated or shortened source excerpt that preserves the structure is usually enough to reproduce a retrieval issue.

## Issue Report Template

```markdown
Capability:
Model:
DeepTutor version:

What the learner asked:
What DeepTutor answered:
Why the answer looks wrong:

Selected sources:
Tool calls observed:
Retrieved snippet or citation IDs:

Reproducible steps:
Expected behavior:
Actual behavior:
What I already tried:
```
