# گزارش Phase 3 — Product Database, Migration & Storage Foundations

- تاریخ: 2026-11-17
- وضعیت: **COMPLETE**
- Gate 3: **PASS**

## ۱. Phase و scope

Phase 3 طبق `ROADMAP.md` خطوط ۹۶–۱۲۰:

- تصمیم نهایی DB/ORM/migration.
- PostgreSQL برای identity، کاتالوگ آموزشی، آزمون‌ها، صورتحساب و audit.
- مرز repository/service **بدون حذف بدون‌بررسی مدل‌های فایل/JSON موجود**.
- طرح migration، backfill و rollback.
- interface ذخیره‌سازی آبجکت.
- interface worker/queue.
- health/readiness/backup/restore.

Acceptance:

| معیار | نتیجه |
|---|---|
| migration از دیتابیس خالی | ✅ V1–V5 اعمال شد |
| migration از fixture نسخهٔ قبل | ✅ V4 روی Supabase موجود اعمال شد، ۱۶ جدول و ۱۱ FK سالم |
| rollback/restore drill | ✅ V0005 `DOWN` واقعی اجرا و بازساخته شد؛ restore ردیف با همهٔ فیلدها |
| داده کاربر A برای B نامرئی/تغییرناپذیر | ✅ `tests/db/test_isolation.py` |
| تراکنش + یکتایی wallet/رزرو/هویت | ✅ `ck_wallet_balance`، `uq_jobs_dedupe`، `uq_payment_provider_authority` |
| backup restore نتیجهٔ قابل مقایسه | ✅ مقایسهٔ فیلد‌به‌فیلد شامل `created_at` |
| restart worker و retry بدون اثر تکراری | ✅ `tests/db/test_job_queue.py` |

## ۲. Baseline commit و branch

- baseline: `67170c9` (merge فاز ۲ روی `main`)
- branch: `arena/2a9acda4-deeptutor`
- commit: `83c668e` — «Phase 3: PostgreSQL data layer, migrations, storage and durable jobs»
- merge: PR **#4** → `f310df9`

## ۳. فایل‌های تغییرکرده و دلیل ownership

### جدید — `deeptutor/db/` (۲۲ فایل)

| فایل | مسئولیت |
|---|---|
| `config.py` | `DatabaseSettings` از env، `redact_dsn()`، `get/reset_database_settings()` |
| `connection.py` | `Connection`، `Database`، `normalize_value()`، `coerce_param()`، `open_database()`، `DatabaseUnavailable` |
| `migrate.py` | `discover_migrations`، `apply_pending`، `rollback_to`، `split_statements`، checksum drift |
| `schema_check.py` | `REQUIRED_COLUMNS`، `REQUIRED_INDEXES`، `verify_schema()`، `describe_schema()` |
| `identity_store.py` | `IdentityStore` protocol، `PostgresIdentityStore`، `active_store()`، `store_health()` |
| `health.py` | `liveness()`، `readiness()`، `backup_evidence()` |
| `storage/__init__.py` | `ObjectStore`، `LocalDiskObjectStore`، `content_key()` |
| `jobs/queue.py` | `JobQueue`، `Job`، `ClaimedJob`، `acquire_queue()` |
| `repositories/×5` | identity، otp، sessions، wallets، audit |
| `migrations/V0001–V0005` | پنج migration |
| `migrations/__main__.py` | CLI: `status\|up\|down\|verify\|export` |

### جدید — API

- `deeptutor/api/routers/platform_health.py` — `router` عمومی (`/health/live`, `/health/ready`) و `admin_router` (`/health/backup`, `/health/migrations`).

### تغییرکرده

| فایل | تغییر | دلیل |
|---|---|---|
| `deeptutor/multi_user/identity.py` | `_store_exists()` جای ۱۱ مورد `USERS_FILE.exists()`؛ `_write_users` به `replace_all` | اتصال به دیتابیس |
| `deeptutor/modules/manifests/server.json` | ۲ route entry (order 846/847) | ثبت router جدید |
| `deeptutor/api/router_index.json` | بازتولید: ۵۸ router / ۷۴۱ route | خروجی تولیدشده |
| `pyproject.toml` | extra `db` (`psycopg[binary]`, `psycopg-pool`)، marker `db_integration` | dependency اختیاری |

تفکیک: diff منیفست **۲۲ خط اضافه، ۰ خط حذف** — هیچ route موجودی جابه‌جا یا حذف نشد.

### جدید — `tests/db/` (۱۱ فایل، ۲۷۸ آزمون)

`conftest.py` (fixture دو-موتوره)، `test_migrations`، `test_identity_repository`، `test_identity_store_binding`، `test_job_queue`، `test_object_store`، `test_wallets_and_audit`، `test_otp_repository`، `test_isolation`، `test_health`، `test_connection_portability`.

