# گزارش گام ۱.۵ فاز ۱ — بازطراحی ظاهری ورود و ثبت‌نام

**پروژه:** درسیار
**تاریخ:** ۲۰۲۶-۱۱-۱۷
**مرجع:** `ROADMAP.md` — فاز ۱، گام ۱.۵؛ `DECISIONS.md` D-04
**وضعیت:** انجام شد (PASS) — منتظر بازبینی مالک

---

## ۱. خواستهٔ دقیق

ROADMAP خط ۳۱۷:

> **1.5 — Functional login presentation**
> - مسیر `/login` و flow فعلی username/password حفظ شود.
> - ظاهر و برند بازطراحی شود؛ ورود OTP تا Phase 2 خارج از scope است.

دو قید و یک اختیار:
- **قید ۱:** مسیر `/login` بماند.
- **قید ۲:** flow فعلی username/password دست‌نخورده بماند.
- **اختیار:** ظاهر بازطراحی شود.

پس این یک کار **صرفاً ظاهری** است. هر تغییری در منطق، نقض خواسته است.

---

## ۲. نقطهٔ شروع

قبل از این گام، `/login` یک کارت کوچک وسط‌چین بود:

```
┌─────────────────────────┐
│      DeepTutor          │   ← (در گام ۱.۴ به درسیار تبدیل شد)
│  Sign in to your account │
│  ┌───────────────────┐   │
│  │  [form]           │   │
│  └───────────────────┘   │
└─────────────────────────┘
```

این از هر اپلیکیشن دیگری قابل تفکیک نبود. برای محصولی که حرفش «کمک به یادگیری» است، اولین برخورد ضعیف بود. صفحهٔ `/register` دقیقاً همین ساختار را داشت.

---

## ۳. آنچه ساخته شد

### ۳.۱. چیدمان دوستونه

`app/(auth)/layout.tsx` به یک grid دوستونه تبدیل شد:

```diff
-<div className="min-h-screen flex items-center justify-center bg-[var(--background)]">
+<div className="min-h-screen grid lg:grid-cols-2 bg-[var(--background)]">
```

از `lg` به بالا: پنل برند در یک ستون، فرم در ستون دیگر.
زیر `lg`: پنل پنهان می‌شود و فرم تمام عرض را می‌گیرد.

### ۳.۲. پنل برند — `components/auth/AuthBrandPanel.tsx`

کامپوننت مشترک بین `/login` و `/register`. سه بخش:

| بخش | محتوا |
| --- | --- |
| بالا | نشان برند + نام «درسیار» |
| میان | یک جملهٔ ارزش: «همراهی برای یادگیری، هم‌قدم با شما» |
| پایین | سه مزیت با بولت |

**چرا این‌جا؟** پیش از ورود، این تنها جایی است که محصول می‌تواند بگوید *چیست*. یک کارت خالی فقط می‌گفت «وارد شو».

### ۳.۳. بازگشت وردمارک در موبایل

پنل در موبایل پنهان است، پس کاربر موبایل نمی‌فهمید کدام محصول را باز کرده. برای همین یک نوار کوچک وردمارک با `lg:hidden` در بالای فرم اضافه شد.

### ۳.۴. تیتر بازنویسی شد

```diff
-<h1>درسیار</h1>
-<p>Sign in to your account</p>
+<h1>Sign in to your account</h1>
+<p>Welcome back</p>
```

نام محصول به پنل برند منتقل شد (جایی که هویت را تعریف می‌کند)، و تیتر فرم اکنون می‌گوید کاربر چه کاری باید بکند. همان کار برای `/register` با «Start learning in a minute».

---

## ۴. رفتار دست‌نخورده — و چگونه تضمین شد

این مهم‌ترین بخش است. من فقط **پوسته** را عوض کردم؛ بدنهٔ فرم کلمه‌به‌کلمه از فایل اصلی برداشته شد.

| مورد | وضعیت |
| --- | --- |
| `handleSubmit` | دست‌نخورده |
| `login()` و مدیریت خطا | دست‌نخورده |
| `mustChangePassword` → `/profile?change=1` | دست‌نخورده |
| `resolvedNext()` و `inheritLoginHash` | دست‌نخورده |
| `fetchAuthStatus` / `checkIsFirstUser` redirect | دست‌نخورده |
| پارامتر `?registered=1` | دست‌نخورده |
| مسیر `/login` و `/register` | دست‌نخورده |

