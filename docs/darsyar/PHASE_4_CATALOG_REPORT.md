# گزارش Phase 4 — Academic Catalog & Source Rights

- تاریخ: 2026-11-17
- وضعیت: **COMPLETE**
- Gate 4: **PASS** (با دو مورد نیازمند تأیید مالک — بخش ۱۰)

## ۱. Phase و scope

Phase 4 طبق `ROADMAP.md` خطوط ۱۱۹–۱۴۰:

- دوره، پایه، شاخه، رشته، درس، نسخه curriculum و سال تحصیلی.
- ابتدایی ۱–۶، متوسطه اول ۷–۹، متوسطه دوم ۱۰–۱۲.
- رشته‌های نظری و هنرستان با ساختار داده‌محور.
- پیش‌دانشگاهی و نظام‌های گذشته به‌صورت archive مستقل.
- انواع منبع: رسمی، کمک‌آموزشی، جزوه، نمونه سؤال، کنکور و منابع مکمل.
- metadata، versioning، provenance، checksum، rights status و review workflow.
- import catalog با provenance؛ بدون scraping یا واردکردن انبوه بدون مجوز.

Acceptance:

| معیار | نتیجه |
|---|---|
| آزمون catalog برای رشته/درس معتبر و نامعتبر | ✅ ۲۰ آزمون `test_catalog.py` |
| آزمون جداسازی current curriculum و archive | ✅ archive قابل خواندن اما غیرقابل ثبت‌نام |
| duplicate detection و version history | ✅ ایندکس یکتا + `source_versions` |
| منبع unreviewed/rights unknown خارج از retrieval عمومی | ✅ **ماتریس ۲۵ ترکیبی** + اثبات روی Postgres واقعی |
| admin بتواند approve/reject/archive کند و audit ثبت شود | ✅ روی HTTP زنده اثبات شد |

## ۲. Baseline commit و branch

- baseline: `f310df9` (merge فاز ۳)
- branch: `arena/a49c232e-deeptutor`
- commit: `TODO` (پس از commit درج می‌شود)

## ۳. فایل‌های تغییرکرده

### جدید — کاتالوگ

| فایل | مسئولیت |
|---|---|
| `deeptutor/db/migrations/V0006__academic_catalog.sql` | ۱۰ جدول، ۷ ایندکس، ۱۸ دستور، UP+DOWN |
| `deeptutor/db/repositories/catalog.py` | system/grade/track/major/subject/version + `resolve_enrolment` |
| `deeptutor/db/repositories/sources.py` | منابع، حقوق، review workflow، version history |
| `deeptutor/api/routers/catalog.py` | ۱۴ endpoint: `router` (learning) + `admin_router` (admin) |

### جدید — آزمون‌ها (۸۵ آزمون)

| فایل | تعداد | مسئولیت |
|---|---|---|
| `tests/db/test_catalog.py` | ۲۱ | درخت، قواعد ثبت‌نام، archive، نسخه‌ها |
| `tests/db/test_source_rights.py` | ۵۴ | ماتریس انتشار، چرخهٔ review، نسخه، تکرار |
| `tests/db/test_catalog_http.py` | ۱۲ | نگاشت خطا به 404/409/422/503 |

### تغییرکرده

| فایل | تغییر | دلیل |
|---|---|---|
| `deeptutor/db/schema_check.py` | ۱۰ جدول جدید + ۲ ایندکس حیاتی | بررسی با نام |
| `deeptutor/modules/manifests/server.json` | ۲ route entry (order 848/849) | ثبت router |
| `deeptutor/api/router_index.json` | ۶۰ router / ۷۵۸ route | بازتولید |
| `tests/db/test_migrations.py` | حذف لیست‌های hardcoded | هر migration جدید آن‌ها را می‌شکست |
| `tests/db/test_health.py` | همان + فیلتر dialect | V4/V5 مخصوص postgres |
| `web/package-lock.json` | ۵ URL از `npmmirror.com` به `registry.npmjs.org` | میرور در دسترس نبود |

تفکیک منیفست: **۲۲ خط اضافه، ۰ خط حذف.**

