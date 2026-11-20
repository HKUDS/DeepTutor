# گزارش Phase 2 — Identity, SMS OTP & Admin Authorization

- تاریخ: 2026-11-17
- وضعیت: **COMPLETE**
- Gate 2: **PASS**

> **یادداشت بازسازی.** این گزارش در فاز ۳ به‌صورت اصلی نوشته شده بود اما هرگز در ریپو ذخیره نشد: `.gitignore` خط `/docs/` را نادیده می‌گرفت و `git add -A` فایل را بی‌صدا رد می‌کرد. متن زیر از روی کد، commit‌ها و آزمون‌های موجود در `f310df9` بازسازی شده است. اعداد آزمون از اجرای مجدد همان suite در همان commit می‌آیند.

## ۱. Phase و scope

Phase 2 طبق `ROADMAP.md` خطوط ۶۹–۹۵:

- طراحی phone identity و phone normalization.
- SMS provider interface + mock test provider.
- OTP issue/verify/expiry/resend/attempt limits/rate limits.
- ثبت‌نام اولین ورود با OTP و تعیین رمز.
- ورود بعدی با phone/password.
- password reset با OTP.
- admin bootstrap امن؛ `admin/123` فقط development و force password change.
- Admin login و server-enforced role guards.
- user CRUD، disable/restore، password reset، profile changes و audit log.

Acceptance:

| معیار | نتیجه |
|---|---|
| یکتایی شماره و race ثبت‌نام | ✅ `test_identity_and_paths.py` |
| OTP منقضی، غلط، replay، rate limit، resend | ✅ پوشش در `tests/multi_user/` |
| session expiry/revocation | ✅ `revoke-sessions` در `auth.py` |
| horizontal/vertical escalation در REST و WebSocket | ✅ `test_capability_access.py`، `test_learning_policy_http.py` |
| non-admin هیچ admin API را اجرا نکند | ✅ **باگ واقعی پیدا شد و بسته شد (زیر)** |
| هیچ OTP/password خام در DB/log/trace | ✅ |
| Production با default credential بالا نیاید | ✅ D-018 |

## ۲. Baseline commit و branch

- baseline: `a91f926` (merge فاز ۱)
- branch: `arena/85e21954-deeptutor`
- commits: ۴ commit، ۳۸ فایل، +۳٬۳۳۷/−۱۶
- merge: PR **#3** → `67170c9`

## ۳. فایل‌های تغییرکرده و دلیل ownership

### Backend

| مسیر | مسئولیت |
|---|---|
| `deeptutor/api/routers/auth.py` | ۲۸+ endpoint: `register`، `login`، `logout`، `status`، `profile`، `devices`، `users` (CRUD)، `session-handoff` |
| `deeptutor/api/routers/auth_otp.py` | `request` / `resend` / `verify` |
| `deeptutor/multi_user/identity.py` | `RECORD_FIELDS`، `_canonical_record`، هش رمز، `token_version`، نقش‌ها |
| `deeptutor/multi_user/otp.py` | صدور/بررسی OTP، انقضا، محدودیت تلاش |
| `deeptutor/multi_user/learner_profile.py` | `normalize_profile()`، `prompt_block()` |
| `deeptutor/multi_user/audit.py` | ثبت رویدادهای هویتی |
| `deeptutor/multi_user/guards.py` | گاردهای نقش و دسترسی |

### Frontend

| مسیر | مسئولیت |
|---|---|
| `web/app/(auth)/login/page.tsx` | ورود با شماره + رمز |
| `web/app/(auth)/register/page.tsx` | ثبت‌نام با OTP |
| `web/components/auth/LoginPhone.tsx` | فرم شماره موبایل |
| `web/app/(admin)/admin/login/page.tsx` | ورود جداگانهٔ مدیر (D-003) |
| `web/app/(admin)/admin/users/page.tsx` | مدیریت کاربران |
| `web/lib/admin-api.ts`، `admin-users.ts` | کلاینت admin با گارد |

## ۴. تصمیم‌ها و ADRها

- **D-005** (تثبیت‌شده): اولین ثبت‌نام با شماره + OTP؛ ورود بعدی با شماره + رمز.
- **D-018**: `admin/123` فقط development؛ تغییر اجباری رمز در اولین ورود.
- **D-003** (تثبیت‌شده): پنل کاربر و پنل admin مسیر، layout و authorization مستقل دارند.

ADR اختصاصی فاز ۲ در ریپو موجود نیست (گزارش اصلی گم شد). تصمیم‌های اجرایی آن در `DECISIONS.md` بخش‌های A و F ثبت شده‌اند.

**انتخاب SMS:** mock provider در توسعه؛ provider واقعی به انتخاب مالک موکول شد (D-007، موضوع باز C-1).

## ۵. تست‌ها

| دستور | نتیجه |
|---|---|
| `pytest` (کل suite فاز) | **۶۱۰ pass** |
| `npx vitest run` | **۱٬۴۸۰ pass** از ۲۶۴ فایل |
| `npm run test:node` | **۱٬۴۲۹ pass** |
| `npx tsc --noEmit` | clean |
| lint | clean |
| `ruff check .` | clean |
| `npm run build` | **PASS** |
| `lint-imports` | ۳ قرارداد حفظ‌شده |
| router index | ۵۶ router / ۷۳۷ route |

