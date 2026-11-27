# گزارش گام ۱ فاز ۱ — رفع R-12 (بارگذاری تنبل `main.yaml`)

**پروژه:** درسیار (شاخهٔ توسعه: DeepTutor)
**تاریخ:** ۲۰۲۶-۱۱-۱۶
**مرجع تصمیم:** `DECISIONS.md` بخش F، بند F-2
**مرجع نقشهٔ راه:** `ROADMAP.md` — فاز ۱، گام ۱
**وضعیت:** انجام شد (PASS) — منتظر بازبینی مالک

---

## ۱. صورت مسئله

در نسخهٔ پایهٔ مخزن (`4c1e000`، معادل v1.7.3)، چهار روتر FastAPI فایل `main.yaml` را **در زمان import ماژول** بارگذاری می‌کردند:

| فایل | خط (پایه) | فراخوانی |
| --- | --- | --- |
| `deeptutor/api/routers/co_writer.py` | 44 | `load_main_config()` در سطح ماژول |
| `deeptutor/api/routers/knowledge.py` | 115 | همان |
| `deeptutor/api/routers/question.py` | 26 | همان |
| `deeptutor/api/routers/quiz_judge.py` | 24 | همان |

نتیجه: اگر `DEEPTUTOR_HOME` هنوز مقدار‌دهی نشده بود (`deeptutor init` اجرا نشده بود)، هر import از این ماژول‌ها — حتی import ساده در تست، ابزار CLI، یا بارگذاری پویا — با `FileNotFoundError` خام می‌شکست. این خطا **قابل اقدام** نبود: نه می‌گفت چه فایلی کم است، نه می‌گفت کاربر چه باید بکند.

### بازتولید خطا روی پایه

دستور (روی worktree پایهٔ `4c1e000` با `DEEPTUTOR_HOME` تازه و خالی):

```bash
DEEPTUTOR_HOME=/tmp/dt_fresh_base python -c "import deeptutor.api.routers.co_writer"
```

نتیجه:

```
FileNotFoundError: Configuration file not found: main.yaml
(expected under /tmp/dt_fresh_base/data/user/settings)
  at deeptutor/services/config/loader.py:106
```

خروجی: **exit code 1 — FAIL (خطا بازتولید شد)**

---

## ۲. دامنهٔ تغییر

هیچ API، مسیر، قرارداد HTTP، ساختار دیتابیس یا وابستگی تغییر نکرد. فهرست مسیرهای سرویس‌شده **عیناً** ثابت است (۷۳۱ مسیر؛ فقط اثر انگشت فایل ایندکس به‌روز شد).

### ۲.۱. `deeptutor/core/errors.py`

افزودن استثنای نوع‌دار جدید:

```python
class SetupRequiredError(ConfigurationError):
    """Raised when the app needs 'deeptutor init' before it can run."""
```

پیام خطا عمداً **قابل اقدام** است و دو چیز را نام می‌برد: فایل گم‌شده (`main.yaml`) و دستوری که آن را می‌سازد (`deeptutor init`). همچنین دو ویژگی ماشین‌خوان دارد: `config_file` و `settings_dir`.

از `ConfigurationError` ارث می‌برد تا هر کد موجودی که قبلاً `ConfigurationError` را می‌گرفت، بدون تغییر به کار خود ادامه دهد — یعنی **سازگاری عقب‌رو** حفظ شد.

### ۲.۲. `deeptutor/services/config/loader.py`

تابع جدید `load_main_config()`:

```python
def load_main_config(project_root: Path | None = None) -> dict: ...
```

- فایل را **در لحظهٔ فراخوانی** می‌خواند (نه در import).
- اگر `main.yaml` نبود، `SetupRequiredError` می‌دهد.
- از `resolve_config_path` و `_inject_runtime_paths` موجود دوباره استفاده می‌کند (بدون بازنویسی منطق).
- **هرگز** فایل پیش‌فرض نمی‌سازد و مقدار جعلی برنمی‌گرداند (الزام صریح F-2).