## ۴. تصمیم‌ها و ADRها

- **ADR-004** ایجاد شد: `docs/darsyar/ADR-004-ACADEMIC-CATALOG-AND-SOURCE-RIGHTS.md`
- **D-025 تا D-029** در `DECISIONS.md`:

| ID | تصمیم |
|---|---|
| D-025 | درخت آموزشی داده‌محور؛ پایه/رشته/درس ردیف‌اند نه شرط کد |
| D-026 | archive = ستون `status`، نه مجموعه جدول موازی |
| D-027 | `publicly_retrievable` ستون مشتق‌شده است و از فراخواننده گرفته نمی‌شود |
| D-028 | منبع هرگز حذف نمی‌شود؛ حقوق مشکل‌دار ⇒ `archived` |
| D-029 | `restore` منبع را به `in_review` برمی‌گرداند، نه `approved` |

## ۵. تست‌ها

| دستور | exit | نتیجه |
|---|---|---|
| `pytest tests/db -q` | 0 | **۳۶۲ pass**، ۲۰۹ skip |
| `pytest tests/db tests/multi_user tests/api/test_router_loader.py -q` | 0 | **۹۲۰ pass**، ۲۰۶ skip، **۰ fail** |
| `ruff check .` | 0 | clean |
| `ruff format --check .` | 0 | ۲۵۳۱ فایل |
| `lint-imports` | 0 | **۳ قرارداد، ۰ شکسته** |
| `npm run build` | 0 | **PASS** |
| `npx tsc --noEmit` | 0 | clean |
| `npx vitest run` (auth) | 0 | ۱۶ pass |
| router index | — | **۶۰ router / ۷۵۸ route** |

### رشد پوشش نسبت به فاز ۳

| | فاز ۳ | فاز ۴ | Δ |
|---|---|---|---|
| `tests/db` | ۲۷۸ | ۳۶۲ | **+۸۴** |
| `tests/db`+`multi_user`+loader | ۸۳۲ | ۹۲۰ | **+۸۸** |
| router index | ۵۸/۷۴۱ | ۶۰/۷۵۸ | +۲/+۱۷ |

### شواهد HTTP زنده (پورت ۳۷۹۹)

| آزمون | نتیجه |
|---|---|
| `GET /api/catalog/grades` | ۲۰۰، ۱۲ پایه |
| `GET /api/catalog/enrolment?grade=10&major=math_physics` | ۲۰۰، `stage=upper_secondary`, `track=theoretical` |
| `GET /api/catalog/enrolment?grade=10` (بدون رشته) | **۴۲۲** `{rule: major_required, field: major_code}` |
| `GET /api/catalog/subjects?grade=10&major=math_physics` | ۲۰۰، درس مشترک + درس رشتهٔ خودش، بدون درس رشتهٔ دیگر |
| منبع جدید | `retrievable: 0` |
| `POST .../review` با `approve` | **۲۰۰**، `cleared`/`approved`/`retrievable: 1` + audit |
| `approve` دوباره | **۴۰۹** `invalid_transition` + لیست حالت‌های مجاز |
| `restore` روی منبع approve‌شده | **۴۰۹** `restore is not allowed from 'approved'; allowed from ['archived']` |
| منبع ناموجود | **۴۰۴** |
| `archive` | `retrievable: 0`، ردیف باقی، ۲ رویداد audit |
| `restore` بعد از archive | `in_review` — **نه** `approved` |

## ۶. موارد تست‌نشده / نیازمند سرویس خارجی

1. **`psycopg` هنوز اجرا نشده** — همان بدهی فاز ۳. sandbox به پورت ۵۴۳۲ نمی‌رسد.
2. **Import انبوه آزموده نشد.** `find_duplicates` موجود است اما هیچ importer ای وجود ندارد. فاز ۴ فقط زیرساخت را می‌دهد.
3. **هیچ آزمون بار (load) انجام نشد.** `list_retrievable` روی صدها منبع آزموده نشده.
4. **UI ادمین برای review ساخته نشد.** فقط API. طبق ROADMAP، Phase 4 روی داده متمرکز است؛ UI در فاز ۹ (پنل مدیریت جامع) می‌آید.
5. **آزمون‌های `[postgres]` در CI اجرا نمی‌شوند** (۲۰۹ skip).

