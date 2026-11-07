#!/usr/bin/env python
"""
Conversation Runner - Run multi-turn student-tutor conversations

Supports two modes:
  1. Interactive: Human plays the tutor, types responses in terminal
  2. Auto: Tutor backend (deep_tutor variants or mock)

Usage:
  # Interactive mode (editor by default; use --inline for console input):
  python -m benchmark.simulation.conversation --entry path/to/entry.json

  # Console input (empty line + Enter to send; paste may truncate long content):
  python -m benchmark.simulation.conversation --entry path/to/entry.json --inline

  # Auto mode with DeepTutor backend:
  python -m benchmark.simulation.conversation --entry path/to/entry.json --auto --auto-backend deep_tutor
"""

import asyncio
import contextlib
import io
import json
import logging
import os
import re
import subprocess
import tempfile
import textwrap
from datetime import datetime
from pathlib import Path
from typing import Literal

from benchmark.simulation.student_agent import StudentAgent

# Delimiter to separate student context from tutor response in editor
_EDITOR_DELIMITER = "\n\n--- Type your response below this line ---\n\n"

logger = logging.getLogger("benchmark.conversation")

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

SUPPORTED_AUTO_BACKENDS = [
    "deep_tutor",
    "deep_tutor_no_rag",
    "deep_tutor_no_memory",
    "deep_tutor_no_rag_memory",
    "mock",
    "cot",
    "self_refine",
    "react",
]

AutoBackend = Literal[
    "deep_tutor",
    "deep_tutor_no_rag",
    "deep_tutor_no_memory",
    "deep_tutor_no_rag_memory",
    "mock",
    "cot",
    "self_refine",
    "react",
]


def _is_deeptutor_backend(backend: str) -> bool:
    return backend.startswith("deep_tutor")


async def _dispatch_mock_like_backend(
    backend: str,
    student_message: str,
    history: list[dict[str, str]],
    kb_name: str | None,
) -> str:
    """Dispatch to the correct mock-like backend respond function."""
    if backend == "cot":
        return await cot_tutor_respond(student_message, history, kb_name)
    if backend == "self_refine":
        return await self_refine_tutor_respond(student_message, history, kb_name)
    if backend == "react":
        return await react_tutor_respond(student_message, history, kb_name)
    return await mock_tutor_respond(student_message, history, kb_name)


def _resolve_deeptutor_ablation_flags(backend: str) -> dict[str, bool]:
    """
    Resolve ablation toggles for DeepTutor variants.

    Returns dict:
      - enable_rag
      - enable_memory
    """
    if backend == "deep_tutor":
        return {"enable_rag": True, "enable_memory": True}
    if backend == "deep_tutor_no_rag":
        return {"enable_rag": False, "enable_memory": True}
    if backend == "deep_tutor_no_memory":
        return {"enable_rag": True, "enable_memory": False}
    if backend == "deep_tutor_no_rag_memory":
        return {"enable_rag": False, "enable_memory": False}
    raise ValueError(f"Unsupported DeepTutor backend variant: {backend}")


def _suppress_noisy_auto_logs() -> None:
    """Suppress verbose INFO/DEBUG logs from RAG/LLM internals during simulation."""
    # Clamp root logger first to suppress generic "INFO: Process ..." style logs.
    logging.getLogger().setLevel(logging.WARNING)

    noisy_loggers = [
        "CodeExecutor",
        "RAGService",
        "RAGForward",
        "Main",
        "LLMClient",
        "EmbeddingClient",
        "lightrag",
        "raganything",
        "nano-vectordb",
        "multiprocessing",
        "openai",
        "httpx",
        "httpcore",
        "src.services.embedding.provider",
        "src.services.embedding.adapters.openai_compatible",
        "src.services.rag",
        "src.services.rag.service",
        "src.tools.rag_tool",
    ]
    for name in noisy_loggers:
        logging.getLogger(name).setLevel(logging.WARNING)


def _get_tutor_input_via_editor(student_context: str) -> str | None:
    """
    Open editor with student's message at top for reference.
    Returns tutor response (content below delimiter), or None if aborted.
    Avoids terminal paste truncation (4096 bytes on Linux, ~16K on macOS).
    """
    editor = os.environ.get("EDITOR") or os.environ.get("VISUAL") or "nano"
    # Wrap long lines so they fit in editor (72 chars per line)
    wrapped_lines = []
    for para in student_context.strip().split("\n"):
        for wline in textwrap.wrap(para, width=72):
            wrapped_lines.append(f"# {wline}")
        wrapped_lines.append("#")  # blank line between paragraphs
    header = "# Student's question (read-only reference):\n#\n"
    header += "\n".join(wrapped_lines) + "\n"
    header += _EDITOR_DELIMITER

    with tempfile.NamedTemporaryFile(
        mode="w",
        suffix=".txt",
        delete=False,
        encoding="utf-8",
    ) as f:
        f.write(header)
        f.flush()
        path = f.name

    try:
        ret = subprocess.call([editor, path])
        if ret != 0:
            return None
        with open(path, encoding="utf-8") as f:
            text = f.read()
        if _EDITOR_DELIMITER in text:
            result = text.split(_EDITOR_DELIMITER, 1)[1].strip()
        else:
            result = text.strip()
        if not result or result.lower() == "quit":
            return None
        return result
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


# Fixed prompt sent to tutor after student says task_complete
TUTOR_POST_COMPLETE_PROMPT = (
    "The student has indicated they are done with this session. "
    "Based on this conversation, please create 5 practice problems that reinforce what was covered. "
    "Use multiple-choice format where applicable, and ensure distractors are plausible and non-trivial "
    "(not obviously wrong at first glance). "
    "Give only problem statements (no solutions)."
)
PRACTICE_QUESTION_COUNT = 5


