from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import eval_persona as ev  # noqa: E402

BARS = '```coco-bars\n{"say": "很多很多句。很多句。很多句。"}\n```'


def test_sentence_count_ignores_diagrams_math_and_lists() -> None:
    reply = f"第一句。第二句？\n\n{BARS}\n\n$12 \\times 57 = 684$ 第三句！\n- 列表项。"
    assert ev.sentence_count(reply) == 3


def test_ends_with_question_skips_trailing_markup() -> None:
    assert ev.ends_with_question("你试过什么？**")
    assert not ev.ends_with_question("你试过什么？\n\n- 选项一")


def test_mostly_chinese() -> None:
    assert ev.mostly_chinese("平均数就是把总数分匀。")
    assert not ev.mostly_chinese("The average is the total divided by count.")


def test_score_flags_leaked_answer_and_missing_retell() -> None:
    case = ev.Case(
        id="t",
        goal="g",
        turns=("q",),
        forbidden={0: ("36人",)},
        expect_bars=True,
        allow_long_last=True,
    )
    results = {r["check"]: r["ok"] for r in ev.score(case, ["乙车间36人。"])}
    assert results["第1轮 不提前给答案"] is False
    assert results["画了柱形图"] is False
    assert results["请她复述"] is False


def test_case_ids_are_unique() -> None:
    ids = [c.id for c in ev.CASES]
    assert len(ids) == len(set(ids))
