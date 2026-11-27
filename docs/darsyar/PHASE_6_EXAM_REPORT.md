# گزارش فاز ۶ — مرکز آزمون و ارزیابی

**تاریخ:** ۲۰۲۶-۱۱-۱۸ · **شاخه:** `arena/d6193a93-deeptutor` · **پایه:** `1ceff2a`

---

## ۱. فاز و دامنه

فاز ۶ طبق `ROADMAP.md` (سطرهای ۱۸۲–۲۰۷): اجرای آزمون چهارگزینه‌ای،
تشریحی و کنکوری با نمره‌دهی قطعی و تکرارپذیر.

| خواستهٔ ROADMAP | وضعیت | کجا |
|---|---|---|
| بانک سؤال و نسخهٔ سؤال | ✅ | `exam_questions` + `create_question` |
| blueprint آزمون، فصل/مبحث، دشواری، زمان و ترتیب | ✅ | `exams.blueprint` + `validate_exam` |
| چهارگزینه‌ای با نمره‌دهی قطعی بر اساس کلید | ✅ | `scoring.grade_multiple_choice` |
| تشریحی با rubric، نمرهٔ جزئی، عدم‌قطعیت، بازبینی انسانی | ✅ | `grade_essay` + `regrade_attempt` |
| نمرهٔ منفی با policy قابل تنظیم به‌ازای هر آزمون | ✅ | `exam_scoring_policies.negative_ratio` |
| snapshot از سؤال، کلید و سیاست نمره‌دهی | ✅ | سه ستون snapshot در `exam_attempts` |
| گزارش اشتباهات و مباحث نیازمند مرور | ✅ | `mistake_report` |
| جلوگیری از نمره‌دهی قطعی به سؤال خراب/بدون کلید | ✅ | `key_status` ⇒ `voided` |

## ۲. baseline و شاخه