از `deeptutor/services/config/__init__.py` صادر شد.

### ۲.۳. چهار روتر

الگوی یکسان در هر چهار فایل:

1. بارگذاری سطح ماژول حذف شد.
2. دسترسی تنبل اضافه شد: `_main_config()` که فقط در زمان فراخوانی endpoint اجرا می‌شود.
3. توابع کمکی زبان در نبود پیکربندی به `"en"` برمی‌گردند (رفتار قبلی برای خانهٔ سالم حفظ شد؛ اولویت UI-setting اول، بعد `main.yaml`، بعد `"en"`).

نکتهٔ مهم: ترتیب اولویت اصلی حفظ شد. در `question.py` تابع `_response_language_default()` ابتدا `get_response_language()` (تنظیم UI) را امتحان می‌کند و تنها در نبود آن به `main.yaml` و سپس `"en"` می‌رسد.

---

## ۳. آزمون‌های رگرسیون

فایل جدید: `tests/api/test_r12_lazy_main_config.py` — **۶ آزمون**:

| # | آزمون | چه چیزی را تضمین می‌کند |
| --- | --- | --- |
| ۱ | `test_router_modules_import_without_an_initialized_home` | هر ۴ روتر با خانهٔ خالی import می‌شوند (مسیر «خانهٔ تازه») |
| ۲ | `test_load_main_config_explains_that_setup_is_required` | نوع خطا `SetupRequiredError` است و پیام `deeptutor init` دارد |
| ۳ | `test_load_main_config_does_not_invent_defaults` | هیچ فایلی ساخته نمی‌شود و پیش‌فرض جعلی برنمی‌گردد |
| ۴ | `test_load_main_config_reads_a_valid_config` | **مسیر عادی**: با پیکربندی معتبر، مقدار درست خوانده می‌شود |
| ۵ | `test_reply_language_helpers_fall_back_to_english_without_config` | کمکی‌های زبان بدون پیکربندی به `en`/`fa` تنزل می‌کنند |
| ۶ | `test_co_writer_current_language_survives_missing_config` | `_current_language()` بدون پیکربندی استثنا نمی‌دهد |

پوشش هر دو حالت الزامی F-2 (خانهٔ تازه + مسیر عادی با پیکربندی معتبر) تأمین شد.

---

## ۴. شواهد اجرا (دستور / exit code / نتیجه)

| # | دستور | exit code | نتیجه |
| --- | --- | --- | --- |
| ۱ | `pytest tests/api/test_r12_lazy_main_config.py` (خانهٔ خالی) | 0 | **PASS** — ۶ passed |
| ۲ | `pytest tests/api tests/services/config tests/co_writer tests/core` | 0 | **PASS** — ۲۰۰۸ passed، ۲۳ skip |
| ۳ | `pytest` (مجموعهٔ کامل طبق `testpaths`) | 1 | **PASS\*** — ۱۳۷۵۹ passed، ۱۳۲ skip، ۱ failed |
| ۴ | `ruff check .` | 0 | **PASS** — All checks passed |
| ۵ | `lint-imports` | 0 | **PASS** — ۳ قرارداد KEPT، ۰ نقض |
| ۶ | `python scripts/check_architecture.py` | 0 | **PASS** — Architecture boundaries: OK |
| ۷ | import روترها روی خانهٔ تازه (کد اصلاح‌شده) | 0 | **PASS** — هر ۴ روتر بدون خطا import شدند |

### \* دربارهٔ آن یک failure

`tests/cli/test_doctor_cli.py::test_diagnostics_never_render_credentials_or_endpoint_secrets` — این همان محدودیت محیطی مستندشده در گزارش Gate 0 است، نه رگرسیون این تغییر. علت: نام کاربری سندباکس (`user`) در مسیر `/tmp/pytest-of-user/…` ظاهر می‌شود و آزمون بررسی می‌کند رشتهٔ `user` در خروجی نباشد. با کد این تغییر هیچ ارتباطی ندارد و آزمون دست‌کاری نشد (مطابق محدودیت F-3).

