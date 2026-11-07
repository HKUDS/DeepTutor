#!/usr/bin/env python3
"""
Audit pipeline result folders: compare folder-name model vs actual model in cost_reports.
"""

import json
import os
import re
import sys
from collections import defaultdict
from pathlib import Path

RESULTS_ROOT = Path(__file__).parent / "results"


def extract_model_from_folder(folder_name: str) -> str | None:
    """Extract model identifier from folder name like 'openai_gpt-5.2_nitro_20260224_014320'."""
    m = re.match(r"^(.+?)_(\d{8}_\d{6})(-.*)?$", folder_name)
    if m:
        return m.group(1)
    return folder_name


def collect_models_from_cost_reports(folder: Path) -> set[str]:
    """Walk all cost_report.json under a run folder, return the set of models actually used."""
    models = set()
    for root, _, files in os.walk(folder):
        if "cost_report.json" in files:
            try:
                with open(os.path.join(root, "cost_report.json")) as f:
                    data = json.load(f)
                by_model = data.get("summary", {}).get("by_model", {})
                for model_key in by_model:
                    models.add(model_key)
            except (json.JSONDecodeError, KeyError):
                pass
    return models


def normalize_model(name: str) -> str:
    """Normalize model name for comparison: strip provider prefix, colon suffix, replace / and : with _."""
    return name.replace("/", "_").replace(":", "_")


def main():
    mismatches = []
    ok_count = 0
    skip_count = 0

    for benchmark_dir in sorted(RESULTS_ROOT.iterdir()):
        if not benchmark_dir.is_dir():
            continue
        pipeline_dir = benchmark_dir / "pipeline"
        if not pipeline_dir.is_dir():
            continue
        for run_dir in sorted(pipeline_dir.iterdir()):
            if not run_dir.is_dir():
                continue

            folder_model = extract_model_from_folder(run_dir.name)
            actual_models = collect_models_from_cost_reports(run_dir)

            if not actual_models:
                skip_count += 1
                continue

            folder_model_norm = normalize_model(folder_model) if folder_model else ""
            actual_norms = {normalize_model(m) for m in actual_models}

            if folder_model_norm in actual_norms or (len(actual_norms) == 1 and folder_model_norm == actual_norms.pop()):
                ok_count += 1
            else:
                mismatches.append({
                    "path": str(run_dir.relative_to(RESULTS_ROOT)),
                    "folder_model": folder_model,
                    "actual_models": sorted(actual_models),
                })

    print("=" * 80)
    print("Pipeline Folder Name Audit")
    print("=" * 80)
    print(f"  OK (folder matches cost_report): {ok_count}")
    print(f"  Skipped (no cost_report found):   {skip_count}")
    print(f"  MISMATCH:                         {len(mismatches)}")
    print("=" * 80)

    if mismatches:
        print("\nMISMATCHED FOLDERS:\n")
        for i, m in enumerate(mismatches, 1):
            print(f"  [{i}] {m['path']}")
            print(f"      Folder says:       {m['folder_model']}")
            print(f"      Actually used:     {', '.join(m['actual_models'])}")
            print()
    else:
        print("\nAll pipeline folders match their cost reports!")

    return 1 if mismatches else 0


if __name__ == "__main__":
    sys.exit(main())
