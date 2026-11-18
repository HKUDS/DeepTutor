# نقشه راه اجرایی درسیار (Roadmap & Acceptance Gates)

- نسخه: 1.0
- تاریخ: 2026-11-16
- وضعیت همه فازها در زمان ایجاد سند: NOT STARTED / نیازمند اجرا و شواهد

## اصول اجرای نقشه راه

1. فازها به ترتیب اجرا شوند؛ فاز بعدی پیش از عبور رسمی از Gate فاز جاری شروع نشود.
2. هر فاز scope محدود، مالکیت فایل/ماژول، معیار پذیرش، تست و گزارش مستقل داشته باشد.
3. ابتدا source owner و تست‌های فعلی DeepTutor شناخته شوند؛ قابلیت تکراری ساخته نشود.
4. هیچ Phase با صرف نوشتن UI، کامیت یا وجود کلاس/Manifest COMPLETE نیست.
5. تست‌های موجود نباید بی‌دلیل حذف یا ضعیف شوند.
6. داده واقعی کتاب یا دانش‌آموز در fixture عمومی/ریپازیتوری قرار نگیرد.
7. هیچ عملیات تولیدی/Production با رمز پیش‌فرض، کلید تست یا مجوز نامشخص فعال نشود.
8. KiloCode باید تفاوت بین PASS، FAIL، BLOCKED، NOT RUN و NOT APPLICABLE را صریح گزارش کند.

## فازها

### Phase 0 — Repository Audit & Architecture Baseline

**هدف:** ساختن خط مبنا و کاهش ریسک پیش از هر تغییر اجرایی.

Scope:
- بررسی README، AGENTS، مستندات معماری، توسعه، تست، ماژول‌ها، ذخیره‌سازی، امنیت و قراردادهای Frontend.
- ترسیم request flow از Browser تا TurnApplicationService/Turn Engine و بازگشت stream.
- فهرست auth، session، multi-user، knowledge, RAG, books, questions, practice, mastery, audio/video, provider catalog و usage.
- تهیه dependency map و source ownership map.
- فهرست تست‌های مرتبط و baseline قابل تکرار.
- تشخیص وضعیت current branch، working tree و آخرین commit.
- بررسی fork/upstream و رعایت Apache-2.0 و THIRD_PARTY_NOTICES.
- ثبت gaps، risks و ADRهای لازم.

ممنوع:
- تغییر کد اجرایی، schema، settings یا dependency.
- حذف فایل/ماژول.
- migration داده یا تنظیم Production.

Acceptance:
- گزارش ممیزی با pathهای واقعی و وضعیت هر قابلیت.
- test baseline با command، environment، exit code و summary.
- هیچ ادعای PASS بدون خروجی ثبت‌شده.
- نقشه وابستگی و اولویت ریسک.
- فهرست دقیق تصمیم‌هایی که مانع Phase 1 می‌شوند.

**Gate 0:** بازبینی گزارش؛ فقط با مشخص بودن baseline و ریسک‌ها اجازه ورود به Phase 1 صادر شود.

### Phase 1 — Darsyar Brand & Web Product Shell

**هدف:** تبدیل هویت قابل مشاهده از DeepTutor به درسیار و تثبیت تجربه وب فارسی.

Scope:
- نام و برند نمایشی در Header، Login، metadata، empty/error/loading states و navigation.
- فارسی‌سازی کامل و RTL با الگوی i18n فعلی.
- طراحی responsive کاربر و layout مستقل admin.
- مسیرهای product shell؛ لینک admin فقط برای مدیر مجاز.
- Desktop از build/deploy هدف درسیار خارج شود، اما source آن تا dependency audit حذف نشود.
- حفظ Next.js App Router و قراردادهای موجود.

Acceptance:
- تمام مسیرهای اصلی روی mobile/tablet/desktop کار کنند.
- مسیرهای auth/admin در refresh و direct navigation درست باشند.
- i18n parity، lint، typecheck، architecture check و build پاس شوند.
- هیچ عبارت برند DeepTutor در UI عمومی درسیار باقی نماند، مگر در صفحه attribution/notice لازم.
- هیچ API یا data schema بدون نیاز تغییر نکند.

**Gate 1:** UI smoke tests و browser E2E مسیرهای اصلی PASS.

### Phase 2 — Identity, SMS OTP & Admin Authorization

**هدف:** ورود موبایلی امن و مدیریت واقعی کاربران.

Scope:
- طراحی phone identity و phone normalization.
- SMS provider interface + mock test provider + یک provider واقعی منتخب پس از ADR.
- OTP issue/verify/expiry/resend/attempt limits/rate limits.
- ثبت‌نام اولین ورود با OTP و تعیین رمز.
- ورود بعدی با phone/password.
- password reset با OTP.
- admin bootstrap امن؛ admin/123 فقط development و force password change.
- Admin login و server-enforced Super Admin/role guards.
- user CRUD، disable/restore، password reset، profile changes و audit log.
- تصمیم و پیاده‌سازی storage مرکزی بر اساس ADR.

