"""Build tutoring notes ("教学版") for one douYinGZ lesson.

The douYinGZ production sheets (讲解总表) mix teaching content with render,
audio and coordinate details. For AI tutoring we only want what the child
heard and saw, so this script combines:

* the voice ``timing.json`` of each episode (dialogue + per-clip times),
* the shot table rows of the 讲解总表 (what appeared on screen),
* the teaching-method and math-check sections of the 讲解总表,

and writes one Markdown note per episode (for the knowledge base) plus a
``timeline/*.json`` per episode with absolute video times for later
video-pause features. Each run fully regenerates the lesson's output folder.

Usage (from any directory)::

    python -X utf8 coco/tools/build_lesson_notes.py \
        --lesson-dir "D:/Peter2025/myCursor/douYinGZ/剧情主题/四年级-Q11平均数II"
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import difflib
import json
import math
from pathlib import Path
import re
import sys
from typing import Callable

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUT_ROOT = REPO_ROOT / "data" / "coco" / "lessons"

FPS = 30
FADE_FRAMES = 10  # cross-fade overlap between clips (remotion l10/anim FADE)
PROMO_COVER_SECONDS = 2.5  # series/promo PROMO_COVER
PROMO_END_SECONDS = 4.0  # series/promo PROMO_END
FADE_COVER_SECONDS = 1.5  # l910/kit COVER_FRAMES

KEEP_HEADING_WORDS = ("讲法", "题目", "复核", "教学目标", "七集安排", "统一画法", "怎么讲")
SPEAKER_NAMES = {"dad": "爸爸", "daughter": "女儿", "daughter_v2": "女儿", "mom": "妈妈"}
MATCH_THRESHOLD = 0.6
MIN_SUBSTRING_LEN = 4  # shorter lines ("对！") must match a cell exactly

_PUNCT_RE = re.compile(r"[\s，。！？、；：,.!?;:“”\"'「」『』（）()《》…—\-·*]+")
_LINK_RE = re.compile(r"!?\[([^\]]*)\]\([^)]*\)")
_ANIM_CODE_RE = re.compile(r"[ \t]*(?<![A-Za-z])(?:R|MP)#\d+(?:/(?:R|MP)#\d+)*")
# Pause cues sit anywhere in a line ("先暂停，画三列"), but "不用暂停" is not one.
_PAUSE_RE = re.compile(r"(?<!不用)(?<!不要)(?<!别)(?<!不)暂停")


@dataclass(frozen=True)
class Episode:
    number: int
    title: str
    sheet: Path
    timing: Path
    tsx: Path | None
    video: Path | None


@dataclass(frozen=True)
class Line:
    clip: str
    line: int
    speaker: str
    text: str
    start: float
    end: float
    visual: str


# ---------------------------------------------------------------- text utils


def read_text(path: Path) -> str:
    """Read UTF-8 text, tolerating a BOM written by Windows editors."""
    return path.read_text(encoding="utf-8-sig")


def normalize(text: str) -> str:
    """Strip punctuation, spaces and a leading ``爸爸：``-style speaker tag."""
    text = re.sub(r"^\s*(爸爸|女儿|妈妈)\s*[：:]", "", text)
    return _PUNCT_RE.sub("", text)


def clean_markdown(text: str) -> str:
    """Drop links to production files and animation codes like ``R#61``."""
    return _ANIM_CODE_RE.sub("", _LINK_RE.sub(r"\1", text)).strip()


def fmt_time(seconds: float) -> str:
    total = int(seconds)
    return f"{total // 60}:{total % 60:02d}"


def js_round(value: float) -> int:
    """JavaScript ``Math.round`` (halves round up), as Remotion uses."""
    return math.floor(value + 0.5)


def version_of(label: str) -> int:
    m = re.search(r"-v(\d+)$", label)
    return int(m.group(1)) if m else 0


def latest_version(
    paths: list[Path], label: Callable[[Path], str] = lambda p: p.stem
) -> Path | None:
    """Pick the path whose ``label`` ends with the highest ``-vN``."""
    return max(paths, key=lambda p: version_of(label(p))) if paths else None


def clip_sort_key(clip: str) -> tuple[int, str]:
    digits = re.sub(r"\D", "", clip)
    return (int(digits) if digits else 0, clip)


# ---------------------------------------------------------- video timeline


def _cover_frames(promo: bool) -> int:
    return js_round((PROMO_COVER_SECONDS if promo else FADE_COVER_SECONDS) * FPS)


