#!/usr/bin/env python
"""
Benchmark Evaluator - Independent metric evaluation (no weighted merge)

Metrics (turn-level):
1) Source faithfulness (LLM, per tutor turn): 1-5 score against source text
2) Teaching quality (LLM, per tutor turn): personalization + applicability +
   vividness + logical_depth (all 1-5)
3) Turn count (non-LLM): student/tutor interaction counts (iter uses raw data)

Metrics (practice questions, session-level):
4) Practice question evaluation (LLM, per-question):
   - fitness (1-5)
   - groundedness (1-5)
   - diversity (1-5)
   - answer_quality (1-5)
   - cross_concept (1-5)

Supports:
- Single-session transcript: {"transcript": [...], "entry": {...}}
- Multi-session transcript: {"sessions": [{"transcript": [...], "entry": {...}, ...}, ...]}
"""

import json
import logging
from pathlib import Path

from benchmark.data_generation.llm_utils import call_llm_json, extract_json, load_prompt

logger = logging.getLogger("benchmark.evaluation")

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
RECENT_CONTEXT_WINDOW = 8  # messages (student+tutor) to provide around each turn
TEACHING_QUALITY_JSON_MAX_ATTEMPTS = 3


def _format_profile(profile: dict) -> str:
    """Format student profile for prompt."""
    parts = []
    if profile.get("personality"):
        parts.append(f"Personality: {profile['personality']}")
    if profile.get("education_background"):
        parts.append(f"Background: {profile['education_background']}")
    if profile.get("learning_purpose"):
        parts.append(f"Purpose: {profile['learning_purpose']}")
    ks = profile.get("knowledge_state", {})
    if ks.get("known_well"):
        parts.append(f"Known well: {', '.join(ks['known_well'][:5])}")
    if ks.get("partially_known"):
        parts.append(f"Partially known: {', '.join(ks['partially_known'][:5])}")
    if ks.get("unknown"):
        parts.append(f"Unknown: {', '.join(ks['unknown'][:5])}")
    if profile.get("beliefs"):
        parts.append(f"Beliefs (may be misconceptions): {profile['beliefs']}")
    return "\n".join(parts) if parts else "(no profile)"


def _format_task(task: dict) -> str:
    """Format task for prompt."""
    parts = []
    if task.get("title"):
        parts.append(f"Title: {task['title']}")
    if task.get("description"):
        parts.append(f"Description: {task['description']}")
    if task.get("success_criteria"):
        parts.append(f"Success criteria: {task['success_criteria']}")
    if task.get("target_gaps"):
        parts.append(f"Target gaps: {task['target_gaps']}")
    return "\n".join(parts) if parts else "(no task)"


def _normalize_source_by_page(source_content: dict | None) -> dict[int, str]:
    """Normalize source_content keys to int (JSON may have str page keys)."""
    if not source_content:
        return {}
    out = {}
    for k, v in source_content.items():
        pk = int(k) if isinstance(k, str) and k.isdigit() else k
        if isinstance(pk, int):
            out[pk] = v or ""
    return out


def _format_transcript(transcript: list[dict]) -> str:
    """Format transcript for prompt."""
    lines = []
    for i, msg in enumerate(transcript, 1):
        role = msg.get("role", "?")
        content = (msg.get("content", "") or "")[:900]
        if len((msg.get("content") or "")) > 900:
            content += "..."
        lines.append(f"[{i}] {role.upper()}: {content}")
    return "\n\n".join(lines) if lines else "(empty)"


def _filter_dialog_messages(transcript: list[dict]) -> list[dict]:
    """Keep only student/tutor messages for evaluation scope."""
    return [m for m in transcript if m.get("role") in {"student", "tutor"}]


def _extract_turn_pairs(dialog_msgs: list[dict]) -> list[dict]:
    """
    Build per-turn student->tutor pairs.

    Returns list of:
      {
        "turn_index": int,
        "student_message": str,
        "tutor_response": str,
        "student_msg_index": int,   # index in dialog_msgs
      }
    """
    turns: list[dict] = []
    turn_index = 0
    for i in range(len(dialog_msgs) - 1):
        a, b = dialog_msgs[i], dialog_msgs[i + 1]
        if a.get("role") == "student" and b.get("role") == "tutor":
            turn_index += 1
            turns.append(
                {
                    "turn_index": turn_index,
                    "student_message": a.get("content", ""),
                    "tutor_response": b.get("content", ""),
                    "student_msg_index": i,
                }
            )
    return turns


def _get_recent_context(dialog_msgs: list[dict], student_msg_index: int, window: int = RECENT_CONTEXT_WINDOW) -> str:
    """
    Return recent context ending at current student message.

    This intentionally provides more than just current turn for metric-1 robustness.
    """
    start = max(0, student_msg_index - window + 1)
    snippet = dialog_msgs[start : student_msg_index + 1]
    return _format_transcript(snippet)


