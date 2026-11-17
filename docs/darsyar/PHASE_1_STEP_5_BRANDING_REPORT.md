# گزارش گام ۵ فاز ۱ — برندینگ قابل‌مشاهده «درسیار»

**پروژه:** درسیار (شاخهٔ توسعه: DeepTutor)
**تاریخ:** ۲۰۲۶-۱۱-۱۶
**مرجع تصمیم:** `DECISIONS.md` بخش F، بند D-01
**مرجع نقشهٔ راه:** `ROADMAP.md` — فاز ۱، گام ۱.۴
**وضعیت:** انجام شد (PASS) — منتظر بازبینی مالک

---

## ۱. صورت مسئله و مرز دقیق

D-01 دو نیمه دارد و هر دو به یک اندازه الزامی‌اند:

> **بله:** نام نمایشی، title، metadata عمومی، login و navigation «درسیار» شود.
> **نه:** Python package/import namespace، distribution `deeptutor`، CLI، runtime home/env و نام‌های داخلی بدون ADR جداگانه تغییر نکنند. attribution و notices اصلی حفظ شوند.

یعنی این کار یک «تغییر برند» معمولی نیست — یک تغییر **لایهٔ نمایش** با حفظ کامل قرارداد اپراتور است. کسی که `deeptutor init` می‌زند یا `DEEPTUTOR_HOME` تنظیم می‌کند نباید هیچ چیزی را از نو یاد بگیرد.

پیش از این گام، «DeepTutor» در سه لایه حضور داشت:

| لایه | نمونه | تصمیم |
| --- | --- | --- |
| متن رابط کاربری | `DeepTutor Exploring…`, `Uploaded to DeepTutor` | **تغییر** |
| metadata قابل‌مشاهده | `<title>DeepTutor</title>` | **تغییر** |
| شناسهٔ داخلی | `deeptutor`, `DEEPTUTOR_HOME`, `/api/...` | **بدون تغییر** |

---

## ۲. راه‌حل — یک منبع یگانه برای برند

به‌جای ویرایش ۸۳ فایل، ماژول `web/lib/brand.ts` ساخته شد:

```ts
export const PRODUCT_NAME_FA    = "درسیار";
export const PRODUCT_NAME_LATIN = "Darsyar";
export const PRODUCT_TAGLINE    = "همراه یادگیری عامل‌محور";

/** فارسی برای fa، لاتین برای بقیهٔ زبان‌ها */
export function productName(language?: string): string { … }
```

**چرا دو نام؟** یک جملهٔ انگلیسی با واژهٔ فارسی در میانش مثل یک غلط تایپی خوانده می‌شود (`درسیار's built-in canvas`). پس:

- رابط فارسی → **درسیار**
- رابط غیرفارسی → **Darsyar**

این خودِ D-01 را نقض نمی‌کند: نام نمایشی محصول است، نه identifier داخلی.

---

## ۳. دامنهٔ تغییر

### ۳.۱. metadata — مهم‌ترین بخش

```diff
-export const metadata: Metadata = {
-  title: "DeepTutor",
-  description: "Agent-native intelligent learning companion",
+export const metadata: Metadata = {
+  title: PRODUCT_NAME_FA,
+  description: PRODUCT_TAGLINE,
```

**تأیید از خروجی build:**

```
<title>درسیار</title>
```

عنوان تب مرورگر، پیش‌نمایش پیوند و نتیجهٔ جست‌وجو — اولین و گاهی تنها جایی که محصول خودش را نام می‌برد — اکنون درسیار است.

### ۳.۲. کاتالوگ پیام‌ها — ۸۴ مقدار

کاتالوگ `en` کلیدهایی به شکل جملهٔ انگلیسی دارد (پروژه `keySeparator` را غیرفعال کرده). بنابراین:

- **کلید دست‌نخورده ماند** (چون `t()` آن را صدا می‌زند)،
- **مقدار** بازنویسی شد.

```diff
- "Uploaded to DeepTutor": "Uploaded to DeepTutor",
+ "Uploaded to DeepTutor": "Uploaded to درسیار",
```

این تفکیک حیاتی است: اگر کلید عوض می‌شد، **۸۴ نقطهٔ فراخوانی** می‌شکست و هر `t()` به رشتهٔ خام برمی‌گشت.

**۸۴ مقدار** بازنویسی شد و **صفر** نقطهٔ فراخوانی تغییر کرد.

### ۳.۳. صفحه‌های ورود و ثبت‌نام

```diff
<h1 className="font-serif …">
-  DeepTutor
+  {productName(i18n.language)}
</h1>
```

### ۳.۴. نام‌های دسترس‌پذیری (alt / aria-label)