def clip_offsets(durations: list[float], promo: bool) -> list[float]:
    """Absolute start (seconds) of each clip in the rendered episode.

    Mirrors remotion ``PromoEpisode`` / ``FadeEpisode``: the first clip starts
    ``FADE`` frames before the cover ends and every clip overlaps the next by
    ``FADE`` frames.
    """
    start = _cover_frames(promo) - FADE_FRAMES
    offsets = []
    for duration in durations:
        offsets.append(start / FPS)
        start += js_round(duration * FPS) - FADE_FRAMES
    return offsets


def episode_frames(durations: list[float], promo: bool) -> int:
    body = sum(js_round(d * FPS) for d in durations) - FADE_FRAMES * len(durations)
    end = js_round(PROMO_END_SECONDS * FPS) if promo else 0
    return _cover_frames(promo) + body + end


def is_promo(tsx: Path | None) -> bool | None:
    """Detect the episode wrapper actually rendered (``<PromoEpisode`` JSX)."""
    if tsx is None or not tsx.exists():
        return None
    source = read_text(tsx)
    if re.search(r"<\s*PromoEpisode\b", source):
        return True
    if re.search(r"<\s*FadeEpisode\b", source):
        return False
    return None


# ------------------------------------------------------- shot table parsing


def table_rows(markdown: str) -> list[list[str]]:
    rows = []
    for raw in markdown.splitlines():
        stripped = raw.strip()
        if not stripped.startswith("|") or re.match(r"^\|[\s\-|:]+\|?$", stripped):
            continue
        cells = re.split(r"(?<!\\)\|", stripped[1:-1] if stripped.endswith("|") else stripped[1:])
        rows.append([c.strip().replace("\\|", "|") for c in cells])
    return rows


def _match_score(target: str, cell: str) -> float:
    if not cell:
        return 0.0
    if target == cell:
        return 1.0
    if len(target) >= MIN_SUBSTRING_LEN and (target in cell or cell in target):
        return 0.99
    return difflib.SequenceMatcher(None, target, cell).ratio()


def _best_visual(target: str, rows: list[list[str]]) -> tuple[float, str]:
    best_score, best_visual = 0.0, ""
    for row in rows:
        if len(row) < 3:
            continue
        score = max(_match_score(target, normalize(cell)) for cell in row[:-1])
        if score > best_score:
            best_score, best_visual = score, clean_markdown(row[-1])
    return best_score, best_visual


def find_visual(text: str, rows: list[list[str]], clip: str = "") -> str:
    """Return the 画面 cell of the shot-table row holding ``text``.

    Rows of the same clip (first cell ``C02`` / ``C02-03``) are preferred so
    lines repeated across clips ("对！") get their own clip's visual.
    """
    target = normalize(text)
    if not target:
        return ""
    if clip:
        same_clip = [r for r in rows if r and re.match(rf"^{re.escape(clip)}(\b|-)", r[0])]
        score, visual = _best_visual(target, same_clip)
        if score >= MATCH_THRESHOLD:
            return visual
    score, visual = _best_visual(target, rows)
    return visual if score >= MATCH_THRESHOLD else ""


def _drop_checklists(section: str) -> str:
    """Remove production self-check lines such as ``- 清单1–5：…``."""
    return "\n".join(ln for ln in section.splitlines() if not re.search(r"清单\s*1", ln))


def kept_sections(markdown: str, skip_words: tuple[str, ...] = ("进度",)) -> list[str]:
    """Return ``## `` sections whose heading names teaching content."""
    sections, current, keep = [], [], False
    for raw in markdown.splitlines():
        if raw.startswith("## "):
            if keep and current:
                sections.append("\n".join(current).strip())
            heading = raw[3:]
            keep = any(w in heading for w in KEEP_HEADING_WORDS) and not any(
                w in heading for w in skip_words
            )
            current = [raw]
        elif keep:
            current.append(raw)
    if keep and current:
        sections.append("\n".join(current).strip())
    return [clean_markdown(_drop_checklists(s)) + "\n" for s in sections]


# ---------------------------------------------------------------- discovery


def lesson_identity(lesson_dir: Path) -> tuple[str, str, str, int]:
    """``四年级-Q11平均数II`` -> (grade, code+name, name, lecture number)."""
    m = re.match(r"(.+?)-(Q(\d+))(.+)$", lesson_dir.name)
    if not m:
        raise ValueError(f"课程目录名应形如「四年级-Q11平均数II」：{lesson_dir.name}")
    grade, code, lecture, name = m.group(1), m.group(2), int(m.group(3)), m.group(4)
    return grade, f"{code}{name}", name, lecture


