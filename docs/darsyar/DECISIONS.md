# ثبت تصمیم‌های محصول و معماری درسیار

- نسخه: 1.0
- تاریخ: 2026-11-16

این سند بین خواسته‌های قطعی محصول، گزینه معماری پیشنهادی و تصمیم‌های باز تمایز می‌گذارد. «خواسته قطعی» به معنی تصمیم محصول است؛ الزاماً به معنی پیاده‌سازی یا تصویب فنی تمام جزئیات نیست.

## A. تصمیم‌های تثبیت‌شده محصول

| ID | تصمیم | وضعیت |
|---|---|---|
| D-001 | نام و برند محصول در UI: درسیار (Darsyar) | CONFIRMED |
| D-002 | محصول هدف وب‌محور است؛ Desktop جزو تجربه/استقرار اصلی نیست | CONFIRMED |
| D-003 | پنل کاربر و پنل مدیریت مسیر، layout و authorization مستقل دارند | CONFIRMED |
| D-004 | مسیرهای مدیریتی شامل /admin/login و /admin هستند | CONFIRMED |
| D-005 | اولین ثبت‌نام کاربر با شماره موبایل و OTP؛ ورود بعدی با شماره و رمز عبور | CONFIRMED |
| D-006 | کاربر باید پایه تحصیلی خود را مشخص کند؛ از پایه 10 به بعد شاخه/رشته متناسب انتخاب شود | CONFIRMED |
| D-007 | پایه‌های جاری 1 تا 12؛ پیش‌دانشگاهی و نظام‌های قدیمی در archive مجزا | CONFIRMED |
| D-008 | پاسخ درسی با منابع مجاز و scope آموزشی محدود می‌شود | CONFIRMED |
| D-009 | ارجاع نمایشی کوتاه و در حد نام کتاب و فصل است؛ صفحه/chunk/پایه/رشته نمایش داده نشود | CONFIRMED |
| D-010 | منابع شامل کتاب رسمی، کمک‌آموزشی، جزوه، نمونه سؤال و کنکور است | CONFIRMED |
| D-011 | آزمون تشریحی، چهارگزینه‌ای و کنکوری با نمره منفی قابل تنظیم لازم است | CONFIRMED |
| D-012 | فلش‌کارت و Spaced Review موجود ابتدا reuse و یکپارچه شوند؛ سیستم موازی بدون دلیل ساخته نشود | CONFIRMED |
| D-013 | token usage و هزینه سرویس‌های غیرتوکنی برای پلن تجاری حیاتی است | CONFIRMED |
| D-014 | Audio/Video/Slides/Mind-map و قابلیت‌های مشابه Studio به‌شکل تدریجی اضافه شوند | CONFIRMED |
| D-015 | پنل مدیریت باید کنترل جامع کاربران، محتوا، AI، API، پلن، مصرف و تنظیمات را داشته باشد | CONFIRMED |
| D-016 | Custom AI API و انتخاب Provider/Model لازم است | CONFIRMED |
| D-017 | هسته مفید DeepTutor حفظ و قابلیت‌های نامرتبط از محصول/استقرار غیرفعال شوند؛ حذف source فقط با audit | CONFIRMED |
| D-018 | حساب اولیه admin/123 فقط برای development مجاز است و باید اولین ورود عوض شود | CONFIRMED AS DEV-ONLY |

## B. گزینه‌های معماری پیشنهادی؛ هنوز نیازمند ADR

| ID | پیشنهاد | چرا نیازمند ADR است؟ |
|---|---|---|
| P-001 | PostgreSQL به‌عنوان source of truth داده تجاری | باید با storage فعلی، multi-user و migration سازگار شود |
| P-002 | SQLAlchemy 2 + Alembic برای مدل و migration | باید dependency و سبک موجود بررسی شود |
| P-003 | Object storage abstraction برای فایل‌های بزرگ و media assets | باید محیط deploy و هزینه انتخاب شود |
| P-004 | Queue/worker برای ingestion و media jobs | باید orchestration موجود و نیاز concurrency ارزیابی شود |
| P-005 | استفاده از RAG adapter فعلی پیش از انتخاب vector backend جدید | نیازمند benchmark فارسی و ریاضی |
| P-006 | pgvector فقط در صورت برتری اثبات‌شده در benchmark | انتخاب vector store نباید صرفاً از سلیقه باشد |
| P-007 | SMS provider abstraction و سپس gateway انتخابی | gateway، هزینه، محدودیت تحویل و compliance باید مشخص شود |
| P-008 | Pricing versioned + transactional wallet ledger | واحد پول، تعرفه و refund policy باید تعیین شوند |
| P-009 | Provider secret encryption/rotation و egress controls | باید deployment secret manager و تهدید SSRF بررسی شود |
| P-010 | MFA مدیران در Production | باید UX و recovery flow تعریف شود |

## C. موضوعات باز که نباید با حدس نهایی شوند

1. کدام درگاه پیامک ایرانی برای OTP انتخاب می‌شود؟
2. واحد پول محصول و واحد نمایش/ثبت حسابداری چیست؟
3. پلن‌های اولیه، قیمت، سهمیه و سیاست refund چه هستند؟
4. کدام درگاه پرداخت برای خرید اشتراک استفاده می‌شود؟
5. آیا و در چه شرایطی کاربر می‌تواند خارج از کتاب‌های انتخاب‌شده سؤال بپرسد؟
6. منابع آموزشی مکمل چه شواهد مجوز و چه محدوده استفاده دارند؟
7. سیاست حفظ/حذف سوابق دانش‌آموز و رضایت والد/سرپرست چگونه است؟
8. grading تشریحی تا چه حد خودکار باشد و چه نوعی بازبینی انسانی لازم دارد؟
9. providerهای OCR، embedding، reranker، TTS و video در اولین استقرار کدام‌اند؟
10. حجم مورد انتظار کاربران همزمان و بودجه زیرساخت چقدر است؟

## D. محدودیت‌های امنیتی غیرقابل مذاکره

- رمز خام کاربران هرگز قابل مشاهده نیست.
- API key و OTP در response/log/browser افشا نمی‌شوند.
- Super Admin مجوز اجرای shell دلخواه یا خواندن secretهای OS را از پنل نمی‌گیرد.
- scope پایه/رشته و rights منابع توسط Backend enforce می‌شود.
- تراکنش اعتبار و مصرف idempotent و audit-able است.
- Production default credential ندارد.
- سند/فایل آپلودشده به‌عنوان prompt/instruction مورد اعتماد اجرا نمی‌شود.

## E. مدیریت تغییر تصمیم

هر تصمیمی که روی database، identity، auth، RAG retrieval, billing، provider credentials، media job lifecycle یا data retention اثر می‌گذارد باید ADR اختصاصی با status، context، options، consequences، migration و rollback داشته باشد. این سند نباید به‌جای ADR جزئیات اجرای production را تصویب کند.