Acceptance:
- تست یکتایی شماره و race condition ثبت‌نام.
- تست OTP منقضی، غلط، replay، rate limit و resend.
- تست session expiry/revocation.
- تست دسترسی horizontal/vertical escalation در REST و WebSocket.
- test اثبات اینکه non-admin هیچ admin API را حتی با فراخوانی مستقیم نمی‌تواند اجرا کند.
- هیچ OTP/password خام در DB/log/trace.
- Production با default credential بالا نمی‌آید.

**Gate 2:** امنیت auth و admin به‌طور مستقل بازبینی شود.

### Phase 3 — Product Database, Migration & Storage Foundations

**هدف:** داده تراکنشی قابل اعتماد برای سرویس چندکاربره.

Scope:
- تصمیم نهایی database/ORM/migrations.
- PostgreSQL target برای identity، academic catalog، exams، billing و audit.
- repository/service boundaries؛ مدل‌های file/JSON فعلی بی‌بررسی حذف نشوند.
- migration plan، backfill و rollback.
- object storage interface برای فایل‌ها و assets.
- worker/queue interface برای jobs طولانی.
- health/readiness/backup/restore.

Acceptance:
- migration از DB خالی و migration از fixture نسخه قبلی.
- rollback/restore drill.
- داده کاربر A از کاربر B قابل مشاهده/تغییر نباشد.
- transaction و unique constraints برای wallet/reservations/account identity.
- backup restore نتیجه قابل مقایسه ارائه دهد.
- restart worker و retry job باعث duplicate اثر نشود.

**Gate 3:** migration و recovery evidence PASS.

### Phase 4 — Academic Catalog & Source Rights

**هدف:** تعریف درخت رسمی آموزشی و ثبت کنترل‌شده منابع.

Scope:
- دوره، پایه، شاخه، رشته، درس، نسخه curriculum و سال تحصیلی.
- ابتدایی 1–6، متوسطه اول 7–9، متوسطه دوم 10–12.
- رشته‌های نظری و هنرستان با ساختار داده‌محور.
- پیش‌دانشگاهی و نظام‌های گذشته به‌صورت archive مستقل.
- انواع منبع: رسمی، کمک‌آموزشی، جزوه، نمونه سؤال، کنکور و منابع مکمل.
- metadata، versioning، provenance، checksum، rights status و review workflow.
- import catalog با provenance؛ بدون scraping یا واردکردن انبوه بدون مجوز.

Acceptance:
- آزمون‌های catalog برای رشته/درس معتبر و نامعتبر.
- آزمون جداسازی current curriculum و archive.
- duplicate detection و version history.
- منبع unreviewed/rights unknown از retrieval عمومی خارج باشد.
- admin بتواند منبع را approve/reject/archive کند و audit ثبت شود.

**Gate 4:** owner review برای taxonomy و legal provenance.

### Phase 5 — Ingestion, OCR & Grounded Tutor

**هدف:** پردازش باکیفیت کتاب‌ها و پاسخ قابل استناد.

Scope:
- PDF parsing و OCR pipeline با ماژول‌های موجود.
- استخراج chapter/section، جدول، تصویر، فرمول و page provenance.
- ingestion jobs با staging، review، retry و index version.
- source filtering اجباری بر اساس grade/track/subject/rights.
- RAG adapter برای reuse کردن pipeline موجود.
- citation renderer کوتاه: [نام کتاب | فصل].
- پاسخ خارج از منابع، abstention و conflict handling.
- dataset طلایی فارسی برای همه پایه‌های pilot.

Acceptance:
- golden tests برای بازیابی دقیق موضوع و فصل.
- no grade/track leakage در تست adversarial.
- citation validation با سند واقعی بازیابی‌شده.
- تست فارسی، اعداد، جدول، شکل، فرمول و OCR.
- query خارج از منبع به‌درستی abstain شود.
- ingestion failure/timeout/cancellation و restart recovery آزمایش شود.
- hallucinated citation در مجموعه ارزیابی صفر باشد.

**Gate 5:** ارزیابی کیفیت retrieval و مجوز محتوا قبل از pilot.