def find_timing(douyin_root: Path, name: str, number: int) -> Path:
    dirs = [
        d
        for d in (douyin_root / "配音").glob(f"{name}-第{number}集-*")
        if (d / "timing.json").is_file()
    ]
    latest = latest_version(dirs, label=lambda d: d.name)
    if latest is None:
        raise FileNotFoundError(f"第{number}集缺少配音 timing.json（配音/{name}-第{number}集-*/）")
    return latest / "timing.json"


def discover_episodes(
    lesson_dir: Path, douyin_root: Path, lecture: int, name: str
) -> list[Episode]:
    by_number: dict[int, list[Path]] = {}
    for sheet in lesson_dir.glob("讲解总表-第*集-*.md"):
        m = re.match(r"讲解总表-第(\d+)集-", sheet.name)
        if m:
            by_number.setdefault(int(m.group(1)), []).append(sheet)
    episodes = []
    for number in sorted(by_number):
        sheet = latest_version(by_number[number])
        title = re.sub(r"^讲解总表-第\d+集-|-v\d+$", "", sheet.stem)
        videos = list(
            (douyin_root / "remotion" / "out" / lesson_dir.name).glob(
                f"第{lecture}讲-*-第{number}集-*.mp4"
            )
        )
        tsx = douyin_root / "remotion" / "src" / f"l{lecture}" / f"Ep{number}.tsx"
        episodes.append(
            Episode(
                number,
                title,
                sheet,
                find_timing(douyin_root, name, number),
                tsx if tsx.exists() else None,
                latest_version(videos),
            )
        )
    return episodes


# ------------------------------------------------------------------ building


def load_clips(timing_path: Path) -> list[tuple[str, dict]]:
    timing = json.loads(read_text(timing_path))
    clips = [
        (k, v)
        for k, v in timing.items()
        if isinstance(v, dict) and "lines" in v and "duration" in v
    ]
    if not clips:
        raise ValueError(f"timing.json 里没有段落（C01…）：{timing_path}")
    return sorted(clips, key=lambda kv: clip_sort_key(kv[0]))


def build_lines(episode: Episode, promo: bool | None) -> tuple[list[Line], list[float]]:
    clips = load_clips(episode.timing)
    durations = [float(c["duration"]) for _, c in clips]
    offsets = clip_offsets(durations, promo) if promo is not None else [0.0] * len(clips)
    rows = table_rows(read_text(episode.sheet))
    lines = []
    for (clip, data), offset in zip(clips, offsets):
        for item in data["lines"]:
            speaker = item.get("name") or SPEAKER_NAMES.get(item["speaker"], item["speaker"])
            lines.append(
                Line(
                    clip,
                    int(item["line"]),
                    speaker,
                    item["text"],
                    round(offset + float(item["start"]), 2),
                    round(offset + float(item["end"]), 2),
                    find_visual(item["text"], rows, clip),
                )
            )
    return lines, durations


def render_dialogue(code_name: str, number: int, lines: list[Line], absolute: bool) -> list[str]:
    out = ["## 逐段对白与画面", ""]
    if not absolute:
        out += ["> 注意：没有找到动画工程，时间为段内相对时间。", ""]
    clips = sorted({ln.clip for ln in lines}, key=clip_sort_key)
    for clip in clips:
        group = [ln for ln in lines if ln.clip == clip]
        out += [
            f"### {code_name} 第{number}集 · {clip}（{fmt_time(group[0].start)}–{fmt_time(group[-1].end)}）",
            "",
        ]
        for ln in group:
            pause = "⏸ 停下来想 · " if _PAUSE_RE.search(ln.text) else ""
            out.append(f"- **{fmt_time(ln.start)}** {pause}{ln.speaker}：{ln.text}")
            if ln.visual:
                out.append(f"  - 画面：{ln.visual}")
        out.append("")
    return out


def render_episode(
    grade: str,
    code_name: str,
    episode: Episode,
    lines: list[Line],
    durations: list[float],
    promo: bool | None,
) -> str:
    sections = kept_sections(read_text(episode.sheet))
    video = episode.video.name if episode.video else "（未找到成片）"
    length = fmt_time(episode_frames(durations, promo) / FPS) if promo is not None else "未知"
    head = [
        f"# {code_name} · 第{episode.number}集 · {episode.title}（教学版）",
        "",
        f"> {grade}数学思维 · {code_name} · 第{episode.number}集。成片：{video}，时长约 {length}。",
        "> 由 coco/tools/build_lesson_notes.py 从讲解总表和配音 timing.json 生成，供 AI 辅导检索。",
        "> 讲解时请沿用视频里的画法和说法：先画平均线、柱底写人数、每份差乘份数。",
        "",
    ]
    math_checks = [s for s in sections if "复核" in s.splitlines()[0]]
    method = [s for s in sections if s not in math_checks]
    body = (
        method
        + [""]
        + render_dialogue(code_name, episode.number, lines, promo is not None)
        + math_checks
    )
    return "\n".join(head + body).rstrip() + "\n"


