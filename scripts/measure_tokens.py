#!/usr/bin/env python3
"""Regenerate `tests/data/cl100k_reference.json` from a real tokenizer.

The studio counts tokens offline, so its estimator is calibrated against
`cl100k_base` and the *counts* are committed instead of the 1.6 MB BPE table.
This script produces them; CI only reads them.

Getting the BPE file without network access in this environment: tiktoken
downloads `cl100k_base.tiktoken` from Azure blob storage, which some hosts
refuse. The same file is vendored inside `zurawiki/tiktoken-rs`, reachable over
`codeload.github.com`:

    curl -sL -o rs.tar.gz \\
        https://codeload.github.com/zurawiki/tiktoken-rs/tar.gz/refs/heads/main
    tar xzf rs.tar.gz tiktoken-rs-main/tiktoken-rs/assets/cl100k_base.tiktoken
    python scripts/measure_tokens.py --bpe tiktoken-rs-main/tiktoken-rs/assets/cl100k_base.tiktoken

Then, to make the *application* use the real tokenizer instead of the
estimator, point it at the same file:

    export DEEPTUTOR_TIKTOKEN_BPE=/path/to/cl100k_base.tiktoken

Usage:
    python scripts/measure_tokens.py [--bpe PATH] [--check]
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

TARGET = ROOT / "tests" / "data" / "cl100k_reference.json"

PAT_STR = (
    r"'(?i:[sdmt]|ll|ve|re)|[^\r\n\p{L}\p{N}]?+\p{L}++|\p{N}{1,3}+"
    r"| ?[^\s\p{L}\p{N}]++[\r\n]*+|\s++$|\s*[\r\n]|\s+(?!\S)|\s"
)

SENTENCES = [
    "مشتق نرخ تغییر لحظه‌ای است. در فیزیک، مشتق مکان نسبت به زمان همان سرعت است.",
    "شتاب نیز مشتق سرعت نسبت به زمان است. از مشتق برای یافتن بیشینه و کمینهٔ توابع استفاده می‌کنیم.",
    "به این درس خوش آمدید. فصل ۳ — مشتق. بخش ۱: مشتق نرخ تغییر لحظه‌ای است.",
    "حد و پیوستگی. حد یعنی نزدیک شدن به یک مقدار. پیوستگی یعنی بی‌پرش بودن نمودار.",
    "انتگرال مساحت زیر نمودار است. انتگرال معکوس مشتق است و کاربردهای زیادی دارد.",
    "تابع مثلثاتی، مشتق زنجیره‌ای، قاعدهٔ ضرب، قاعدهٔ تقسیم، و رسم نمودار دقیق توابع.",
    "اگر مشتق تابع در یک نقطه مثبت باشد، تابع در آن نقطه صعودی است.",
    "مساحت زیر نمودار سرعت برابر است با جابه‌جایی. این رابطه مفهوم انتگرال را روشن می‌کند.",
    "در ریاضیات، بردار یک کمیت با اندازه و جهت است و با پیکان نمایش داده می‌شود.",
    "معادلهٔ خط و شیب آن: شیب خط برابر است با تغییر در y تقسیم بر تغییر در x.",
    "Use the chain rule to differentiate a composite function in three steps.",
    "The area under a velocity graph equals displacement, which is the integral.",
    "A limit describes the value a function approaches, not necessarily reaches.",
    "Derivative of position with respect to time is velocity; derivative of velocity is acceleration.",
    "This lesson covers five worked examples and two exercises on continuity.",
    "مشتق",
    "انتگرال معین",
    "۳/۲",
    "تابع f(x) = x² + 2x + 1",
    "قالب: عنوان، مقدمه، بدنه، جمع‌بندی.",
]


def load_encoder(bpe: str | None):
    from tiktoken import Encoding
    from tiktoken.load import load_tiktoken_bpe

    if not bpe:
        import tiktoken

        return tiktoken.get_encoding("cl100k_base")
    return Encoding(
        name="cl100k_base",
        pat_str=PAT_STR,
        mergeable_ranks=load_tiktoken_bpe(bpe),
        special_tokens={},
    )


def build(encoder) -> dict:
    from deeptutor.services.studio import tokens

    rows = []
    for sentence in SENTENCES:
        rows.append(
            {
                "text": sentence,
                "chars": len(sentence),
                "cl100k": len(encoder.encode(sentence)),
                "estimator": tokens._estimate(sentence),
                "chars_div_4": tokens.count_chars_baseline(sentence),
            }
        )
    real = sum(r["cl100k"] for r in rows)
    estimate = sum(r["estimator"] for r in rows)
    baseline = sum(r["chars_div_4"] for r in rows)
    return {
        "reference": "cl100k_base",
        "how_obtained": "tiktoken Encoding with the published BPE file, loaded offline",
        "why_committed": "pins the estimator's calibration so CI can check it without network",
        "sentences": rows,
        "totals": {
            "cl100k": real,
            "estimator": estimate,
            "chars_div_4": baseline,
            "estimator_error": round(abs(estimate - real) / real, 4),
            "chars_div_4_error": round(abs(baseline - real) / real, 4),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bpe", help="path to a local cl100k_base.tiktoken")
    parser.add_argument(
        "--check",
        action="store_true",
        help="compare against the committed file instead of writing it",
    )
    args = parser.parse_args()

    payload = build(load_encoder(args.bpe))
    rendered = json.dumps(payload, ensure_ascii=False, indent=1) + "\n"

    if args.check:
        existing = TARGET.read_text() if TARGET.exists() else ""
        if existing != rendered:
            print("reference file is stale; run without --check", file=sys.stderr)
            return 1
        print("reference file matches a fresh measurement")
        return 0

    TARGET.write_text(rendered)
    totals = payload["totals"]
    print(f"wrote {TARGET.relative_to(ROOT)}")
    print(
        f"  real {totals['cl100k']}  estimator {totals['estimator']} "
        f"({totals['estimator_error']:.1%})  "
        f"chars/4 {totals['chars_div_4']} ({totals['chars_div_4_error']:.1%})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