۱۲ نقطه در ۵ فایل. این‌ها راوی صفحه‌خوان می‌خواند و در جمله قرار نمی‌گیرند، پس یک نام پایدار گرفتند:

```diff
-<Image … alt="DeepTutor" />
+<Image … alt={PRODUCT_NAME_FA} />
```

### ۳.۵. سند نمونهٔ co-writer

این یک سند انگلیسی است که کاربر باز می‌کند، پس با نام لاتین برند شد (`Darsyar`) تا متن انگلیسی سالم بماند.

---

## ۴. دو اتصال کارکردی که پیدا شد و حفظ شد

این مهم‌ترین بخش فنی گام است: دو جا برند فقط «متن» نبود، بلکه در **منطق** استفاده می‌شد.

### ۴.۱. فیلتر انتخاب پاسخ‌دهنده

```diff
-{matches("DeepTutor") && (
+{matches("DeepTutor", t("composer.tray.deeptutor")) && (
```

`matches()` یک فیلتر جست‌وجوی زنده روی برچسب نمایشی ردیف‌هاست. اگر فقط مقدار کاتالوگ عوض می‌شد و این رشته نه، **جست‌وجوی «deeptutor» دیگر ردیف محصول را پیدا نمی‌کرد**. اکنون هر دو شکل را می‌پذیرد.

### ۴.۲. نام پیش‌فرض ردیف فعالیت

```diff
-const name = agentName?.trim() || "DeepTutor";
+const name = agentName?.trim() || t("composer.tray.deeptutor");
```

این `name` در `t("{{name}} Exploring…")` تزریق می‌شود. رشتهٔ ثابت یعنی متن انگلیسی در میان جملهٔ فارسی. اکنون از همان کلید ترجمه‌شده می‌آید.

---

## ۵. آنچه عمداً تغییر نکرد

| مورد | دلیل |
| --- | --- |
| `pyproject.toml`: `name = "deeptutor"` | قرارداد نصب و import — D-01 صریحاً منع کرده |
| `DEEPTUTOR_HOME`, `DEEPTUTOR_EXTRAS`, … | env اپراتور |
| `deeptutor init`, `deeptutor module install` | CLI |
| مسیرهای `/api/...` | قرارداد HTTP |
| `https://github.com/HKUDS/DeepTutor` | attribution بالا‌دستی |
| `THIRD_PARTY_NOTICES.md` | الزام مجوز |
| «your DeepTutor installation» در پرامپت راه‌اندازی | به **نصب واقعی** اشاره دارد، نه به محصول |

آزمون `internal identity is untouched` دقیقاً همین‌ها را قفل می‌کند.

---

## ۶. شواهد اجرا (دستور / exit code / نتیجه)

| # | دستور | exit code | نتیجه |
| --- | --- | --- | --- |
| ۱ | `npm run typecheck` | 0 | **PASS** |
| ۲ | `npm run lint` | 0 | **PASS** — ۰ خطا، **۴۴** هشدار (از ۵۸ کاهش یافت) |
| ۳ | `npm run test:node` | 0 | **PASS** — **۱۴۱۸** pass / ۰ fail |
| ۴ | `npm run test:unit` | 0 | **PASS** — ۲۶۲ فایل / **۱۴۶۴** آزمون |
| ۵ | `npm run i18n:check` | 0 | **PASS** |
| ۶ | `npm run contracts:check` | 0 | **PASS** |
| ۷ | `npm run architecture:check` | 0 | **PASS** |
| ۸ | `npm run build` | 0 | **PASS** |
| ۹ | `npm run perf:check` | 0 | **PASS** — ۹/۹ بودجه OK |
| ۱۰ | `pytest` (کامل) | 1 | **PASS\*** — ۱۳٬۷۹۵ passed، ۱۳۲ skip، ۱ failed |
| ۱۱ | `ruff check .` | 0 | **PASS** |
| ۱۲ | `lint-imports` | 0 | **PASS** — ۳ KEPT، ۰ broken |

\* همان `test_doctor_cli` با محدودیت محیطی سندباکس؛ مستند در F-3، آزمون دست‌کاری نشد.

### نکتهٔ قابل توجه: کاهش هشدارهای lint

از **۵۸** به **۴۴**. دلیل: بخشی از هشدارها مربوط به رشته‌های انگلیسی سخت‌کد در UI بود که با برندینگ حذف شدند. این نشانهٔ جانبی مثبت است، نه هدف.

### شمارش آزمون‌ها

| سنجه | گام ۴ | گام ۵ | تفاوت |
| --- | --- | --- | --- |
| pytest | ۱۳٬۷۹۵ | ۱۳٬۷۹۵ | ۰ |
| test:node | ۱۴۱۳ | **۱۴۱۹** | **+۶** (آزمون‌های برند) |
| vitest | ۱۴۶۴ | ۱۴۶۴ | ۰ |