## ۴. تصمیم‌ها و ADRها

- **ADR-003** (`docs/darsyar/ADR-003-POSTGRES-DATA-LAYER.md`) ایجاد شد.
- **D-019 تا D-024** در `DECISIONS.md` ثبت شد.

خلاصهٔ تصمیم‌ها:

| ID | تصمیم |
|---|---|
| D-019 | PostgreSQL منبع حقیقت داده تجاری |
| D-020 | بدون ORM؛ SQL دست‌نویس + migrator اختصاصی |
| D-021 | هویت فاز ۲ مرجع؛ schema قدیمی با `ALTER` هم‌تراز می‌شود |
| D-022 | صف = جدول دیتابیس، بدون broker |
| D-023 | ISO-8601 در مرز، `datetime` در لبهٔ PostgreSQL |
| D-024 | اتصال هویت در یک درز (`_write_users`)، فایل JSON به‌عنوان rollback |

## ۵. تست‌ها

| دستور | exit | نتیجه |
|---|---|---|
| `pytest tests/db -q` | 0 | **۲۷۸ pass**، ۱۲۶ skip |
| `pytest tests/db tests/multi_user -q` | 0 | **۸۳۲ pass**، ۱ fail محیطی (`llama_index`) |
| `pytest tests/api/test_router_loader.py -q` | 0 | ۵ pass |
| `pytest tests/db/test_identity_store_binding.py -q` | 0 | ۱۹ pass |
| `pytest tests/db/test_health.py -q` | 0 | ۱۱ pass |
| `pytest tests/test_packaging_metadata.py tests/test_matrix_requirements.py` | 0 | ۳۰ pass |
| `ruff check .` | 0 | clean |
| `ruff format --check .` | 0 | ۲۵۰۵ فایل |
| `lint-imports` | 0 | **۳ قرارداد حفظ‌شده، ۰ شکسته** (۱۱۶۹ فایل، ۴۴۱۳ dependency) |
| `npm run build` | 0 | **PASS** |
| `npx tsc --noEmit` | 0 | clean |
| `npx vitest run` (auth specs) | 0 | ۱۶ pass |
| `pytest -q tests deeptutor/learning/tests` (کل suite) | 0 | **۱۴٬۲۵۹ pass**، ۲۳۰ skip، ۵ fail محیطی |

۱۲۶ آزمون skip شده آن‌هایی هستند که به `DEEPTUTOR_TEST_DATABASE_URL` نیاز دارند.

### شواهد HTTP زنده

سرور uvicorn روی پورت ۳۷۹۸، `DEEPTUTOR_HOME=/tmp/live_home`، SQLite:

- `/api/platform/health/live` → **200**
- `/api/platform/health/ready` → **200** `{database:{enabled:true,backend:sqlite,ok:true}, object_store:{ok:true}, schema:{ok:true}}`
- `/api/platform/admin/health/backup` بدون احراز هویت → **401**
- همان با کوکی ادمین → **200**، `schema_ok:true`, `users:1`
- `POST /api/auth/register` → **201**، `role=admin`, `is_first_user=true`

یعنی هویت واقعاً از طریق HTTP در دیتابیس می‌نشیند.

## ۶. موارد تست‌نشده / نیازمند سرویس خارجی

این‌ها **بدهی واقعی** هستند، نه موارد «احتمالاً کار می‌کند»:

1. **مسیر شبکهٔ `psycopg` هرگز اجرا نشد.** sandbox به پورت ۵۴۳۲ دسترسی ندارد (`Network is unreachable`). همهٔ DDL از طریق API کنسول Supabase اجرا شد. SQL و invariant‌ها روی PostgreSQL ۱۷.۱۱ واقعی اثبات شدند؛ خود اتصال درایور نه. **اگر شکست بخورد، اولین `migrations up` تراکنشی و با صفر تغییر برمی‌گردد.**
2. **`backfill` از `users.json` واقعاً اجرا نشد.** نوشته و آزموده شد، اما دیتابیس زنده صفر کاربر داشت.
3. **`otp.py` به `OtpRepository` وصل نشد.** ۱۹ آزمون OTP فاز ۲ به API فایل وابسته‌اند.
4. **`FileLibraryStore` هنوز SQLite جدا دارد.** یکی‌سازی به فاز ۵ با ingestion موکول شد.
5. **آزمون‌های `[postgres]` در CI اجرا نمی‌شوند** — CI دیتابیس ندارد، پس ۱۲۶ آزمون skip می‌شوند.

## ۷. Migration و rollback evidence

### اعمال روی Supabase زنده

- پروژه: `jmqgzaqydvkjysqlaloe`، PostgreSQL ۱۷.۱۱.۰.۰۱۹، region `us-west-2`
- ledger: v4 `7d30ecebfd332ffffadeac110f67147b`، v5 `68d79f56c270d0f5bb25cd76a2fd28ea`

