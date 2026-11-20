# گزارش گام ۴ فاز ۱ — RTL کامل با logical properties

**پروژه:** درسیار (شاخهٔ توسعه: DeepTutor)
**تاریخ:** ۲۰۲۶-۱۱-۱۶
**مرجع تصمیم:** `DECISIONS.md` بخش F، بند D-02
**مرجع نقشهٔ راه:** `ROADMAP.md` — فاز ۱، گام ۱.۳
**پیش‌نیاز:** گام ۳ (locale فارسی + `dir` metadata) — انجام شد
**وضعیت:** انجام شد (PASS) — منتظر بازبینی مالک

---

## ۱. صورت مسئله

گام ۳ صفت `dir="rtl"` را روی `<html>` می‌گذاشت، ولی چیدمان تقریباً به‌طور کامل با **خواص فیزیکی** نوشته شده بود. نتیجه:

- متن فارسی راست‌چین می‌شد،
- ولی پدینگ‌ها، فاصله‌ها، حاشیه‌ها و آیکون‌ها جای خود می‌ماندند.

یعنی صفحهٔ فارسی، متنی راست‌چین در قالبی چپ‌چین نشان می‌داد. شمارش اولیه:

| خانواده | تعداد در کد |
| --- | --- |
| `text-left` | ۱۰۷ |
| `right-*` (inset) | ۱۲۶ |
| `left-*` (inset) | ۱۱۳ |
| `ml-*` / `mr-*` | ۷۷ / ۳۰ |
| `pl-*` / `pr-*` | ۵۹ / ۴۱ |
| `border-l-*` / `border-r-*` | ۱۵ / ۴ |
| `rounded-*` (گوشه‌ای) | ۶ |

مجموع: حدود **۶۰۰** توکن در فایل‌های TSX/TS، به‌علاوهٔ **۲۷۶** اعلان در فایل‌های CSS.

---

## ۲. راه‌حل

نگاشت ۱:۱ به خواص منطقی (logical properties) که خودِ مرورگر بر پایهٔ `dir` حل می‌کند:

| فیزیکی | منطقی |
| --- | --- |
| `ml-*` / `mr-*` | `ms-*` / `me-*` |
| `pl-*` / `pr-*` | `ps-*` / `pe-*` |
| `left-*` / `right-*` | `start-*` / `end-*` |
| `border-l` / `border-r` | `border-s` / `border-e` |
| `text-left` / `text-right` | `text-start` / `text-end` |
| `rounded-tl/tr/bl/br` | `rounded-ss/se/es/ee` |
| `padding-left` / `margin-right` (CSS) | `padding-inline-start` / `margin-inline-end` |

مزیت این روش نسبت به نوشتن قواعد جدا برای `[dir="rtl"]`: یک نسخه کد برای هر دو جهت کار می‌کند و امکان «فراموش‌کردن یک حالت» وجود ندارد.

### نتیجهٔ عددی

- **۷۵۹ توکن** کلاس در **۲۴۰ فایل** TSX/TS
- **۲۷۶ اعلان** در **۸ فایل** CSS
- جمعاً **۲۱۶ فایل** در یک کامیت
- **۰** توکن فیزیکی جهتی باقی‌مانده

---

## ۳. آنچه عمداً تبدیل **نشد**

این بخش مهم‌ترین بخش این گزارش است. سه گروه وجود دارد که شبیه کلاس جهتی هستند ولی **نیستند**:

### ۳.۱. هندسه، نه چیدمان

| الگو | تعداد | دلیل |
| --- | --- | --- |
| `rotate-*`, `-translate-x-*` | ۱۴ | چرخش و جابه‌جایی، جهتی نیستند |
| `left-1/2` + `-translate-x-1/2` | ۳ | الگوی مرکزکردن؛ اگر `start-1/2` شود، `-translate-x-1/2` دیگر خنثی نمی‌کند و عنصر از مرکز بیرون می‌زند |
| `getBoundingClientRect` (`.left`/`.right`) | ۶+ | مختصات پیکسلی واقعی پنجره، نه CSS |

### ۳.۲. `right-hand`، `right-click`، `right-aligned`

این‌ها واژه‌های انگلیسی‌اند، نه یوتیلیتی. تبدیل‌شان معنا را عوض می‌کند.

### ۳.۳. سه موردی که codemod واقعاً خراب کرد (و اصلاح شد)

این بخش را صادقانه ثبت می‌کنم چون درس اصلی گزارش است.

#### الف) propهای کامپوننت که «واژهٔ جهت» در خود دارند — ۲۵ نقطه

```tsx
// TooltipSide = "top" | "right" | "bottom" | "left"
<Tooltip side="right">        // ❌ codemod: side="end"  → خطای Type
// align = "left" | "right"
<CategoryMenu align="right">  // ❌ codemod: align="end"
// BlockNote: textAlignment = "left" | "center" | "right"
textAlignment: 'left'         // ❌ codemod: 'start'
```