> **وضعیت (۲۰۲۶-۱۱-۱۸): پیاده‌سازی COMPLETE، Gate 5 BLOCKED.**
> همهٔ محورهای Scope پیاده شدند و همهٔ Acceptance در
> `tests/db/test_scope_isolation.py`، `test_citation.py`، `test_extraction.py`،
> `test_ingestion_pipeline.py` و `test_golden_set.py` پاس می‌شوند (۴۷۶ pass در
> `tests/db`). گزارش: `PHASE_5_INGESTION_REPORT.md`؛ تصمیم‌ها: ADR-005 و
> D-031…D-037.
>
> Gate 5 هنوز دو شرط ناتمام دارد:
> ۱. **مجوز محتوا** — سؤال Gate 4 («آیا سرو کردن کتاب‌های سازمان پژوهش مجاز
>    است؟») بی‌پاسخ است. خط لوله دروازهٔ مجوز را اکنون *اجرا* می‌کند
>    (`source_not_approved`)، اما هیچ کتاب واقعی وارد نشده.
> ۲. **ارزیابی کیفیت retrieval** — امتیازدهی فعلی واژگانی است
>    (`grounding.search`)؛ سنجش معنایی با embedding انجام نشده.
>
> تا پاسخ سؤال حقوقی، import انبوه (که ROADMAP سطر ~۱۳۷ ممنوع می‌کند) انجام
> نمی‌شود.

### Phase 6 — Exam Center & Assessment

**هدف:** اجرای آزمون تشریحی، چهارگزینه‌ای و کنکوری.

Scope:
- question bank و نسخه سؤال.
- exam blueprint، فصل/مبحث، دشواری، زمان و ترتیب.
- چهارگزینه‌ای با grading قطعی بر اساس answer key.
- تشریحی با rubric، نمره جزئی، uncertainty و human review.
- نمره منفی با policy قابل تنظیم per-exam.
- snapshot از سؤال، answer key و scoring policy.
- گزارش اشتباهات و مباحث نیازمند مرور.
- جلوگیری از نمره‌دهی قطعی به سؤال خراب/بدون کلید معتبر.

Acceptance:
- unit/property tests برای فرمول نمره و edge cases.
- پاسخ غلط، درست، نزده، سؤال بدون پاسخ و ضریب متفاوت.
- تست سه پاسخ غلط/یک پاسخ درست فقط وقتی policy مربوطه فعال است.
- تشریحی: rubric، حداقل/حداکثر نمره، اعتراض و تغییر ثبت‌شده.
- تکرار/refresh ارسال پاسخ نباید دوباره نمره یا attempt ایجاد کند.
- نمره قبلی با تغییر question bank یا policy جدید تغییر نکند.

**Gate 6:** validation آزمون با مجموعه سؤال بازبینی‌شده.

> **وضعیت (۲۰۲۶-۱۱-۱۸): پیاده‌سازی COMPLETE، Gate 6 BLOCKED.**
> همهٔ محورهای Scope پیاده شدند و همهٔ Acceptance در
> `tests/db/test_exam_scoring.py` (۴۸)، `test_exam_center.py` (۳۹) و
> `test_exam_http.py` (۲۹) پاس می‌شوند. گزارش: `PHASE_6_EXAM_REPORT.md`؛
> تصمیم‌ها: ADR-006 و D-038…D-046.
>
> Gate 6 شرط «اعتبارسنجی با مجموعهٔ سؤال بازبینی‌شده» را دارد. `validate_exam`
> آماده است و انتشار آزمون با سؤال بازبینی‌نشده را با `409` می‌بندد، اما هیچ
> مجموعهٔ سؤال واقعیِ بازبینی‌شده وجود ندارد — و سؤال از کتاب می‌آید، پس این
> به پاسخ حقوقی فاز ۴/۵ وابسته است.
>
> دو باگ که فقط اجرای زنده پیدا کرد: گزینهٔ عددی به‌جای متن خوانده می‌شد
> (نمرهٔ ۲.۰۰۰۱ به‌جای ۶.۰) و «الف» هرگز مطابقت نمی‌کرد (هر پاسخ اول از یک
> فرم فارسی بی‌سروصدا غلط شمرده می‌شد).
>
> **ترمیم (۲۰۲۶-۱۱-۱۸):** بازبینی رقابتی سه باگ دیگر پیدا کرد که هیچ‌کدام در
> آزمون‌های این فاز دیده نمی‌شدند، چون آزمون‌ها با کلاینت مؤدب نوشته شده بودند:
>
> ۱. **ارسال هم‌زمان** دو درخواست یکسان خطای ۵۰۰ می‌داد، چون خواندنِ «تلاش
>    قبلی» بیرون از تراکنش درج بود و بازنده روی ایندکس یکتایی می‌مرد. حالا
>    برخورد گرفته می‌شود و پاسخ تکراری برمی‌گردد (D-047).
> ۲. **هیچ مسیری دامنهٔ آزمون را بررسی نمی‌کرد** — دانش‌آموز پایهٔ هفت روی
>    کاغذ پایهٔ دوازدهم نمره گرفت. `services/exam/scope.py` اضافه شد؛ دامنه از
>    پروفایلِ ذخیره‌شده می‌آید و مقدار درخواست نادیده گرفته می‌شود (D-048…D-050).
> ۳. **همان حفره در فاز ۵** — `search`/`browse`/`validate` هیچ بررسی‌ای نداشتند
>    و `catalogue` با `(? IS NULL OR ...)` رشته را باز می‌کرد (D-051).
>
> گزارش: `PHASE_6_REPAIR_REPORT.md`؛ شواهد: `evidence/phase6-repair-scope.json`.
> `pytest tests/db` از ۵۹۲ به ۶۲۱ رسید. Gate 6 همچنان BLOCKED است روی محتوای
> واقعی — این ترمیم امنیت را درست کرد، نه اعتبار محتوا را.

