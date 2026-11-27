# گزارش فاز ۵ — دریافت محتوا، OCR و مدرسِ مستند

**تاریخ:** ۲۰۲۶-۱۱-۱۸ · **شاخه:** `arena/d6193a93-deeptutor` · **پایه:** `8a52d3e`

---

## ۱. فاز و دامنه

فاز ۵ طبق `ROADMAP.md` (سطرهای ۱۴۱–۱۶۶): تبدیل کتاب درسی PDF به متن
قابل بازیابی با منشأ صفحه/فصل، و پاسخ‌دادن به پرسش دانش‌آموز با ارجاع
کوتاه و قابل‌بررسی.

تحویل‌شده:

| خواستهٔ ROADMAP | وضعیت | کجا |
|---|---|---|
| خط لولهٔ PDF و OCR با استفادهٔ مجدد از ماژول‌های موجود | ✅ | `services/ingestion/extract.py` روی `services/parsing` |
| استخراج فصل، بخش، جدول، تصویر، فرمول و منشأ صفحه | ✅ | `ExtractedChunk` با `block_kind` چهارگانه |
| job دریافت با staging، بررسی، retry و نسخهٔ ایندکس | ✅ | `services/ingestion/pipeline.py` + `ingestion_runs` |
| فیلتر اجباری پایه/رشته/درس/حق نشر | ✅ | `grounding.scope_sql` — بدون پارامتر دور زدن |
| آداپتر RAG با استفادهٔ مجدد از خط لولهٔ موجود | ✅ | `grounding.retrievable/search` روی `ingestion_chunks` |
| رندر ارجاع کوتاه `[نام کتاب \| فصل]` | ✅ | `grounding.render_citation` |
| پاسخ خارج از منبع، abstention و مدیریت تناقض | ✅ | `search` + `grounding.abstain` |
| مجموعهٔ طلایی فارسی برای پایه‌های پایلوت | ✅ | `tests/fixtures/grounding/darsyar_phase5_golden.json` |

## ۲. baseline و شاخه

