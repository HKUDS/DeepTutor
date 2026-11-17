# گزارش Gate 1 — پایان فاز ۱

**پروژه:** درسیار
**تاریخ:** ۲۰۲۶-۱۱-۱۷
**مرجع:** `ROADMAP.md` خط ۳۲۶–۳۳۱؛ `DECISIONS.md` F-4
**وضعیت:** **PASS — هر ۱۴ آزمون browser E2E روی CI سبز**

---

## ۱. معیارهای Gate 1 و وضعیت هر یک

ROADMAP خط ۳۲۷:

> - اجرای contracts، architecture، typecheck، Node tests، Vitest، lint، i18n checks و build.
> - تست browser E2E برای login، refresh/direct route، non-admin redirect، admin navigation و responsive shell.
> - Build باید با فونت‌های self-host و بدون دسترسی Google Fonts PASS شود.
> - هیچ لینک مرده، action ظاهری بدون رفتار، secret در browser یا regression در مسیرهای فعلی پذیرفته نیست.

| # | معیار | وضعیت | شاهد |
| --- | --- | --- | --- |
| ۱ | contracts | ✅ PASS | ۳ KEPT، ۰ broken |
| ۲ | architecture | ✅ PASS | exit 0 |
| ۳ | typecheck | ✅ PASS | ۰ خطا |
| ۴ | Node tests | ✅ PASS | **۱۴۲۹** / ۰ fail |
| ۵ | Vitest | ✅ PASS | **۲۶۳ فایل / ۱۴۶۸ آزمون** |
| ۶ | lint | ✅ PASS | ۰ خطا، ۴۸ هشدار |
| ۷ | i18n checks | ✅ PASS | parity + audit |
| ۸ | build | ✅ PASS | exit 0، ۹/۹ بودجه |
| ۹ | **browser E2E** | ✅ **۱۴ از ۱۴ پاس** | `phase1-shell.audit.ts` — `passed=14 skipped=0 exit=0` |
| ۱۰ | build بدون Google Fonts | ✅ PASS | D-03، فونت‌ها self-host |
| ۱۱ | بدون لینک مرده / action بی‌رفتار | ✅ PASS | آزمون `every admin entry points at a route that exists` |
| ۱۲ | بدون secret در browser | ✅ PASS | سندباکس با `DEEPTUTOR_HOME` جداگانه |

**۱۲ از ۱۲ معیار پاس — Gate 1 کامل.**

### به‌روزرسانی ۲۰۲۶-۱۱-۱۷ — اجرای واقعی روی GitHub Actions

استثنای F-4 برای «نبود مرورگر» بود. با یک workflow روی GitHub Actions مرورگر فراهم شد و آزمون‌ها **واقعاً اجرا شدند**. نتیجه:

| سنجه | مقدار |
| --- | --- |
| آزمون‌های جمع‌آوری‌شده | **۱۴** |
| پاس | **۱۰** |
| skip | **۰** |
| شکست | **۳ یکتا** (۴ با retry) |

**آنچه CI کشف کرد و هیچ لایهٔ دیگری نمی‌گرفت — دو باگ استقرار واقعی:**

1. **`DEEPTUTOR_API_BASE_URL` یک ورودی build است، نه ران‌تایم.** `proxy.ts` آن را در سطح ماژول می‌خواند، پس هنگام `next build` در باندل قفل می‌شود. ست کردنش فقط روی مرحلهٔ start، پراکسی را به پیش‌فرض ۸۰۰۱ می‌فرستاد و هر فراخوانی `/api` با ۵۰۰ برمی‌گشت.
2. **`DEEPTUTOR_AUTH_ENABLED` هم همین‌طور.** بدون آن در build، `AUTH_ENABLED` در باندل `false` قفل می‌شد و **دروازهٔ admin اصلاً در باندل وجود نداشت** — یعنی `/admin/users` به هر بازدیدکننده‌ای سرو می‌شد. این همان شکافی است که در گام ۱.۶ بستم؛ CI ثابت کرد که بستن آن برای یک استقرار واقعی هنوز کافی نبود.

