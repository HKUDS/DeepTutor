#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Interactive CLI for testing the refactored question module.

Usage:
    python src/agents/question/cli.py

Features:
- Real-time progress display during generation
- Saves all intermediate files (templates, traces, per-question results)
  to a per-batch directory under the output folder
- Detailed summary with question previews at the end
- Interactive answering mode after question generation
- Integrated with PersonalizationService for memory recording
"""

from __future__ import annotations

import asyncio
from pathlib import Path
import sys
from typing import Any

# Ensure project root import works when running as a script
PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv

load_dotenv(PROJECT_ROOT / "DeepTutor.env", override=False)
load_dotenv(PROJECT_ROOT / ".env", override=False)

from src.agents.question import AgentCoordinator
from src.knowledge.config import KNOWLEDGE_BASES_DIR
from src.knowledge.manager import KnowledgeBaseManager
from src.services.llm.config import get_llm_config


# ── Formatting helpers ────────────────────────────────────────────────

BOLD = "\033[1m"
DIM = "\033[2m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
CYAN = "\033[96m"
MAGENTA = "\033[95m"
RESET = "\033[0m"
CHECK = f"{GREEN}✓{RESET}"
CROSS = f"{RED}✗{RESET}"
ARROW = f"{CYAN}→{RESET}"


def _hr(char: str = "─", width: int = 70) -> str:
    return f"{DIM}{char * width}{RESET}"


def _header(title: str) -> None:
    print(f"\n{_hr('━')}")
    print(f"  {BOLD}{title}{RESET}")
    print(_hr("━"))


def _prompt_non_empty(message: str, default: str | None = None) -> str:
    suffix = f" [{DIM}{default}{RESET}]" if default else ""
    while True:
        raw = input(f"  {message}{suffix}: ").strip()
        if raw:
            return raw
        if default is not None:
            return default
        print(f"  {RED}Input cannot be empty, please try again.{RESET}")


def _list_kbs() -> list[str]:
    """Fetch available knowledge bases from the local KB manager."""
    try:
        manager = KnowledgeBaseManager(str(KNOWLEDGE_BASES_DIR))
        return manager.list_knowledge_bases()
    except Exception:
        return []


def _select_kb() -> str:
    """Show a numbered list of KBs and let the user pick one."""
    kbs = _list_kbs()
    if not kbs:
        print(f"  {YELLOW}No existing knowledge base was found. Please enter one manually.{RESET}")
        return _prompt_non_empty("KB name", "ai_textbook")

    print(f"\n  {BOLD}Available knowledge bases:{RESET}")
    for i, name in enumerate(kbs, 1):
        print(f"    {CYAN}{i}{RESET}) {name}")
    print(f"    {CYAN}0{RESET}) Enter manually")

    while True:
        raw = input(f"  Select [{DIM}1{RESET}]: ").strip()
        if not raw:
            return kbs[0]
        if raw == "0":
            return _prompt_non_empty("KB name")
        try:
            idx = int(raw)
            if 1 <= idx <= len(kbs):
                return kbs[idx - 1]
        except ValueError:
            # Allow typing a name directly
            if raw in kbs:
                return raw
        print(f"  {RED}Invalid selection, please try again.{RESET}")


def _prompt_int(message: str, default: int) -> int:
    while True:
        raw = input(f"  {message} [{DIM}{default}{RESET}]: ").strip()
        if not raw:
            return default
        try:
            value = int(raw)
            if value > 0:
                return value
        except ValueError:
            pass
        print(f"  {RED}Please enter a positive integer.{RESET}")


# ── Progress callback ────────────────────────────────────────────────

async def _cli_progress(data: dict[str, Any]) -> None:
    """Real-time progress callback printed to terminal."""
    msg_type = data.get("type", "")

    if msg_type == "progress":
        stage = data.get("stage", "")
        if stage == "idea_loop":
            rd = data.get("current_round", "")
            mx = data.get("max_rounds", "")
            if rd:
                print(f"    {MAGENTA}🔄 Idea loop{RESET} round {rd}/{mx}")
        elif stage == "generating":
            cur = data.get("current", "")
            tot = data.get("total", "")
            qid = data.get("question_id", "")
            if cur and tot:
                print(f"    {CYAN}📝 Generating{RESET} {cur}/{tot}  {DIM}{qid}{RESET}")
        elif stage == "complete":
            comp = data.get("completed", "?")
            tot = data.get("total", "?")
            print(f"    {GREEN}✅ Complete{RESET} {comp}/{tot}")
        elif stage in ("parsing", "extracting", "uploading"):
            status = data.get("status", "")
            print(f"    {YELLOW}📄 {stage}{RESET} {status}")

    elif msg_type == "templates_ready":
        count = data.get("count", 0)
        print(f"    {GREEN}📋 Templates ready{RESET} {count}")

    elif msg_type == "idea_round":
        rd = data.get("round", "?")
        fb = data.get("feedback", "")
        cont = data.get("continue_loop", False)
        status = "Continue refining" if cont else "Finalized"
        print(f"    {MAGENTA}💡 Idea round {rd}{RESET} → {status}")
        if fb:
            print(f"       {DIM}Feedback: {fb[:100]}{RESET}")

    elif msg_type == "question_update":
        qid = data.get("question_id", "")
        attempt = data.get("attempt", 1)
        max_att = data.get("max_attempts", "?")
        print(f"    {CYAN}⚙  {qid}{RESET} generation (attempt {attempt}/{max_att})")

    elif msg_type == "validating":
        qid = data.get("question_id", "")
        attempt = data.get("attempt", 1)
        validation = data.get("validation", {})
        decision = validation.get("decision", "?")
        icon = CHECK if decision == "approve" else CROSS
        print(f"    {YELLOW}🔍 {qid}{RESET} validation -> {icon} {decision}")

    elif msg_type == "result":
        qid = data.get("question_id", "")
        validation = data.get("validation", {})
        approved = validation.get("approved", False)
        attempts = data.get("attempts", 1)
        icon = CHECK if approved else CROSS
        print(f"    {icon} {BOLD}{qid}{RESET} ({attempts}  attempts)")


# ── PersonalizationService startup ────────────────────────────────────

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
        print(f"\n  {RED}WARNING: EventBus failed to start: {exc}{RESET}")
        ok = False
    try:
        from src.personalization.service import get_personalization_service

        svc = get_personalization_service()
        await svc.start()
    except Exception as exc:
        print(f"\n  {RED}WARNING: PersonalizationService failed to start: {exc}{RESET}")
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


# ── Result display ────────────────────────────────────────────────────

def _print_summary(summary: dict[str, Any]) -> None:
    _header("Summary")
    success = summary.get("success", False)
    status_icon = f"{GREEN}SUCCESS{RESET}" if success else f"{RED}FAILED{RESET}"
    print(f"  Status:     {status_icon}")
    print(f"  Source:     {summary.get('source', '?')}")
    print(f"  Requested:     {summary.get('requested', '?')} questions")
    print(f"  Completed:     {GREEN}{summary.get('completed', 0)}{RESET}")
    print(f"  Failed:     {RED}{summary.get('failed', 0)}{RESET}")
    print(f"  Template count:   {summary.get('template_count', '?')}")

    batch_dir = summary.get("batch_dir")
    if batch_dir:
        print(f"  Output directory: {CYAN}{batch_dir}{RESET}")

    results = summary.get("results", []) or []
    if results:
        print(f"\n  {BOLD}Question preview:{RESET}")
        for i, item in enumerate(results, 1):
            qa = item.get("qa_pair", {})
            approved = item.get("success", False)
            icon = CHECK if approved else CROSS
            q_type = qa.get("question_type", "unknown")
            question = str(qa.get("question", "")).replace("\n", " ")[:100]
            attempts = len(item.get("attempts", []))

            # Tool usage info
            tool_plan = qa.get("metadata", {}).get("tool_plan", {})
            tools_used = []
            if tool_plan.get("use_rag"):
                tools_used.append("rag")
            if tool_plan.get("use_web"):
                tools_used.append("web")
            if tool_plan.get("use_code"):
                tools_used.append("code")
            tool_str = f" {DIM}[{', '.join(tools_used)}]{RESET}" if tools_used else ""

            print(f"  {icon} {i}. [{q_type}]{tool_str} {DIM}({attempts} attempts){RESET}")
            print(f"     {question}...")

    print()


# ── Interactive answering ─────────────────────────────────────────────

def _display_question(idx: int, qa: dict[str, Any]) -> None:
    """Display a single question for the user to answer."""
    q_type = qa.get("question_type", "written")
    question_text = qa.get("question", "")
    options = qa.get("options") or {}

    print(f"\n  {BOLD}Question {idx}{RESET}  [{q_type}]")
    print(_hr())
    print(f"  {question_text}")

    if options:
        print()
        for key in sorted(options.keys()):
            print(f"    {CYAN}{key}{RESET}. {options[key]}")
    print(_hr())


def _judge_answer(user_answer: str, correct_answer: str, q_type: str) -> str:
    """Simple answer judgement. Returns 'correct', 'wrong', or 'partial'."""
    ua = user_answer.strip().lower()
    ca = correct_answer.strip().lower()
    if not ua:
        return "skipped"
    if q_type == "choice":
        ua_letter = ua.strip("().）（ ").upper()
        ca_letter = ca.strip("().）（ ").upper()
        if ua_letter and ca_letter:
            return "correct" if ua_letter == ca_letter else "wrong"
    if ua == ca:
        return "correct"
    if ua in ca or ca in ua:
        return "partial"
    return "pending"


async def _run_answer_session(summary: dict[str, Any]) -> None:
    """Interactive answering session after question generation."""
    results = summary.get("results", []) or []
    approved_results = [r for r in results if r.get("success")]
    if not approved_results:
        print(f"  {YELLOW}No available questions to answer.{RESET}")
        return

    batch_dir = summary.get("batch_dir", "")
    trace_id = Path(batch_dir).name if batch_dir else ""

    _header(f"Answering Session ({len(approved_results)} questions)")
    print(f"  {DIM}Press Enter to skip this question, or type /quit to exit the session.{RESET}\n")

    answers_recorded = 0
    correct_count = 0
    wrong_count = 0
    skipped_count = 0

    for i, item in enumerate(approved_results, 1):
        qa = item.get("qa_pair", {})
        question_id = qa.get("question_id", f"q_{i}")
        q_type = qa.get("question_type", "written")
        correct_answer = str(qa.get("correct_answer", ""))

        _display_question(i, qa)

        try:
            user_input = input(f"  {ARROW} Your answer: ").strip()
        except (EOFError, KeyboardInterrupt):
            print(f"\n  {YELLOW}Answering interrupted.{RESET}")
            break

        if user_input.lower() in ("/quit", "/exit", "/q"):
            print(f"  {DIM}Exiting answer session.{RESET}")
            break

        if not user_input:
            skipped_count += 1
            print(f"  {DIM}(skipped){RESET}")
            continue

        judged = _judge_answer(user_input, correct_answer, q_type)

        if judged == "correct":
            print(f"  {CHECK} {GREEN}Correct!{RESET}")
            correct_count += 1
        elif judged == "wrong":
            print(f"  {CROSS} {RED}Incorrect{RESET}  Correct answer: {GREEN}{correct_answer}{RESET}")
            wrong_count += 1
        elif judged == "partial":
            print(f"  {YELLOW}~ Partial match{RESET}  Reference answer: {correct_answer}")
        elif judged == "skipped":
            skipped_count += 1
            print(f"  {DIM}(skipped){RESET}")
            continue
        else:
            print(f"  {YELLOW}? Pending review{RESET}  Reference answer: {correct_answer}")

        explanation = qa.get("explanation", "")
        if explanation:
            short_exp = explanation[:200]
            if len(explanation) > 200:
                short_exp += "..."
            print(f"  {DIM}Explanation: {short_exp}{RESET}")

        # Record to PersonalizationService
        if trace_id:
            try:
                from src.personalization.service import get_personalization_service

                svc = get_personalization_service()
                ok = await svc.record_user_answer(
                    trace_id=trace_id,
                    question_id=question_id,
                    user_answer=user_input,
                    judged_result=judged,
                )
                if ok:
                    answers_recorded += 1
            except Exception:
                pass

    # Flush trace + run memory agents once with the complete trace
    if answers_recorded > 0 and trace_id:
        print(f"\n  {DIM}Syncing answer memory...{RESET}", end="", flush=True)
        await _flush_events()
        try:
            from src.personalization.service import get_personalization_service
            svc = get_personalization_service()
            await svc.flush_memory_agents(trace_id)
        except Exception:
            pass
        print(f" {CHECK}")

    # Print answer session summary
    _header("Answer Results")
    total = correct_count + wrong_count + skipped_count
    print(f"  Total:   {total}")
    print(f"  Correct:   {GREEN}{correct_count}{RESET}")
    print(f"  Incorrect:   {RED}{wrong_count}{RESET}")
    print(f"  Skipped:   {DIM}{skipped_count}{RESET}")
    if answers_recorded > 0:
        print(f"  {CHECK} Recorded {answers_recorded} answer records to the memory system")
    print()


# ── Coordinator builder ───────────────────────────────────────────────

def _build_coordinator(
    kb_name: str, output_dir: str, language: str
) -> AgentCoordinator:
    try:
        llm_config = get_llm_config()
        return AgentCoordinator(
            api_key=llm_config.api_key,
            base_url=llm_config.base_url,
            api_version=getattr(llm_config, "api_version", None),
            kb_name=kb_name,
            output_dir=output_dir,
            language=language,
        )
    except Exception:
        return AgentCoordinator(
            kb_name=kb_name, output_dir=output_dir, language=language
        )


# ── Mode runners ──────────────────────────────────────────────────────

async def _run_topic_mode(coordinator: AgentCoordinator) -> None:
    _header("Topic Mode")
    user_topic = _prompt_non_empty("Topic (e.g. Lagrange multipliers)")
    preference = input(f"  Preference (optional): ").strip()
    num_questions = _prompt_int("Number of questions", 3)

    print(f"\n  {ARROW} Generating {BOLD}{num_questions}{RESET} questions...")
    print(_hr())

    coordinator.set_ws_callback(_cli_progress)
    summary = await coordinator.generate_from_topic(
        user_topic=user_topic,
        preference=preference,
        num_questions=num_questions,
    )

    # Wait for memory system to process the generation event
    print(f"  {DIM}Syncing memory system...{RESET}", end="", flush=True)
    await _flush_events()
    print(f" {CHECK}")

    _print_summary(summary)

    # Offer interactive answering
    approved = [r for r in (summary.get("results") or []) if r.get("success")]
    if approved:
        try:
            choice = input(f"  {ARROW} Start answering? (y/n) [{DIM}y{RESET}]: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            choice = "n"
        if choice != "n":
            await _run_answer_session(summary)


async def _run_mimic_mode(coordinator: AgentCoordinator) -> None:
    _header("Mimic Mode")
    mode = _prompt_non_empty("Input mode [upload/parsed]", "parsed").lower()
    if mode not in {"upload", "parsed"}:
        print(f"  {YELLOW}Invalid mode, using parsed.{RESET}")
        mode = "parsed"

    if mode == "upload":
        exam_path = _prompt_non_empty("PDF path")
    else:
        exam_path = _prompt_non_empty("Parsed exam directory path")

    max_questions = _prompt_int("Maximum question count", 5)

    print(f"\n  {ARROW} Starting parsing and generation...")
    print(_hr())

    coordinator.set_ws_callback(_cli_progress)
    summary = await coordinator.generate_from_exam(
        exam_paper_path=exam_path,
        max_questions=max_questions,
        paper_mode=mode,
    )

    # Wait for memory system to process the generation event
    print(f"  {DIM}Syncing memory system...{RESET}", end="", flush=True)
    await _flush_events()
    print(f" {CHECK}")

    _print_summary(summary)

    # Offer interactive answering
    approved = [r for r in (summary.get("results") or []) if r.get("success")]
    if approved:
        try:
            choice = input(f"  {ARROW} Start answering? (y/n) [{DIM}y{RESET}]: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            choice = "n"
        if choice != "n":
            await _run_answer_session(summary)


# ── Main ──────────────────────────────────────────────────────────────

async def main() -> None:
    print(f"\n{BOLD}{'=' * 70}{RESET}")
    print(f"  {BOLD}{CYAN}DeepTutor Question Module CLI{RESET}")
    print(f"{BOLD}{'=' * 70}{RESET}")

    # Start PersonalizationService for memory recording
    print(f"  {DIM}Initializing memory system...{RESET}", end="", flush=True)
    mem_ok = await _ensure_personalization()
    print(f" {CHECK}" if mem_ok else f" {CROSS}")

    kb_name = _select_kb()
    language = _prompt_non_empty("Language [en/zh]", "zh").lower()
    if language not in {"en", "zh"}:
        print(f"  {YELLOW}Invalid language, using zh.{RESET}")
        language = "zh"

    default_output = str(PROJECT_ROOT / "data" / "user" / "question")
    output_dir = _prompt_non_empty(f"Output directory", default_output)

    coordinator = _build_coordinator(
        kb_name=kb_name,
        output_dir=output_dir,
        language=language,
    )

    print(f"\n  {DIM}Configuration: KB={kb_name}, language={language}, output={output_dir}{RESET}")

    while True:
        print(f"\n  {BOLD}Select a mode:{RESET}")
        print(f"    {CYAN}1{RESET}) Topic Mode - generate from a topic")
        print(f"    {CYAN}2{RESET}) Mimic Mode - mimic an exam paper")
        print(f"    {CYAN}q{RESET}) Exit")
        choice = input(f"  {ARROW} ").strip().lower()

        try:
            if choice == "1":
                await _run_topic_mode(coordinator)
            elif choice == "2":
                await _run_mimic_mode(coordinator)
            elif choice in {"q", "quit", "exit"}:
                print(f"\n  {DIM}Exited.{RESET}\n")
                break
            else:
                print(f"  {RED}Invalid input, please try again.{RESET}")
        except KeyboardInterrupt:
            print(f"\n  {YELLOW}The current task has been interrupted.{RESET}")
        except Exception as exc:
            print(f"\n  {RED}Run failed: {exc}{RESET}")
            import traceback
            traceback.print_exc()

    # Cleanup
    try:
        from src.core.event_bus import get_event_bus

        await get_event_bus().stop()
    except Exception:
        pass


if __name__ == "__main__":
    asyncio.run(main())