- پایه: `8a52d3e` (ادغام PR #5، فاز ۴ روی `main`)
- شاخه: `arena/d6193a93-deeptutor`

## ۳. فایل‌های تغییرکرده و دلیل مالکیت

**جدید:**

| مسیر | دلیل |
|---|---|
| `deeptutor/db/migrations/V0007__ingestion_and_grounding.sql` | سه جدول فاز ۵؛ مالکیت: لایهٔ DB |
| `deeptutor/db/repositories/grounding.py` | قرارداد دامنه، ارجاع، abstention |
| `deeptutor/services/ingestion/grounding_keys.py` | مشتق‌سازی کلید؛ ورق‌ای تا لایه‌بندی نشکند |
| `deeptutor/services/ingestion/extract.py` | قطعه‌بندی و تشخیص فصل |
| `deeptutor/services/ingestion/pipeline.py` | اجرا، retry، recovery |
| `deeptutor/services/ingestion/golden.py` | مجموعهٔ طلایی و سنجش |
| `deeptutor/api/routers/ingestion.py` | ۸ endpoint (۴ یادگیرنده، ۴ اپراتور) |
| `tests/db/test_scope_isolation.py` | ۱۱ آزمون نشتی |
| `tests/db/test_extraction.py` | ۲۷ آزمون استخراج و متن فارسی |
| `tests/db/test_citation.py` | ۱۹ آزمون ارجاع |
| `tests/db/test_ingestion_pipeline.py` | ۲۲ آزمون چرخهٔ عمر |
| `tests/db/test_grounding_http.py` | ۱۷ آزمون HTTP |
| `tests/db/test_golden_set.py` | ۱۸ آزمون مجموعهٔ طلایی |
| `tests/fixtures/grounding/darsyar_phase5_golden.json` | ۱۵ پروندهٔ طلایی فارسی |

**تغییرکرده:**

| مسیر | تغییر | دلیل |
|---|---|---|
| `deeptutor/services/rag/eval/matching.py` | افزودن شاخهٔ فارسی به tokenizer | **باگ موجود:** متن فارسی صفر توکن می‌داد |
| `deeptutor/db/schema_check.py` | سه جدول + دو ایندکس فاز ۵ | پوشش verify |
| `deeptutor/modules/manifests/server.json` | دو router جدید | ۲۲ خط اضافه، ۰ حذف |
| `deeptutor/modules/manifests/router-index.json` | بازسازی | ۶۲ router / ۷۶۶ route |

هیچ قابلیت موجودی حذف نشده. `retrievable()` امضایش تغییر نکرد؛ `search()` کنار
آن اضافه شد.

## ۴. تصمیم‌ها و ADR

`ADR-005-INGESTION-AND-GROUNDING.md` با شش تصمیم:

۱. فیلتر دامنه تابع است نه پارامتر — حتی `ignore_scope` وجود ندارد.
۲. ارجاع فقط با مجموعهٔ بازیابی‌شدهٔ همان پرسش اعتبار می‌گیرد.
۳. «قابل مشاهده» و «مرتبط» دو پرسش‌اند: `retrievable` در برابر `search`.
۴. `chunk_key` مکانی است تا ارتقای parser ارجاع‌ها را نشکند.
۵. `ocr_required` از `failed` جداست.
۶. ارجاع هرگز صفحه/پایه/رشته چاپ نمی‌کند (D-009).

## ۵. تست‌ها

| فرمان | exit | نتیجه |
|---|---|---|
| `pytest tests/db -q` | 0 | **۴۷۶ pass، ۲۶۸ skip، ۰ fail** |
| `pytest -q` (کامل) | 1 | **۱۴۴۳۰ pass، ۴۰۰ skip، ۲ fail** |
| `pytest tests/services/rag/eval -q` | 0 | ۸۹ pass |
| `pytest tests/api/test_router_loader.py -q` | 0 | ۵ pass |
| `ruff check` (فایل‌های فاز ۵) | 0 | All checks passed |
| `ruff format` | 0 | ۹ فایل بازقالب‌بندی، ۵ بدون تغییر |
| `lint-imports` | 0 | **۳ قرارداد حفظ، ۰ شکست** |

**دو شکست کامل، هر دو محیطی و از قبل موجود:**

- `test_doctor_cli::test_diagnostics_never_render_credentials_or_endpoint_secrets`
  — شکست به‌دلیل wrap شدن مسیر `/tmp/pytest-of-user/...` در کنسول باریک؛
  تفاوت فقط در `"user"` داخل مسیر موقت است.
- `test_kb_eval_cli::test_eval_reports_an_invalid_dataset` — همان علت؛
  `case\n#1` در برابر `case #1`.

هیچ‌کدام به کد فاز ۵ مربوط نیست و هر دو در فاز ۴ هم شکست می‌خوردند.

**آزمون‌های پذیرش ROADMAP، یکی‌یکی:**

| خواستهٔ پذیرش | آزمون |
|---|---|
| بازیابی دقیق مبحث و فصل | `test_the_whole_golden_set_passes` — ۱۵/۱۵ |
| نشت پایه/رشته در آزمون دشمن‌گونه | `test_scope_isolation.py` — ۱۱ آزمون |
| اعتبار ارجاع با سند واقعاً بازیابی‌شده | `test_citation.py` — ۱۹ آزمون |
| فارسی، ارقام، جدول، تصویر، فرمول، OCR | `test_extraction.py` — ۲۷ آزمون |
| پرسش خارج از منبع abstain می‌کند | ۳ پروندهٔ `abstain` در مجموعهٔ طلایی |
| شکست/timeout/لغو/restart | `test_ingestion_pipeline.py` — ۲۲ آزمون |
| صفر ارجاع ساختگی در مجموعهٔ ارزیابی | `test_no_answer_in_the_evaluation_set_has_a_hallucinated_citation` |

## ۶. آنچه تست نشده

- **OCR واقعی روی PDF اسکن‌شده.** `ocr_required` به‌عنوان برچسب آزمون
  دارد، اما هیچ PDF اسکن‌شده‌ای در مخزن نیست و نصب Tesseract در این محیط
  ممکن نشد. Gate 5 این را لازم دارد.
- **PostgreSQL برای کل خط لوله.** migration و هر دو ایندکس expression روی
  پروژهٔ واقعی Supabase اجرا و اثبات شدند (پایین را ببینید)، اما تست‌های
  `tests/db` فقط روی SQLite اجرا می‌شوند چون `DEEPTUTOR_TEST_DATABASE_URL`
  در این محیط به ۵۴۳۲ نمی‌رسد.
- **کیفیت بازیابی معنایی.** `search()` واژگانی است. سنجش با embedding ها
  کار Gate 5 است.

## ۷. شواهد migration و rollback

`V0007` روی **پروژهٔ واقعی Supabase** (`jmqgzaqydvkjysqlaloe`) اعمال شد:

```
deeptutor_schema_migrations:
  4 reconcile_legacy_supabase  7d30ecebfd332ffffadeac110f67147b
  5 ensure_unique_indexes      68d79f56c270d0f5bb25cd76a2fd28ea
  6 academic_catalog           e27fcfc57351ad3018f84acb3e38d914
  7 ingestion_and_grounding    fa648f8dc41a510ce030e9e45ee7b8f2
```

سه جدول `ingestion_runs`، `ingestion_chunks`، `grounded_answers` و پنج ایندکس
ساخته شدند. `-- @@ DOWN @@` همه را به ترتیب معکوس برمی‌دارد.

**باگ واقعی که فقط با PostgreSQL پیدا شد — باگ اصلی این فاز:**

```sql
-- رد شد روی PostgreSQL با 42601:
CREATE UNIQUE INDEX uq_ingestion_active
    ON ingestion_runs (source_id, CASE WHEN ... END);
```

SQLite این شکل را می‌پذیرد؛ PostgreSQL با `syntax error at or near "CASE"`
رد می‌کند. شکل قابل‌حمل، پرانتزگذاری دور خودِ `CASE` است:

```sql
CREATE UNIQUE INDEX uq_ingestion_active
    ON ingestion_runs (source_id,
        (CASE WHEN status IN ('queued','running') THEN 1 ELSE NULL END));
```

سپس روی PostgreSQL واقعی اثبات شد:

- دو ران live همزمان ⇒ `23505 duplicate key value violates unique constraint`
- ران اول `succeeded` شد ⇒ ران دوم `queued` پذیرفته شد ✅

اگر فقط به SQLite تکیه می‌شد، این migration در اولین deploy روی Supabase
می‌شکست. رگرسیون‌تست به‌صورت متنی فایل migration را می‌سنجد و شکل نادرست را
رد می‌کند.

## ۸. امنیت، حریم خصوصی، حق نشر

- **دریافت نامنبع رد می‌شود.** `source_not_approved` قبل از نوشتن هر ردیف.
  محتوای بدون مجوز نمی‌تواند به ایندکس برسد. زنده تست شد: `409`.
- **آرشیو فوراً قطع می‌کند.** اتصال زندهٔ `publicly_retrievable = 1` در
  `retrievable`. زنده تست شد: قبل `grounded: true`، بعد `abstained: true`،
  و قطعه‌ها هنوز در جدول برای حسابرسی هستند.
- **تغییر فایل زیر مجوز قدیم رد می‌شود.** `checksum_mismatch` مگر با
  `accept_checksum_change`.
- **دامنه از کلاینت نمی‌آید.** آزمون ساختاری: `ignore_scope=True` ⇒
  `TypeError`.
- **اپراتور از دانش‌آموز جدا است.** ingest و runs با سیاست `admin`؛ جست‌وجو
  با `learning`.
- **D-009 رعایت شد.** ارجاع هرگز صفحه/قطعه/پایه/رشته چاپ نمی‌کند.

## ۹. مسائل شناخته‌شده و ریسک باز

**بحرانی برای Gate 5:**

۱. **مجوز محتوا هنوز پاسخ ندارد.** سؤال Gate 4 بی‌پاسخ است: آیا سرو کردن
   کتاب‌های سازمان پژوهش مجاز است؟ `ROADMAP` (سطر ~۱۳۷) import انبوه بدون
   مجوز را ممنوع می‌کند. خط لوله از نظر فنی آماده است و اکنون *دروازهٔ مجوز
   را اجرا می‌کند*، اما هیچ کتاب واقعی وارد نشده چون پاسخ حقوقی نیست.

۲. **کیفیت بازیابی سنجیده نشده.** `search()` واژگانی است. پرسشی با مترادف
   کامل ممکن است abstain شود. این بدترین حالت ایمن است (سکوت به‌جای پاسخ
   غلط)، ولی برای پایلوت باید با embedding سنجیده شود.

**غیربحرانی:**

۳. نرمال‌سازی فارسی در دو جا تکرار شده (`grounding._normalise_fa` و
   `eval.matching`). باید به ماژول مشترک منتقل شود.
۴. `golden.py` به fixture وابسته است، نه به کتاب واقعی. با اولین کتاب مجوز
   گرفته باید با محتوای واقعی بازنویسی شود.
۵. `search()` بودجهٔ ۲۰۰ قطعه در حافظه دارد؛ برای کتابخانهٔ بزرگ باید به
   SQL منتقل شود.

## ۱۰. نتیجهٔ Gate

**PASS فنی / BLOCKED حقوقی.**

همهٔ معیارهای پذیرش فاز ۵ پاس شدند و روی سرور زنده اثبات شدند. اما Gate 5
دو شرط دارد که هیچ‌کدام هنوز برآورده نشده: ارزیابی کیفیت بازیابی، و مجوز
محتوا. تا پاسخ سؤال حقوقی، هیچ کتاب واقعی وارد نمی‌شود.

## ۱۱. commit و شاخه

- شاخه: `arena/d6193a93-deeptutor`
- push و merge فقط با اجازهٔ صریح کارفرما. این گزارش با PR ارائه می‌شود و
  منتظر تأیید می‌ماند.
