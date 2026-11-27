# گزارش گام ۲ فاز ۱ — میزبانی خودی فونت‌ها و حذف `next/font/google`

**پروژه:** درسیار (شاخهٔ توسعه: DeepTutor)
**تاریخ:** ۲۰۲۶-۱۱-۱۶
**مرجع تصمیم:** `DECISIONS.md` بخش F، بند D-03
**مرجع نقشهٔ راه:** `ROADMAP.md` — فاز ۱، گام ۲
**وضعیت:** انجام شد (PASS) — منتظر بازبینی مالک

---

## ۱. صورت مسئله

`web/app/layout.tsx` فونت‌ها را با `next/font/google` بارگذاری می‌کرد:

```tsx
import { Geist, Lora } from "next/font/google";
```

`next/font/google` فایل‌های فونت را **در زمان build** از `fonts.googleapis.com` می‌گیرد. نتیجه:

- build تولیدی به دسترسی اینترنت خروجی وابسته بود؛
- در محیط بسته/آفلاین یا پشت فایروال، build شکست می‌خورد؛
- در گزارش Gate 0 این تنها **دروازهٔ مسدود** وب ثبت شد (`npm run build` → FAIL).

افزون بر آن، هیچ فونت فارسی‌ای وجود نداشت: `layout.tsx` مقدار `lang="en"` را سخت‌کد کرده بود و در زنجیرهٔ فونت Tailwind هیچ چهرهٔ فارسی نبود.

---

## ۲. راه‌حل

فونت‌ها به‌صورت **خودی** (self-host) درون مخزن قرار گرفتند و `next/font/google` کاملاً حذف شد.

### ۲.۱. فونت‌های افزوده‌شده

هر سه خانواده متغیر (variable) و دارای پروانهٔ **SIL OFL 1.1** هستند — یعنی بازتوزیع با حفظ پروانه مجاز است.

| خانواده | کاربرد | نسخهٔ بسته | حجم |
| --- | --- | --- | --- |
| Geist Variable | رابط کاربری (sans) | `@fontsource-variable/geist@5.3.0` | 3 فایل |
| Lora Variable | متن‌های prose (serif) | `@fontsource-variable/lora@5.3.0` | 5 فایل |
| **Vazirmatn Variable** | **فارسی** | `@fontsource-variable/vazirmatn@5.3.0` | 3 فایل |

مجموع: **۳۸۰ کیلوبایت** فایل `woff2` در `web/public/fonts/`.
پروانه‌ها در `web/public/fonts/licenses/` (سه فایل `OFL-*.txt`) قرار گرفتند و در `THIRD_PARTY_NOTICES.md` ثبت شدند.

### ۲.۲. `web/app/fonts.css` (جدید)

- قواعد `@font-face` برای هر سه خانواده، با `font-weight: 100 900` (Vazirmatn/Geist) و `400 700` (Lora) — بازهٔ کامل محور متغیر.
- `unicode-range` از خود بستهٔ بالا‌دستی کپی شد تا مرورگر فقط برش‌های لازم را دانلود کند. برای Lora برش‌های `latin`, `latin-ext`, `math`, `symbols` (فرمول‌ها و فلش‌ها وسط جمله به فونت پیش‌فرض مرورگر نمی‌افتند).
- تعریف دوبارهٔ توکن‌های `--font-sans` و `--font-serif` با **همان نام‌هایی** که `next/font` تزریق می‌کرد. به این ترتیب تمام ارجاع‌های موجود `var(--font-sans)` در `tailwind.config.js`، `globals.css` و CSS ویژگی‌ها **بدون هیچ تغییری** به کار خود ادامه می‌دهند.
- دو توکن جدید فقط برای فارسی: `--font-fa-sans` و `--font-fa-serif` که Vazirmatn را اول می‌آورند.
- قواعد `:lang(fa)` هم‌سبک با الگوی موجود `:lang(ja)`/`:lang(ko)` در `globals.css`.

### ۲.۳. `web/app/layout.tsx`

```diff
-import { Geist, Lora } from "next/font/google";
 import "./globals.css";
+import "./fonts.css";
...
-const fontSans = Geist({ subsets: ["latin"], display: "swap", variable: "--font-sans" });
-const fontSerif = Lora({ subsets: ["latin"], display: "swap", variable: "--font-serif" });
...
-      className={`${fontSans.variable} ${fontSerif.variable}`}
```

توجه: `html` عنصر دیگر کلاس فونت ندارد، ولی `body` همچنان `className="font-sans"` دارد که از توکن `--font-sans` تعریف‌شده در `fonts.css` تغذیه می‌شود. **ظاهر صفحه تغییر نمی‌کند.**

