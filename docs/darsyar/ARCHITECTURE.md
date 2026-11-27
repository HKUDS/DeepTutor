# معماری هدف درسیار (Darsyar Target Architecture)

- نسخه: 1.0
- تاریخ: 2026-11-16
- وضعیت: Target Architecture؛ تصمیم‌های پرهزینه نیازمند ADR و اعتبارسنجی

## 1. اصول معماری

1. Preserve the useful DeepTutor core؛ آن را از نو ننویس.
2. Product boundary: درسیار یک محصول وب مستقل است؛ DeepTutor موتور فنی اولیه است.
3. Server-side authorization؛ UI فقط projection مجوز است.
4. Source-grounded learning؛ scope آموزشی قبل از retrieval enforce شود.
5. One source of truth برای identity، entitlements، billing و academic catalog.
6. Explicit async jobs برای parse، indexing، OCR، audio و video.
7. Meter every billable operation؛ actual و estimated را جدا نگه دار.
8. Modular by capability؛ قابلیت‌های گران یا غیرضروری در استقرار اولیه خاموش باشند.
9. Backward-compatible migration تا حد امکان؛ داده‌های فعلی runtime از بین نروند.
10. Evidence-based readiness؛ وجود کد به معنی Production ready نیست.

## 2. زمینه فعلی مخزن

مرجع baseline در زمان نوشتن سند:
- Repo: mahakas/DeepTutor
- main: 4c1e000d8563c5ac3b231baaaf149dc4dc4d2406
- Release metadata: v1.7.3
- Repo is a fork of HKUDS/DeepTutor under Apache-2.0; third-party notices نیز باید حفظ شوند.
- Web: Next.js App Router, React, TypeScript.
- API/runtime: Python و FastAPI، agent/capability runtime و WebSocket streaming.
- ماژولار بودن با manifests و optional module packages.
- ذخیره‌سازی فعلی ترکیبی از runtime home، فایل/JSON، SQLite و storage اختصاصی بعضی RAG engines است.
- سیستم auth فعلی نام کاربری/رمز و multi-user layer دارد؛ login عمومی فعلی OTP موبایل نیست.
- Usage ledger فعلی SQLite per-account است، نه دفتر تجاری مرکزی چندکاربره.
- RAG، Knowledge Base، Books، Mastery، Questions، Audio Overview، Video Lesson و Custom Provider UI در کد/manifest قابل مشاهده‌اند.

این توضیحات خلاصه ممیزی سطح معماری است، نه ادعای line-by-line audit یا اجرای تست‌ها.

## 3. نمای سطح بالا