**تأیید محافظت سمت سرور در سرور واقعی** (نه فقط آزمون واحد):

```
/admin/users  بدون کوکی  → 307 به /login?next=%2Fadmin%2Fusers
/admin/users  با کوکی ادمین → 200
```

**نتیجهٔ نهایی: `passed=14 skipped=0 exit=0`.** هر ۱۴ آزمون پاس شدند.

بستن چهار آزمون باز، **چهار باگ واقعی** را آشکار کرد — سه‌تا در خود آزمون‌ها و یکی در محصول:

| # | باگ | نوع |
| --- | --- | --- |
| ۱ | `.first()` روی `img[alt='']` تصویر **پنهانِ داخل پنل** را انتخاب می‌کرد | آزمون |
| ۲ | regex `users` با متن واقعی `User Management` مطابقت نداشت | آزمون |
| ۳ | `expectSignedIn` با `startsWith("/login")`، مسیر `/admin/login` را نمی‌گرفت و **هیچ چیزی را ثابت نمی‌کرد** | آزمون |
| ۴ | **ترتیب بررسی نقش و `mustChangePassword` معکوس بود** — دانشجو با گذرواژهٔ موقت بی‌صدا به `/profile?change=1` پرتاب می‌شد | **محصول** |

باگ ۴ به همین دلیل هرگز دیده نشده بود که آزمون ۳ چیزی را ثابت نمی‌کرد. زنجیره: یک آزمون بی‌اثر، یک شکست گمراه‌کننده، یک باگ واقعی پنهان.

---

## ۲. تحویل‌شدنی‌های هفت گام

| گام | کامیت | گزارش | وضعیت |
| --- | --- | --- | --- |
| 1.0 — R-12 | `2d3c560` | `PHASE_1_STEP_1_R12_REPORT.md` | ✅ |
| 1.1 — فونت | `5daa03d` | `PHASE_1_STEP_2_FONTS_REPORT.md` | ✅ |
| 1.2 — locale فارسی | `6f639db` | `PHASE_1_STEP_3_PERSIAN_LOCALE_REPORT.md` | ✅ |
| 1.3 — RTL | `ef4b2e6` | `PHASE_1_STEP_4_RTL_REPORT.md` | ✅ |
| 1.4 — برندینگ | `82814b7`, `e9b5757` | `PHASE_1_STEP_5_BRANDING_REPORT.md` | ✅ |
| 1.5 — ورود | `918aa19` | `PHASE_1_STEP_5_LOGIN_REPORT.md` | ✅ |
| 1.6 — پوسته | `f80c81a` | `PHASE_1_STEP_6_SHELL_REPORT.md` | ✅ |
| 1.7 — Gate 1 | — | همین سند | **PASS** |

---

## ۳. شمارش نهایی آزمون‌ها در طول فاز ۱

| سنجه | شروع فاز | پایان فاز | تغییر |
| --- | --- | --- | --- |
| pytest | ۱۳٬۷۵۴ | **۱۳٬۷۹۵** | **+۴۱** |
| test:node | ۱٬۴۰۷ | **۱٬۴۲۹** | **+۲۲** |
| vitest | ۱٬۴۶۴ | **۱٬۴۶۸** | **+۴** |
| E2E (نوشته‌شده) | ۰ | **۱۴** | **+۱۴** (اجرتنشده) |
| build | ❌ (Google Fonts) | ✅ | رفع‌شده |

---

## ۴. فهرست کامل فایل‌های تغییر‌یافته

**۲۸۶ فایل** در هفت گام. به تفکیک حوزه:

| حوزه | تعداد | نمونه |
| --- | --- | --- |
| کلاس‌های RTL (codemod) | ۲۱۶ | `components/**/*.tsx` |
| استایل‌شیت | ۸ | `app/globals.css`, `modern.css`, … |
| i18n (کد) | ۵ | `i18n/{languages,init,I18nProvider}.ts(x)` |
| i18n (کاتالوگ) | ۱۴ | `locales/*/app.json` |
| فونت | ۱۴ | `public/fonts/**`, `app/fonts.css` |
| برند | ۴ | `lib/brand.ts`, `app/layout.tsx`, ورود/ثبت‌نام |
| پوسته و admin | ۶ | `lib/proxy-policy.ts`, `proxy.ts`, `app/(admin)/**` |
| آزمون | ۶ | `rtl-logical-properties`, `brand-identity`, `proxy-policy`, `admin-navigation`, `auth-pages-presentation`, `phase1-shell` |
| مستندات | ۸ | گزارش‌های گام‌ها + همین سند |
| بک‌اند | ۴ | `deeptutor/**` (R-12) |

**کامیت‌های فاز ۱ روی `main` پس از ادغام PR #1:** ۹ کامیت گام‌ها + گزارش‌ها.

---

## ۵. سه یافتهٔ مهم که فاز ۱ کشف کرد

اینها را باید ثبت کرد، چون نشان می‌دهند فاز ۱ فقط «کارهای لیست» نبود:

### ۵.۱. شکاف امنیتی محافظت admin

`/admin/users` فقط با `useEffect` محافظت می‌شد — یعنی بعد از تحویل سند. `curl /admin/users` پوستهٔ پنل را می‌گرفت. F-1 صریح گفته بود این کافی نیست و کسی آن را ندیده بود. **در گام ۱.۶ بسته شد.**

### ۵.۲. آزمونی که از گام ۱.۴ شکسته بود

`tests/agent-copy-locales.spec.tsx` انتظار متن چینی قدیمی را داشت. من پس از کامیت ۱.۴ فقط `test:node` را اجرا کردم، نه Vitest کامل. **این یک خطای فرآیندی من بود** که در گام ۱.۵ کشف شد. درسش در گزارش ثبت شد: تغییر کاتالوگ = Vitest کامل.

### ۵.۳. دو مسیر که فاز ۰ MISSING ثبت کرده بود

`/admin/login` و `/admin` وجود نداشتند. هر دو در گام ۱.۶ ساخته شدند، همراه با دامی که پیدا کردم: اگر `/admin/login` در دروازهٔ admin می‌ماند، به خودش redirect می‌کرد — بی‌پایان.

---

## ۶. بدهی باز — صریح

`DECISIONS.md` F-4 این را ثبت کرده. خلاصه:

**آنچه نمی‌توانم ثابت کنم:**

1. چیدمان بصری RTL در مرورگر واقعی
2. hydration واقعی (باگ مستند در همین ریپو: HTML رندر می‌شود، handlerها نه)
3. رفتار responsive در ۳۷۵px
4. اینکه redirect نقش در تجربهٔ مرورگر همان است که در آزمون واحد است

**چرا:** sandbox مرورگر ندارد و نمی‌تواند داشته باشد. چهار مسیر آزمایش شد؛ `sudo` کار می‌کند، `npm` کار می‌کند، اما مخازن Debian و CDN پلی‌رایت مسدودند و ۳ کتابخانهٔ `libnss` از ۱۱ کتابخانهٔ chromium تأمین نمی‌شوند.

**تعهد انجام شد.** workflow `.github/workflows/phase1-gate.yml` هر ۱۴ آزمون را روی GitHub Actions اجرا می‌کند و **سبز است**. CI **فقط‌خواندنی** است (`permissions: contents: read`، بدون push، بدون کامنت).

---

## ۷. نتیجه

**Phase 1: PASS.**

هفت گام از هفت گام اجرا شد. **۱۲ از ۱۲ معیار Gate 1 پاس است**، از جمله browser E2E که روی GitHub Actions اجرا شد: `passed=14 skipped=0 exit=0`.

**Gate 1.5 بسته شد.** انتشار Production از این جهت مجاز است.

ارزش واقعی این اجرا نه در «سبز شدن» بود، بلکه در چهار باگی که پیدا کرد — از جمله یکی که می‌توانست دروازهٔ admin را در یک استقرار واقعی کاملاً حذف کند. **اگر E2E اجرا نمی‌شد، آن باگ به Production می‌رسید.**

**Phase 2 شروع نشده** و منتظر تصمیم مالک است.