def _build_sim_workspace(profile_id: str | None, entry_id: str, shared_by_profile: bool) -> str:
    """Build workspace path for DeepTutor tool-based auto tutor."""
    base = PROJECT_ROOT / "benchmark" / "data" / "sim_workspaces"
    key = profile_id if (shared_by_profile and profile_id) else entry_id
    return str(base / key)


# Simple tutor system prompt for auto mode
MOCK_TUTOR_SYSTEM = (
    "You are a helpful and patient tutor."
)

COT_TUTOR_SYSTEM = (
    "You are a helpful and patient tutor.\n\n"
    "Before responding, think step by step:\n"
    "1. What is the student really asking or confused about?\n"
    "2. What are the key concepts involved?\n"
    "3. What is the best way to explain this to the student given the conversation so far?\n"
    "4. Are there any common misconceptions to address?\n\n"
    "Then provide your response to the student. "
    "Do NOT output your thinking process — only output the final response to the student."
)

SELF_REFINE_SYSTEM = (
    "You are a teaching quality reviewer. You will receive a tutor's draft response "
    "to a student question, along with the student message and any retrieved context.\n\n"
    "Improve the draft by:\n"
    "- Making explanations more specific to what the student asked\n"
    "- Adding concrete examples or step-by-step breakdowns where helpful\n"
    "- Removing redundant or generic filler\n"
    "- Ensuring accuracy and clarity\n\n"
    "Output ONLY the improved response. Do NOT add meta-commentary."
)

REACT_THOUGHT_SYSTEM = (
    "You are a tutoring strategist. Given a student's message and conversation history, "
    "analyze what the student needs. Output a brief THOUGHT (2-4 sentences) that identifies:\n"
    "- The student's core question or confusion\n"
    "- Their apparent knowledge level based on the conversation\n"
    "- Key concepts that need to be addressed\n\n"
    "Output ONLY the thought. Do NOT respond to the student."
)

REACT_ACT_SYSTEM = (
    "You are a tutoring strategist. Given a THOUGHT analysis about a student's question, "
    "decide on an ACTION plan. Output a brief ACTION (2-4 sentences) specifying:\n"
    "- What teaching strategy to use (explain, give example, ask Socratic question, correct misconception, etc.)\n"
    "- What specific content to include\n"
    "- How to structure the response\n\n"
    "Output ONLY the action plan. Do NOT respond to the student."
)

REACT_OBSERVE_SYSTEM = (
    "You are a tutoring quality checker. Given a THOUGHT and ACTION plan for responding "
    "to a student, evaluate and refine the plan. Output a brief OBSERVATION (2-4 sentences):\n"
    "- Is the planned action appropriate for this student's level?\n"
    "- Any risks of confusion or inaccuracy?\n"
    "- Any adjustments needed?\n\n"
    "Output ONLY the observation. Do NOT respond to the student."
)

REACT_RESPOND_SYSTEM = (
    "You are a helpful and patient tutor. You have analyzed the student's question "
    "(THOUGHT), decided on a strategy (ACTION), and reviewed your plan (OBSERVATION).\n\n"
    "Now produce the final response to the student. Use the insights from your analysis "
    "but do NOT mention the thought/action/observation process. "
    "Respond naturally as a tutor would."
)


async def _retrieve_rag_context(student_message: str, kb_name: str | None) -> str:
    """Shared RAG retrieval for mock-like backends."""
    if not kb_name:
        return ""
    from src.tools.rag_tool import rag_search

    try:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            rag_result = await rag_search(
                query=student_message,
                kb_name=kb_name,
                mode="naive",
                only_need_context=True,
                top_k=2,
            )
        rag_answer = (rag_result.get("answer") or rag_result.get("content") or "").strip()
        if rag_answer:
            return (
                "## Retrieved context (RAG, naive mode)\n"
                f"{rag_answer[:1500]}\n\n"
            )
    except Exception as e:
        logger.warning("RAG retrieval failed for kb=%s: %s", kb_name, e)
    return ""


async def mock_tutor_respond(
    student_message: str,
    history: list[dict[str, str]],
    kb_name: str | None = None,
) -> str:
    """Generate a mock tutor response using LLM (single call, minimal prompt)."""
    from src.services.llm import factory

    rag_context = await _retrieve_rag_context(student_message, kb_name)
    user_content = f"{rag_context}## Student message\n{student_message}"

    messages = [{"role": "system", "content": MOCK_TUTOR_SYSTEM}]
    messages.extend(history)
    messages.append({"role": "user", "content": user_content})

    return await factory.complete(
        prompt="",
        system_prompt="",
        messages=messages,
        temperature=0.5,
        max_tokens=1024,
    )


async def cot_tutor_respond(
    student_message: str,
    history: list[dict[str, str]],
    kb_name: str | None = None,
) -> str:
    """Generate a tutor response with Chain-of-Thought prompting (single call)."""
    from src.services.llm import factory

    rag_context = await _retrieve_rag_context(student_message, kb_name)
    user_content = f"{rag_context}## Student message\n{student_message}"

    messages = [{"role": "system", "content": COT_TUTOR_SYSTEM}]
    messages.extend(history)
    messages.append({"role": "user", "content": user_content})

    return await factory.complete(
        prompt="",
        system_prompt="",
        messages=messages,
        temperature=0.5,
        max_tokens=1024,
    )


async def self_refine_tutor_respond(
    student_message: str,
    history: list[dict[str, str]],
    kb_name: str | None = None,
) -> str:
    """Generate a tutor response via mock draft + LLM refinement (two calls)."""
    from src.services.llm import factory

    draft = await mock_tutor_respond(student_message, history, kb_name)

    rag_context = await _retrieve_rag_context(student_message, kb_name)
    refine_prompt = (
        f"{rag_context}"
        f"## Student message\n{student_message}\n\n"
        f"## Draft tutor response (improve this)\n{draft}"
    )

    messages = [{"role": "system", "content": SELF_REFINE_SYSTEM}]
    messages.extend(history)
    messages.append({"role": "user", "content": refine_prompt})

    refined = await factory.complete(
        prompt="",
        system_prompt="",
        messages=messages,
        temperature=0.3,
        max_tokens=1024,
    )
    return refined