def _build_gap_map(gaps: list[dict]) -> dict[str, dict]:
    """Build gap_id -> gap dict mapping."""
    out = {}
    for g in gaps:
        gid = str(g.get("gap_id", "")).strip()
        if gid:
            out[gid] = g
    return out


def _format_gap_catalog(gaps: list[dict]) -> str:
    """Format full gap catalog for metric-1 prompt."""
    if not gaps:
        return "(no gaps)"
    lines = []
    for g in gaps:
        gid = g.get("gap_id", "unknown")
        concept = g.get("target_concept", "?")
        desc = (g.get("description", "") or "")[:350]
        mani = (g.get("manifestation", "") or "")[:240]
        corr = (g.get("correct_understanding", "") or "")[:320]
        lines.append(
            f"- gap_id: {gid}\n"
            f"  concept: {concept}\n"
            f"  description: {desc}\n"
            f"  manifestation: {mani}\n"
            f"  expected_correct_understanding: {corr}"
        )
    return "\n".join(lines)


def _format_mentioned_gaps_with_source(mentioned_gap_ids: list[str], gap_by_id: dict[str, dict], source_content: dict | None) -> str:
    """Format only mentioned gaps and their source excerpts for metric-2."""
    if not mentioned_gap_ids:
        return "(no mentioned gaps)"

    src_by_page = _normalize_source_by_page(source_content)
    lines = []
    for gid in mentioned_gap_ids:
        gap = gap_by_id.get(gid)
        if not gap:
            continue
        concept = gap.get("target_concept", "?")
        desc = (gap.get("description", "") or "")[:260]
        lines.append(f"### {gid} - {concept}")
        lines.append(f"Description: {desc}")
        pages = sorted(set(gap.get("source_pages", [])))
        if pages:
            lines.append(f"Source pages: {pages}")
        for p in pages:
            text = src_by_page.get(p, "")
            if text:
                excerpt = text[:1800] + ("..." if len(text) > 1800 else "")
                lines.append(f"Source page {p}:\n{excerpt}")
        lines.append("")
    return "\n".join(lines).strip() or "(no source excerpt for mentioned gaps)"


async def evaluate_gap_tracking_turn(
    *,
    entry: dict,
    turn_index: int,
    student_message: str,
    tutor_response: str,
    recent_context: str,
    previously_mentioned_gap_ids: list[str],
    previously_resolved_gap_ids: list[str],
    temperature: float,
) -> dict:
    """
    Metric-1 (LLM): detect mentioned gaps and newly resolved gaps on this tutor turn.

    Strict resolution is enforced in prompt:
      - "resolved" requires clear correction + concrete closure evidence, not a casual mention.
    """
    prompt_cfg = load_prompt("eval_gap_tracking_turn")
    profile = entry.get("profile", {})
    gaps = entry.get("gaps", [])
    task = entry.get("task", {})
    gap_by_id = _build_gap_map(gaps)
    valid_gap_ids = set(gap_by_id.keys())
    unresolved = valid_gap_ids - set(previously_resolved_gap_ids)

    user_prompt = prompt_cfg["user_template"].format(
        profile_summary=_format_profile(profile),
        task_summary=_format_task(task),
        gap_catalog=_format_gap_catalog(gaps),
        recent_context=recent_context,
        student_message=student_message,
        tutor_response=tutor_response,
        turn_index=turn_index,
        previously_mentioned_gap_ids=sorted(set(previously_mentioned_gap_ids)),
        previously_resolved_gap_ids=sorted(set(previously_resolved_gap_ids)),
    )

    try:
        result = await call_llm_json(
            user_prompt=user_prompt,
            system_prompt=prompt_cfg["system"],
            temperature=temperature,
            max_tokens=1024,
        )
    except (json.JSONDecodeError, Exception) as e:
        logger.warning("Gap tracking failed at turn %d: %s", turn_index, e)
        return {
            "turn_index": turn_index,
            "mentioned_gap_ids": [],
            "resolved_gap_ids_new": [],
            "rationale": f"Evaluation failed: {e}",
            "error": str(e),
        }

    mentioned = [gid for gid in result.get("mentioned_gap_ids", []) if gid in valid_gap_ids]
    mentioned = sorted(set(mentioned))

    resolved_new_raw = [gid for gid in result.get("resolved_gap_ids_new", []) if gid in unresolved]
    resolved_new = sorted(set(resolved_new_raw))
    # Resolved should be a subset of mentioned on this turn for consistency.
    resolved_new = [gid for gid in resolved_new if gid in mentioned]

    return {
        "turn_index": turn_index,
        "mentioned_gap_ids": mentioned,
        "resolved_gap_ids_new": resolved_new,
        "rationale": result.get("rationale", ""),
    }


