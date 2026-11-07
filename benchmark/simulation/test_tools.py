#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Quick smoke-test for the three simulator tools.

Usage:
    python benchmark/simulation/test_tools.py
"""

from __future__ import annotations

import asyncio
import json
import shutil
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env", override=False)

# ── Test workspace ─────────────────────────────────────────────────────

TEST_WS = str(PROJECT_ROOT / "data" / "eval_test" / "student_test")
KB = "ai-textbook"
LANG = "en"

GREEN = "\033[92m"
RED = "\033[91m"
CYAN = "\033[96m"
BOLD = "\033[1m"
DIM = "\033[2m"
RESET = "\033[0m"


def section(title: str) -> None:
    print(f"\n{'='*60}")
    print(f"  {BOLD}{CYAN}{title}{RESET}")
    print(f"{'='*60}")


def check_path(label: str, path: str | Path) -> bool:
    p = Path(path)
    ok = p.exists()
    icon = f"{GREEN}✓{RESET}" if ok else f"{RED}✗{RESET}"
    print(f"  {icon} {label}: {DIM}{p}{RESET}")
    return ok


def check_key(label: str, d: dict, key: str) -> bool:
    val = d.get(key)
    ok = val is not None and val != "" and val != []
    icon = f"{GREEN}✓{RESET}" if ok else f"{RED}✗{RESET}"
    short = str(val)[:120] if val else "(missing)"
    print(f"  {icon} {label}: {DIM}{short}{RESET}")
    return ok


# ── Test 1: solve_question ─────────────────────────────────────────────

async def test_solve():
    section("Test 1: solve_question")
    from benchmark.simulation import solve_question

    result = await solve_question(
        workspace=TEST_WS,
        kb_name=KB,
        question="What is gradient descent and why is it important in machine learning?",
        language=LANG,
    )

    print(f"\n  {BOLD}Return keys:{RESET} {list(result.keys())}")
    check_key("question", result, "question")
    check_key("answer", result, "answer")
    check_key("output_dir", result, "output_dir")
    check_key("steps", result, "steps")

    # Check file paths
    print(f"\n  {BOLD}File paths:{RESET}")
    ws = Path(TEST_WS)
    check_path("workspace/memory/", ws / "memory")
    check_path("workspace/solve/", ws / "solve")

    out_dir = result.get("output_dir", "")
    if out_dir:
        check_path("output_dir exists", out_dir)
        check_path("scratchpad.json", Path(out_dir) / "scratchpad.json")
        check_path("final_answer.md", Path(out_dir) / "final_answer.md")

    # Check trace was registered
    traces_dir = ws / "memory" / "traces"
    check_path("traces/ dir", traces_dir)
    check_path("index.json", traces_dir / "index.json")
    if (traces_dir / "index.json").exists():
        idx = json.loads((traces_dir / "index.json").read_text())
        n_traces = len(idx.get("traces", []))
        n_nodes = len(idx.get("nodes", []))
        print(f"  {GREEN}✓{RESET} index: {n_traces} trace(s), {n_nodes} node(s)")

    # Check memory docs
    print(f"\n  {BOLD}Memory docs:{RESET}")
    for doc in ("memory.md", "weakness.md", "reflection.md"):
        p = ws / "memory" / doc
        if p.exists():
            size = len(p.read_text())
            print(f"  {GREEN}✓{RESET} {doc}: {size} chars")
        else:
            print(f"  {DIM}○{RESET} {doc}: not yet created (agent may not have written it)")

    return result


# ── Test 2: generate_questions ─────────────────────────────────────────

async def test_generate():
    section("Test 2: generate_questions")
    from benchmark.simulation import generate_questions

    result = await generate_questions(
        workspace=TEST_WS,
        kb_name=KB,
        topic="gradient descent and optimization",
        preferences="focus on intuition and practical applications",
        num_questions=2,
        language=LANG,
    )

    print(f"\n  {BOLD}Return keys:{RESET} {list(result.keys())}")
    check_key("batch_id", result, "batch_id")
    check_key("batch_dir", result, "batch_dir")
    check_key("num_generated", result, "num_generated")
    check_key("questions", result, "questions")

    questions = result.get("questions", [])
    print(f"\n  {BOLD}Questions generated: {len(questions)}{RESET}")
    for q in questions:
        print(f"    {CYAN}[{q.get('question_id')}]{RESET} {q.get('question', '')[:80]}...")
        opts = q.get("options", {})
        if isinstance(opts, dict):
            for k, v in opts.items():
                print(f"      {k}. {v[:60]}")
        # Verify no correct answer leaked
        assert "correct_answer" not in q, "LEAK: correct_answer in question!"
        print(f"      {GREEN}✓ no correct_answer leak{RESET}")

    # Check file paths
    print(f"\n  {BOLD}File paths:{RESET}")
    batch_dir = result.get("batch_dir", "")
    if batch_dir:
        check_path("batch_dir", batch_dir)
        check_path("summary.json", Path(batch_dir) / "summary.json")
        check_path("templates.json", Path(batch_dir) / "templates.json")

    # Check trace registered (should be in question dir, NOT solve dir)
    ws = Path(TEST_WS)
    traces_dir = ws / "memory" / "traces"
    if (traces_dir / "index.json").exists():
        idx = json.loads((traces_dir / "index.json").read_text())
        q_traces = [t for t in idx.get("traces", []) if t.get("trace_type") == "question"]
        print(f"  {GREEN}✓{RESET} question traces in index: {len(q_traces)}")

    return result


# ── Test 3: submit_answers ─────────────────────────────────────────────

async def test_submit(gen_result: dict):
    section("Test 3: submit_answers")
    from benchmark.simulation import submit_answers

    questions = gen_result.get("questions", [])
    if not questions:
        print(f"  {RED}✗ No questions to answer, skipping{RESET}")
        return

    # Simulate student answers (pick "A" for all — naive strategy)
    answers = [
        {"question_id": q["question_id"], "answer": "A"}
        for q in questions
    ]
    print(f"  Submitting {len(answers)} answer(s) (all 'A')...")

    result = await submit_answers(
        workspace=TEST_WS,
        batch_id=gen_result["batch_id"],
        answers=answers,
        language=LANG,
    )

    print(f"\n  {BOLD}Return keys:{RESET} {list(result.keys())}")

    # Per-question results
    results = result.get("results", [])
    for r in results:
        judged = r.get("judged_result", "?")
        icon = f"{GREEN}✓{RESET}" if judged == "correct" else f"{RED}✗{RESET}"
        print(
            f"  {icon} {r.get('question_id')}: "
            f"user={r.get('user_answer')} correct={r.get('correct_answer')} → {judged}"
        )
        # Verify explanation is returned
        assert "explanation" in r, "Missing explanation in result"

    # Score
    score = result.get("score", {})
    print(f"\n  {BOLD}Score:{RESET} {score.get('correct')}/{score.get('total')} "
          f"(accuracy={score.get('accuracy', 0):.2%})")

    # Check trace now has answer nodes
    ws = Path(TEST_WS)
    traces_dir = ws / "memory" / "traces"
    batch_id = gen_result["batch_id"]
    trace_file = traces_dir / f"{batch_id}.json"
    if trace_file.exists():
        tree_data = json.loads(trace_file.read_text())
        nodes = tree_data.get("nodes", {})
        answer_nodes = {k: v for k, v in nodes.items() if v.get("node_type") == "answer"}
        print(f"  {GREEN}✓{RESET} trace has {len(answer_nodes)} answer node(s)")
    else:
        print(f"  {RED}✗{RESET} trace file not found: {trace_file}")

    # Check memory docs updated after submit
    print(f"\n  {BOLD}Memory docs after submit:{RESET}")
    for doc in ("memory.md", "weakness.md", "reflection.md"):
        p = ws / "memory" / doc
        if p.exists():
            size = len(p.read_text())
            print(f"  {GREEN}✓{RESET} {doc}: {size} chars")
        else:
            print(f"  {DIM}○{RESET} {doc}: not created")

    return result


# ── Main ───────────────────────────────────────────────────────────────

async def main():
    ws = Path(TEST_WS)
    if ws.exists():
        print(f"  Cleaning previous test workspace: {ws}")
        shutil.rmtree(ws)

    try:
        await test_solve()
        gen_result = await test_generate()
        await test_submit(gen_result)
    finally:
        section("Final workspace tree")
        # Print directory tree (first 3 levels)
        for p in sorted(ws.rglob("*")):
            rel = p.relative_to(ws)
            depth = len(rel.parts)
            if depth > 3:
                continue
            indent = "  " * depth
            if p.is_file():
                size = p.stat().st_size
                print(f"  {indent}{p.name} ({size:,} bytes)")
            else:
                print(f"  {indent}{p.name}/")

    print(f"\n  {GREEN}{BOLD}All tests completed.{RESET}\n")


if __name__ == "__main__":
    asyncio.run(main())
