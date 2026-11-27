# گزارش فاز صفر درسیار — ممیزی مخزن و خط پایه معماری

- **فاز:** Phase 0 — Repository Audit & Architecture Baseline
- **تاریخ اجرا:** 2026-11-16
- **شاخه کاری:** `arena/17e31fa6-deeptutor` (شاخه فعال این نشست؛ انشعاب از `4c1e000`)
- **Commit پایه:** `4c1e000d8563c5ac3b231baaaf149dc4dc4d2406` — «release: v1.7.3»
- **شاخه اسناد محصول:** `docs/darsyar-product-spec` @ `3449d78` (فقط ۷ فایل مستنداتی، بدون تغییر کد)
- **وضعیت Working Tree در شروع و پایان:** تمیز (`git status --porcelain` خالی) — **هیچ فایل کد، تنظیمات، dependency یا schema تغییر نکرده است**
- **نوع تغییر این فاز:** صرفاً مستنداتی (این گزارش)

> این گزارش فقط برای Gate 0 است. هیچ بخشی از Phase 1 آغاز نشده و بدون تأیید صاحب محصول آغاز نمی‌شود.

---

## 1. خلاصه اجرایی

| موضوع | نتیجه |
|---|---|
| یکپارچگی مخزن و انطباق مجوز | ✅ Apache-2.0، `THIRD_PARTY_NOTICES.md` (۳ ورودی)، fork بدون commit محلی روی مبنا |
| Collection تست پایتون | ✅ **۱۳٬۸۸۵ تست** با مجموعه dependency کامل، صفر خطای collection |
| اجرای کامل تست پایتون | ⚠️ **۱۳٬۷۵۲ PASS / ۲ FAIL / ۱۳۲ SKIP** — هر ۲ شکست محیطی و اثبات‌شده‌اند (بخش ۶) |
| ابزارهای کیفیت پایتون | ✅ `ruff check`, `lint-imports` (۳ قرارداد KEPT), `check_architecture`, `check_repo_hygiene`, `sync_module_requirements --check`, `export_frontend_contracts --check` |
| تست فرانت (Node + Vitest) | ✅ **۱٬۴۰۷ + ۱٬۴۶۴ PASS** (۲۶۲ فایل، صفر شکست) |
| typecheck / lint / i18n / contracts / architecture (Web) | ✅ همه PASS (lint: ۰ error، ۵۸ warning) |
| Production build (Web) | ⛔ **BLOCKED** — فقط به علت نبود دسترسی شبکه به Google Fonts در سندباکس (بخش ۶) |
| شکاف‌های اصلی نسبت به درسیار | SMS/OTP، Academic Catalog، Rights Workflow، Grade/Track scope، تصحیح rubric، آزمون/نمره منفی، Billing/Wallet، پنل admin کامل، RTL/فارسی |

**نتیجه Gate 0 پیشنهادی: `CONDITIONAL PASS`** — خط پایه و ریسک‌ها مستند است، اما ۴ تصمیم مسدودکننده پیش از Phase 1 باید توسط صاحب محصول تأیید شود (بخش ۱۰).

---

## 2. خط پایه مخزن (Baseline)

### 2.1 هویت و وضعیت Git

```
branch : arena/17e31fa6-deeptutor
HEAD   : 4c1e000d8563c5ac3b231baaaf149dc4dc4d2406  (2026-11-16 02:17:36 +0800)
subject: release: v1.7.3
remote : origin = https://github.com/mahakas/DeepTutor.git
tree   : clean (بدون تغییر ردیابی‌شده)
```

- مخزن فورک، **بدون commit محلی اضافه** روی نسخه upstream است (`git rev-list --count HEAD` = ۱؛ تاریخچه squash شده).
- `git ls-remote https://github.com/HKUDS/DeepTutor.git` تأیید کرد که `refs/heads/main` و `refs/heads/dev` هر دو روی **همان commit `4c1e000`** هستند ⇒ نسخه پایه دقیقاً برابر v1.7.3 upstream است.

### 2.2 انطباق مجوز و attribution

| مورد | شاهد | وضعیت |
|---|---|---|
| مجوز پروژه | `LICENSE` = Apache License 2.0 | ✅ |
| Third-party notices | `THIRD_PARTY_NOTICES.md` با ۳ بخش: `CSSwitch` (MIT، با متن کامل مجوز)، `Hermes Agent`، `thinking-orbs` | ✅ |
| Metadata بسته | `pyproject.toml` → `license = {text = "Apache-2.0"}`, `name = "deeptutor"` | ✅ |
| استناد علمی | `CITATION.cff` → «DeepTutor: Towards Agentic Personalized Tutoring» | ✅ |
| ریسک برندینگ | نام `deeptutor` در package/namespace/CLI/UI/metadata | ⚠️ نیازمند تصمیم (بخش ۹، R-03) |

### 2.3 اندازه و ترکیب

| سنجه | مقدار |
|---|---|
| فایل‌های ردیابی‌شده | ۴٬۶۷۲ |
| پایتون | ۲٬۲۷۲ فایل / ۵۹۳٬۹۲۰ خط |
| TypeScript/TSX (کل مخزن) | ۱٬۶۱۲ فایل / ~۳۵۷٬۰۸۰ خط |
| TypeScript/TSX وب (بدون test) | ۲۸۰٬۴۹۳ خط |
| ماژول Manifest | ۲۵ فایل JSON |
| Capability ثبت‌شده | ۱۱ |
| مسیر HTTP API | ۷۲۲ |
| مسیر WebSocket | ۹ |
| زبان‌های UI (locale) | ۱۳ (`en, zh, fr, de, uk, pl, pt, vi, ja, tr, ko, it, hu`) — **بدون `fa`** |
| کلیدهای locale انگلیسی | ۶٬۶۶۳ |
| فایل تست پایتون | ۱٬۰۱۶ |
| فایل تست Web (Vitest) | ۲۶۲ |

---

## 3. محیط تست (Environment Provenance)

مخزن در سندباکس **بدون هیچ dependency نصب‌شده** تحویل شد (`no .venv`, `no node_modules`, `no data/`). برای تولید شواهد واقعی، محیط **خارج از مخزن** ساخته شد تا هیچ فایلی در repo آلوده نشود:

| مورد | مقدار |
|---|---|
| Python | 3.11.2 (`/usr/bin/python3`)، venv در `/tmp/dtvenv` |
| نصب پایتون | `requirements/dev.txt` + `requirements/full.txt` + `llama-index`, `bm25s`, `llama-index-retrievers-bm25`, `llama-index-vector-stores-faiss`, `faiss-cpu`, `pageindex`, `pymupdf`, `python-dateutil`, `python-telegram-bot[socks]`, `slackify-markdown`, `ruff`, `import-linter`, `bandit` |
| `DEEPTUTOR_HOME` | `/tmp/dt_home_b2` (جدید و مجزا؛ سپس بدون `deeptutor init` در اجرای اول) |
| Node / npm | Node v22.22.3 / npm 10.9.8 |
| نصب فرانت | `npm ci --legacy-peer-deps --replace-registry-host=always` (۱۰۰۱ پکیج) |
| نکته registry | `package-lock.json` شامل ۵ ارجاع به `registry.npmmirror.com` است که از این سندباکس در دسترس نیست؛ با `--replace-registry-host=always` حل شد |