async def react_tutor_respond(
    student_message: str,
    history: list[dict[str, str]],
    kb_name: str | None = None,
) -> str:
    """Generate a tutor response via ReAct loop: thought -> act -> observe -> respond (four calls)."""
    from src.services.llm import factory

    rag_context = await _retrieve_rag_context(student_message, kb_name)

    history_block = ""
    if history:
        recent = history[-16:]
        lines = []
        for msg in recent:
            role = "Student" if msg.get("role") == "user" else "Tutor"
            text = (msg.get("content", "") or "").strip()[:500]
            if text:
                lines.append(f"[{role}] {text}")
        if lines:
            history_block = "## Recent conversation\n" + "\n".join(lines) + "\n\n"

    base_context = f"{rag_context}{history_block}## Current student message\n{student_message}"

    # Step 1: Thought
    thought = await factory.complete(
        prompt=base_context,
        system_prompt=REACT_THOUGHT_SYSTEM,
        temperature=0.3,
        max_tokens=400,
    )

    # Step 2: Act
    act_prompt = f"{base_context}\n\n## THOUGHT\n{thought}"
    action = await factory.complete(
        prompt=act_prompt,
        system_prompt=REACT_ACT_SYSTEM,
        temperature=0.3,
        max_tokens=400,
    )

    # Step 3: Observation
    obs_prompt = f"{base_context}\n\n## THOUGHT\n{thought}\n\n## ACTION\n{action}"
    observation = await factory.complete(
        prompt=obs_prompt,
        system_prompt=REACT_OBSERVE_SYSTEM,
        temperature=0.3,
        max_tokens=400,
    )

    # Step 4: Final response
    resp_prompt = (
        f"{base_context}\n\n"
        f"## THOUGHT\n{thought}\n\n"
        f"## ACTION\n{action}\n\n"
        f"## OBSERVATION\n{observation}"
    )
    messages = [{"role": "system", "content": REACT_RESPOND_SYSTEM}]
    messages.extend(history)
    messages.append({"role": "user", "content": resp_prompt})

    return await factory.complete(
        prompt="",
        system_prompt="",
        messages=messages,
        temperature=0.5,
        max_tokens=1024,
    )


_TUTOR_INSTRUCTION_BASE = (
    "You are a helpful and patient tutor."
)

_HISTORY_CHAR_BUDGET = 10000


def _build_history_entries(
    tutor_history: list[dict[str, str]],
    *,
    char_budget: int,
) -> list[str]:
    """Render recent tutor/student history within a character budget."""
    if not tutor_history or char_budget <= 0:
        return []

    lines: list[str] = []
    total = 0
    for msg in reversed(tutor_history):
        role = "Student" if msg.get("role") == "user" else "Tutor"
        text = (msg.get("content", "") or "").strip()
        if not text:
            continue
        entry = f"[{role}] {text}"
        if total + len(entry) > char_budget:
            break
        lines.append(entry)
        total += len(entry)
    lines.reverse()
    return lines


def _build_conversation_context(tutor_history: list[dict[str, str]]) -> str:
    """Build a compact conversation-so-far block from tutor_history.

    Keeps the most recent turns within a character budget so the solver
    can adapt to the student's expressed confusion and level without
    exposing any private profile data.
    """
    lines = _build_history_entries(
        tutor_history,
        char_budget=_HISTORY_CHAR_BUDGET,
    )
    if not lines:
        return ""
    return (
        "## Conversation so far\n"
        + "\n".join(lines)
        + "\n\n"
    )


def _build_tutor_instruction(student_message: str) -> str:
    """Build adaptive tutoring instruction without rule-based matching."""
    _ = student_message  # Keep signature stable for callers.
    return _TUTOR_INSTRUCTION_BASE  + "Student says: "


async def deep_tutor_respond(
    student_message: str,
    kb_name: str,
    workspace: str,
    language: str = "en",
    enable_rag: bool = True,
    enable_memory: bool = True,
    rag_mode: str = "naive",
    tutor_history: list[dict[str, str]] | None = None,
) -> str:
    """
    Generate tutor response via DeepTutor solve pipeline.
    Wraps the student message with tutoring instructions so the
    WriterAgent produces a pedagogical response rather than an essay.
    Conversation history (tutor_history) is prepended so the solver
    can adapt to what the student has expressed, without exposing
    any private student profile data.
    """
    from benchmark.simulation.tools import solve_question

    if not kb_name:
        return "(DeepTutor unavailable: missing kb_name in entry.)"

    convo_ctx = _build_conversation_context(tutor_history or [])
    question = convo_ctx + _build_tutor_instruction(student_message) + student_message
    enabled_tools = ["code_execute", "reason"]
    if enable_rag:
        enabled_tools.insert(0, "rag_search")

    result = await solve_question(
        workspace=workspace,
        kb_name=kb_name,
        question=question,
        language=language,
        enabled_tools=enabled_tools,
        enable_memory=enable_memory,
        enable_planner_retrieve=enable_rag,
        rag_mode=rag_mode,
    )
    answer = (result.get("answer") or "").strip()
    return answer or "(No answer generated.)"


def _format_question_block(q: dict) -> str:
    """Format one generated question for tutor output."""
    title = q.get("question", "").strip()
    options = q.get("options", {}) or {}
    lines = [title] if title else ["(Empty question)"]
    if isinstance(options, dict):
        for k, v in options.items():
            lines.append(f"{k}. {v}")
    elif isinstance(options, list):
        for item in options:
            lines.append(str(item))
    correct_answer = str(q.get("correct_answer", "") or "").strip()
    explanation = str(q.get("explanation", "") or "").strip()
    if correct_answer:
        lines.append(f"Correct answer: {correct_answer}")
    if explanation:
        lines.append(f"Explanation: {explanation}")
    return "\n".join(lines)


