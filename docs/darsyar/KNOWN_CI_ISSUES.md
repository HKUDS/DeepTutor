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

## ۲. `Experimental TypeScript Chat Engine`

**وضعیت: flaky در CI، سبز در محیط محلی.**

روی همین شاخه، **سه commit متوالی** پیش از commit آخر این job را پاس کردند:

| commit | نتیجه |
| --- | --- |
| `490e67b` | ✅ success |
| `769b393` | ✅ success |
| `cecccc2` | ✅ success |
| `6a8f55f` | ❌ failure |

`6a8f55f` **فقط ۵ فایل Python را فرمت کرد** (whitespace محض) و `packages/chat-engine` را لمس نکرد. پس ارتباط علّی منتفی است.

بازتولید محلی — هر دو بخش سبز:

```
packages/chat-engine$ npm test                    → 76/76 pass
DEEPTUTOR_CHAT_ENGINE=typescript pytest \
  tests/agents/chat tests/runtime/test_ts_engine.py \
  tests/services/partners/test_partner_runtime.py \
  tests/capabilities/test_partner_group_capability.py \
  tests/capabilities/test_mastery_loop_pipeline.py
                                                  → 292 + 112 pass
```

**گام بعدی روی سیستم خودتان:** job را دوباره اجرا کنید. اگر سبز شد، flaky تأیید می‌شود. اگر نه، لحظهٔ دقیق شکست را با `gh run view <id> --log-failed` ببینید — چیزی که در این sandbox مسدود است. علت محتمل: تفاوت نسخهٔ Node (CI از ۲۲ استفاده می‌کند) یا وابستگی شبکه‌ای در `npm ci`.

## ۳. `Test Summary`

**نتیجهٔ #۱ و #۲ است، نه شکست مستقل.** وقتی آن دو سبز شوند، این هم سبز می‌شود.

---

## آنچه در این شاخه رفع شد

`Lint and Format` — از زمان PR #1 روی `main` قرمز بود (`ruff format --check .` → ۵ فایل). با همان `ruff==0.16.0` که workflow پین می‌کند تأیید شد، سپس در commit `6a8f55f` فرمت اعمال شد. **تغییرات فقط whitespace؛ بدون تغییر منطق.** پس از آن: ۲۵۰ آزمون i18n پاس، هر چهار ماژول تمیز import می‌شوند.

---

## نکتهٔ مهم برای نگهداری

`ruff` را **همیشه** با نسخهٔ پین‌شده اجرا کنید. در این محیط `ruff 0.17.5` پنج فایل متفاوت را unformatted گزارش کرد و `0.16.0` همان پنج فایل اصلی را. نسخهٔ آزاد = نتیجهٔ متفاوت = سردرگمی.