async def evaluate_source_faithfulness_turn(
    *,
    turn_index: int,
    student_message: str,
    tutor_response: str,
    recent_context: str,
    mentioned_gap_ids: list[str],
    gap_by_id: dict[str, dict],
    source_content: dict | None,
    temperature: float,
) -> dict:
    """
    Metric-2 (LLM): faithfulness (1-5) against source text of mentioned gaps only.
    """
    if not mentioned_gap_ids:
        return {
            "turn_index": turn_index,
            "mentioned_gap_ids": [],
            "not_applicable": True,
            "reason": "No mentioned gaps on this turn.",
        }

    prompt_cfg = load_prompt("eval_source_faithfulness_turn")
    source_for_mentioned = _format_mentioned_gaps_with_source(mentioned_gap_ids, gap_by_id, source_content)
    if source_for_mentioned.startswith("(no source excerpt"):
        return {
            "turn_index": turn_index,
            "mentioned_gap_ids": mentioned_gap_ids,
            "not_applicable": True,
            "reason": "Mentioned gaps have no usable source excerpts.",
        }

    user_prompt = prompt_cfg["user_template"].format(
        turn_index=turn_index,
        recent_context=recent_context,
        student_message=student_message,
        tutor_response=tutor_response,
        mentioned_gap_ids=mentioned_gap_ids,
        source_content_for_mentioned_gaps=source_for_mentioned,
    )

    try:
        result = await call_llm_json(
            user_prompt=user_prompt,
            system_prompt=prompt_cfg["system"],
            temperature=temperature,
            max_tokens=900,
        )
    except (json.JSONDecodeError, Exception) as e:
        logger.warning("Source faithfulness failed at turn %d: %s", turn_index, e)
        return {
            "turn_index": turn_index,
            "mentioned_gap_ids": mentioned_gap_ids,
            "not_applicable": True,
            "reason": f"Evaluation failed: {e}",
            "error": str(e),
        }

    score = result.get("faithfulness_score")
    try:
        score = int(score)
    except (TypeError, ValueError):
        score = None
    if score is not None:
        score = max(1, min(5, score))

    return {
        "turn_index": turn_index,
        "mentioned_gap_ids": mentioned_gap_ids,
        "faithfulness_score": score,
        "rationale": result.get("rationale", ""),
        "contradictions": result.get("contradictions", result.get("unsupported_claims", [])),
        "not_applicable": score is None,
    }


def _build_source_faithfulness_summary(per_turn: list[dict]) -> dict:
    """Aggregate metric-2 stats: min/max/avg over scored turns only."""
    total_turns = len(per_turn)
    failed_turns = sum(1 for t in per_turn if t.get("error"))
    scored = [t["faithfulness_score"] for t in per_turn if not t.get("not_applicable") and t.get("faithfulness_score") is not None]
    if not scored:
        return {
            "scale": "1-5",
            "num_total_turns": total_turns,
            "num_scored_turns": 0,
            "num_failed_turns": failed_turns,
            "failed_ratio": round(failed_turns / total_turns, 4) if total_turns else 0.0,
            "max_score": None,
            "min_score": None,
            "avg_score": None,
            "per_turn": per_turn,
        }
    return {
        "scale": "1-5",
        "num_total_turns": total_turns,
        "num_scored_turns": len(scored),
        "num_failed_turns": failed_turns,
        "failed_ratio": round(failed_turns / total_turns, 4) if total_turns else 0.0,
        "max_score": max(scored),
        "min_score": min(scored),
        "avg_score": round(sum(scored) / len(scored), 4),
        "per_turn": per_turn,
    }


async def evaluate_teaching_quality_turn(
    *,
    turn_index: int,
    student_message: str,
    tutor_response: str,
    recent_context: str,
    temperature: float,
) -> dict:
    """
    Turn-level teaching quality on four dimensions (all 1-5):
      - personalization
      - applicability
      - vividness
      - logical_depth
    """
    prompt_cfg = load_prompt("eval_teaching_quality_turn")
    user_prompt = prompt_cfg["user_template"].format(
        turn_index=turn_index,
        recent_context=recent_context,
        student_message=student_message,
        tutor_response=tutor_response,
    )

    result = None
    last_error: Exception | None = None
    for attempt in range(1, TEACHING_QUALITY_JSON_MAX_ATTEMPTS + 1):
        attempt_user_prompt = user_prompt
        # On retries, harden output constraints to reduce malformed/truncated JSON.
        if attempt > 1:
            attempt_user_prompt = (
                user_prompt
                + "\n\nIMPORTANT OUTPUT FORMAT:\n"
                + "- Return ONE complete JSON object only.\n"
                + "- No markdown, no code fence, no extra text.\n"
                + "- Ensure all quotes/braces are closed.\n"
            )
        attempt_temperature = temperature if attempt == 1 else min(temperature, 0.1)
        try:
            result = await call_llm_json(
                user_prompt=attempt_user_prompt,
                system_prompt=prompt_cfg["system"],
                temperature=attempt_temperature,
                max_tokens=700,
            )
            break
        except Exception as e:
            last_error = e
            if attempt < TEACHING_QUALITY_JSON_MAX_ATTEMPTS:
                logger.info(
                    "Teaching quality parse retry turn %d attempt %d/%d: %s",
                    turn_index,
                    attempt + 1,
                    TEACHING_QUALITY_JSON_MAX_ATTEMPTS,
                    e,
                )
                continue

    if result is None:
        e = last_error or RuntimeError("Unknown error in teaching quality evaluation")
        logger.warning("Teaching quality failed at turn %d: %s", turn_index, e)
        return {
            "turn_index": turn_index,
            "personalization_score": None,
            "applicability_score": None,
            "vividness_score": None,
            "logical_depth_score": None,
            "rationale": f"Evaluation failed: {e}",
            "not_applicable": True,
            "error": str(e),
        }

    personalization = result.get("personalization_score")
    applicability = result.get("applicability_score")
    vividness = result.get("vividness_score")
    logical_depth = result.get("logical_depth_score")

    def _parse_1_to_5(v):
        try:
            iv = int(v) if v is not None else None
        except (TypeError, ValueError):
            return None
        return max(1, min(5, iv)) if iv is not None else None

    personalization = _parse_1_to_5(personalization)
    applicability = _parse_1_to_5(applicability)
    vividness = _parse_1_to_5(vividness)
    logical_depth = _parse_1_to_5(logical_depth)

    not_applicable = (
        personalization is None
        and applicability is None
        and vividness is None
        and logical_depth is None
    )

    return {
        "turn_index": turn_index,
        "personalization_score": personalization,
        "applicability_score": applicability,
        "vividness_score": vividness,
        "logical_depth_score": logical_depth,
        "rationale": result.get("rationale", ""),
        "evidence": result.get("evidence", []),
        "not_applicable": not_applicable,
    }


