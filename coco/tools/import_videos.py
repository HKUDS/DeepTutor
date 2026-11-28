"""Import a lesson's episode MP4s into DeepTutor's reading library.

DeepTutor normally transcribes an uploaded video with a speech-to-text
service. Our episodes already have the exact narration with timings (the
``timeline/*.json`` written by build_lesson_notes.py), so this script feeds
that narration in place of speech recognition: no STT service, no cost, and
every sentence lands on its real timestamp.

The videos go into one library folder per lesson (e.g. "四年级·Q11平均数II"),
in episode order. Re-running is safe: the same file keeps the same material
id, and its transcript is rewritten.

Usage (from the DeepTutor-CoCo root, deeptutor conda env)::

    python -X utf8 coco/tools/import_videos.py ^
        --lesson-dir data/coco/lessons/四年级/Q11平均数II ^
        --video-dir "D:/Peter2025/myCursor/douYinGZ/remotion/out/四年级-Q11平均数II"
"""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass
import json
import os
from pathlib import Path
import shutil
import subprocess  # nosec B404 - fixed ffprobe argv below
import sys
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
# Timeline may end a little after the last word; a larger gap means the
# timeline belongs to another render of the episode.
DURATION_TOLERANCE_SECONDS = 2.0


@dataclass(frozen=True)
class Line:
    start: float
    end: float
    text: str


@dataclass(frozen=True)
class Episode:
    number: int
    title: str
    video: Path
    lines: tuple[Line, ...]

    @property
    def display_name(self) -> str:
        return f"第{self.number}集-{self.title}.mp4"


def load_episode(timeline: Path, video_dir: Path) -> Episode:
    data = json.loads(timeline.read_text(encoding="utf-8-sig"))
    if not data.get("absolute_times"):
        raise ValueError(f"{timeline.name}: 时间不是整集的绝对时间，不能直接导入")
    lines = tuple(
        Line(float(row["start"]), float(row["end"]), f"{row['speaker']}：{row['text']}".strip())
        for row in data["lines"]
        if str(row.get("text", "")).strip()
    )
    if not lines:
        raise ValueError(f"{timeline.name}: 没有台词")
    if any(b.start < a.start for a, b in zip(lines, lines[1:])):
        raise ValueError(f"{timeline.name}: 台词时间不是递增的")
    video = video_dir / str(data["video"])
    if not video.is_file():
        raise FileNotFoundError(f"找不到视频 {video}")
    return Episode(int(data["episode"]), str(data["title"]), video, lines)


def discover(lesson_dir: Path, video_dir: Path) -> list[Episode]:
    timelines = sorted((lesson_dir / "timeline").glob("*.json"))
    if not timelines:
        raise FileNotFoundError(
            f"{lesson_dir / 'timeline'} 里没有时间轴文件，先运行 build_lesson_notes.py"
        )
    episodes = sorted((load_episode(t, video_dir) for t in timelines), key=lambda e: e.number)
    numbers = [e.number for e in episodes]
    if len(set(numbers)) != len(numbers):
        raise ValueError(f"集数重复：{numbers}")
    return episodes


def probe_duration(video: Path) -> float | None:
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return None
    result = subprocess.run(  # nosec B603 - fixed argv, no shell
        [ffprobe, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(video)],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    try:
        return float(result.stdout.strip())
    except ValueError:
        return None


def check_duration(episode: Episode, duration: float | None) -> None:
    if duration is None:
        return
    last = episode.lines[-1].end
    if last > duration + DURATION_TOLERANCE_SECONDS:
        raise ValueError(
            f"第{episode.number}集：台词到 {last:.1f} 秒，但视频只有 {duration:.1f} 秒——"
            f"时间轴和视频 {episode.video.name} 可能不是同一版"
        )


def make_cues(episode: Episode) -> list[Any]:
    from deeptutor.services.voice.base import TranscriptCue

    return [TranscriptCue(line.start, line.end, line.text) for line in episode.lines]


async def import_episode(episode: Episode, catalog: Any, store: Any) -> str:
    """Store one video and give it the timeline narration; returns material id."""
    from deeptutor.reading.catalog_models import IngestionStatus
    from deeptutor.reading.ingestion import ReadingIngestionService

    cues = make_cues(episode)
    span = episode.lines[-1].end + 1.0

    async def one_chunk(_path: Path) -> list[tuple[float, float, bytes]]:
        return [(0.0, span, b"")]  # times are already absolute; no audio needed

    async def timeline_transcriber(_audio: bytes, **_kwargs: Any) -> list[Any]:
        return cues

    service = ReadingIngestionService(
        store, catalog, media_chunker=one_chunk, transcriber=timeline_transcriber
    )
    record = await service.queue_media(episode.video, filename=episode.display_name)
    done = await service.process_media(record.material_id)
    if done.status is not IngestionStatus.READY:
        raise RuntimeError(f"第{episode.number}集导入失败：{done.error_detail or done.status}")
    return record.material_id


def put_in_folder(catalog: Any, title: str, material_ids: list[str]) -> str:
    """Create or reuse the lesson folder and keep the episodes in order."""
    existing = next((w for w in catalog.list_workspaces() if w.title == title), None)
    if existing is None:
        return catalog.create_workspace(title, material_ids).workspace_id
    for material_id in material_ids:
        catalog.add_material(existing.workspace_id, material_id)
    current = [t.material.material_id for t in catalog.get_workspace(existing.workspace_id).tabs]
    ordered = material_ids + [m for m in current if m not in material_ids]
    catalog.reorder_materials(existing.workspace_id, ordered)
    return existing.workspace_id


async def run(lesson_dir: Path, video_dir: Path, folder: str, only: set[int]) -> int:
    os.environ.setdefault("DEEPTUTOR_HOME", str(REPO_ROOT))
    from deeptutor.reading.catalog_store import ReadingCatalogStore
    from deeptutor.reading.store import ReadingStore

    episodes = [e for e in discover(lesson_dir, video_dir) if not only or e.number in only]
    if not shutil.which("ffprobe"):
        print("提示：没找到 ffprobe，视频不会有时长和封面（可把 ffmpeg 目录加进 PATH）")
    for episode in episodes:
        check_duration(episode, probe_duration(episode.video))

    catalog = ReadingCatalogStore()
    store = ReadingStore(catalog.root)
    ids = []
    for episode in episodes:
        material_id = await import_episode(episode, catalog, store)
        ids.append(material_id)
        print(f"✓ 第{episode.number}集 {episode.title}：{len(episode.lines)} 句台词")
    workspace_id = put_in_folder(catalog, folder, ids)
    print(f"已放进文件夹「{folder}」（{workspace_id}），共 {len(ids)} 集")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--lesson-dir", type=Path, required=True, help="教学版目录（含 timeline/）")
    parser.add_argument("--video-dir", type=Path, required=True, help="渲染好的 MP4 所在目录")
    parser.add_argument("--folder", default="", help="资料库文件夹名，默认「年级·讲次」")
    parser.add_argument("--only", type=int, nargs="*", default=[], help="只导入这几集")
    args = parser.parse_args()
    lesson_dir = args.lesson_dir.resolve()
    folder = args.folder or f"{lesson_dir.parent.name}·{lesson_dir.name}"
    try:
        return asyncio.run(run(lesson_dir, args.video_dir.resolve(), folder, set(args.only)))
    except (ValueError, FileNotFoundError, RuntimeError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