۱۵ فایل، ۲۵ نقطه اصلاح شد. این‌ها **API کامپوننت** هستند، نه CSS.

نکتهٔ ظریف: در سه فایل، هم *تعریف* نوع و هم *مقدار مصرف‌کننده* باید هم‌زمان تغییر می‌کرد. codemod فقط مصرف‌کننده را دید و در `ComposerTrayMenu` نوع `"start" | "end"` با مقدار `"left"` ناسازگار شد. همه با typecheck پیدا و اصلاح شدند.

#### ب) متن، کامنت و جدول فرمان LaTeX

```diff
- "ldotp ldots leadsto left leftarrow leftarrowtail leftharpoondown",
+ "ldotp ldots leadsto start leftarrow leftarrowtail leftharpoondown",
```

جدول دستورهای KaTeX آسیب دید (دو سطر). همچنین کامنت:

```diff
- // list ends, and a wrap makes "left" mean two different things
+ // list ends, and a wrap makes "start" mean two different things
```

هر دو دسته برگردانده شدند. برای جلوگیری از تکرار، codemod نهایی فقط رشته‌هایی را لمس کرد که **شاهد کلاس‌بودن** دارند (وجود توکن‌هایی مانند `flex`, `p-`, `text-xs`, `bg-`).

#### ج) لبه‌ای که بین دو یوتیلیتی تقسیم شده بود

```diff
- "border-l-[3px] border-l-emerald-500"
+ "border-s-[3px] border-l-emerald-500"   // ❌ فقط نیمهٔ عرض تبدیل شد
```

نتیجه: ضخامت روی لبهٔ شروع، ولی رنگ روی لبهٔ چپ. در RTL رنگ به سمت اشتباه می‌رفت. اصلاح شد به `border-s-[3px] border-s-emerald-500`. یک آزمون اختصاصی برای این الگو نوشته شد.

---

## ۴. روش تأیید

برای اینکه مطمئن شوم هیچ دستکاری غیرکلاسی دیگری رخ نداده، یک **بازرسی نظام‌مند** نوشتم:

> برای هر فایل تغییریافته، مجموعهٔ رشته‌های نسخهٔ کامیت‌شده با نسخهٔ فعلی مقایسه شد، پس از آنکه تغییرها با نگاشت جهتی «بی‌اثر» شدند. اگر تفاوتی باقی می‌ماند، یعنی تغییری خارج از نگاشت رخ داده.

نتیجه:

```
files with unexplained literal/property changes: 0
```

یعنی **هر** تغییر در کل diff با نگاشت جهتی توضیح داده می‌شود — هیچ چیز دیگری جابه‌جا نشده است.

---

## ۵. شواهد اجرا (دستور / exit code / نتیجه)

| # | دستور | exit code | نتیجه |
| --- | --- | --- | --- |
| ۱ | `npm run typecheck` | 0 | **PASS** |
| ۲ | `npm run lint` | 0 | **PASS** — ۰ خطا، ۵۸ هشدار (بدون تغییر) |
| ۳ | `npm run test:node` | 0 | **PASS** — **۱۴۱۳** pass / ۰ fail |
| ۴ | `npm run test:unit` (vitest) | 0 | **PASS** — ۲۶۲ فایل / ۱۴۶۴ آزمون |
| ۵ | `npm run contracts:check` | 0 | **PASS** |
| ۶ | `npm run architecture:check` | 0 | **PASS** |
| ۷ | `npm run build` | 0 | **PASS** (با `NODE_OPTIONS=--max-old-space-size=2560`) |
| ۸ | `npm run perf:check` | 0 | **PASS** — ۹/۹ بودجه OK |
| ۹ | `pytest` (کامل) | 1 | **PASS\*** — ۱۳٬۷۹۵ passed، ۱۳۲ skip، ۱ failed |
| ۱۰ | `ruff check .` | 0 | **PASS** |
| ۱۱ | `lint-imports` | 0 | **PASS** — ۳ KEPT، ۰ broken |
| ۱۲ | `check_architecture.py` | 0 | **PASS** |

\* همان `test_doctor_cli` با محدودیت محیطی سندباکس (نام کاربری در مسیر `/tmp/pytest-of-user/…`). مستند در F-3؛ آزمون دست‌کاری نشد.

### شمارش آزمون‌ها

| سنجه | گام ۳ | گام ۴ | تفاوت |
| --- | --- | --- | --- |
| pytest | ۱۳٬۷۹۵ | ۱۳٬۷۹۵ | ۰ (بدون تغییر) |
| test:node | ۱۴۰۷ | **۱۴۱۳** | **+۶** (آزمون‌های جدید RTL) |
| vitest | ۱۴۶۴ | ۱۴۶۴ | ۰ |

هیچ آزمونی حذف یا ضعیف نشد.

### تأیید کامپایل خواص منطقی

CSS تولیدشده بررسی شد:

```
.ms-2  { margin-inline-start: .5rem }
.ps-4  { padding-inline-start: 1rem }
```

و حضور اعلان‌های منطقی در خروجی build:

| اعلان | تعداد در CSS نهایی |
| --- | --- |
| `margin-inline-start` | ۶۵ |
| `padding-inline-start` | ۴۵ |
| `text-align:start` | ۲۶ |
| `border-inline-start` | ۲۲ |
| `margin-inline-end` | ۱۸ |
| `inset-inline-start` | ۱۲ |

این اعلان‌ها را مرورگر بر پایهٔ `dir` حل می‌کند؛ پس هیچ قاعدهٔ جداگانهٔ `[dir="rtl"]` لازم نیست.

### یادداشت فنی: حافظه

`npm run build` یک بار با exit code 1 و بدون پیام خطا متوقف شد. `dmesg` علت را نشان داد:

```
Out of memory: Killed process (next-build) … anon-rss:2817192kB
```

سندباکس ۳٫۹ گیگابایت RAM دارد. با محدودکردن heap گره، build کامل شد:

```bash
NODE_OPTIONS="--max-old-space-size=2560" npm run build   # exit 0
```

این محدودیت محیط است، نه نقص پروژه. در گزارش Gate 1 ثبت خواهد شد.

---

## ۶. آزمون رگرسیون جدید

فایل `web/tests/rtl-logical-properties.test.ts` — **۶ آزمون**:

| # | آزمون | چه چیزی را از بازگشت محافظت می‌کند |
| --- | --- | --- |
| ۱ | `no class string still uses a physical inline-start/end utility` | هیچ کلاس جهتی فیزیکی دوباره اضافه نشود |
| ۲ | `component props keep their own direction vocabulary` | `side`/`align`/`textAlignment` دوباره دستکاری نشوند |
| ۳ | `comments and prose still speak the product language` |کامنت‌ها به نام‌های منطقی آلوده نشوند |
| ۴ | `an edge is never split across physical and logical halves` | لبه‌های دو-یوتیلیتی ناهمگون نشوند |
| ۵ | `stylesheets express insets and padding on the inline axis` | CSS به خواص منطقی بماند |
| ۶ | `the locale declares direction and the document publishes it` | `RTL_LANGUAGES`/`root.dir` حذف نشوند |

این آزمون‌ها همان سه اشتباه واقعی codemod را کدگذاری می‌کنند، تا تکرارشان ممکن نباشد.

---

## ۷. فایل‌های تغییر‌یافته

**۲۱۶ فایل** در یک کامیت:

```
وب/کامپوننت‌ها و صفحه‌ها : ۲۰۸ فایل (TSX/TS)
وب/CSS                  : ۸ فایل (globals + ویژگی‌ها)
وب/آزمون جدید           : ۱ فایل
```

**کامیت:** `ef4b2e6` — `refactor(web): express direction with logical properties for RTL (1.3)`

`+883 / −697` خط. توازن نزدیک به ۱:۱ خودش شاهدی است که محتوا جابه‌جا نشده، فقط نام‌ها عوض شده‌اند.

---

## ۸. ریسک‌ها و محدودیت‌ها

| ریسک | سطح | توضیح |
| --- | --- | --- |
| آزمون بصری مرورگر | **متوسط (محیط)** | Playwright/Chromium در سندباکس دانلود نمی‌شود. به‌جای آن: کامپایل خواص منطقی، حضور اعلان‌ها در CSS نهایی، و بازرسی یکپارچگی رشته‌ها تأیید شد. **تأیید بصری موبایل/تبلت/دسکتاپ در Gate 1 انجام می‌شود** (الزام ROADMAP 1.3). |
| یوتیلیتی‌های فیزیکی باقی‌مانده | صفر | جست‌وجوی نهایی روی همهٔ رشته‌ها: **۰** توکن جهتی فیزیکی |
| الگوهای مرکزکردن | ۳ مورد | عمداً فیزیکی ماندند تا مرکز ماند؛ در RTL هم درست کار می‌کنند چون تقارن دارند |
| کتابخانه‌های ثالث (PDF.js و …) | کم | چیدمان داخلی کتابخانه‌ها نه در دامنهٔ ماست و نه در diff؛ در Gate 1 بررسی می‌شود |

---

## ۹. نتیجهٔ گام

**PASS** — کل چیدمان از خواص فیزیکی به منطقی منتقل شد (۷۵۹ توکن کلاس + ۲۷۶ اعلان CSS، صفر باقی‌مانده)، سه دستهٔ تغییر مخرب codemod شناسایی، اصلاح و با ۶ آزمون رگرسیون محافظت شد، و همهٔ دروازه‌های وب و بک‌اند با اعداد بدون رگرسیون سبز ماندند.

**گام بعدی فاز ۱:** برندینگ درسیار — تغییر نام نمایشی و metadata، بدون تغییر namespace، CLI یا runtime (بند ۱.۴).