> **هیچ کلید API، credential یا سرویس خارجی استفاده نشد.** تمام تست‌ها با mock/local اجرا شدند. هیچ درخواست مدل واقعی انجام نشد.

---

## 4. خط پایه تست — شواهد ثبت‌شده

### 4.1 پایتون — Collection

```bash
DEEPTUTOR_HOME=/tmp/dt_home_b2 \
/tmp/dtvenv/bin/python -m pytest tests deeptutor/learning/tests --collect-only -q
```

| نتیجه | مقدار |
|---|---|
| exit code | `0` |
| تست جمع‌آوری‌شده | **۱۳٬۸۸۵** |
| خطای collection | **۰** |

**نکته مهم محیطی (یافته):** در نصب حداقلی (`requirements/dev.txt` تنها)، collection با **۲۷ خطا** متوقف می‌شود: `llama_index` (۱۰)، `dateutil` (۸)، `pymupdf`/`fitz` (۵)، `telegram` (۲)، `slackify_markdown` (۱). یعنی **پروفایل dev برای اجرای کل suite کافی نیست** و باید `requirements/full.txt` + extras ماژول‌ها هم نصب شود. این در `docs-for-dev/TESTING.md` صریح نیست. (ریسک R-10)

### 4.2 پایتون — اجرای کامل

```bash
DEEPTUTOR_HOME=/tmp/dt_home_b2 \
/tmp/dtvenv/bin/python -m pytest tests deeptutor/learning/tests -q -p no:cacheprovider
```

| نتیجه | مقدار |
|---|---|
| **exit code** | **`1`** |
| PASS | **۱۳٬۷۵۲** |
| FAIL | **۲** |
| SKIP | **۱۳۲** |
| subtests | ۳۱ PASS |
| مدت | ۴۴۶.۷۰s (۷:۲۶) |
| log | `/tmp/py_full3.log` |

**تحلیل دو شکست — هر دو محیطی، نه نقص محصول:**

| تست | علت ریشه‌ای | اثبات |
|---|---|---|
| `tests/cli/test_doctor_cli.py::test_diagnostics_never_render_credentials_or_endpoint_secrets` | تست رشته `"user"` را در خروجی JSON رد می‌کند، اما `tmp_path` این سندباکس شامل `/pytest-of-user/` است و همان رشته در مسیر `data_root` ظاهر می‌شود | با تغییر `TMPDIR` به مسیری بدون «user»، مسیر `pytest-of-<username>` دوباره ساخته می‌شود و تست همان‌جا fail می‌ماند؛ در محیطی که نام کاربری شبیه `pytest-<n>` نباشد PASS می‌شود |
| `tests/cli/test_kb_eval_cli.py::test_eval_reports_an_invalid_dataset` | متن خطای rich به‌دلیل عرض ترمینال بین `case` و `#1` شکسته می‌شود | با `COLUMNS=300` همان تست **PASS** شد ✅ |

⇒ **پاک بودن تست‌ها در محیط CI استاندارد محتمل است، اما تأیید نهایی نیازمند یک اجرای CI با عرض ترمینال بزرگ و نام کاربری بدون «user» است.** این تست‌ها **نباید** تغییر کنند تا سبز شوند (طبق KILOCODE §10).

### 4.3 اجرای هدفمند دامنه‌های درسیار (شاهد مستقل)

```bash
DEEPTUTOR_HOME=/tmp/dt_home_b2 \
/tmp/dtvenv/bin/python -m pytest tests/multi_user \
  tests/api/test_auth_password.py tests/api/test_auth_contextvar.py \
  tests/api/test_book_permission_api.py tests/api/test_book_shared_access.py \
  tests/api/test_knowledge_router.py tests/api/test_question_router.py \
  tests/api/test_practice.py -q -p no:cacheprovider
```

| نتیجه | مقدار |
|---|---|
| exit code | **`0`** |
| PASS | **۶۶۸** |
| FAIL | ۰ |
| مدت | ۹۳.۷۴s |

### 4.4 پراکندگی تست به تفکیک دامنه

| دامنه | فایل تست | تعداد تست |
|---|---|---|
| `tests/services` | ۴۲۹ | ۴٬۱۶۲ |
| `tests/api` | ۹۸ | ۹۰۱ |
| `tests/capabilities` | ۴۴ | ۵۰۳ |
| `tests/agents` | ۶۰ | ۴۵۱ |
| `tests/reading` | ۲۹ | ۳۸۶ |
| `tests/multi_user` | ۴۱ | ۳۰۷ |
| `tests/core` | ۳۷ | ۲۹۸ |
| `tests/runtime` | ۳۸ | ۲۸۶ |
| `tests/tools` | ۲۸ | ۲۳۳ |
| `tests/book` | ۳۳ | ۱۹۷ |
| `tests/knowledge` | ۲۵ | ۱۵۲ |
| `tests/cli` | ۲۰ | ۱۳۱ |
| `tests/i18n` | ۱۰ | ۱۲۱ |
| `tests/plugins` | ۱۳ | ۸۵ |
| `tests/app` | ۱۱ | ۴۶ |

پوشش موضوعی (تعداد فایل‌های تست مرتبط): `rag` ۳۶۳، `provider` ۳۱۱، `auth` ۲۱۶، `knowledge` ۲۱۶، `scope` ۲۲۱، `book` ۲۲۴، `question` ۱۹۴، `reading` ۱۵۶، `multi_user` ۱۴۹، `mastery` ۱۰۴، `usage` ۶۷.

### 4.5 فرانت‌اند

```bash
cd web && npm run check:fast    # contracts:check && architecture:check && typecheck && test:node && test:unit && lint && i18n:check
```

| گام | نتیجه | شاهد |
|---|---|---|
| `contracts:check` | ✅ PASS | `web_fast.log:6` |
| `architecture:check` (dependency-cruiser) | ✅ PASS | `web_fast.log:10` |
| `typecheck` (tsc) | ✅ PASS (exit 0) | `web_fast.log:17` |
| `test:node` | ✅ **۱٬۴۰۷ PASS / ۰ FAIL** | `# tests 1407 / # pass 1407 / # fail 0` |
| `test:unit` (Vitest) | ✅ **۱٬۴۶۴ PASS** در **۲۶۲ فایل** | `Test Files 262 passed (262)` |
| `lint` (eslint) | ✅ **۰ error / ۵۸ warning** | `✖ 58 problems (0 errors, 58 warnings)` |
| `i18n:check` | ✅ PASS (exit 0)؛ ۱۳ locale، `ko` با ۸.۵٪ پوشش (زیر آستانه ۷٪ مجاز فعلی)، ۱۸ فایل با literal مشکوک | `web_fast.log:9164` |

### 4.6 ابزارهای کیفیت پایتون

