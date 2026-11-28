from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import import_videos as iv  # noqa: E402


def _timeline(
    lesson: Path, number: int, video: str, lines: list[dict], absolute: bool = True
) -> None:
    (lesson / "timeline").mkdir(parents=True, exist_ok=True)
    data = {
        "episode": number,
        "title": f"标题{number}",
        "video": video,
        "absolute_times": absolute,
        "lines": lines,
    }
    (lesson / "timeline" / f"ep{number}.json").write_text(
        json.dumps(data, ensure_ascii=False), encoding="utf-8"
    )


LINES = [
    {"speaker": "爸爸", "text": "先画图。", "start": 1.0, "end": 2.5},
    {"speaker": "女儿", "text": "  ", "start": 3.0, "end": 3.5},
    {"speaker": "女儿", "text": "我知道了。", "start": 4.0, "end": 6.0},
]


@pytest.fixture
def dirs(tmp_path: Path) -> tuple[Path, Path]:
    lesson, videos = tmp_path / "lesson", tmp_path / "videos"
    videos.mkdir()
    for n in (2, 1):
        (videos / f"v{n}.mp4").write_bytes(b"x")
        _timeline(lesson, n, f"v{n}.mp4", LINES)
    return lesson, videos


def test_discover_sorts_episodes_and_keeps_speakers(dirs: tuple[Path, Path]) -> None:
    episodes = iv.discover(*dirs)
    assert [e.number for e in episodes] == [1, 2]
    assert [line.text for line in episodes[0].lines] == ["爸爸：先画图。", "女儿：我知道了。"]
    assert episodes[0].display_name == "第1集-标题1.mp4"


def test_missing_video_is_reported(dirs: tuple[Path, Path]) -> None:
    lesson, videos = dirs
    (videos / "v2.mp4").unlink()
    with pytest.raises(FileNotFoundError, match="v2.mp4"):
        iv.discover(lesson, videos)


def test_relative_timeline_is_rejected(tmp_path: Path) -> None:
    _timeline(tmp_path, 1, "v.mp4", LINES, absolute=False)
    with pytest.raises(ValueError, match="绝对时间"):
        iv.load_episode(tmp_path / "timeline" / "ep1.json", tmp_path)


def test_unsorted_lines_are_rejected(tmp_path: Path) -> None:
    (tmp_path / "v.mp4").write_bytes(b"x")
    _timeline(tmp_path, 1, "v.mp4", [LINES[2], LINES[0]])
    with pytest.raises(ValueError, match="递增"):
        iv.load_episode(tmp_path / "timeline" / "ep1.json", tmp_path)


def test_duplicate_episode_numbers_are_rejected(dirs: tuple[Path, Path]) -> None:
    lesson, videos = dirs
    _timeline(lesson, 1, "v2.mp4", LINES)  # writes ep1.json again: fine
    (lesson / "timeline" / "copy.json").write_text(
        (lesson / "timeline" / "ep2.json").read_text(encoding="utf-8"), encoding="utf-8"
    )
    with pytest.raises(ValueError, match="重复"):
        iv.discover(lesson, videos)


def test_duration_check_catches_wrong_render(dirs: tuple[Path, Path]) -> None:
    episode = iv.discover(*dirs)[0]
    iv.check_duration(episode, 6.5)
    iv.check_duration(episode, None)  # no ffprobe: skip
    with pytest.raises(ValueError, match="不是同一版"):
        iv.check_duration(episode, 3.0)


@dataclass
class _Tab:
    material: object


@dataclass
class _Workspace:
    workspace_id: str
    title: str
    tabs: list = field(default_factory=list)


@dataclass(frozen=True)
class _Material:
    material_id: str


class _FakeCatalog:
    def __init__(self) -> None:
        self.workspaces: dict[str, _Workspace] = {}

    def list_workspaces(self) -> list[_Workspace]:
        return list(self.workspaces.values())

    def create_workspace(self, title: str, ids: list[str]) -> _Workspace:
        ws = _Workspace(f"rw_{len(self.workspaces)}", title, [_Tab(_Material(i)) for i in ids])
        self.workspaces[ws.workspace_id] = ws
        return ws

    def get_workspace(self, workspace_id: str) -> _Workspace:
        return self.workspaces[workspace_id]

    def add_material(self, workspace_id: str, material_id: str) -> None:
        ws = self.workspaces[workspace_id]
        if all(t.material.material_id != material_id for t in ws.tabs):
            ws.tabs.append(_Tab(_Material(material_id)))

    def reorder_materials(self, workspace_id: str, ids: list[str]) -> None:
        ws = self.workspaces[workspace_id]
        ws.tabs = [_Tab(_Material(i)) for i in ids]


def test_folder_is_reused_and_episodes_stay_in_order() -> None:
    catalog = _FakeCatalog()
    first = iv.put_in_folder(catalog, "四年级·Q11", ["e4"])
    catalog.add_material(first, "extra")
    again = iv.put_in_folder(catalog, "四年级·Q11", ["e1", "e2", "e4"])
    assert again == first and len(catalog.workspaces) == 1
    assert [t.material.material_id for t in catalog.get_workspace(first).tabs] == [
        "e1",
        "e2",
        "e4",
        "extra",
    ]
