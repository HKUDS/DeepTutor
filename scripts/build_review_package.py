#!/usr/bin/env python3
"""Build a self-contained quality-review package for an independent reviewer.

Gate 8's quality column needs a Persian-speaking human who did not write this
code. The obstacle is not their judgment, it is friction: asking someone to run
a migration, seed a database and call an API to record an opinion is asking
them to do our job first.

So this script produces a folder with everything the verdict needs:

    <out>/
      artefacts/            one real file per kind, produced by the real renderer
      review.html           open in any browser, fill in, press "download verdict"
      verdict_template.json what the browser produces, for anyone who prefers an editor
      README.md             what each artefact is, and what the reviewer is asked
      load_verdict.py       takes the downloaded verdict and records it
      manifest.json         hashes, sizes, source text, so a verdict can be tied
                            to exactly what was reviewed

The reviewer never touches the repository. `load_verdict.py` does, and it
records the verdict through the same `record_review` the API uses, so an
independent review ends up as real evidence with `independent_reviews` counting
it -- not as an email.

Usage:
    python scripts/build_review_package.py --out review-package
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
import textwrap

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

#: One artefact per kind. The source text is a real lesson excerpt, not lorem
#: ipsum: a reviewer judging Persian register cannot judge gibberish.
#: Defects visible in the current output that the reviewer should confirm rather
#: than discover. Listing them is not an excuse: a `fail` on these is still a
#: fail, and the point of the exercise is that someone else confirms it.
KNOWN_ISSUES: dict[str, list[str]] = {
    "slide_deck": [
        "اسلاید ۱ فقط یک درود است («به این درس خوش آمدید») و هیچ ایده‌ای ندارد؛ "
        "پرسش one_idea باید روی آن fail بگیرد.",
        "هر شش اسلاید عنوان یکسانی دارند، چون یک درس یک فصل است؛ پرسش "
        "one_idea را با این ذهنیت پاسخ دهید که هر اسلاید فقط یک ایدهٔ *بدنه* دارد.",
    ],
    "video_lesson": [
        "فریم ۳ می‌گوید «سه شرط پیوستگی را با هم بررسی می‌کنیم» ولی هیچ‌کدام از "
        "سه شرط روی همان فریم نوشته نشده — این یک نقص است، نه یک انتخاب.",
        "چهار خانهٔ آخر storyboard خالی است، چون سه فریم داریم و چیدمان ۲×۲ است.",
    ],
    "mind_map": [
        "برچسب‌ها از جمله‌ها استخراج شده‌اند، نه از یک مدل؛ ممکن است یکی از آن‌ها "
        "دستور زبان ناهمواری داشته باشد که یک معلم بهتر می‌نوشت.",
    ],
    "audio_overview": [
        "این فایل گفتار نیست: یک تن با طول درست است. پرسش‌های pacing و "
        "no_reading را با این ذهنیت پاسخ دهید که نمونهٔ ساختار است.",
    ],
}

SAMPLES: list[dict[str, str]] = [
    {
        "kind": "infographic",
        "title": "ریاضی دهم — فصل مشتق",
        "source": (
            "مشتق نرخ تغییر لحظه‌ای است. در فیزیک، مشتق مکان نسبت به زمان همان "
            "سرعت است و مشتق سرعت نسبت به زمان شتاب. در ریاضی، مشتق در یک نقطه "
            "شیب خط مماس بر نمودار تابع است. اگر مشتق تابع در نقطه‌ای مثبت باشد، "
            "تابع در آن نقطه صعودی است و اگر منفی باشد نزولی. کاربردهای مشتق: "
            "یافتن بیشینه و کمینه، رسم دقیق نمودار، و محاسبهٔ سرعت و شتاب."
        ),
    },
    {
        "kind": "mind_map",
        "title": "ریاضی دهم — فصل مشتق",
        "source": (
            "مشتق نرخ تغییر لحظه‌ای است. مشتق در یک نقطه شیب خط مماس است. "
            "قواعد مشتق‌گیری: قاعدهٔ توان، قاعدهٔ ضرب، قاعدهٔ تقسیم و قاعدهٔ زنجیره‌ای. "
            "کاربرد مشتق در یافتن بیشینه و کمینه و رسم نمودار است. مشتق مرتبهٔ دوم "
            "تقعر نمودار را نشان می‌دهد."
        ),
    },
    {
        "kind": "slide_deck",
        "title": "ریاضی دهم — فصل مشتق",
        "source": (
            "به این درس خوش آمدید. امروز مشتق را تعریف می‌کنیم و می‌بینیم چرا مهم "
            "است. مشتق نرخ تغییر لحظه‌ای است. برای محاسبهٔ مشتق از قاعدهٔ توان "
            "استفاده می‌کنیم. مثال: مشتق تابع x به توان دو برابر است با دو x. "
            "حالا یک مثال از زندگی واقعی: سرعت خودرو مشتق مکان است."
        ),
    },
    {
        "kind": "audio_overview",
        "title": "ریاضی دهم — فصل انتگرال",
        "source": (
            "انتگرال مساحت زیر نمودار است. انتگرال معکوس مشتق است. اگر سرعت را "
            "بر حسب زمان داشته باشیم، انتگرال آن جابه‌جایی را می‌دهد. انتگرال معین "
            "بین دو نقطه مساحت را حساب می‌کند و انتگرال نامعین یک خانواده از توابع "
            "است. قضیهٔ اساسی حساب دیفرانسیل و انتگرال این دو را به هم وصل می‌کند."
        ),
    },
    {
        "kind": "video_lesson",
        "title": "ریاضی دهم — فصل حد و پیوستگی",
        "source": (
            "حد یعنی نزدیک شدن به یک مقدار. تابع می‌تواند در یک نقطه تعریف نشده "
            "باشد ولی حد داشته باشد. پیوستگی یعنی بی‌پرش بودن نمودار. اگر حد تابع "
            "در یک نقطه با مقدار تابع در آن نقطه برابر باشد، تابع در آن نقطه "
            "پیوسته است. سه شرط پیوستگی را با هم بررسی می‌کنیم."
        ),
    },
]

def build(out: Path) -> dict:
    from deeptutor.services.studio import licences, render
    from deeptutor.services.studio.script import ScriptRequest, build_script, quality_checklist

    artefacts = out / "artefacts"
    artefacts.mkdir(parents=True, exist_ok=True)

    entries = []
    for index, sample in enumerate(SAMPLES, start=1):
        kind = sample["kind"]
        script = build_script(
            ScriptRequest(
                kind=kind,
                source_text=sample["source"],
                source_id=f"review_src_{index}",
                chapter_title=sample["title"],
            )
        )
        credit = licences.attribution_for(
            licence_code="cc-by",
            source_title=sample["title"],
            source_id=f"review_src_{index}",
        )
        rendered = render.render_local(
            kind,
            {"attribution": credit, "chapter_title": sample["title"]},
            script=script,
        )
        data, mime = rendered.data, rendered.mime_type
        name = f"{index}-{kind}{rendered.extension}"
        path = artefacts / name
        path.write_bytes(data)
        entries.append(
            {
                "asset": name,
                "kind": kind,
                "mime": mime,
                "bytes": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
                "title": sample["title"],
                "source_text": sample["source"],
                "attribution": credit,
                # What the renderer says it actually is: a storyboard is not a
                # video and a tone is not speech. The reviewer is told, because
                # judging the wrong artefact produces a confident wrong verdict.
                "renderer_note": rendered.note,
                "known_issues": KNOWN_ISSUES.get(kind, []),
                "checklist": quality_checklist(kind),
            }
        )

    manifest = {
        "created_for": "Gate 8 quality column",
        "why": (
            "an independent Persian-speaking reviewer must judge these; a verdict "
            "from the author of the code is not a quality gate"
        ),
        "artefacts": entries,
    }
    (out / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return manifest


def write_form(out: Path, manifest: dict) -> None:
    (out / "review.html").write_text(_render_html(manifest), encoding="utf-8")


def write_verdict_template(out: Path, manifest: dict) -> None:
    template = {
        "reviewer": "",
        "reviewed_at": "",
        "notes": "",
        "verdicts": [
            {"asset": entry["asset"], "item_id": item["id"], "verdict": "", "comment": ""}
            for entry in manifest["artefacts"]
            for item in entry["checklist"]
        ],
    }
    (out / "verdict_template.json").write_text(
        json.dumps(template, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def write_readme(out: Path, manifest: dict) -> None:
    lines = [
        "# بستهٔ داوری کیفیت — فاز ۸",
        "",
        "این بسته برای یک **بازبین فارسی‌زبان مستقل** ساخته شده است. کسی که این کد را",
        "ننوشته باشد. داوری خودِ نویسندهٔ کد، هرچند ثبت شود، «مستقل» شمرده نمی‌شود.",
        "",
        "## چه کاری از شما خواسته شده",
        "",
        "۱. `review.html` را در مرورگر باز کنید (بدون اینترنت، بدون نصب چیزی).",
        "۲. برای هر اثر، به تصویر/صدا نگاه کنید و هر پرسش را پاسخ دهید.",
        "۳. در پایان «دانلود داوری» را بزنید؛ یک فایل `verdict.json` می‌گیرید.",
        "۴. همان فایل را به ما بدهید. کار شما تمام است.",
        "",
        "اگر مرورگر ندارید، `verdict_template.json` را با هر ویرایشگری پر کنید —",
        "شکل داده یکی است.",
        "",
        "## سه گزینه برای هر پرسش",
        "",
        "| گزینه | معنی |",
        "|---|---|",
        "| `pass` | درست است |",
        "| `fail` | غلط است؛ لطفاً در توضیح بنویسید کجا |",
        "| `unclear` | نمی‌توانم قضاوت کنم (مثلاً تخصص کافی ندارم) |",
        "",
        "`unclear` یک پاسخ کامل است. اگر همه را `pass` بزنید تا کار تمام شود،",
        "بسته بی‌فایده می‌شود؛ اگر واقعاً خوب است، `pass` درست است.",
        "",
        "## چه چیزی داوری می‌شود",
        "",
    ]
    for entry in manifest["artefacts"]:
        lines += [
            f"### {entry['asset']} — `{entry['kind']}`",
            "",
            f"- **فایل:** `artefacts/{entry['asset']}` ({entry['bytes']:,} بایت)",
            f"- **عنوان:** {entry['title']}",
            "- **متن منبعی که این اثر از آن ساخته شده:**",
            "",
            "  > " + entry["source_text"],
            "",
            f"- **renderer می‌گوید:** {entry['renderer_note']}",
            f"- **تعداد پرسش:** {len(entry['checklist'])}",
            "",
        ]
    lines += [
        "## نقص‌هایی که خودم می‌بینم (لطفاً تأیید یا رد کنید)",
        "",
        "این‌ها را نوشتم چون پیدا کردنشان کاری نیست که ارزش وقت شما را داشته باشد؛",
        "داوری این‌ها همچنان `fail` است، ولی می‌خواهم بدانید که ندیده نمانده‌اند.",
        "",
    ]
    for entry in manifest["artefacts"]:
        if not entry.get("known_issues"):
            continue
        lines.append(f"### {entry['asset']}")
        lines.append("")
        for issue in entry["known_issues"]:
            lines.append(f"- {issue}")
        lines.append("")

    lines += [
        "## چرا متن منبع هم آمده",
        "",
        "یکی از پرسش‌ها «آیا هر ادعای متن در منبع قابل ردیابی است؟» است — بدون دیدن",
        "منبع، این پرسش قابل پاسخ نیست. متن منبع عیناً همان چیزی است که به renderer",
        "داده شده، نه خلاصه‌ای از آن.",
        "",
        "## این بسته چه چیزی را ثابت نمی‌کند",
        "",
        "- **ویدیو یک فایل ویدیو نیست.** روی این ماشین encoder نیست؛ `video_lesson` یک",
        "  storyboard واقعی از فریم‌هاست. پرسش‌های آن دربارهٔ ترتیب و خوانایی فریم‌هاست.",
        "- **صدا گفتار نیست.** `audio_overview` یک WAV واقعی با طول درست و لحن",
        "  جایگزین است، نه گفتار فارسی. پرسش «سرعت گفتار» را با این ذهنیت پاسخ دهید",
        "  که نمونهٔ محتوا است، نه محصول نهایی.",
        "- **متن با مدل نوشته نشده.** `build_script` ساختار می‌دهد و از منبع استخراج",
        "  می‌کند. داوری شما دربارهٔ ساختار و ثبت فارسی است، نه دربارهٔ تولید محتوا.",
        "",
        "این‌ها را نوشتم تا داوری شما دربارهٔ چیزی باشد که واقعاً ساخته شده، نه",
        "چیزی که فکر می‌کنید باید ساخته شود.",
        "",
    ]
    (out / "README.md").write_text("\n".join(lines), encoding="utf-8")


def write_loader(out: Path) -> None:
    loader = textwrap.dedent(
        '''\
        #!/usr/bin/env python3
        """Record a completed review package as real evidence.

        Run this after the reviewer hands back `verdict.json`. It writes the
        verdicts through the same `record_review` the API uses, so the result
        shows up in `independent_reviews` and can be quoted by the phase report.

        The reviewer's id is what makes the review independent, so it is
        required and must differ from the asset owner.

            python load_verdict.py --verdict verdict.json \\
                --db sqlite:///studio.db --owner u1 --reviewer teacher-01
        """
        from __future__ import annotations

        import argparse
        import json
        from pathlib import Path
        import sys

        ROOT = Path(__file__).resolve().parents[1]
        sys.path.insert(0, str(ROOT))


        def main() -> int:
            parser = argparse.ArgumentParser(description=__doc__)
            parser.add_argument("--verdict", required=True)
            parser.add_argument("--db", required=True, help="sqlite:///path or postgres DSN")
            parser.add_argument("--owner", required=True, help="the asset owner's user id")
            parser.add_argument("--reviewer", required=True, help="the reviewer's id")
            parser.add_argument("--registry", required=True,
                                help="path to the assets file produced alongside this script")
            args = parser.parse_args()

            if args.reviewer == args.owner:
                print("reviewer must differ from owner: a self-review is not independent",
                      file=sys.stderr)
                return 2

            from deeptutor.db.config import DatabaseSettings
            from deeptutor.db.connection import Database
            from deeptutor.services.studio import jobs as studio

            settings = DatabaseSettings(app_url=args.db, migration_url=args.db)
            db = Database(settings)
            registry = json.loads(Path(args.registry).read_text(encoding="utf-8"))
            payload = json.loads(Path(args.verdict).read_text(encoding="utf-8"))

            recorded = 0
            for row in payload.get("verdicts", []):
                if not row.get("verdict"):
                    continue
                asset_id = registry[row["asset"]]
                studio.record_review(
                    db,
                    asset_id=asset_id,
                    user_id=args.owner,
                    item_id=row["item_id"],
                    verdict=row["verdict"],
                    comment=row.get("comment", ""),
                    reviewer_id=args.reviewer,
                )
                recorded += 1
            print(f"recorded {recorded} verdicts from reviewer {args.reviewer}")
            return 0


        if __name__ == "__main__":
            raise SystemExit(main())
        '''
    )
    path = out / "load_verdict.py"
    path.write_text(loader, encoding="utf-8")
    path.chmod(0o755)


def _render_html(manifest: dict) -> str:
    data = json.dumps(manifest, ensure_ascii=False)
    return f"""<!doctype html>