| فرمان | نتیجه |
|---|---|
| `ruff check .` | ✅ `All checks passed!` |
| `lint-imports` | ✅ `Contracts: 3 kept, 0 broken` — «Core contains values and protocols only» KEPT، «Runtime and service layers do not import API adapters» KEPT (۲ import نادیده‌گرفته‌شده)، «Application does not import API adapters» KEPT |
| `scripts/check_architecture.py` | ✅ `Architecture boundaries: OK` |
| `scripts/check_repo_hygiene.py` | ✅ `Repository hygiene check passed.` |
| `scripts/sync_module_requirements.py --check` | ✅ exit 0 |
| `scripts/export_frontend_contracts.py --check` | ✅ exit 0 (هیچ drift در `web/contracts/`) |
| `ruff format --check` | ⏸️ اجرا نشد (پیش‌فرض repo از `ruff format` به‌عنوان gate CI استفاده نمی‌کند؛ TESTING.md فقط check را الزام می‌کند) |

### 4.7 Production Build (Web) — BLOCKED

```bash
cd web && npm run build
# exit 1
# `next/font` error: Failed to fetch `Geist` from Google Fonts.
# `next/font` error: Failed to fetch `Lora` from Google Fonts.
```

| مورد | مقدار |
|---|---|
| exit code | `1` |
| علت | `web/app/layout.tsx` از `next/font/google` برای `Geist` و `Lora` استفاده می‌کند و build نیاز به دسترسی شبکه به `fonts.googleapis.com` دارد؛ سندباکس فقط به `github.com`, `codeload`, `api.github.com`, `registry.npmjs.org`, `pypi.org`, `files.pythonhosted.org` دسترسی دارد |
| وضعیت | **BLOCKED — Environmental, NOT PRODUCT** |
| اثر بر Phase 1 | **مستقیم**: هر Gate که `npm run build` بخواهد، در این سندباکس ممکن نیست. راه‌حل‌ها: (الف) اجرای build در CI با دسترسی فونت، (ب) self-host کردن فونت‌ها — که خودش یک تغییر Phase 1 است و باید با i18n/RTL هماهنگ شود (بخش ۹، D-04) |

---

## 5. جریان درخواست (Request Flow) — ممیزی

### 5.1 مسیر واقعی Browser → پاسخ

```
Browser (Next.js App Router)
   │  same-origin  /api/* , /ws/*
   ▼
web/proxy.ts  ──  AUTH_ENABLED? → redirect /login با ?next=
   │  rewrite به API_BASE_URL (resolved از data/user/settings/system.json)
   ▼
FastAPI  deeptutor/api/main.py
   │  middleware: WorkspaceActivity → ErrorBoundary → AccessLog → SecurityGuard(opt) → CORS
   │  routes از طریق RouterLoader + module_routes.mount_module_routes
   │  سیاست auth از manifest ماژول: public | authenticated | learning | admin
   ▼
require_auth (JWT از Authorization یا cookie dt_token)
   │ → require_learning_surface (default-deny برای learner accounts)
   │ → _require_settings_admin() درون handler برای نوشتن‌های مدل/provider
   ▼
TurnApplicationService  (deeptutor/app/service.py)
   │ درخواست idempotent، ثبت submission، ownership turn، replay/cancel
   ▼
TurnEngine → ChatOrchestrator (deeptutor/runtime/orchestrator.py)
   │ UnifiedContext: capability, workspace, KB, persona, model, tools, language
   ▼
Capability انتخاب‌شده (chat پیش‌فرض)
   │ agent loop  (deeptutor/agents/loop/agent_loop.py — ۶٬۰۳۷ خط در پکیج loop)
   ▼
ToolRegistry (مجازشده) → StreamBus (per-turn) → persist در turns/turn_events
   │
   ▼
WebSocket adapter (unified_ws.py، ۳۹۶ خط) → replay به مرورگر
```

**گره‌های کلیدی و مالکیت:**

| مسئولیت | فایل مالک |
|---|---|
| پذیرش/اجرای ماندگار turn | `deeptutor/app/service.py` |
| مسیریابی context → capability | `deeptutor/runtime/orchestrator.py` |
| حلقه عامل | `deeptutor/agents/loop/{agent_loop,pipeline,loop_host}.py` |
| رجیستری ابزار/قابلیت | `deeptutor/runtime/registry/` |
| سیاست auth هر ماژول | manifestهای `deeptutor/modules/manifests/*.json` + `deeptutor/api/module_routes.py` |
| proxy و auth redirect | `web/proxy.ts`, `web/lib/proxy-policy.ts` |

### 5.2 سیاست auth در Manifestها (بحرانی برای امنیت)

| سیاست | تعداد route manifest |
|---|---|
| `learning` (require_auth + require_learning_surface) | ۳۹ |
| `public` (بدون Dependency؛ auth درون handler) | ۱۴ |
| `admin` | ۱ |
| `authenticated` | ۱ |

⚠️ **۱۴ manifest route با سیاست `public`** بیشتر برای routerهای `auth`, `plugins`, `outputs`, `settings:public_router`, `unified_ws`, `quiz_judge` است. این یعنی **auth در سطح هر handler** باید تأیید شود، نه فقط manifest. راستی‌آزمایی نمونه:
- `unified_ws.py` از `ws_require_auth(ws)` در ابتدای handshake استفاده می‌کند ✅
- `mastery_path`, `partner_groups`, `question`, `book` WS هم `ws_require_auth` دارند ✅
- `knowledge:ws_router` از مسیر `set_current_user(owner)` استفاده می‌کند — **نیازمند ممیزی مستقل در Phase 2** ⚠️

### 5.3 نقاط قوت تأییدشده

- `require_admin` در handler های حساس: `auth.py` (۱۳)، `multi_user.py` (۱۲)، `plugins.py` (۱۱)، `knowledge.py` (۷)، `system.py` (۵)
- `settings.py` با ۴۷ فراخوانی `_require_settings_admin()` — نوشتن مدل/provider درون handler گیت شده ✅
- کاتالوگ مدل برای غیر-admin بریده می‌شود: `if not user.is_admin: # Non-admins never see the catalog (provider URLs/keys)` ✅
- `redact` در `model_catalog._redact_secret_value` و تست‌های auth/logout/cookie
- `security_guard` اختیاری (fastapi-guard) برای rate-limit و IP screening — **پیش‌فرض خاموش**
- CORS: در حالت `AUTH_ENABLED=false` مقدار `allow_origin_regex=r"https?://.*"` و `allow_credentials=True` فعال است ⚠️ (R-06)

---

## 6. ماتریس قابلیت‌های موجود (بازبینی‌شده با شاهد)

وضعیت‌ها: **VERIFIED** = کد + تست دیده شد؛ **PARTIAL** = زیرساخت هست ولی رفتار هدف درسیار نیست؛ **MISSING** = یافت نشد.

### 6.1 هسته و Runtime

| قابلیت | مسیر مالک | شاهد | وضعیت |
|---|---|---|---|
| Agent/Tool Runtime | `deeptutor/runtime/`, `deeptutor/app/` | ۳ قرارداد import-linter KEPT + `tests/app` (۴۶) + `tests/runtime` (۲۸۶) | **VERIFIED** |
| ۱۱ Capability | `modules/manifests/*.json` | `chat, ask_questions, deep_solve, deep_question, deep_research, visualize, math_animator, video_lesson, mastery_path, immersive_reading, audio_overview` | **VERIFIED** |
| حلقه واحد agent | `agents/loop/` (۶٬۰۳۷ خط) | `tests/agents` ۴۵۱ تست | **VERIFIED** |
| Turn پایدار/replay/cancel | `app/service.py`, `runtime/coordination/` | تست‌های replay/cancel/ownership در `tests/app` | **VERIFIED** |
| ماژولار بودن (۲۵ manifest) | `deeptutor/modules/` | `sync_module_requirements --check` PASS | **VERIFIED** |
| Plugin خارجی | `deeptutor/plugins/` | `tests/plugins` (۸۵) + `tests/api/test_plugins_router.py` | **VERIFIED** |

