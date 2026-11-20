# گزارش گام ۱.۶ فاز ۱ — پوستهٔ وب و سطح مدیریت

**پروژه:** درسیار
**تاریخ:** ۲۰۲۶-۱۱-۱۷
**مرجع:** `ROADMAP.md` خط ۳۲۱–۳۲۵؛ `DECISIONS.md` F-1، D-004
**وضعیت:** انجام شد (PASS) — منتظر بازبینی مالک

---

## ۱. خواسته

ROADMAP:

> **1.6 — Full web shell**
> - Shell کامل کاربر و admin طبق `DECISIONS.md` F-1.
> - قابلیت‌های موجود reuse شوند؛ برای قابلیت‌های آینده placeholder شفاف استفاده شود.
> - مسیر `/admin/login` و `/admin` مستقل بمانند؛ احراز هویت/نقش از قرارداد موجود استفاده کند و **API ساختگی ایجاد نشود**.

F-1 یک قید اضافه دارد که تعیین‌کننده بود:

> محافظت admin باید با auth و role فعلی **سمت سرور** حفظ شود؛ route guard مرورگر به‌تنهایی کافی نیست.

---

## ۲. نقطهٔ شروع — سه شکاف واقعی

پیش از هر کدی، وضعیت را سنجیدم. سه شکاف پیدا شد که هیچ‌کدام در گزارش فاز ۰ به این دقت ثبت نشده بود:

| # | شکاف | شدت |
| --- | --- | --- |
| ۱ | `/admin/users` **هیچ محافظت سمت سروری نداشت** | **بالا — امنیتی** |
| ۲ | `/admin/login` و `/admin` **وجود نداشتند** (فاز ۰: MISSING) | بالا |
| ۳ | لینک admin در ناوبری نبود، پس مدیر راهی به پنل نداشت | متوسط |

### ۲.۱. شکاف امنیتی — جزئیات

محافظت فعلی این بود:

```ts
// app/(admin)/admin/users/page.tsx
useEffect(() => {
  fetchAuthStatus().then((status) => {
    if (!status?.authenticated) { router.replace("/login"); return; }
    if (status.role !== "admin") { router.replace("/"); return; }
```

**مشکل:** `useEffect` بعد از آن اجرا می‌شود که مرورگر سند را دریافت کرده است. یعنی هر کسی که `curl /admin/users` بزند، یا JavaScript را غیرفعال کند، **پوستهٔ صفحهٔ مدیریت را می‌گرفت**. داده‌ها لو نمی‌رفت (بک‌اند هر API را تأیید می‌کند)، اما F-1 صریح می‌گوید این کافی نیست.

---

## ۳. راه‌حل

### ۳.۱. دروازهٔ سمت سرور در middleware

`web/lib/proxy-policy.ts` دو تابع خالص جدید گرفت:

```ts
export function isAdminPagePath(pathname: string): boolean
export function tokenRole(token: string | undefined): string | null
```

و `proxy.ts` آن را در جریان موجود وصل کرد — **پس از** بررسی معتبر بودن توکن:

```ts
if (isAdminPagePath(pathname) && tokenRole(token) !== "admin") {
  const home = req.nextUrl.clone();
  home.pathname = "/";
  home.search = "";
  return NextResponse.redirect(home);
}
```

### ۳.۲. چرا امضا تأیید نمی‌شود — و چرا این درست است

`tokenRole` ادعای `role` را **بدون تأیید امضای JWT** می‌خواند. این یک تصمیم آگاهانه است:

| لایه | چه چیزی را تأیید می‌کند |
| --- | --- |
| middleware | آیا کاربر توکنی دارد که ادعای admin می‌کند؟ |
| **بک‌اند** | آیا این توکن معتبر است؟ آیا این کاربر مجاز است؟ |

توکن جعلی با ادعای `role: "admin"` فقط **پوستهٔ خالی** می‌گیرد؛ هر API بعدی در بک‌اند رد می‌شود. افزودن یک کتابخانهٔ JWT به Edge runtime برای تصمیمی که API همین حالا می‌گیرد، پیچیدگی بی‌فایده بود.

**این تصمیم در آزمون مستند شده** تا اگر روزی فرضش تغییر کرد، آزمون جایی باشد که بشکند.