### Phase 7 — Mastery, Flashcards & Personalized Review

**هدف:** تکمیل تجربه یادگیری شخصی و مرور.

Scope:
- ممیزی و reuse ماژول Flash Cards و Mastery.
- ساخت کارت از کتاب/فصل/منبع و اشتباهات آزمون.
- spaced repetition با تاریخچه review.
- dashboard تسلط بر فصل و مبحث.
- پیشنهاد تمرین/مرور بر اساس evidence نه صرفاً تخمین مدل.

Acceptance:
- هیچ deck/card خارج از scope کاربر ساخته/خوانده نشود.
- progress پس از restart حفظ شود.
- الگوریتم مرور deterministic test داشته باشد.
- deduplication و citation provenance.
- regression tests ماژول mastery فعلی پاس شوند.

**Gate 7:** اثبات تداوم progress و صحت جداسازی کاربران.

> **وضعیت (۲۰۲۶-۱۱-۱۸): COMPLETE — Gate 7 PASS.**
>
> ممیزی: ماژول Mastery در `deeptutor/learning/` بالغ بود (زمان‌بند FSRSمانند،
> سیاست تسلط، ذخیره‌گاه تراکنشی) و **دوباره استفاده شد**؛ ولی «Flash Cards»
> فقط یک بلوک تولید کتاب بود که کارت را در پاسخ می‌نوشت و دور می‌ریخت —
> بدون ماندگاری، dedup، provenance یا تاریخچه. پس ذخیره‌سازی از صفر ساخته شد
> (`V0009`) و زمان‌بندی به همان زمان‌بند موجود واگذار شد.
>
> پذیرش‌ها: هیچ deck/card خارج از scope (۸ آزمون)؛ پیشرفت پس از restart با
> **دو اثبات مستقل** (پروسهٔ جدا روی فایل، و کشتن و بالا آوردن دوبارهٔ سرور)؛
> الگوریتم deterministic چون `now` پارامتر است نه خواندن ساعت؛ dedup با
> ایندکس یکتایی و `content_key` نرمال‌شده؛ provenance روی هر کارت؛ آزمون‌های
> mastery فعلی دست‌نخورده و سبز.
>
> ۱۵ مسیر زیر `/api/flashcards`؛ ۸۱ آزمون تازه. `pytest tests/db` از ۶۲۱ به
> ۷۰۴؛ کل مجموعه **۱۴۶۵۹ گذشت** با ۱ شکست محیطی شناخته‌شده.
> گزارش: `PHASE_7_REVIEW_REPORT.md`؛ تصمیم‌ها: D-052…D-058؛ شواهد:
> `evidence/phase7-review-baseline.json`.
>
> سه باگ در حین کار: گزینه‌های snapshot متنِ خط‌جداشده‌اند نه لیست (`ت` به‌جای
> `تهران`)؛ روتر تازه از ماژول `server` به `deeptutor.learning` وابسته شده بود
> که `tests/modules` گرفتش؛ و یک پیش‌نویس scope که پایهٔ آزمون را به‌جای پایهٔ
> فراخوان پاس می‌داد.
>
> **آنچه انجام نشد:** رابط کاربری؛ و کارت از فصل واقعی کتاب، که به پاسخ حقوقی
> فاز ۴/۵ گره خورده است. Gate 5 و 6 همچنان BLOCKED.

### Phase 8 — Learning Studio & Media Jobs

**هدف:** فراهم‌کردن خروجی‌های آموزشی چندرسانه‌ای.

Scope:
- فعال‌سازی و فارسی‌سازی Audio Overview و Video Lesson.
- تولید slide، mind map و infographic در اولویت‌های جداگانه.
- job queue، cancellation، retry limit، quota و asset library.
- source-aware script/output و provenance.
- cache/reuse محتوا در صورت یکسان بودن scope و مجوز.
- cost measurement برای token و non-token operations.