### تأیید نبود رگرسیون در مجموعهٔ آزمون‌ها

فهرست کامل شناسهٔ آزمون‌ها بین پایه (`4c1e000`) و شاخهٔ فعلی مقایسه شد:

```
پایه:  13,145 شناسه
فعلی:  13,151 شناسه
تفاوت: فقط ۶ آزمون جدید R-12 — هیچ آزمونی حذف یا گم نشده
```

شمارش نهایی: ۱۳۷۵۹ passed + ۱ failed = ۱۳۷۶۰ = ۱۳۷۵۴ (پایهٔ Gate 0) + ۶ (آزمون‌های جدید). تطابق کامل.

---

## ۵. اثر انگشت ایندکس روتر

`deeptutor/api/router_index.json` تنها در فیلد `fingerprint` تغییر کرد:

```diff
-  "fingerprint": "c3b938e1...625a"
+  "fingerprint": "9334fc28...65e"
```

فهرست ۷۳۱ مسیر و ۵۵ روتر **بدون تغییر** است. علت تغییر اثر انگشت: هش محتوای فایل‌های روتر تغییر کرد (اصلاح کد)، نه مسیرها. این با اجرای `scripts/build_router_index.py` بازتولید شد.

---

## ۶. فایل‌های تغییر‌یافته

```
 deeptutor/api/router_index.json          |   2 +-
 deeptutor/api/routers/co_writer.py       |   ~30 +/-
 deeptutor/api/routers/knowledge.py       |   ~25 +/-
 deeptutor/api/routers/question.py        |   ~25 +/-
 deeptutor/api/routers/quiz_judge.py      |   ~25 +/-
 deeptutor/core/errors.py                 |   ~25 +
 deeptutor/services/config/__init__.py    |   2 +
 deeptutor/services/config/loader.py      |   ~30 +
 tests/api/test_r12_lazy_main_config.py   |  (جدید)
```

**کامیت:** `2d3c560` — `fix(config): load main.yaml lazily so routers import without init (R-12)`
طبق الزام F-2، این اصلاح در یک کامیت **مستقل** است تا در صورت نیاز به بازگشت، بدون درگیرکردن گام‌های دیگر فاز ۱ قابل revert باشد.

---

## ۷. ریسک‌ها و ملاحظات

| ریسک | سطح | کاهش‌دهنده |
| --- | --- | --- |
| کدی که قبلاً به بارگذاری در import تکیه می‌کرد | کم | جست‌وجوی کامل انجام شد؛ فقط این ۴ روتر الگوی سطح‌ماژول داشتند. سایر مصرف‌کننده‌ها (`security`, `search`, `provider_runtime`) از قبل `try/except` داشتند |
| تفاوت رفتار زبان پیش‌فرض | خیلی کم | ترتیب اولویت اصلی بازسازی شد (UI → `main.yaml` → `en`) و با آزمون پوشش داده شد |
| سرریز خطای پیکربندی به‌صورت ۵۰۰ در زمان درخواست | کم | در حالت خانهٔ راه‌اندازی‌نشده، خطا فقط هنگام فراخوانی endpoint رخ می‌دهد؛ پیام قابل اقدام است. (تبدیل آن به پاسخ HTTP 503 موضوعی برای فاز بعد است و در فاز ۱ خارج از دامنه است) |

---

## ۸. نتیجهٔ گام

**PASS** — R-12 رفع شد، خطا با نوع‌دار و پیام قابل اقدام جایگزین شد، هیچ فایل پیش‌فرضی ساخته نمی‌شود، دو حالت الزامی آزمون شد، و هیچ رگرسیونی در ۱۳٬۷۵۴ آزمون موجود ثبت نشد.

**گام بعدی فاز ۱:** میزبانی فونت‌ها به‌صورت self-host و حذف وابستگی `next/font/google` (بند D-03).
