---
name: deep-question
description: "Generate quiz questions with answers on any topic."
metadata: {"nanobot":{"emoji":"❓","requires":{"bins":["deeptutor"]}}}
always: false
---

# Deep Question (Quiz Generation)

Use the `exec` tool to invoke DeepTutor's quiz generation pipeline (ideation → evaluation → generation → validation).

## When to Use

- User wants **practice questions** or **quizzes** on a topic
- User is preparing for an exam or self-testing
- User asks to "generate questions", "quiz me", "create practice problems"

## Command

```bash
deeptutor run deep_question "<topic>" --format json -l <lang> [options]
```

### Options

| Flag | Description |
|------|-------------|
| `-l <lang>` | Response language: `en` or `zh` |
| `--config num_questions=N` | Number of questions (default: 1, max: 50) |
| `--config difficulty=<level>` | `easy`, `medium`, `hard` |
| `--config question_types=<type1,type2>` | Comma-separated list: `multiple_choice`, `open_ended`, `true_false`, etc. |
| `--config mode=<mode>` | `custom` (default) or `mimic` |
| `-t rag` | Ground questions in a knowledge base |
| `--kb <name>` | Knowledge base to use |

## Examples

Basic quiz:
```bash
deeptutor run deep_question "Calculus integration techniques" --format json -l en --config num_questions=5 --config difficulty=medium
```

Multiple-choice from a textbook:
```bash
deeptutor run deep_question "Chapter 3: Linear Algebra" --format json -l zh -t rag --kb math-textbook --config question_types=multiple_choice --config num_questions=10
```

Hard open-ended questions:
```bash
deeptutor run deep_question "Quantum mechanics fundamentals" --format json -l en --config difficulty=hard --config question_types=open_ended
```

## Important

- This capability can take **over a minute** for multiple questions — use `timeout=300` with the `exec` tool.
- Parse NDJSON events with `"type": "content"` for the generated questions and answers.