Acceptance:
- mock-provider integration tests و یک مسیر واقعی controlled smoke test.
- job state transitions و recovery پس از worker restart.
- عدم اجرای job بدون entitlement/quota/authorization.
- فایل asset فقط برای مالک یا مجاز قابل دریافت باشد.
- مصرف job قابل ردیابی و settle/refund صحیح باشد.
- خطای ویدئو/صوت chat عادی را مختل نکند.
- کیفیت فارسی با checklist انسانی ارزیابی شود.

**Gate 8:** هزینه، کیفیت، rights و capacity به‌صورت مستند پذیرفته شوند.

> **وضعیت (۲۰۲۶-۱۱-۱۶): تکمیل شد — مکانیزم، خروجی واقعی، و تضمین‌های سطح
> جدول. Gate 8 هنوز پذیرفته نشد.**
>
> پیش از این فاز تولید رسانه از صف، سهمیه، مالکیت و حسابداری عبور نمی‌کرد.
> فاز ۸ آن را به زنجیرهٔ «entitlement → سهمیه → hold → صف → اجرا →
> settle/refund → دارایی» تبدیل کرد.
>
> فرض بنیادی: `user_wallets` قید `CHECK (tokens_remaining = tokens_total -
> tokens_used)` دارد، پس hold **نمی‌تواند** داخل کیف پول نوشته شود؛ جدول
> `media_reservations` ساخته شد و موجودی قابل استفاده یک محاسبهٔ اتمیک است
> (D-059). لایسنس داخل کلید کش آمد (D-060) و کش per-user است (D-061). شکست
> غیرنهایی hold را آزاد نمی‌کند (D-062). هزینهٔ غیرتوکنی بدون نرخ اختراعی
> ثبت می‌شود (D-063).
>
> **پاس دوم — خروجی واقعی.** `render.py` با Pillow و `wave` artefact واقعی
> می‌سازد: PNG فارسی درست‌شکل و WAV با طول واقعی. شکل‌دهی فارسی اجباری است و
> بدون `arabic-reshaper`/`python-bidi` renderer **امتناع** می‌کند (D-072).
> `V0011` اشتراک‌گذاری صریح را آورد (D-067…D-069). **باگ افزایش سطح دسترسی
> پیدا شد:** عملیات مالک‌محور از `get_asset` استفاده می‌کردند و گیرنده
> می‌توانست دارایی مالک را حذف کند (D-066). worker مستقل اضافه شد (D-074).
>
> **پاس سوم — سه شکافی که «تمام‌شده» را از «درست» جدا می‌کرد.** این‌ها با
> آزمودن ادعاها پیدا شدند، نه با خواندن کد:
>
> - **مجوز می‌توانست خالی باشد.** ردیفی که می‌گفت از کدام منبع آمده و هیچ
>   نمی‌گفت با چه حقی. اکنون `licence_required` است، و **نه فقط در سرویس**:
>   دو trigger سطح جدول در زمان راه‌اندازی نصب می‌شوند، پس `INSERT` خامی که
>   تمام سرویس را دور می‌زند هم مسدود است. چرا trigger و نه `CHECK`؟ SQLite
>   نمی‌تواند `CHECK` را به جدول موجود اضافه کند، و قطعه‌کنندهٔ دستورات این
>   پروژه بدنهٔ `BEGIN ... END` را نمی‌فهمد — **این را با آزمون کشف کردم**
>   (اولین نسخه با `incomplete input` شکست)، نه با فرض (D-078).
> - **حذف، شمارنده را صفر می‌کرد و فایل را نگه می‌داشت.** بدتر از حذف نکردن:
>   سهمیه می‌گفت فضا آزاد است، دیسک می‌گفت نه. اکنون اول بایت‌ها، بعد
>   شمارنده، آخر ردیف (D-076). **اثبات:** سه چرخهٔ ساخت/حذف، دیسک
>   ۱٬۰۵۵٬۲۳۶ بایت — صفر رشد.
> - **checklist پرکردنی نبود.** «کیفیت ارزیابی شد» فقط می‌توانست یعنی «معیار
>   نوشتیم». `media_quality_reviews` اضافه شد با داوری سه‌مقداری
>   (`pass`/`fail`/`unclear`) و تفکیک مهم: خودداوری «کامل» شمرده می‌شود ولی
>   **مستقل** نه (D-077).
>
> پذیرش‌هایی که **انجام شد:** ۱۴۹ آزمون تازه با **یازده شاهد جهش**؛ سه
> مایگریشن با بالا و پایین اثبات‌شده؛ دو فرایند واقعی (API روی `:3851` و
> worker جدا)؛ بازیابی پس از مرگ worker (lease منقضی → reclaim → یک دارایی،
> یک settle، صفر hold نشتی)؛ شکست عمدی job که worker را نکشت؛ و زنجیرهٔ
> کامل دسترسی/حذف/داوری از راه HTTP واقعی.
>
> **یافتهٔ غیرمنتظره:** اندازه‌گیری با خروجی واقعی نشان داد تخمین‌های
> `DEFAULT_ESTIMATES` بین ۲۰ تا ۵۰ برابر بیش‌برآورد بودند (D-073). اگر Gate 8
> را بر پایهٔ آن جدول می‌پذیرفتیم، عددی را پذیرفته بودیم که بیش از یک مرتبهٔ
> بزرگی غلط است.
>
> **پاس چهارم — چهار ستون Gate 8، یکی‌یکی.**
>
> | ستون | وضعیت | چه چیزی بسته شد | چه چیزی بسته نشد |
> |---|---|---|---|
> | **rights** | ✅ اجرا شد | مجوز = مجموعهٔ اختیارات؛ `citation-only` برای هر پنج kind **رد** می‌شود، `cc-by` برای همه پذیرفته؛ attribution روی خودِ PNG سوزانده می‌شود | «آیا ما واقعاً آن مجوز را داریم؟» — سؤال انسانی، Gate 5/6 |
> | **cost** | ✅ شمارش + قیمت | tokenizer واقعی cl100k؛ **۴۲ میکرودلار بر درس**، ۴.۲ سنت بر هزار درس — از نرخ منتشرشدهٔ provider | completion واقعی: `openrouter.ai` از این sandbox در TLS بسته است. رقم از «توکن × نرخ» می‌آید، نه از فاکتور |
> | **capacity** | ✅ سنجیده شد | ۱۲۰ job، صفر خطا؛ throughput ۷۵–۸۶/s؛ حافظه ۱۰MB؛ **گلوگاه SQLite است نه رندر** (p50: ۱۳ms → ۲۵۳ms) | rate limit provider و throughput GPU: قابل اندازه‌گیری نبود |
> | **quality** | ❌ **باز** | مکانیزم ثبت داوری موجود است | `independent_reviews = 0`. داوری که خودم دربارهٔ خروجی خودم بنویسم، گیت نیست |
>
> **آنچه در این پاس کشف شد، نه ساخته شد:**
>
> - **عدد هزینه غلط بود.** اولین شمارش `len(text) // 4` بود — قاعدهٔ انگلیسی.
>   با cl100k واقعی سنجیده شد: روی فارسی ۶۰٪ کم‌شمارش. دلیل ساختاری است:
>   فارسی بدون مصوت کوتاه نوشته می‌شود، پس واژه کوتاه است، ولی cl100k برای
>   خط عربی merge ندارد — یک واژهٔ ۴ حرفی ~۳.۵ توکن است (D-081).
> - **یک آزمون از قبل موجود، ایراد را در registry پیدا کرد.** `all-rights`
>   — واژه‌ای که هر کاربری برای کتاب خودش می‌زند — «کد ناشناخته» برمی‌گرداند.
>   ثبتش کردم؛ درس: وقتی قید جدید آزمون قدیمی را می‌شکند، دو احتمال است و
>   «بستن آزمون» با «شنیدنش» فرق دارد (D-084).
> - **retry توکن را نگه می‌دارد** — تا ۱۴ ثانیه backoff. این انتخاب درست است
>   (refund زودتر یعنی retry چیزی برای تسویه ندارد) ولی هزینه‌اش حالا نوشته
>   شده است، نه پنهان (D-083).
>
> **پاس پنجم — قیمت، و سقفی که «رایگان» را بی‌معنا می‌کند.** کلید OpenRouter
> و مدل `nvidia/nemotron-3.5-super-vl:free` داده شد. نتیجه در سه لایه:
>
> ۱. **کد اتصال درست است.** با یک stand-in محلی که همان قرارداد OpenAI را دارد:
>    مسیر `/api/v1/chat/completions`، هدر `Bearer`، و ارسال مدل با `:free` —
>    همه تأیید شد. ریپو از قبل gateway `openrouter` را دارد و کلید را از پیشوند
>    `sk-or-` تشخیص می‌دهد.
> ۲. **قیمت واقعی است.** نرخ‌ها از کاتالوگ عمومی provider خوانده شد، با تاریخ.
>    هشت endpoint پرداختی بین ۶e-۸ و ۱.۸۳e-۶ دلار بر توکن، و یکی صفر.
>    **۴۲ میکرودلار برای یک درس؛ ۴.۲ سنت برای هزار درس.**
> ۳. **completion واقعی اجرا نشد.** `openrouter.ai` از این sandbox در لایهٔ TLS
>    بسته است — DNS حل می‌شود، TCP وصل می‌شود، handshake قطع می‌شود؛ حتی HTTP
>    ساده. `github.com` و `pypi.org` بازِ‌اند، پس فیلتر گزینشی است.
>
> **یافته‌ای که فقط با خواندن سقف‌ها پیدا شد:** مدل `:free` واقعاً صفر است، ولی
> ۲۰ درخواست در دقیقه و **۵۰ درخواست در روز** (۱۰۰۰ اگر ۱۰ دلار اعتبار بخرید).
> یعنی ظرفیت ۸۶ job/ثانیهٔ این host با طرح رایگان **بی‌معنا** است: گلوگاه
> **۵.۸ درس در ساعت** است. اگر فقط «رایگان است» را گزارش می‌کردیم، یک
> نتیجه‌گیری غلط تحویل داده بودیم. (D-085، D-086، D-087)
>
> **پاس ششم — بستهٔ داوری، و سه نقصی که فقط با نگاه کردن پیدا شد.**
>
> برای بستن ستون quality، اول باید چیزی وجود داشته باشد که کسی بتواند داوری
> کند. `scripts/build_review_package.py` می‌سازد: پنج اثر واقعی، یک
> `review.html` که **بدون اینترنت** کار می‌کند، و `load_verdict.py` که داوری را
> از راه همان `record_review` ثبت می‌کند. حلقه با اجرا اثبات شد: خودداوری
> `independent=0`، داوری مستقل `independent=7`.
>
> **ولی پیش از تحویل بسته، خروجی‌ها را باز کردم و سه چیز غلط بود:**
>
> - هر اسلاید اولین خط بدنه را به‌عنوان عنوان تکرار می‌کرد، پس ویدیو سه بار
>   خودش را با «در این ویدیو یاد می‌گیریم» معرفی می‌کرد؛
> - شاخه‌های نقشهٔ ذهنی پرتکرارترین **کلمات** بودند: «مشتق / قاعده / نمودار /
>   نرخ / تغییر» — تکه‌های جمله، نه مفهوم؛
> - وقتی شاخه‌ها عبارت شدند، چیدمان با شعاع ثابت آن‌ها را روی hub انداخت و متن
>   موضوع را پوشاند.
>
> هر سه رفع و با چشم بازرندر تأیید شدند. **اگر بسته را با آن نقص‌ها تحویل
> می‌دادم، از یک انسان می‌خواستم چیزی را داوری کند که خودم می‌دیدم غلط است.**
>
> **و سه آزمون از چهار آزمون تازه، با جهش زنده ماندند** — چون تابع را مستقیم
> صدا می‌زدند و مسیر واقعی را نه. بازنویسی شدند و حالا هر چهار گرفته می‌شوند.
> این سومین بار در این فاز است که آزمونم از آزمونِ کد ضعیف‌تر بود.
>
> **آنچه هنوز باز است — یک چیز، و در کد نیست:** یک **بازبین فارسی‌زبان مستقل**.
> ابزار آماده است و کار او به «باز کردن یک فایل HTML» کاهش یافته، ولی خودِ
> داوری را نمی‌توانم انجام دهم: داوری که دربارهٔ خروجی خودم بنویسم، گیت نیست.
> چهار نقص شناخته‌شده هم در README بسته به بازبین گفته شده تا آن‌ها را کشف
> نکند — کشفشان کار او نیست، **تأییدشان** هست. برای بستن ستون cost به‌معنای
> کامل (فاکتور به‌جای محاسبه)، یک اجرای واقعی روی host با egress باز لازم است.
>
> **Gate 8: سه ستون از چهار بسته شد — cost اکنون قیمت دارد نه فقط شمارش، و
> quality ابزار داوری دارد که حلقه‌اش اثبات شده است. ستون quality با یک انسان
> بسته می‌شود، نه با کد — و آن انسان اکنون فقط باید یک فایل HTML باز کند.**

