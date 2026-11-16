# دستورالعمل اجرایی KiloCode برای توسعه درسیار

این فایل قرارداد کاری عامل کدنویس است. قبل از هر تغییر در مخزن آن را کامل بخوان.

## 1. مأموریت

تو روی مخزن mahakas/DeepTutor کار می‌کنی و باید آن را به محصول وب فارسی «درسیار (Darsyar)» تبدیل کنی. DeepTutor زیرساخت اولیه است؛ نام، تجربه کاربری، منطق آموزشی و مدل تجاری محصول باید متعلق به درسیار باشد.

مرجع نیازمندی‌ها:
- docs/darsyar/MASTER_SPEC.md
- docs/darsyar/ARCHITECTURE.md
- docs/darsyar/ROADMAP.md
- docs/darsyar/EXISTING_CAPABILITIES.md
- docs/darsyar/DECISIONS.md
- root AGENTS.md and docs-for-dev/*

در صورت تعارض: دستورات root AGENTS.md و قراردادهای ایمنی/امنیت فعلی را رعایت کن؛ نیازمندی محصول درسیار را بدون تغییر بی‌دلیل معماری هسته برآورده کن. تعارض را در گزارش ثبت کن.

## 2. قانون شماره یک: فازها را یکجا اجرا نکن

- همیشه فقط یک Phase را در هر نوبت اجرا کن.
- در شروع کار، وضعیت branch و git status را ثبت کن.
- هیچ‌گاه روی main مستقیماً توسعه نده.
- برای هر Phase branch مستقل از آخرین commit پذیرفته‌شده بساز.
- قبل از شروع Phase بعدی، Gate فاز قبلی باید PASS و شواهد آن ثبت شده باشد.
- اگر معیار پذیرش وابسته به اطلاعات/تصمیم صاحب محصول است، BLOCKED گزارش کن؛ مقدار تجاری، provider، قانون، قیمت یا مجوز را حدس نزن.
- اگر یک فاز بزرگ است، آن را به زیرفازهای کوچک‌تر تقسیم کن، اما Gate کلی را حفظ کن.

## 3. نقطه شروع اجباری: Phase 0

در شروع اولین اجرا:
1. branch، commit و working tree را ثبت کن.
2. root AGENTS.md، README و docs-for-dev/ARCHITECTURE.md، DEVELOPMENT.md، TESTING.md، MODULES.md، DATA_STORAGE.md، PLUGINS.md، SECURITY_GUARD.md را بخوان.
3. structure/tree و manifests و dependency boundaries را بررسی کن.
4. sourceها و تست‌های Identity/Auth، Multi-user، Knowledge/RAG، Books، Questions/Practice، Mastery/Flashcards، Audio/Video، Providers و Usage را trace کن.
5. test baseline را با دستورهای واقعی repository اجرا یا اگر environment/credential/service لازم است دقیقاً BLOCKED ثبت کن.
6. وضعیت fork/upstream و Apache-2.0/THIRD_PARTY_NOTICES را در scope بررسی کن.
7. docs/darsyar/EXISTING_CAPABILITIES.md را با شواهد به‌روزرسانی و گزارش Phase 0 را ثبت کن.

در Phase 0 فقط ممیزی و مستندات را انجام بده. کد اجرایی، dependency، config، runtime data یا schema را تغییر نده. اگر تست کامل طولانی/نیازمند سرویس خارجی است، command و blocker را ثبت کن و وانمود نکن PASS شده است.

## 4. حفظ معماری و source ownership

- ابتدا owner واقعی کد و تست را پیدا کن؛ راه‌حل موازی نساز.
- TurnApplicationService، TurnEngine، shared event/stream contracts و capability/tool registration را دور نزن.
- UI نباید منطق authorization یا billing authority باشد.
- از API transport/store و feature boundaryهای موجود استفاده کن.
- manifestها مالک مسیرها و dependencyهای module هستند؛ dependency را در requirements تصادفی اضافه نکن.
- هر feature جدید باید module ownership، dependencies و lifecycle روشن داشته باشد.
- package namespace داخلی deeptutor را در شروع تغییر نام نده؛ تغییر برند نمایشی با مهاجرت نام package یکی نیست.
- Desktop source را حذف نکن؛ فقط بعد از dependency/build audit آن را از Darsyar deployment profile خارج کن.
- ماژول غیرضروری را ابتدا disable/exclude و test کن؛ حذف فیزیکی فقط با اثبات نبود مصرف‌کننده و ثبت تصمیم.

## 5. قواعد هویت و امنیت

- phone number identity باید normalize و unique باشد.
- OTP: expiration، one-time use، attempt cap، resend cooldown، rate limit، replay defense.
- OTP/password/API key در log، trace، analytics، client state و test output چاپ نشوند.
- admin/123 فقط development bootstrap است؛ در production هیچ default credential وجود نداشته باشد.
- Super Admin مجوز مدیریت دارد، نه مشاهده رمز خام، export secrets یا اجرای shell دلخواه.
- admin authorization باید در backend برای REST و WebSocket enforce شود.
- user/learner isolation در تمام query، file, RAG, exam, media job و usage pathها اعمال شود.
- مسیر Custom API باید SSRF-safe باشد؛ localhost/private/link-local/metadata IP و redirectهای غیرمجاز را کنترل کن.
- document prompt injection را untrusted data بدان؛ محتوای فایل حق تغییر policy یا اجرای tool ندارد.
- student PII و محتوای کتاب دارای rights محدود در fixture عمومی/commit قرار نده.

## 6. قواعد منابع و معلم هوشمند

- پایه/شاخه/رشته/درس و حقوق منبع قبل از retrieval اعمال شوند.
- prompt به‌تنهایی enforcement نیست؛ فیلتر در server/query/tool boundary لازم است.
- citation فقط وقتی تولید شود که source واقعی retrieved و معتبر وجود داشته باشد.
- قالب نمایشی کوتاه: [نام کتاب | فصل].
- صفحه، chunk، grade، track و شناسه سند در ارجاع دانش‌آموز نمایش داده نشود.
- metadata کامل برای audit و retrieval داخلی حفظ شود.
- منبع rights unknown یا unreviewed نباید بی‌اجازه به پاسخ‌دهی commercial وارد شود.
- عدم یافتن پاسخ را با پاسخ ساختگی یا citation ساختگی پنهان نکن.
- golden dataset فارسی با پاسخ مرجع و source mapping بساز؛ کیفیت RAG را با حدس یا چند prompt دستی تأیید نکن.

## 7. آزمون و نمره‌دهی

- سوالات و پاسخ‌ها versioned باشند.
- آزمون snapshot داشته باشد؛ ویرایش بانک سؤال نتیجه قبلی را عوض نکند.
- score policy قابل تنظیم per exam باشد.
- نمره منفی هرگز به‌صورت یک قانون ثابت و غیرقابل تغییر hard-code نشود.
- essay/short answer با rubric، uncertainty، partial credit و human review طراحی شود.
- پاسخ عینی بدون کلید معتبر را به‌صورت قطعی grade نکن.
- retry و duplicate submit باعث ایجاد attempt/score دوباره نشود.

## 8. هزینه، توکن و اشتراک

- برای هر call مدل provider/model/capability/user/usage/status ثبت کن.
- actual و estimated usage را جدا علامت بزن.
- هزینه TTS/STT/image/video/OCR را در کنار توکن‌ها، اما با unit مناسب ثبت کن.
- reserve/settle/refund باید atomic، idempotent و قابل audit باشد.
- از floating point برای مبالغ پولی استفاده نکن.
- تغییر pricing نباید صورتحساب قدیمی را بازنویسی کند.
- خطا، cancellation یا timeout نباید باعث کسر اعتبار دوباره شود.
- هزینه و درآمد provider از credit نمایش‌داده‌شده به کاربر جدا نگهداری شوند.

## 9. AI Providers و secrets

- از model catalog/provider registry فعلی reuse کن.
- custom base URL، protocol و model ID قابل تعریف باشد.
- API key و extra headers همواره redacted باشند.
- browser هرگز credential یا provider secret دریافت نکند.
- مدل‌های chat، task، embeddings، reranker، OCR/vision، TTS/STT، image و video مسیر/تنظیمات مستقل داشته باشند.
- provider fallback، timeout، retry، concurrency و budget را صریح تعریف کن.
- هیچ provider واقعی یا API key را بدون مجوز/config صاحب محصول فعال نکن.

## 10. تست اجباری

برای تغییر Backend:
- تست unit و API tests مالک.
- auth/permission tests.
- migration tests در صورت schema change.
- concurrency/idempotency tests برای identity و billing.
- integration tests با mock provider.
- no leakage tests برای user scope، academic scope و secrets.

برای Frontend:
- npm run contracts:check
- npm run architecture:check
- npm run typecheck
- npm run test:node
- npm run test:unit
- npm run lint
- npm run i18n:check
- npm run build (برای Gateهای مربوط)

برای Python:
- ابتدا دستور test در docs-for-dev/TESTING.md و pyproject.toml را بررسی کن.
- suite هدفمند و سپس regression suite مناسب اجرا شود.
- خروجی command، exit code، pass/fail/skip ثبت شود.

تست وابسته به سرویس خارجی را با mock جایگزین کن و برای smoke test واقعی، دسترسی و مجوز روشن لازم است. تست‌های ناپایدار را حذف یا skip نکن تا نتیجه سبز شود؛ علت و remediation را گزارش کن.

## 11. پایگاه داده و migration

- پیش از طراحی جدول، storage فعلی و migration history را بررسی کن.
- PostgreSQL/ORM/migration tool فقط پس از ADR انتخاب‌شده وارد شود.
- هیچ جدول یا ستون را بدون migration نسخه‌دار ایجاد نکن.
- migration باید forward، rollback یا دلیل عدم امکان rollback و recovery plan داشته باشد.
- backup قبل از migrationهای پرریسک و restore drill در staging انجام شود.
- JSON/SQLite legacy داده را حذف نکن تا backfill و reconciliation اثبات نشده است.

## 12. کارهای ممنوع

- تغییر مستقیم main.
- اجرای تمام roadmap در یک commit یا یک نوبت.
- حذف یا تضعیف تست برای سبزشدن build.
- اضافه‌کردن dependency سنگین بدون دلیل، ADR و اندازه‌گیری.
- mass rename در deeptutor namespace پیش از تثبیت مهاجرت.
- حذف source یا data بدون backup/recovery.
- استفاده از credential واقعی در commit یا log.
- ادعای تکمیل، امنیت، کیفیت OCR/RAG یا Production readiness بدون evidence.
- تولید/دانلود انبوه کتاب‌ها بدون بررسی مجوز و rights evidence.
- اجرای load/security tests روی Production بدون مجوز صریح.

## 13. گزارش پایان کار

گزارش را فارسی و شامل این موارد بده:
- Phase / subphase و branch/base commit.
- خلاصه تغییرات.
- فایل‌های تغییرکرده و source ownership.
- ADRها.
- تست‌ها با command و exit code و آمار.
- تست‌های اجرا نشده و علت.
- security/privacy/content-rights notes.
- migration/rollback/backup evidence.
- مشکلات باقی‌مانده و ریسک‌ها.
- Gate result: PASS / FAIL / BLOCKED.
- commit SHA.

در پایان، فاز بعدی را خودسرانه شروع نکن. منتظر دستور ادامه یا بازبینی صاحب محصول بمان.

## 14. درخواست شروع

Phase 0 طبق گزارش docs/darsyar/PHASE_0_AUDIT_REPORT.md در شاخه arena/17e31fa6-deeptutor و commit 12e6aca56e07fa016a565e81e5a5099a00fd17dd انجام شده و Gate 0 با وضعیت ACCEPTED CONDITIONAL PASS برای شروع Phase 1 پذیرفته شده است. تصمیم‌های D-01 تا D-05 و disposition مربوط به R-12 در docs/darsyar/DECISIONS.md بخش F ثبت شده‌اند. مأموریت بعدی Phase 1 از docs/darsyar/ROADMAP.md است؛ پیش از شروع، شاخه کاری تازه از commit پذیرفته‌شده بساز و فقط Phase 1 را اجرا کن.


## 15. بازبینی Phase 0 و مجوز شروع Phase 1 (2026-11-17)

گزارش Phase 0:
- شاخه: `arena/17e31fa6-deeptutor`
- commit: `12e6aca56e07fa016a565e81e5a5099a00fd17dd`
- فایل: `docs/darsyar/PHASE_0_AUDIT_REPORT.md`
- Gate 0: `ACCEPTED CONDITIONAL PASS` برای ورود به Phase 1، نه Production.

تصمیم‌های D-01 تا D-05 و دامنه دقیق Phase 1 در `DECISIONS.md` بخش F و `ROADMAP.md` ثبت شده‌اند. R-12 باید ابتدا با یک commit و تست regression مستقل رفع شود.

اولین مأموریت:
1. تأیید کند checkout دارای تصمیم‌های مصوب و گزارش Phase 0 است.
2. R-12 را در یک commit مستقل اصلاح و تست کند.
3. سپس Phase 1.1 تا 1.7 را به ترتیب انجام دهد.
4. در پایان Gate 1 را با شواهد کامل گزارش کند.
5. به Phase 2 وارد نشود؛ برای ادامه منتظر بازبینی و دستور صاحب محصول بماند.