async def deep_tutor_generate_practice_problem(
    *,
    kb_name: str,
    workspace: str,
    topic: str,
    language: str = "en",
    enable_rag: bool = True,
    enable_memory: bool = True,
) -> str:
    """
    Generate one practice problem via DeepTutor question pipeline.
    """
    from benchmark.simulation.tools import generate_questions

    if not kb_name:
        return "(Practice problem generation unavailable: missing kb_name in entry.)"

    result = await generate_questions(
        workspace=workspace,
        kb_name=kb_name,
        topic=topic,
        num_questions=1,
        language=language,
        enable_memory=enable_memory,
        enable_rag=enable_rag,
        enable_web=False,
        include_answers=True,
    )
    questions = result.get("questions", []) or []
    if not questions:
        return "(Practice problem generation failed.)"
    return _format_question_block(questions[0])


def _build_practice_preferences(
    tutor_history: list[dict[str, str]],
) -> str:
    """Build a preferences string from conversation history."""
    quality_rules = (
        "Question quality requirements:\n"
        "- For MCQ, provide 4 options (A-D) with exactly one correct answer.\n"
        "- Distractors must be plausible and reflect common misconceptions.\n"
        "- Distractors must NOT be obviously wrong at first glance.\n"
        "- Keep options balanced in style and length to avoid test-taking shortcuts.\n"
    )
    lines = _build_history_entries(
        tutor_history,
        char_budget=_HISTORY_CHAR_BUDGET,
    )
    if not lines:
        return quality_rules
    return quality_rules + "\nRecent conversation:\n" + "\n".join(lines)


async def deep_tutor_generate_practice_questions(
    *,
    kb_name: str,
    workspace: str,
    topic: str,
    language: str = "en",
    num_questions: int = PRACTICE_QUESTION_COUNT,
    max_retries: int = 2,
    tutor_history: list[dict[str, str]] | None = None,
    enable_rag: bool = True,
    enable_memory: bool = True,
) -> list[str]:
    """Generate multiple practice questions via DeepTutor question pipeline.

    If fewer than num_questions are returned, retries with the remaining count.
    """
    from benchmark.simulation.tools import generate_questions

    if not kb_name:
        return ["(Practice question generation unavailable: missing kb_name in entry.)"]

    preferences = _build_practice_preferences(tutor_history or [])
    formatted: list[str] = []
    remaining = num_questions

    for attempt in range(1 + max_retries):
        if remaining <= 0:
            break
        result = await generate_questions(
            workspace=workspace,
            kb_name=kb_name,
            topic=topic,
            preferences=preferences,
            num_questions=remaining,
            language=language,
            enable_memory=enable_memory,
            enable_rag=enable_rag,
            enable_web=False,
            include_answers=True,
        )
        questions = result.get("questions", []) or []
        for q in questions:
            if q:
                formatted.append(_format_question_block(q))
        remaining = num_questions - len(formatted)
        if remaining <= 0:
            break
        logger.warning(
            "DeepTutor generated %d/%d questions (attempt %d/%d), retrying %d remaining",
            len(formatted), num_questions, attempt + 1, 1 + max_retries, remaining,
        )

    if not formatted:
        return ["(Practice question generation failed.)"]
    return formatted[:num_questions]


def _format_practice_questions_block(questions: list[str]) -> str:
    """Render practice questions as numbered block."""
    lines: list[str] = []
    for i, q in enumerate(questions, start=1):
        lines.append(f"Q{i}. {q.strip()}")
    return "\n\n".join(lines) if lines else "(No practice questions generated.)"


def _split_questions_from_text(text: str) -> list[str]:
    """Best-effort split of question list from raw text."""
    if not text.strip():
        return []
    blocks = [b.strip() for b in re.split(r"\n\s*\n", text) if b.strip()]
    # Prefer lines/blocks that look like numbered questions.
    numbered = [b for b in blocks if re.match(r"^(Q?\d+[\).:]\s+)", b, flags=re.I)]
    if numbered:
        return numbered[:PRACTICE_QUESTION_COUNT]
    return blocks[:PRACTICE_QUESTION_COUNT]


def _normalize_question_text(text: str) -> str:
    """Normalize question text for duplicate checks."""
    s = text.strip().lower()
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r"^[qQ]?\d+[\).:]\s*", "", s)
    return s


async def mock_tutor_generate_practice_questions(
    *,
    tutor_history: list[dict[str, str]],
    kb_name: str | None,
    num_questions: int = PRACTICE_QUESTION_COUNT,
) -> list[str]:
    """
    Generate MCQ practice questions via mock tutor in iterative rounds.
    Each round includes all previously generated questions as context.
    """
    generated: list[str] = []
    generated_norm: set[str] = set()
    practice_history = list(tutor_history)

    for i in range(1, num_questions + 1):
        prev = "\n\n".join([f"{idx + 1}. {q}" for idx, q in enumerate(generated)]) or "(none yet)"
        prompt = (
            "The student has finished this session. Generate EXACTLY ONE new "
            "multiple-choice question (MCQ) with 4 options (A-D).\n"
            f"This is question {i} of {num_questions}.\n\n"
            "Requirements:\n"
            "- Keep it aligned with this session's covered concepts.\n"
            "- Use the exact format:\n"
            "  <question stem>\n"
            "  A. <option>\n"
            "  B. <option>\n"
            "  C. <option>\n"
            "  D. <option>\n"
            "- Exactly ONE option must be correct. The other three are distractors.\n"
            "- Include the correct answer and explanation.\n\n"
            f"Previously generated questions:\n{prev}"
        )

        chosen = None
        for _ in range(3):
            candidate = await mock_tutor_respond(
                prompt,
                practice_history,
                kb_name=kb_name,
            )
            candidate = (candidate or "").strip()
            norm = _normalize_question_text(candidate)
            if candidate and norm and norm not in generated_norm:
                chosen = candidate
                generated_norm.add(norm)
                break
            prompt = (
                "Your previous output overlapped with an existing question.\n"
                "Generate ONE different MCQ (A-D options), substantially different.\n\n"
                f"Existing questions:\n{prev}"
            )

        if not chosen:
            chosen = "(Failed to generate a unique practice question.)"

        generated.append(chosen)
        practice_history.append({"role": "user", "content": prompt})
        practice_history.append({"role": "assistant", "content": chosen})

    return generated