### Phase 9 — Plans, Billing, Custom AI & Production Readiness

**هدف:** تکمیل مدل تجاری و آماده‌سازی انتشار.

Scope:
- plans, subscriptions, entitlement engine.
- usage ledger مرکزی و قیمت‌گذاری نسخه‌دار.
- transactional reserve/settle/refund.
- Custom AI Provider UI/API و routing برای هر capability.
- secret encryption، rotation، SSRF/egrss policy.
- پرداخت/تمدید تنها پس از انتخاب درگاه و ADR مستقل.
- admin reporting و cost/profit views.
- performance, security, backup, restore, deployment runbooks.

Acceptance:
- تست exactly-once/idempotency برای ledger و wallet.
- تست provider actual vs estimated usage.
- تست refund و failure cases.
- تست عدم افشای API key در browser/network/log.
- تست SSRF برای localhost، private IP، metadata endpoint و redirect.
- load test ترکیبی chat + ingest + media jobs.
- security review و backup/restore drill.
- migration و rollback روی staging.
- deployment smoke test و monitoring alerts.

**Gate 9:** انتشار Production فقط با شواهد کامل، secrets واقعی امن، rights approved و owner acceptance مجاز است.

---

## قالب گزارش پایان هر فاز

هر گزارش باید شامل:
1. Phase و scope.
2. baseline commit و branch.
3. فایل‌های تغییرکرده و دلیل ownership.
4. تصمیم‌ها و ADRهای ایجاد/تغییر یافته.
5. تست‌ها: command، exit code، تعداد PASS/FAIL/SKIP و log reference.
6. مواردی که تست نشده‌اند یا external service لازم دارند.
7. migration/rollback evidence.
8. security/privacy/rights considerations.
9. known issues و ریسک باز.
10. نتیجه Gate: PASS / FAIL / BLOCKED.
11. commit SHA و مسیر branch؛ push/merge فقط مطابق اختیار صریح کارفرما.

