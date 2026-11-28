"""Run the CoCo tutor test conversations and score each reply.

Each case is a short scripted conversation from the child's side. The same
cases run with the persona (``--persona coco-tutor``) and without it
(``--persona ""``) so the effect of the persona can be compared.

Usage (from the DeepTutor-CoCo root, deeptutor conda env)::

    python -X utf8 coco/tools/eval_persona.py --persona coco-tutor --out <dir>
    python -X utf8 coco/tools/eval_persona.py --persona "" --out <dir>

Automatic checks are rough signals; read the replies in the report too.
"""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import re
import sys
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
KB = "四年级数学思维"
MAX_SENTENCES = 4
FENCE_RE = re.compile(r"```.*?```", re.DOTALL)
MATH_RE = re.compile(r"\$\$.*?\$\$|\$[^$\n]*\$", re.DOTALL)
SENTENCE_END_RE = re.compile(r"[。！？!?]+")
CJK_RE = re.compile(r"[一-鿿]")
LATIN_WORD_RE = re.compile(r"[A-Za-z]{3,}")


@dataclass(frozen=True)
class Case:
    id: str
    goal: str
    turns: tuple[str, ...]
    language: str = "zh"
    # Strings that must NOT appear in the given reply (0-based turn index).
    forbidden: dict[int, tuple[str, ...]] = field(default_factory=dict)
    expect_bars: bool = False
    expect_question: bool = True
    allow_long_last: bool = False  # a requested full explanation may be longer


CASES: tuple[Case, ...] = (
    Case(
        id="ep4-why-div7",
        goal="问「为什么」：先引导，不直接说出 450，图不画到答案",
        turns=("第4集中间段那题为什么要÷7？我没听懂。",),
        forbidden={0: ("450",)},
        expect_bars=True,
    ),
    Case(
        id="car-first-ask",
        goal="直接要答案：只给第一层提示，不说出 36",
        turns=(
            "汽车厂那题：甲车间57人平均132个，乙车间平均163个，合起来平均144个，乙车间多少人？",
        ),
        forbidden={0: ("36人", "36 人", "= 36", "＝36", "＝ 36")},
    ),
    Case(
        id="car-stuck-ladder",
        goal="连续说不会：提示逐层加深，第二轮仍不直接给 36",
        turns=(
            "汽车厂那题：甲车间57人平均132个，乙车间平均163个，合起来平均144个，乙车间多少人？",
            "我不知道。",
            "还是不会。",
        ),
        forbidden={0: ("36人", "= 36", "＝36"), 1: ("36人", "= 36", "＝36")},
    ),
    Case(
        id="car-wrong-step",
        goal="她算错：指出可疑的那一步，让她自己检查",
        turns=(
            "汽车厂那题：甲车间57人平均132个，乙车间平均163个，合起来平均144个，乙车间多少人？"
            "我算的：甲每人少12个，12×57=674，674÷19，除不尽。",
        ),
        forbidden={0: ("36人", "= 36", "＝36")},
    ),
    Case(
        id="full-explain-retell",
        goal="她要完整讲解：讲完要请她复述",
        turns=(
            "汽车厂那题：甲车间57人平均132个，乙车间平均163个，合起来平均144个，乙车间多少人？"
            "我想了很久了，请完整讲一遍。",
        ),
        expect_bars=True,
        allow_long_last=True,
    ),
    Case(
        id="not-in-kb",
        goal="知识库没有的内容：说不确定，不编造视频内容",
        turns=("第12讲鸡兔同笼第3集最后那道题是怎么讲的？",),
        expect_question=False,
    ),
    Case(
        id="off-topic",
        goal="跑题：回应一句再带回学习",
        turns=("你喜欢看什么动画片？",),
        expect_question=False,
    ),
    Case(
        id="english-ui",
        goal="界面语言是英文时也用中文回答",
        turns=("平均数到底是什么意思？",),
        language="en",
    ),
)


def prose(text: str) -> str:
    """Reply text without code fences and math, for counting sentences."""
    return MATH_RE.sub("", FENCE_RE.sub("", text)).strip()


def sentence_count(text: str) -> int:
    body = re.sub(
        r"^\s*[#>*\-|].*$", "", prose(text), flags=re.MULTILINE
    )  # headings, lists, tables
    return len(
        [s for s in SENTENCE_END_RE.split(body) if CJK_RE.search(s) or LATIN_WORD_RE.search(s)]
    )


def mostly_chinese(text: str) -> bool:
    body = prose(text)
    return len(CJK_RE.findall(body)) >= 3 * len(LATIN_WORD_RE.findall(body))


def ends_with_question(text: str) -> bool:
    tail = prose(text).rstrip(" \n*_`)）")
    return tail.endswith(("？", "?"))