def _build_teaching_quality_summary(per_turn: list[dict]) -> dict:
    """Aggregate turn-level teaching quality stats over scored turns only."""
    total_turns = len(per_turn)
    failed_turns = sum(1 for t in per_turn if t.get("error"))
    not_applicable_turns = sum(1 for t in per_turn if t.get("not_applicable"))
    metric_keys = [
        "personalization_score",
        "applicability_score",
        "vividness_score",
        "logical_depth_score",
    ]
    values_by_metric: dict[str, list[float]] = {k: [] for k in metric_keys}

    for t in per_turn:
        if t.get("not_applicable"):
            continue
        for k in metric_keys:
            v = t.get(k)
            if v is not None:
                values_by_metric[k].append(float(v))

    def _pack(values: list[float]) -> dict:
        return {
            "num_scored_turns": len(values),
            "avg": round(sum(values) / len(values), 4) if values else None,
            "max": max(values) if values else None,
            "min": min(values) if values else None,
        }

    return {
        "scale": "1-5",
        "num_total_turns": total_turns,
        "num_failed_turns": failed_turns,
        "failed_ratio": round(failed_turns / total_turns, 4) if total_turns else 0.0,
        "num_not_applicable_turns": not_applicable_turns,
        "not_applicable_ratio": round(not_applicable_turns / total_turns, 4) if total_turns else 0.0,
        "personalization": _pack(values_by_metric["personalization_score"]),
        "applicability": _pack(values_by_metric["applicability_score"]),
        "vividness": _pack(values_by_metric["vividness_score"]),
        "logical_depth": _pack(values_by_metric["logical_depth_score"]),
        "per_turn": per_turn,
    }


# ======================================================================
# Practice question evaluation (session-level, 5 metrics)
# ======================================================================

def _format_gaps_with_source_for_pq(gaps: list[dict], source_content: dict | None) -> str:
    """Format gaps + their source pages for practice question grounding-related metrics."""
    src_by_page = _normalize_source_by_page(source_content)
    lines = []
    for g in gaps:
        gid = g.get("gap_id", "?")
        concept = g.get("target_concept", "?")
        desc = (g.get("description", "") or "")[:300]
        correct = (g.get("correct_understanding", "") or "")[:300]
        lines.append(f"### {gid} - {concept}")
        lines.append(f"Description: {desc}")
        if correct:
            lines.append(f"Correct understanding: {correct}")
        pages = sorted(set(g.get("source_pages", [])))
        for p in pages:
            text = src_by_page.get(p, "")
            if text:
                excerpt = text[:1500] + ("..." if len(text) > 1500 else "")
                lines.append(f"Source page {p}:\n{excerpt}")
        lines.append("")
    return "\n".join(lines).strip() or "(no source content)"


def _clamp_score(raw, lo: int = 1, hi: int = 5) -> int | None:
    if raw is None:
        return None
    try:
        v = int(raw)
    except (TypeError, ValueError):
        return None
    return max(lo, min(hi, v))