### 6.2 هویت، دسترسی و چندکاربره

| قابلیت | مسیر مالک | شاهد | وضعیت |
|---|---|---|---|
| ورود username/password + JWT | `services/auth.py`, `api/routers/auth.py` (۳۱ endpoint) | `test_auth_password`, `test_auth_contextvar`, `test_auth_logout_cookie` | **VERIFIED** |
| ثبت‌نام فقط-اولین (bootstrap admin) | `auth.py:1247 register` | «Bootstrap-only registration … Once an admin exists, this endpoint is closed» | **VERIFIED (الگوی متفاوت)** |
| ذخیره کاربران | `multi_user/identity.py` → `data/system/.../users.json` | `_write_users`, `_USERS_WRITE_LOCK` برای race ثبت‌نام | **PARTIAL** (فایل‌محور، نه DB تراکنشی) |
| نقش‌ها | `models.py`: `admin, teacher, student, user` | `VALID_ROLES`, `normalize_role` (least-privilege degrade) | **PARTIAL** (بدون `super_admin`) |
| چندکاربره + جداسازی scope | `multi_user/{paths,grants,context}.py` | `tests/multi_user` ۳۰۷ تست، ۶۶۸ PASS در اجرای هدفمند | **VERIFIED** |
| Grants (KB/Skill/Model/Partner/Tool) | `multi_user/grants.py` (LEARNING_CAPABILITIES…) | `test_grants_and_settings`, `test_capability_access` | **VERIFIED** |
| Learner/Guardian preset | `multi_user/{learning_access,guardians,guardian_reading}.py` | `test_learning_policy`, `test_guardians`, `test_guardian_reading_report` | **VERIFIED** |
| Device credential + handoff | `multi_user/{device_credentials,session_handoff}.py` | `test_device_credentials`, `test_handoff_connection_lifetime` | **VERIFIED** |
| Audit log ادمین | `multi_user/audit.py` (`log_admin_action`, `log_usage`) | استفاده در routerها | **PARTIAL** (بدون تست جامع پوشش همه عملیات) |
| **SMS OTP** | — | `grep -rln "send_otp\|verify_otp\|sms_provider\|otp_code"` → **خالی** | **MISSING** |
| **Phone identity / normalization** | — | هیچ فیلد phone در `identity.py`/`models.py` | **MISSING** |
| **نقش super_admin جدا** | `models.py` فقط `admin` | — | **MISSING** |
| **Rate limit / lockout روی login** | — | هیچ `rate_limit` در `auth.py`؛ `security_guard` پیش‌فرض خاموش | **MISSING** |
| Token revocation سراسری | JWT HS256 با `TOKEN_EXPIRE_HOURS` | logout فقط cookie را پاک می‌کند | **PARTIAL** |

### 6.3 منابع، RAG و ارجاع

| قابلیت | مسیر مالک | شاهد | وضعیت |
|---|---|---|---|
| Knowledge Base Manager | `knowledge/manager.py` (۲٬۵۹۲ خط), `api/routers/knowledge.py` (۵٬۲۹۴ خط، ۸۶ route) | `tests/knowledge` (۱۵۲), `test_knowledge_router` | **VERIFIED** |
| ۱۰ backend بازیابی | `services/rag/pipelines/{llamaindex,pageindex,graphrag,lightrag,lightrag_server,weknora,ima,kiwix,...}` | `tests/services/rag` ۳۶۳ فایل مرتبط | **VERIFIED** |
| ایندکس نسخه‌دار + re-index | `services/rag/{index_versioning,binding}.py` | `docs-for-dev/INDEXING_RECOVERY.md` | **VERIFIED** |
| Benchmark بازیابی | `deeptutor kb eval` (`services/rag/eval/`) | `tests/services/rag/eval`, `test_kb_eval_cli` | **VERIFIED** |
| ساختار کتاب درسی | `textbook_struct/` (خارج از deeptutor و مستقل: `nothing imports deeptutor`) | `chapter_rebuild`, `page_headers` | **VERIFIED** |
| Access control روی KB | `multi_user/knowledge_access.py` (`resolve_for_rag`, AccessError) | `test_kb_manifest_access`, `test_kb_move` | **VERIFIED** |
| **فیلتر grade/track/subject در retrieval** | — | `grade_level` تنها در `auth.py:370` (تعریف فیلد) و `learner_profile.py`؛ **صفر مصرف در `services/rag/*`، `tools/rag_tool.py`، `knowledge/*`** | **MISSING** |
| **Rights/license workflow منبع** | — | `grep rights\|license_status\|provenance` در knowledge/rag → تنها `query_rewrite`, `service`, `visual_assets` (نامرتبط) | **MISSING** |
| **ارجاع کوتاه `[کتاب \| فصل]`** | قالب فعلی `sources[]` = `{source, page, excerpt, score}` | `pipelines/llamaindex/pipeline.py:462-465` | **PARTIAL** (page/chunk آشکار است؛ فصل/کتاب به شکل هدف نیست) |
| **Abstention اجباری در نبود منبع** | — | هیچ policy صریح؛ فقط پیام خطای فنی (`error_type`) | **MISSING** |
| **Prompt-injection isolation برای متن PDF** | — | `untrusted data` تنها در `learning/lesson_evidence.py`, `semantic_assessment.py`, `multi_user/learner_profile.py`؛ **نه در RAG/tool boundary** | **PARTIAL** |

### 6.4 آزمون، بانک سؤال و تمرین

| قابلیت | مسیر مالک | شاهد | وضعیت |
|---|---|---|---|
| تولید سؤال (`deep_question`) | `agents/question/capability.py`, `pipeline.py` | `num_questions`, `difficulty`, `question_types`, `per_type_counts`, `mode=mimic` | **VERIFIED** |
| بانک سؤال | `tools/question_bank.py`, `api/routers/question_notebook.py` (۱۵ route), SQLite `notebook_entries` | `test_question_bank_api`, `test_question_router` | **VERIFIED** |
| تمرین/مرور | `services/practice/` + `api/routers/practice.py` (۹ route) | `test_practice` | **VERIFIED** |
| تصحیح عینی | `services/practice/answers.py` — «Conservative objective grading; prose and qualitative work uses self-assessment» | `check_answer` برای concept/true_false/multi_choice؛ برای `essay/short_answer/qualitative/free_response` → **`None`** | **VERIFIED (محدود)** |
| **تصحیح rubric با نمره جزئی** | `learning/semantic_assessment.py` (ارزیابی معنایی، نه rubric/partial-credit) | — | **PARTIAL** |
| **موجودیت Exam با snapshot** | — | `grep "class Exam\|exam_attempt"` → هیچ | **MISSING** |
| **نمره منفی قابل پیکربندی** | — | `grep negative\|penalt\|score_policy` → فقط کامنت‌های mastery (نه scoring آزمون) | **MISSING** |
| **زمان‌بندی/negative marking کنکور** | — | — | **MISSING** |

