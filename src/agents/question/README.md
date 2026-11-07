# Question Module (Refactored)

`src/agents/question` has been refactored into a **dual-loop architecture** that supports:

- topic-driven question generation (`topic + preference`)
- exam-driven question generation (`PDF` or pre-parsed exam content)

## 1. Directory Structure

```text
src/agents/question/
├── __init__.py
├── coordinator.py
├── models.py
├── cli.py
├── agents/
│   ├── idea_agent.py
│   ├── evaluator.py
│   ├── generator.py
│   └── validator.py
└── prompts/
    ├── en/
    │   ├── idea_agent.yaml
    │   ├── evaluator.yaml
    │   ├── generator.yaml
    │   └── validator.yaml
    └── zh/
        ├── idea_agent.yaml
        ├── evaluator.yaml
        ├── generator.yaml
        └── validator.yaml
```

## 2. Architecture Overview

### Path 1: Topic Mode

1. `IdeaAgent` generates candidate question ideas from the topic, preference, and RAG context
2. `Evaluator` scores the ideas and provides feedback; additional rounds run if needed
3. The system outputs top-k `QuestionTemplate` objects
4. Each template enters a generation-validation loop:
   - `Generator` produces a Q-A pair and may use `rag_tool`, `web_search`, or `write_code`
   - `Validator` approves or rejects the result; rejected outputs are regenerated with feedback

### Path 2: Mimic Mode

1. A PDF is first parsed by MinerU, or a pre-parsed directory is used directly
2. Reference questions are extracted
3. Reference questions are mapped into `QuestionTemplate` objects
4. The same generation-validation loop used in topic mode is applied

## 3. Core Data Models

Defined in `models.py`:

- `QuestionTemplate`: unified intermediate representation
  - `question_id`
  - `concentration`
  - `question_type`
  - `difficulty`
  - `source` (`custom` or `mimic`)
- `QAPair`: final generated output
  - `question`
  - `correct_answer`
  - `explanation`
  - `validation`

## 4. Coordinator Entry Points

`AgentCoordinator` exposes two main entry points:

- `generate_from_topic(user_topic, preference, num_questions)`
- `generate_from_exam(exam_paper_path, max_questions, paper_mode)`

## 5. Configuration (`main.yaml`)

```yaml
question:
  rag_query_count: 3
  max_parallel_questions: 1
  rag_mode: naive
  idea_loop:
    max_rounds: 3
    ideas_per_round: 5
  generation:
    max_retries: 2
    tools:
      web_search: true
      rag_tool: true
      write_code: true
```

## 6. Interactive CLI Testing

The module includes an interactive script:

```bash
python src/agents/question/cli.py
```

Supported flows:

- Interactive topic-mode testing
- Interactive mimic-mode testing (`upload` or `parsed`)
- Summary output showing completed/failed items and question previews

## 7. Related Tool Modules

Tools are located under `src/tools/question/`:

- `pdf_parser.py`
- `question_extractor.py`
- `exam_mimic.py` (thin wrapper delegating to the coordinator)

## 8. Notes

- The legacy `retrieve_agent`, `generate_agent`, and `relevance_analyzer` have been removed
- Legacy prompt files have been removed
- Old interfaces from previous documentation, such as `generate_questions_custom`, are no longer applicable