---

## ۷. دو آزمون که شکستند و چرا درست شکستند

پس از تغییر مقادیر، سه تست Vitest شکست:

```
FAIL tests/chat-streaming-status.spec.tsx      (۲ مورد)
FAIL tests/attachment-processing-status.spec.tsx (۱ مورد)
```

دلیل: این‌ها **متن قابل‌مشاهده** را می‌سنجیدند:

```ts
expect(status).toHaveTextContent("DeepTutor Exploring");
expect(screen.getByText("Uploaded to DeepTutor")).toBeVisible();
```

این آزمون‌ها درست کار کردند: تغییر برند را گرفتند. اقدام:

```diff
-expect(status).toHaveTextContent("DeepTutor Exploring");
+expect(status).toHaveTextContent("درسیار Exploring");
```

**این تضعیف آزمون نیست.** تطبیق همچنان **کامل و دقیق** است (`toHaveTextContent` با رشتهٔ کامل، نه regex و نه `toContain`). فقط انتظار با محصول جدید هم‌راستا شد — همان چیزی که D-01 خواسته. اگر روزی متن به `DeepTutor` برگردد، این آزمون دوباره شکست می‌خورد.

---

## ۸. آزمون رگرسیون جدید

`web/tests/brand-identity.test.ts` — **۵ آزمون** که هر دو جهت D-01 را قفل می‌کند:

| # | آزمون | چه چیزی را تضمین می‌کند |
| --- | --- | --- |
| ۱ | `the brand module owns the displayed name` | منبع یگانه برند وجود دارد |
| ۲ | `the document title and description carry the new brand` | metadata از برند می‌آید، نه رشتهٔ ثابت |
| ۳ | `no user-visible value still says DeepTutor` | هیچ مقدار قابل‌مشاهده‌ای نام قدیمی ندارد (با دو استثنای مستند) |
| ۴ | `the auth screens name the product from the brand module` | ورود/ثبت‌نام از تابع برند استفاده می‌کنند |
| ۵ | `internal identity is untouched` | `deeptutor` در package، CLI و env دست‌نخورده است |

آزمون ۳ در اولین اجرا **یک مورد واقعی** پیدا کرد (`settings.agentSetup.instructions`) و ما را مجبور کرد تصمیم را صریح کنیم: آن رشته به *نصب* اشاره دارد، نه به محصول — پس استثنا شد و در کد مستند گشت.

---

## ۹. تکمیل برندینگ کاتالوگ‌ها — ۹۸۲ مقدار در ۱۲ زبان

پس از نخستین کامیت، اندازه‌گیری نشان داد کار نیمه‌کاره است:

```
de 86   fr 108   hu 87   it 86   ja 87   ko 3
pl 87   pt 87    tr 87   uk 86   vi 87   zh 98
```

رابط این ۱۲ زبان هنوز «DeepTutor» نشان می‌داد. این در همان گام بسته شد.

### ۹.۱. قاعدهٔ ترجمه

| زبان | نام نمایشی | دلیل |
| --- | --- | --- |
| `en` (باندل پایه) | **درسیار** | همان چیزی که محصول واقعاً نمایش می‌دهد |
| `fr, de, it, pt, uk, pl, hu, tr, vi, ja, ko, zh` | **Darsyar** | جمله در یک script بماند |
| `fa` | دست‌نخورده | از ابتدا فارسی نوشته شد، هرگز نام انگلیسی نداشت |

### ۹.۲. حفاظت از ارجاعات بالا‌دستی

همان‌طور که در `en` بود: `https://github.com/HKUDS/DeepTutor`، `HKUDS/DeepTutor`، `deeptutor` (CLI) و «DeepTutor installation» با placeholder موقت محافظت و سپس بازگردانده شدند.

### ۹.۳. اعتبارسنجی — چرا این تغییر خطرناک بود و چگونه مهار شد

ویرایش ۹۸۲ مقدار با اسکریپت می‌توانست سه چیز را بشکند: مجموعهٔ کلیدها، placeholderها و ساختار JSON.

| بررسی | نتیجه |
| --- | --- |
| مجموعهٔ کلیدها تغییر کرد؟ | **۰ مورد** — با `git show HEAD:` مقایسه شد |
| تعداد عدم‌تطابق placeholder نسبت به قبل زیاد شد؟ | **۰ مورد** — `old == new` برای هر ۱۴ زبان |
| JSON معتبر است؟ | بله — هر ۱۴ فایل parse شد |
| `i18n:check` | **PASS** (exit 0) |
| برند قدیمی در مقدار قابل‌مشاهدهٔ باقی‌مانده | **۰** |

