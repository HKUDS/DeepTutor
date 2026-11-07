# iso_solve

`iso_solve` is used to evaluate DeepTutor's solving capability in isolation. It supports a shared evaluation pipeline that can be reused across multiple benchmarks.

- `direct`: solve questions with a direct LLM call
- `pipeline`: solve questions through DeepTutor's `Plan -> ReAct -> Write` pipeline

The evaluation logic always has two steps:

1. Extract the final answer from the problem statement and model output (`output.md` or `final_answer.md`) with an LLM
2. Compare the extracted answer with the ground truth using an LLM judge

## Directory Structure

```text
benchmark/iso_solve/
├── run_benchmark.py          # Unified CLI entry point
├── config.yaml               # Shared configuration
├── core/                     # Common evaluation framework
│   ├── types.py
│   ├── extractor.py
│   ├── judge.py
│   ├── pipeline.py
│   └── runner.py
├── eval/                     # Benchmark adapters
│   ├── base.py
│   ├── math.py
│   ├── gpqa.py
│   ├── aime25.py
│   ├── gaia.py
│   ├── hle.py
│   ├── livebench.py
│   └── scorers/
└── results/                  # All evaluation outputs
```

## Design Overview

- `core/runner.py`
  - Handles concurrency, result persistence, and report generation
  - Remains benchmark-agnostic
- `eval/*.py`
  - Handles data loading, filtering, and benchmark-specific prompt or metadata differences
  - Integrates each benchmark through an adapter layer
- `core/extractor.py` + `core/judge.py`
  - Provide shared LLM-based answer extraction and judging
  - Use the global `evaluation` section in `config.yaml`

## Configuration

Global evaluation switches are defined in one place:

```yaml
evaluation:
  llm_extract: true
  llm_judge: true
  extract_model: null
  extract_max_tokens: 256
  judge_model: null
  judge_max_tokens: 128
```

Notes:

- If `extract_model` or `judge_model` is `null`, the default LLM configuration is used
- `extract_max_tokens` and `judge_max_tokens` control output length for extraction and judging
- Benchmark-specific configs no longer control extract/judge models or feature toggles independently

## Running Benchmarks

Run commands from the project root.

### MATH

```bash
# direct, small run
python -m benchmark.iso_solve.run_benchmark --benchmark math --mode direct --config benchmark/iso_solve/config.yaml --limit 5

# direct, full run
python -m benchmark.iso_solve.run_benchmark --benchmark math --mode direct --config benchmark/iso_solve/config.yaml

# pipeline, small run
python -m benchmark.iso_solve.run_benchmark --benchmark math --mode pipeline --config benchmark/iso_solve/config.yaml --limit 5

# pipeline, full run
python -m benchmark.iso_solve.run_benchmark --benchmark math --mode pipeline --config benchmark/iso_solve/config.yaml
```

### GPQA-Diamond

```bash
python -m benchmark.iso_solve.run_benchmark --benchmark gpqa --mode direct --config benchmark/iso_solve/config.yaml --limit 5
python -m benchmark.iso_solve.run_benchmark --benchmark gpqa --mode direct --config benchmark/iso_solve/config.yaml
python -m benchmark.iso_solve.run_benchmark --benchmark gpqa --mode pipeline --config benchmark/iso_solve/config.yaml --limit 5
python -m benchmark.iso_solve.run_benchmark --benchmark gpqa --mode pipeline --config benchmark/iso_solve/config.yaml
```

### AIME 2025

```bash
python -m benchmark.iso_solve.run_benchmark --benchmark aime25 --mode direct --config benchmark/iso_solve/config.yaml --limit 5
python -m benchmark.iso_solve.run_benchmark --benchmark aime25 --mode direct --config benchmark/iso_solve/config.yaml
python -m benchmark.iso_solve.run_benchmark --benchmark aime25 --mode pipeline --config benchmark/iso_solve/config.yaml --limit 5
python -m benchmark.iso_solve.run_benchmark --benchmark aime25 --mode pipeline --config benchmark/iso_solve/config.yaml
```

### HLE

```bash
python -m benchmark.iso_solve.run_benchmark --benchmark hle --mode direct --config benchmark/iso_solve/config.yaml --limit 5
python -m benchmark.iso_solve.run_benchmark --benchmark hle --mode direct --config benchmark/iso_solve/config.yaml
python -m benchmark.iso_solve.run_benchmark --benchmark hle --mode pipeline --config benchmark/iso_solve/config.yaml --limit 5
python -m benchmark.iso_solve.run_benchmark --benchmark hle --mode pipeline --config benchmark/iso_solve/config.yaml
```

### GAIA

```bash
python -m benchmark.iso_solve.run_benchmark --benchmark gaia --mode direct --config benchmark/iso_solve/config.yaml --limit 3
python -m benchmark.iso_solve.run_benchmark --benchmark gaia --mode direct --config benchmark/iso_solve/config.yaml
python -m benchmark.iso_solve.run_benchmark --benchmark gaia --mode pipeline --config benchmark/iso_solve/config.yaml --limit 3
python -m benchmark.iso_solve.run_benchmark --benchmark gaia --mode pipeline --config benchmark/iso_solve/config.yaml
```

### LiveBench

```bash
python -m benchmark.iso_solve.run_benchmark --benchmark livebench --mode direct --config benchmark/iso_solve/config.yaml --limit 20
python -m benchmark.iso_solve.run_benchmark --benchmark livebench --mode direct --config benchmark/iso_solve/config.yaml
python -m benchmark.iso_solve.run_benchmark --benchmark livebench --mode pipeline --config benchmark/iso_solve/config.yaml --limit 20
python -m benchmark.iso_solve.run_benchmark --benchmark livebench --mode pipeline --config benchmark/iso_solve/config.yaml
```

### Common Arguments

| Argument | Description |
|----------|-------------|
| `--benchmark` | `math | gpqa | aime25 | hle | gaia | livebench` |
| `--mode` | `direct | pipeline` |
| `--limit N` | Limit the sample count and override `filter.limit` in `config.yaml` |
| `--seed N` | Random seed for sampling |
| `--output DIR` | Custom result root directory |
| `--dry-run` | Validate data loading and filtering without calling an LLM |
| `-v` | Enable DEBUG logging |

## Result Layout

Each run is organized by benchmark, mode, and timestamped model directory:

```text
results/{benchmark}/{mode}/{model}_{YYYYMMDD_HHMMSS}/
├── report.json
├── summary.txt
└── outputs/
    ├── 0000/
    │   ├── output.md
    │   ├── meta.json
    │   ├── scratchpad.json
    │   ├── cost_report.json
    │   ├── task.log
    │   └── code_runs/
    │       └── exec_*/...
    └── 0001/
```

## About `code_execute` Artifacts

When `pipeline` mode calls `code_execute`, the execution directory is written into the current problem's solve output directory (`code_runs/exec_*`) rather than the global `run_code_workspace`.

This keeps each experiment directory self-contained and reproducible: outputs, reasoning traces, cost reports, and code-execution artifacts all live under the same directory tree.