### ۲.۴. `web/tailwind.config.js`

`Vazirmatn` به‌عنوان دومین چهره در هر دو زنجیرهٔ `sans` و `serif` اضافه شد (پس از `var(--font-sans)`/`var(--font-serif)` و پیش از چهره‌های CJK). دلیل: در صفحهٔ `fa` باید گلیف فارسی پیش از آنکه یک چهرهٔ چینی مدعی آن شود، در Vazirmatn حل شود؛ در حالی که برای متن لاتین همچنان Geist/Lora اول است.

---

## ۳. شواهد اجرا (دستور / exit code / نتیجه)

### ۳.۱. دروازه‌ای که قبلاً مسدود بود

| دستور | exit code | نتیجه |
| --- | --- | --- |
| `npm run build` | 0 | **PASS** — «Compiled successfully»، جدول کامل مسیرها تولید شد |
| `npm run perf:check` | 0 | **PASS** — همهٔ ۹ بودجهٔ مسیر OK |

**این نخستین باری است که `npm run build` در این پروژه PASS می‌شود.** در Gate 0 همین دستور FAIL بود.

نتیجهٔ بودجهٔ مسیرها (نمونه):

```
OK   /chat                                            1086KB / budget 1100KB
OK   /settings                                         125KB / budget  840KB
OK   /co-writer                                        466KB / budget  470KB
OK   root-app-shell                                    343KB / budget  390KB
```

هیچ مسیری از بودجه عبور نکرد. مصرف فونت جدید در بودجهٔ JS اثری ندارد (فونت‌ها در `public/` هستند، نه در باندل).

### ۳.۲. بقیهٔ دروازه‌های وب

| دستور | exit code | نتیجه |
| --- | --- | --- |
| `npm run typecheck` | 0 | **PASS** |
| `npm run lint` | 0 | **PASS** — ۰ خطا، ۵۸ هشدار (بدون تغییر نسبت به Gate 0) |
| `npm run contracts:check` | 0 | **PASS** |
| `npm run architecture:check` | 0 | **PASS** — ۱۰۹۸ ماژول، ۳۶۱۷ وابستگی، ۰ نقض |
| `npm run i18n:check` | 0 | **PASS** |
| `npm run test:node` | 0 | **PASS** — ۱۴۰۷ pass / ۰ fail |
| `npm run test:unit` (vitest) | 0 | **PASS** — ۲۶۲ فایل / ۱۴۶۴ آزمون |

همهٔ اعداد **عیناً** برابر Gate 0 هستند: هیچ آزمونی حذف، ضعیف یا نادیده گرفته نشد.

### ۳.۳. تأیید سرو فونت‌ها

سرور تولیدی (`next start`) اجرا و هر سه فایل با `curl` درخواست شد:

| فایل | پاسخ |
| --- | --- |
| `/fonts/geist/geist-latin-wght-normal.woff2` | HTTP 200 — 29,400 B — `font/woff2` |
| `/fonts/lora/lora-latin-wght-normal.woff2` | HTTP 200 — 37,788 B — `font/woff2` |
| `/fonts/vazirmatn/vazirmatn-arabic-wght-normal.woff2` | HTTP 200 — 46,308 B — `font/woff2` |

CSS کامپایل‌شده بررسی شد: بلوک‌های `@font-face` با `font-family: Geist` / `Lora` / `Vazirmatn` و توکن‌ها (`--font-fa-sans`, `--font-fa-serif`) و ورود `Vazirmatn` در زنجیرهٔ Tailwind **همه حاضرند**.

### ۳.۴. پوشش گلیف فارسی (تأیید محتوایی)

با `fontTools` جدول `cmap` هر فایل بازرسی شد:

| فایل | تعداد گلیف | نمونهٔ آزمون (پچگژکی۰۱۲۹،؛؟) | محور متغیر |
| --- | --- | --- | --- |
| `vazirmatn-arabic-wght-normal.woff2` | 366 | **۰ گم‌شده** | `wght` 100–900 |
| `vazirmatn-latin-wght-normal.woff2` | 229 | ۰ گم‌شده | `wght` 100–900 |
| `geist-latin-wght-normal.woff2` | 225 | ۰ گم‌شده | `wght` 100–900 |
| `lora-latin-wght-normal.woff2` | 226 | ۰ گم‌شده | `wght` 400–700 |

یعنی حروف فارسی، اعداد فارسی (۰–۹)، علائم نگارشی فارسی (، ؛ ؟) و نیم‌فاصله همگی در فونت موجودند.

