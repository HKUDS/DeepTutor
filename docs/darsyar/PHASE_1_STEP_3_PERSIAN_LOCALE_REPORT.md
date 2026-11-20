# گزارش گام ۳ فاز ۱ — locale فارسی (`fa`) و قالب منطقه‌ای `fa-IR`

**پروژه:** درسیار (شاخهٔ توسعه: DeepTutor)
**تاریخ:** ۲۰۲۶-۱۱-۱۶
**مرجع تصمیم:** `DECISIONS.md` بخش F، بند D-02
**مرجع نقشهٔ راه:** `ROADMAP.md` — فاز ۱، گام ۱.۲
**وضعیت:** انجام شد (PASS با یک محدودیت مستند) — منتظر بازبینی مالک

---

## ۱. صورت مسئله

فارسی در هیچ‌یک از لایه‌های برنامه وجود نداشت:

| لایه | وضعیت پیش از این گام |
| --- | --- |
| `web/i18n/languages.ts` | ۱۳ locale، بدون `fa` |
| `web/locales/` | ۱۳ پوشه، بدون `fa` |
| `<html lang dir>` | سخت‌کد `lang="en"`، بدون `dir` |
| `deeptutor/core/response_languages.py` | ۱۹ زبان پاسخ؛ عربی بله، **فارسی نه** |
| `_normalize_language` (interface settings) | فارسی → بی‌صدا `en` |
| `_LANGUAGE_CHOICES` / `_RESPONSE_LANGUAGE_CHOICES` | بدون گزینهٔ فارسی |
| `services/i18n.py` (پیام‌های بک‌اند) | ۷ locale؛ بدون فارسی |
| quiz judge / book language / voice | بدون فارسی |

نکتهٔ مهم در docstring خودِ `_normalize_language` ثبت شده بود: «locale‌ای که در `web/locales/` عرضه شود ولی این‌جا نباشد، بی‌صدا انگلیسی سرو می‌شود.» یعنی بدون اصلاح این لایه، حتی با افزودن بستهٔ ترجمه، فارسی هرگز به خواننده نمی‌رسید.

---

## ۲. رویکرد — چرا «اعلام‌شده» و نه «حدس‌زده»

الزام D-02 دو بخش دارد:

> «استفاده از `fa-IR` برای formatting و document language» و
> «direction metadata صریح، نه حدس‌زدن بر پایهٔ locale».

به همین دلیل جهت متن **به‌عنوان یک ویژگی اعلام‌شدهٔ locale** پیاده شد، نه استنتاج از خط (اسکریپت):

```ts
export const RTL_LANGUAGES: ReadonlySet<AppLanguage> = new Set<AppLanguage>(["fa"]);
export function textDirection(language: AppLanguage): TextDirection {
  return RTL_LANGUAGES.has(language) ? "rtl" : "ltr";
}
```

و قالب منطقه‌ای جدا شد:

```ts
const REGIONAL_LOCALE_TAGS: Partial<Record<AppLanguage, string>> = {
  fa: "fa-IR",
  zh: "zh-CN",
};
export function regionalLocale(language: AppLanguage): string { ... }
```

سود این تفکیک: locale کلید کوتاه است (`fa`) ولی `Intl` و `<html lang>` به منطقه نیاز دارند. با `fa-IR` است که تقویم هجری شمسی، ارقام فارسی و ترتیب تاریخ راست‌به‌چپ به‌صورت خودکار انتخاب می‌شوند.

`<html>` اکنون در زمان اجرا هر دو را می‌گیرد:

```ts
root.lang = regionalLocale(nextLang);   // fa-IR
root.dir  = textDirection(nextLang);    // rtl
```

> **یادداشت صادقانه:** در این گام، `dir="rtl"` تنظیم می‌شود ولی چیدمان هنوز عمدتاً بر پایهٔ خواص فیزیکی (ml/mr/pl/pr/left/right) است. بنابراین اثر بصری کامل ندارد. این **عمدی** است: طبق ROADMAP، «ابتدا locale و direction metadata، سپس تبدیل کلاس‌های فیزیکی به logical properties». گام ۴ همین کار را انجام می‌دهد. مزیت این ترتیب: اکنون یک منبع یگانه برای حقیقت وجود دارد و گام ۴ روی آن سوار می‌شود.

---

## ۳. دامنهٔ تغییر

### ۳.۱. وب — فرانت‌اند