def _summarize_session(transcript: list[dict], task: dict, session_index: int) -> str:
    """Produce a brief summary of a session for prior_sessions context."""
    title = task.get("title", "Unknown task")
    lines = [f"Session {session_index}: {title}"]
    # First exchange
    for i, msg in enumerate(transcript[:4]):
        role = msg.get("role", "?")
        content = (msg.get("content", "") or "").strip()[:150]
        if content:
            lines.append(f"  {role}: {content}...")
    lines.append(f"  ({len(transcript)} messages total)")
    return "\n".join(lines)


async def _run_single_session(
    entry: dict,
    max_turns: int,
    auto: bool,
    use_editor: bool,
    auto_backend: AutoBackend = "deep_tutor",
    deeptutor_workspace: str | None = None,
    deeptutor_language: str = "en",
    deeptutor_rag_mode: str = "naive",
    prior_sessions_summary: str | None = None,
) -> dict:
    """
    Run one session (one task). Returns result dict with transcript, entry, etc.
    """
    agent = StudentAgent.from_entry(
        entry,
        prior_sessions_context=prior_sessions_summary,
    )
    entry_id = entry.get("entry_id", "unknown")
    kb_name = entry.get("kb_name")
    profile_id = entry.get("profile", {}).get("profile_id")
    workspace = deeptutor_workspace or _build_sim_workspace(
        profile_id=profile_id,
        entry_id=entry_id,
        shared_by_profile=True,
    )
    task_title = entry.get("task", {}).get("title", "")

    tutor_history: list[dict[str, str]] = []
    if auto and auto_backend not in SUPPORTED_AUTO_BACKENDS:
        raise ValueError(
            f"Unsupported auto_backend='{auto_backend}'. "
            f"Supported: {SUPPORTED_AUTO_BACKENDS}"
        )
    student_msg = agent.initial_message()
    deep_flags = (
        _resolve_deeptutor_ablation_flags(auto_backend)
        if _is_deeptutor_backend(auto_backend)
        else {}
    )

    print(f"[Student] {student_msg}\n")

    for turn in range(1, max_turns):
        if auto:
            try:
                if _is_deeptutor_backend(auto_backend):
                    tutor_msg = await deep_tutor_respond(
                        student_message=student_msg,
                        kb_name=kb_name,
                        workspace=workspace,
                        language=deeptutor_language,
                        enable_rag=deep_flags.get("enable_rag", True),
                        enable_memory=deep_flags.get("enable_memory", True),
                        rag_mode=deeptutor_rag_mode,
                        tutor_history=tutor_history,
                    )
                else:
                    tutor_msg = await _dispatch_mock_like_backend(
                        auto_backend, student_msg, tutor_history, kb_name,
                    )
            except Exception as e:
                logger.error("Auto tutor failed (%s): %s", auto_backend, e)
                print(f"\n[Tutor] Error: {e}")
                break
        else:
            if use_editor:
                tutor_msg = _get_tutor_input_via_editor(student_msg)
            else:
                print("[Tutor] (type response, empty line + Enter to send, 'quit' to end)")
                lines = []
                quit_typed = False
                while True:
                    try:
                        line = input()
                    except EOFError:
                        break
                    if line.strip().lower() == "quit":
                        quit_typed = True
                        break
                    if line == "" and lines:
                        break
                    lines.append(line)
                if quit_typed or not lines:
                    break
                tutor_msg = "\n".join(lines)

            if tutor_msg is None:
                break

        tutor_history.append({"role": "user", "content": student_msg})
        tutor_history.append({"role": "assistant", "content": tutor_msg})

        print(f"[Tutor] {tutor_msg}\n")

        student_msg, student_action = await agent.respond(tutor_msg)
        print(f"[Student] {student_msg}\n")
        if student_action == "task_complete":
            tutor_history.append({"role": "user", "content": student_msg})
            break

    # --- Practice question generation (runs after session ends for any reason) ---
    practice_questions: list[str] = []

    if auto:
        end_reason = "task_complete" if (student_action if "student_action" in dir() else None) == "task_complete" else "max_turns"
        print(f"[System] Session ended ({end_reason}). Generating practice questions...")
        try:
            if _is_deeptutor_backend(auto_backend):
                topic = (
                    f"{task_title}\n"
                    f"Conversation summary request: {TUTOR_POST_COMPLETE_PROMPT}\n"
                    f"Generate {PRACTICE_QUESTION_COUNT} practice questions aligned to this session."
                )
                practice_questions = await deep_tutor_generate_practice_questions(
                    kb_name=kb_name,
                    workspace=workspace,
                    topic=topic,
                    language=deeptutor_language,
                    tutor_history=tutor_history,
                    enable_rag=deep_flags.get("enable_rag", True),
                    enable_memory=deep_flags.get("enable_memory", True),
                )
            else:
                practice_questions = await mock_tutor_generate_practice_questions(
                    tutor_history=tutor_history,
                    kb_name=kb_name,
                )
        except Exception as e:
            logger.error("Auto tutor post-complete failed (%s): %s", auto_backend, e)
            practice_questions = ["(Practice question generation failed.)"]
    elif not auto and tutor_history:
        print(f"[Tutor] {TUTOR_POST_COMPLETE_PROMPT}")
        print("[Tutor] (type 5 practice questions, separate by blank lines, empty line + Enter to send)")
        lines = []
        while True:
            try:
                line = input()
            except EOFError:
                break
            if line == "" and lines:
                break
            lines.append(line)
        practice_questions = _split_questions_from_text("\n".join(lines))
        if not practice_questions:
            practice_questions = ["(No practice questions provided.)"]

    if practice_questions:
        if len(practice_questions) > PRACTICE_QUESTION_COUNT:
            practice_questions = practice_questions[:PRACTICE_QUESTION_COUNT]
        practice_msg = _format_practice_questions_block(practice_questions)
        tutor_history.append({"role": "assistant", "content": practice_msg})
        print(f"[Tutor] {practice_msg}\n")
        agent.history.append({"role": "user", "content": practice_msg})

    transcript = agent.get_transcript()
    return {
        "entry_id": entry_id,
        "transcript": transcript,
        "entry": entry,
        "actual_turns": agent.turn_count,
        "practice_questions": practice_questions,
    }


