#!/usr/bin/env python
"""
CLI test script for the Solve Agent (Plan -> ReAct -> Write).

Usage:
    # Single question mode
    python -m src.agents.solve.cli "What is linear convolution?" --kb ai-textbook

    # Detailed (iterative) answer mode
    python -m src.agents.solve.cli "What is linear convolution?" --detailed

    # Interactive mode (default when no question given)
    python -m src.agents.solve.cli
    python -m src.agents.solve.cli -i --language zh

Features:
    - Integrated with PersonalizationService for memory recording
    - EventBus enabled for post-solve memory updates
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

# Ensure project root is on sys.path
_project_root = Path(__file__).resolve().parent.parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from dotenv import load_dotenv

load_dotenv(_project_root / "DeepTutor.env", override=False)
load_dotenv(_project_root / ".env", override=False)


def _list_knowledge_bases() -> list[str]:
    """List available knowledge bases from disk."""
    try:
        from src.knowledge.manager import KnowledgeBaseManager
        mgr = KnowledgeBaseManager()
        return mgr.list_knowledge_bases()
    except Exception:
        # Fallback: scan directory
        kb_dir = _project_root / "data" / "knowledge_bases"
        if kb_dir.exists():
            return [d.name for d in kb_dir.iterdir() if d.is_dir() and not d.name.startswith(".")]
        return []


def _pick_kb(current_kb: str) -> str:
    """Prompt user to pick a knowledge base, returns selected name."""
    kbs = _list_knowledge_bases()
    if not kbs:
        print("  (no knowledge bases found, using default)")
        return current_kb

    print("\n  Available knowledge bases:")
    for i, name in enumerate(kbs, 1):
        marker = " <-" if name == current_kb else ""
        print(f"    {i}. {name}{marker}")
    print(f"    0. Keep current ({current_kb})")

    try:
        choice = input("  Select [0]: ").strip()
    except (EOFError, KeyboardInterrupt):
        return current_kb

    if not choice or choice == "0":
        return current_kb

    try:
        idx = int(choice) - 1
        if 0 <= idx < len(kbs):
            return kbs[idx]
    except ValueError:
        # Treat raw text as kb name
        if choice in kbs:
            return choice

    print(f"  Invalid choice, keeping: {current_kb}")
    return current_kb


async def _ensure_personalization() -> bool:
    """Start EventBus and PersonalizationService for in-process memory.

    Returns True if both services started successfully.
    """
    ok = True
    try:
        from src.core.event_bus import get_event_bus

        bus = get_event_bus()
        await bus.start()
    except Exception as exc:
        print(f"\n  WARNING: EventBus failed to start: {exc}")
        ok = False
    try:
        from src.personalization.service import get_personalization_service

        svc = get_personalization_service()
        await svc.start()
    except Exception as exc:
        print(f"\n  WARNING: PersonalizationService failed to start: {exc}")
        ok = False
    return ok


async def _flush_events() -> None:
    """Wait for EventBus to finish processing all pending events."""
    try:
        from src.core.event_bus import get_event_bus

        bus = get_event_bus()
        await bus.flush(timeout=60.0)
    except Exception:
        pass


def _print_result(result: dict) -> None:
    print("\n" + "=" * 60)
    print("FINAL ANSWER")
    print("=" * 60)
    print(result["final_answer"])
    print("=" * 60)
    print(f"Output directory: {result['output_dir']}")
    print(f"Steps: {result.get('completed_steps', '?')}/{result.get('total_steps', '?')}")
    print(f"ReAct entries: {result.get('total_react_entries', '?')}")
    print(f"Plan revisions: {result.get('plan_revisions', 0)}")


async def _make_solver(kb_name: str, language: str, output_dir: str | None = None):
    from src.agents.solve import MainSolver
    solver = MainSolver(kb_name=kb_name, language=language, output_base_dir=output_dir)
    await solver.ainit()
    return solver


async def run_interactive(kb_name: str, language: str, output_dir: str | None, detailed: bool = False) -> None:
    print("\n" + "=" * 60)
    mode_label = "Detailed" if detailed else "Simple"
    print(f"  DeepTutor Solve Agent — Interactive Mode ({mode_label})")
    print("=" * 60)

    print("  Initializing memory system...", end="", flush=True)
    mem_ok = await _ensure_personalization()
    print(" done" if mem_ok else " FAILED (see warnings above)")

    while True:
        # --- Step 1: pick knowledge base ---
        kb_name = _pick_kb(kb_name)
        print(f"  KB: {kb_name}  |  Language: {language}  |  Detailed: {detailed}")

        # --- Step 2: enter question ---
        try:
            question = input("\nQuestion (/quit to exit)> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nBye!")
            break

        if not question:
            continue
        if question.lower() in ("/quit", "/exit", "/q"):
            print("Bye!")
            break

        # --- Step 3: solve ---
        try:
            solver = await _make_solver(kb_name, language, output_dir)
            result = await solver.solve(question, detailed=detailed)
            _print_result(result)
        except Exception as exc:
            print(f"\n  Error: {exc}\n")
            import traceback
            traceback.print_exc()

        # Wait for memory system to process the solve event
        print("  Syncing memory...", end="", flush=True)
        await _flush_events()
        print(" done")
        print()


async def main() -> None:
    parser = argparse.ArgumentParser(
        description="DeepTutor Solve Agent — Plan -> ReAct -> Write",
    )
    parser.add_argument("question", nargs="?", default=None, help="Question to solve (omit for interactive mode)")
    parser.add_argument("--kb", default="ai-textbook", help="Knowledge base name (default: ai-textbook)")
    parser.add_argument("--language", default="en", help="Output language: en / zh (default: en)")
    parser.add_argument("--output-dir", default=None, help="Override output base directory")
    parser.add_argument("-i", "--interactive", action="store_true", help="Start in interactive mode")
    parser.add_argument("--detailed", action="store_true", default=None,
                        help="Enable iterative detailed answer mode")
    args = parser.parse_args()

    if args.interactive or args.question is None:
        await run_interactive(args.kb, args.language, args.output_dir, args.detailed)
    else:
        await _ensure_personalization()
        solver = await _make_solver(args.kb, args.language, args.output_dir)
        result = await solver.solve(args.question, detailed=args.detailed)
        _print_result(result)
        print("  Syncing memory...", end="", flush=True)
        await _flush_events()
        print(" done")

    # Cleanup
    try:
        from src.core.event_bus import get_event_bus
        await get_event_bus().stop()
    except Exception:
        pass


if __name__ == "__main__":
    asyncio.run(main())