Browser
  ├── /login, /register, /profile, /workspace
  └── /admin/login, /admin/*
          |
          v
Next.js Web App + same-origin proxy
          |
          v
FastAPI API / existing application & turn runtime
          |
          +-- Identity & Access domain
          +-- Academic Catalog domain
          +-- Source Catalog & Rights domain
          +-- Learning / Chat / RAG capabilities
          +-- Question Bank & Exam domain
          +-- Mastery / Flashcard domain
          +-- Usage, Wallet & Subscription domain
          +-- AI Provider & Routing domain
          +-- Learning Studio job domain
          |
          +-- PostgreSQL: transactional product data (target)
          +-- Existing RAG engine adapters and vector/index storage
          +-- Object storage: originals, parsed artifacts, audio/video
          +-- Queue/Workers: long-running jobs
          +-- SMS provider adapter
          +-- AI providers (LLM, embedding, reranker, OCR/Vision, TTS/STT, image/video)

## 4. Frontend boundaries

حفظ Next.js App Router موجود و گسترش Feature ownership:
- web/app/(auth): ورود، ثبت‌نام، OTP و بازیابی رمز.
- web/app/(workspace): تجربه یادگیری و چت.
- web/app/(admin): داشبورد و مدیریت.
- web/features/identity: profile و auth transport/store.
- web/features/academic-catalog: پایه، رشته، درس.
- web/features/sources: کاتالوگ و مدیریت منابع.
- web/features/exams: آزمون، پاسخ و گزارش.
- web/features/mastery: استفاده مجدد از Mastery موجود.
- web/features/billing: plan، balance و usage.
- web/features/ai-providers: مدیریت Provider و routing.
- web/features/learning-studio: audio/video/slide outputs.
- web/shared: UI primitives و transport مشترک.

ساختار دقیق پوشه قبل از ایجاد باید با feature boundaries و dependency-cruiser فعلی تطبیق داده شود؛ ایجاد feature تکراری برای همان مالکیت ممنوع است. API contracts باید از schema/source of truth تولید یا با آن همگام باشند.

## 5. Backend domain boundaries

### 5.1 Identity & Access
مسئول شماره موبایل، OTP lifecycle، password hash، session/token، disable/restore، role، admin bootstrap و audit. SMS از طریق interface مستقل قابل تعویض باشد.

### 5.2 Academic Catalog
مرجع داده‌محور برای دوره، پایه، شاخه، رشته، درس، سال/نسخه برنامه و رابطه کتاب با آن‌ها. ساختار جاری و آرشیوی تفکیک شود. شناسه‌ها پایدار باشند؛ label فارسی mutable باشد.

### 5.3 Source Catalog & Rights
مرجع فایل و محتوای آموزشی همراه نسخه، provenance، rights status، quality status، academic scope و index version. دسترسی به فایل خام با مجوز دامنه و signed URL کوتاه‌عمر انجام شود.

### 5.4 RAG & Teaching
Adapter روی RAG service و retrieval pipelines موجود؛ فیلتر scope و حقوق به شکل server-enforced قبل از retrieval. Citation renderer اطلاعات داخلی را به قالب کوتاه کاربر تبدیل کند. نیاز به RAG engine جدید بدون benchmark و ADR وجود ندارد.

### 5.5 Exams & Question Bank
بانک سؤال نسخه‌دار، آزمون snapshotدار، attempt، پاسخ، rubric، grading، marking scheme، result و appeal. هر آزمون نمره منفی را با config مستقل تعریف کند.

### 5.6 Billing & Usage
LLM call ledger، modality usage ledger، wallet transactions، reservations، plan entitlements، pricing version و invoices/receipts. ذخیره باید transactional و idempotent باشد.

### 5.7 Provider Routing
یک catalog امن برای provider connections و model profiles. Routing با capability/task policy انجام شود، نه از کد UI. secretها در storage امن/رمزگذاری‌شده نگهداری و responseها redacted باشند.

### 5.8 Learning Studio
درخواست تولید محتوا به job تبدیل شود. Worker وضعیت queued/running/succeeded/failed/cancelled و usage را ثبت کند. فایل خروجی در object storage ذخیره شود.

## 6. مدل داده مفهومی

این فهرست طرح دامنه است، نه schema نهایی:

- users, user_credentials, phone_verifications, sessions, roles, permissions, admin_audit_events.
- learner_profiles, academic_years, school_stages, grades, branches, tracks, subjects, curriculum_versions.
- sources, source_versions, source_rights, source_review_events, source_chapters, source_assets, ingestion_jobs, index_versions.
- source_scope_assignments, source_access_policies.
- question_banks, questions, question_versions, answer_keys, rubrics, exams, exam_blueprints, exam_attempts, exam_answers, grading_events, score_policies.
- learning_paths, mastery_states, flashcards, review_events.
- ai_providers, provider_credentials, model_profiles, capability_routes, model_pricing_versions.
- plans, plan_entitlements, subscriptions, wallets, wallet_transactions, usage_reservations, usage_events, invoices.
- media_jobs, media_assets, job_events.

قواعد:
- هر رکورد دامنه دارای stable ID، timestamps و status مناسب باشد.
- مبالغ با decimal/integers در واحد پول مشخص؛ floating point برای حسابداری ممنوع.
- تمام تغییرات schema با migration versioned.
- exam/question snapshots و pricing versions immutable باشند.
- حذف user/source باید اثر بر audit، billing و retention را مشخص کند.

## 7. پایگاه داده و ذخیره‌سازی

### 7.1 Product database

هدف معماری برای داده‌های تجاری و چندکاربره PostgreSQL است؛ زیرا identity، catalog، exam, subscription و wallet به تراکنش و query مشترک نیاز دارند.

انتخاب ORM/migration، اتصال و مدل نهایی باید در ADR پس از بررسی dependency stack و compatibility موجود تثبیت شود. SQLAlchemy 2 + Alembic گزینه پیشنهادی برای ارزیابی است، نه مجوز افزودن بی‌بررسی. هرگز PostgreSQL و فایل JSON را دو مرجع متناقض برای یک نوع رکورد نکن.

### 7.2 RAG stores

DeepTutor چند pipeline و storage backend دارد. تصمیم اینکه vector store از pgvector، pipeline فعلی یا backend دیگری باشد باید پس از benchmark و سنجش:
- کیفیت retrieval متون فارسی و ریاضی.
- دقت page/chapter provenance.
- OCR/layout/table handling.
- هزینه، latency و concurrency.
- قابلیت versioning و حذف/بازایندکس.
انجام شود. مهاجرت همه knowledge data فقط برای یکنواختی ظاهری ممنوع است.

### 7.3 Object storage

فایل خام، نسخه parse شده، تصویر صفحه، نمودار، صدا و ویدئو در مسیرهای ایزوله نگهداری شوند. طراحی باید امکان local filesystem در development و object storage-compatible backend در Production را داشته باشد. Access control باید در backend اعمال شود.

### 7.4 Async worker

PDF parsing/OCR/indexing و audio/video generation از درخواست اصلی کاربر جدا شوند. Queue backend (مثلاً Redis-backed) باید پس از بررسی orchestration فعلی و نیاز deploy انتخاب شود. Job باید idempotent، observable، cancellable و دارای retry limit باشد.

## 8. احراز هویت و امنیت

- OTP با provider abstraction؛ در Production فقط provider واقعی configured و health checked.
- password hash با الگوریتم مقاوم و policy به‌روز.
- secure, HttpOnly, SameSite cookies یا توکن متناسب با قرارداد موجود؛ تصمیم با بررسی auth/session فعلی.
- CSRF/CORS و trusted proxy policy بررسی شود.
- SMS brute-force و resend abuse محدود شود.
- Super Admin bootstrap فقط development؛ Production secret از environment/secret manager و rotation.
- دسترسی admin در تمام API routeها و WebSocket handshake enforce شود.
- password خام، OTP، API key و authorization headers در telemetry/log/test artifact ممنوع.
- مسیرهای Custom API با SSRF defense و egress policy.
- فایل‌های آپلودی untrusted؛ parsing در subprocess/container محدودشده با timeout/memory/CPU limits و عدم انتقال database secrets.
- document text یک منبع داده است، نه دستور مورد اعتماد برای agent.

## 9. RAG scope enforcement

ساختار فیلتر در سطح درخواست:
1. user identity و entitlements.
2. learner profile (grade, branch, track, subject).
3. source rights + review/approval.
4. current/archived curriculum version.
5. selected source collection and allowed source types.
6. retrieval + rerank.
7. citation validation against retrieved source IDs.

فیلترها باید در repository/query layer و tool/capability boundary enforce شوند. اگر profile ناقص باشد، پیش از retrieval سؤال روشن‌کننده پرسیده شود یا تنها منابع مجاز بدون ابهام استفاده شوند. هیچ fallback پنهانی به سایر پایه‌ها مجاز نیست.

## 10. حسابداری مصرف

برای هر مدل و modality event ایجاد شود. Reservation/settlement/refund تراکنشی و idempotent باشد. در صورت عدم دریافت usage واقعی، estimated flag و مبنای تخمین ذخیره شود. Pricing version زمان درخواست ثبت شود تا تغییر قیمت آینده تراکنش قبلی را عوض نکند.

نمای کاربر: سهمیه/اعتبار باقی‌مانده و مصرف خوانا.
نمای admin: call-level، مدل، provider، capability، کاربر، هزینه تأمین‌کننده و مبالغ شارژشده.
هر گزارش باید مجموع داده‌های actual و estimated را تفکیک کند.

## 11. تست‌پذیری و محیط‌ها

- isolated DEEPTUTOR_HOME برای تست.
- mock SMS, LLM, OCR, TTS, video provider.
- synthetic PDFs و داده جعلی دانش‌آموز.
- integration test برای migrations و storage adapters.
- no real API keys / student PII in CI.
- test matrix برای grade/track/source scope and permission boundaries.
- browser E2E برای OTP، login، admin, exam, source upload and usage.
- load test برای concurrent chat و indexing/media jobs.
- backup/restore drill پیش از Production.

## 12. تصمیم‌های نیازمند ADR

پیش از پیاده‌سازی production-grade باید ADRهای مستقل برای موارد زیر تهیه شوند:
1. PostgreSQL adoption, ORM, migration strategy and legacy data migration.
2. SMS gateway, OTP policy and phone normalization.
3. Object storage and async queue/workers.
4. RAG pipeline/provider and vector backend benchmark.
5. Pricing/credit currency, plan model and refund policy.
6. Provider secret encryption/rotation and outbound network policy.
7. Admin bootstrap and MFA.
8. Copyright/license evidence workflow for textbook and supplementary content.
9. Data retention, account deletion and student/guardian privacy.
10. Persian OCR/math extraction quality gates.

تا زمان تصمیم، implementation باید adapter-based و کم‌ریسک باشد؛ انتخاب موقت نباید به‌عنوان تصمیم نهایی ثبت شود.