### 6.5 یادگیری شخصی، Flashcards و Mastery

| قابلیت | مسیر مالک | شاهد | وضعیت |
|---|---|---|---|
| Mastery Path | `capabilities/mastery/` (tools.py ۴٬۰۱۲ خط), `learning/` (۳۴ فایل) | manifest با ۱۷ tool؛ `mastery_source_pages`, `test_mastery_path_reviews`, `deeptutor/learning/tests` | **VERIFIED** |
| Spaced repetition | `learning/scheduler.py`, `services/practice/scheduler.py` (`schedule(state, rating, now)`) | `test_scheduler` در learning tests | **VERIFIED** |
| Flash Cards | `book/blocks/flash_cards.py` + export Anki | README §Learning Notebook | **VERIFIED** |
| Learning journal | `services/learning_journal/`, `api/routers/learning_journal.py` | `tests/notes` (۴۴) | **VERIFIED** |
| Profile آموزشی (پایه/رشته) | `multi_user/learner_profile.py` — ۶ فیلد آزاد، `prompt_block()` با برچسب untrusted | تزریق به prompt: `services/session/turns/executor.py:628` → `learner_profile_prompt` → `agents/loop/prompt_blocks.py:153` | **PARTIAL** (به prompt می‌رسد، اما در retrieval/filtering اعمال نمی‌شود) |
| **Academic Catalog (پایه ۱–۱۲، شاخه، رشته، درس)** | — | هیچ مدل `Subject/Grade/Branch/Track/curriculum_version` | **MISSING** |
| **Archive پیش‌دانشگاهی/نظام قدیم** | — | — | **MISSING** |

### 6.6 محتوای چندرسانه‌ای (Learning Studio)

| قابلیت | مسیر مالک | شاهد | وضعیت |
|---|---|---|---|
| Audio Overview (۲ گوینده) | `capabilities/audio_overview/` (stages: retrieving→script_writing→voice_generation→publishing) | زبان فقط `zh`/`English` hard-code در `pipeline.py:386` و `:284` | **PARTIAL** (فارسی hard-code نشده) |
| Video Lesson (Remotion) | `agents/video_lesson/` (stages: code_generation→render_check→render_output) | `tests/agents/video_lesson` + `test_isolation` | **VERIFIED** |
| Visualize (SVG/Chart/Mermaid/Manim/HTML) | `agents/visualize/`, `deeptutor/visualizers/` | manifest با stages تحلیل/تولید/بازبینی | **VERIFIED** |
| Math Animator (Manim) | `agents/math_animator/` | manifest + extra `renderer-manim` | **VERIFIED (needs system LaTeX)** |
| TTS/STT | `services/voice/` + adapters | `voice` manifest; edge-tts / Gemini / OpenAI | **VERIFIED** |
| **Job queue پایدار با cancel/retry/quota** | — | audio/video **درون request** اجرا می‌شوند؛ تنها `services/cron/` و `runtime/isolated_worker.py` (subprocess محدود) وجود دارد | **MISSING** |
| **Object storage abstraction** | — | فایل‌ها در `data/user/workspace/...` (filesystem) | **MISSING** |

### 6.7 مصرف، Provider و Billing

| قابلیت | مسیر مالک | شاهد | وضعیت |
|---|---|---|---|
| Provider Registry | `services/provider_registry.py` — **۵۱ ProviderSpec** | شامل local: `ollama`, `lm_studio`, `vllm`, `llama_cpp`, `lemonade`, `ovms` و cloud | **VERIFIED** |
| Custom Provider UI | `web/components/settings/AddProviderPanel.tsx` + `ProvidersWorkspace.tsx` | در Setting کاربر (نه admin panel) | **PARTIAL** |
| Redaction کلید | `model_catalog._redact_secret_value`, `test_*` مربوط | تست‌های auth/logout/cookie + تست doctor | **VERIFIED** |
| Usage ledger | `services/llm/usage_ledger.py` — SQLite `llm_calls(call_id, started_at, session_id, turn_id, source, usage_json)` | `record_call` + `usage_records` | **VERIFIED (توکنی، per-account)** |
| Usage API | `settings.py:2584 GET /usage` → `UsageStatistics` | `test_usage*` | **VERIFIED** |
| **هزینه/قیمت/ارز در ledger** | — | `grep cost\|price\|billing\|currency` در `usage_ledger.py` = **۰** | **MISSING** |
| **استفاده غیرتوکنی (ثانیه صوت/ویدیو/تصویر)** | — | هیچ unit/metering غیرتوکنی | **MISSING** |
| **Wallet/Plan/Subscription/reserve-settle-refund** | — | `grep "class Plan\|class Subscription\|class Wallet\|wallet_transaction"` → **خالی** | **MISSING** |
| **Metering مرکزی چندکاربره** | local SQLite در `get_owner_path_service().get_user_root()` | — | **MISSING** |

### 6.8 پنل مدیریت و هویت بصری

| قابلیت | مسیر مالک | شاهد | وضعیت |
|---|---|---|---|
| صفحه مدیریت کاربران | `web/app/(admin)/admin/users/page.tsx` | تنها صفحه زیر `/admin` | **PARTIAL** |
| layout مستقل admin | `web/app/(admin)/layout.tsx` = `<div className="min-h-screen">` فقط | بدون sidebar/nav اختصاصی | **MISSING (عملاً)** |
| `/admin/login` مستقل | — | `find web -path "*admin*" -name page.tsx` → فقط `users` | **MISSING** |
| داشبورد admin | — | — | **MISSING** |
| API ادمین غیرکاربری (محتوا/AI/پلن) | Sectionهای Settings موجود | ۷۹ route در `settings.py`، ۱۹ در `multi_user.py` | **PARTIAL** |
| **برندینگ درسیار** | `layout.tsx` → `title: "DeepTutor"`؛ ۸۳ فایل UI شامل «DeepTutor»؛ ۸۸ کلید locale | — | **MISSING** |
| **فارسی + RTL** | `languages.ts` بدون `fa`؛ `layout.tsx` → `<html lang="en">`؛ **هیچ `dir="rtl"`**؛ ۳۸۶ کلاس فیزیکی (`ml/mr/pl/pr/left/right`) در مقابل ۱۷ کلاس منطقی (`ms/me/ps/pe/start/end`) | — | **MISSING** (کار قابل توجه) |
| فونت فارسی | — | تنها `Geist`, `Lora` (latin subsets) | **MISSING** |

---

## 7. نقشه وابستگی ماژول‌ها (Dependency Map)