## Definition of Done

فاز فقط وقتی COMPLETE می‌شود که scope کامل، acceptance criteria پاس، regression tests پاس، docs به‌روز، migration قابل بازیابی، گزارش مستند و هیچ blocker بحرانی حل‌نشده باقی نمانده باشد.


---

## Phase 1 — تصمیم‌های مصوب صاحب محصول (2026-11-17)

این بخش تکمیل‌کننده دامنه Phase 1 است و بر توضیحات کلی قبلی اولویت دارد.

### ترتیب اجرایی

**1.0 — R-12 import-time configuration fix**
- فقط refactor لازم برای حذف import-time crash در `co_writer.py`.
- رفتار با config معتبر بدون تغییر بماند.
- تست import در runtime home تازه و بدون `deeptutor init` + تست مسیر initialized.
- commit مستقل و گزارش تست مستقل.

**1.1 — Font foundation**
- self-host کردن Vazirmatn Variable و فونت‌های محلی موردنیاز.
- افزودن متن license و attribution فونت.
- حذف وابستگی `next/font/google` و درخواست شبکه در build.
- production build واقعی باید از شبکه Google Fonts مستقل شود.

**1.2 — i18n فارسی**
- افزودن locale key `fa` به‌عنوان زبان چهاردهم.
- استفاده از `fa-IR` برای formatting و document language.
- تکمیل کلیدها با parity؛ متن‌های ناقص/انگلیسی در جریان‌های اصلی قابل پذیرش نیستند.