### ۳.۳. `/admin/login` — ورودی مستقل

فاز ۰ این را **MISSING** ثبت کرده بود و D-004 می‌گوید باید مستقل باشد.

- همان `login()`، همان مدیریت `mustChangePassword`
- یک قاعدهٔ اضافه: حسابی که مدیر نیست **رد می‌شود**، به‌جای اینکه عبور کند و لحظه‌ای بعد در middleware بounces شود
- خطای «این حساب دسترسی مدیر ندارد» با «گذرواژه اشتباه» متفاوت است — دو چیز متفاوت‌اند
- لینک بازگشت به اپ یادگیری، تا اپراتوری که اشتباهی اینجا آمده گیر نکند

**دام حلقه که گرفته شد:** اگر `/admin/login` در `isAdminPagePath` می‌ماند، صفحه به خودش redirect می‌کرد — بی‌پایان. اکنون از هر دو دروازه مستثناست و آزمون جداگانه دارد.

### ۳.۴. `/admin` — صفحهٔ فرود صادقانه

`/admin` وجود نداشت؛ مدیر به ۴۰۴ می‌رسید.

این صفحه **داشبورد جعلی نساختم**. F-1 و ROADMAP هر دو می‌گویند placeholder نباید به‌عنوان قابلیت کامل ارائه شود. پس:

- **کاربران** → لینک واقعی و کارا
- چهار پنل دیگر → حاشیهٔ خط‌چین، برچسب **«به‌زودی»**، و ذکر فازی که مالک آن است

تفاوت «خالی» و «ساخته‌نشده» برای اپراتور روشن است.

### ۳.۵. لینک admin در ناوبری

`pageSections()` پارامتر `isAdmin` گرفت و یک بخش مجزا می‌سازد:

```ts
if (isAdmin) {
  sections.push({
    id: 'admin',
    label: t('navigation.admin'),
    icon: ShieldCheck,
    account: true,
    pages: [{ href: '/admin/users', label: t('navigation.users'), icon: UserRound }],
  })
}
```

پیش‌فرض `false` است: فراموش کردن پارامتر باید پنل را **پنهان** کند، نه آشکار. آزمون همین را تضمین می‌کند.

---

## ۴. آنچه تغییر نکرد

| مورد | دلیل |
| --- | --- |
| `/login` و `/register` | بیرون از دامنهٔ این گام |
| ساختار shelf های کاربر | فقط یک بخش *اضافه* شد، هیچ‌کدام بازچینی نشد |
| `login()` در `lib/auth.ts` | امضایش دست‌نخورده؛ نقش از `fetchAuthStatus` خوانده می‌شود |
| هیچ API جدیدی | F-1 صریحاً منع کرده |
| semantics نقش‌ها | از قرارداد موجود (`admin/teacher/student/user`) |

---

## ۵. شواهد اجرا

| # | دستور | exit | نتیجه |
| --- | --- | --- | --- |
| ۱ | `npm run typecheck` | 0 | **PASS** |
| ۲ | `npm run lint` | 0 | **PASS** — ۰ خطا، ۴۸ هشدار |
| ۳ | `npm run test:node` | 0 | **PASS** — **۱۴۲۹** / ۰ fail |
| ۴ | `npm run test:unit` | 0 | **PASS** — **۲۶۳ فایل / ۱۴۶۸ آزمون** |
| ۵ | `npm run i18n:check` | 0 | **PASS** |
| ۶ | `npm run contracts:check` | 0 | **PASS** |
| ۷ | `npm run architecture:check` | 0 | **PASS** |
| ۸ | `npm run build` | 0 | **PASS** — `/admin`, `/admin/login`, `/admin/users` در خروجی |
| ۹ | `npm run perf:check` | 0 | **PASS** — ۹/۹ |
| ۱۰ | `pytest` (کامل) | 1 | **PASS\*** — **۱۳٬۷۹۵** passed |

\* همان `test_doctor_cli` با محدودیت کاربر سندباکس.

### آزمون‌های جدید

**`web/tests/proxy-policy.test.ts`** — ۵ آزمون اضافه:

| آزمون | چه چیزی را می‌گیرد |
| --- | --- |
| `isAdminPagePath covers the admin surface and nothing adjacent` | `/administrator` و `/admin-panel` gate **نمی‌شوند** |
| `tokenRole reads the role claim` | سه نقش |
| `tokenRole fails closed` | هفت ورودی خراب همه `null` → رد |
| `a token whose payload claims admin is read as admin` | فرض «امضا تأیید نمی‌شود» را مستند می‌کند |
| `the admin sign-in page is reachable and does not loop` | حلقهٔ بی‌پایان |

**`web/tests/admin-navigation.test.ts`** — ۴ آزمون:

| آزمون | تضمین |
| --- | --- |
| `an administrator gets an admin section` | بخش admin وجود دارد و به `/admin/users` می‌رود |
| `a non-administrator never sees the admin section` | شامل حالت **پیش‌فرض** |
| `the user shelves are unchanged by the admin flag` | افزودنی است، نه جایگزین |
| `every admin entry points at a route that exists` | لینک مرده ممنوع |

**`tests/auth-pages-presentation.spec.tsx`** — ۱ آزمون اضافه برای رندر `/admin/login`.

---

## ۶. باگ واقعی که در همین گام پیدا و رفع شد

**حلقهٔ redirect.** نسخهٔ اول `/admin/login` را در `isAdminPagePath` نگه می‌داشت. نتیجه:

```
/admin/login → (بدون نقش admin) → redirect → /admin/login → …
```

این را قبل از build گرفتم و آزمون `does not loop` را برایش نوشتم.

---

## ۷. نگهبان پرتغالی — دو بار

`tests/i18n/test_portuguese_locale.py` دو بار جلوی من را گرفت:

1. ۱۶ کلید جدید admin انگلیسی مانده بودند
2. دو کلید `navigation.admin` / `navigation.users` که به‌اشتباه اضافه نشده بودند

هر دو بار ترجمهٔ واقعی پرتغالی نوشتم، نه placeholder. این آزمون دقیقاً کارش را می‌کند.

---

## ۸. محدودیت صریح

**تأیید بصری ممکن نشد.** Playwright در سندباکس نصب نمی‌شود:

```
Error: Download failure, code=1
```

می‌توانم ثابت کنم:
- ✅ سه مسیر admin در `build` ساخته می‌شوند
- ✅ middleware تصمیم درست می‌گیرد (۵ آزمون)
- ✅ صفحه‌ها با کامپوننت واقعی در jsdom رندر می‌شوند

**نمی‌توانم ثابت کنم:**
- ❌ اینکه `/admin` در مرورگر درست به نظر می‌رسد
- ❌ اینکه RTL در سطح admin سالم است (فقط `border-e` و logical properties به کار رفته)

Gate 1 صریحاً `browser E2E` می‌خواهد. **این محدودیت Gate 1 را مسدود می‌کند** و باید تصمیمش با مالک باشد.

---

## ۹. فایل‌های تغییر‌یافته

**۴۰ فایل:**

```
web/lib/proxy-policy.ts                         (2 تابع جدید + ADMIN_LOGIN_PATH)
web/proxy.ts                                    (دروازهٔ admin)
web/components/sidebar/page-sections.ts         (بخش admin + isAdmin)
web/components/sidebar/PageBar.tsx              (وصل کردن isAdmin)
web/app/(admin)/admin/page.tsx                  (جدید — فرود)
web/app/(admin)/admin/login/page.tsx            (جدید — ورود مستقل)
web/tests/proxy-policy.test.ts                  (+۵ آزمون)
web/tests/admin-navigation.test.ts              (جدید — ۴ آزمون)
web/tests/auth-pages-presentation.spec.tsx      (+۱ آزمون)
web/locales/*/app.json                          (۳۵ کلید جدید × ۱۴ زبان)
```

---

## ۱۰. نتیجهٔ گام

**PASS** — یک شکاف امنیتی واقعی بسته شد (محافظت admin سمت سرور)، دو مسیر گم‌شده ساخته شدند، ناوبری مدیر کامل شد، و همهٔ placeholderها برچسب صریح «به‌زودی» دارند بدون هیچ API جعلی.

**تنها محدودیت:** تأیید بصری، که Gate 1 را مسدود می‌کند.

**گام بعدی:** ۱.۷ — Gate 1.