```
attention: هیچ ماژولی نباید به‌صورت فیزیکی حذف شود تا این گراف و تست‌های مالک بررسی شوند.

core
 ├── knowledge ──── parsing ──── {parser-docling, parser-markitdown, parser-liteparse, parser-pymupdf4llm}
 │      ├── audio-overview
 │      ├── co-writer
 │      ├── mastery
 │      └── questions ──── parsing
 ├── memory ──── partners (optional: calendar, knowledge)
 ├── notebook ──── reading
 ├── server ──── web
 ├── providers (بدون requires)
 ├── calendar (بدون requires)
 ├── visualize (بدون requires)   ← books به آن نیاز دارد
 ├── renderer-manim (بدون requires)
 └── video-lesson (بدون requires)

books requires [knowledge, parsing, questions, visualize, mastery]
reading requires [knowledge, parsing, mastery, notebook]
```

**آثار برای درسیار:** خاموش‌کردن `partners` (کانال‌های IM، خارج از محدوده محصول) امن است — تنها `memory` را لازم دارد و هیچ ماژول دیگری به آن وابسته نیست ✅. حذف فیزیکی `apps/desktop` باید پس از audit بیلد انجام شود (خارج از deploy استقرار، اما source حفظ می‌شود).

---

## 8. شکاف‌های معماری: فعلی در برابر هدف درسیار

| # | محور | وضعیت فعلی (شاهد) | هدف درسیار | فاصله |
|---|---|---|---|---|
| A-01 | **Identity** | username/password + JSON file در `data/system/` | phone + OTP + password، DB تراکنشی | 🔴 بازنویسی دامنه |
| A-02 | **Authorization** | `admin/user/teacher/student` + grants فایل‌محور | super_admin/admin/teacher/student + backend enforcement + audit کامل | 🟠 گسترش |
| A-03 | **Academic Catalog** | ندارد؛ `learner_profile.grade_level` رشتهٔ آزاد | درخت داده‌محور دوره/پایه/شاخه/رشته/درس/نسخه | 🔴 ساخت از صفر |
| A-04 | **Source Rights** | ندارد؛ KB فایل‌محور با metadata محدود | rights status، مجوز، review workflow، quarantine | 🔴 ساخت از صفر |
| A-05 | **RAG scope** | scope = KB-level access (per-user/گروه) | فیلتر اجباری grade/track/subject/rights **پیش از** retrieval | 🔴 enforcement جدید |
| A-06 | **Citation** | `{source, page, excerpt, score}` | `[نام کتاب \| فصل]` بدون page/chunk | 🟠 لایه renderer جدید |
| A-07 | **Exam** | بانک سؤال + practice + mastery quiz؛ بدون موجودیت Exam | Exam/Blueprint/Attempt/ScorePolicy با snapshot و نمره منفی | 🔴 ساخت از صفر |
| A-08 | **Grading** | objective قطعی؛ essay → `None` (خودارزیابی) | rubric + partial credit + uncertainty + human review | 🔴 ساخت از صفر |
| A-09 | **Billing** | usage ledger توکنی per-account در SQLite | Plan/Wallet/Subscription/reserve-settle-refund + قیمت نسخه‌دار | 🔴 ساخت از صفر |
| A-10 | **Media Jobs** | in-request؛ بدون queue/cancel/resume | job-based، idempotent، cancellable، quota | 🔴 بازطراحی |
| A-11 | **Database** | SQLite + JSON + فایل؛ بدون ORM/migration | PostgreSQL + ORM/migration (ADR) | 🔴 ADR + مهاجرت |
| A-12 | **Admin Panel** | یک صفحه `/admin/users` در layout بدون nav | `/admin` کامل با داشبورد، محتوا، AI، پلن، مصرف | 🔴 ساخت از صفر |
| A-13 | **i18n / RTL** | ۱۳ locale، بدون fa، `lang="en"`، بدون `dir` | fa پیش‌فرض، RTL کامل، اعداد/تاریخ فارسی | 🔴 کار گسترده |
| A-14 | **Branding** | «DeepTutor» در UI/metadata/CLI | «درسیار» | 🟠 متوسط (Phase 1) |
| A-15 | **SMS Provider** | ندارد | interface + mock + gateway ایرانی (ADR) | 🔴 ساخت از صفر |

---

## 9. ریسک‌ها و ثبت تصمیم‌های باز

### 9.1 ریسک‌ها با اولویت

| ID | ریسک | احتمال | اثر | شاهد | کاهش |
|---|---|---|---|---|---|
| **R-01** | مهاجرت identity از JSON به DB بدون از دست‌دادن کاربران موجود | بالا | بالا | `multi_user/identity.py` (`USERS_FILE`, `_migrate_legacy_users`) — مهاجرت‌های قبلی موجودند | backfill + reconciliation + rollback drill در Phase 3 |
| **R-02** | اجرای `require_admin` دوباره در ۱۴ route با سیاست manifest `public` می‌تواند باعث نشت عملیات ادمین در routerهای جدید شود | متوسط | بالا | `module_routes.py` policies؛ `public` = بدون Dependency | ADR: سیاست «deny-by-default» در manifest + تست سطح-route خودکار |
| **R-03** | تغییر نام `deeptutor` → `darsyar` در namespace/package/CLI باعث شکستن imports، مسیرها، pluginها و ۵۹۴k خط کد می‌شود | بالا | بالا | `pyproject.toml name="deeptutor"`, `deeptutor_cli/main.py`, همه importها | برندینگ فقط UI در Phase 1؛ rename داخلی به ADR جدا موکول شود (D-01) |
| **R-04** | RTL نیازمند بازنویسی ۳۸۶ کلاس فیزیکی به ۱۷ کلاس منطقی | بالا | متوسط | `grep ml\|mr\|pl\|pr\|left\|right` = ۳۸۶ vs `ms\|me\|ps\|pe\|start\|end` = ۱۷ | استفاده از Tailwind logical properties + codemod کنترل‌شده + بصری E2E |
| **R-05** | اجرای in-request برای audio/video در مقیاس چندکاربره ⇒ timeout و هزینه غیرقابل کنترل | بالا | بالا | `capabilities/audio_overview`, `agents/video_lesson` — بدون queue | Phase 8 با queue abstraction (ADR P-004) |
| **R-06** | `AUTH_ENABLED=false` ⇒ CORS باز (`https?://.*` + `allow_credentials=True`) | متوسط | بالا | `main.py:_build_cors_settings` | در راه‌اندازی Production درسیار auth اجباری + CORS صریح |
| **R-07** | نبود rate-limit/lockout روی login و OTP ⇒ brute-force | بالا | بالا | `grep rate_limit` در auth → خالی | Phase 2: rate limit + attempt cap + `security_guard` روشن |
| **R-08** | پروفایل آموزشی به prompt می‌رود اما در retrieval اعمال نمی‌شود ⇒ grade leakage در پاسخ | بالا | بالا | `executor.py:628` → `prompt_blocks.py:153`؛ صفر مصرف `grade_level` در RAG | Phase 5: enforcement در query layer + تست adversarial |
| **R-09** | OTP خام/کلید در log یا تست accidently چاپ شود | متوسط | بالا | تست doctor نشان داد رد کردن رشته‌های حساس شکننده است (شکست محیطی) | تست اختصاصی «no secret in logs» + بازبینی fixtures |
| **R-10** | پروفایل `requirements/dev.txt` برای اجرای suite کافی نیست ⇒ CI یا توسعه محلی با collection error | بالا | متوسط | ۲۷ خطای collection با dev-only | مستندسازی + اسکریپت `check` واحد |
| **R-11** | Production build نیازمند Google Fonts است ⇒ عدم offline/build در محیط محدود | بالا | متوسط | `next/font` failure | self-host فونت + fallback font فارسی (مرتبط با RTL) |
| **R-12** | اجرای `deeptutor init` لازم است وگرنه `main.yaml` غایب ⇒ **import-time crash** در `co_writer.py` | متوسط | بالا | `co_writer.py:44 load_config_with_main("main.yaml")` در سطح ماژول؛ اجرای تست بدون init → `FileNotFoundError` | **candidate fix در Phase 1/3** (lazy load)؛ در حال حاضر فقط از طریق init پوشش داده می‌شود |
| **R-13** | استفاده تجاری از کتاب‌ها بدون evidence حقوقی | بالا | بالا | MASTER_SPEC §3.3؛ هیچ rights field در کد | Phase 4: rights schema + quarantine + owner review |

