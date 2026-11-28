from __future__ import annotations

import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import build_lesson_notes as bln  # noqa: E402

SHEET = (
    "# 第2集\n## 本集讲法\n先写人数。\n## 画图规格\n坐标\n"
    "| 段 | 人物 | 对白 | 同步画面 |\n|---|---|---|---|\n"
    "| C01 | 爸爸 | 暂停，先画图。 | 画平均线 |\n"
    "| C01 | 女儿 | 对！ | 第一段的对 |\n"
    "| C02 | 女儿 | 对！ | 第二段的对 |\n"
    "## 算式复核\n12×57＝684\n- 清单1–5：略\n"
)


def _timing(clips: dict[str, list[str]]) -> dict:
    return {
        clip: {
            "duration": 5,
            "lines": [
                {
                    "line": i + 1,
                    "speaker": "dad",
                    "name": "爸爸",
                    "text": t,
                    "start": 0.3 + i,
                    "end": 0.9 + i,
                }
                for i, t in enumerate(texts)
            ],
        }
        for clip, texts in clips.items()
    }


def make_lesson(
    tmp_path: Path,
    *,
    tsx: str | None = "<PromoEpisode ep={ep}/>",
    timing_versions: dict[int, dict] | None = None,
    bom: bool = False,
) -> Path:
    root = tmp_path / "douYinGZ"
    lesson = root / "剧情主题" / "四年级-Q11平均数II"
    lesson.mkdir(parents=True)
    encoding = "utf-8-sig" if bom else "utf-8"
    (lesson / "讲解总表-第2集-移多补少-v1.md").write_text(SHEET, encoding=encoding)
    versions = timing_versions or {1: _timing({"C01": ["暂停，先画图。", "对！"], "C02": ["对！"]})}
    for version, timing in versions.items():
        voice = root / "配音" / f"平均数II-第2集-移多补少-v{version}"
        voice.mkdir(parents=True)
        (voice / "timing.json").write_text(
            json.dumps(timing, ensure_ascii=False), encoding=encoding
        )
    if tsx is not None:
        src = root / "remotion" / "src" / "l11"
        src.mkdir(parents=True)
        (src / "Ep2.tsx").write_text(tsx, encoding="utf-8")
    return lesson


def run(lesson: Path, out_root: Path) -> int:
    return bln.main(["--lesson-dir", str(lesson), "--out-root", str(out_root)])


def note_text(out_root: Path) -> str:
    return (
        out_root / "四年级" / "Q11平均数II" / "notes" / "Q11平均数II-第2集-移多补少.md"
    ).read_text(encoding="utf-8")


# ------------------------------------------------------------------- units


def test_normalize_strips_punctuation_and_speaker_tag() -> None:
    assert bln.normalize("爸爸：暂停，先画图！") == "暂停先画图"


def test_clean_markdown_drops_links_and_anim_codes() -> None:
    assert bln.clean_markdown("[任务单](a.md) 标题遮罩 R#9/MP#005") == "任务单 标题遮罩"
    assert bln.clean_markdown("![图](x.png) 保留MR#5") == "图 保留MR#5"


def test_fmt_time_and_js_round() -> None:
    assert bln.fmt_time(275.5) == "4:35"
    assert bln.fmt_time(9.2) == "0:09"
    assert bln.js_round(2.5) == 3 and bln.js_round(3.5) == 4  # not banker's rounding


def test_latest_version_uses_given_label() -> None:
    dirs = [Path("a-v1"), Path("a-v10"), Path("a-v2")]
    assert bln.latest_version(dirs, label=lambda p: p.name) == Path("a-v10")
    assert bln.latest_version([]) is None


def test_clip_sort_key_is_natural() -> None:
    assert sorted(["C10", "C2", "C1"], key=bln.clip_sort_key) == ["C1", "C2", "C10"]


def test_episode_frames_matches_rendered_episode_two() -> None:
    # 讲解总表 第2集 records 8265 frames for clips totalling 271 s (PromoEpisode).
    assert bln.episode_frames([13, 48, 38, 54, 71, 47], promo=True) == 8265


def test_clip_offsets_account_for_cover_and_fades() -> None:
    offsets = bln.clip_offsets([13, 48], promo=True)
    assert offsets[0] == pytest.approx((75 - 10) / 30)
    assert offsets[1] == pytest.approx((65 + 390 - 10) / 30)
    assert bln.clip_offsets([10], promo=False)[0] == pytest.approx((45 - 10) / 30)


def test_is_promo_detects_jsx_usage_only(tmp_path: Path) -> None:
    tsx = tmp_path / "Ep.tsx"
    tsx.write_text(
        "import {PromoEpisode} from 'x';\nexport const A=()=> <FadeEpisode ep={e}/>;",
        encoding="utf-8",
    )
    assert bln.is_promo(tsx) is False
    assert bln.is_promo(None) is None


def test_table_rows_handles_indent_and_escaped_pipes() -> None:
    rows = bln.table_rows("  | C01 | 爸爸 | a \\| b | 画面 |\n|---|---|\n")
    assert rows == [["C01", "爸爸", "a | b", "画面"]]


