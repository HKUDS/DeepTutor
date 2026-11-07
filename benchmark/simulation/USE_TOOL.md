# Simulator Tools Guide

## Overview

This module provides three async tools for student agents. Together they cover the full **solve -> generate -> answer** workflow and integrate with the memory system automatically.

Each student uses an isolated `workspace` directory. All outputs, including solve traces, generated question batches, and memory files, are stored under that workspace, and the memory agents read only from that workspace.

## Workspace Layout

```text
workspace/
├── memory/
│   ├── traces/
│   │   ├── index.json
│   │   ├── embeddings.json
│   │   └── {trace_id}.json
│   ├── logs/
│   ├── memory.md
│   ├── weakness.md
│   └── reflection.md
├── solve/
│   └── solve_YYYYMMDD_HHMMSS/
│       ├── scratchpad.json
│       ├── final_answer.md
│       └── cost_report.json
└── question/
    └── batch_YYYYMMDD_HHMMSS/
        ├── templates.json
        ├── summary.json
        └── q_X_result.json
```

## Tool APIs

### 1. `solve_question`

```python
from benchmark.simulation import solve_question

result = await solve_question(
    workspace="/path/to/student_001",
    kb_name="ai-textbook",
    question="What is the method of Lagrange multipliers?",
    language="en",
)
```

**Arguments**

| Argument | Type | Description |
|---|---|---|
| `workspace` | `str` | Root path of the student's workspace |
| `kb_name` | `str` | Knowledge base name |
| `question` | `str` | Student question |
| `language` | `str` | Output language, default `en` |

**Return value**

```python
{
    "question": "What is the method of Lagrange multipliers?",
    "answer": "The method of Lagrange multipliers is ...",
    "output_dir": "/path/to/.../solve_20260220_143022",
    "steps": 3,
    "completed_steps": 3,
    "citations": ["source-1", "source-2"],
}
```

**Internal flow**: `Plan -> ReAct -> Write -> trace creation -> trace forest registration -> memory agent updates`.

### 2. `generate_questions`

```python
from benchmark.simulation import generate_questions

result = await generate_questions(
    workspace="/path/to/student_001",
    kb_name="ai-textbook",
    topic="Eigenvalue decomposition in linear algebra",
    preferences="Focus on applied and computational questions",
    num_questions=3,
    language="en",
)
```

**Arguments**

| Argument | Type | Description |
|---|---|---|
| `workspace` | `str` | Root path of the student's workspace |
| `kb_name` | `str` | Knowledge base name |
| `topic` | `str` | Topic for question generation |
| `preferences` | `str` | Optional user preferences |
| `num_questions` | `int` | Number of questions to generate |
| `language` | `str` | Output language, default `en` |

**Return value**

```python
{
    "batch_id": "batch_20260220_150000",
    "batch_dir": "/path/to/.../batch_20260220_150000",
    "num_generated": 3,
    "questions": [
        {
            "question_id": "q_1",
            "question": "Which statement about eigenvalues is correct?",
            "options": {"A": "...", "B": "...", "C": "...", "D": "..."},
            "question_type": "choice",
        },
    ],
}
```

`questions` intentionally omits the correct answers so the student agent cannot peek. Correct answers stay in `summary.json` and are read later by `submit_answers`.

### 3. `submit_answers`

```python
from benchmark.simulation import submit_answers

result = await submit_answers(
    workspace="/path/to/student_001",
    batch_id="batch_20260220_150000",
    answers=[
        {"question_id": "q_1", "answer": "A"},
        {"question_id": "q_2", "answer": "C"},
        {"question_id": "q_3", "answer": "B"},
    ],
    language="en",
)
```

**Arguments**

| Argument | Type | Description |
|---|---|---|
| `workspace` | `str` | Root path of the student's workspace |
| `batch_id` | `str` | Batch ID returned by `generate_questions` |
| `answers` | `list[dict]` | Answer list such as `[{"question_id": "q_1", "answer": "A"}]` |
| `language` | `str` | Output language, default `en` |

**Return value**

```python
{
    "results": [
        {
            "question_id": "q_1",
            "user_answer": "A",
            "correct_answer": "A",
            "judged_result": "correct",
            "explanation": "Because ...",
        },
    ],
    "score": {
        "total": 3,
        "correct": 2,
        "wrong": 1,
        "accuracy": 0.6667,
    },
}
```

**Internal flow**: read answers from `summary.json`, grade automatically, append answer traces, and update memory files.

## Typical Usage

```python
import asyncio
from benchmark.simulation import solve_question, generate_questions, submit_answers

WS = "/data/eval/student_001"
KB = "ai-textbook"

async def main():
    solve_result = await solve_question(
        workspace=WS,
        kb_name=KB,
        question="What is gradient descent?",
        language="en",
    )
    print(solve_result["answer"])

    gen_result = await generate_questions(
        workspace=WS,
        kb_name=KB,
        topic="Backpropagation",
        num_questions=3,
        language="en",
    )

    answers = []
    for q in gen_result["questions"]:
        answer = student_agent_think(q)
        answers.append({"question_id": q["question_id"], "answer": answer})

    ans_result = await submit_answers(
        workspace=WS,
        batch_id=gen_result["batch_id"],
        answers=answers,
        language="en",
    )
    print(f"Score: {ans_result['score']['correct']}/{ans_result['score']['total']}")

asyncio.run(main())
```

## Parallel Simulation

Use different `workspace` paths for different students. That gives complete isolation and works naturally with `asyncio.gather`:

```python
async def simulate_student(student_id: str):
    ws = f"/data/eval/student_{student_id}"
    # call solve_question / generate_questions / submit_answers here

await asyncio.gather(
    simulate_student("001"),
    simulate_student("002"),
    simulate_student("003"),
)
```

## Requirements

Before using these tools, make sure `.env` or `DeepTutor.env` contains valid LLM credentials and the target knowledge base has already been built under `data/knowledge_bases/`.