async def run_conversation(
    entry_path: str | Path,
    max_turns: int = 20,
    auto: bool = False,
    auto_backend: AutoBackend = "deep_tutor",
    deeptutor_language: str = "en",
    output_dir: str | Path | None = None,
    entry_index: int = 0,
    use_editor: bool = True,
) -> dict:
    """
    Run a multi-turn conversation between student agent and tutor.

    Args:
        entry_path: Path to benchmark entry JSON file, or JSONL file
        max_turns: Maximum number of student turns (including initial message, default: 20)
        auto: If True, use mock LLM tutor. If False, interactive (stdin).
        output_dir: Directory to save transcript. If None, uses default.
        entry_index: When entry_path is JSONL, which entry to use (0-based).
        use_editor: If True (default), open $EDITOR. If False, use console input.

    Returns:
        Conversation result dict with transcript and metadata
    """
    entry_path = Path(entry_path)

    # Load entry and create agent
    with open(entry_path, encoding="utf-8") as f:
        if entry_path.suffix.lower() == ".jsonl":
            lines = [ln.strip() for ln in f if ln.strip()]
            if not lines:
                raise ValueError(f"Empty JSONL file: {entry_path}")
            if entry_index >= len(lines):
                raise ValueError(
                    f"entry_index={entry_index} out of range (file has {len(lines)} entries)"
                )
            entry = json.loads(lines[entry_index])
        else:
            entry = json.load(f)

    agent = StudentAgent.from_entry(entry)
    entry_id = entry.get("entry_id", entry_path.stem)
    kb_name = entry.get("kb_name")
    profile_id = entry.get("profile", {}).get("profile_id")
    workspace = _build_sim_workspace(
        profile_id=profile_id,
        entry_id=entry_id,
        shared_by_profile=False,
    )
    task_title = entry.get("task", {}).get("title", "")

    print(f"\n{'='*60}")
    print(f"Conversation: {entry_id}")
    mode_desc = f"auto ({auto_backend})" if auto else "interactive (you are the tutor)"
    print(f"Mode: {mode_desc}")
    print(f"Max turns: {max_turns}")
    print(f"{'='*60}\n")

    # Tutor-side history (from tutor's perspective)
    tutor_history: list[dict[str, str]] = []
    if auto and auto_backend not in SUPPORTED_AUTO_BACKENDS:
        raise ValueError(
            f"Unsupported auto_backend='{auto_backend}'. "
            f"Supported: {SUPPORTED_AUTO_BACKENDS}"
        )
    deep_flags = (
        _resolve_deeptutor_ablation_flags(auto_backend)
        if _is_deeptutor_backend(auto_backend)
        else {}
    )

    # Turn 0: Student's initial message
    student_msg = agent.initial_message()
    print(f"[Student] {student_msg}\n")

    for turn in range(1, max_turns):
        # Get tutor response
        if auto:
            try:
                if _is_deeptutor_backend(auto_backend):
                    tutor_msg = await deep_tutor_respond(
                        student_message=student_msg,
                        kb_name=kb_name,
                        workspace=workspace,
                        language=deeptutor_language,
                        enable_rag=deep_flags.get("enable_rag", True),
                        enable_memory=deep_flags.get("enable_memory", True),
                        tutor_history=tutor_history,
                    )
                else:
                    tutor_msg = await _dispatch_mock_like_backend(
                        auto_backend, student_msg, tutor_history, kb_name,
                    )
            except Exception as e:
                logger.error("Auto tutor failed (%s): %s", auto_backend, e)
                print(f"\n[Tutor] Error: {e}")
                print("(Conversation stopped. Partial transcript will be saved.)")
                break
        else:
            print("-" * 40)
            if use_editor:
                print("[Tutor] Opening editor (student's question at top).")
                print("        Save & close to send. nano: Ctrl+O then Ctrl+X | vim: :wq | VS Code: Cmd+S then close tab")
                tutor_msg = _get_tutor_input_via_editor(student_msg)
                if tutor_msg is None:
                    print("\n[Conversation ended by tutor]")
                    break
            else:
                print("[Tutor] (type your response, empty line + Enter to send, 'quit' to end)")
                lines = []
                quit_typed = False
                while True:
                    try:
                        line = input()
                    except EOFError:
                        break
                    if line.strip().lower() == "quit":
                        print("\n[Conversation ended by tutor]")
                        quit_typed = True
                        break
                    if line == "" and lines:
                        break
                    lines.append(line)
                if quit_typed or not lines:
                    break
                tutor_msg = "\n".join(lines)

        # Record in tutor history
        tutor_history.append({"role": "user", "content": student_msg})
        tutor_history.append({"role": "assistant", "content": tutor_msg})

        print(f"[Tutor] {tutor_msg}\n")

        # Get student response (task_complete only when ending)
        student_msg, student_action = await agent.respond(tutor_msg)
        print(f"[Student] {student_msg}\n")
        if student_action == "task_complete":
            tutor_history.append({"role": "user", "content": student_msg})
            break

    # --- Practice question generation (runs after session ends for any reason) ---
    practice_questions: list[str] = []

    if auto and tutor_history:
        end_reason = "task_complete" if (student_action if "student_action" in dir() else None) == "task_complete" else "max_turns"
        print(f"[System] Session ended ({end_reason}). Generating practice questions...")
        try:
            if _is_deeptutor_backend(auto_backend):
                topic = (
                    f"{task_title}\n"
                    f"Conversation summary request: {TUTOR_POST_COMPLETE_PROMPT}\n"
                    f"Generate {PRACTICE_QUESTION_COUNT} practice questions aligned to this session."
                )
                practice_questions = await deep_tutor_generate_practice_questions(
                    kb_name=kb_name,
                    workspace=workspace,
                    topic=topic,
                    language=deeptutor_language,
                    tutor_history=tutor_history,
                    enable_rag=deep_flags.get("enable_rag", True),
                    enable_memory=deep_flags.get("enable_memory", True),
                )
            else:
                practice_questions = await mock_tutor_generate_practice_questions(
                    tutor_history=tutor_history,
                    kb_name=kb_name,
                )
        except Exception as e:
            logger.error("Auto tutor post-complete failed (%s): %s", auto_backend, e)
            practice_questions = ["(Practice question generation failed.)"]
    elif not auto and tutor_history:
        print(f"[Tutor] {TUTOR_POST_COMPLETE_PROMPT}")
        print("[Tutor] (type 5 practice questions, separate by blank lines, empty line + Enter to send)")
        lines = []
        while True:
            try:
                line = input()
            except EOFError:
                break
            if line == "" and lines:
                break
            lines.append(line)
        practice_questions = _split_questions_from_text("\n".join(lines))
        if not practice_questions:
            practice_questions = ["(No practice questions provided.)"]

    if practice_questions:
        if len(practice_questions) > PRACTICE_QUESTION_COUNT:
            practice_questions = practice_questions[:PRACTICE_QUESTION_COUNT]
        practice_msg = _format_practice_questions_block(practice_questions)
        print(f"[Tutor] {practice_msg}\n")
        agent.history.append({"role": "user", "content": practice_msg})

    print(f"{'='*60}")
    print(f"Conversation complete. {agent.turn_count} student turns.")
    print(f"{'='*60}\n")

    # Build result
    result = {
        "entry_id": entry_id,
        "timestamp": datetime.now().isoformat(),
        "mode": "auto" if auto else "interactive",
        "max_turns": max_turns,
        "actual_turns": agent.turn_count,
        "transcript": agent.get_transcript(),
        "entry": entry,
        "practice_questions": practice_questions,
    }

    # Save transcript
    if output_dir is None:
        output_dir = PROJECT_ROOT / "benchmark" / "data" / "transcripts"
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = output_dir / f"{entry_id}_{timestamp}.json"
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"Transcript saved → {output_file}")
    return result