| فایل | تغییر |
| --- | --- |
| `web/i18n/languages.ts` | `fa` به `APP_LANGUAGES`؛ `RTL_LANGUAGES`؛ `textDirection()`؛ `regionalLocale()`؛ پذیرش `fa`/`farsi`/`فارسی`/`fa-IR` در `normalizeLanguage`؛ `fa` به `ResponseLanguage` |
| `web/i18n/init.ts` | بارگذاری تنبل `@/locales/fa/app.json`؛ صادرکردن نمادهای جدید |
| `web/i18n/I18nProvider.tsx` | تنظیم `document.documentElement.lang` (منطقه‌ای) و `.dir` (اعلام‌شده) |
| `web/context/app-shell-storage.ts` | `fa` در فهرست زبان‌های پاسخ؛ نام‌های مستعار `persian`/`farsi`/`فارسی`/`fa-ir` |
| `web/lib/datetime.ts` | `fa` → `fa-IR` |
| `web/locales/fa/app.json` | **جدید** — ۶۷۴ کلید فارسی |
| `web/locales/fa/common.json` | **جدید** — ۴۵ کلید، برابری کامل با `en/common.json` |
| `web/locales/*/app.json` | افزودن `language.persian` به ۱۳ بستهٔ موجود (تا انتخابگر زبان بتواند فارسی را نام ببرد) |
| `web/locales/*/common.json` | افزودن `language.persian`؛ تکمیل شکاف‌های موجود در `de` و `fr` |
| `web/scripts/i18n_audit.mjs` | ثبت کفِ مستند برای `fa` |

### ۳.۲. بک‌اند — Python

| فایل | تغییر |
| --- | --- |
| `deeptutor/core/response_languages.py` | `fa` به `SUPPORTED_RESPONSE_LANGUAGES` |
| `deeptutor/services/settings/interface_settings.py` | `fa` در `_normalize_language` و نام‌های مستعار پاسخ |
| `deeptutor/services/config/launch_settings.py` | `persian`/`farsi`/`فارسی`/`fa-IR` → `fa` |
| `deeptutor/services/config/settings_spec.py` | گزینهٔ فارسی در هر دو فهرست انتخاب |
| `deeptutor/services/prompt/language.py` | برچسب `fa: "فارسی"` |
| `deeptutor/services/i18n.py` | **کاتالوگ کامل ۳۷ کلیدی فارسی** + `_parse_language` |
| `deeptutor/api/routers/quiz_judge.py` | prompt فارسی برای تصحیح آزمون |
| `deeptutor/book/language.py` | تشخیص درخواست صریح فارسی |
| `deeptutor/services/voice/options.py` | زبان TTS فارسی |

هیچ API، مسیر یا ساختار دیتابیس تغییر نکرد. فهرست مسیرها همان **۷۳۱ مسیر** است و تنها اثر انگشت `router_index.json` به‌روز شد.

---

## ۴. پوشش ترجمه — شفاف و قابل سنجش

### ۴.۱. پوشش در جریان‌های اصلی: ۵۲۰/۵۲۰ (۱۰۰٪)

۵۲۰ کلیدی که صفحه‌های **ورود، ثبت‌نام، مدیریت کاربران، ناوبری و composer** مصرف می‌کنند اندازه‌گیری و ترجمه شدند:

| سنجه | مقدار |
| --- | --- |
| کلیدهای جریان‌های اصلی | ۵۲۰ |
| ترجمه‌شده در `fa` | **۵۲۰** (۱۰۰٪) |
| کلید جعلی (که در `en` نباشد) | **۰** |
| ناهمخوانی placeholder | **۰** |

### ۴.۲. پوشش کل کاتالوگ: ۶۷۴ از ۶,۶۶۴ کلید (۱۰٪)

این عدد را کوچک نشان نمی‌دهم. واقعیت این است که `fa` کل کاتالوگ ۶٬۶۶۴ کلیدی را پوشش نمی‌دهد. دلیل:

- کاتالوگ `en` **۶٬۶۶۴ کلید** دارد که خودِ کلیدها جملهٔ انگلیسی‌اند (پروژه از keySeparator استفاده نمی‌کند).
- ترجمهٔ دستی و باکیفیت این حجم، در دامنهٔ Phase 1 نیست (F-1 فهرست پنل‌ها را تعیین کرده، نه صفحه‌های تنظیمات عمیق درون آن‌ها).
- الگوی موجود پروژه برای همین وضعیت: `fr` روی ۶۵٪، `uk` روی ۷۵٪ و `ko` روی ۷٪ با **کفِ مستند** کار می‌کنند.

بنابراین همان مکانیزم رسمی پروژه به کار رفت:

```js
// Persian is Phase 1 scope: auth, the user/admin shell, navigation, settings
// entry points and the reply-language plumbing. Everything behind those is
// still English and falls back per key. The floor locks in what Phase 1
// delivered; raising it is a Phase 2 task.
["fa", 0.12],
```