انحراف‌هایی که `i18n` نشان می‌دهد (مثل `fa` با ۵٬۹۹۰ کلید کمتر، یا `fr` با ۹۰۵ کلید اضافه) **از قبل وجود داشته‌اند** — با اجرای همان بررسی روی `HEAD` اثبات شد که تغییر من صفر مورد به آن‌ها افزوده است.

### ۹.۴. آزمون گسترش‌یافته

آزمون `every locale bundle is free of the old visible name` اضافه شد: هر ۱۴ باندل را می‌خواند، وجود کامل مجموعه را تأیید می‌کند و هیچ مقدار قابل‌مشاهده‌ای با نام قدیمی را نمی‌پذیرد (با همان دو استثنای مستند). **test:node از ۱۴۱۸ به ۱۴۱۹ رسید.**

---

## ۱۰. فایل‌های تغییر‌یافته

**۲۸ فایل (کد) + ۱ گزارش.**

```
web/lib/brand.ts                              (جدید — منبع یگانه برند)
web/app/layout.tsx                            (metadata)
web/app/(auth)/login/page.tsx                 (wordmark + i18n)
web/app/(auth)/register/page.tsx              (wordmark + i18n)
web/app/(admin)/admin/users/page.tsx          (footer)
web/app/(workspace)/co-writer/sampleTemplate.ts
web/components/layout/AppShell.tsx            (alt)
web/components/sidebar/SidebarShell.tsx       (alt + aria)
web/components/chat/home/SessionLoadingView.tsx
web/components/chat/home/AnswerModeMenu.tsx   (فیلتر جست‌وجو)
web/features/ui-layout/classic/ClassicSidebarShell.tsx
web/features/chat/components/ChatWorkspace.tsx
web/features/chat/trace/TracePresentation.tsx (نام پیش‌فرض)
web/locales/en/app.json                       (۸۴ مقدار)
web/locales/{de,fr,hu,it,ja,ko,pl,pt,tr,uk,vi,zh}/app.json  (۹۸۲ مقدار)
web/tests/{chat-streaming,attachment-processing}-status.spec.tsx
web/tests/brand-identity.test.ts              (جدید)
```

**کامیت‌ها:**
- `82814b7` — برندینگ رابط + metadata + کاتالوگ `en`
- کامیت دوم — برندینگ ۱۲ کاتالوگ دیگر + آزمون گسترش‌یافته

---

## ۱۱. ریسک‌ها و محدودیت‌ها

| ریسک | سطح | توضیح |
| --- | --- | --- |
| کاتالوگ‌های غیرانگلیسی | **بسته شد** | در نسخهٔ اول فقط `en` برند شده بود؛ ۱۲ کاتالوگ دیگر جا مانده بود. با اندازه‌گیری (۹۸۲ مقدار) در همین گام بسته شد — به بخش ۹ مراجعه کنید. |
| آیکون‌ها و لوگو | کم | فایل‌های `public/brand/*.png` هنوز لوگوی قبلی‌اند. تغییرشان نیازمند دارایی طراحی است و در دامنهٔ کد نیست؛ در Gate 1 به مالک گزارش می‌شود. |
| تأیید بصری | متوسط (محیط) | Playwright در سندباکس نیست. به‌جای آن، `<title>درسیار</title>` در خروجی build تأیید شد. اسکرین‌شات در Gate 1. |
| برندینگ بک‌اند | کم | پیام‌های بک‌اند (`services/i18n.py`) نام محصول را در متن ندارند، پس کاری لازم نبود. |

### کار باقی‌ماندهٔ صریح

**هیچ.** برندینگ کاتالوگ‌ها کامل است (بخش ۹).

تنها مورد باز: دارایی‌های تصویری `public/brand/*.png` که هنوز لوگوی قبلی‌اند. این یک کار **طراحی** است نه کد، و در Gate 1 به مالک گزارش می‌شود.

---

## ۱۲. نتیجهٔ گام

**PASS با یک کار باقی‌ماندهٔ مستند** — نام نمایشی، عنوان تب، ورود/ثبت‌نام، footer مدیریت و ۸۴ رشتهٔ رابط به «درسیار» تغییر کرد؛ منبع یگانهٔ برند ساخته شد؛ دو اتصال کارکردی که برند در آن‌ها منطق بود پیدا و حفظ شد؛ و شناسه‌های داخلی، CLI، env و attribution دست‌نخورده ماندند. آزمون جدید هر دو جهت را قفل می‌کند.

**گام بعدی فاز ۱:** بازطراحی ظاهری `/login` با حفظ مسیر و رفتار (بند ۱.۵، D-04).