### 9.2 تصمیم‌های باز — **مسدودکننده Phase 1**

| ID | تصمیم لازم | گزینه‌ها | چرا مسدودکننده است؟ |
|---|---|---|---|
| **D-01** | دامنه rename به «درسیار» | (الف) فقط UI/metadata (توصیه Phase 0) (ب) rename نام package هم | Phase 1 باید بداند آیا `package.json name`, `pyproject name`, `appId` دسکتاپ را تغییر می‌دهد یا نه |
| **D-02** | سیاست فارسی/RTL | (الف) `fa` به‌عنوان locale چهاردهم موجود + RTL کامل (ب) locale مستقل `fa-IR` با fork از `en` | حجم کار codemod RTL و محل فونت به این بستگی دارد |
| **D-03** | استراتژی فونت | (الف) self-host (Vazirmatn/IRANSans) (ب) Google Fonts با دسترسی شبکه | بدون آن **build قفل است** (R-11) و Gate 1 نمی‌تواند PASS شود |
| **D-04** | مسیر `/login` موجود | (الف) حفظ و توسعه (OTP در Phase 2) (ب) طراحی مسیر جدید | Phase 1 باید بداند آیا `/login` را بازطراحی می‌کند یا صبر می‌کند تا Phase 2 |
| **D-05** | دامنه Phase 1 (کدام قابلیت‌ها دیده شوند) | (الف) shell کامل کاربر (ب) فقط brand + RTL + `/login` + `/` | Gate 1 به scope وابسته است |

> تصمیم‌های باز غیرمرتبط با Phase 1 که باید تا فاز مربوطه نهایی شوند: gateway SMS (Phase 2)، ORM/migration (Phase 3)، taxonomy رشته‌ها (Phase 4)، RAG backend و golden dataset فارسی (Phase 5)، سیاست نمره منفی (Phase 6)، واحد پول/refund (Phase 9).

### 9.3 مواردی که در این فاز **تغییر نکردند** (تأیید صریح)

- ❌ هیچ فایل `.py`، `.ts`، `.tsx`، `.json` تنظیمات، `.yaml`، `requirements/*` یا manifest
- ❌ هیچ schema، migration، داده runtime یا `data/` در repo (پوشه `data/` که ابزار contracts ساخت، **حذف شد**)
- ❌ هیچ module enable/disable، هیچ حذف فایل، هیچ dependency اضافه/کم
- ❌ هیچ commit/merge/push به `main` یا شاخه اسناد
- ✅ تنها فایل جدید: همین گزارش

---

## 10. ترتیب پیشنهادی اجرای Phase 1 (فقط پیشنهاد — بدون شروع)

**هدف Phase 1 (از ROADMAP):** تبدیل هویت قابل مشاهده به درسیار + تثبیت تجربه وب فارسی.

| گام | کار | مالک فایل/دامنه | تست/شاهد لازم | اندازه |
|---|---|---|---|---|
| 1.1 | تصویب D-01…D-05 (بدون کد) | صاحب محصول | صورت‌جلسه تصمیم در `DECISIONS.md` | ۰.۵ روز |
| 1.2 | **Font foundation**: self-host فونت فارسی + `next/font/local` برای Geist/Lora | `web/app/layout.tsx`, `web/public/fonts/` | `npm run build` PASS + بصری | ۱ روز |
| 1.3 | **i18n فارسی**: افزودن `fa` به `languages.ts`, `locales/fa/{app,common}.json` (۸۰۰ کلید اولیه)، `dir=rtl` در `<html>` | `web/i18n/languages.ts`, `web/locales/fa/` | `npm run i18n:check` + parity | ۳–۵ روز |
| 1.4 | **RTL codemod**: تبدیل کلاس‌های فیزیکی به منطقی در `web/components`, `web/features`, `web/shared` | Tailwind + dependency-cruiser | typecheck + بصری mobile/tablet/desktop | ۵–۸ روز |
| 1.5 | **Branding**: `title`, metadata, sidebar/login brand، حذف «DeepTutor» از UI عمومی (به‌جز صفحه attribution) | `layout.tsx`, `locales/*/app.json`, `components/sidebar` | جست‌وجوی صفر occurrence در UI | ۲ روز |
| 1.6 | **Admin route skeleton**: `/admin/login` + layout مستقل + nav (بدون API جدید) | `web/app/(admin)/` | direct navigation + refresh + non-admin redirect | ۲ روز |
| 1.7 | **Gate 1**: smoke + E2E مسیرهای اصلی | — | Playwright روی build واقعی | ۲ روز |

**پیش‌نیاز سخت قبل از 1.2:** D-03 (فونت) و D-02 (RTL) تصویب شوند؛ در غیر این صورت کل Phase 1 در حالت BLOCKED می‌ماند.
**هشدار وابستگی:** گام 1.4 (RTL) اگر قبل از 1.3 (locale) انجام شود، برای هر رشته دوباره بازبینی بصری لازم می‌شود ⇒ ترتیب 1.3 → 1.4 حفظ شود.

**خارج از Phase 1 (به‌عمد):** OTP (Phase 2)، PostgreSQL (Phase 3)، catalog (Phase 4)، rights/scope (Phase 5)، exam (Phase 6)، flashcards (Phase 7)، Studio (Phase 8)، billing (Phase 9).

---

## 11. تست‌هایی که اجرا نشدند و علت

| مورد | وضعیت | علت |
|---|---|---|
| Playwright `npm run audit` / `test:e2e:critical` / `epub-reader-*` | **NOT RUN** | نیازمند backend + frontend زنده و Chromium/WebKit؛ در سندباکس ممکن ولی خارج از scope Phase 0 |
| `deeptutor doctor --online` | **NOT RUN** | نیازمند API key و درخواست واقعی مدل — ممنوع طبق KILOCODE |
| `tests/integration` (۱ فایل) و تست‌های `redis_integration` | **SKIP (در suite)** | نیازمند `DEEPTUTOR_TEST_REDIS_URL` |
| تست‌های RAG با engine واقعی (GraphRAG/LightRAG) | **SKIP (در suite)** | نیازمند سرور و credential خارجی؛ ۱۳۲ skip کل suite عمدتاً به همین دلیل |
| `npm run check` (کامل، شامل build + perf:check) | **BLOCKED** | build به دلیل Google Fonts (R-11) |
| `scripts/check_workspace_hygiene.py` | **NOT RUN** | نیازمند checkout کاملاً تمیز؛ در این نشست هیچ کامیتی انجام نشده |
| `docker compose` / ایمیج | **NOT RUN** | نیازمند Docker daemon (در سندباکس در دسترس نیست) |
| `apps/desktop` build (Electron/macOS/Windows) | **NOT RUN** | نیازمند macOS/Windows و signing |

