# Benchmark - Tutor Evaluation System

This module generates evaluation data for the tutoring system, runs simulated conversations, and scores tutor performance with LLM-as-a-judge evaluation.

## Directory Structure

```text
benchmark/
├── config/
│   └── benchmark_config.yaml    # Data-generation and evaluation config
├── data/
│   ├── generated/               # Generated entries (JSONL and per-entry JSON)
│   ├── transcripts/             # Conversation transcripts
│   └── evaluations/             # Evaluation outputs
├── data_generation/             # Data-generation pipeline
├── simulation/                  # Conversation simulation (StudentAgent + human/LLM tutor)
├── evaluation/                  # LLM-as-judge evaluation logic
├── prompts/                     # Prompt templates for each stage
└── README.md
```

## 1. Data Generation

### Pipeline Overview

```text
Knowledge Base
    │
    ▼  Stage 1: Discover available KBs
    ▼  Stage 2: Query RAG to build a knowledge scope
    ▼  Stage 3: Generate student profiles (beginner / intermediate / advanced)
    ▼  Stage 4-5: Loop per profile until quality thresholds are met
    │       ├── Sample a contiguous page window from `content_list`
    │       ├── Generate gaps with `source_pages`
    │       ├── Generate tasks with partitioning and rejection sampling
    │       └── Continue until `min_tasks_per_profile` is satisfied
    ▼  Stage 6: Write entries to JSONL and per-entry JSON
```

### Core Concepts

- **Profile**: a synthetic student profile including background, prior knowledge, personality, and learning goals
- **Gap**: a knowledge gap such as a misconception, incomplete understanding, or missing knowledge, with linked `source_pages`
- **Task**: a tutoring task tied to one or more gaps, including an `initial_message` and `success_criteria`
- **Entry**: one evaluation sample combining profile, gaps, task, and source content

### Important Config Keys

| Key | Description |
|-----|-------------|
| `profile_generation.profiles_per_subtopic` | Number of students generated per KB/subtopic |
| `gap_generation.use_content_list` | Whether to build page-grounded gaps from `content_list` |
| `gap_generation.pages_per_profile` | Number of contiguous pages sampled per profile |
| `gap_generation.rejection_sampling` | Whether task generation uses rejection sampling |
| `task_generation.min_tasks_per_profile` | Minimum task count for each profile |
| `task_generation.gaps_per_batch` | Number of gaps generated in each batch |

### Usage

```bash
# Generate evaluation data for calc1
python3 -m benchmark.data_generation.pipeline --kb-names calc1

# Use a custom config file
python3 -m benchmark.data_generation.pipeline --config path/to/config.yaml --kb-names calc1
```

### Outputs

- `benchmark/data/generated/benchmark_{timestamp}/`
  - `{entry_id}.json`: one entry per file
  - `_all_entries.jsonl`: all entries in one JSONL file
  - `_summary.json`: summary statistics
- `benchmark/data/generated/knowledge_scopes/{kb_name}.json`: generated knowledge scope

## 2. Conversation Simulation

### Modes

1. **Interactive**: a human acts as the tutor in the terminal or editor
2. **Auto**: an LLM acts as a mock tutor

### Single Conversation

```bash
# Interactive mode (uses $EDITOR by default)
python3 -m benchmark.simulation.conversation --entry benchmark/data/generated/benchmark_xxx/calc1_xxx_task_001.json

# Inline terminal input
python3 -m benchmark.simulation.conversation --entry path/to/entry.json --inline

# Auto mode
python3 -m benchmark.simulation.conversation --entry path/to/entry.json --auto --max-turns 10
```

### Multi-Session Runs

```bash
# Filter by profile from a JSONL file
python3 -m benchmark.simulation.conversation \
  --entry benchmark/data/generated/benchmark_xxx/_all_entries.jsonl \
  --profile calc1_beginner_00 \
  --multi-session --auto

# Explicit list of entries
python3 -m benchmark.simulation.conversation \
  --entries entry1.json,entry2.json,entry3.json \
  --multi-session --auto

# Disable profile evolution
python3 -m benchmark.simulation.conversation --entry ... --profile ... --multi-session --no-evolve
```

