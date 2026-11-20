# ممیزی قابلیت‌های موجود DeepTutor برای درسیار

- تاریخ: 2026-11-16
- مبنای ممیزی: مخزن mahakas/DeepTutor، شاخه main، commit 4c1e000d8563c5ac3b231baaaf149dc4dc4d2406 (v1.7.3)
- نوع بررسی: خواندن ساختار repository، manifestها و فایل‌های source منتخب؛ اجرای تست یا ممیزی خط‌به‌خط کل مخزن در این مرحله انجام نشده است.

## معنی وضعیت‌ها

- موجود: کد/صفحه/manifest در repository دیده شده؛ کیفیت و آمادگی تجاری هنوز تأیید نشده.
- موجود، نیازمند تطبیق: زیرساخت مرتبط وجود دارد، اما رفتار موردنیاز درسیار دقیقاً همان نیست.
- نیازمند توسعه: پیاده‌سازی هدف از شواهد بررسی‌شده تأیید نشده است.
- نیازمند آزمون: کد مربوط وجود دارد، ولی جزئیات مهم باید با تست/بازبینی تأیید شود.
- حذف/غیرفعال‌سازی: فقط از محصول و استقرار درسیار کنار گذاشته می‌شود؛ حذف source نیازمند dependency audit است.

## ماتریس قابلیت‌ها

| حوزه | شواهد در مخزن | وضعیت برای درسیار | اقدام |
|---|---|---|---|
| هسته Agent و Turn Runtime | deeptutor/runtime، deeptutor/app، capability/tool registries | موجود و حیاتی | حفظ؛ فقط adapter/policy لازم تغییر کند |
| رابط وب | web/app، Next.js App Router | موجود | حفظ؛ branding، فارسی و UX بازطراحی شود |
| ورود کاربر | deeptutor/api/routers/auth.py، deeptutor/services/auth.py، web/app/(auth) | موجود، نیازمند تطبیق | افزودن phone+OTP و flow تعیین رمز |
| مدیریت کاربران | deeptutor/api/routers/multi_user.py، multi_user/identity.py، web/app/(admin)/admin/users | موجود، نیازمند تطبیق | افزودن عملیات کامل و انتقال به storage مرکزی |
| Super Admin | نقش admin و require_admin در auth/API | موجود، نیازمند آزمون | جداسازی super_admin، bootstrap امن و MFA |
| SMS OTP | در مسیرهای بررسی‌شده قابلیت تأییدشده یافت نشد | نیازمند توسعه | interface، provider، OTP lifecycle و abuse controls |
| ذخیره هویت | multi_user/identity.py و users.json | موجود اما فایل‌محور | طرح مهاجرت تراکنشی؛ storage نهایی با ADR |
| Knowledge Base | deeptutor/knowledge، API knowledge و UI components | موجود | حفظ؛ کاتالوگ منابع ایرانی و rights workflow افزوده شود |
| RAG و retrieval | deeptutor/services/rag، متعدد pipeline و adapter | موجود | حفظ و اعمال academic/rights filters قبل از retrieval |
| کتاب‌ها | deeptutor/book، api/routers/book.py، modules/manifests/books.json | موجود اما هدف آن عیناً کاتالوگ کتب رسمی نیست | reuse مدل‌های آموزشی قابل استفاده؛ طراحی official textbook catalog |
| پردازش PDF | document extractor، parser modules و indexing | موجود با provider/extraهای اختیاری | benchmark فارسی، ریاضی، OCR و isolation |
| کاتالوگ پایه/رشته ایران | ساختار کامل هدف در شواهد منتخب دیده نشد | نیازمند توسعه | academic catalog داده‌محور |
| محدودیت سخت پایه/رشته در RAG | multi-user/knowledge scope موجود؛ policy مخصوص curriculum باید اثبات شود | نیازمند تکمیل و تست | query-level filters و adversarial tests |
| تولید سؤال | deeptutor/agents/question، API question، question bank | موجود | reuse و فارسی‌سازی/منبع‌محوری |
| بانک سؤال و تمرین | deeptutor/tools/question_bank.py، api/routers/practice.py، services/practice | موجود | افزودن metadata منبع و نسخه‌بندی آزمون |
| تصحیح عینی | services/practice/answers.py | موجود با محدودیت نوع سؤال | حفظ؛ تست edge cases |
| تصحیح تشریحی rubricدار | answers.py برای essay/short answer نتیجه قطعی نمی‌دهد | نیازمند توسعه | rubric grading، uncertainty و بازبینی انسانی |
| نمره منفی کنکوری | در sourceهای بررسی‌شده تأیید نشد | نیازمند توسعه و تست | score policy پیکربندی‌شده per exam |
| فلش‌کارت | deeptutor/book/blocks/flash_cards.py، FlashCardsBlock UI | موجود | حفظ و اتصال به منابع رسمی/کمکی |
| مرور فاصله‌دار | deeptutor/capabilities/mastery و manifest mastery | موجود | حفظ؛ بررسی فارسی و یکپارچه‌سازی با آزمون |
| پادکست/Audio Overview | deeptutor/capabilities/audio_overview و manifest | موجود | حفظ؛ ارزیابی صدای فارسی، هزینه و حقوق منابع |
| ویدئوی آموزشی | deeptutor/agents/video_lesson و manifest video-lesson | موجود | حفظ اختیاری؛ فارسی‌سازی و job isolation |
| اسلاید/نقشه ذهنی/اینفوگرافیک | ابزارهای visualize/notes موجودند، ولی workflow یکپارچه NotebookLM باید ارزیابی شود | موجود جزئی/نیازمند تطبیق | reuse فقط پس از audit |
| ثبت مصرف LLM | deeptutor/services/llm/usage_ledger.py، usage_statistics.py | موجود اما SQLite محلی | حفظ اندازه‌گیری؛ ledger تجاری متمرکز لازم |
| پلن و wallet تجاری | در شواهد بررسی‌شده قرارداد کامل تجاری تأیید نشد | نیازمند توسعه | entitlement و reserve/settle/refund |
| Custom Provider UI | web/components/settings/AddProviderPanel.tsx، model_catalog.py | موجود | منتقل/محدودسازی به پنل admin و تست امنیت |
| Routing مدل‌ها | model catalog/provider registry | موجود | routing per capability و per plan |
| API secret redaction | model_catalog.py قابلیت redact دارد | موجود در بخشی از تنظیمات | review کامل همه APIها، logs و secret lifecycle |
| PostgreSQL مرکزی | dependency/architecture فعلی بر file/SQLite و storageهای مختلف است | نیازمند تصمیم و توسعه | ADR و migration strategy |
| پنل admin جامع | admin users و تنظیمات متعدد وجود دارد | موجود جزئی | یکپارچه‌سازی در مرکز کنترل درسیار |
| Desktop | apps/desktop و workflows مربوط | موجود، خارج از محصول هدف | از build/deploy درسیار کنار گذاشته شود؛ source فعلاً حفظ شود |