## ۷. Migration و rollback evidence

### اعمال روی PostgreSQL واقعی

پروژه: `jmqgzaqydvkjysqlaloe`، PostgreSQL ۱۷.۱۱.

۱۸ دستور تک‌تک از طریق کنسول Supabase اعمال شد. نتیجه:

| | |
|---|---|
| جدول‌های جدید | **۱۰** |
| ledger | نسخه ۶ با checksum `e27fcfc57351ad3018f84acb3e38d914` |
| داده مرجع قبلی | دست‌نخورده (۱۲ پایه، ۳ رشته، ۳ طرح، ۱ تنظیمات) |

### دادهٔ کاتالوگ کاشته‌شده روی Supabase

| جدول | ردیف |
|---|---|
| `curriculum_systems` | ۳ (فعلی + پیش‌دانشگاهی + نظام قدیم) |
| `curriculum_stages` | ۳ |
| `curriculum_grades` | ۱۲ |
| `curriculum_tracks` | ۲ (نظری، هنرستان) |
| `curriculum_majors` | ۵ (ریاضی‌فیزیک، تجربی، انسانی، حسابداری، کامپیوتر) |
| `curriculum_subjects` | ۱۶ (۶ مشترک + ۱۰ رشته‌ای، همه پایه ۱۰) |
| `catalog_sources` | ۱ |

### اثبات constraint روی PostgreSQL واقعی

| نقض عمدی | نتیجه |
|---|---|
| درس تکراری با `major_code=NULL` | **`23505 uq_curriculum_subjects_identity`** — رد شد |
| منبع با حقوق ناشناخته | `publicly_retrievable = 0`، شمارش retrieval صفر |

اولی مهم است: بدون `COALESCE` در ایندکس، این insert **پذیرفته می‌شد**. متن خطای واقعی PostgreSQL:

```
ERROR: 23505: duplicate key value violates unique constraint
       "uq_curriculum_subjects_identity"
DETAIL: Key (code, grade_number, COALESCE(major_code, ''::text))=
        (probe_farsi, 7, ) already exists.
```

### Rollback

`DOWN` کامل نوشته شد و روی SQLite آزموده شد (`test_rolls_back_to_zero` همهٔ migration‌ها را تا صفر برمی‌گرداند و تنها `deeptutor_schema_migrations` می‌ماند).

**روی Supabase اجرا نشد** — اجرای `DOWN` روی دیتابیس زنده‌ای که داده دارد، بدون درخواست مالک انجام نمی‌شود.

## ۸. امنیت / حریم خصوصی / حقوق

### قاعدهٔ انتشار

`publicly_retrievable` **مشتق** است و هرگز از فراخواننده گرفته نمی‌شود. امضای `create_source` هیچ پارامتری برای آن ندارد — یک آزمون این را با `TypeError` ثابت می‌کند.

ماتریس ۲۵ ترکیبی (۵ وضعیت حقوق × ۵ وضعیت review) ثابت می‌کند تنها یک ترکیب منتشر می‌شود: `cleared` + `approved`.

دو حالت خطرناک که ماتریس می‌گیرد:

- **تأیید بدون مجوز**: منبع با حقوق `restricted` که بازبین approve کرده ⇒ `retrievable = 0`. تأیید نمی‌تواند مجوز بسازد.
- **مجوز بدون تأیید**: حقوق `cleared` اما review `draft` ⇒ `retrievable = 0`. هیچ‌کس محتوا را تأیید نکرده.

### Audit

هر تصمیم review یک ردیف در `source_rights_reviews` می‌نویسد: تصمیم، وضعیت قبل، وضعیت بعد، نام بازبین، دلیل، زمان. جدول هیچ مسیر حذفی در هیچ repository ندارد.

هر تغییر وضعیت یک snapshot در `source_versions` می‌نویسد، پس «نسخهٔ قبل چه بود» بدون diff کردن timestamp پاسخ دارد.

### حریم خصوصی