def _load_entries_for_profile(
    jsonl_path: Path,
    profile_id: str,
) -> list[dict]:
    """Load and return entries for a given profile_id, sorted by task_id."""
    entries = []
    with open(jsonl_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            entry = json.loads(line)
            if entry.get("profile", {}).get("profile_id") == profile_id:
                entries.append(entry)
    # Sort by entry_id (contains task_id) for deterministic order
    entries.sort(key=lambda e: e.get("entry_id", ""))
    return entries


def _load_entries_from_paths(paths: list[str]) -> list[dict]:
    """Load entries from explicit JSON paths."""
    entries = []
    for p in paths:
        path = Path(p.strip())
        if not path.exists():
            raise FileNotFoundError(f"Entry file not found: {path}")
        with open(path, encoding="utf-8") as f:
            entries.append(json.load(f))
    return entries


async def run_multi_session(
    entry_path: str | Path | None = None,
    profile_id: str | None = None,
    entry_paths: list[str] | None = None,
    max_turns: int = 20,
    auto: bool = False,
    auto_backend: AutoBackend = "deep_tutor",
    deeptutor_language: str = "en",
    output_dir: str | Path | None = None,
    use_editor: bool = True,
    evolve_profile: bool = True,
) -> dict:
    """
    Run multiple sessions for the same student (one task per session).

    Entries are loaded either by:
    - profile_id: filter JSONL at entry_path by profile
    - entry_paths: explicit list of entry JSON paths

    After each session, prior_sessions_summary is built and injected into
    student context for the next session. If evolve_profile is True, the profile is
    evolved (resolved gaps → known_well) for the next session.

    Returns:
        Dict with sessions list and combined transcript
    """
    if entry_paths:
        entries = _load_entries_from_paths(entry_paths)
    elif entry_path and profile_id:
        entries = _load_entries_for_profile(Path(entry_path), profile_id)
        if not entries:
            raise ValueError(
                f"No entries found for profile_id={profile_id} in {entry_path}"
            )
    else:
        raise ValueError("Provide either (entry_path + profile_id) or entry_paths")

    if auto and auto_backend not in SUPPORTED_AUTO_BACKENDS:
        raise ValueError(
            f"Unsupported auto_backend='{auto_backend}'. "
            f"Supported: {SUPPORTED_AUTO_BACKENDS}"
        )

    if output_dir is None:
        output_dir = PROJECT_ROOT / "benchmark" / "data" / "transcripts"
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    profile_id_display = profile_id or entries[0].get("profile", {}).get("profile_id", "?")
    shared_workspace = _build_sim_workspace(
        profile_id=profile_id_display,
        entry_id=entries[0].get("entry_id", "unknown"),
        shared_by_profile=True,
    )
    print(f"\n{'='*60}")
    print(f"Multi-session: {profile_id_display} ({len(entries)} sessions)")
    print(f"Mode: {'auto (' + auto_backend + ')' if auto else 'interactive'}")
    if auto and _is_deeptutor_backend(auto_backend):
        print(f"DeepTutor workspace(shared): {shared_workspace}")
    print(f"Evolve profile: {evolve_profile}")
    print(f"{'='*60}\n")

    prior_sessions_summary: list[str] = []
    current_profile = entries[0].get("profile", {})
    sessions_results: list[dict] = []

    for i, base_entry in enumerate(entries):
        session_num = i + 1
        entry_id = base_entry.get("entry_id", f"session_{session_num}")

        # Build entry for this session: evolved profile + prior context
        entry = dict(base_entry)
        if evolve_profile and i > 0:
            prev_entry = entries[i - 1]
            resolved = prev_entry.get("gaps", [])
            from benchmark.simulation.profile_evolver import evolve_profile as evolve_profile_fn

            current_profile = evolve_profile_fn(prev_entry.get("profile", {}), resolved)
        entry["profile"] = current_profile

        prior_ctx = "\n".join(prior_sessions_summary) if prior_sessions_summary else None

        print(f"\n--- Session {session_num}/{len(entries)}: {entry_id} ---\n")

        result = await _run_single_session(
            entry=entry,
            max_turns=max_turns,
            auto=auto,
            use_editor=use_editor,
            auto_backend=auto_backend,
            deeptutor_workspace=shared_workspace,
            deeptutor_language=deeptutor_language,
            prior_sessions_summary=prior_ctx,
        )

        task = entry.get("task", {})
        summary = _summarize_session(
            result["transcript"],
            task,
            session_num,
        )
        prior_sessions_summary.append(summary)

        sessions_results.append(result)
        print(f"\n[Session {session_num} complete. {result['actual_turns']} turns.]")

    combined = {
        "profile_id": profile_id_display,
        "timestamp": datetime.now().isoformat(),
        "mode": "auto" if auto else "interactive",
        "evolve_profile": evolve_profile,
        "num_sessions": len(sessions_results),
        "sessions": [
            {
                "entry_id": r["entry_id"],
                "actual_turns": r["actual_turns"],
                "transcript": r["transcript"],
                "entry": r["entry"],
                "practice_questions": r.get("practice_questions", []),
            }
            for r in sessions_results
        ],
    }

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_file = output_dir / f"multi_{profile_id_display}_{timestamp}.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(combined, f, ensure_ascii=False, indent=2)

    print(f"\n{'='*60}")
    print(f"Multi-session complete. Transcript saved → {out_file}")
    print(f"{'='*60}\n")

    return combined


async def main():
    """CLI entry point."""
    import argparse

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    parser = argparse.ArgumentParser(
        description="Run a student-tutor conversation from a benchmark entry"
    )
    parser.add_argument(
        "--entry",
        help="Path to benchmark entry JSON or JSONL file",
    )
    parser.add_argument(
        "--multi-session",
        action="store_true",
        help="Run multiple sessions for same student (requires --profile or --entries)",
    )
    parser.add_argument(
        "--profile",
        help="Profile ID to filter JSONL entries (use with --entry and --multi-session)",
    )
    parser.add_argument(
        "--entries",
        help="Comma-separated paths to entry JSON files (use with --multi-session)",
    )
    parser.add_argument(
        "--no-evolve",
        action="store_true",
        help="Disable profile evolution between sessions (multi-session only)",
    )
    parser.add_argument(
        "--auto",
        action="store_true",
        help="Use auto tutor backend instead of interactive mode",
    )
    parser.add_argument(
        "--auto-backend",
        choices=SUPPORTED_AUTO_BACKENDS,
        default="deep_tutor",
        help=(
            "Auto tutor backend "
            "(deep_tutor, deep_tutor_no_rag, deep_tutor_no_memory, "
            "deep_tutor_no_rag_memory, mock)"
        ),
    )
    parser.add_argument(
        "--deeptutor-language",
        default="en",
        help="Language for DeepTutor tools (default: en)",
    )
    parser.add_argument(
        "--max-turns",
        type=int,
        default=20,
        help="Maximum number of student turns (default: 20)",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Directory to save transcript (default: benchmark/data/transcripts/)",
    )
    parser.add_argument(
        "--entry-index",
        type=int,
        default=0,
        help="When entry is a JSONL file, which entry to use (0-based, default: 0)",
    )
    parser.add_argument(
        "--inline",
        action="store_true",
        help="Use console input instead of editor (empty line + Enter to send)",
    )

    args = parser.parse_args()
    if args.auto:
        _suppress_noisy_auto_logs()

    if args.multi_session:
        if args.entries:
            entry_paths = [p.strip() for p in args.entries.split(",") if p.strip()]
            await run_multi_session(
                entry_paths=entry_paths,
                max_turns=args.max_turns,
                auto=args.auto,
                auto_backend=args.auto_backend,
                deeptutor_language=args.deeptutor_language,
                output_dir=args.output_dir,
                use_editor=not args.inline,
                evolve_profile=not args.no_evolve,
            )
        elif args.entry and args.profile:
            await run_multi_session(
                entry_path=args.entry,
                profile_id=args.profile,
                max_turns=args.max_turns,
                auto=args.auto,
                auto_backend=args.auto_backend,
                deeptutor_language=args.deeptutor_language,
                output_dir=args.output_dir,
                use_editor=not args.inline,
                evolve_profile=not args.no_evolve,
            )
        else:
            parser.error(
                "Multi-session requires either --entries or (--entry + --profile)"
            )
    else:
        if not args.entry:
            parser.error("Single-session mode requires --entry")
        await run_conversation(
            entry_path=args.entry,
            max_turns=args.max_turns,
            auto=args.auto,
            auto_backend=args.auto_backend,
            deeptutor_language=args.deeptutor_language,
            output_dir=args.output_dir,
            entry_index=args.entry_index,
            use_editor=not args.inline,
        )


if __name__ == "__main__":
    asyncio.run(main())