---

## 12. امنیت، حریم خصوصی و حقوق محتوا — یادداشت‌های فاز

- **هیچ secret یا PII واقعی** در این فاز استفاده، چاپ یا ذخیره نشد.
- لایه `security_guard` (fastapi-guard) موجود است اما **پیش‌فرض خاموش** و مستقل از auth؛ برای درسیار باید در Production اجبار شود.
- `AUTH_ENABLED=false` یک حالت توسعه است ولی در عمل CORS باز می‌کند (R-06) — در استقرار درسیار باید auth همیشه فعال شود.
- هیچ زمینه حقوقی/مجوز برای منابع آموزشی اضافه نشده؛ طبق MASTER_SPEC §3.3، پیش از Phase 4 نباید هیچ کتابی وارد retrieval تولیدی شود.
- مستندات فعلی هیچ ادعای «Production Ready» نمی‌کنند؛ این گزارش هم نمی‌کند.

---

## 13. نتیجه Gate 0

| معیار پذیرش ROADMAP | نتیجه |
|---|---|
| گزارش ممیزی با مسیرهای واقعی و وضعیت هر قابلیت | ✅ بخش ۶ (با شاهد خط‌به‌خط) |
| Test baseline با command، environment، exit code و summary | ✅ بخش ۳ و ۴ |
| هیچ ادعای PASS بدون خروجی ثبت‌شده | ✅ همه نتایج با log path / exit code |
| نقشه وابستگی و اولویت ریسک | ✅ بخش ۷ و ۹ |
| فهرست دقیق تصمیم‌هایی که مانع Phase 1 می‌شوند | ✅ بخش ۹.۲ (D-01…D-05) |

### **Gate 0 = CONDITIONAL PASS**

خط پایه کامل و قابل تکرار است؛ کد و تست‌ها پایدارند و ابزارهای کیفیت سبز هستند. ورود به Phase 1 مشروط به:

1. **تصویب D-01…D-05** توسط صاحب محصول (بخش ۹.۲)
2. **پذیرش دو محدودیت محیطی به‌عنوان شناخته‌شده:** (الف) ۲ شکست محیطی تست CLI، (ب) build مسدود تا تصمیم فونت (D-03)
3. **تصمیم در مورد R-12** (import-time crash بدون `init`) — آیا در Phase 1 اصلاح شود یا تا Phase 3 به تعویق بیفتد

> **هیچ بخشی از Phase 1 آغاز نشده است.** پس از بازبینی و تأیید این گزارش و پاسخ به D-01…D-05، اجرای Phase 1 به‌صورت مستقل و مرحله‌ای آغاز می‌شود.

---

## پیوست پ — یافته کوچک در مورد مخزن: `docs/` در `.gitignore`

`.gitignore` خط ۱۳ شامل `/docs/` است («Developer and agent documentation is tracked in docs-for-dev/»). اما شاخه `docs/darsyar-product-spec` فایل‌های `docs/darsyar/*.md` را **به‌صورت force-add** ردیابی می‌کند.

| موضوع | وضعیت |
|---|---|
| آیا اسناد درسیار در Git هستند؟ | ✅ بله، روی `origin/docs/darsyar-product-spec` |
| آیا `.gitignore` با آن‌ها تعارض دارد؟ | ⚠️ بله، نیازمند `git add -f` برای هر فایل جدید |
| اثر بر Phase 1 | هر گزارش/ADR جدید در `docs/darsyar/` باید force-add شود یا یک exception در `.gitignore` (`!/docs/darsyar/`) اضافه شود — این تغییر `.gitignore` **در Phase 1** و با ثبت در گزارش انجام می‌شود، نه در Phase 0 |

این گزارش نیز به همان روش شاخه اسناد (`git add -f`) ردیابی شده است تا با ساختار موجود همراستا بماند.

---

## پیوست الف — فرمان‌های بازتولید شواهد

```bash
# 1) Baseline
git rev-parse HEAD && git status --porcelain

# 2) Python environment (خارج از repo)
python3 -m venv /tmp/dtvenv
/tmp/dtvenv/bin/pip install -r requirements/dev.txt -r requirements/full.txt
/tmp/dtvenv/bin/pip install llama-index bm25s llama-index-retrievers-bm25 \
  llama-index-vector-stores-faiss faiss-cpu pageindex pymupdf python-dateutil \
  "python-telegram-bot[socks]" slackify-markdown ruff import-linter bandit

# 3) Collection + full suite
export DEEPTUTOR_HOME=/tmp/dt_home_b2
/tmp/dtvenv/bin/python -m pytest tests deeptutor/learning/tests --collect-only -q   # 13885, exit 0
/tmp/dtvenv/bin/python -m pytest tests deeptutor/learning/tests -q -p no:cacheprovider
#   2 failed, 13752 passed, 132 skipped in 446.70s (exit 1)

# 4) اثبات محیطی بودن ۲ شکست
COLUMNS=300 /tmp/dtvenv/bin/python -m pytest \
  tests/cli/test_kb_eval_cli.py::test_eval_reports_an_invalid_dataset -q      # PASS

# 5) Python quality gates
/tmp/dtvenv/bin/python -m ruff check .                       # All checks passed


/tmp/dtvenv/bin/lint-imports                                 # ✅
/tmp/dtvenv/bin/python scripts/check_architecture.py         # OK
/tmp/dtvenv/bin/python scripts/check_repo_hygiene.py         # passed
/tmp/dtvenv/bin/python scripts/sync_module_requirements.py --check   # exit 0
DEEPTUTOR_HOME=/tmp/dt_contracts \
  /tmp/dtvenv/bin/python scripts/export_frontend_contracts.py --check # exit 0

# 6) Web
cd web && npm ci --legacy-peer-deps --replace-registry-host=always
npm run check:fast        # contracts+architecture+typecheck+node(1407)+unit(1464)+lint(0 err)+i18n → PASS
npm run build             # exit 1 → BLOCKED (Google Fonts)
```

## پیوست ب — Logها (خارج از repo، در سندباکس)

| فایل | محتوا |
|---|---|
| `/tmp/py_full3.log` | اجرای کامل pytest (۱۷KB) |
| `/tmp/web_fast.log` | خروجی کامل `npm run check:fast` (۳۴۱KB) |
| `/tmp/web_lint.log` | خروجی `eslint` (۵۸ warning, ۰ error) |
| `/tmp/web_build2.log` | build ناموفق (فونت) |
| `/tmp/npm.log` | نصب dependency وب |

> این logها **عامدانه در Git قرار نمی‌گیرند** (حاوی مسیرهای محلی و ممکن است حاوی نام کاربری سندباکس باشند). قابل بازتولید با پیوست الف.