**بازگشت ناخواسته:** در تلاش اول، `npx prettier` را روی فایل اجرا کردم. `prettier` در `package.json` نیست و `.prettierrc.json` با `singleQuote: true` با کل کدبیس (که از `"` استفاده می‌کند) ناسازگار است. نتیجه ۱۴۶ خط نویز شد. `git checkout` زدم و دستی نوشتم. **هیچ فرمت غیرمرتبطی در کامیت نیست.**

---

## ۵. RTL — با logical properties

هیچ کلاس فیزیکی اضافه نشد:

| جایگزین فیزیکی | آنچه استفاده شد |
| --- | --- |
| `border-r` | **`border-e`** |
| `ml-*` / `mr-*` | `gap-*` و `mx-auto` |
| `text-left` | جهت از `dir` روی `<html>` می‌آید |

صفحه با `dir` ریشه آینه می‌شود، بدون قاعدهٔ `[dir=rtl]` اضافی. این با کاری که در گام ۱.۳ انجام شد هم‌راستاست.

---

## ۶. کلیدهای جدید کاتالوگ

هشت رشتهٔ جدید اضافه شد. چون `keySeparator: false` است، کلید عیناً همان جملهٔ انگلیسی است.

| کلید | fa |
| --- | --- |
| `Welcome back` | خوش آمدید |
| `A learning companion that works the way you do` | همراهی برای یادگیری، هم‌قدم با شما |
| `Agent-native learning companion` | همراه یادگیری عامل‌محور |
| `Study from your own sources` | از منابع خودتان یاد بگیرید |
| `Practice and track what you have learned` | تمرین کنید و پیشرفتتان را ببینید |
| `Always know which source an answer came from` | همیشه بدانید پاسخ از کدام منبع آمده |
| `Start learning in a minute` | شروع یادگیری در یک دقیقه |
| `Darsyar` | درسیار |

هر هشت کلید در **هر ۱۴ باندل** اضافه شدند تا `i18n:parity` پاس شود.

---

## ۷. دو نقص واقعی که این گام آشکار کرد

این بخش را باید جدی خواند: **گام ۱.۵ دو باگ از گام ۱.۴ را پیدا کرد که در زمان خودشان دیده نشده بودند.**

### ۷.۱. آزمون چینی که شکسته بود

`tests/agent-copy-locales.spec.tsx` انتظار داشت:

```ts
).toBe("DeepTutor 通过 consult_subagent 调用本机 Codex 时使用的模型…");
```

اما گام ۱.۴ مقدار `zh` را به `Darsyar` تغییر داده بود. **این آزمون از آن زمان شکسته بود و من ندیدمش** — چون پس از کامیت گام ۱.۴، Vitest کامل را دوباره اجرا نکردم و فقط `test:node` را دیدم.

**درس:** پس از هر تغییر کاتالوگ، Vitest کامل باید اجرا شود، نه فقط `test:node`.

**اصلاح:** انتظار به `Darsyar` تغییر کرد — تطبیق همچنان دقیق و کامل است.

### ۷.۲. regex آزمون‌های E2E

سه regex در `tests/e2e/` متن ردیف فعالیت را با `DeepTutor` تطبیق می‌دادند:

```diff
-/DeepTutor (?:Exploring|Reasoning|Planning|Quizzing|Reflecting|responded)|Tool Calling/i
+/(?:Darsyar|درسیار|DeepTutor) (?:Exploring|Reasoning|Planning|Quizzing|Reflecting|responded)|Tool Calling/i
```

این‌ها در سندباکس اجرا نمی‌شوند (Playwright نصب نمی‌شود) و بنابراین در گام ۱.۴ دیده نشدند. اکنون هر سه شکل را می‌پذیرند.

### ۷.۳. آزمون پرتغالی

`tests/i18n/test_portuguese_locale.py` تلاش کرد کلیدهای تازه‌ام را بگیرد:

```
assert ['Welcome bac...me from', ...] == []
```

این آزمون درست کار می‌کرد. دو اقدام:
- هفت رشته به پرتغالی واقعی ترجمه شد (نه placeholder انگلیسی).
- `"Darsyar"` به `tests/fixtures/portuguese_unchanged_ui.json` اضافه شد، چون نام برند ترجمه نمی‌شود بلکه **حمل** می‌شود. fixture به‌درستی مقدار انگلیسی را هم ذخیره می‌کند تا تغییر بعدی نام محصول، متن جدید را بی‌سروصدا معاف نکند.

---

## ۸. شواهد اجرا