def test_find_visual_matches_exact_and_fuzzy_rows() -> None:
    rows = bln.table_rows(
        "| C02 | 爸爸 | 暂停，先画图。哪边缺零件？ | 留空缺口和问号 R#61 |\n"
        "| 1 | 爸爸：今天只练一件事，把题里的数画到纸上。 | 滑入格纸 |\n"
    )
    assert bln.find_visual("暂停，先画图。哪边缺零件？", rows) == "留空缺口和问号"
    assert bln.find_visual("今天只练一件事，把题里的数画到纸上", rows) == "滑入格纸"
    assert bln.find_visual("完全无关的一句话", rows) == ""


def test_find_visual_rejects_empty_and_prefers_same_clip() -> None:
    rows = bln.table_rows(SHEET)
    assert bln.find_visual("……", rows) == ""
    assert bln.find_visual("对！", rows, "C02") == "第二段的对"
    assert bln.find_visual("对！", rows, "C01") == "第一段的对"


def test_kept_sections_keeps_teaching_and_drops_production() -> None:
    md = "# T\n## 本集讲法\n要点\n## 画图坐标与动画执行\nx=1\n## 数学复核\n- 验算\n- 清单1–5：略\n## 进度\n略\n"
    sections = bln.kept_sections(md)
    assert [s.splitlines()[0] for s in sections] == ["## 本集讲法", "## 数学复核"]
    assert "清单" not in sections[1] and "- 验算" in sections[1]


def test_lesson_identity() -> None:
    assert bln.lesson_identity(Path("四年级-Q11平均数II")) == (
        "四年级",
        "Q11平均数II",
        "平均数II",
        11,
    )
    with pytest.raises(ValueError):
        bln.lesson_identity(Path("随便的目录"))


# -------------------------------------------------------------- end to end


def test_main_builds_notes_end_to_end(tmp_path: Path) -> None:
    out_root = tmp_path / "out"
    assert run(make_lesson(tmp_path), out_root) == 0
    note = note_text(out_root)
    assert "⏸ 停下来想 · 爸爸：暂停，先画图。" in note
    assert "画面：画平均线" in note
    assert "## 本集讲法" in note and "## 算式复核" in note
    assert "坐标" not in note and "清单" not in note
    assert "**0:02**" in note  # 65/30 + 0.3 s
    timeline = out_root / "四年级" / "Q11平均数II" / "timeline" / "Q11平均数II-第2集-移多补少.json"
    assert json.loads(timeline.read_text(encoding="utf-8"))["absolute_times"] is True


def test_main_uses_latest_timing_version(tmp_path: Path) -> None:
    lesson = make_lesson(
        tmp_path,
        timing_versions={
            1: _timing({"C01": ["旧的一句台词内容"]}),
            2: _timing({"C01": ["新的一句台词内容"]}),
        },
    )
    out_root = tmp_path / "out"
    assert run(lesson, out_root) == 0
    note = note_text(out_root)
    assert "新的一句台词内容" in note and "旧的一句台词内容" not in note


def test_main_reads_bom_files(tmp_path: Path) -> None:
    out_root = tmp_path / "out"
    assert run(make_lesson(tmp_path, bom=True), out_root) == 0
    assert "画面：画平均线" in note_text(out_root)


def test_main_without_remotion_uses_relative_times(tmp_path: Path) -> None:
    out_root = tmp_path / "out"
    assert run(make_lesson(tmp_path, tsx=None), out_root) == 0
    note = note_text(out_root)
    assert "段内相对时间" in note and "**0:00**" in note


def test_main_removes_stale_outputs(tmp_path: Path) -> None:
    out_root = tmp_path / "out"
    stale = out_root / "四年级" / "Q11平均数II" / "notes" / "Q11平均数II-第2集-旧标题.md"
    stale.parent.mkdir(parents=True)
    stale.write_text("old", encoding="utf-8")
    assert run(make_lesson(tmp_path), out_root) == 0
    assert not stale.exists()


def test_main_missing_timing_fails_cleanly(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    lesson = make_lesson(tmp_path)
    for f in (lesson.parent.parent / "配音").rglob("timing.json"):
        f.unlink()
    out_root = tmp_path / "out"
    assert run(lesson, out_root) == 2
    assert "缺少配音 timing.json" in capsys.readouterr().err
    assert not out_root.exists()


def test_main_rejects_bad_directory(tmp_path: Path) -> None:
    assert run(tmp_path / "不存在", tmp_path / "out") == 2
    bad = tmp_path / "随便的目录"
    bad.mkdir()
    assert run(bad, tmp_path / "out") == 2


def test_pause_cue_detection() -> None:
    assert bln._PAUSE_RE.search("先暂停，在草稿纸上画三列。")
    assert bln._PAUSE_RE.search("六十分是摊平得到的。暂停，先画图。")
    assert not bln._PAUSE_RE.search("这次不用暂停，直接说。")
    assert not bln._PAUSE_RE.search("别暂停，接着看。")