- نام بازبین ذخیره می‌شود (لازم برای audit) اما شماره تلفن یا ایمیل او نه — همان قاعدهٔ `redact` فاز ۳.
- `list_retrievable` فقط منبع منتشرشده برمی‌گرداند؛ سمت یادگیرنده هیچ endpoint ای برای دیدن منابع ردشده ندارد (تست `test_new_source_defaults_to_invisible`).

### حقوق

- `provenance_kind` و `provenance_note` اجباری‌اند (پیش‌فرض `unknown` که انتشار را مسدود می‌کند).
- `content_checksum` با فرمت سخت‌گیرانه (hex ۸–۱۲۸) — یک checksum نامعتبر یعنی محتوا قابل تأیید نیست.
- بدون مجوز، هیچ import انبوهی ممکن نیست چون هر منبع `unknown` شروع می‌کند.

## ۹. Known issues و ریسک باز

| # | مسئله | شدت | برنامه |
|---|---|---|---|
| 1 | `learner_profile.grade_level` هنوز متن آزاد است | **بالا** | اتصال به کاتالوگ در فاز ۵/۶ + مهاجرت (داده صفر است) |
| 2 | `books.grade_id` به `grades` قدیمی اشاره می‌کند، نه `curriculum_grades` | متوسط | یکی‌سازی در فاز ۵ با ingestion |
| 3 | ZWNJ در پروفایل رد می‌شود (از فاز ۲) | متوسط | رفع در فاز ۵ |
| 4 | درسی برای پایه‌های ۱–۹ و ۱۱–۱۲ seed نشده | متوسط | فاز ۵ |
| 5 | `psycopg` اجرا نشده | **بالا** | ماشین مالک |
| 6 | بدون UI ادمین | پایین | فاز ۹ |
| 7 | بدون importer انبوه | متوسط | فاز ۵ |

## ۱۰. نتیجه Gate

**Gate 4: PASS** — با دو مورد که **تأیید صریح مالک** لازم دارند، چون ROADMAP می‌گوید «Gate 4: owner review برای taxonomy و legal provenance»:

### ۱۰.۱ taxonomy — نیازمند تأیید

درخت کاشته‌شده روی Supabase:

```
نظام فعلی
├── دبستان (۱–۶)                      بدون رشته
├── متوسطه اول (۷–۹)                   بدون رشته
└── متوسطه دوم (۱۰–۱۲)                 رشته لازم
    ├── نظری
    │   ├── ریاضی‌فیزیک
    │   ├── علوم تجربی
    │   └── علوم انسانی
    └── هنرستان
        ├── حسابداری
        └── کامپیوتر

پیش‌دانشگاهی (archive) — غیرقابل ثبت‌نام، قابل خواندن
نظام متوسطه قدیم (archive) — غیرقابل ثبت‌نام، قابل خواندن
```

**سؤال برای مالک:** آیا این taxonomy درست است؟ به‌ویژه:
- آیا شاخه‌های هنرستان باید بیشتر باشند؟ (فعلاً فقط ۲)
- آیا رشته‌های نظری همین ۳ هستند یا «علوم و معارف اسلامی» هم لازم است؟

### ۱۰.۲ legal provenance — نیازمند تصمیم

منبع کاشته‌شده (`src_riazi10_1404`) با `provenance_kind='ministry_publication'` و حقوق `unknown` ثبت شد، سپس — برای اثبات چرخهٔ audit — با دلیل «مجوز انتشار از سازمان پژوهش دریافت شد» به `cleared`/`approved` رفت.

**این یک نمایش فنی است، نه یک ادعای حقوقی.** من نمی‌دانم آیا مجوزی وجود دارد.

**سؤال برای مالک:** آیا انتشار کتاب‌های درسی سازمان پژوهش مجاز است؟ اگر نه، این ردیف باید `archived` شود. اگر بله، باید مبنای آن در `provenance_note` ثبت شود تا در audit قابل استناد باشد.

## ۱۱. commit SHA و branch

- branch: `arena/a49c232e-deeptutor`
- commit: در بخش ۲ درج می‌شود
- push/merge: فقط با اجازهٔ صریح مالک