async def _eval_pq_per_question(
    questions: list[str],
    gaps: list[dict],
    source_content: dict | None,
    profile: dict,
    temperature: float,
) -> list[dict]:
    """Per-question: fitness, groundedness, diversity, answer_quality, cross_concept."""
    from src.services.llm import factory

    gap_source_block = _format_gaps_with_source_for_pq(gaps, source_content)
    profile_view = json.dumps({
        "profile_id": profile.get("profile_id", ""),
        "learning_purpose": profile.get("learning_purpose", ""),
        "knowledge_state": profile.get("knowledge_state", {}),
    }, ensure_ascii=False, indent=2)

    results = []
    for i, q in enumerate(questions, start=1):
        prompt = (
            f"Evaluate this multiple-choice practice question (Q{i}) on five dimensions.\n\n"
            f"Question:\n{q}\n\n"
            f"Student profile:\n{profile_view}\n\n"
            f"Knowledge gaps and source content:\n{gap_source_block}\n\n"
            "Return strict JSON only:\n"
            "{\n"
            '  "fitness": 1-5,\n'
            '  "groundedness": 1-5,\n'
            '  "diversity": 1-5,\n'
            '  "answer_quality": 1-5,\n'
            '  "cross_concept": 1-5,\n'
            '  "rationale": "short reason"\n'
            "}\n\n"
            "Scoring guide:\n"
            "- fitness (1-5): Match to student profile + target gaps + suitable "
            "difficulty level.\n"
            "- groundedness (1-5): Are the question's claims, terminology, and "
            "correct answer consistent with the source content? "
            "Check FOUR aspects:\n"
            "  (a) Factual consistency: do factual claims align with and not "
            "contradict the source?\n"
            "  (b) Terminological consistency: does the question use the same "
            "definitions, terminology, and framing as the source? Different "
            "textbooks may define concepts differently; the question should follow "
            "the source's conventions, not introduce alternative definitions.\n"
            "  (c) Source grounding: does the question draw on specific details, "
            "examples, or structures from the source material? A question that "
            "references concrete content from the source (even paraphrased) is "
            "better grounded than one based on generic knowledge alone.\n"
            "  (d) Source attribution: does the question or its explanation "
            "attribute information to the source material? Attribution can be "
            "formal markers (e.g. [S1], [Source 2]) OR natural-language references "
            "(e.g. 'according to Chapter 3', 'as defined on page 60', 'the textbook "
            "states…', 'in Section 2.4'). Either form counts. A question whose stem "
            "or answer explanation indicates WHERE the information comes from is "
            "better grounded than one that presents source-derived content without "
            "any indication of its origin.\n"
            "A question that goes beyond the source (e.g. applies concepts to new "
            "scenarios) is fine as long as it doesn't distort or contradict the source. "
            "5 = all claims are accurate, terminology matches, the question clearly "
            "draws on specific source content, AND attributes information to the "
            "source (via citations or natural-language references); "
            "4 = mostly consistent, some evidence of source grounding, may include "
            "occasional attribution or clearly paraphrases the source even without "
            "explicit attribution; "
            "3 = some claims or definitions deviate from the source, or the question "
            "appears largely generic with weak connection to source material, no "
            "meaningful attribution; "
            "2 = multiple claims contradict the source, or key terms use different "
            "definitions, or no evidence of consulting the source; "
            "1 = core claims are wrong or hallucinated, or terminology directly "
            "conflicts with the source's definitions.\n"
            "- diversity (1-5): For this question itself, does it present a distinct "
            "angle/format/cognitive action compared with typical rote items?\n"
            "- answer_quality (1-5): Evaluate reference answer correctness + clarity. "
            "Also check answer-option consistency (correct option unambiguous; explanation "
            "matches selected answer; options are coherent).\n"
            "- cross_concept (1-5): Degree to which this question meaningfully connects "
            "multiple concepts instead of testing one isolated fact.\n"
        )
        eval_failed = False
        try:
            raw = await factory.complete(prompt=prompt,
                system_prompt="You are a strict education evaluator. Output valid JSON only.",
                temperature=temperature, max_tokens=800)
            parsed = extract_json(raw)
        except Exception as e:
            logger.warning("Practice Q%d per-question eval failed: %s", i, e)
            eval_failed = True
            parsed = {"fitness": 1, "groundedness": 1, "diversity": 1, "answer_quality": 1, "cross_concept": 1,
                      "rationale": f"fallback: {e}"}

        results.append({
            "question_index": i,
            "question_preview": q[:200],
            "fitness": _clamp_score(parsed.get("fitness")) or 1,
            "groundedness": _clamp_score(parsed.get("groundedness")) or 1,
            "diversity": _clamp_score(parsed.get("diversity")) or 1,
            "answer_quality": _clamp_score(parsed.get("answer_quality")) or 1,
            "cross_concept": _clamp_score(parsed.get("cross_concept")) or 1,
            "rationale": parsed.get("rationale", ""),
            "eval_failed": eval_failed,
        })
    return results