<html lang="fa" dir="rtl">
<meta charset="utf-8">
<title>داوری کیفیت — فاز ۸</title>
<style>
 body {{ font-family: Tahoma, "Iranian Sans", sans-serif; background:#111; color:#eee;
        max-width: 900px; margin: 0 auto; padding: 2rem 1rem; line-height: 1.9; }}
 h1 {{ font-size:1.4rem; border-bottom:2px solid #444; padding-bottom:.5rem }}
 h2 {{ font-size:1.1rem; margin-top:2.5rem; color:#9cf }}
 .asset {{ background:#1b1b1b; border:1px solid #333; border-radius:8px;
           padding:1rem; margin-bottom:2rem }}
 img {{ max-width:100%; border-radius:6px; background:#fff }}
 audio {{ width:100%; margin:.5rem 0 }}
 .src {{ background:#151515; border-right:3px solid #666; padding:.6rem .8rem;
         font-size:.9rem; color:#bbb; margin:.5rem 0 1rem }}
 .item {{ border-top:1px solid #2a2a2a; padding:.8rem 0 }}
 .q {{ font-weight:bold; margin-bottom:.5rem }}
 label {{ margin-inline-end:1.2rem; cursor:pointer }}
 textarea {{ width:100%; background:#0d0d0d; color:#eee; border:1px solid #333;
             border-radius:4px; padding:.4rem; font-family:inherit; font-size:.9rem }}
 input[type=text] {{ background:#0d0d0d; color:#eee; border:1px solid #333;
                      border-radius:4px; padding:.4rem; font-family:inherit }}
 button {{ background:#2d6cdf; color:#fff; border:0; border-radius:6px;
           padding:.7rem 1.4rem; font-size:1rem; cursor:pointer; margin-top:1rem }}
 .hint {{ color:#888; font-size:.85rem }}
 progress {{ width:100%; height:8px }}
</style>
<h1>داوری کیفیت — فاز ۸</h1>
<p class="hint">
 برای هر پرسش یک گزینه انتخاب کنید. <b>unclear</b> پاسخ کامل است؛ اگر تخصص کافی
 ندارید همین را بزنید. در پایان «دانلود داوری» را بزنید.
</p>
<p>پیشرفت: <progress id="bar" value="0" max="1"></progress> <span id="cnt">۰</span></p>
<div id="root"></div>

<div class="asset">
  <h2>شناسنامهٔ بازبین</h2>
  <p><label>نام یا شناسهٔ شما: <input type="text" id="reviewer" size="30"></label></p>
  <p class="hint">این نام در گزارش می‌آید تا داوری قابل استناد باشد.</p>
  <p><label>یادداشت کلی (اختیاری):<br>
     <textarea id="notes" rows="3"></textarea></label></p>
  <button onclick="download()">دانلود داوری</button>
</div>

<script>
const MANIFEST = {data};
const root = document.getElementById('root');
const state = {{}};

for (const entry of MANIFEST.artefacts) {{
  const box = document.createElement('div');
  box.className = 'asset';
  const src = entry.mime.startsWith('audio')
      ? `<audio controls src="artefacts/${{entry.asset}}"></audio>`
      : `<img src="artefacts/${{entry.asset}}" alt="${{entry.asset}}">`;
  box.innerHTML = `<h2>${{entry.asset}}</h2>
    <p class="hint">${{entry.kind}} — ${{entry.bytes.toLocaleString('fa')}} بایت</p>
    ${{src}}
    <p class="hint">متنی که این اثر از آن ساخته شده:</p>
    <div class="src">${{entry.source_text}}</div>`;
  for (const item of entry.checklist) {{
    const key = entry.asset + '::' + item.id;
    state[key] = {{asset: entry.asset, item_id: item.id, verdict: '', comment: ''}};
    const div = document.createElement('div');
    div.className = 'item';
    div.innerHTML = `<div class="q">${{item.question}}</div>
      <label><input type="radio" name="${{key}}" value="pass"> pass</label>
      <label><input type="radio" name="${{key}}" value="fail"> fail</label>
      <label><input type="radio" name="${{key}}" value="unclear"> unclear</label>
      <textarea rows="2" placeholder="توضیح (برای fail لازم است)"></textarea>`;
    div.querySelectorAll('input[type=radio]').forEach(r =>
      r.addEventListener('change', () => {{ state[key].verdict = r.value; update(); }}));
    div.querySelector('textarea').addEventListener('input', e => state[key].comment = e.target.value);
    box.appendChild(div);
  }}
  root.appendChild(box);
}}

function update() {{
  const total = Object.keys(state).length;
  const done = Object.values(state).filter(v => v.verdict).length;
  document.getElementById('bar').max = total;
  document.getElementById('bar').value = done;
  document.getElementById('cnt').textContent =
      done.toLocaleString('fa') + ' از ' + total.toLocaleString('fa');
}}

function download() {{
  const reviewer = document.getElementById('reviewer').value.trim();
  if (!reviewer) {{ alert('نام یا شناسهٔ خود را بنویسید.'); return; }}
  const missing = Object.values(state).filter(v => !v.verdict);
  if (missing.length) {{
    if (!confirm(missing.length + ' پرسش بی‌پاسخ مانده. با این حال ادامه می‌دهید؟')) return;
  }}
  const payload = {{
    reviewer,
    reviewed_at: new Date().toISOString(),
    notes: document.getElementById('notes').value,
    verdicts: Object.values(state).filter(v => v.verdict),
  }};
  const blob = new Blob([JSON.stringify(payload, null, 2)], {{type: 'application/json'}});
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = 'verdict.json';
  a.click();
}}
update();
</script>
</html>
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="review-package")
    args = parser.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    manifest = build(out)
    write_form(out, manifest)
    write_verdict_template(out, manifest)
    write_readme(out, manifest)
    write_loader(out)

    total_items = sum(len(entry["checklist"]) for entry in manifest["artefacts"])
    print(f"wrote {out}/")
    print(f"  {len(manifest['artefacts'])} artefacts, {total_items} questions")
    for entry in manifest["artefacts"]:
        print(f"    {entry['asset']:28s} {entry['bytes']:>9,} bytes  {len(entry['checklist'])} questions")
    print(f"  open {out}/review.html to review")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
