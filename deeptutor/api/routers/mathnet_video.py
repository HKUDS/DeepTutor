"""MathNet Video Generation API Router

Correct data flow:
1. Script Generation (Problem + Steps -> Structured Script)
2. TTS Synthesis (Script -> Audio + Sentence Boundaries)
3. Segment Duration Mapping (Boundaries -> Exact durations per segment)
4. Timed Manim Code Generation (Script + Durations -> Manim with exact timing)
5. Video Render (Manim code -> Video with exact audio duration)
6. Mux (Video + Audio -> Final)

Principle: TTS decides duration, Manim adapts to duration.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any, Match
import asyncio
import re

from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel

from deeptutor.services.config import load_config_with_main
from deeptutor.services.path_service import get_path_service
from deeptutor.utils.ffmpeg import check_ffmpeg_available

# Lecture script imports for Phase 1 enhancement
from deeptutor.agents.lecture_script import (
    LectureScriptGenerator,
    LectureScript,
    LectureSegment,
    ScriptTiming,
    optimize_script_with_llm,
    extract_visual_elements,
)

# Tier 2 diagram generator imports for Phase 2
from deeptutor.agents.diagram_generator import StaticDiagramGenerator

logger = logging.getLogger(__name__)
router = APIRouter()


class VideoGenerationRequest(BaseModel):
    """Request to generate a narrated video."""
    problem_id: str
    tts_provider: str = "edge"
    voice: str | None = None
    quality: str = "medium"  # low, medium, high
    force_regenerate: bool = False  # Force re-generation even if cached video exists
    optimize_script: bool = True  # Use LLM to optimize script for colloquial narration
    use_english_voice: bool = True  # Use English voice for narration


class VideoGenerationResponse(BaseModel):
    """Response from video generation."""
    status: str
    video_url: str | None
    duration_seconds: float
    generation_time_seconds: float


# Segment definition for timed generation
class ScriptSegment:
    """A segment of the lecture script with timing info."""
    def __init__(self, segment_type: str, title: str, script: str, visual_desc: str, step_index: int = 0):
        self.segment_type = segment_type  # "intro", "step", "conclusion"
        self.title = title
        self.script = script
        self.visual_desc = visual_desc
        self.step_index = step_index  # 0 for intro/conclusion, actual step number for steps
        self.start_ms: int = 0
        self.end_ms: int = 0
        self.duration_ms: int = 0
        self.sentence_boundaries: list[dict] = None  # set by _map_durations_to_segments

    def to_dict(self) -> dict:
        return {
            "type": self.segment_type,
            "title": self.title,
            "script": self.script[:100] + "..." if len(self.script) > 100 else self.script,
            "duration_ms": self.duration_ms,
        }


def _get_db_connection():
    """Get connection to MathNet database."""
    import sqlite3
    from pathlib import Path

    # Try to find database
    db_paths = [
        Path("/Users/xj/projectxjai/claude/code/deepmath/mathnet-kb/data/mathnet-kb.db"),
        Path("../mathnet-kb/data/mathnet-kb.db"),
        Path("../../mathnet-kb/data/mathnet-kb.db"),
    ]

    for path in db_paths:
        if path.exists():
            return sqlite3.connect(path)

    raise HTTPException(status_code=503, detail="MathNet database not found")


def _parse_json_field(value: str | None) -> list:
    """Parse JSON array field from database."""
    if not value:
        return []
    try:
        import json
        result = json.loads(value)
        return result if isinstance(result, list) else [str(result)]
    except Exception:
        return []


def _generate_script_segments(problem_data: dict, steps_data: list[dict]) -> list[ScriptSegment]:
    """Step 1: Generate structured script segments from problem and steps.

    Returns list of segments: Intro -> Step1 -> Step2 -> ... -> Conclusion
    """
    segments = []
    problem_id = problem_data.get("id", "0000")
    problem_md = problem_data.get("problem_markdown", "")
    problem_zh = problem_data.get("problem_zh", "") or problem_md

    # Intro segment - ENGLISH narration
    intro_script = (
        f"Today we're going to solve this math problem. "
        f"Problem ID is {problem_id}. "
        f"This problem {'has ' + str(len(steps_data)) + ' steps to solve.' if steps_data else 'is a comprehensive problem.'} "
        f"Let's get started."
    )
    segments.append(ScriptSegment(
        segment_type="intro",
        title=f"题目 {problem_id}",
        script=intro_script,
        visual_desc=f"Display problem {problem_id}: {problem_zh[:200]}",
        step_index=0
    ))

    # Step segments
    for step in steps_data:
        step_title = step.get("step_title_en") or step.get("step_title_zh", f"Step {step.get('step_index', 0)}")
        step_text = step.get("step_text_zh", "")
        explanation = step.get("explanation_zh", "")
        step_idx = step.get("step_index", 0)

        # Build narration - use FULL step content for complete voice
        # Step title in English for voice (Step 1, Step 2, etc.)
        display_title = f"Step {step_idx}"
        # Use FULL Chinese text - let TTS handle it with English voice (accent is OK, content must be complete)
        display_text = step_text
        display_explanation = explanation

        script = f"{display_title}. {display_text}. {display_explanation}"
        segments.append(ScriptSegment(
            segment_type="step",
            title=step_title,
            script=script,
            visual_desc=step.get("step_goal_zh", step_title),
            step_index=step_idx
        ))

    # Conclusion segment - ENGLISH
    conclusion_script = "Let's summarize our solution process. " + (
        f"We solved this problem in {len(steps_data)} steps. "
        if steps_data else ""
    ) + "Hope this explanation helps you understand the problem better."
    segments.append(ScriptSegment(
        segment_type="conclusion",
        title="总结",
        script=conclusion_script,
        visual_desc="Summary of solution",
        step_index=0
    ))

    return segments


async def _generate_script_with_lecture_layer(
    problem_data: dict,
    steps_data: list[dict],
    optimize: bool = True,
) -> list[ScriptSegment]:
    """Generate script using the Lecture Script layer with visual element extraction.

    This is the enhanced Phase 1 implementation that:
    1. Uses LectureScriptGenerator for base script with visual element extraction
    2. Optionally uses LLM to optimize for colloquial narration
    3. Converts to ScriptSegment format for existing pipeline

    Args:
        problem_data: Problem data from MathNet
        steps_data: Step data from MathNet
        optimize: Whether to use LLM optimization for colloquial narration

    Returns:
        List of ScriptSegment for the existing pipeline
    """
    # Use the new lecture script generator
    generator = LectureScriptGenerator()

    architecture = problem_data.get("architecture", {})
    if not architecture:
        # Try to construct minimal architecture from problem_data
        architecture = {
            "problem_summary_zh": problem_data.get("problem_zh", ""),
            "solution_strategy_zh": "",
        }

    # Generate base script (includes visual element extraction)
    lecture_script = generator.generate_from_mathnet(
        problem_id=problem_data.get("id", "0000"),
        problem_markdown=problem_data.get("problem_markdown", ""),
        architecture=architecture,
        steps=steps_data,
        final_answer=problem_data.get("final_answer"),
    )

    # Optionally optimize with LLM
    if optimize:
        try:
            # Convert steps_data to have visual_elements for problem_data
            problem_data_with_steps = problem_data.copy()
            problem_data_with_steps["steps"] = steps_data

            lecture_script = await optimize_script_with_llm(
                lecture_script, problem_data_with_steps
            )
            logger.info("Script optimized with LLM for colloquial narration")
        except Exception as e:
            logger.warning(f"LLM optimization failed, using base script: {e}")

    # Convert LectureScript to ScriptSegments
    segments = []

    # Intro segment
    intro = lecture_script.intro
    segments.append(ScriptSegment(
        segment_type="intro",
        title=intro.title,
        script=intro.script,
        visual_desc=intro.visual_description,
        step_index=0
    ))

    # Step segments
    for seg in lecture_script.segments:
        segments.append(ScriptSegment(
            segment_type="step",
            title=seg.title,
            script=seg.script,
            visual_desc=seg.visual_description,
            step_index=seg.step_index
        ))

    # Conclusion segment
    conclusion = lecture_script.conclusion
    segments.append(ScriptSegment(
        segment_type="conclusion",
        title=conclusion.title,
        script=conclusion.script,
        visual_desc=conclusion.visual_description,
        step_index=len(lecture_script.segments) + 1
    ))

    return segments


async def _synthesize_tts(
    segments: list[ScriptSegment],
    voice: str | None,
    use_english: bool = True,
) -> tuple[str, list[dict], float]:
    """Step 2: Synthesize TTS audio and get sentence boundaries.

    Returns: (audio_path, sentence_boundaries, total_duration_seconds)
    """
    from deeptutor.services.tts import get_tts_client

    # Merge all scripts for TTS — use space separator, NOT newlines
    # Newlines confuse the sentence boundary detection in edge-tts stream()
    full_script = " ".join([s.script for s in segments])

    # Voice selection based on language preference
    if not voice:
        if use_english:
            # Use English voice for optimized/colloquial scripts
            voice = "en-US-AriaNeural"
        else:
            # Use Chinese voice for direct Chinese narration
            voice = "zh-CN-XiaoxiaoNeural"

    logger.info(f"TTS using voice: {voice} (english={use_english}), script length: {len(full_script)} chars")

    tts = get_tts_client(provider="edge")
    tts_result = await tts.synthesize(full_script, voice=voice)

    logger.info(f"TTS generated: {tts_result.duration_seconds:.1f}s audio, "
                f"{len(tts_result.sentence_boundaries)} boundaries")

    # Convert boundaries to dicts
    boundaries = [b.to_dict() for b in tts_result.sentence_boundaries]

    return tts_result.audio_path, boundaries, tts_result.duration_seconds


def _map_durations_to_segments(segments: list[ScriptSegment], boundaries: list[dict]) -> float:
    """Step 3: Map sentence boundary timestamps to script segments using EXACT character-position matching.

    For each TTS SentenceBoundary (with real offset/duration from Azure), finds its
    position in the concatenated script text and assigns it to the owning segment.

    Each segment receives:
    - start_ms / end_ms / duration_ms: from assigned boundaries
    - sentence_boundaries: list of {text, start_ms, end_ms} for this segment

    Returns: total_duration_seconds
    """
    import re
    import bisect

    # Build concatenated full text and segment character ranges
    full_text_parts: list[str] = []
    seg_char_ranges: list[tuple[int, int]] = []  # (start_char, end_char) per segment
    char_pos = 0

    for seg in segments:
        seg_text = re.sub(r'\s+', ' ', seg.script.strip())
        full_text_parts.append(seg_text)
        seg_char_ranges.append((char_pos, char_pos + len(seg_text)))
        char_pos += len(seg_text) + 1  # +1 for space separator

    full_text = " ".join(full_text_parts)

    # Map each boundary to a character position in full_text via incremental search
    # boundary_texts holds the ordered boundary text from this segment
    boundary_char_positions: list[tuple[int, dict]] = []
    search_pos = 0

    for boundary in boundaries:
        btext = boundary.get("text", "")
        btext_norm = re.sub(r'\s+', ' ', btext.strip())

        if not btext_norm:
            boundary_char_positions.append((search_pos, boundary))
            continue

        # Try exact match first
        pos = full_text.find(btext_norm, search_pos)
        # Try without trailing period (Azure sometimes drops it)
        if pos < 0 and btext_norm.endswith('.'):
            pos = full_text.find(btext_norm[:-1], search_pos)
        # Try with trailing period added (Azure sometimes adds it)
        if pos < 0 and not btext_norm.endswith('.'):
            pos = full_text.find(btext_norm + '.', search_pos)

        if pos >= 0:
            boundary_char_positions.append((pos, boundary))
            search_pos = pos + len(btext_norm)
        else:
            # Fallback: use current search_pos (boundary text not found verbatim)
            boundary_char_positions.append((search_pos, boundary))

    # Assign each boundary to its owning segment by character position
    seg_start_chars = [r[0] for r in seg_char_ranges]
    seg_boundaries: list[list[dict]] = [[] for _ in segments]

    for char_pos, boundary in boundary_char_positions:
        # Binary search to find segment index
        seg_idx = bisect.bisect_right(seg_start_chars, char_pos) - 1
        seg_idx = max(0, min(seg_idx, len(segments) - 1))
        seg_boundaries[seg_idx].append(boundary)

    # Set timing on each segment
    total_ms = 0
    for i, seg in enumerate(segments):
        sboundaries = seg_boundaries[i]
        if sboundaries:
            seg.start_ms = sboundaries[0].get("start_ms", total_ms)
            seg.end_ms = sboundaries[-1].get("end_ms", total_ms + 5000)
            seg.duration_ms = seg.end_ms - seg.start_ms
            seg.sentence_boundaries = sboundaries
        else:
            # Fallback: estimate from segment text length
            estimated_duration = max(3000, len(seg.script) * 1000 // 4)
            seg.start_ms = total_ms
            seg.end_ms = total_ms + estimated_duration
            seg.duration_ms = estimated_duration
            seg.sentence_boundaries = None

        total_ms = seg.end_ms

    return total_ms / 1000.0  # Return seconds


async def _generate_timed_manim_code(segments: list[ScriptSegment], problem_data: dict) -> str:
    """Step 4: Generate Manim code via StaticDiagramGenerator deterministic templates.

    Uses rule-based StaticDiagramGenerator (not LLM) for reliable, consistent output.
    LLM is used only for script generation and TTS — visualization is 100% deterministic.
    """
    problem_id = problem_data.get("id", "0000")
    problem_markdown = problem_data.get("problem_markdown", "")
    steps = problem_data.get("steps", [])

    logger.warning(f"[TMFunc] _generate_timed_manim_code STARTED for {problem_id} (deterministic template mode)")

    # ---- Step 1: Convert ScriptSegment -> LectureSegment ----
    lecture_segments = []
    for seg in segments:
        duration_s = seg.duration_ms / 1000.0 if seg.duration_ms > 0 else 5.0
        ls = LectureSegment(
            step_index=seg.step_index,
            title=seg.title,
            script=seg.script,
            visual_description=seg.visual_desc,
            timing=ScriptTiming(
                estimated_duration_seconds=duration_s,
                min_duration=1.0,
                max_duration=60.0,
            ),
            start_time_ms=seg.start_ms,
            end_time_ms=seg.end_ms,
        )
        lecture_segments.append(ls)

    # Wire sentence_boundaries from TTS -> LectureSegment for subtitle timing
    for seg, ls in zip(segments, lecture_segments):
        ls.sentence_boundaries = seg.sentence_boundaries

    # ---- Step 2: Extract visual elements and step content ----
    for ls in lecture_segments:
        if ls.step_index > 0 and ls.step_index <= len(steps):
            step = steps[ls.step_index - 1]
            try:
                elements = extract_visual_elements(step)
                if elements:
                    ls.visual_elements = elements
            except Exception:
                pass

            # Store step content for template (Zh preferred, En fallback)
            ls.step_text_raw = step.get("step_text_zh", "") or step.get("step_text_en", "")
            ls.step_title = step.get("step_title_zh", "") or step.get("step_title_en", "")
            ls.step_goal = step.get("step_goal_zh", "") or step.get("step_goal_en", "")

        elif ls.step_index == 0 and problem_markdown:
            # Store clean problem text for intro display
            try:
                plain = re.sub(r'\$\$.*?\$\$', '', problem_markdown, flags=re.DOTALL)
                plain = re.sub(r'\$([^$]+)\$', r'\1', plain)
                plain = ' '.join(plain.split())
                ls.problem_text = plain
            except Exception:
                pass

    # ---- Step 3: Generate deterministic Manim code ----
    generator = StaticDiagramGenerator()
    code = generator.generate_for_segments(lecture_segments)

    # ---- Step 4: Post-process ----
    code = _inject_manim_subtitles(code, segments)

    try:
        code = _fix_chinese_mathtex(code)
    except Exception as e:
        logger.warning(f"[ChineseFix] _fix_chinese_mathtex crashed: {e}")

    code = _fix_common_manim_errors(code)
    code = _fix_unmatched_braces(code)

    # ---- Step 5: Compile validation ----
    try:
        compile(code, '<manim_code>', 'exec')
    except SyntaxError as e:
        logger.warning(f"Template code syntax error (line {e.lineno}: {e.msg}), applying fixes...")
        code = _fix_common_manim_errors(code)
        code = _force_normalize_indentation(code)
        code = _fix_truncated_expressions(code)
        code = _fix_unmatched_braces(code)
        compile(code, '<manim_code>', 'exec')

    logger.warning(f"[TMFunc] returning template-generated code ({len(code)} chars)")
    return code


def _inject_manim_subtitles(code: str, segments: list[ScriptSegment]) -> str:
    """Inject sentence-level scrolling subtitles into LLM-generated Manim code.

    Strategy: replace each self.wait(X) call inside a segment method with
    sentence-by-sentence subtitle + short wait blocks.

    Key difference from previous approach: ORIGINAL self.wait() calls are
    REPLACED (not removed and re-inserted elsewhere), preserving the original
    FadeIn → content → FadeOut structure and keeping content visible during subtitles.

    Font: sans-serif at fixed font_size=18, conditionally scaled only if too wide.
    """
    import re

    lines = code.split('\n')

    # Step 1: Parse construct() to map method names → segment indices
    method_to_index: dict[str, int] = {}
    inside_construct = False

    for line in lines:
        stripped = line.strip()
        if 'def construct(self)' in stripped:
            inside_construct = True
            continue
        if inside_construct:
            if stripped.startswith('def ') and '(self)' in stripped:
                break
            if stripped.startswith('self.') and '(' in stripped:
                call = stripped.split('#')[0].strip()
                method_name = call.split('(')[0].split('.', 1)[-1]
                if not method_name.startswith(('play', 'wait', 'add', 'remove', 'camera')):
                    method_to_index[method_name] = len(method_to_index)

    if not method_to_index:
        import logging
        _log = logging.getLogger(__name__)
        # INLINE CODE PATH: template emits SUBS_EARLY (before content) + SUBS_LATE (after content)
        # Pair them and split each segment's sentences between the two slots.
        # Sentences starting during content animation overlap go to EARLY.
        wait_list: list[tuple[int, str]] = []  # [(line_idx, marker), ...]
        for li, line in enumerate(lines):
            stripped = line.strip()
            if re.match(r'^self\.wait\(', stripped):
                if '# PAUSE' in line:
                    continue
                marker = 'late' if '# SUBS_LATE' in line else ('early' if '# SUBS_EARLY' in line else 'none')
                wait_list.append((li, marker))

        if not wait_list:
            return code

        OVERLAP_INTRO = 800      # FadeIn intro_content only
        OVERLAP_STEP = 1500      # FadeIn left + right
        OVERLAP_CONCLUSION = 1000  # FadeIn summary + answer

        def _make_subs(li, seg, sentences, boundaries, start_si, gap_ms, seg_idx, prefix, overlap_reduce=0.0):
            """Build subtitle block lines for a group of sentences."""
            line = lines[li]
            indent = ' ' * (len(line) - len(line.lstrip()))
            blocks = []
            for si, sentence in enumerate(sentences):
                idx = start_si + si
                escaped = sentence.replace('\\', '\\\\').replace('"', '\\"')
                if boundaries and idx < len(boundaries):
                    exact_ms = boundaries[idx]["end_ms"] - boundaries[idx]["start_ms"]
                    if si == len(sentences) - 1 and gap_ms > 0:
                        exact_ms += gap_ms
                    wait_s = max(0.3, exact_ms / 1000.0 - (overlap_reduce if si == 0 else 0))
                else:
                    fallback_ms = (seg.duration_ms / max(len(sentences), 1)) if seg.duration_ms > 0 else 3000
                    wait_s = max(0.3, fallback_ms / 1000.0 - (overlap_reduce if si == 0 else 0))
                blocks.append(f'{indent}_{prefix}_{seg_idx}_{si} = Text("{escaped}", font_size=18, color=GRAY_A, font="sans-serif")')
                blocks.append(f'{indent}if _{prefix}_{seg_idx}_{si}.width > 11.5:')
                blocks.append(f'{indent}    _{prefix}_{seg_idx}_{si}.scale(11.5 / _{prefix}_{seg_idx}_{si}.width)')
                blocks.append(f'{indent}_{prefix}_{seg_idx}_{si}.to_edge(DOWN, buff=0.15)')
                blocks.append(f'{indent}self.add(_{prefix}_{seg_idx}_{si})')
                blocks.append(f'{indent}self.wait({wait_s:.2f})')
                blocks.append(f'{indent}self.remove(_{prefix}_{seg_idx}_{si})')
            return '\n'.join(blocks)

        wait_map: dict[int, str] = {}
        seg_idx = 0
        wi = 0
        while wi < len(wait_list) and seg_idx < len(segments):
            early_li, early_marker = wait_list[wi]
            late_li = wait_list[wi + 1][0] if wi + 1 < len(wait_list) else None

            seg = segments[seg_idx]
            scripts = seg.script.strip() if seg.script else ''
            if not scripts or late_li is None:
                wi += 1
                seg_idx += 1
                continue

            sentences = _split_srt_sentences(scripts)
            sentences = [s.strip() for s in sentences if s.strip()]
            if not sentences:
                wi += 2
                seg_idx += 1
                continue

            if seg_idx == 0:
                overlap_ms = OVERLAP_INTRO
            elif seg_idx == len(segments) - 1:
                overlap_ms = OVERLAP_CONCLUSION
            else:
                overlap_ms = OVERLAP_STEP

            cutoff_ms = 300 + overlap_ms
            boundaries = seg.sentence_boundaries
            seg_offset = seg.start_ms or 0

            early_count = 0
            if boundaries and len(boundaries) >= len(sentences):
                for si in range(len(sentences)):
                    sent_start = boundaries[si].get("start_ms", seg_offset) - seg_offset
                    if sent_start < cutoff_ms:
                        early_count += 1
                    else:
                        break
            early_count = max(1, min(early_count, len(sentences) - 1))

            gap_ms = 0
            if boundaries and len(boundaries) >= len(sentences):
                total_sum = sum(b["end_ms"] - b["start_ms"] for b in boundaries[:len(sentences)])
                gap_ms = max(0, seg.duration_ms - total_sum)

            early_sents = sentences[:early_count]
            late_sents = sentences[early_count:]

            # Content animation duration for EARLY→LATE overlap
            # Values must match StaticDiagramGenerator.ANIM_DUR_* constants
            if seg_idx == 0:
                content_dur = StaticDiagramGenerator.ANIM_DUR_INTRO
            elif seg_idx == len(segments) - 1:
                content_dur = StaticDiagramGenerator.ANIM_DUR_CONCLUSION
            else:
                content_dur = StaticDiagramGenerator.ANIM_DUR_STEP

            if early_sents:
                early_code = _make_subs(early_li, seg, early_sents, boundaries, 0, 0, seg_idx, "e", overlap_reduce=content_dur)
                early_lines = early_code.rstrip().split('\n')
                early_lines = [l for l in early_lines if not l.strip().startswith('self.remove(')]
                wait_map[early_li] = '\n'.join(early_lines)

            if late_sents:
                late_code_lines = []
                for si in range(early_count):
                    late_code_lines.append(f'        self.remove(_e_{seg_idx}_{si})')
                late_code = _make_subs(late_li, seg, late_sents, boundaries, early_count, gap_ms, seg_idx, "l")
                late_code_lines.append(late_code)
                wait_map[late_li] = '\n'.join(late_code_lines)

            _log.warning(f"[SubDEBUG] Inline seg {seg_idx}: {len(early_sents)} early/{len(late_sents)} late sentences")
            wi += 2
            seg_idx += 1

        result = []
        for li, line in enumerate(lines):
            if li in wait_map:
                result.append(wait_map[li])
            else:
                result.append(line)

        _log.warning(f"[SubDEBUG] Total lines in result: {len(result)}")
        return '\n'.join(result)

    # DEBUG: log method-to-index mapping
    _log.warning(f"[SubDEBUG] Found {len(method_to_index)} methods: {list(method_to_index.keys())}")
    _log.warning(f"[SubDEBUG] Segments: {len(segments)}")
    for si, sg in enumerate(segments):
        _log.warning(f"[SubDEBUG] Seg{si}: type={sg.segment_type} title={sg.title[:40]} dur_ms={sg.duration_ms}")

    # Step 2: Find method boundaries
    method_ranges: list[tuple[int, int, str]] = []
    current_method: str | None = None
    current_start = None

    for lineno, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith('def ') and '(self)' in stripped:
            if current_method is not None and current_start is not None:
                method_ranges.append((current_start, lineno, current_method))
            current_method = stripped.split('def ')[1].split('(')[0].strip()
            current_start = lineno
        elif lineno == len(lines) - 1:
            if current_method is not None and current_start is not None:
                method_ranges.append((current_start, lineno + 1, current_method))

    # Step 3: Process each method — replace waits with subtitle blocks inline
    if method_ranges:
        first_def_line = min(start for start, _, _ in method_ranges)
        result: list[str] = list(lines[:first_def_line])
    else:
        result: list[str] = list(lines)

    for start, end, method_name in method_ranges:
        if method_name not in method_to_index:
            result.extend(lines[start:end])
            continue

        seg_idx = method_to_index[method_name]
        seg = segments[seg_idx]
        logger.warning(f"[SubDEBUG] Processing method '{method_name}' -> seg_idx={seg_idx}, dur_ms={seg.duration_ms}, script_len={len(seg.script or '')}")
        script = seg.script.strip() if seg.script else ''

        if not script:
            result.extend(lines[start:end])
            continue

        sentences = _split_srt_sentences(script)
        sentences = [s.strip() for s in sentences if s.strip()]
        if not sentences:
            result.extend(lines[start:end])
            continue

        boundaries = seg.sentence_boundaries

        # Compute the FIRST wait's indentation for subtitle lines
        # (all subtitles use method body indent level)
        first_line = lines[start]
        method_indent_len = len(first_line) - len(first_line.lstrip())
        indent = ' ' * (method_indent_len + 4)

        st_idx = 0

        # Calculate gap for last sentence absorption
        sentence_gap_ms = 0
        if boundaries and len(boundaries) >= len(sentences):
            total_sentence_ms = sum(b["end_ms"] - b["start_ms"] for b in boundaries[:len(sentences)])
            sentence_gap_ms = max(0, seg.duration_ms - total_sentence_ms)

        # with corresponding subtitle sentences.
        # Each self.wait() gets ONE sentence's subtitle (distributed round-robin).
        method_body = list(lines[start:end])
        wait_indices = []
        for j, line in enumerate(method_body):
            sl = line.strip()
            m = re.match(r'^self\.wait\(([^)]+)\)\s*(?:#.*)?$', sl)
            if m:
                wait_indices.append(j)

        if not wait_indices:
            # No wait() found — skip
            result.extend(lines[start:end])
            continue

        # Distribute subtitle sentences across wait() calls
        sentence_idx = 0
        for wi, wait_lineno in enumerate(wait_indices):
            if sentence_idx >= len(sentences):
                break  # no more sentences, keep remaining waits as-is

            # Calculate how many sentences this wait() gets (even distribution)
            remaining_waits = len(wait_indices) - wi
            remaining_sentences = len(sentences) - sentence_idx
            sentences_this_wait = (remaining_sentences + remaining_waits - 1) // remaining_waits  # ceil division

            # Build subtitle blocks for all sentences assigned to this wait
            sub_blocks = []
            for si in range(sentences_this_wait):
                idx = sentence_idx + si
                sentence = sentences[idx]
                escaped = sentence.replace('\\', '\\\\').replace('"', '\\"')

                if boundaries and idx < len(boundaries):
                    exact_ms = boundaries[idx]["end_ms"] - boundaries[idx]["start_ms"]
                    if sentence_gap_ms > 0 and idx == len(sentences) - 1:
                        exact_ms += sentence_gap_ms
                    wait_s = max(0.3, exact_ms / 1000.0 - (overlap_reduce if si == 0 else 0))
                else:
                    fallback_ms = (seg.duration_ms / max(len(sentences), 1)) if seg.duration_ms > 0 else 3000
                    wait_s = max(0.3, fallback_ms / 1000.0)

                single_sub = (
                    f'{indent}_st_{seg_idx}_{idx} = Text("{escaped}", font_size=18, color=GRAY_A, font="sans-serif")\n'
                    f'{indent}if _st_{seg_idx}_{idx}.width > 11.5:\n'
                    f'{indent}    _st_{seg_idx}_{idx}.scale(11.5 / _st_{seg_idx}_{idx}.width)\n'
                    f'{indent}_st_{seg_idx}_{idx}.to_edge(DOWN, buff=0.15)\n'
                    f'{indent}self.add(_st_{seg_idx}_{idx})\n'
                    f'{indent}self.wait({wait_s:.2f})\n'
                    f'{indent}self.remove(_st_{seg_idx}_{idx})'
                )
                sub_blocks.append(single_sub)

            # Replace the single wait line with ALL subtitle blocks
            method_body[wait_lineno] = ('', '\n'.join(sub_blocks))
            sentence_idx += sentences_this_wait

        logger.warning(f"[SubDEBUG] Method '{method_name}': {sentence_idx}/{len(sentences)} sentences placed, {len(wait_indices)} waits, exact_tts_timing")

        # Build output: replace marked wait lines with subtitle lines
        for line in method_body:
            if isinstance(line, tuple):
                prefix, sub_block = line
                if prefix:
                    result.append(prefix)
                for sub_line in sub_block.split('\n'):
                    result.append(sub_line)
            else:
                result.append(line)

    logger.warning(f"[SubDEBUG] Total lines in result: {len(result)}")
    return '\n'.join(result)


def _fix_common_manim_errors(code: str) -> str:
    """Fix common Manim code generation errors from the LLM.

    The LLM occasionally generates code with bugs like:
    - Bare variable references (e.g., a line with just `labels`)
    - Unclosed strings
    - Wrong indentation in edge cases

    Args:
        code: The raw code from LLM

    Returns:
        Fixed code
    """
    import re

    # Fix 0: Fix indentation errors before other fixers
    code = _dedent_method_body(code)

    # Fix 0.5: Strip aligned_center= from .arrange() calls — Manim 0.20.1 doesn't support it
    # LLM generates .arrange(DOWN, aligned_center=False, buff=0.2) but arrange() passes kwargs
    # to next_to() which has no 'aligned_center' param. Just remove the argument entirely.
    code = re.sub(r',\s*aligned_center\s*=\s*(?:True|False)', '', code)

    lines = code.split('\n')
    fixed_lines = []

    for line in lines:
        stripped = line.strip()

        # Skip empty comment-only or whitespace lines that look like bare variable refs
        # A bare identifier on its own line (not assignment, not in expression)
        if stripped and not stripped.startswith('#') and not stripped.startswith('import'):
            # Check if line is a standalone bare name (just a variable reference, no assignment)
            bare_name_pattern = r'^[a-zA-Z_][a-zA-Z0-9_]*$'
            if re.match(bare_name_pattern, stripped):
                # Check it's not already part of a comment/string and is not a keyword
                python_keywords = {'from', 'import', 'class', 'def', 'return', 'if', 'else', 'elif',
                                   'for', 'while', 'try', 'except', 'finally', 'with', 'as', 'pass',
                                   'break', 'continue', 'and', 'or', 'not', 'in', 'is', 'True',
                                   'False', 'None', 'self', 'self.', 'lambda', 'yield', 'raise'}
                if stripped not in python_keywords and '.' not in stripped:
                    # This is likely a bare variable reference - comment it out
                    indent = line[:len(line) - len(line.lstrip())]
                    fixed_lines.append(f"{indent}# {stripped}  # fixed: bare reference was commented out")
                    continue

        fixed_lines.append(line)

    # Fix 2: Remove lines with truncated attribute access like `.sc` or `.sca`
    # (LLM truncation: intended to be .scale(...) but got cut off mid-method-name)
    result = []
    truncated_pattern = re.compile(r'^\s*\w+\.[a-z]{1,3}\s*$')
    for line in fixed_lines:
        stripped = line.strip()
        if truncated_pattern.match(stripped) and '.' in stripped:
            known_short = {'dot', 'arr', 'set', 'add', 'sub', 'mul', 'div', 'pow', 'abs', 'all'}
            suffix = stripped.split('.')[-1]
            if suffix not in known_short:
                indent = line[:len(line) - len(line.lstrip())]
                result.append(f"{indent}# {stripped}  # fixed: truncated attribute removed")
                continue
        result.append(line)

    return '\n'.join(result)


def _dedent_method_body(code: str) -> str:
    """Fix incorrect indentation inside method bodies.

    LLM often generates lines with extra spaces inside method bodies,
    causing Python SyntaxError: unexpected indent.

    Strategy:
    1. Find method definitions and track their indentation level
    2. Inside each method body, if a line is indented MORE than 1 level
       deeper than the method def AND the preceding line doesn't end
       with ':' (not a control flow start), reduce to method level + 4
    """
    import re

    lines = code.split('\n')
    result: list[str] = []
    method_indent = 0
    inside_method = False
    prev_line_endswith_colon = False

    for i, line in enumerate(lines):
        stripped = line.rstrip()
        indent = len(line) - len(line.lstrip())

        # Detect method definition
        method_match = re.match(r'^(\s*)def\s+\w+\(self', line)
        if method_match:
            method_indent = len(method_match.group(1))
            inside_method = True
            prev_line_endswith_colon = False
            result.append(line)
            continue

        if inside_method:
            # Check if we've left the method (next def or class-level statement)
            if stripped and indent <= method_indent and not stripped.startswith('#'):
                # A non-comment line at or above method indent level = end of method body
                # But check: blank lines between methods may have 0 indent
                if indent < method_indent and stripped:
                    inside_method = False
                    result.append(line)
                    continue
                elif indent == method_indent:
                    # Could be a decorator or another method
                    if not stripped.startswith('@'):
                        inside_method = False
                        result.append(line)
                        continue

            # Inside method body: check for unexpected deep indent
            expected_min = method_indent + 4  # normal body indent
            # Max expected: method_indent + 8 (one nested block, e.g. for/if)
            # But this can be deeper for nested structures.
            # Safe check: if indent > expected_min + 8 AND prev line doesn't end with ':' and isn't a continuation
            if indent > expected_min + 8 and not prev_line_endswith_colon:
                # Unexpected indent: reduce to method_indent + 4
                fixed_line = ' ' * (method_indent + 4) + line.lstrip()
                result.append(fixed_line)
                prev_line_endswith_colon = fixed_line.rstrip().endswith(':')
                continue

        # Track whether this line ends with ':' (control flow start)
        prev_line_endswith_colon = stripped.endswith(':')
        result.append(line)

    return '\n'.join(result)


def _fix_unmatched_braces(code: str) -> str:
    """Fix unclosed parentheses/brackets/braces from LLM truncation at file end."""
    open_count = code.count('(') + code.count('[') + code.count('{')
    close_count = code.count(')') + code.count(']') + code.count('}')
    if open_count > close_count:
        needed = open_count - close_count
        # Determine which type: assume all open are '(' (most common in Manim API calls)
        code += ')' * needed
    return code


def _fix_chinese_mathtex(code: str) -> str:
    """Replace MathTex() containing Unicode letters (Greek, CJK, Cyrillic, etc.) with Text().

    pdflatex (used by Manim's MathTex) crashes on non-ASCII Unicode letter
    characters (e.g. Greek ``τ``, CJK ``平行``, Cyrillic ``п``).  Text()
    uses Cairo/pango and handles these correctly.
    """
    import re
    import unicodedata

    def _has_non_ascii_letter(s: str) -> bool:
        """pdflatex crashes on non-ASCII letter characters."""
        for c in s:
            if ord(c) > 127 and unicodedata.category(c).startswith('L'):
                return True
        return False

    def _find_closing_paren(line: str, start: int) -> int:
        depth = 0
        for j in range(start, len(line)):
            if line[j] == '(':
                depth += 1
            elif line[j] == ')':
                depth -= 1
                if depth == 0:
                    return j + 1
        return len(line)

    result_lines: list[str] = []
    for line in code.split('\n'):
        # Pass 1: fix MathTex( with non-ASCII letters
        if 'MathTex(' in line and _has_non_ascii_letter(line):
            call_start = line.index('MathTex(')
            call_end = _find_closing_paren(line, call_start + len('MathTex') - 1)
            inner = line[call_start + len('MathTex('):call_end - 1]

            quote = 'r"' if inner.startswith('r"') else ('"' if inner.startswith('"') else None)
            if quote:
                content_rest = inner[len(quote):]
                close_pos = content_rest.index('"')
                content = content_rest[:close_pos]
                if _has_non_ascii_letter(content):
                    rest = content_rest[close_pos + 1:]
                    fs_match = re.search(r'font_size\s*=\s*(\d+)', rest)
                    if fs_match:
                        raw_fs = int(fs_match.group(1))
                        new_fs = max(14, int(raw_fs * 0.65))
                        rest = rest[:fs_match.start()] + rest[fs_match.end():]
                        rest = re.sub(r'^,\s*', '', rest)
                        inner_replacement = f'{quote}{content}", font_size={new_fs}'
                        if rest:
                            inner_replacement += ', ' + rest
                    else:
                        inner_replacement = f'{quote}{content}", font_size=20'
                    line = line[:call_start] + f'Text({inner_replacement})' + line[call_end:]

        # Pass 2: inside raw strings, strip Chinese from \text{...} content
        # e.g., r"\text{合并剩余项: } +22n^2" → r"\text{ } +22n^2"
        if re.search(r'[一-鿿]', line):
            line = re.sub(
                r'(\\text\{)([^}]*[一-鿿][^}]*)(\})',
                lambda m: m.group(1) + re.sub(r'[一-鿿]+', '', m.group(2)).strip() + m.group(3),
                line
            )

        result_lines.append(line)

    result = '\n'.join(result_lines)
    if result != code:
        logger.info(f"[ChineseFix] Fixed Unicode content in strings")
    return result


def _validate_layout_compliance(code: str) -> bool:
    """Validate that generated code follows left-right layout rules.

    Checks:
    1. Graphics use LEFT panel positioning (LEFT * 3.5 + UP * 0.3)
    2. Text/formulas use RIGHT panel positioning (RIGHT * 3.5 + UP * 0.3)
    3. No content in forbidden middle zone

    Returns True if layout is compliant.
    """
    import re

    problems = []

    # CRITICAL: Must have exact LEFT * 3.5 and RIGHT * 3.5 positioning
    # Check entire code, not just move_to calls (LLM may use direct coordinates)
    has_left_panel = 'LEFT * 3.5' in code
    has_right_panel = 'RIGHT * 3.5' in code

    if not has_left_panel:
        problems.append('Missing LEFT * 3.5 panel positioning for graphics')
    if not has_right_panel:
        problems.append('Missing RIGHT * 3.5 panel positioning for text/formulas')

    # Check for forbidden patterns (content not in left-right layout)
    forbidden_patterns = [
        (r'\.move_to\(UP\s*\*\s*[\d\.]+\s*\)(?!\s*\+\s*(LEFT|RIGHT))', 'UP without LEFT/RIGHT'),
        (r'\.move_to\(DOWN\s*\*', 'DOWN direction'),
        (r'\.move_to\(ORIGIN\)', 'ORIGIN center'),
        (r'\.move_to\(CENTER\)', 'CENTER position'),
    ]

    for pattern, desc in forbidden_patterns:
        if re.search(pattern, code):
            problems.append(desc)

    if problems:
        logger.warning(f"Layout validation failed: {problems}")
        return False

    return True


def _extract_math_expressions(text: str) -> list[str]:
    """Extract mathematical expressions from Chinese text.

    Returns list of MathTex-ready strings.
    """
    import re

    expressions = []

    # Pattern 1: $...$ or $$...$$
    latex_pattern = r'\$\$?(.*?)\$\$?'
    for match in re.finditer(latex_pattern, text):
        expr = match.group(1).strip()
        if expr:
            expressions.append(expr)

    # Pattern 2: equations with = < > ≤ ≥
    eq_pattern = r'([\w\^\{\}\(\)\[\]\+\-\*/=<>≤≥]+=[\w\^\{\}\(\)\[\]\+\-\*/=<>≤≥]+)'
    for match in re.finditer(eq_pattern, text):
        expr = match.group(1).strip()
        # Filter out very short or non-math matches
        if len(expr) >= 3 and any(c in expr for c in '=_^+*/'):
            expressions.append(expr)

    # Pattern 3: polynomial terms (n^2, x^3, etc.)
    poly_pattern = r'[a-zA-Z]\^?\d*\s*[\+\-]\s*[a-zA-Z]?\^?\d*'
    for match in re.finditer(poly_pattern, text):
        expr = match.group(0).strip()
        if len(expr) >= 3:
            expressions.append(expr)

    # Pattern 4: numbers with special meaning (coordinates, values)
    coord_pattern = r'[=为是]\s*\(?\s*([\d\-\.]+)\s*[,，]\s*([\d\-\.]+)\s*\)?'
    for match in re.finditer(coord_pattern, text):
        expressions.append(f"({match.group(1)}, {match.group(2)})")

    # Deduplicate while preserving order
    seen = set()
    unique = []
    for expr in expressions:
        key = expr.replace(' ', '')
        if key not in seen:
            seen.add(key)
            unique.append(expr)

    return unique[:5]  # Limit to 5 expressions


def _text_to_mathtex_formulas(text: str, max_lines: int = 4) -> list[str]:
    """Convert Chinese math text to list of MathTex-compatible formulas.

    This is the core of Tier 2: extract displayable math from step text.
    """
    import re

    formulas = []

    # Direct LaTeX extraction
    if '$' in text:
        latex_matches = re.findall(r'\$\$?(.*?)\$\$?', text)
        for m in latex_matches:
            clean = m.strip()
            if clean:
                formulas.append(clean)

    # Look for specific math patterns and convert
    # Pattern: "n^4 - 4n^3 + ..." polynomial
    poly_match = re.search(r'([a-zA-Z]\^?\d*(?:\s*[\+\-]\s*[a-zA-Z]\^?\d*)+)', text)
    if poly_match:
        formulas.append(poly_match.group(1).replace(' ', ''))

    # Pattern: "(n^2-2n)^2" type expressions
    paren_match = re.search(r'\([^()]+\)\^?\d*', text)
    if paren_match:
        expr = paren_match.group(0)
        if any(c in expr for c in '^+-=*/'):
            formulas.append(expr)

    # Pattern: "k = ..." or "x = ..." assignments
    assign_match = re.search(r'([a-zA-Z])\s*=\s*([^，。,\.]+)', text)
    if assign_match:
        var, val = assign_match.groups()
        val_clean = val.strip()[:30]  # Limit length
        formulas.append(f"{var} = {val_clean}")

    # Pattern: inequality like "k >= 18"
    ineq_match = re.search(r'([a-zA-Z])\s*([<>≥≤]|>=|<=)\s*(\d+)', text)
    if ineq_match:
        var, op, num = ineq_match.groups()
        op_tex = {'>=': r'\geq', '<=': r'\leq', '>': '>', '<': '<', '≥': r'\geq', '≤': r'\leq'}.get(op, op)
        formulas.append(f"{var} {op_tex} {num}")

    # If nothing found, create a generic display
    if not formulas and len(text) > 10:
        # Take key numbers and symbols
        key_chars = re.findall(r'[\d\+\-\*/=\^\(\)\[\]\{\}a-zA-Z]+', text)
        if key_chars:
            combined = ' '.join(key_chars[:8])
            formulas.append(combined)

    return formulas[:max_lines]


def _generate_tier2_static_manim(segments: list[ScriptSegment], problem_id: str,
                                  problem_markdown: str = "", steps: list = None) -> str:
    """TIER 2: Generate static visualization with geometry graphics.

    Strategy:
    1. Try StaticDiagramGenerator (uses MathTex + GeometryFactory — LaTeX IS installed)
    2. If that fails, use text-only fallback with LEFT * 3.5 geometry panel
    """
    steps = steps or []

    # ---- Strategy A: StaticDiagramGenerator ----
    try:
        logger.info("Attempting StaticDiagramGenerator for Tier 2...")
        generator = StaticDiagramGenerator()

        # Convert ScriptSegment → LectureSegment
        lecture_segments = []
        for seg in segments:
            duration_s = seg.duration_ms / 1000.0 if seg.duration_ms > 0 else 5.0
            ls = LectureSegment(
                step_index=seg.step_index,
                title=seg.title,
                script=seg.script,
                visual_description=seg.visual_desc,
                timing=ScriptTiming(
                    estimated_duration_seconds=duration_s,
                    min_duration=1.0,
                    max_duration=60.0,
                ),
                start_time_ms=seg.start_ms,
                end_time_ms=seg.end_ms,
            )
            lecture_segments.append(ls)

        # Wire sentence_boundaries from TTS -> LectureSegment for subtitle timing
        for seg, ls in zip(segments, lecture_segments):
            ls.sentence_boundaries = seg.sentence_boundaries

        # Extract visual elements from step data and attach, plus inject step_text
        import re
        for ls in lecture_segments:
            if ls.step_index > 0 and ls.step_index <= len(steps):
                step = steps[ls.step_index - 1]
                try:
                    elements = extract_visual_elements(step)
                    if elements:
                        ls.visual_elements = elements
                except Exception:
                    pass

                # Store clean step text for RIGHT panel display (voice → step text)
                raw_text = step.get("step_text_en", "") or step.get("step_text_zh", "")
                # Remove $...$ signs but keep text content between them
                clean = re.sub(r'\$([^$]+)\$', lambda m: m.group(1), raw_text)
                clean = ' '.join(clean.split())  # Normalize whitespace
                ls.step_text = clean[:300]  # Cap at 300 chars for display
            elif ls.step_index == 0 and problem_markdown:
                # Store clean problem text for intro display (instead of $...$ formula fragments)
                try:
                    # Remove display math $$...$$, keep clean text
                    plain = re.sub(r'\$\$.*?\$\$', '', problem_markdown, flags=re.DOTALL)
                    # Remove inline math $...$ but keep content
                    plain = re.sub(r'\$([^$]+)\$', r'\1', plain)
                    # Clean up whitespace
                    plain = ' '.join(plain.split())
                    # Store as attribute so _generate_intro_content() can display it
                    ls.problem_text = plain
                except Exception:
                    pass

        sdg_code = generator.generate_for_segments(lecture_segments)
        if sdg_code and len(sdg_code) > 300:
            logger.info("StaticDiagramGenerator succeeded — using generated code")
            return sdg_code
        else:
            logger.warning("StaticDiagramGenerator generated too little content, using text fallback")
    except Exception as e:
        logger.warning(f"StaticDiagramGenerator failed: {e}, using text fallback")

    # ---- Strategy B: Text-only fallback with LEFT * 3.5 geometry panel ----
    logger.info("Using text-only Tier 2 fallback with LEFT * 3.5 geometry panel")
    code_lines = [
        "from manim import *",
        "import numpy as np",
        "",
        "class MathVisualization(Scene):",
        "    def construct(self):",
        "        self.camera.frame_width = 14",
        "        self.camera.frame_height = 8",
        "",
        "        # Geometry constants for LEFT panel",
        "        # Triangle coordinates for a general acute triangle",
        "        tri_A = np.array([0, 2.0, 0])",
        "        tri_B = np.array([-3.5, -1.5, 0])",
        "        tri_C = np.array([3.5, -1.5, 0])",
        "        tri_D = np.array([0, -1.5, 0])  # foot from A to BC",
        "        triangle_left = Polygon(tri_A, tri_B, tri_C, color=WHITE, stroke_width=2)",
        "        triangle_left.move_to(LEFT * 3.5 + UP * 0.3)",
        "",
    ]

    for seg in segments:
        duration = seg.duration_ms / 1000.0
        title = seg.title.replace('"', '\\"')

        # Animation budget: 0.5s in + wait + 0.5s out
        wait_time = max(1.0, duration - 1.0)

        code_lines.extend([
            f"        # ===== {seg.segment_type}: {title} =====",
            f"        step_label = Text(\"Step {seg.step_index}: {title}\", font_size=24, color=YELLOW)",
            "        step_label.to_edge(UP, buff=0.3)",
            "        self.play(FadeIn(step_label), run_time=0.3)",
            "",
        ])

        if seg.segment_type == "intro":
            clean_problem = problem_markdown.replace('"', '\\"').replace('$', '')
            # Full-width centered layout for intro (no left-right split)
            import textwrap
            intro_lines = textwrap.wrap(clean_problem, width=55)
            if len(intro_lines) > 10:
                intro_lines = intro_lines[:8] + ["..."] + intro_lines[-2:]
            code_lines.extend([
                "        # Full-width centered layout for intro (no left-right split)",
                "        intro_content = VGroup()",
            ])
            for i, line in enumerate(intro_lines):
                escaped = line.replace('"', '\\"')
                code_lines.extend([
                    f"        prob_{i} = Text(\"{escaped}\", font_size=18, line_spacing=1.2)",
                    f"        intro_content.add(prob_{i})",
                ])
            code_lines.extend([
                "        intro_content.arrange(DOWN, buff=0.15, aligned_edge=LEFT)",
                "        intro_content.move_to(UP * 0.3)",
                "        if intro_content.width > 12:",
                "            intro_content.scale(12.0 / intro_content.width)",
                "        self.play(FadeIn(intro_content), run_time=0.5)",
                f"        self.wait({max(3.0, wait_time)})",
                "        self.play(FadeOut(intro_content), run_time=0.5)",
            ])

        elif seg.segment_type == "step" and seg.step_index and seg.step_index <= len(steps):
            step = steps[seg.step_index - 1]
            step_text = step.get("step_text_zh", "") or step.get("text_zh", "")
            step_title = step.get("step_title_zh", "")

            clean_title = step_title.replace('"', '\\"')[:50]
            code_lines.extend([
                "        # Step title on RIGHT panel, triangle on LEFT",
                "        self.play(FadeIn(triangle_left), run_time=0.3)",
                f"        step_title_text = Text(\"{clean_title}\", font_size=22, color=YELLOW)",
                "        step_title_text.move_to(RIGHT * 3.5 + UP * 0.3)",
                "        self.play(FadeIn(step_title_text), run_time=0.5)",
            ])

            clean_text = step_text.replace('"', '\\"')[:100]
            code_lines.extend([
                f"        content = Text(\"{clean_text}...\", font_size=18, color=WHITE)",
                "        content.move_to(RIGHT * 3.5 + UP * 0.3 + DOWN * 0.8)",
                "        content.scale(0.9)",
                "        self.play(FadeIn(content), run_time=0.5)",
                f"        self.wait({wait_time})",
                "        self.play(FadeOut(content), FadeOut(step_title_text), run_time=0.5)",
            ])

        elif seg.segment_type == "conclusion":
            wait_final = max(2.0, wait_time)
            code_lines.extend([
                "        # Final answer on RIGHT panel, triangle on LEFT",
                "        self.play(FadeIn(triangle_left), run_time=0.3)",
                f"        answer = Text(\"{title}\", font_size=30, color=GREEN)",
                "        answer.move_to(RIGHT * 3.5 + UP * 0.3)",
                "        self.play(FadeIn(answer), run_time=0.5)",
                f"        self.wait({wait_final})",
                "        self.play(FadeOut(answer), run_time=0.5)",
            ])

        code_lines.extend([
            "        self.play(FadeOut(step_label), run_time=0.3)",
            "",
        ])

    return "\n".join(code_lines)


def _generate_fallback_manim(segments: list[ScriptSegment], problem_id: str,
                            problem_markdown: str = "", steps: list = None) -> str:
    """Generate fallback Manim code - now delegates to Tier 2 static visualization."""
    return _generate_tier2_static_manim(segments, problem_id, problem_markdown, steps)


async def _render_manim_video_direct(manim_code: str, output_dir: Path, problem_id: str) -> Path:
    """Step 5: Render Manim code directly using ManimRenderService.

    This bypasses the MathAnimatorPipeline's retry mechanism which can
    regenerate code and lose layout fixes. Uses the provided code directly.

    Returns: Path to rendered video
    """
    from deeptutor.agents.math_animator.renderer import ManimRenderService

    path_service = get_path_service()
    outputs_root = path_service.get_public_outputs_root()

    turn_id = f"mathnet_{problem_id}_{int(time.time())}"

    async def progress_callback(msg: str, raw: Any = None) -> None:
        logger.info(f"[Render] {msg}")

    renderer = ManimRenderService(turn_id, progress_callback=progress_callback)

    try:
        render_result = await renderer.render(
            code=manim_code,
            output_mode="video",
            quality="medium",
        )

        if not render_result.artifacts:
            raise RuntimeError("Render failed: no output artifact")

        video_url = render_result.artifacts[0].url

        if video_url.startswith("/api/outputs/"):
            rel_path = video_url.replace("/api/outputs/", "")
            video_path = outputs_root / rel_path
        else:
            video_path = Path(video_url)

        if not video_path.exists():
            raise RuntimeError(f"Render failed: video file not found at {video_path}")

        logger.info(f"Render succeeded: {video_path}")
        return video_path

    except Exception as e:
        logger.error(f"Render failed: {e}")
        raise RuntimeError(f"Video rendering failed: {e}")


def _force_normalize_indentation(code: str) -> str:
    """Aggressively normalize ALL indentation inside method bodies.

    LLM code often has inconsistent indentation (tabs, spaces in odd multiples).
    This snaps every indented line to the nearest multiple-of-4 within method body.
    Only applies to lines inside 'def construct(self)' or defined sub-methods.
    """
    import re
    lines = code.split('\n')
    result: list[str] = []
    in_method = False
    method_indent = 0

    for line in lines:
        stripped = line.rstrip()
        if not stripped:
            result.append(line)
            continue

        raw_indent = len(line) - len(line.lstrip())
        content = line.lstrip()

        # Detect method definitions
        method_match = re.match(r'^(\s*)def\s+\w+\(self', line)
        if method_match:
            method_indent = len(method_match.group(1))
            in_method = True
            result.append(line)
            continue

        if in_method:
            # End of method: line at or above method indent (not comment, not decorator)
            if raw_indent <= method_indent and not stripped.startswith('#'):
                if not stripped.startswith('@'):
                    in_method = False
                    result.append(line)
                    continue

            # Inside method: snap indent to nearest multiple of 4
            if raw_indent > method_indent:
                # Calculate what the indent SHOULD be (multiple of 4)
                relative = raw_indent - method_indent
                # Snap to nearest multiple of 4, minimum 4
                snapped_relative = max(4, round(relative / 4) * 4)
                snapped = method_indent + snapped_relative
                result.append(' ' * snapped + content)
                continue

        result.append(line)

    return '\n'.join(result)


def _fix_truncated_expressions(code: str) -> str:
    """Fix LLM output truncation: remove lines with incomplete expressions.

    Common truncation patterns (binary operator without right operand):
    - move_to(RIGHT *)      — operator * missing right operand
    - obj.shift(LEFT +      — trailing operator
    - SomeClass(            — unclosed call (will be handled by _fix_unmatched_braces)

    Strategy: detect and comment out lines with binary operators that
    lack a right operand (followed immediately by ')' or end-of-line).
    """
    import re
    lines = code.split('\n')
    result: list[str] = []

    for line in lines:
        stripped = line.strip()
        indent = line[:len(line) - len(line.lstrip())]

        # Skip empty/comment lines
        if not stripped or stripped.startswith('#'):
            result.append(line)
            continue

        # Pattern 1: binary operator missing right operand before ')'
        # e.g., move_to(RIGHT *) or .shift(LEFT +)
        if re.search(r'\([^()]*([+\-*/%&|^<>!=])\s*\)\s*$', stripped):
            result.append(f"{indent}pass  # fixed: incomplete expression (operator without right operand)")
            continue

        # Pattern 2: line ends with a bare binary operator (no continuation)
        # e.g.,   obj.shift(LEFT +   but NOT import/from lines (from manim import *)
        if not stripped.startswith(('import ', 'from ')):
            if re.search(r'[+\-*/%&|^<>!=]\s*$', stripped.rstrip(')').rstrip()):
                result.append(f"{indent}pass  # fixed: line ends with bare operator (truncated)")
                continue

        result.append(line)

    return '\n'.join(result)


async def _render_manim_video(manim_code: str, output_dir: Path, problem_id: str) -> Path:
    """Render Manim code to video. Single path — no fallback."""
    logger.info(f"[Render] Rendering Manim code ({len(manim_code)} chars)")
    try:
        result = await _render_manim_video_direct(manim_code, output_dir, f"{problem_id}_llm")
        return result
    except Exception as e:
        raise RuntimeError(f"Video rendering failed: {e}")


def _generate_srt_subtitles(segments: list[ScriptSegment]) -> str:
    """Generate SRT format subtitles with sentence-level scrolling.

    Splits each segment's script into sentences and divides the segment's
    timing proportionally by character count. This creates natural-looking
    scrolling subtitles instead of one static block per segment.
    """
    srt_lines = []
    subtitle_index = 1

    for seg in segments:
        start_ms = seg.start_ms
        end_ms = seg.end_ms
        total_duration_ms = end_ms - start_ms

        script = seg.script.replace("\n", " ")
        sentences = _split_srt_sentences(script)

        if len(sentences) <= 1:
            # Fallback: single subtitle entry for this segment
            en_text = script[:117] + "..." if len(script) > 120 else script
            srt_lines.append(str(subtitle_index))
            srt_lines.append(f"{_ms_to_srt_time(start_ms)} --> {_ms_to_srt_time(end_ms)}")
            srt_lines.append(en_text)
            srt_lines.append("")
            subtitle_index += 1
            continue

        # Distribute timing proportionally by character count
        total_chars = sum(len(s) for s in sentences)
        current_ms = start_ms

        for sentence in sentences:
            sentence = sentence.strip()
            if not sentence:
                continue

            # Estimate duration proportional to char count (min 1.0s)
            ratio = len(sentence) / max(total_chars, 1)
            sentence_duration_ms = max(1000, int(total_duration_ms * ratio))

            sentence_end_ms = min(current_ms + sentence_duration_ms, end_ms)

            srt_lines.append(str(subtitle_index))
            srt_lines.append(f"{_ms_to_srt_time(current_ms)} --> {_ms_to_srt_time(sentence_end_ms)}")
            srt_lines.append(sentence)
            srt_lines.append("")
            subtitle_index += 1
            current_ms = sentence_end_ms

    return "\n".join(srt_lines)


def _split_srt_sentences(text: str) -> list[str]:
    """Split text into sentences for SRT subtitle display.

    Handles sentence boundaries (.!?) while keeping mathematical
    expressions (like "n = 1, 3.") intact.
    """
    import re

    # Split on sentence-ending punctuation followed by whitespace
    # but NOT on periods within numbers (like "n = 1.5")
    raw = re.split(r'(?<=[!?])\s+', text)
    # Further split on periods that end sentences (followed by uppercase or end-of-string)
    refined = []
    for part in raw:
        sub = re.split(r'(?<=\.)\s+(?=[A-Z])', part)
        refined.extend(sub)

    # Filter empty and trim
    result = [s.strip() for s in refined if s.strip()]
    return result if result else [text]


def _ms_to_srt_time(ms: int) -> str:
    """Convert milliseconds to SRT time format HH:MM:SS,mmm."""
    hours = ms // 3600000
    ms %= 3600000
    minutes = ms // 60000
    ms %= 60000
    seconds = ms // 1000
    milliseconds = ms % 1000
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{milliseconds:03d}"


async def _mux_final_video(
    video_path: Path,
    audio_path: str,
    output_path: Path,
    segments: list[ScriptSegment],
    problem_data: dict,
) -> Path:
    """Step 6: Mux video and audio.

    Subtitles are rendered into video frames by Manim's Text() overlay,
    visible in ALL video players. No separate SRT embedding needed.

    Uses apad to pad audio with silence when video is longer than audio,
    so extra video time (PAUSE, FadeOut) is preserved instead of trimmed.
    """
    # Verify durations match
    video_duration = await _get_video_duration(video_path)
    audio_duration = await _get_audio_duration(Path(audio_path))

    duration_diff = abs(video_duration - audio_duration)
    if duration_diff > 1.0:
        logger.warning(
            f"Duration mismatch: video={video_duration:.1f}s, audio={audio_duration:.1f}s, "
            f"diff={duration_diff:.1f}s. apad will fill gap with silence."
        )

    # Video+audio mux
    # If video > audio: pad audio with silence so the full video (including
    #   conclusion PAUSE) plays through without being trimmed by -shortest.
    # If audio >= video: -shortest trims audio to video length (normal case).
    if video_duration > audio_duration:
        pad_dur = video_duration - audio_duration
        cmd = [
            "ffmpeg", "-y",
            "-i", str(video_path),
            "-i", audio_path,
            "-c:v", "copy",
            "-c:a", "aac",
            "-b:a", "192k",
            "-af", f"apad=pad_dur={pad_dur}",
            "-shortest",
            "-movflags", "+faststart",
            str(output_path),
        ]
    else:
        cmd = [
            "ffmpeg", "-y",
            "-i", str(video_path),
            "-i", audio_path,
            "-c:v", "copy",
            "-c:a", "aac",
            "-b:a", "192k",
            "-shortest",
            "-movflags", "+faststart",
            str(output_path),
        ]

    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()

    if process.returncode != 0:
        logger.error(f"FFmpeg mux failed: {stderr.decode()[:200]}")
        raise RuntimeError(f"FFmpeg mux failed: {stderr.decode()[:200]}")

    logger.info(f"Video+audio muxed: {output_path}")
    return output_path


async def _get_video_duration(video_path: Path) -> float:
    """Get video duration using ffprobe."""
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(video_path),
    ]
    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await process.communicate()

    if process.returncode == 0:
        return float(stdout.decode().strip())
    return 0.0


async def _get_audio_duration(audio_path: Path) -> float:
    """Get audio duration using ffprobe."""
    return await _get_video_duration(audio_path)  # ffprobe works for audio too


def _get_llm_config():
    """Get LLM config."""
    config = load_config_with_main("main.yaml")
    provider = config.get("llm", {}).get("provider", "deepseek")
    provider_config = config.get("llm", {}).get("providers", {}).get(provider, {})
    return {
        "api_key": provider_config.get("api_key"),
        "base_url": provider_config.get("base_url"),
        "api_version": provider_config.get("api_version"),
    }


@router.post("/generate", response_model=VideoGenerationResponse)
async def generate_narrated_video(
    request: VideoGenerationRequest,
    background_tasks: BackgroundTasks,
) -> VideoGenerationResponse:
    """Generate a narrated video explanation for a MathNet problem.

    Data flow:
    1. Generate script segments from problem steps
    2. Synthesize TTS audio with sentence boundaries
    3. Map audio timings to each segment
    4. Generate Manim code with exact segment durations
    5. Render video
    6. Mux audio and video
    """
    start_time = time.perf_counter()

    if not check_ffmpeg_available():
        raise HTTPException(status_code=503, detail="FFmpeg not available")

    # Check cache
    path_service = get_path_service()
    output_dir = path_service.get_public_outputs_root()
    final_output = output_dir / f"mathnet_{request.problem_id}.mp4"

    if final_output.exists() and not request.force_regenerate:
        duration = await _get_video_duration(final_output)
        logger.info(f"Returning cached video for {request.problem_id}")
        return VideoGenerationResponse(
            status="success",
            video_url=f"/api/outputs/{final_output.name}",
            duration_seconds=duration,
            generation_time_seconds=time.perf_counter() - start_time,
        )

    # Force regenerate: delete old video
    if final_output.exists() and request.force_regenerate:
        logger.info(f"Force regenerate: deleting old video for {request.problem_id}")
        final_output.unlink(missing_ok=True)

    # Fetch problem data
    conn = _get_db_connection()
    try:
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM problems WHERE id = ?", (request.problem_id,))
        problem_row = cursor.fetchone()
        if not problem_row:
            raise HTTPException(status_code=404, detail=f"Problem '{request.problem_id}' not found")

        cursor.execute(
            "SELECT * FROM architectures WHERE problem_id = ?",
            (request.problem_id,),
        )
        arch_row = cursor.fetchone()
        if not arch_row:
            raise HTTPException(
                status_code=400,
                detail=f"Problem '{request.problem_id}' has no AI solution yet"
            )

        cursor.execute(
            "SELECT * FROM steps WHERE architecture_id = ? ORDER BY step_index",
            (arch_row[0],),
        )
        step_rows = cursor.fetchall()
    finally:
        conn.close()

    problem_data = {
        "id": problem_row[0],
        "problem_markdown": problem_row[1],
        "problem_zh": problem_row[3],
    }

    steps_data = [
        {
            "step_index": row[3],
            "step_title_zh": row[5],
            "step_title_en": row[4],
            "step_text_zh": row[7],
            "step_text_en": row[6],
            "explanation_zh": row[9],
            "explanation_en": row[8],
            "step_goal_zh": row[13] if len(row) > 13 else "",
        }
        for row in step_rows
    ]

    # Add steps to problem_data so code generator can access them
    problem_data["steps"] = steps_data

    try:
        # Step 1: Generate script segments (using new lecture script layer)
        segments = await _generate_script_with_lecture_layer(
            problem_data, steps_data, optimize=request.optimize_script
        )
        logger.info(f"Generated {len(segments)} script segments with lecture layer")

        # Step 2: TTS synthesis
        audio_path, boundaries, audio_duration = await _synthesize_tts(
            segments, request.voice, use_english=request.use_english_voice
        )
        logger.info(f"TTS generated: {audio_duration:.1f}s audio, {len(boundaries)} boundaries")

        # Step 3: Map durations to segments
        total_duration = _map_durations_to_segments(segments, boundaries)
        logger.info(f"Mapped durations: {total_duration:.1f}s total")
        for seg in segments:
            logger.info(f"  {seg.title}: {seg.duration_ms/1000:.1f}s")

        # Step 4: Generate timed Manim code
        manim_code = await _generate_timed_manim_code(segments, problem_data)
        logger.info(f"Generated Manim code ({len(manim_code)} chars)")

        # Apply Chinese-safe fix (pdflatex cannot handle CJK Unicode in MathTex)
        try:
            manim_code = _fix_chinese_mathtex(manim_code)
            logger.warning("[ChineseFix] _fix_chinese_mathtex completed")
        except Exception as e:
            logger.warning(f"[ChineseFix] _fix_chinese_mathtex crashed: {e}")

        # Step 5: Render video
        video_path = await _render_manim_video(manim_code, output_dir, request.problem_id)
        logger.info(f"Video rendered: {video_path}")

        # Step 6: Mux final video
        final_path = await _mux_final_video(video_path, audio_path, final_output, segments, problem_data)
        logger.info(f"Final video: {final_path}")

    except Exception as e:
        logger.exception("Video generation failed")
        raise HTTPException(status_code=500, detail=f"Generation failed: {str(e)}")

    generation_time = time.perf_counter() - start_time
    final_duration = await _get_video_duration(final_path)

    return VideoGenerationResponse(
        status="success",
        video_url=f"/api/outputs/{final_output.name}",
        duration_seconds=final_duration,
        generation_time_seconds=generation_time,
    )


__all__ = ["router"]