| # | دستور | exit | نتیجه |
| --- | --- | --- | --- |
| ۱ | `npm run typecheck` | 0 | **PASS** |
| ۲ | `npm run lint` | 0 | **PASS** — ۰ خطا، ۴۷ هشدار (۴۴ + ۳ از فایل جدید) |
| ۳ | `npm run test:node` | 0 | **PASS** — ۱۴۱۹ / ۰ fail |
| ۴ | `npm run test:unit` | 0 | **PASS** — **۲۶۳ فایل / ۱۴۶۷ آزمون** (از ۲۶۲/۱۴۶۴) |
| ۵ | `npm run i18n:check` | 0 | **PASS** |
| ۶ | `npm run contracts:check` | 0 | **PASS** |
| ۷ | `npm run architecture:check` | 0 | **PASS** |
| ۸ | `npm run build` | 0 | **PASS** |
| ۹ | `npm run perf:check` | 0 | **PASS** — ۹/۹ |
| ۱۰ | `pytest` (کامل) | 1 | **PASS\*** — **۱۳٬۷۹۵** passed / ۱۳۲ skip / ۱ failed |

\* همان `test_doctor_cli` با محدودیت کاربر سندباکس. آزمون دست‌کاری نشد.

### آزمون جدید

`web/tests/auth-pages-presentation.spec.tsx` — **۳ آزمون** که کامپوننت‌های واقعی را رندر می‌کنند:

| # | آزمون | چه چیزی را تضمین می‌کند |
| --- | --- | --- |
| ۱ | `renders the sign-in form inside the two-column shell` | فرم و هر سه فیلد هنوز رندر می‌شوند؛ `aside` وجود دارد |
| ۲ | `names the product in the brand panel` | نشان تزئینی است (`alt=""`)، نام در تیتر می‌آید |
| ۳ | `keeps the brand panel out of the reading order on small screens` | `hidden lg:flex` + `border-e` (RTL-safe) |

**چرا این آزمون مهم است:** سرور Next در حالت standalone فقط پوستهٔ Suspense را برای `/login` می‌فرستد، پس `curl` نمی‌تواند ثابت کند صفحه رندر می‌شود. این آزمون با jsdom همان رندر را انجام می‌دهد.

---

## ۹. فایل‌های تغییر‌یافته

**۲۱ فایل:**

```
web/app/(auth)/layout.tsx                          (grid دوستونه)
web/app/(auth)/login/page.tsx                      (پوستهٔ جدید)
web/app/(auth)/register/page.tsx                   (پوستهٔ جدید)
web/components/auth/AuthBrandPanel.tsx             (جدید)
web/lib/brand.ts                                   (PRODUCT_TAGLINE_FA)
web/locales/*/app.json                             (۸ کلید × ۱۴ زبان)
tests/fixtures/portuguese_unchanged_ui.json        (برند در فهرست استثنا)
web/tests/agent-copy-locales.spec.tsx              (انتظار zh)
web/tests/e2e/fixtures/runtime.ts                  (regex)
web/tests/e2e/turn-lifecycle.audit.ts              (regex)
web/tests/auth-pages-presentation.spec.tsx         (جدید)
```

---

## ۱۰. محدودیت صریح: تأیید بصری

**می‌توانم ثابت کنم** که صفحه رندر می‌شود، فرم سالم است و کلاس‌ها درست‌اند (آزمون jsdom).

**نمی‌توانم ثابت کنم** که چیدمان در مرورگر واقعی زیبا یا درست است. Playwright در این سندباکس نصب نمی‌شود:

```
Error: Download failure, code=1
E: Unable to locate package fonts-wqy-zenhei
```

شبکهٔ سندباکس فقط npm و PyPI و GitHub را می‌دهد. این محدودیت در Gate 1 هم روی `browser E2E` اثر می‌گذارد.

**جایگزین مورد استفاده:** آزمون jsdom روی کامپوننت واقعی + بازرسی CSS کامپایل‌شده. **نه** تصویر مرورگر.

تصمیم دربارهٔ پذیرش این جایگزینی با مالک است.

---

## ۱۱. نتیجهٔ گام

**PASS** — ظاهر `/login` و `/register` بازطراحی شد با چیدمان دوستونه و پنل برند؛ مسیر، flow، و تمام مسیرهای خطا/ریدایرکت دست‌نخورده ماندند؛ ۸ کلید جدید در ۱۴ زبان با ترجمهٔ واقعی؛ و سه نقص از گام قبل کشف و اصلاح شد.

**تنها محدودیت:** تأیید بصری در مرورگر واقعی ممکن نشد.

**گام بعدی:** ۱.۶ — پوستهٔ کامل کاربر و admin طبق `DECISIONS.md` F-1.