async def evaluate_practice_questions(
    *,
    practice_questions: list[str],
    entry: dict,
    temperature: float,
) -> dict:
    """Full practice-question evaluation with five per-question 1-5 metrics."""
    if not practice_questions:
        return {
            "per_question": [],
            "summary": {
                "num_questions": 0,
                "num_eval_failed_questions": 0,
                "eval_failed_ratio": 0.0,
                "avg_fitness": None,
                "avg_groundedness": None,
                "avg_diversity": None,
                "avg_answer_quality": None,
                "avg_cross_concept": None,
            },
        }

    gaps = entry.get("gaps", [])
    profile = entry.get("profile", {})
    source_content = entry.get("source_content")
    per_question = await _eval_pq_per_question(
        practice_questions, gaps, source_content, profile, temperature)

    fitness_scores = [pq["fitness"] for pq in per_question]
    ground_scores = [pq["groundedness"] for pq in per_question]
    diversity_scores = [pq["diversity"] for pq in per_question]
    answer_quality_scores = [pq["answer_quality"] for pq in per_question]
    cross_concept_scores = [pq["cross_concept"] for pq in per_question]
    eval_failed_questions = sum(1 for pq in per_question if pq.get("eval_failed"))
    total_questions = len(per_question)

    return {
        "per_question": per_question,
        "summary": {
            "num_questions": total_questions,
            "num_eval_failed_questions": eval_failed_questions,
            "eval_failed_ratio": round(eval_failed_questions / total_questions, 4) if total_questions else 0.0,
            "avg_fitness": round(sum(fitness_scores) / len(fitness_scores), 4) if fitness_scores else None,
            "avg_groundedness": round(sum(ground_scores) / len(ground_scores), 4) if ground_scores else None,
            "avg_diversity": round(sum(diversity_scores) / len(diversity_scores), 4) if diversity_scores else None,
            "avg_answer_quality": round(sum(answer_quality_scores) / len(answer_quality_scores), 4) if answer_quality_scores else None,
            "avg_cross_concept": round(sum(cross_concept_scores) / len(cross_concept_scores), 4) if cross_concept_scores else None,
        },
    }