- پایه: `1ceff2a` (ادغام PR #6، فاز ۵ روی `main`)
- شاخه: `arena/d6193a93-deeptutor`

## ۳. فایل‌های تغییرکرده

**جدید:**

| مسیر | خط | دلیل |
|---|---|---|
| `deeptutor/db/migrations/V0008__exam_center.sql` | ۲۶۷ | هفت جدول فاز ۶ |
| `deeptutor/services/exam/scoring.py` | ۵۳۰ | نمره‌دهی خالص و قطعی |
| `deeptutor/db/repositories/exam.py` | ۹۸۰ | بانک، آزمون، attempt، تغییر نمره |
| `deeptutor/api/routers/exam.py` | ۶۹۰ | ۱۷ endpoint در سه سطح |
| `tests/db/test_exam_scoring.py` | ۴۸۰ | ۴۸ آزمون واحد و property |
| `tests/db/test_exam_center.py` | ۵۶۰ | ۳۹ آزمون مخزن |
| `tests/db/test_exam_http.py` | ۴۲۰ | ۲۹ آزمون HTTP |
| `docs/darsyar/ADR-006-EXAM-CENTER.md` | — | ۹ تصمیم |
| `docs/darsyar/evidence/phase6-exam-baseline.json` | — | شواهد |

**تغییرکرده:** `schema_check.py` (۷ جدول + ۴ ایندکس)،
`manifests/server.json` (۳ router، ۴۳ خط اضافه)، `router_index.json`،
`ROADMAP.md`، `DECISIONS.md` (§J).

## ۴. تصمیم‌ها

`ADR-006` با ۹ تصمیم. سه‌تای اصلی:

۱. **snapshot در ارسال** — نمره‌دهی هرگز بانک زنده را نمی‌خواند.
۲. **نسخه قفل می‌شود** — آزمون ساخته‌شده با v1 همیشه v1 می‌ماند.
۳. **`(exam, user, attempt_no)` هویت attempt** — تکرار همان پاسخ بی‌اثر،
   پاسخ متفاوت تعارض.

بقیه: نمرهٔ منفی نسبت است، نزده خنثی، سؤال خراب void، تشریحی هرگز خودکار
قطعی نمی‌شود، کلید پاسخ به دانش‌آموز نمی‌رسد، attempt متعلق به صاحبش است.

## ۵. تست‌ها

| فرمان | exit | نتیجه |
|---|---|---|
| `pytest tests/db -q` | 0 | **۵۸۷ pass، ۳۳۵ skip، ۰ fail** |
| `pytest tests/db tests/services/rag/eval tests/api -q` | 0 | **۱۹۵۶ pass، ۳۵۸ skip** |
| `pytest tests/db/test_exam_*.py` | 0 | **۱۱۶ pass** |
| `ruff check deeptutor tests/db` | 0 | All checks passed |
| `lint-imports` | 0 | ۳ قرارداد حفظ |
| router index | — | **۶۵ router / ۷۸۵ route** |

**آزمون‌های پذیرش ROADMAP:**

| خواستهٔ پذیرش | آزمون |
|---|---|
| unit/property برای فرمول نمره و edge cases | ۸ آزمون property در `test_exam_scoring.py` |
| پاسخ غلط، درست، نزده، بدون پاسخ، ضریب متفاوت | ۴ آزمون پایه + `test_property_*` |
| سه غلط/یک درست فقط با policy فعال | `test_three_wrong_and_one_right_only_works_when_the_policy_is_active` |
| تشریحی: rubric، حداقل/حداکثر، اعتراض و تغییر ثبت‌شده | ۵ آزمون در `test_exam_center.py` |
| تکرار/refresh نباید attempt یا نمرهٔ دوم بسازد | ۳ آزمون idempotency |
| نمرهٔ قبلی با تغییر بانک یا policy عوض نشود | **۲ آزمون که حمله می‌کنند** |

**آزمون‌های property — چرا مهم‌اند:** آزمون واحد یک نمونه را می‌سنجد؛ آزمون
property یک گزاره را که باید برای **همهٔ** ورودی‌ها درست باشد. نمره‌دهی
دقیقاً به همین نیاز دارد:

- **کران‌داری**: نمره هرگز از حداکثر بیشتر نمی‌شود (برای همهٔ ۲۷ ترکیب
  ۳ سؤال × ۳ حالت، کامل و نه نمونه‌ای)
- **یکنوایی**: پاسخ درست هرگز از غلط کمتر نمی‌گیرد (برای ۵ نسبت جریمه)
- **قطعی‌بودن**: همان snapshot همیشه همان عدد (۳۰ اجرای تصادفی)
- **جمع‌پذیری**: نمرهٔ کل همیشه برابر مجموع آیتم‌ها

## ۶. آنچه تست نشده

- **نمره‌دهی تشریحی با LLM.** هیچ ارائه‌دهندهٔ فعالی در این محیط نیست؛
  `needs_review` مسیر واقعی است. Gate 6 باید با پاسخ‌های واقعی سنجیده شود.
- **کل خط لوله روی PostgreSQL.** migration و هر پنج ایندکس روی پروژهٔ واقعی
  Supabase اجرا و اثبات شدند، اما `tests/db` فقط روی SQLite اجرا می‌شود چون
  `DEEPTUTOR_TEST_DATABASE_URL` به ۵۴۳۲ نمی‌رسد.
- **UI آزمون.** این فاز فقط سرور است.

## ۷. شواهد migration و rollback

`V0008` روی **پروژهٔ واقعی Supabase** اعمال شد. دفترچه:

```
4 reconcile_legacy_supabase  7d30ecebfd332ffffadeac110f67147b
5 ensure_unique_indexes      68d79f56c270d0f5bb25cd76a2fd28ea
6 academic_catalog           e27fcfc57351ad3018f84acb3e38d914
7 ingestion_and_grounding    fa648f8dc41a510ce030e9e45ee7b8f2
8 exam_center                abb527d6653e232c24ec3ec88f6462ed
```

هفت جدول ساخته شدند: `exam_questions`، `exam_scoring_policies`، `exams`،
`exam_items`، `exam_attempts`، `exam_attempt_items`، `exam_grade_changes`.

**اثبات روی PostgreSQL واقعی:**

- درج `exam_attempts` با `exam_id` ناموجود ⇒ **`23503`** (کلید خارجی کار می‌کند)
- درج دوم با `(ex_probe, u1, 1)` ⇒ **`23505 duplicate key`** روی
  `uq_exam_attempt_identity`
- درج با `(ex_probe, u1, 2)` ⇒ **پذیرفته** (امتحان مجدد ممکن است)

یعنی محدودیتی که «تکرار نباید attempt دوم بسازد» را تضمین می‌کند، روی موتور
واقعی کار می‌کند و امتحان مجدد را هم نمی‌بندد.

`-- @@ DOWN @@` هر هفت جدول و همهٔ ایندکس‌ها را به ترتیب معکوس برمی‌دارد.

## ۸. امنیت، حریم خصوصی، حق نشر

- **کلید پاسخ هرگز به دانش‌آموز نمی‌رسد.** `GET /api/exam/exams/{id}` بدون
  `answer_key`؛ آزمون رشتهٔ سریال‌شده را می‌گردد. روی سرور زنده تأیید شد:
  `answer_key present? False`.
- **IDOR بسته است.** `GET /api/exam/attempts/{id}?user_id=` مالکیت را بررسی
  می‌کند؛ stranger ⇒ `404`. زنده تأیید شد.
- **سه سطح دسترسی.** student (`learning`)، operator (`admin`)، review
  (`admin` روی prefix جدا). تغییر نمرهٔ ثبت‌شده فقط از سطح review ممکن است.
- **هر تغییر نمره دلیل اجباری دارد.** `OverridePayload.reason` با
  `min_length=1`؛ بدون دلیل، درخواست اصلاً ساخته نمی‌شود.
- **آزمون draft به دانش‌آموز نشان داده نمی‌شود** و منتشر کردن آزمون با سؤال
  بازبینی‌نشده ⇒ `409`.

## ۹. مسائل شناخته‌شده و ریسک باز

**برای Gate 6:**

۱. **اعتبارسنجی با مجموعهٔ سؤال بازبینی‌شده.** `validate_exam` آماده است و
   منتشر کردن را می‌بندد، اما هیچ مجموعهٔ سؤال واقعیِ بازبینی‌شده وجود ندارد.
   Gate 6 این را لازم دارد و به پاسخ حقوقی فاز ۵ هم وابسته است (سؤال از کتاب
   می‌آید).

۲. **نمره‌دهی تشریحی.** `needs_review` امن است اما بدون نمرهٔ انسانی هیچ
   بازخوردی به دانش‌آموز نمی‌دهد. یک مسیر UI برای معلم لازم است.

**غیربحرانی:**

۳. `exam_questions` هر ویرایش یک ردیف جدید می‌سازد و ردیف‌های قدیمی هرگز
   پاک نمی‌شوند (برای حسابرسی درست است) — نیازمند یک کار پاک‌سازی دوره‌ای.
۴. snapshot برای هر attempt تکرار می‌شود (~۵۰KB برای ۵۰ سؤال). پذیرفتنی است
   ولی برای کتابخانهٔ بزرگ مقیاس‌پذیر نیست.
۵. `list_my_attempts` فیلد `user_id` را از کلاینت می‌گیرد؛ در تولید باید از
   نشست احراز هویت بیاید (همان الگوی `admin/123` dev-only).

## ۱۰. نتیجهٔ Gate

**PASS فنی / BLOCKED برای اعتبارسنجی محتوا.**

همهٔ معیارهای پذیرش فاز ۶ پاس شدند و روی سرور زنده اثبات شدند. Gate 6 شرط
«اعتبارسنجی آزمون با مجموعهٔ سؤال بازبینی‌شده» را دارد که بدون محتوای واقعی
(و بدون پاسخ سؤال حقوقی فاز ۴) قابل انجام نیست.

## ۱۱. commit و شاخه

- شاخه: `arena/d6193a93-deeptutor`
- push و merge فقط با اجازهٔ صریح کارفرما.