def score(case: Case, replies: list[str]) -> list[dict[str, Any]]:
    """Per-reply check results: ``{"check": name, "ok": bool, "detail": str}``."""
    results: list[dict[str, Any]] = []
    last = len(replies) - 1
    for i, reply in enumerate(replies):
        tag = f"第{i + 1}轮"
        n = sentence_count(reply)
        long_ok = case.allow_long_last and i == last
        results.append(
            {
                "check": f"{tag} 简短(≤{MAX_SENTENCES}句)",
                "ok": long_ok or n <= MAX_SENTENCES,
                "detail": f"{n}句",
            }
        )
        results.append({"check": f"{tag} 中文", "ok": mostly_chinese(reply), "detail": ""})
        leaked = [s for s in case.forbidden.get(i, ()) if s in reply]
        if case.forbidden.get(i):
            results.append(
                {"check": f"{tag} 不提前给答案", "ok": not leaked, "detail": ",".join(leaked)}
            )
        if case.expect_question and not long_ok:
            results.append(
                {"check": f"{tag} 以提问结尾", "ok": ends_with_question(reply), "detail": ""}
            )
    if case.expect_bars:
        results.append(
            {"check": "画了柱形图", "ok": any("```coco-bars" in r for r in replies), "detail": ""}
        )
    if case.allow_long_last:
        results.append(
            {
                "check": "请她复述",
                "ok": any(k in replies[-1] for k in ("复述", "用自己的话", "说一说", "讲给我听")),
                "detail": "",
            }
        )
    return results


async def run_case(app: Any, case: Case, persona: str) -> list[str]:
    from deeptutor.app import TurnRequest

    session_id: str | None = None
    replies: list[str] = []
    for text in case.turns:
        request = TurnRequest(
            content=text,
            capability="chat",
            session_id=session_id,
            knowledge_bases=[KB],
            language=case.language,
            persona=persona,
        )
        session, turn = await app.start_turn(request)
        session_id = session["id"]
        async for item in app.stream_turn(turn["id"]):
            if item.get("type") == "ask_user" or (item.get("metadata") or {}).get("ask_user"):
                await app.submit_user_reply(turn["id"], text="")
        detail = await app.get_session(session_id) or {}
        messages = [m for m in detail.get("messages", []) if m.get("role") == "assistant"]
        replies.append(str(messages[-1].get("content", "")) if messages else "")
    return replies


def report(persona: str, outcomes: list[tuple[Case, list[str], list[dict[str, Any]]]]) -> str:
    passed = sum(r["ok"] for _, _, rs in outcomes for r in rs)
    total = sum(len(rs) for _, _, rs in outcomes)
    lines = [f"# 人设测试：{persona or '（无人设）'}", "", f"自动检查通过 {passed}/{total}", ""]
    for case, replies, results in outcomes:
        lines += [f"## {case.id} — {case.goal}", ""]
        lines += [
            f"- {'✅' if r['ok'] else '❌'} {r['check']} {r['detail']}".rstrip() for r in results
        ]
        for i, (ask, reply) in enumerate(zip(case.turns, replies)):
            lines += [
                "",
                f"**孩子 {i + 1}：** {ask}",
                "",
                f"**AI {i + 1}：**",
                "",
                reply.strip(),
                "",
            ]
        lines.append("---")
    return "\n".join(lines) + "\n"


async def main_async(persona: str, out: Path, only: set[str]) -> int:
    os.environ.setdefault("DEEPTUTOR_HOME", str(REPO_ROOT))
    from deeptutor.app import DeepTutorApp

    app = DeepTutorApp()
    outcomes = []
    for case in CASES:
        if only and case.id not in only:
            continue
        print(f"… {case.id}", flush=True)
        replies = await run_case(app, case, persona)
        outcomes.append((case, replies, score(case, replies)))
    out.mkdir(parents=True, exist_ok=True)
    stem = persona or "no-persona"
    (out / f"{stem}.md").write_text(report(persona, outcomes), encoding="utf-8")
    (out / f"{stem}.json").write_text(
        json.dumps(
            [{"id": c.id, "replies": r, "checks": s} for c, r, s in outcomes],
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    passed = sum(r["ok"] for _, _, rs in outcomes for r in rs)
    total = sum(len(rs) for _, _, rs in outcomes)
    print(f"{stem}: {passed}/{total} 项通过 → {out / (stem + '.md')}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--persona", default="coco-tutor", help='人设名；"" 表示不用人设')
    parser.add_argument("--out", type=Path, required=True, help="报告输出目录")
    parser.add_argument("--only", nargs="*", default=[], help="只跑这些用例 id")
    args = parser.parse_args()
    return asyncio.run(main_async(args.persona, args.out, set(args.only)))


if __name__ == "__main__":
    sys.exit(main())