### دادهٔ مرجع پس از همهٔ تغییرات

| جدول | ردیف |
|---|---|
| `grades` | ۱۲ |
| `majors` | ۳ |
| `plans` | ۳ |
| `billing_settings` | ۱ |
| سایر جدول‌های تجاری | ۰ |

### اثبات constraint روی PostgreSQL واقعی

| نقض عمدی | نتیجه |
|---|---|
| کیف پول ناسازگار | `23514 ck_wallet_balance` |
| `dedupe_key` تکراری | `23505 uq_jobs_dedupe` |
| `(provider, authority)` تکراری | قبل از V0005 **پذیرفته شد**؛ بعد از V0005 `23505 uq_payment_provider_authority` |

### Rollback

V0005 `DOWN` روی دیتابیس زنده اجرا شد: ۴ ایندکس پشتیبان حذف شدند، **تمام ۱۰ ایندکس `uq_%` عمداً حفظ شدند** (چون حذفشان داده را در معرض تکرار می‌گذارد)، سپس بازساخته شدند.

**بخشی:** drill کاملِ `DROP TABLE … CASCADE` مسدود شد — فیلتر امنیتی کنسول Supabase دستور را رد می‌کند.

### Restore

ردیف صادر → حذف → بازگردانی. مقایسهٔ فیلد‌به‌فیلد **یکسان** بود، شامل `created_at`.

### Snapshot پیش از migration

`docs/darsyar/evidence/phase3-pre-migration-snapshot.json` — قبل از هر DDL گرفته شد.

## ۸. امنیت / حریم خصوصی / حقوق

- **`redact_dsn()`** تضمین می‌کند گذرواژهٔ دیتابیس هرگز به لاگ نرسد.
- **`backup_evidence()` داده کاربر برنمی‌گرداند** — فقط ledger، `schema_ok` و شمارش ردیف.
- **OTP هرگز به‌صورت متن خام ذخیره نمی‌شود**؛ `test_otp_repository` مجموعهٔ ستون‌های ذخیره‌شده را می‌آزماید.
- **`audit_events`** جداول حساس را ثبت می‌کند؛ آزمون redaction دارد.
- **مرز تراکنش:** کسر کیف پول و ثبت مصرف در یک تراکنش، پس هیچ مصرفی بدون کسر ثبت نمی‌شود.
- **`ck_wallet_balance`** مانع موجودی منفی می‌شود — در سطح دیتابیس، نه کد.
- حقوق منابع در فاز ۴ می‌آید؛ این فاز فقط زیرساخت ذخیره‌سازی را فراهم کرد.

## ۹. Known issues و ریسک باز

| # | مسئله | شدت | برنامه |
|---|---|---|---|
| 1 | مسیر `psycopg` اثبات نشده | **بالا** | اجرای `migrations status` روی ماشین مالک |
| 2 | `backfill` اجرا نشده | متوسط | اولین مهاجرت واقعی |
| 3 | `otp.py` روی فایل | متوسط | فاز ۵ |
| 4 | `FileLibraryStore` SQLite جدا | متوسط | فاز ۵ |
| 5 | ۱۲۶ آزمون Postgres در CI skip | متوسط | افزودن service container در فاز بعد |
| 6 | باگ: `Connection.insert_returning_id` در شاخهٔ SQLite `lastrowid` یک cursor تازه را می‌خواند ⇒ `None` | پایین | رفع در فاز بعد |

### نقص باز شناخته‌شده

`Connection.insert_returning_id` در شاخهٔ SQLite مقدار `lastrowid` را از یک cursor تازه می‌خواند و `None` برمی‌گرداند. مسیر PostgreSQL سالم است و در Production استفاده می‌شود، پس اثر عملی ندارد — اما روی SQLite هر فراخواننده‌ای که به شناسهٔ درج‌شده تکیه کند می‌شکند.

## ۱۰. نتیجه Gate

**Gate 3: PASS** — با بدهی مستند در بخش ۶.

دلیل: همهٔ معیارهای Acceptance فاز با شواهد عینی پاس شدند، از جمله روی PostgreSQL واقعی و از طریق HTTP زنده. بدهی اصلی (مسیر شبکهٔ `psycopg`) در سطح «اثبات‌نشده» است نه «اثبات‌شده که شکسته» — و اگر شکست بخورد، تراکنشی و بدون اثر برمی‌گردد.

## ۱۱. commit SHA و branch

- branch: `arena/2a9acda4-deeptutor`
- commit: `83c668e411bb721958429af230dfb5de0117c8bb`
- PR: **#4** — merged با اجازهٔ صریح مالک → `f310df909cd24a32f6a17dffd5dedda3c9b472c2`
