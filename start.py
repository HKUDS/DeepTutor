#!/usr/bin/env python
"""
DeepTutor CLI Launcher

Unified entry point for:
1. Solver system  (same logic as ``python -m src.agents.solve.cli``)
2. Question generation system  (same logic as ``python src/agents/question/cli.py``)
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

if sys.platform == "win32":
    import io

    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")

PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv

load_dotenv(PROJECT_ROOT / "DeepTutor.env", override=False)
load_dotenv(PROJECT_ROOT / ".env", override=False)

from src.knowledge.manager import KnowledgeBaseManager
from src.logging import get_logger
from src.services.llm.config import get_llm_config

logger = get_logger("CLI", console_output=True, file_output=True)

# ── ANSI helpers (reused from question CLI) ──────────────────────────

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


# ── Shared infrastructure ────────────────────────────────────────────


def _list_knowledge_bases() -> list[str]:
    try:
        mgr = KnowledgeBaseManager()
        return mgr.list_knowledge_bases()
    except Exception:
        kb_dir = PROJECT_ROOT / "data" / "knowledge_bases"
        if kb_dir.exists():
            return [d.name for d in kb_dir.iterdir() if d.is_dir() and not d.name.startswith(".")]
        return []


def _select_kb(current: str = "ai-textbook") -> str:
    kbs = _list_knowledge_bases()
    if not kbs:
        print(f"  {YELLOW}No knowledge bases found, using default: {current}{RESET}")
        return current

    print(f"\n  {BOLD}Available knowledge bases:{RESET}")
    for i, name in enumerate(kbs, 1):
        marker = f" {CYAN}<-{RESET}" if name == current else ""
        print(f"    {CYAN}{i}{RESET}) {name}{marker}")
    print(f"    {CYAN}0{RESET}) Keep current ({current})")

    while True:
        raw = input(f"  Select [{DIM}1{RESET}]: ").strip()
        if not raw:
            return kbs[0]
        if raw == "0":
            return current
        try:
            idx = int(raw) - 1
            if 0 <= idx < len(kbs):
                return kbs[idx]
        except ValueError:
            if raw in kbs:
                return raw
        print(f"  {RED}Invalid selection, please try again.{RESET}")


async def _ensure_personalization() -> bool:
    """Start EventBus and PersonalizationService for in-process memory."""
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


# ── Solve mode ───────────────────────────────────────────────────────


async def run_solve_mode(kb_name: str) -> None:
    """Solve a question — mirrors ``src.agents.solve.cli`` logic."""
    _header("Solve System (Solver)")

    kb_name = _select_kb(current=kb_name)
    print(f"  {CHECK} Knowledge base: {BOLD}{kb_name}{RESET}")

    language = input(f"  Language (en/zh) [{DIM}en{RESET}]: ").strip().lower() or "en"
    if language not in {"en", "zh"}:
        language = "en"

    print(f"\n  Enter your question (multi-line input, blank line to finish):")
    print(_hr())

    lines: list[str] = []
    while True:
        line = input()
        if not line:
            break
        lines.append(line)

    if not lines:
        print(f"  {YELLOW}No question entered, returning to the main menu.{RESET}")
        return

    question = "\n".join(lines)

    print(f"\n  {ARROW} Mode: Plan -> ReAct -> Write")
    print(f"  {DIM}Initializing Solver...{RESET}")

    try:
        from src.agents.solve import MainSolver

        solver = MainSolver(kb_name=kb_name, language=language)
        await solver.ainit()

        result = await solver.solve(question)

        _header("Solve Complete")
        print(f"  Output directory:  {CYAN}{result['output_dir']}{RESET}")
        print(f"  Steps completed:  {result.get('completed_steps', '?')}/{result.get('total_steps', '?')}")
        print(f"  ReAct entries: {result.get('total_react_entries', '?')}")
        print(f"  Plan revisions:  {result.get('plan_revisions', 0)}")

        final_answer = result.get("final_answer", "")
        if final_answer:
            print(f"\n  {BOLD}Answer preview:{RESET}")
            print(_hr())
            preview_lines = final_answer.split("\n")[:20]
            preview = "\n".join(preview_lines)
            if len(final_answer.split("\n")) > 20:
                preview += f"\n\n  {DIM}... (see the output file for the full content) ...{RESET}"
            print(preview)
            print(_hr())

    except Exception as e:
        _header("Solve Failed")
        print(f"  {RED}{e}{RESET}")
        import traceback
        traceback.print_exc()

    print(f"  {DIM}Syncing memory...{RESET}", end="", flush=True)
    await _flush_events()
    print(f" {CHECK}")


# ── Question generation mode ─────────────────────────────────────────


async def _cli_progress(data: dict) -> None:
    """Real-time progress callback for question generation."""
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
        cont = data.get("continue_loop", False)
        status = "Continue refining" if cont else "Finalized"
        print(f"    {MAGENTA}💡 Idea round {rd}{RESET} → {status}")
    elif msg_type == "question_update":
        qid = data.get("question_id", "")
        attempt = data.get("attempt", 1)
        max_att = data.get("max_attempts", "?")
        print(f"    {CYAN}⚙  {qid}{RESET} generation (attempt {attempt}/{max_att})")
    elif msg_type == "validating":
        qid = data.get("question_id", "")
        decision = data.get("validation", {}).get("decision", "?")
        icon = CHECK if decision == "approve" else CROSS
        print(f"    {YELLOW}🔍 {qid}{RESET} validation -> {icon} {decision}")
    elif msg_type == "result":
        qid = data.get("question_id", "")
        approved = data.get("validation", {}).get("approved", False)
        attempts = data.get("attempts", 1)
        icon = CHECK if approved else CROSS
        print(f"    {icon} {BOLD}{qid}{RESET} ({attempts}  attempts)")


def _print_question_summary(summary: dict) -> None:
    _header("Question Generation Summary")
    success = summary.get("success", False)
    status_icon = f"{GREEN}SUCCESS{RESET}" if success else f"{RED}FAILED{RESET}"
    print(f"  Status:     {status_icon}")
    print(f"  Source:     {summary.get('source', '?')}")
    print(f"  Requested:     {summary.get('requested', '?')} questions")
    print(f"  Completed:     {GREEN}{summary.get('completed', 0)}{RESET}")
    print(f"  Failed:     {RED}{summary.get('failed', 0)}{RESET}")

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
            print(f"  {icon} {i}. [{q_type}] {DIM}({attempts} attempts){RESET}")
            print(f"     {question}...")
    print()


def _prompt_non_empty(message: str, default: str | None = None) -> str:
    suffix = f" [{DIM}{default}{RESET}]" if default else ""
    while True:
        raw = input(f"  {message}{suffix}: ").strip()
        if raw:
            return raw
        if default is not None:
            return default
        print(f"  {RED}Input cannot be empty, please try again.{RESET}")


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


# ── Interactive answering session ─────────────────────────────────────


def _display_question(idx: int, qa: dict) -> None:
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


async def _run_answer_session(summary: dict) -> None:
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

    _header("Answer Results")
    total = correct_count + wrong_count + skipped_count
    print(f"  Total:   {total}")
    print(f"  Correct:   {GREEN}{correct_count}{RESET}")
    print(f"  Incorrect:   {RED}{wrong_count}{RESET}")
    print(f"  Skipped:   {DIM}{skipped_count}{RESET}")
    if answers_recorded > 0:
        print(f"  {CHECK} Recorded {answers_recorded} answer records to the memory system")
    print()


# ── Coordinator builder ──────────────────────────────────────────────


def _build_coordinator(kb_name: str, output_dir: str, language: str):
    from src.agents.question import AgentCoordinator
    from src.services.llm.config import get_llm_config as _get_llm

    try:
        cfg = _get_llm()
        return AgentCoordinator(
            api_key=cfg.api_key,
            base_url=cfg.base_url,
            api_version=getattr(cfg, "api_version", None),
            kb_name=kb_name,
            output_dir=output_dir,
            language=language,
        )
    except Exception:
        return AgentCoordinator(
            kb_name=kb_name, output_dir=output_dir, language=language,
        )


async def run_question_mode(kb_name: str) -> None:
    """Generate questions — mirrors ``src/agents/question/cli.py`` logic."""
    _header("Question Generation System (Question Generator)")

    kb_name = _select_kb(current=kb_name)
    print(f"  {CHECK} Knowledge base: {BOLD}{kb_name}{RESET}")

    language = input(f"  Language (en/zh) [{DIM}zh{RESET}]: ").strip().lower() or "zh"
    if language not in {"en", "zh"}:
        language = "zh"

    default_output = str(PROJECT_ROOT / "data" / "user" / "question")
    output_dir = _prompt_non_empty("Output directory", default_output)

    coordinator = _build_coordinator(kb_name=kb_name, output_dir=output_dir, language=language)

    print(f"\n  {BOLD}Select a mode:{RESET}")
    print(f"    {CYAN}1{RESET}) Topic mode - generate from a topic")
    print(f"    {CYAN}2{RESET}) Mimic mode - mimic an exam paper")

    mode_choice = input(f"  {ARROW} ").strip()

    if mode_choice == "2":
        await _run_mimic_submode(coordinator)
    else:
        await _run_topic_submode(coordinator)


async def _run_topic_submode(coordinator) -> None:
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

    print(f"  {DIM}Syncing memory system...{RESET}", end="", flush=True)
    await _flush_events()
    print(f" {CHECK}")

    _print_question_summary(summary)

    approved = [r for r in (summary.get("results") or []) if r.get("success")]
    if approved:
        try:
            ans_choice = input(f"  {ARROW} Start answering? (y/n) [{DIM}y{RESET}]: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            ans_choice = "n"
        if ans_choice != "n":
            await _run_answer_session(summary)


async def _run_mimic_submode(coordinator) -> None:
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

    print(f"  {DIM}Syncing memory system...{RESET}", end="", flush=True)
    await _flush_events()
    print(f" {CHECK}")

    _print_question_summary(summary)

    approved = [r for r in (summary.get("results") or []) if r.get("success")]
    if approved:
        try:
            ans_choice = input(f"  {ARROW} Start answering? (y/n) [{DIM}y{RESET}]: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            ans_choice = "n"
        if ans_choice != "n":
            await _run_answer_session(summary)


# ── Settings ─────────────────────────────────────────────────────────


def show_settings() -> None:
    _header("System Settings")

    try:
        llm_config = get_llm_config()
        print(f"  {BOLD}LLM configuration:{RESET}")
        print(f"    Model:     {llm_config.model or 'N/A'}")
        print(f"    Endpoint:     {llm_config.base_url or 'N/A'}")
        print(f"    API Key:  {'Configured' if llm_config.api_key else 'Not configured'}")
    except Exception as e:
        print(f"  {RED}Load failed: {e}{RESET}")

    kbs = _list_knowledge_bases()
    print(f"\n  {BOLD}Available knowledge bases:{RESET}")
    for i, kb in enumerate(kbs, 1):
        print(f"    {i}. {kb}")

    print(f"\n  {BOLD}Configuration files:{RESET}")
    for name in [".env", "DeepTutor.env"]:
        p = PROJECT_ROOT / name
        status = f"{GREEN}✓{RESET}" if p.exists() else f"{RED}✗{RESET}"
        print(f"    {status} {p}")

    print(f"\n  {DIM}Tip: edit the .env file directly to update the configuration.{RESET}")
    input(f"\n  Press Enter to return to the main menu...")


# ── Main loop ────────────────────────────────────────────────────────


async def run() -> None:
    print(f"\n{BOLD}{'=' * 70}{RESET}")
    print(f"  {BOLD}{CYAN}DeepTutor Evaluation System{RESET}")
    print(f"{BOLD}{'=' * 70}{RESET}")

    try:
        from src.services.setup import init_user_directories

        init_user_directories(PROJECT_ROOT)
    except Exception as e:
        print(f"  {YELLOW}WARNING: Failed to initialize user directories: {e}{RESET}")

    try:
        llm_config = get_llm_config()
        if not llm_config.api_key:
            print(f"  {RED}ERROR: API key is not configured. Please check the .env file.{RESET}")
            sys.exit(1)
    except ValueError as e:
        print(f"  {RED}ERROR: {e}{RESET}")
        sys.exit(1)

    print(f"  {DIM}Initializing memory system...{RESET}", end="", flush=True)
    mem_ok = await _ensure_personalization()
    print(f" {CHECK}" if mem_ok else f" {CROSS}")

    default_kb = "ai-textbook"

    while True:
        try:
            print(f"\n  {BOLD}Select a function:{RESET}")
            print(f"    {CYAN}1{RESET}) Solve System (Solver)")
            print(f"    {CYAN}2{RESET}) Question Generation System (Question Generator)")
            print(f"    {CYAN}3{RESET}) System Settings (Settings)")
            print(f"    {CYAN}q{RESET}) Exit")
            choice = input(f"  {ARROW} ").strip().lower()

            if choice == "1":
                await run_solve_mode(default_kb)
            elif choice == "2":
                await run_question_mode(default_kb)
            elif choice == "3":
                show_settings()
                continue
            elif choice in {"q", "quit", "exit", "4"}:
                print(f"\n  {DIM}Thanks for using DeepTutor!{RESET}\n")
                break
            else:
                print(f"  {RED}Invalid option, please try again.{RESET}")
                continue

            cont = input(f"\n  Continue? (y/n) [{DIM}y{RESET}]: ").strip().lower()
            if cont == "n":
                print(f"\n  {DIM}Thanks for using DeepTutor!{RESET}\n")
                break

        except KeyboardInterrupt:
            print(f"\n\n  {YELLOW}Program interrupted.{RESET}\n")
            break
        except Exception as e:
            print(f"\n  {RED}Incorrect: {e}{RESET}")
            import traceback
            traceback.print_exc()

    # Cleanup EventBus
    try:
        from src.core.event_bus import get_event_bus

        await get_event_bus().stop()
    except Exception:
        pass


def main():
    try:
        asyncio.run(run())
    except Exception as e:
        print(f"  {RED}Startup failed: {e}{RESET}")
        sys.exit(1)


if __name__ == "__main__":
    main()
