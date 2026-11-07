# -*- coding: utf-8 -*-
"""
Simulator Tools — workspace-isolated solve / question / answer tools.

Each tool accepts a ``workspace`` path that determines where all artifacts
(solve outputs, question batches, traces, memory documents) are stored.
Memory agents only see traces inside that workspace.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from pathlib import Path
from typing import Any

# ── Ensure project root is importable ──────────────────────────────────
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from dotenv import load_dotenv

load_dotenv(_PROJECT_ROOT / "DeepTutor.env", override=False)
load_dotenv(_PROJECT_ROOT / ".env", override=False)

import yaml

from src.personalization.memory_reader import (
    MemoryReader,
    _workspace_memory_disabled_var,
    _workspace_reader_var,
)
from src.personalization.trace_forest import TraceForest
from src.personalization.trace_tree import TraceNode, TraceTree
from src.agents.solve.tools import ToolRegistry

logger = logging.getLogger(__name__)


# ======================================================================
# Workspace session
# ======================================================================

class WorkspaceSession:
    """Directory layout manager for one simulated student."""

    def __init__(self, workspace: str) -> None:
        self.root = Path(workspace)
        self.memory_dir = self.root / "memory"
        self.solve_dir = self.root / "solve"
        self.question_dir = self.root / "question"
        for d in (self.memory_dir, self.solve_dir, self.question_dir):
            d.mkdir(parents=True, exist_ok=True)


# ======================================================================
# Tool 1 — solve_question
# ======================================================================

async def solve_question(
    workspace: str,
    kb_name: str,
    question: str,
    language: str = "en",
    enabled_tools: list[str] | None = None,
    enable_memory: bool = True,
    enable_planner_retrieve: bool = True,
    rag_mode: str = "naive",
) -> dict[str, Any]:
    """Solve a question with the full Plan → ReAct → Write pipeline.

    All outputs are saved under ``<workspace>/solve/``.
    Memory agents update ``<workspace>/memory/``.

    Returns
    -------
    dict with keys: question, answer, output_dir, steps,
    completed_steps, citations.
    """
    session = WorkspaceSession(workspace)
    forest: TraceForest | None = None
    token = None
    disable_token = None
    if enable_memory:
        forest = TraceForest(memory_dir=session.memory_dir)
        reader = MemoryReader(forest=forest)
        token = _workspace_reader_var.set(reader)
    else:
        disable_token = _workspace_memory_disabled_var.set(True)

    try:
        from src.agents.solve import MainSolver

        tool_registry = (
            ToolRegistry.create_from_names(enabled_tools, language=language)
            if enabled_tools is not None
            else None
        )

        solver = MainSolver(
            kb_name=kb_name,
            language=language,
            output_base_dir=str(session.solve_dir),
            tool_registry=tool_registry,
            disable_planner_retrieve=not enable_planner_retrieve,
            rag_mode=rag_mode,
        )
        await solver.ainit()
        result = await solver.solve(question)

        # Build trace from scratchpad and register
        scratchpad_path = Path(result["output_dir"]) / "scratchpad.json"
        if enable_memory and forest is not None and scratchpad_path.exists():
            scratchpad_data = json.loads(scratchpad_path.read_text("utf-8"))
            answer_path = str(Path(result["output_dir"]) / "final_answer.md")
            tree = TraceTree.from_scratchpad(
                scratchpad_data,
                task_id=Path(result["output_dir"]).name,
                answer_path=answer_path,
            )
            await forest.register(tree)
            await _run_memory_agents(tree, forest, session.memory_dir, language)

        return {
            "question": question,
            "answer": result.get("final_answer", ""),
            "output_dir": result.get("output_dir", ""),
            "steps": result.get("total_steps", 0),
            "completed_steps": result.get("completed_steps", 0),
            "citations": result.get("citations", []),
        }
    finally:
        if token is not None:
            _workspace_reader_var.reset(token)
        if disable_token is not None:
            _workspace_memory_disabled_var.reset(disable_token)


# ======================================================================
# Tool 2 — generate_questions
# ======================================================================

async def generate_questions(
    workspace: str,
    kb_name: str,
    topic: str,
    preferences: str = "",
    num_questions: int = 3,
    language: str = "en",
    enable_memory: bool = True,
    enable_rag: bool = True,
    enable_web: bool = True,
    include_answers: bool = False,
) -> dict[str, Any]:
    """Generate multiple-choice questions with memory.

    All outputs are saved under ``<workspace>/question/``.
    Returns questions **without** correct answers by default so the student
    agent cannot peek. Set ``include_answers=True`` only for offline
    evaluation/export flows where answer quality must be visible.

    Returns
    -------
    dict with keys: batch_id, batch_dir, num_generated,
    questions (list of {question_id, question, options, question_type});
    when include_answers=True, each item also includes correct_answer and
    explanation if available.
    """
    session = WorkspaceSession(workspace)
    forest: TraceForest | None = None
    token = None
    disable_token = None
    if enable_memory:
        forest = TraceForest(memory_dir=session.memory_dir)
        reader = MemoryReader(forest=forest)
        token = _workspace_reader_var.set(reader)
    else:
        disable_token = _workspace_memory_disabled_var.set(True)

    try:
        from src.agents.question import AgentCoordinator

        coordinator = AgentCoordinator(
            kb_name=kb_name,
            output_dir=str(session.question_dir),
            language=language,
            tool_flags_override={
                "rag_tool": enable_rag,
                "web_search": enable_web,
                "write_code": True,
            },
            enable_idea_rag=enable_rag,
        )
        summary = await coordinator.generate_from_topic(
            user_topic=topic,
            preference=preferences,
            num_questions=num_questions,
            question_type="choice",
        )

        batch_dir = summary.get("batch_dir", "")
        batch_id = Path(batch_dir).name if batch_dir else ""

        # Register trace (without answers — deferred until submit_answers)
        if enable_memory and forest is not None and batch_dir:
            summary_path = Path(batch_dir) / "summary.json"
            if summary_path.exists():
                summary_data = json.loads(summary_path.read_text("utf-8"))
                tree = TraceTree.from_question_summary(
                    summary=summary_data,
                    user_topic=topic,
                    task_id=batch_id,
                    include_answers=False,
                    answer_path=str(summary_path),
                )
                await forest.register(tree)

        # Build question list for the student/evaluator.
        questions: list[dict[str, Any]] = []
        for r in summary.get("results", []):
            if not r.get("success"):
                continue
            qa = r.get("qa_pair", {})
            item = {
                "question_id": qa.get("question_id", ""),
                "question": qa.get("question", ""),
                "options": qa.get("options", {}),
                "question_type": qa.get("question_type", "choice"),
            }
            if include_answers:
                item["correct_answer"] = qa.get("correct_answer", "")
                item["explanation"] = qa.get("explanation", "")
            questions.append(item)

        return {
            "batch_id": batch_id,
            "batch_dir": batch_dir,
            "num_generated": len(questions),
            "questions": questions,
        }
    finally:
        if token is not None:
            _workspace_reader_var.reset(token)
        if disable_token is not None:
            _workspace_memory_disabled_var.reset(disable_token)


# ======================================================================
# Tool 3 — submit_answers
# ======================================================================

async def submit_answers(
    workspace: str,
    batch_id: str,
    answers: list[dict[str, str]],
    language: str = "en",
) -> dict[str, Any]:
    """Submit answers for a previously generated question batch.

    Each entry in *answers* should be ``{"question_id": "q_1", "answer": "A"}``.

    The tool:
    1. Loads the stored correct answers from ``summary.json``.
    2. Auto-judges each answer.
    3. Appends answer nodes to the trace tree.
    4. Runs the three memory agents on the complete trace.

    Returns
    -------
    dict with keys: results (per-question detail), score.
    """
    session = WorkspaceSession(workspace)
    forest = TraceForest(memory_dir=session.memory_dir)
    reader = MemoryReader(forest=forest)

    tree = forest.load_tree(batch_id)
    if tree is None:
        return {"error": f"Trace '{batch_id}' not found", "results": [], "score": {}}

    # Load correct answers from summary.json
    correct_map: dict[str, dict[str, str]] = {}
    summary_path = session.question_dir / batch_id / "summary.json"
    if summary_path.exists():
        summary_data = json.loads(summary_path.read_text("utf-8"))
        for r in summary_data.get("results", []):
            qa = r.get("qa_pair", {})
            qid = qa.get("question_id", "")
            if qid:
                correct_map[qid] = {
                    "correct_answer": qa.get("correct_answer", ""),
                    "question_type": qa.get("question_type", "choice"),
                    "explanation": qa.get("explanation", ""),
                }

    # Judge each answer and attach to trace
    results: list[dict[str, Any]] = []
    for ans in answers:
        qid = ans.get("question_id", "")
        user_answer = ans.get("answer", "")
        info = correct_map.get(qid, {})
        correct_answer = info.get("correct_answer", "")
        explanation = info.get("explanation", "")

        judged = _judge_choice(user_answer, correct_answer)

        # Locate the template node and attach an answer node
        tmpl_node = _find_template_node(tree, qid)
        if tmpl_node is not None:
            answer_short = f"{tmpl_node.short_id}.A1"
            answer_node = TraceNode(
                short_id=answer_short,
                level=3,
                text=user_answer.strip() or qid,
                node_type="answer",
                data={
                    "question_id": qid,
                    "user_answer": user_answer,
                    "judged_result": judged,
                    "question": tmpl_node.data.get("concentration", ""),
                },
                parent=tmpl_node.short_id,
            )
            if answer_short not in tree.nodes:
                tmpl_node.children.append(answer_short)
            tree.nodes[answer_short] = answer_node

        results.append({
            "question_id": qid,
            "user_answer": user_answer,
            "correct_answer": correct_answer,
            "judged_result": judged,
            "explanation": explanation,
        })

    # Re-register trace (now includes answer nodes)
    await forest.register(tree)

    # Run memory agents with the complete trace
    token = _workspace_reader_var.set(reader)
    try:
        await _run_memory_agents(tree, forest, session.memory_dir, language)
    finally:
        _workspace_reader_var.reset(token)

    correct = sum(1 for r in results if r["judged_result"] == "correct")
    wrong = sum(1 for r in results if r["judged_result"] == "wrong")
    total = len(results)

    return {
        "results": results,
        "score": {
            "total": total,
            "correct": correct,
            "wrong": wrong,
            "accuracy": round(correct / total, 4) if total else 0.0,
        },
    }


# ======================================================================
# Internal helpers
# ======================================================================

def _judge_choice(user_answer: str, correct_answer: str) -> str:
    ua = user_answer.strip().upper().strip("().）（ ")
    ca = correct_answer.strip().upper().strip("().）（ ")
    if not ua:
        return "skipped"
    if ua == ca:
        return "correct"
    return "wrong"


def _find_template_node(tree: TraceTree, question_id: str) -> TraceNode | None:
    q_idx = question_id.replace("q_", "")
    short = f"T{q_idx}" if q_idx.isdigit() else f"T{question_id}"
    node = tree.nodes.get(short)
    if node is not None:
        return node
    for n in tree.nodes.values():
        if n.node_type == "template" and n.data.get("question_id") == question_id:
            return n
    return None


# ── Memory-agent runner (standalone, no singleton) ─────────────────────

async def _run_memory_agents(
    trace: TraceTree,
    forest: TraceForest,
    memory_dir: Path,
    language: str,
) -> None:
    """Launch ReflectionAgent, SummaryAgent, WeaknessAgent in parallel."""
    from src.personalization.agents import (
        ReflectionAgent,
        SummaryAgent,
        WeaknessAgent,
    )
    from src.personalization.react_runner import ReActRunner
    from src.personalization.trace_tools import TraceToolkit
    from src.services.path_service import get_path_service

    config_path = get_path_service().project_root / "config" / "memory.yaml"
    config: dict[str, Any] = {}
    if config_path.exists():
        with open(config_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f) or {}

    temperature = config.get("llm", {}).get("temperature", 0.5)
    max_rounds = config.get("memory", {}).get("max_react_rounds", 6)
    agents_cfg = config.get("agents", {})

    toolkit = TraceToolkit(forest, memory_dir)
    session_summary = _build_session_summary(trace)
    full_context = _build_full_context(trace)

    ctx_base: dict[str, str] = {
        "trace_id": trace.trace_id,
        "trace_type": trace.trace_type,
        "question": trace.root.text,
        "answer_path": trace.answer_path,
        "session_summary": session_summary,
        "full_context": full_context,
    }

    log_dir = memory_dir / "logs"
    tasks: list[asyncio.Task] = []

    if agents_cfg.get("reflection", {}).get("enabled", True):
        agent = ReflectionAgent(language=language, temperature=temperature)
        ctx = {**ctx_base, "current_document": _read_md(memory_dir, "reflection.md")}
        tasks.append(asyncio.create_task(
            _run_single_agent(agent, toolkit, ctx, max_rounds, log_dir),
            name="reflection",
        ))

    if agents_cfg.get("summary", {}).get("enabled", True):
        agent = SummaryAgent(language=language, temperature=temperature)
        tasks.append(asyncio.create_task(
            _run_single_agent(agent, toolkit, ctx_base, max_rounds, log_dir),
            name="summary",
        ))

    if agents_cfg.get("weakness", {}).get("enabled", True):
        agent = WeaknessAgent(language=language, temperature=temperature)
        ctx = {**ctx_base, "current_document": _read_md(memory_dir, "weakness.md")}
        tasks.append(asyncio.create_task(
            _run_single_agent(agent, toolkit, ctx, max_rounds, log_dir),
            name="weakness",
        ))

    if tasks:
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for task, result in zip(tasks, results):
            if isinstance(result, Exception):
                logger.error("Memory agent '%s' failed: %s", task.get_name(), result)
            else:
                logger.info("Memory agent '%s' done", task.get_name())


async def _run_single_agent(
    agent: Any,
    toolkit: Any,
    context: dict[str, str],
    max_rounds: int,
    log_dir: Path | None,
) -> None:
    from src.personalization.react_runner import ReActRunner

    system_prompt = agent.get_prompt("system", "")
    user_template = agent.get_prompt("user_template", "")
    if not system_prompt or not user_template:
        return
    initial_context = user_template.format(**context)
    runner = ReActRunner(
        agent=agent,
        toolkit=toolkit,
        max_rounds=max_rounds,
        log_dir=log_dir,
    )
    await runner.run(system_prompt=system_prompt, initial_context=initial_context)


# ── Context builders (mirrored from PersonalizationService) ────────────

def _read_md(memory_dir: Path, filename: str) -> str:
    p = memory_dir / filename
    try:
        return p.read_text(encoding="utf-8").strip() or "(empty document)"
    except FileNotFoundError:
        return "(document not found)"


def _build_session_summary(trace: TraceTree) -> str:
    if trace.trace_type == "solve":
        steps = [n for n in trace.nodes.values() if n.node_type == "step"]
        tools = sorted(trace.tools_used) if trace.tools_used else ["none"]
        total_rounds = sum(1 for n in trace.nodes.values() if n.node_type == "round")
        lines = [
            f"Solve summary: {len(steps)} steps, {total_rounds} ReAct rounds, "
            f"tools: {', '.join(tools)}",
        ]
        for step in steps:
            n_rounds = len(step.children)
            status = step.data.get("status", "?")
            goal = step.data.get("step_goal", step.text)
            lines.append(f'- {step.short_id} "{goal}" ({n_rounds} rounds) -> {status}')
        return "\n".join(lines)

    if trace.trace_type == "question":
        templates = [n for n in trace.nodes.values() if n.node_type == "template"]
        correct = wrong = skipped = 0
        q_lines: list[str] = []
        for tmpl in templates:
            qtype = tmpl.data.get("question_type", "?")
            diff = tmpl.data.get("difficulty", "?")
            conc = tmpl.data.get("concentration", tmpl.text)
            answer_nodes = [
                trace.nodes[cid]
                for cid in tmpl.children
                if cid in trace.nodes and trace.nodes[cid].node_type == "answer"
            ]
            if answer_nodes:
                res = str(answer_nodes[0].data.get("judged_result", "unknown"))
                if res.lower() in ("correct", "true"):
                    correct += 1
                elif res.lower() in ("wrong", "incorrect", "false"):
                    wrong += 1
                else:
                    skipped += 1
            else:
                res = "no_answer"
                skipped += 1
            q_lines.append(f'- {tmpl.short_id} [{qtype}/{diff}] "{conc}" -> {res}')
        total = correct + wrong + skipped
        header = (
            f"Question summary: {total} questions | "
            f"correct {correct}, wrong {wrong}, skipped {skipped}"
        )
        return "\n".join([header] + q_lines)

    return "(unknown trace type)"


def _build_full_context(trace: TraceTree) -> str:
    if trace.trace_type == "solve":
        if not trace.answer_path:
            return "(no final answer available)"
        p = Path(trace.answer_path)
        if not p.exists():
            return "(no final answer available)"
        try:
            content = p.read_text(encoding="utf-8").strip()
            return content if content else "(empty)"
        except Exception:
            return "(failed to read)"

    if trace.trace_type == "question":
        if not trace.answer_path:
            return "(no answer data)"
        try:
            summary_data = json.loads(Path(trace.answer_path).read_text("utf-8"))
        except Exception:
            return "(no question data)"
        if not isinstance(summary_data, dict):
            return "(no question data)"

        results = list(summary_data.get("results", []) or [])
        if not results:
            return "(no results)"

        tmpl_by_qid: dict[str, TraceNode] = {}
        for t in trace.nodes.values():
            if t.node_type == "template":
                qid = t.data.get("question_id", "")
                if qid:
                    tmpl_by_qid[qid] = t

        parts: list[str] = []
        for idx, result in enumerate(results, 1):
            qa = result.get("qa_pair", {}) or {}
            template = result.get("template", {}) or {}

            qid = str(template.get("question_id") or qa.get("question_id") or f"q_{idx}")
            qtype = str(template.get("question_type") or qa.get("question_type") or "?")
            diff = str(template.get("difficulty") or qa.get("difficulty") or "?")
            question_text = str(qa.get("question", "") or "")
            correct_answer = str(
                qa.get("correct_answer", "") or qa.get("answer", "") or ""
            )
            explanation = str(qa.get("explanation", "") or "")
            options = qa.get("options", None)

            user_answer = ""
            judged = "no_answer"
            tmpl_node = tmpl_by_qid.get(qid)
            if tmpl_node:
                for cid in tmpl_node.children:
                    child = trace.nodes.get(cid)
                    if child and child.node_type == "answer":
                        user_answer = str(child.data.get("user_answer", "") or "")
                        judged = str(
                            child.data.get("judged_result", "unknown") or "unknown"
                        )
                        break

            block = [f"--- Question {idx} [{qtype}/{diff}] ---"]
            if question_text:
                block.append(f"Question: {question_text}")
            if options and isinstance(options, (list, dict)):
                if isinstance(options, list):
                    for opt in options:
                        block.append(f"  {opt}")
                elif isinstance(options, dict):
                    for key, val in options.items():
                        block.append(f"  {key}. {val}")
            if correct_answer:
                block.append(f"Correct answer: {correct_answer}")
            block.append(f"User answer: {user_answer or '(none)'}")
            block.append(f"Judged: {judged}")
            if explanation:
                block.append(f"Explanation: {explanation}")
            parts.append("\n".join(block))

        return "\n\n".join(parts)

    return "(unknown)"