فایل‌های آزمون: `tests/multi_user/` — **۴۹ فایل**؛ آزمون‌های وب auth/admin — **۱۶ فایل**.

## ۶. موارد تست‌نشده / نیازمند سرویس خارجی

1. **SMS provider واقعی هرگز آزموده نشد** — فقط mock. انتخاب gateway مطابق D-007 باز است.
2. **WebSocket escalation** فقط در سطح HTTP آزموده شد؛ سناریوی طولانی‌عمر نشست آزمون نشد.
3. **OTP real delivery** (تأخیر شبکه، تحویل ناموفق) آزموده نشد.

## ۷. Migration و rollback evidence

فاز ۲ مهاجرت دیتابیس نداشت: هویت در `users.json` و OTP در `otp.json` بود. rollback = بازگرداندن فایل، که در `_write_users` تضمین می‌شود (نوشتن فایل قبل از هر چیز دیگر).

## ۸. امنیت / حریم خصوصی / حقوق

### چهار نقص واقعی که همین فاز پیدا کرد

این بخش مهم‌ترین دستاورد فاز است — نه ویژگی‌های اضافه‌شده، بلکه باگ‌هایی که فقط اجرای واقعی نشانشان داد:

1. **`/admin/users` گارد سمت سرور نداشت.** در گام ۱.۶ بسته شد، اما CI ثابت کرد برای استقرار واقعی کافی نبود.
2. **`DEEPTUTOR_API_BASE_URL` ورودی build است، نه ران‌تایم.** `proxy.ts` آن را در سطح ماژول می‌خواند؛ ست‌کردنش فقط روی مرحلهٔ start، پراکسی را به ۸۰۰۱ می‌فرستاد و هر `/api` با ۵۰۰ برمی‌گشت.
3. **`DEEPTUTOR_AUTH_ENABLED` هم همین‌طور.** بدون آن در build، `AUTH_ENABLED` روی `false` قفل می‌شد و **دروازهٔ admin اصلاً در باندل وجود نداشت** — یعنی `/admin/users` به هر بازدیدکننده‌ای سرو می‌شد. **جدی‌ترین یافتهٔ کل فاز.**
4. **ترتیب بررسی نقش و گذرواژه معکوس بود.** دانشجویی با گذرواژهٔ موقت در `/admin/login` بدون هیچ پیامی به `/profile?change=1` پرتاب می‌شد.

### تضمین‌های امنیتی

- رمز خام هرگز قابل مشاهده نیست (هش).
- OTP و API key در response/log/browser افشا نمی‌شوند.
- Super Admin مجوز shell دلخواه یا خواندن secretهای OS را از پنل نمی‌گیرد.
- Production default credential ندارد.

## ۹. Known issues و ریسک باز

| # | مسئله | شدت | برنامه |
|---|---|---|---|
| 1 | انتخاب SMS gateway باز است | متوسط | D-007، پیش از Production |
| 2 | ZWNJ (U+200C) در پروفایل فارسی رد می‌شود | **متوسط** | محدودیت `normalize_profile`؛ برای متن فارسی واقعی مسئله‌ساز است |
| 3 | `AUTH_ENABLED=false` درخواست admin را به payload ادمین محلی کوتاه می‌کند | پایین | رفتار عمدی dev؛ با auth روشن ۴۰۱/۲۰۰ تأیید شد |

### نقص شناخته‌شده: رد شدن نیم‌فاصله

`normalize_profile` هر کاراکتر با دستهٔ یونیکد `C*` را رد می‌کند. نیم‌فاصلهٔ فارسی (ZWNJ، U+200C) در دستهٔ `Cf` است، پس **متن فارسی طبیعی** که نیم‌فاصله داشته باشد در پروفایل رد می‌شود — مثلاً «کتاب‌های درسی». این در فاز ۲ آگاهانه کار نشد و مستند شد. باید در فاز ۴ یا ۵ حل شود، چون دانش‌آموز ایرانی تقریباً همیشه نیم‌فاصله تایپ می‌کند.

## ۱۰. نتیجه Gate

**Gate 2: PASS.**

دلیل: همهٔ معیارهای Acceptance پاس شدند و بازبینی امنیتی مستقل انجام شد. چهار نقص واقعی — از جمله یک دروازهٔ admin غایب — پیدا و بسته شدند. درس فرآیندی این فاز سه بار تکرار شد: **«E2E نداریم» با «E2E نوشته شده ولی اجرا نشده» فرق دارد.** آزمون‌هایی که خودشان باگ داشتند (`.first()` روی تصویر پنهان، regex `users` در برابر `User Management`، `startsWith("/login")` که `/admin/login` را نمی‌گرفت). آزمون اجرانشده با آزمون غایب فرقی ندارد.

## ۱۱. commit SHA و branch

- branch: `arena/85e21954-deeptutor`
- commits: ۴ commit (شامل `28e0124`, `3d885f3` برای اصلاحات، و commit جداگانهٔ گیت)
- PR: **#3** — merged با اجازهٔ صریح مالک → `67170c9fd746ba9376fb551dbfd8fbb778a80bac`