**1.3 — RTL کامل**
- ابتدا locale و direction metadata، سپس تبدیل کلاس‌های فیزیکی به logical properties.
- ترتیب i18n پیش از RTL codemod حفظ شود.
- بصری در موبایل، تبلت و دسکتاپ تست شود.

**1.4 — Darsyar branding**
- نام نمایشی و metadata قابل مشاهده به درسیار تغییر کند.
- Python package/import namespace، CLI و runtime internals تغییر نام ندهند.
- attribution مجوز و upstream حفظ شود.

**1.5 — Functional login presentation**
- مسیر `/login` و flow فعلی username/password حفظ شود.
- ظاهر و برند بازطراحی شود؛ ورود OTP تا Phase 2 خارج از scope است.

**1.6 — Full web shell**
- Shell کامل کاربر و admin طبق `DECISIONS.md` بخش F-1.
- قابلیت‌های موجود reuse شوند؛ برای قابلیت‌های آینده placeholder شفاف استفاده شود.
- مسیر `/admin/login` و `/admin` مستقل بمانند؛ احراز هویت/نقش از قرارداد موجود استفاده کند و API ساختگی ایجاد نشود.

**1.7 — Gate 1**
- اجرای contracts، architecture، typecheck، Node tests، Vitest، lint، i18n checks و build.
- تست browser E2E برای login، refresh/direct route، non-admin redirect، admin navigation و responsive shell.
- Build باید با فونت‌های self-host و بدون دسترسی Google Fonts PASS شود.
- هیچ لینک مرده، action ظاهری بدون رفتار، secret در browser یا regression در مسیرهای فعلی پذیرفته نیست.

### خارج از Phase 1

SMS/OTP، تغییر storage هویت به PostgreSQL، Academic Catalog و import کتاب‌ها، rights workflow، grade/track RAG enforcement، Exam domain/negative marking، wallet/subscription واقعی و media job queue در فازهای بعدی ROADMAP باقی می‌مانند. Phase 1 حق ندارد placeholderها را به‌عنوان قابلیت تکمیل‌شده معرفی کند.

### Gate 0 disposition

Gate 0 = **ACCEPTED CONDITIONAL PASS** برای شروع Phase 1، با شرایط خط پایه ثبت‌شده در DECISIONS.md بخش F-3. این پذیرش به معنی عبور از Gateهای Phase 1 تا 9 یا Production approval نیست.