> **محدودیت محیط:** عکس‌گرفتن از رندر واقعی با Playwright ممکن نشد، چون دانلود Chromium توسط محدودیت خروجی شبکهٔ سندباکس مسدود است. به‌جای آن، سرو صحیح فایل‌ها (HTTP 200 + نوع MIME درست)، حضور قواعد CSS در خروجی build، و پوشش گلیف با بازرسی مستقیم فایل تأیید شد. **آزمون بصری مرورگر در Gate 1 انجام خواهد شد.**

### ۳.۵. یادداشت فنی دربارهٔ حافظه

اولین اجرای `npm run build` با exit code 1 و **بدون هیچ پیام خطایی** تمام شد. بررسی `dmesg` نشان داد دلیل، **کشته‌شدن فرایند توسط OOM** است، نه خطای کد:

```
Out of memory: Killed process … (next-build (v16) …
```

سندباکس ۳٫۹ گیگابایت RAM و ۲ هسته دارد. با محدودکردن heap گره، build کامل شد:

```bash
NODE_OPTIONS="--max-old-space-size=2560" npm run build   # exit 0
```

این محدودیت محیط است، نه نقص پروژه؛ روی ماشین با حافظهٔ بیشتر نیازی به این متغیر نیست. در گزارش Gate 1 ثبت خواهد شد.

---

## ۴. فایل‌های تغییر‌یافته

```
 THIRD_PARTY_NOTICES.md              | +17   (ثبت سه خانوادهٔ فونت و پروانه)
 web/app/fonts.css                   | جدید  (@font-face + توکن‌ها + :lang(fa))
 web/app/layout.tsx                  | ۱٬۴ ±  (حذف next/font/google، import fonts.css)
 web/tailwind.config.js              | ۶ ±   (Vazirmatn در زنجیرهٔ sans/serif)
 web/public/fonts/licenses/OFL-*.txt | ۳ فایل جدید
 web/public/fonts/geist/*.woff2      | ۳ فایل
 web/public/fonts/lora/*.woff2       | ۵ فایل
 web/public/fonts/vazirmatn/*.woff2  | ۳ فایل
```

**کامیت:** `5daa03d` — `feat(web): self-host Geist, Lora and Vazirmatn; drop next/font/google (D-03)`

هیچ وابستگی npm افزوده یا حذف نشد (`next/font/google` بخشی از خود Next است، نه بستهٔ جدا).

---

## ۵. ریسک‌ها و ملاحظات

| ریسک | سطح | توضیح / کاهش‌دهنده |
| --- | --- | --- |
| تفاوت جزئی رندر با نسخهٔ Google | خیلی کم | همان فایل‌های اصلی و همان وزن‌های متغیر؛ تنها منبع تغییر کرده. `font-display: swap` حفظ شد |
| افزایش ۳۸۰KB به مخزن | کم | فقط زیرمجموعه‌های استفاده‌شده؛ بقیهٔ برش‌ها (سیریلیک، ویتنامی، …) حذف شدند |
| نبود آزمون خودکار برای رگرسیون فونت | متوسط | Gate 1 شامل smoke بصری است. در صورت نیاز می‌توان در فاز بعد آزمونی افزود که `next/font/google` را ممنوع کند |
| `html` دیگر کلاس فونت ندارد | خیلی کم | `body` همچنان `font-sans` دارد و توکن‌ها در `:root` تعریف شده‌اند؛ استایل نهایی یکسان است |

### نکتهٔ مربوط به گام بعدی

هنگام کار روی این گام مشخص شد که چهره‌های CJK در `globals.css` با انتخابگر `:lang(ja)`/`:lang(ko)` تعیین می‌شوند. همین الگو برای `fa` به کار رفت تا در گام‌های بعدی (locale فارسی + RTL) نیازی به بازنویسی دوباره نباشد. **`lang` روی `<html>` هنوز `"en"` است** و تغییر آن بخشی از گام ۳ (locale فارسی) خواهد بود.

---

## ۶. نتیجهٔ گام

**PASS** — وابستگی build به Google Fonts حذف شد، `npm run build` برای نخستین بار PASS شد، تمام دروازه‌های وب با اعداد بدون تغییر سبز ماندند، و Vazirmatn با پوشش کامل گلیف فارسی و پروانهٔ ثبت‌شده در مخزن جای گرفت.

**گام بعدی فاز ۱:** افزودن locale فارسی (`fa`) و قالب منطقه‌ای `fa-IR` (بند D-02).
