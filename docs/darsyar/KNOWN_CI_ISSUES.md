# بدهی باز CI — برای رفع روی سیستم محلی

**تاریخ:** ۲۰۲۶-۱۱-۱۷ · **شاخه:** `arena/334e26e8-deeptutor` · **PR:** #2

این سند آنچه را ثبت می‌کند که در این محیط **قابل رفع نبود** و باید روی یک ماشین محلی بررسی شود. دلیل هر مورد و شواهدش آمده است، تا بازتولید ارزان باشد.

---

## ۱. `Import Check (Python 3.14, macos-latest)` و `Video lesson isolation (macos-latest)`

**وضعیت: زیرساخت GitHub، نه کد.**

annotation خودِ job:

> The job was not acquired by Runner of type hosted even after multiple attempts
> Due to capacity constraints, jobs targeting macOS arm64 runners may experience longer queue times.

**هیچ چیزی برای رفع در کد نیست.** این job‌ها حتی شروع نشدند. دوباره اجرا کنید؛ یا اگر تکرار شد، `macos-latest` را به `macos-13`/`macos-14` (x64) تغییر دهید که ظرفیت بیشتری دارد.

**شاهد این‌که به کد ربطی ندارد:** `Import Check` روی ubuntu (۳.۱۱/۳.۱۲/۳.۱۳/۳.۱۴) و windows هر دو پاس‌اند، و `Video lesson isolation` روی ubuntu و windows هم پاس.

## ۲. ~~`Experimental TypeScript Chat Engine`~~ — **رفع شد، تقصیر من بود**

**این مورد «flaky» نبود. یک آزمون واقعی بود که تغییر خودم شکسته بود.**

### چه شد

مرحلهٔ ۱۰ از ۱۰ مرحلهٔ این job شکست می‌خورد:

> Exercise native model, history, tool boundaries and lazy API admission

اجرای `tests/runtime/test_native_engine.py` و `tests/api/test_router_loader.py` محلی:

```
FAILED tests/api/test_router_loader.py::test_repository_index_matches_router_sources
AssertionError: Run scripts/build_router_index.py
```

`deeptutor/api/router_index.json` یک **fingerprint** از سورس همهٔ روترها نگه می‌دارد. commit `6a8f55f` سه روتر را فرمت کرد (`co_writer.py`، `question.py`، `quiz_judge.py`)، پس fingerprint کهنه شد و آزمون — به‌درستی — گرفتش.

**رفع:** `python scripts/build_router_index.py` → ۵۵ روتر، ۷۳۱ مسیر. سپس ۱۸/۱۸ پاس. commit `d4d85ed`.

### درسی که ارزش ثبت دارد

دو اشتباه از من:

1. **«سه commit پاس بودند، پس flaky است»** — استدلال غلط بود. آن سه commit **قبل** از commit فرمت بودند؛ شکست دقیقاً با همان commit شروع شد. همبستگی را دیدم و علیت را اشتباه خواندم.
2. **مرحلهٔ شکست‌خورده را نگاه نکردم.** `gh run view --log` مسدود است، اما `gh api .../actions/jobs/<id>` فهرست **مرحله‌ها و نتیجهٔ هرکدام** را می‌دهد. یک فراخوانی، و علت مشخص بود. این را باید از اول امتحان می‌کردم.

نکتهٔ مثبت: آزمون درست کار کرد. تغییر ظاهراً بی‌خطر (whitespace) یک artifact تولیدشده را کهنه کرد و نگهبانش گرفتش.

## ۳. `Test Summary`

**نتیجهٔ #۱ است، نه شکست مستقل.** وقتی macOS سبز شود، این هم سبز می‌شود.

---

## آنچه در این شاخه رفع شد

`Lint and Format` — از زمان PR #1 روی `main` قرمز بود (`ruff format --check .` → ۵ فایل). با همان `ruff==0.16.0` که workflow پین می‌کند تأیید شد، سپس در commit `6a8f55f` فرمت اعمال شد. **تغییرات فقط whitespace؛ بدون تغییر منطق.** پس از آن: ۲۵۰ آزمون i18n پاس، هر چهار ماژول تمیز import می‌شوند.

---

## نکتهٔ مهم برای نگهداری

`ruff` را **همیشه** با نسخهٔ پین‌شده اجرا کنید. در این محیط `ruff 0.17.5` پنج فایل متفاوت را unformatted گزارش کرد و `0.16.0` همان پنج فایل اصلی را. نسخهٔ آزاد = نتیجهٔ متفاوت = سردرگمی.