## منبع‌های مهمی که باید پیش از توسعه عمیق خوانده شوند

### هویت و مدیریت
- deeptutor/api/routers/auth.py
- deeptutor/api/routers/multi_user.py
- deeptutor/services/auth.py
- deeptutor/multi_user/identity.py
- deeptutor/multi_user/models.py
- web/app/(auth)/login/page.tsx
- web/app/(admin)/admin/users/page.tsx
- web/lib/admin-api.ts

### منابع و RAG
- deeptutor/api/routers/knowledge.py
- deeptutor/knowledge/manager.py
- deeptutor/services/rag/service.py
- deeptutor/services/rag/smart_retriever.py
- deeptutor/services/rag/source_pages.py
- deeptutor/core/source_context.py
- deeptutor/textbook_struct/

### سؤال، آزمون و یادگیری
- deeptutor/modules/manifests/questions.json
- deeptutor/modules/manifests/mastery.json
- deeptutor/api/routers/practice.py
- deeptutor/services/practice/answers.py
- deeptutor/book/blocks/flash_cards.py
- deeptutor/capabilities/mastery/

### چندرسانه‌ای و مدل
- deeptutor/modules/manifests/audio-overview.json
- deeptutor/capabilities/audio_overview/
- deeptutor/modules/manifests/video-lesson.json
- deeptutor/agents/video_lesson/
- deeptutor/services/config/model_catalog.py
- deeptutor/services/provider_registry.py
- web/components/settings/AddProviderPanel.tsx

### مصرف
- deeptutor/services/llm/usage_ledger.py
- deeptutor/services/session/usage_statistics.py
- deeptutor/runtime/agentic/usage.py

## نتیجه ممیزی

DeepTutor بخش قابل توجهی از پایه‌های هوشمند و آموزشی درسیار را فراهم می‌کند. بزرگ‌ترین gapهای محصول عبارت‌اند از: SMS OTP، academic catalog ایران، rights-aware source management، enforce کردن سخت scope آموزشی، تصحیح تشریحی rubricدار، نمره منفی آزمون، حسابداری/اشتراک متمرکز و پنل مدیریتی یکپارچه.

این جدول مبنای Phase 0 است و در زمان اجرای آن باید با فایل‌ها، تست‌ها و وضعیت واقعی branch فعلی دوباره راستی‌آزمایی شود.