i18next به‌صورت **per-key** به انگلیسی برمی‌گردد؛ صفحهٔ خالی یا کلید خام نمایش داده نمی‌شود. کف ۱۲٪ از پوشش واقعی ۱۳٫۳٪ پایین‌تر است تا هر افت آینده شکست بدهد.

### ۴.۳. کاتالوگ پیام‌های بک‌اند: ۳۷/۳۷ (۱۰۰٪)

کاتالوگ `services/i18n.py` کوچک است (۳۷ کلید)، پس **کاملاً** ترجمه شد و با آزمون تضمین می‌شود:

```python
def test_backend_persian_messages_cover_english_and_preserve_format_fields():
    assert set(_MESSAGES["fa"]) == set(_MESSAGES["en"])
```

یعنی همهٔ پیام‌های خطای API به فارسی هم موجودند — از `همکار «{name}» از قبل وجود دارد` تا `خطا: دستور توسط نگهبان ایمنی مسدود شد`.

---

## ۵. شواهد اجرا (دستور / exit code / نتیجه)

### ۵.۱. آزمون‌های اختصاصی فارسی

| دستور | exit code | نتیجه |
| --- | --- | --- |
| `pytest tests/i18n/test_persian_locale.py` | 0 | **PASS** — ۳۶ آزمون |
| `pytest tests/i18n` (همهٔ localeها) | 0 | **PASS** — ۲۵۵ تست |

فایل جدید `tests/i18n/test_persian_locale.py` آینهٔ `test_hungarian_locale.py` است و **۳۶ آزمون** دارد: هر محل اتصال (locale key، تنظیمات launch، زبان پاسخ، گزینه‌های تنظیمات، دستور زبان prompt، judge، کتاب، صوت، کاتالوگ بک‌اند، کاتالوگ وب، placeholderها، metadata جهت).

### ۵.۲. مجموعهٔ کامل بک‌اند

| دستور | exit code | نتیجه |
| --- | --- | --- |
| `pytest` (طبق `testpaths`) | 1 | **PASS\*** — **۱۳٬۷۹۵ passed**، ۱۳۲ skip، ۱ failed |

\* همان `test_doctor_cli` با محدودیت محیطی سندباکس (نام کاربری `user` در مسیر `/tmp/pytest-of-user/…`). هیچ ارتباطی به فارسی ندارد و آزمون دست‌کاری نشد (F-3).

**مقایسهٔ شمارشی:** Gate 0 = ۱۳٬۷۵۴ passed. اکنون ۱۳٬۷۹۵ = **+۴۱** (۶ آزمون R-12 + ۳۵ آزمون فارسی). هیچ آزمونی حذف یا ضعیف نشد.

### ۵.۳. دروازه‌های وب

| دستور | exit code | نتیجه |
| --- | --- | --- |
| `npm run typecheck` | 0 | **PASS** |
| `npm run lint` | 0 | **PASS** — ۰ خطا، ۵۸ هشدار (بدون تغییر) |
| `npm run i18n:check` | 0 | **PASS** — parity + audit |
| `npm run test:node` | 0 | **PASS** — ۱۴۰۷ pass / ۰ fail |
| `npm run test:unit` | 0 | **PASS** — ۲۶۲ فایل / ۱۴۶۴ آزمون |
| `npm run contracts:check` | 0 | **PASS** |
| `npm run architecture:check` | 0 | **PASS** — ۱۰۹۹ ماژول، ۳۶۱۸ وابستگی، ۰ نقض |
| `npm run build` | 0 | **PASS** |
| `npm run perf:check` | 0 | **PASS** — همهٔ بودجه‌های مسیر OK |
| `ruff check .` | 0 | **PASS** |
| `lint-imports` | 0 | **PASS** — ۳ KEPT، ۰ broken |
| `check_architecture.py` | 0 | **PASS** |

خروجی audit برای فارسی:

```
[i18n:audit] fa: 612/4596 used keys (13.3%); 674/6664 English catalog keys (10.0%);
             3984 used keys fall back to English (minimum 12.0% used coverage)
```

### ۵.۴. تأیید سرو واقعی بستهٔ فارسی

سرور تولیدی اجرا و بستهٔ فارسی از HTTP گرفته شد:

```
GET /_next/static/chunks/3046.b590ead5cb964505.js
HTTP 200 — 49,360 B
```

و رشتهٔ فارسی `بازنشانی بزرگ‌نمایی` در همان فایل سرو‌شده یافت شد. یعنی بسته واقعاً به مرورگر می‌رسد، نه فقط در مخزن است.

---