### Outputs

- Transcripts are saved under `benchmark/data/transcripts/`
- Single-session files use `{entry_id}_{timestamp}.json`
- Multi-session files use `multi_{profile_id}_{timestamp}.json`

## 3. Evaluation

### Metrics

**Turn-level** metrics:
- 50% personalization: `profile_adaptation`, `misconception_targeting`
- 25% response quality: `response_quality`, `engagement`
- 25% knowledge alignment: `knowledge_source_alignment`

**Dialogue-level** metrics:
- 50% personalization: `adaptation_consistency`, `gap_resolution`, `success_criteria_met`
- 25% dialogue quality: `session_quality`, `student_agency`
- 25% knowledge alignment: `knowledge_source_alignment`

The combined score is:

`combined_overall_score = 0.4 * average_turn_score + 0.6 * dialogue_score`

### Usage

```bash
# Evaluate one transcript
python3 -m benchmark.evaluation.run --transcript benchmark/data/transcripts/xxx.json

# Dialogue-only evaluation
python3 -m benchmark.evaluation.run --transcript xxx.json --dialog-only

# Evaluate all transcripts in a directory
python3 -m benchmark.evaluation.run --transcript-dir benchmark/data/transcripts

# Custom output path
python3 -m benchmark.evaluation.run --transcript xxx.json -o results.json
```

### Outputs

- Saved by default to `benchmark/data/evaluations/{stem}_eval_{timestamp}.json`
- Supports both single-session and multi-session transcripts

## 4. End-to-End Example

```bash
# 1. Generate data
python3 -m benchmark.data_generation.pipeline --kb-names calc1

# 2. Run a conversation
python3 -m benchmark.simulation.conversation \
  --entry benchmark/data/generated/benchmark_xxx/_all_entries.jsonl \
  --profile calc1_beginner_00 \
  --multi-session --auto --max-turns 5

# 3. Evaluate the transcript
python3 -m benchmark.evaluation.run \
  --transcript benchmark/data/transcripts/multi_calc1_beginner_00_xxx.json
```

## 5. CLI Quick Reference

### Data Generation

| Argument | Description |
|----------|-------------|
| `--config` | Path to the config file |
| `--kb-names` | Comma-separated KB names overriding config defaults |

### Conversation Simulation

| Argument | Description |
|----------|-------------|
| `--entry` | Entry JSON or JSONL path |
| `--multi-session` | Enable multi-session mode |
| `--profile` | `profile_id` filter used with `--entry` + `--multi-session` |
| `--entries` | Comma-separated entry paths for multi-session runs |
| `--no-evolve` | Disable profile evolution |
| `--auto` | Use an LLM as the tutor |
| `--max-turns` | Maximum number of dialogue turns |
| `--output-dir` | Transcript output directory |
| `--entry-index` | Entry index when reading JSONL |
| `--inline` | Use terminal input instead of an external editor |

### Evaluation

| Argument | Description |
|----------|-------------|
| `--transcript` | Path to a single transcript |
| `--transcript-dir` | Directory of transcripts to evaluate |
| `--dialog-only` | Skip turn-level scoring |
| `--output` / `-o` | Output path for results |
| `--temperature` | Judge model temperature |
| `--verbose` / `-v` | Enable debug logging |

## 6. Key Files

| File | Purpose |
|------|---------|
| `data_generation/pipeline.py` | Main data-generation pipeline |
| `data_generation/content_loader.py` | Loads contiguous pages from `content_list` |
| `data_generation/gap_generator.py` | Generates page-grounded gaps |
| `data_generation/task_generator.py` | Generates tasks with rejection sampling |
| `simulation/student_agent.py` | LLM-based student role |
| `simulation/conversation.py` | Single-session and multi-session runner |
| `simulation/profile_evolver.py` | Evolves student profiles across sessions |
| `evaluation/evaluator.py` | LLM-as-judge evaluation logic |