def _load_entry_by_id(entry_id: str) -> dict | None:
    """
    Try to load entry by entry_id from generated JSONL files.
    Supports nested benchmark_<timestamp>/_all_entries.jsonl layout.
    """
    generated_dir = PROJECT_ROOT / "benchmark" / "data" / "generated"
    candidates = sorted(generated_dir.glob("**/*.jsonl"))
    for jsonl_path in candidates:
        with open(jsonl_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                entry = json.loads(line)
                if entry.get("entry_id") == entry_id:
                    return entry
    return None


async def _evaluate_single_session(
    *,
    transcript: list[dict],
    entry: dict,
    entry_id: str,
    skip_turns: bool,
    temperature: float,
    practice_questions: list[str] | None = None,
) -> dict:
    """Evaluate one session with turn-level + practice-question metrics."""
    dialog_msgs = _filter_dialog_messages(transcript)
    turns = _extract_turn_pairs(dialog_msgs)
    gaps = entry.get("gaps", [])
    gap_by_id = _build_gap_map(gaps)
    source_content = entry.get("source_content")

    has_pq = bool(practice_questions)
    eval_turns = turns
    if has_pq and eval_turns:
        eval_turns = turns[:-1]
        logger.info("Excluding last turn (practice questions) from turn-level evaluation")

    logger.info(
        "Metrics: faithfulness%s, teaching_quality, turn_count | practice_questions=%s",
        " [source present]" if source_content else "",
        f"{len(practice_questions)} Qs" if has_pq else "none",
    )

    student_turns = sum(1 for m in dialog_msgs if m.get("role") == "student")
    tutor_turns = sum(1 for m in dialog_msgs if m.get("role") == "tutor")
    turn_count_metric = {
        "student_turns": student_turns,
        "tutor_turns": tutor_turns,
        "paired_turns": len(eval_turns),
    }

    source_faithfulness_per_turn: list[dict] = []
    teaching_quality_per_turn: list[dict] = []
    all_gap_ids = sorted(gap_by_id.keys())

    if not skip_turns:
        for t in eval_turns:
            turn_index = t["turn_index"]
            student_message = t["student_message"]
            tutor_response = t["tutor_response"]
            recent_context = _get_recent_context(dialog_msgs, t["student_msg_index"])

            faith_turn = await evaluate_source_faithfulness_turn(
                turn_index=turn_index,
                student_message=student_message,
                tutor_response=tutor_response,
                recent_context=recent_context,
                mentioned_gap_ids=all_gap_ids,
                gap_by_id=gap_by_id,
                source_content=source_content,
                temperature=temperature,
            )
            source_faithfulness_per_turn.append(faith_turn)

            quality_turn = await evaluate_teaching_quality_turn(
                turn_index=turn_index,
                student_message=student_message,
                tutor_response=tutor_response,
                recent_context=recent_context,
                temperature=temperature,
            )
            teaching_quality_per_turn.append(quality_turn)

            logger.info(
                "Turn %d: faith=%s, personalization=%s, applicability=%s, vividness=%s, logical_depth=%s",
                turn_index,
                faith_turn.get("faithfulness_score", "N/A"),
                quality_turn.get("personalization_score", "N/A"),
                quality_turn.get("applicability_score", "N/A"),
                quality_turn.get("vividness_score", "N/A"),
                quality_turn.get("logical_depth_score", "N/A"),
            )

    source_faithfulness_metric = _build_source_faithfulness_summary(source_faithfulness_per_turn)
    teaching_quality_metric = _build_teaching_quality_summary(teaching_quality_per_turn)

    result: dict = {
        "entry_id": entry_id,
        "actual_turns": len(eval_turns),
        "metrics": {
            "source_faithfulness": source_faithfulness_metric,
            "teaching_quality": teaching_quality_metric,
            "turn_count": turn_count_metric,
        },
    }

    if has_pq and not skip_turns:
        logger.info("Evaluating %d practice questions...", len(practice_questions))
        pq_eval = await evaluate_practice_questions(
            practice_questions=practice_questions,
            entry=entry,
            temperature=temperature,
        )
        result["metrics"]["practice_questions"] = pq_eval
        s = pq_eval.get("summary", {})
        logger.info(
            "Practice Q: fitness=%.4f groundedness=%.4f diversity=%.4f answer_quality=%.4f cross_concept=%.4f",
            s.get("avg_fitness") or 0,
            s.get("avg_groundedness") or 0,
            s.get("avg_diversity") or 0,
            s.get("avg_answer_quality") or 0,
            s.get("avg_cross_concept") or 0,
        )
    elif has_pq and skip_turns:
        result["metrics"]["practice_questions"] = {
            "num_questions": len(practice_questions),
            "note": "skipped (--skip-turns)",
        }

    sf_fail = source_faithfulness_metric.get("num_failed_turns", 0)
    sf_total = source_faithfulness_metric.get("num_total_turns", 0)
    tq_fail = teaching_quality_metric.get("num_failed_turns", 0)
    tq_total = teaching_quality_metric.get("num_total_turns", 0)
    pq_summary = result.get("metrics", {}).get("practice_questions", {}).get("summary", {})
    pq_fail = pq_summary.get("num_eval_failed_questions", 0)
    pq_total = pq_summary.get("num_questions", 0)
    logger.info(
        "Scoring fail ratio: faithfulness=%d/%d (%.2f%%), teaching_quality=%d/%d (%.2f%%), practice_q=%d/%d (%.2f%%)",
        sf_fail,
        sf_total,
        (100.0 * sf_fail / sf_total) if sf_total else 0.0,
        tq_fail,
        tq_total,
        (100.0 * tq_fail / tq_total) if tq_total else 0.0,
        pq_fail,
        pq_total,
        (100.0 * pq_fail / pq_total) if pq_total else 0.0,
    )

    return result


def _safe_avg(vals: list[float]) -> float | None:
    return round(sum(vals) / len(vals), 4) if vals else None


def _aggregate_multi_session(session_results: list[dict]) -> dict:
    """Build lightweight aggregate view; each session gap stats stay independent."""
    if not session_results:
        return {}

    total_student_turns = 0
    total_tutor_turns = 0
    total_paired_turns = 0
    faith_scores: list[float] = []
    personalization_scores: list[float] = []
    applicability_scores: list[float] = []
    vividness_scores: list[float] = []
    logical_depth_scores: list[float] = []
    faith_total_turns = 0
    faith_failed_turns = 0
    tq_total_turns = 0
    tq_failed_turns = 0

    pq_total_questions = 0
    pq_failed_questions = 0
    pq_fitness: list[float] = []
    pq_ground: list[float] = []
    pq_diversity: list[float] = []
    pq_answer_quality: list[float] = []
    pq_cross_concept: list[float] = []

    for s in session_results:
        tc = s.get("metrics", {}).get("turn_count", {})
        total_student_turns += tc.get("student_turns", 0)
        total_tutor_turns += tc.get("tutor_turns", 0)
        total_paired_turns += tc.get("paired_turns", 0)

        sf = s.get("metrics", {}).get("source_faithfulness", {})
        faith_total_turns += sf.get("num_total_turns", 0) or 0
        faith_failed_turns += sf.get("num_failed_turns", 0) or 0
        for t in sf.get("per_turn", []):
            score = t.get("faithfulness_score")
            if score is not None and not t.get("not_applicable"):
                faith_scores.append(float(score))

        tq = s.get("metrics", {}).get("teaching_quality", {})
        tq_total_turns += tq.get("num_total_turns", 0) or 0
        tq_failed_turns += tq.get("num_failed_turns", 0) or 0
        for t in tq.get("per_turn", []):
            ps = t.get("personalization_score")
            app = t.get("applicability_score")
            vid = t.get("vividness_score")
            dep = t.get("logical_depth_score")
            if ps is not None and not t.get("not_applicable"):
                personalization_scores.append(float(ps))
            if app is not None and not t.get("not_applicable"):
                applicability_scores.append(float(app))
            if vid is not None and not t.get("not_applicable"):
                vividness_scores.append(float(vid))
            if dep is not None and not t.get("not_applicable"):
                logical_depth_scores.append(float(dep))

        pq = s.get("metrics", {}).get("practice_questions")
        if pq and pq.get("summary"):
            sm = pq["summary"]
            pq_total_questions += sm.get("num_questions", 0)
            pq_failed_questions += sm.get("num_eval_failed_questions", 0) or 0
            for key, lst in [
                ("avg_fitness", pq_fitness),
                ("avg_groundedness", pq_ground),
                ("avg_diversity", pq_diversity),
                ("avg_answer_quality", pq_answer_quality),
                ("avg_cross_concept", pq_cross_concept),
            ]:
                v = sm.get(key)
                if isinstance(v, (int, float)):
                    lst.append(float(v))

    result: dict = {
        "turn_count": {
            "student_turns_total": total_student_turns,
            "tutor_turns_total": total_tutor_turns,
            "paired_turns_total": total_paired_turns,
        },
        "source_faithfulness": {
            "scale": "1-5",
            "num_total_turns_total": faith_total_turns,
            "num_scored_turns_total": len(faith_scores),
            "num_failed_turns_total": faith_failed_turns,
            "failed_ratio_overall": round(faith_failed_turns / faith_total_turns, 4) if faith_total_turns else 0.0,
            "max_score_overall": max(faith_scores) if faith_scores else None,
            "min_score_overall": min(faith_scores) if faith_scores else None,
            "avg_score_overall": _safe_avg(faith_scores),
        },
        "teaching_quality": {
            "scale": "1-5",
            "num_total_turns_total": tq_total_turns,
            "num_failed_turns_total": tq_failed_turns,
            "failed_ratio_overall": round(tq_failed_turns / tq_total_turns, 4) if tq_total_turns else 0.0,
            "num_scored_turns_personalization_total": len(personalization_scores),
            "num_scored_turns_applicability_total": len(applicability_scores),
            "num_scored_turns_vividness_total": len(vividness_scores),
            "num_scored_turns_logical_depth_total": len(logical_depth_scores),
            "avg_personalization_overall": _safe_avg(personalization_scores),
            "avg_applicability_overall": _safe_avg(applicability_scores),
            "avg_vividness_overall": _safe_avg(vividness_scores),
            "avg_logical_depth_overall": _safe_avg(logical_depth_scores),
        },
    }

    if pq_total_questions > 0:
        result["practice_questions"] = {
            "total_questions_across_sessions": pq_total_questions,
            "num_eval_failed_questions_total": pq_failed_questions,
            "eval_failed_ratio_overall": round(pq_failed_questions / pq_total_questions, 4) if pq_total_questions else 0.0,
            "avg_fitness": _safe_avg(pq_fitness),
            "avg_groundedness": _safe_avg(pq_ground),
            "avg_diversity": _safe_avg(pq_diversity),
            "avg_answer_quality": _safe_avg(pq_answer_quality),
            "avg_cross_concept": _safe_avg(pq_cross_concept),
        }

    return result


async def evaluate_transcript(
    transcript_path: str | Path,
    skip_turns: bool = False,
    temperature: float = 0.2,
) -> dict:
    """
    Evaluate transcript using independent metrics (no weighted merge).

    Args:
        transcript_path: Path to transcript JSON
        skip_turns: If True, skip LLM per-turn metrics and keep only turn_count
        temperature: LLM temperature for metric-1 and metric-2
    """
    path = Path(transcript_path)
    if not path.exists():
        raise FileNotFoundError(f"Transcript not found: {path}")

    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    # Multi-session format
    if "sessions" in data:
        sessions = data["sessions"]
        profile_id = data.get("profile_id", "unknown")
        session_results = []

        for i, sess in enumerate(sessions):
            transcript = sess.get("transcript", [])
            entry = sess.get("entry")
            entry_id = sess.get("entry_id", f"session_{i+1}")

            if not entry:
                entry = _load_entry_by_id(entry_id)
            if not entry:
                logger.warning(
                    "Session %s has no entry; skipping (run multi-session again to save entry)",
                    entry_id,
                )
                continue

            logger.info("Evaluating session %d/%d: %s", i + 1, len(sessions), entry_id)
            sess_result = await _evaluate_single_session(
                transcript=transcript,
                entry=entry,
                entry_id=entry_id,
                skip_turns=skip_turns,
                temperature=temperature,
                practice_questions=sess.get("practice_questions"),
            )
            session_results.append(sess_result)

        if not session_results:
            raise ValueError(
                "No sessions could be evaluated (missing 'entry' in each session; "
                "re-run multi-session to save entries)"
            )

        return {
            "profile_id": profile_id,
            "transcript_path": str(path),
            "num_sessions": len(session_results),
            "sessions": session_results,
            "aggregate": _aggregate_multi_session(session_results),
        }

    # Single-session format
    transcript = data.get("transcript", [])
    entry = data.get("entry", {})
    if not entry:
        raise ValueError("Transcript must contain 'entry' (benchmark entry with profile, gaps, task)")

    result = await _evaluate_single_session(
        transcript=transcript,
        entry=entry,
        entry_id=data.get("entry_id", "unknown"),
        skip_turns=skip_turns,
        temperature=temperature,
        practice_questions=data.get("practice_questions"),
    )
    result["transcript_path"] = str(path)
    return result