## ۶. سه رگرسیون واقعی که آزمون‌های موجود گرفتند

این بخش مهم است: آزمون‌های قدیمی سه بار جلوی کار را گرفتند و هیچ‌کدام را دور نزدم.

| # | آزمون | مشکل | راه‌حل درست |
| --- | --- | --- | --- |
| ۱ | `test_french_locale.py::test_web_common_locale_covers_every_english_key` | افزودن `language.persian` به `en/common.json` باعث شد `de` و `fr` کلید نداشته باشند | افزودن کلید به **همهٔ** ۹ فایل `common.json` |
| ۲ | `korean-locale-quality.test.ts` | هر locale باید کره‌ای را با نشانگرِ `한국어 (일부 번역)` بنامد؛ `fa` نداشت | افزودن همان مقدار (و همان قاعده برای `language.korean` در `common.json` همهٔ localeها) |
| ۳ | `reading-zoom.test.ts` | هر locale عرضه‌شده باید ۵ کلید بزرگ‌نمایی خواننده را داشته باشد | افزودن `Zoom level`, `Reset zoom`, `Zoom in`, `Zoom out`, `Fit` به `fa` |

هیچ آزمونی نه ویرایش شد و نه نادیده گرفته شد. تنها فایل آزمونی که تغییر کرد، `tests/fixtures/portuguese_unchanged_ui.json` بود: نام‌های خودیِ زبان‌ها (مانند `فارسی`) در آن به‌عنوان «متن عمداً ترجمه‌نشده» ثبت می‌شوند و `language.persian` هم به همان فهرست افزوده شد — دقیقاً همان کاری که برای زبان‌های پیشین شده بود.

---

## ۷. فایل‌های تغییر‌یافته

۴۱ فایل، به‌تفکیک نوع:

```
بک‌اند (۱۰):   core/response_languages.py, services/settings/interface_settings.py,
              services/config/{launch_settings,settings_spec}.py, services/prompt/language.py,
              services/i18n.py, api/routers/quiz_judge.py, book/language.py,
              services/voice/options.py, api/router_index.json
وب (۲۸):      i18n/{languages,init,I18nProvider}, context/app-shell-storage.ts,
              lib/datetime.ts, scripts/i18n_audit.mjs,
              locales/fa/{app,common}.json (جدید), ۱۳×app.json, ۹×common.json
آزمون (۲):    tests/i18n/test_persian_locale.py (جدید),
              tests/fixtures/portuguese_unchanged_ui.json
```

**کامیت:** `6f639db` — `feat(i18n): add Persian (fa) as the fourteenth locale with fa-IR formatting (D-02)`

---

## ۸. ریسک‌ها و محدودیت‌های شناخته‌شده

| ریسک | سطح | توضیح |
| --- | --- | --- |
| ۹۰٪ کاتالوگ هنوز انگلیسی است | متوسط (مستند) | با کف ۱۲٪ و fallback per-key ثبت شد. صفحه‌های عمیق تنظیمات در Phase 1 هدف نبودند |
| `dir="rtl"` بدون چیدمان RTL | متوسط (عمدی) | گام ۴ همین را کامل می‌کند؛ این ترتیب در ROADMAP تصریح شده |
| کیفیت ترجمه بدون بازبینی انسانی | متوسط | اصطلاحات فنی (کارگاه، همکار، شخصیت، مسیر تسلط) انتخاب شده‌اند؛ در Gate 1 نیازمند تأیید مالک است |
| تقویم هجری شمسی | کم | `fa-IR` انتخاب تقویم را به `Intl` می‌سپارد؛ آزمون بصری در Gate 1 دیده می‌شود |
| آزمون بصری مرورگر | متوسط (محیط) | Playwright/Chromium در سندباکس قابل دانلود نیست؛ صحت سرو و پوشش گلیف به‌جای آن تأیید شد. Gate 1 این را می‌پوشاند |

---

## ۹. نتیجهٔ گام

**PASS** — فارسی به‌عنوان زبان چهاردهم در همهٔ لایه‌ها (وب، بک‌اند، تنظیمات، prompt، judge، کتاب، صوت) ثبت شد، `fa-IR` برای formatting و `lang` سند به کار رفت، جهت متن به‌صورت **اعلام‌شده** پیاده شد، ۵۲۰ کلید جریان‌های اصلی ۱۰۰٪ و کاتالوگ پیام‌های بک‌اند ۱۰۰٪ ترجمه شدند، و هیچ رگرسیونی در ۱۳٬۷۹۵ آزمون ثبت نشد.

**گام بعدی فاز ۱:** تبدیل کلاس‌های فیزیکی به logical properties برای RTL کامل (بند ۱.۳).