def render_summary(grade: str, code_name: str, sheet: Path) -> str:
    sections = kept_sections(read_text(sheet))
    head = [
        f"# {code_name} · 全讲总览（教学版）",
        "",
        f"> {grade}数学思维 · {code_name} 各集安排与统一讲法。",
        "",
    ]
    return "\n".join(head + sections).rstrip() + "\n"


@dataclass(frozen=True)
class Output:
    relpath: str
    content: str
    report: str


def build_episode(grade: str, code_name: str, episode: Episode) -> list[Output]:
    promo = is_promo(episode.tsx)
    lines, durations = build_lines(episode, promo)
    stem = f"{code_name}-第{episode.number}集-{episode.title}"
    timeline = {
        "lesson": code_name,
        "episode": episode.number,
        "title": episode.title,
        "video": episode.video.name if episode.video else None,
        "absolute_times": promo is not None,
        "lines": [asdict(ln) for ln in lines],
    }
    matched = sum(1 for ln in lines if ln.visual) * 100 // max(len(lines), 1)
    layout = {True: "片头2.5秒", False: "片头1.5秒", None: "无动画工程·相对时间"}[promo]
    report = f"第{episode.number}集  画面匹配 {matched:3d}%  {layout}  -> {stem}.md"
    return [
        Output(
            f"notes/{stem}.md",
            render_episode(grade, code_name, episode, lines, durations, promo),
            report,
        ),
        Output(f"timeline/{stem}.json", json.dumps(timeline, ensure_ascii=False, indent=1), ""),
    ]


def build_lesson(lesson_dir: Path, douyin_root: Path) -> tuple[str, str, list[Output]]:
    """Build every output in memory so a bad file never leaves half a lesson."""
    grade, code_name, name, lecture = lesson_identity(lesson_dir)
    episodes = discover_episodes(lesson_dir, douyin_root, lecture, name)
    if not episodes:
        raise FileNotFoundError(f"课程目录里没有「讲解总表-第N集-*.md」：{lesson_dir}")
    outputs = [o for ep in episodes for o in build_episode(grade, code_name, ep)]
    summary = latest_version(list(lesson_dir.glob("讲解总表-*复习合集*.md")))
    if summary:
        name_md = f"{code_name}-全讲总览.md"
        outputs.append(
            Output(
                f"notes/{name_md}",
                render_summary(grade, code_name, summary),
                f"全讲总览          -> {name_md}",
            )
        )
    return grade, code_name, outputs


def write_outputs(out_dir: Path, outputs: list[Output]) -> None:
    """Replace the lesson's generated files, removing stale ones from renames."""
    for sub, pattern in (("notes", "*.md"), ("timeline", "*.json")):
        folder = out_dir / sub
        folder.mkdir(parents=True, exist_ok=True)
        for old in folder.glob(pattern):
            old.unlink()
    for out in outputs:
        (out_dir / out.relpath).write_text(out.content, encoding="utf-8", newline="\n")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="生成某一讲的 AI 辅导教学版")
    parser.add_argument("--lesson-dir", required=True, type=Path, help="剧情主题下的课程目录")
    parser.add_argument(
        "--douyin-root", type=Path, default=None, help="douYinGZ 根目录（默认由课程目录推出）"
    )
    parser.add_argument("--out-root", type=Path, default=DEFAULT_OUT_ROOT, help="输出根目录")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    lesson_dir = args.lesson_dir.resolve()
    if not lesson_dir.is_dir():
        print(f"找不到课程目录：{lesson_dir}", file=sys.stderr)
        return 2
    douyin_root = (args.douyin_root or lesson_dir.parent.parent).resolve()
    try:
        grade, code_name, outputs = build_lesson(lesson_dir, douyin_root)
    except (ValueError, FileNotFoundError, KeyError) as exc:
        print(f"生成失败，未写入任何文件：{exc}", file=sys.stderr)
        return 2
    out_dir = args.out_root / grade / code_name
    write_outputs(out_dir, outputs)
    for out in outputs:
        if out.report:
            print(out.report)
    print(f"输出目录：{(out_dir / 'notes').resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
