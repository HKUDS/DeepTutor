<div align="center">

<img src="../../assets/logo-ver2.png" alt="DeepTutor" width="140" style="border-radius: 15px;">

# DeepTutor: تعليم شخصي أصلي قائم على الوكلاء

<a href="https://trendshift.io/repositories/17099" target="_blank"><img src="https://trendshift.io/api/badge/repositories/17099" alt="HKUDS%2FDeepTutor | Trendshift" style="width: 250px; height: 55px;" width="250" height="55"/></a>

[![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-3776AB?style=flat-square&logo=python&logoColor=white)](https://www.python.org/downloads/)
[![Next.js 16](https://img.shields.io/badge/Next.js-16-000000?style=flat-square&logo=next.js&logoColor=white)](https://nextjs.org/)
[![License](https://img.shields.io/badge/License-Apache_2.0-blue?style=flat-square)](../../LICENSE)
[![GitHub release](https://img.shields.io/github/v/release/HKUDS/DeepTutor?style=flat-square&color=brightgreen)](https://github.com/HKUDS/DeepTutor/releases)
[![arXiv](https://img.shields.io/badge/arXiv-2604.26962-b31b1b?style=flat-square&logo=arxiv&logoColor=white)](https://arxiv.org/abs/2604.26962)

[![Discord](https://img.shields.io/badge/Discord-Community-5865F2?style=flat-square&logo=discord&logoColor=white)](https://discord.gg/eRsjPgMU4t)
[![Feishu](https://img.shields.io/badge/Feishu-Group-00D4AA?style=flat-square&logo=feishu&logoColor=white)](../../Communication.md)
[![WeChat](https://img.shields.io/badge/WeChat-Group-07C160?style=flat-square&logo=wechat&logoColor=white)](https://github.com/HKUDS/DeepTutor/issues/78)

[الميزات](#key-features) · [البدء](#get-started) · [استكشاف](#explore-deeptutor) · [TutorBot](#tutorbot) · [CLI](#deeptutor-cli-guide) · [خارطة الطريق](#roadmap) · [المجتمع](#community)

[🇬🇧 English](../../README.md) · [🇨🇳 中文](README_CN.md) · [🇯🇵 日本語](README_JA.md) · [🇪🇸 Español](README_ES.md) · [🇫🇷 Français](README_FR.md) · [🇷🇺 Русский](README_RU.md) · [🇮🇳 हिन्दी](README_HI.md) · [🇵🇹 Português](README_PT.md) · [🇹🇭 ภาษาไทย](README_TH.md) · 🇵🇱 [Polski](README_PL.md)

</div>

---

> 🤝 **نرحّب بجميع أنواع المساهمات!** راجع [دليل المساهمة](../../CONTRIBUTING.md) لاستراتيجية الفروع ومعايير البرمجة وكيفية البدء.

### 📦 الإصدارات

> **[2026.5.9]** [v1.3.9](https://github.com/HKUDS/DeepTutor/releases/tag/v1.3.9) — دعم TutorBot لقناتي Zulip وNVIDIA NIM، توجيه أكثر أمانًا لنماذج التفكير، أمر `deeptutor start`، تلميحات الشريط الجانبي، وتكافؤ مخزن الجلسات.

> **[2026.5.8]** [v1.3.8](https://github.com/HKUDS/DeepTutor/releases/tag/v1.3.8) — نشر اختياري متعدد المستخدمين مع مساحات عمل معزولة، صلاحيات يديرها المسؤول، مسارات مصادقة، ووصول runtime محدود النطاق.

> **[2026.5.4]** [v1.3.7](https://github.com/HKUDS/DeepTutor/releases/tag/v1.3.7) — إصلاحات نماذج التفكير / المزودين، إظهار تاريخ فهرس المعرفة، وزيادة أمان مسح Co-Writer وتحرير القوالب.

> **[2026.5.3]** [v1.3.6](https://github.com/HKUDS/DeepTutor/releases/tag/v1.3.6) — اختيار النماذج عبر الكتالوج في الدردشة وTutorBot، إعادة فهرسة RAG أكثر أمانًا، إصلاحات حد الرموز في OpenAI Responses، والتحقق من محرر Skills.

> **[2026.5.2]** [v1.3.5](https://github.com/HKUDS/DeepTutor/releases/tag/v1.3.5) — إعدادات تشغيل محلية أكثر سلاسة، استعلامات RAG أكثر أمانًا، مصادقة تضمين محلية أوضح، ومعالجة الوضع المظلم في الإعدادات.

> **[2026.5.1]** [v1.3.4](https://github.com/HKUDS/DeepTutor/releases/tag/v1.3.4) — استمرارية دردشة صفحة الكتاب وتدفقات إعادة البناء، مراجع من الدردشة إلى الكتاب، معالجة أقوى للغة/التفكير، تقوية استخراج وثائق RAG.

> **[2026.4.30]** [v1.3.3](https://github.com/HKUDS/DeepTutor/releases/tag/v1.3.3) — دعم تضمين NVIDIA NIM وGemini، سياق Space موحّد لسجل الدردشة / المهارات / الذاكرة، لقطات الجلسة، مرونة إعادة فهرسة RAG.

> **[2026.4.29]** [v1.3.2](https://github.com/HKUDS/DeepTutor/releases/tag/v1.3.2) — عناوين URL شفافة لنقاط نهاية التضمين، مرونة إعادة فهرسة RAG للمتجهات المخزّنة غير الصالحة، تنظيف الذاكرة لمخرجات نماذج التفكير، إصلاح وقت تشغيل Deep Solve.

> **[2026.4.28]** [v1.3.1](https://github.com/HKUDS/DeepTutor/releases/tag/v1.3.1) — الاستقرار: توجيه RAG أكثر أمانًا والتحقق من التضمين، استمرارية Docker، إدخال آمن مع IME، قوة على Windows/GBK.

> **[2026.4.27]** [v1.3.0](https://github.com/HKUDS/DeepTutor/releases/tag/v1.3.0) — فهارس KB ذات إصدار مع سير إعادة الفهرسة، إعادة بناء مساحة المعرفة، اكتشاف تلقائي للتضمين مع محولات جديدة، مركز Space.

> **[2026.4.25]** [v1.2.5](https://github.com/HKUDS/DeepTutor/releases/tag/v1.2.5) — مرفقات دردشة دائمة مع درج معاينة الملفات، خطوط أنابيب قدرات تدرك المرفقات، تصدير Markdown لـ TutorBot.

> **[2026.4.25]** [v1.2.4](https://github.com/HKUDS/DeepTutor/releases/tag/v1.2.4) — مرفقات نص / شيفرة / SVG، جولة إعداد بأمر واحد، تصدير الدردشة Markdown، واجهة إدارة KB مدمجة.

<details>
<summary><b>إصدارات أقدم (أكثر من أسبوعين)</b></summary>

> **[2026.4.24]** [v1.2.3](https://github.com/HKUDS/DeepTutor/releases/tag/v1.2.3) — مرفقات مستندات (PDF/DOCX/XLSX/PPTX)، عرض كتلة تفكير النموذج، محرّر قوالب Soul، حفظ Co-Writer في الدفتر.

> **[2026.4.22]** [v1.2.2](https://github.com/HKUDS/DeepTutor/releases/tag/v1.2.2) — نظام Skills من إنشاء المستخدم، تحسين أداء إدخال الدردشة، بدء تلقائي لـ TutorBot، واجهة مكتبة الكتب، تصور بملء الشاشة.

> **[2026.4.21]** [v1.2.1](https://github.com/HKUDS/DeepTutor/releases/tag/v1.2.1) — حدود رموز لكل مرحلة، إعادة توليد الرد عبر جميع نقاط الدخول، إصلاحات توافق RAG وGemma.

> **[2026.4.20]** [v1.2.0](https://github.com/HKUDS/DeepTutor/releases/tag/v1.2.0) — مُجمّع Book Engine ل«كتب حية»، Co-Writer متعدد المستندات، تصورات HTML تفاعلية، إشارات @ لبنك الأسئلة في الدردشة.

> **[2026.4.18]** [v1.1.2](https://github.com/HKUDS/DeepTutor/releases/tag/v1.1.2) — تبويب القنوات المستند إلى المخطط، دمج RAG في مسار واحد، مطالبات الدردشة خارج الكود.

> **[2026.4.17]** [v1.1.1](https://github.com/HKUDS/DeepTutor/releases/tag/v1.1.1) — «أجب الآن» شامل، مزامنة تمرير Co-Writer، لوحة إعدادات موحّدة، زر إيقاف أثناء البث.

> **[2026.4.15]** [v1.1.0](https://github.com/HKUDS/DeepTutor/releases/tag/v1.1.0) — إعادة هيكلة تحليل صيغ LaTeX في الكتل؛ فحص تشخيص LLM عبر `agents.yaml`؛ إصلاح تمرير رؤوس HTTP إضافية؛ إصلاح UUID في SaveToNotebook؛ إرشادات Docker وLLM محلي.

> **[2026.4.14]** [v1.1.0-beta](https://github.com/HKUDS/DeepTutor/releases/tag/v1.1.0-beta) — جلسات قابلة للإشارة عبر URL؛ سمة Snow؛ نبض WebSocket وإعادة اتصال تلقائية؛ تحسين أداء ChatComposer؛ إعادة هيكلة سجل مزوّدي التضمين؛ مزوّد بحث Serper.

> **[2026.4.13]** [v1.0.3](https://github.com/HKUDS/DeepTutor/releases/tag/v1.0.3) — دفتر أسئلة مع إشارات مرجعية وفئات؛ Mermaid في Visualize؛ كشف عدم تطابق نماذج التضمين؛ توافق Qwen/vLLM؛ دعم LM Studio وllama.cpp؛ سمة Glass.

> **[2026.4.11]** [v1.0.2](https://github.com/HKUDS/DeepTutor/releases/tag/v1.0.2) — دمج البحث مع احتياطي SearXNG؛ إصلاح تبديل المزوّد؛ تسرّب موارد في الواجهة.

> **[2026.4.10]** [v1.0.1](https://github.com/HKUDS/DeepTutor/releases/tag/v1.0.1) — قدرة Visualize ‎(Chart.js/SVG)؛ منع تكرار الاختبارات؛ دعم نموذج o4-mini.

> **[2026.4.10]** [v1.0.0-beta.4](https://github.com/HKUDS/DeepTutor/releases/tag/v1.0.0-beta.4) — تتبع تقدّم التضمين مع إعادة المحاولة عند حد المعدل؛ إصلاحات تبعيات متعددة المنصات؛ التحقق من MIME.

> **[2026.4.8]** [v1.0.0-beta.3](https://github.com/HKUDS/DeepTutor/releases/tag/v1.0.0-beta.3) — SDK أصلي لـ OpenAI/Anthropic (بدون litellm)؛ Math Animator على Windows؛ تحليل JSON أقوى؛ تعريب صيني كامل.

> **[2026.4.7]** [v1.0.0-beta.2](https://github.com/HKUDS/DeepTutor/releases/tag/v1.0.0-beta.2) — إعادة تحميل الإعدادات الساخنة؛ مخرجات MinerU المتداخلة؛ إصلاح WebSocket؛ الحد الأدنى Python 3.11+.

> **[2026.4.4]** [v1.0.0-beta.1](https://github.com/HKUDS/DeepTutor/releases/tag/v1.0.0-beta.1) — إعادة كتابة أصلية للمعمار (‎~200k سطر): نموذج إضافات Tools + Capabilities، وCLI وSDK، وTutorBot، وCo-Writer، وتعليم موجّه، وذاكرة دائمة.

> **[2026.1.23]** [v0.6.0](https://github.com/HKUDS/DeepTutor/releases/tag/v0.6.0) — استمرارية الجلسات، رفع تدريجي، RAG مرن، تعريب صيني كامل.

> **[2026.1.18]** [v0.5.2](https://github.com/HKUDS/DeepTutor/releases/tag/v0.5.2) — Docling، سجلات، إصلاحات.

> **[2026.1.15]** [v0.5.0](https://github.com/HKUDS/DeepTutor/releases/tag/v0.5.0) — إعداد موحّد، RAG لكل قاعدة معرفة، توليد أسئلة، شريط جانبي.

> **[2026.1.9]** [v0.4.0](https://github.com/HKUDS/DeepTutor/releases/tag/v0.4.0) — مزوّدو LLM/تضمينات متعددون، صفحة رئيسية جديدة، فصل RAG، متغيرات البيئة.

> **[2026.1.5]** [v0.3.0](https://github.com/HKUDS/DeepTutor/releases/tag/v0.3.0) — PromptManager، CI/CD، صور GHCR.

> **[2026.1.2]** [v0.2.0](https://github.com/HKUDS/DeepTutor/releases/tag/v0.2.0) — Docker، Next.js 16 وReact 19، WebSocket، ثغرات.

</details>

### 📰 الأخبار

> **[2026.4.19]** 🎉 وصلنا 20k نجمة بعد 111 يومًا! شكرًا لدعمكم — نواصل التطوير نحو تدريس مخصّص وذكي حقًا.

> **[2026.4.10]** 📄 ورقتنا متاحة الآن على arXiv! اطّلع على [النسخة الأولية](https://arxiv.org/abs/2604.26962) لتعرف التصميم والأفكار وراء DeepTutor.

> **[2026.4.4]** منذ زمن غائبين! ✨ DeepTutor v1.0.0 وصل أخيرًا — تطور أصلي للوكلاء مع إعادة بناء المعمار من الصفر وTutorBot وأوضاع مرنة بموجب Apache-2.0. فصل جديد يبدأ!

> **[2026.2.6]** 🚀 10k نجوم في 39 يومًا — شكرًا للمجتمع!

> **[2026.1.1]** سنة جديدة سعيدة! انضم إلى [Discord](https://discord.gg/eRsjPgMU4t) أو [WeChat](https://github.com/HKUDS/DeepTutor/issues/78) أو [Discussions](https://github.com/HKUDS/DeepTutor/discussions).

> **[2025.12.29]** إطلاق DeepTutor رسميًا.

<a id="key-features"></a>
## ✨ أبرز الميزات

- **مساحة دردشة موحّدة** — ستة أوضاع في سلسلة واحدة: دردشة، Deep Solve، اختبارات، Deep Research، Math Animator وVisualize تتشارك السياق.
- **AI Co-Writer** — مساحة Markdown متعددة المستندات: إعادة صياغة، توسيع، اختصار مع قاعدة المعرفة والويب.
- **Book Engine** — «كتب حية» منظّمة وتفاعلية: خط أنابيب متعدّد الوكلاء، 13 نوع كتل (اختبارات، بطاقات، جداول زمنية، رسوم مفاهيم، إلخ).
- **مركز المعرفة** — قواعد RAG، دفاتر ملوّنة، بنك أسئلة، Skills مخصّصة لتشكيل أسلوب التدريس.
- **ذاكرة دائمة** — ملخّص التقدّم وملف المتعلّم؛ مشتركة مع TutorBots.
- **TutorBots شخصية** — ليست روبوتات دردشة: مدرّسون مستقلّون بمساحة عمل وذاكرة وشخصية ومهارات. يعمل بـ [nanobot](https://github.com/HKUDS/nanobot).
- **CLI أصلي للوكلاء** — القدرات وقواعد المعرفة والجلسات وTutorBot بأمر واحد؛ Rich وJSON. [`SKILL.md`](../../SKILL.md).

---

<a id="get-started"></a>
## 🚀 البدء

### المتطلبات المسبقة

قبل البدء، تأكد من تثبيت ما يلي:

| المتطلب | الإصدار | التحقق | ملاحظات |
|:---|:---|:---|:---|
| [Git](https://git-scm.com/) | أي | `git --version` | لاستنساخ المستودع |
| [Python](https://www.python.org/downloads/) | 3.11+ | `python --version` | الخادم الخلفي |
| [Node.js](https://nodejs.org/) | 20.9+ | `node --version` | وقت تشغيل الواجهة الأمامية للتثبيت المحلي عبر الويب |
| [npm](https://www.npmjs.com/) | مُدرج مع Node.js | `npm --version` | يُثبَّت مع Node.js |

تحتاج أيضًا **مفتاح API** من مزوّد LLM واحد على الأقل (مثل [OpenAI](https://platform.openai.com/api-keys) أو [DeepSeek](https://platform.deepseek.com/) أو [Anthropic](https://console.anthropic.com/)). جولة الإعداد ترشدك لإدخاله.

### الخيار A — جولة الإعداد (موصى به)

**سكربت CLI تفاعلي واحد** ينقلك من استنساخ جديد إلى تطبيق يعمل — بلا `pip install` يدوي ولا `npm install` ولا تحرير `.env`. تُكشف التبعيات وتُثبَّت وتُضبط في دفق موجّه من 7 خطوات.

```bash
git clone https://github.com/HKUDS/DeepTutor.git
cd DeepTutor

# بيئة Python الافتراضية (اختر واحدة):
conda create -n deeptutor python=3.11 && conda activate deeptutor   # Anaconda/Miniconda
python -m venv .venv && source .venv/bin/activate                    # macOS/Linux
python -m venv .venv && .venv\Scripts\activate                       # Windows

# بدء الجولة
python scripts/start_tour.py
```

بعد انتهاء المساعد:

```bash
python scripts/start_web.py
```

> **التشغيل اليومي** — غالبًا تكفي جولة واحدة. بعدها نفّذ `python scripts/start_web.py` لبدء الخادمين معًا (يُعرض عنوان الواجهة في الطرفية). أعد `start_tour.py` فقط لإعادة التهيئة أو تغيير المنافذ أو تثبيت إضافات. في **الإعدادات** على الويب يمكن الضغط على **Run Tour** لإعادة جولة واجهة مُميّزة.

<a id="option-b-manual"></a>
### الخيار B — تثبيت يدوي محلي

إذا أردت التحكم الكامل، ثبّت واضبط كل شيء بنفسك.

**1. تثبيت التبعيات**

```bash
git clone https://github.com/HKUDS/DeepTutor.git
cd DeepTutor

# إنشاء وتفعيل البيئة الافتراضية (كما في الخيار A)
conda create -n deeptutor python=3.11 && conda activate deeptutor

# DeepTutor مع تبعيات الخادم الخلفي + الويب
pip install -e ".[server]"

# الواجهة (يتطلب Node.js 18+)
cd web && npm install && cd ..
```

**2. ضبط البيئة**

```bash
cp .env.example .env
```

حرّر `.env` واملأ الحقول المطلوبة على الأقل:

```dotenv
# LLM (مطلوب)
LLM_BINDING=openai
LLM_MODEL=gpt-4o-mini
LLM_API_KEY=sk-xxx
LLM_HOST=https://api.openai.com/v1

# التضمين (مطلوب لقاعدة المعرفة)
EMBEDDING_BINDING=openai
EMBEDDING_MODEL=text-embedding-3-large
EMBEDDING_API_KEY=sk-xxx
EMBEDDING_HOST=https://api.openai.com/v1
EMBEDDING_DIMENSION=3072
```

<details>
<summary><b>مزوّدو LLM المدعومون</b></summary>

| المزوّد | Binding | عنوان Base الافتراضي |
|:--|:--|:--|
| AiHubMix | `aihubmix` | `https://aihubmix.com/v1` |
| Anthropic | `anthropic` | `https://api.anthropic.com/v1` |
| Azure OpenAI | `azure_openai` | — |
| BytePlus | `byteplus` | `https://ark.ap-southeast.bytepluses.com/api/v3` |
| BytePlus Coding Plan | `byteplus_coding_plan` | `https://ark.ap-southeast.bytepluses.com/api/coding/v3` |
| Custom | `custom` | — |
| Custom (Anthropic API) | `custom_anthropic` | — |
| DashScope | `dashscope` | `https://dashscope.aliyuncs.com/compatible-mode/v1` |
| DeepSeek | `deepseek` | `https://api.deepseek.com` |
| Gemini | `gemini` | `https://generativelanguage.googleapis.com/v1beta/openai/` |
| GitHub Copilot | `github_copilot` | `https://api.githubcopilot.com` |
| Groq | `groq` | `https://api.groq.com/openai/v1` |
| llama.cpp | `llama_cpp` | `http://localhost:8080/v1` |
| LM Studio | `lm_studio` | `http://localhost:1234/v1` |
| MiniMax | `minimax` | `https://api.minimaxi.com/v1` |
| MiniMax (Anthropic) | `minimax_anthropic` | `https://api.minimaxi.com/anthropic` |
| Mistral | `mistral` | `https://api.mistral.ai/v1` |
| Moonshot | `moonshot` | `https://api.moonshot.cn/v1` |
| Ollama | `ollama` | `http://localhost:11434/v1` |
| OpenAI | `openai` | `https://api.openai.com/v1` |
| OpenAI Codex | `openai_codex` | `https://chatgpt.com/backend-api` |
| OpenRouter | `openrouter` | `https://openrouter.ai/api/v1` |
| OpenVINO Model Server | `ovms` | `http://localhost:8000/v3` |
| Qianfan | `qianfan` | `https://qianfan.baidubce.com/v2` |
| SiliconFlow | `siliconflow` | `https://api.siliconflow.cn/v1` |
| Step Fun | `stepfun` | `https://api.stepfun.com/v1` |
| vLLM/Local | `vllm` | — |
| VolcEngine | `volcengine` | `https://ark.cn-beijing.volces.com/api/v3` |
| VolcEngine Coding Plan | `volcengine_coding_plan` | `https://ark.cn-beijing.volces.com/api/coding/v3` |
| Xiaomi MIMO | `xiaomi_mimo` | `https://api.xiaomimimo.com/v1` |
| Zhipu AI | `zhipu` | `https://open.bigmodel.cn/api/paas/v4` |

</details>

<details>
<summary><b>مزوّدو التضمين المدعومون</b></summary>

| المزوّد | Binding | مثال نموذج | البعد الافتراضي |
|:--|:--|:--|:--|
| OpenAI | `openai` | `text-embedding-3-large` | 3072 |
| Azure OpenAI | `azure_openai` | اسم النشر | — |
| Cohere | `cohere` | `embed-v4.0` | 1024 |
| Jina | `jina` | `jina-embeddings-v3` | 1024 |
| Ollama | `ollama` | `nomic-embed-text` | 768 |
| vLLM / LM Studio | `vllm` | أي نموذج تضمين | — |
| متوافق OpenAI | `custom` | — | — |

المزوّدون المتوافقون مع OpenAI (DashScope، SiliconFlow، إلخ) يعملون عبر binding ‎`custom` أو `openai`.

</details>

<details>
<summary><b>مزوّدو البحث على الويب المدعومون</b></summary>

| المزوّد | مفتاح البيئة | ملاحظات |
|:--|:--|:--|
| Brave | `BRAVE_API_KEY` | موصى به، يوجد مستوى مجاني |
| Tavily | `TAVILY_API_KEY` | |
| Serper | `SERPER_API_KEY` | نتائج Google عبر Serper |
| Jina | `JINA_API_KEY` | |
| SearXNG | — | مستضاف ذاتيًا، بلا مفتاح API |
| DuckDuckGo | — | بلا مفتاح API |
| Perplexity | `PERPLEXITY_API_KEY` | يتطلب مفتاح API |

</details>

**3. تشغيل الخدمات**

أسرع طريقة:

```bash
python scripts/start_web.py
```

يشغّل الخادم الخلفي والواجهة ويفتح المتصفح تلقائيًا.

أو شغّل كل خدمة يدويًا في طرفيات منفصلة:

```bash
# الخادم الخلفي (FastAPI)
python -m deeptutor.api.run_server

# الواجهة (Next.js) — طرفية أخرى
cd web && npm run dev -- -p 3782
```

| الخدمة | المنفذ الافتراضي |
|:---:|:---:|
| الخادم الخلفي | `8001` |
| الواجهة | `3782` |

افتح [http://localhost:3782](http://localhost:3782).

### الخيار C — Docker

Docker يضمّ الخادم الخلفي والواجهة في حاوية واحدة؛ لا يلزم Python أو Node.js محليًا. يكفي [Docker Desktop](https://www.docker.com/products/docker-desktop/) (أو Docker Engine + Compose على Linux).

**1. متغيرات البيئة** (مطلوبة في الخيارين 2a و 2b أدناه)

```bash
git clone https://github.com/HKUDS/DeepTutor.git
cd DeepTutor
cp .env.example .env
```

حرّر `.env` واملأ الحقول المطلوبة (كما في [الخيار B](#option-b-manual)).

**2a. سحب الصورة الرسمية (موصى به)**

تُنشر الصور الرسمية على [GitHub Container Registry](https://github.com/HKUDS/DeepTutor/pkgs/container/deeptutor) مع كل إصدار لـ `linux/amd64` و`linux/arm64`.

```bash
docker compose -f docker-compose.ghcr.yml up -d
```

لتثبيت إصدار محدّد، عدّل وسم الصورة في `docker-compose.ghcr.yml`:

```yaml
image: ghcr.io/hkuds/deeptutor:1.0.0  # أو :latest
```

**2b. البناء من المصدر**

```bash
docker compose up -d
```

يبني الصورة محليًا من `Dockerfile` ويشغّل الحاوية.

**3. التحقق والإدارة**

افتح [http://localhost:3782](http://localhost:3782) عندما تصبح الحاوية healthy.

```bash
docker compose logs -f   # متابعة السجلات
docker compose down       # إيقاف وإزالة الحاوية
```

<details>
<summary><b>سحابة / خادم بعيد</b></summary>

على خادم بعيد يحتاج المتصفح إلى عنوان URL العام لواجهة الـ API الخلفية. أضف إلى `.env`:

```dotenv
# عنوان URL العام حيث يمكن الوصول إلى الخادم الخلفي
NEXT_PUBLIC_API_BASE_EXTERNAL=https://your-server.com:8001
```

سكربت تشغيل الواجهة يطبّق هذه القيمة أثناء التشغيل — لا حاجة لإعادة البناء.

</details>

<details>
<summary><b>المصادقة (النشر العام)</b></summary>

المصادقة **معطلة افتراضيًا** — لا يلزم تسجيل الدخول على localhost. للنشر متعدد المستأجرين (مساحات عمل لكل مستخدم، نماذج/قواعد معرفة/مهارات يديرها المشرف، سجل تدقيق)، انظر قسم [متعدد المستخدمين](#roadmap) أدناه.

**مستخدم واحد بدون واجهة (بدون `/register`):** إذا لم تتمكن من الوصول إلى المتصفح لإنشاء أول مسؤول، استخدم متغيرات البيئة:

```bash
python -c "from deeptutor.services.auth import hash_password; print(hash_password('yourpassword'))"
```

```dotenv
AUTH_ENABLED=true
AUTH_USERNAME=admin
AUTH_PASSWORD_HASH=<الصقِ الهاش هنا>
AUTH_SECRET=your-secret-here
```

</details>

<details>
<summary><b>PocketBase (اختياري للمصادقة والتخزين)</b></summary>

PocketBase خلفية اختيارية خفيفة تحل محل SQLite/JSON المدمج. تضيف مصادقة متوافقة مع OAuth، اشتراكات في الوقت الفعلي، ولوحة إدارة مرئية.

> ⚠️ **وضع PocketBase للمستخدم الفردي فقط حاليًا.** لا يحتوي المخطط الافتراضي على حقل `role` في `users`، ولا تُصفَّى استعلامات الجلسات حسب `user_id`. النشر متعدد المستخدمين: اتركِ `POCKETBASE_URL` فارغًا.

```bash
docker compose up -d
open http://localhost:8090/_/
pip install pocketbase
python scripts/pb_setup.py
```

```dotenv
POCKETBASE_URL=http://localhost:8090
POCKETBASE_ADMIN_EMAIL=admin@example.com
POCKETBASE_ADMIN_PASSWORD=your-admin-password
```

</details>

<details>
<summary><b>وضع التطوير (إعادة تحميل ساخنة)</b></summary>

اطبق طبقة التطوير لتركيب الشيفرة وتفعيل الإعادة الساخنة لكلا الخدمتين:

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up
```

تنعكس التغييرات في `deeptutor/` و`deeptutor_cli/` و`scripts/` و`web/` فورًا.

</details>

<details>
<summary><b>منافذ مخصّصة</b></summary>

تجاوز المنافذ الافتراضية في `.env`:

```dotenv
BACKEND_PORT=9001
FRONTEND_PORT=4000
```

ثم أعد التشغيل:

```bash
docker compose up -d     # أو docker compose -f docker-compose.ghcr.yml up -d
```

</details>

<details>
<summary><b>استمرارية البيانات</b></summary>

تُخزَّن بيانات المستخدم وقواعد المعرفة عبر مجلدات Docker مربوطة بالمضيف:

| مسار الحاوية | مسار المضيف | المحتوى |
|:---|:---|:---|
| `/app/data/user` | `./data/user` | الإعدادات، مساحة العمل، الجلسات، السجلات |
| `/app/data/memory` | `./data/memory` | الذاكرة طويلة الأمد المشتركة (`SUMMARY.md`، `PROFILE.md`) |
| `/app/data/knowledge_bases` | `./data/knowledge_bases` | المستندات المرفوعة وفهارس المتجهات |

تبقى هذه المجلدات بعد `docker compose down` وتُعاد استخدامها في `docker compose up` التالي.

</details>

<details>
<summary><b>مرجع متغيرات البيئة</b></summary>

| المتغير | مطلوب | الوصف |
|:---|:---:|:---|
| `LLM_BINDING` | **نعم** | مزوّد LLM (`openai`، `anthropic`، إلخ) |
| `LLM_MODEL` | **نعم** | اسم النموذج (مثل `gpt-4o`) |
| `LLM_API_KEY` | **نعم** | مفتاح API للـ LLM |
| `LLM_HOST` | **نعم** | عنوان URL للـ API |
| `EMBEDDING_BINDING` | **نعم** | مزوّد التضمين |
| `EMBEDDING_MODEL` | **نعم** | اسم نموذج التضمين |
| `EMBEDDING_API_KEY` | **نعم** | مفتاح API للتضمين |
| `EMBEDDING_HOST` | **نعم** | نقطة نهاية التضمين |
| `EMBEDDING_DIMENSION` | **نعم** | بُعد المتجه |
| `SEARCH_PROVIDER` | لا | البحث (`tavily`، `jina`، `serper`، `perplexity`، إلخ) |
| `SEARCH_API_KEY` | لا | مفتاح API للبحث |
| `BACKEND_PORT` | لا | منفذ الخادم الخلفي (افتراضي `8001`) |
| `FRONTEND_PORT` | لا | منفذ الواجهة (افتراضي `3782`) |
| `NEXT_PUBLIC_API_BASE_EXTERNAL` | لا | عنوان URL العام للخادم الخلفي في السحابة |
| `DISABLE_SSL_VERIFY` | لا | تعطيل التحقق من SSL (افتراضي `false`) |

</details>

### الخيار D — CLI فقط

إذا أردت CLI دون الواجهة الويب:

```bash
pip install -e ".[cli]"
```

ما زلت بحاجة لضبط مزوّد LLM. أسرع طريقة:

```bash
cp .env.example .env   # ثم عدّل .env وأدخل مفاتيح API
```

بعد الضبط:

```bash
deeptutor chat
deeptutor run chat "Explain Fourier transform"
deeptutor run deep_solve "Solve x^2 = 4"
deeptutor kb create my-kb --doc textbook.pdf
```

> الدليل الكامل: [DeepTutor CLI](#deeptutor-cli-guide).

---

<a id="explore-deeptutor"></a>
## 📖 استكشاف DeepTutor

<div align="center">
<img src="../../assets/figs/deeptutor-architecture.png" alt="هندسة DeepTutor" width="800">
</div>

### 💬 الدردشة — مساحة ذكية موحّدة

<div align="center">
<img src="../../assets/figs/dt-chat.png" alt="الدردشة" width="800">
</div>

ستة أوضاع مع **إدارة سياق موحّدة**.

| الوضع | الوظيفة |
|:---|:---|
| **دردشة** | RAG، ويب، تنفيذ كود، تفكير، عصف ذهني، أوراق. |
| **Deep Solve** | حل متعدّد الوكلاء مع اقتباسات. |
| **توليد اختبارات** | تقييم مرتبط بقاعدة المعرفة. |
| **Deep Research** | مواضيع فرعية، وكلاء متوازيون، تقرير موثّق. |
| **Math Animator** | Manim. |
| **Visualize** | SVG أو Chart.js أو Mermaid أو HTML مستقل من وصف طبيعي. |

الأدوات **منفصلة عن سير العمل** — تختار ما تفعّله.

### ✍️ Co-Writer — مساحة كتابة متعددة المستندات مع الذكاء

<div align="center">
<img src="../../assets/figs/dt-cowriter.png" alt="Co-Writer" width="800">
</div>

أنشئ عدة مستندات، كلّها محفوظة — ليس مسودّة واحدة: Markdown كامل والذكاء شريك. **إعادة صياغة**، **توسيع**، **اختصار**؛ تراجع؛ دفاتر.

### 📖 Book Engine — «كتب حية» تفاعلية

<div align="center">
<img src="../../assets/figs/dt-book-0.png" alt="المكتبة" width="270"><img src="../../assets/figs/dt-book-1.png" alt="القارئ" width="270"><img src="../../assets/figs/dt-book-2.png" alt="الرسوم" width="270">
</div>

حدّد موضوعًا ووجّه قاعدة المعرفة: ينتج DeepTutor كتابًا منظّمًا وتفاعليًا — وثيقة حيّة للقراءة والاختبار الذاتي والنقاش في السياق.

خلف الكواليس، خط أنابيب متعدّد الوكلاء يقترح المخطط، يسترجع المصادر، يدمج شجرة الفصول، يخطّط الصفحات ويجمّع الكتل. أنت تتحكّم: مراجعة المقترح، إعادة ترتيب الفصول، دردشة بجانب أي صفحة.

13 نوع كتلة — نص، تنبيه، اختبار، بطاقات، شفرة، رسم، تعميق، رسوم متحركة، تفاعلي، خط زمني، رسم مفاهيم، قسم، ملاحظة مستخدم — كلّها بمكوّنات تفاعلية. خط زمني للتقدّم لحظيًا.

### 📚 إدارة المعرفة

<div align="center">
<img src="../../assets/figs/dt-knowledge.png" alt="المعرفة" width="800">
</div>

مجموعات مستندات وملاحظات وشخصيات تدريس.

- **قواعد المعرفة** — PDF، TXT، MD.  
- **دفاتر** — من Chat أو Co-Writer أو Book أو Deep Research، بألوان.
- **بنك الأسئلة** — مراجعة الاختبارات؛ مفضّلات و@-إشارات في الدردشة لتحليل الأداء السابق.
- **Skills** — شخصيات عبر `SKILL.md`: اسم، وصف، محفّزات اختيارية، Markdown يُحقَن في مطالبة النظام للدردشة عند التفعيل.

### 🧠 الذاكرة

<div align="center">
<img src="../../assets/figs/dt-memory.png" alt="الذاكرة" width="800">
</div>

- **ملخّص** — التقدّم.  
- **ملف** — التفضيلات والمستوى والأهداف. مشترك مع TutorBots.

---

<a id="tutorbot"></a>
### 🦞 TutorBot — مدرّسو ذكاء اصطناعي دائمون ومستقلّون

<div align="center">
<img src="../../assets/figs/tutorbot-architecture.png" alt="هندسة TutorBot" width="800">
</div>

وكيل **متعدّد النسخ** دائم على [nanobot](https://github.com/HKUDS/nanobot): حلقة ومساحة عمل وذاكرة وشخصية مستقلة.

<div align="center">
<img src="../../assets/figs/tb.png" alt="TutorBot" width="800">
</div>

- **قوالب Soul** — الشخصية والفلسفة التعليمية.  
- **مساحة عمل مستقلة** — ذاكرة وجلسات ومهارات؛ طبقة معرفة مشتركة.  
- **Heartbeat استباقي** — تذكيرات ومهام مجدولة.  
- **أدوات كاملة** — RAG، كود، ويب، أوراق، تفكير، عصف ذهني.  
- **تعلّم المهارات** — ملفات skill.  
- **قنوات متعددة** — Telegram، Discord، Slack، Feishu، WeCom، DingTalk، بريد، إلخ.  
- **فرق ووكلاء فرعيون**.

```bash
deeptutor bot create math-tutor --persona "Socratic math teacher who uses probing questions"
deeptutor bot create writing-coach --persona "Patient, detail-oriented writing mentor"
deeptutor bot list
```

---

<a id="deeptutor-cli-guide"></a>
### ⌨️ DeepTutor CLI — واجهة أصلية للوكلاء

<div align="center">
<img src="../../assets/figs/cli-architecture.png" alt="CLI" width="800">
</div>

بدون متصفح: القدرات وقواعد المعرفة والجلسات والذاكرة وTutorBot. Rich + JSON. [`SKILL.md`](../../SKILL.md).

```bash
deeptutor run chat "Explain the Fourier transform" -t rag --kb textbook
deeptutor run deep_solve "Prove that √2 is irrational" -t reason
deeptutor run deep_question "Linear algebra" --config num_questions=5
deeptutor run deep_research "Attention mechanisms in transformers"
deeptutor run visualize "Draw the architecture of a transformer"
```

```bash
deeptutor chat --capability deep_solve --kb my-kb
# داخل REPL: /cap و /tool و /kb و /history و /notebook و /config للتبديل فورًا
```

```bash
deeptutor kb create my-kb --doc textbook.pdf
deeptutor kb add my-kb --docs-dir ./papers/
deeptutor kb search my-kb "gradient descent"
deeptutor kb set-default my-kb
```

```bash
deeptutor run chat "Summarize chapter 3" -f rich
deeptutor run chat "Summarize chapter 3" -f json
```

```bash
deeptutor session list
deeptutor session open <id>
```

<details>
<summary><b>مرجع أوامر CLI الكامل</b></summary>

**المستوى الأعلى**

| الأمر | الوصف |
|:---|:---|
| `deeptutor run <capability> <message>` | تشغيل قدرة في دور واحد (`chat`، `deep_solve`، `deep_question`، `deep_research`، `math_animator`، `visualize`) |
| `deeptutor chat` | REPL تفاعلي مع `--capability` و`--tool` و`--kb` و`--language` وغيرها |
| `deeptutor serve` | تشغيل خادم API الخاص بـ DeepTutor |

**`deeptutor bot`**

| الأمر | الوصف |
|:---|:---|
| `deeptutor bot list` | عرض جميع مثيلات TutorBot |
| `deeptutor bot create <id>` | إنشاء وتشغيل بوت (`--name`، `--persona`، `--model`) |
| `deeptutor bot start <id>` | تشغيل بوت |
| `deeptutor bot stop <id>` | إيقاف بوت |

**`deeptutor kb`**

| الأمر | الوصف |
|:---|:---|
| `deeptutor kb list` | قائمة قواعد المعرفة |
| `deeptutor kb info <name>` | تفاصيل قاعدة |
| `deeptutor kb create <name>` | إنشاء من مستندات (`--doc`، `--docs-dir`) |
| `deeptutor kb add <name>` | إضافة مستندات |
| `deeptutor kb search <name> <query>` | بحث في القاعدة |
| `deeptutor kb set-default <name>` | تعيين KB افتراضية |
| `deeptutor kb delete <name>` | حذف (`--force`) |

**`deeptutor memory`**

| الأمر | الوصف |
|:---|:---|
| `deeptutor memory show [file]` | عرض (`summary`، `profile`، `all`) |
| `deeptutor memory clear [file]` | مسح (`--force`) |

**`deeptutor session`**

| الأمر | الوصف |
|:---|:---|
| `deeptutor session list` | قائمة الجلسات (`--limit`) |
| `deeptutor session show <id>` | رسائل الجلسة |
| `deeptutor session open <id>` | استئناف في REPL |
| `deeptutor session rename <id>` | إعادة تسمية (`--title`) |
| `deeptutor session delete <id>` | حذف |

**`deeptutor notebook`**

| الأمر | الوصف |
|:---|:---|
| `deeptutor notebook list` | قائمة الدفاتر |
| `deeptutor notebook create <name>` | إنشاء (`--description`) |
| `deeptutor notebook show <id>` | عرض السجلات |
| `deeptutor notebook add-md <id> <path>` | استيراد Markdown |
| `deeptutor notebook replace-md <id> <rec> <path>` | استبدال سجل |
| `deeptutor notebook remove-record <id> <rec>` | إزالة سجل |

**`deeptutor book`**

| الأمر | الوصف |
|:---|:---|
| `deeptutor book list` | قائمة كل الكتب في مساحة العمل |
| `deeptutor book health <book_id>` | انحراف قاعدة المعرفة وصحة الكتاب |
| `deeptutor book refresh-fingerprints <book_id>` | تحديث بصمات KB ومسح الصفحات القديمة |

**`deeptutor config` / `plugin` / `provider`**

| الأمر | الوصف |
|:---|:---|
| `deeptutor config show` | ملخص الإعدادات |
| `deeptutor plugin list` | الأدوات والقدرات المسجّلة |
| `deeptutor plugin info <name>` | تفاصيل أداة أو قدرة |
| `deeptutor provider login <provider>` | مصادقة المزوّد (OAuth مع `openai-codex`؛ `github-copilot` يتحقق من جلسة Copilot قائمة) |

</details>

---

<a id="multi-user"></a>
### 👥 متعدد المستخدمين — نشر مشترك مع مساحات عمل لكل مستخدم

<div align="center">
<img src="../../assets/figs/dt-multi-user.png" alt="متعدد المستخدمين" width="800">
</div>

بتفعيل المصادقة، يتحوّل DeepTutor إلى نشر متعدد المستأجرين مع **مساحات عمل معزولة لكل مستخدم** و**موارد يديرها المشرف**. أول مستخدم يسجّل يصبح مشرفًا يضبط النماذج ومفاتيح API وقواعد المعرفة. الحسابات التالية يُنشئها المشرف (بالدعوة)، ولكل مستخدم تاريخ دردشة وذاكرة ودفاتر وقواعد معرفة خاصة به.

**بدء سريع (5 خطوات):**

```bash
# 1. فعّل المصادقة في .env بجذر المشروع
echo 'AUTH_ENABLED=true' >> .env
# اختياري — مفتاح توقيع JWT. يُولَّد تلقائيًا إذا تُرك فارغًا
echo 'AUTH_SECRET=<الصق 64+ حرفًا عشوائيًا>' >> .env

# 2. أعد تشغيل Web stack
python scripts/start_web.py

# 3. افتح http://localhost:3782/register وأنشئ أول حساب
#    أول تسجيل وحيد عام؛ يصبح ذلك المستخدم مشرفًا
#    ويُغلق endpoint /register تلقائيًا بعدها

# 4. بصفتك مشرفًا، انتقل إلى /admin/users → "إضافة مستخدم"

# 5. لكل مستخدم، انقر أيقونة التمرير → خصِّص نماذج LLM وقواعد المعرفة
#    والمهارات → احفظ. يمكن للمستخدم تسجيل الدخول والبدء
```

**ما يراه المشرف:**

- **صفحة الإعدادات الكاملة** في `/settings` — LLM / التضمين / البحث، المفاتيح، كتالوج النماذج.
- **إدارة المستخدمين** في `/admin/users` — إنشاء الحسابات ورفعها وخفضها وحذفها.
- **محرّر المنح** — تحديد النماذج وقواعد المعرفة والمهارات لكل مستخدم؛ المنح تحتوي على **معرفات منطقية فقط**، ولا تُشارَك مفاتيح API.
- **مسار تدقيق** — كل تغيير منح وصول إلى `multi-user/_system/audit/usage.jsonl`.

**ما يحصل عليه المستخدم العادي:**

- **مساحة عمل معزولة** ضمن `multi-user/<uid>/` — `chat_history.db` وذاكرة ودفاتر وقواعد معرفة شخصية.
- **وصول للقراءة فقط** لقواعد المعرفة والمهارات المعيّنة من المشرف، مع شارة "معيّن من المشرف".
- **صفحة إعدادات مقلَّصة** — سمة ولغة وملخص النماذج الممنوحة فقط؛ لا تُعاد مفاتيح API لطلبات غير المشرفين.
- **LLM محدَّد النطاق** — أدوار الدردشة تمر عبر النموذج الممنوح؛ إذا لم يُمنح، يُرفض الطلب مسبقًا.

**تخطيط مساحة العمل:**

```
multi-user/
├── _system/
│   ├── auth/users.json          # بيانات اعتماد مجزأة وأدوار
│   ├── auth/auth_secret         # مفتاح توقيع JWT (مُولَّد تلقائيًا)
│   ├── grants/<uid>.json        # منح الموارد لكل مستخدم
│   └── audit/usage.jsonl        # مسار التدقيق
└── <uid>/
    ├── user/
    │   ├── chat_history.db
    │   ├── settings/interface.json
    │   └── workspace/{chat,co-writer,book,...}
    ├── memory/{SUMMARY.md,PROFILE.md}
    └── knowledge_bases/...
```

**مرجع الإعداد:**

| المتغير | مطلوب | الوصف |
|:---|:---|:---|
| `AUTH_ENABLED` | نعم | `true` لتفعيل المصادقة متعددة المستخدمين. افتراضي `false`. |
| `AUTH_SECRET` | يُوصى به | مفتاح توقيع JWT؛ فارغ: يُكتب في `multi-user/_system/auth/auth_secret`. |
| `AUTH_TOKEN_EXPIRE_HOURS` | لا | مدة JWT؛ افتراضي 24 ساعة. |
| `AUTH_USERNAME` / `AUTH_PASSWORD_HASH` | لا | بيانات اعتماد احتياطية للمستخدم الفردي. اتركها فارغة في وضع متعدد المستخدمين. |
| `NEXT_PUBLIC_AUTH_ENABLED` | تلقائي | يعكسه `start_web.py` من `AUTH_ENABLED` لإعادة توجيه Next.js إلى `/login`. |

> ⚠️ **وضع PocketBase (`POCKETBASE_URL` مضبوط) للمستخدم الفردي فقط** — لا حقل `role`، ولا تصفية حسب `user_id`. النشر متعدد المستخدمين: اتركِ `POCKETBASE_URL` فارغًا.

> ⚠️ **يُوصى بعملية واحدة.** ترقية أول مشرف محمية بـ `threading.Lock`. البيئات متعددة العمال: أنشئ أول مشرف دون اتصال أو استخدم مخزن مستخدمين خارجيًا.

<a id="roadmap"></a>
## 🗺️ خارطة الطريق

| الحالة | مرحلة |
|:---:|:---|
| 🎯 | **المصادقة وتسجيل الدخول** — صفحة دخول اختيارية للنشر العام مع دعم متعدد المستخدمين |
| 🎯 | **السمات والمظهر** — سمات متنوعة وتخصيص واجهة المستخدم |
| 🎯 | **تحسين التفاعل** — تحسين تصميم الأيقونات وتفاصيل التفاعل |
| 🔜 | **ذاكرة أفضل** — دمج إدارة ذاكرة أقوى |
| 🔜 | **دمج LightRAG** — دمج [LightRAG](https://github.com/HKUDS/LightRAG) كمحرك متقدم لقواعد المعرفة |
| 🔜 | **موقع التوثيق** — توثيق كامل مع أدلة ومرجع API ودروس |

> إذا كان DeepTutor مفيدًا لك، [امنحنا نجمة](https://github.com/HKUDS/DeepTutor/stargazers) — يدعمنا ذلك للاستمرار!

---

<a id="community"></a>
## 🌐 المجتمع والنظام البيئي

| المشروع | الدور |
|:---|:---|
| [**nanobot**](https://github.com/HKUDS/nanobot) | محرّك TutorBot |
| [**LlamaIndex**](https://github.com/run-llama/llama_index) | RAG |
| [**ManimCat**](https://github.com/Wing900/ManimCat) | Math Animator |

| [⚡ LightRAG](https://github.com/HKUDS/LightRAG) | [🤖 AutoAgent](https://github.com/HKUDS/AutoAgent) | [🔬 AI-Researcher](https://github.com/HKUDS/AI-Researcher) | [🧬 nanobot](https://github.com/HKUDS/nanobot) |
|:---:|:---:|:---:|:---:|
| RAG سريع | وكلاء بلا كود | بحث آلي | وكيل خفيف جدًا |

## 🤝 المساهمة

<div align="center">

نأمل أن يكون DeepTutor هدية للمجتمع. 🎁

<a href="https://github.com/HKUDS/DeepTutor/graphs/contributors">
  <img src="https://contrib.rocks/image?repo=HKUDS/DeepTutor&max=999" alt="Contributors" />
</a>
</div>

راجع [CONTRIBUTING.md](../../CONTRIBUTING.md).

## ⭐ تاريخ النجوم

<div align="center">
<a href="https://www.star-history.com/#HKUDS/DeepTutor&type=timeline&legend=top-left">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/svg?repos=HKUDS/DeepTutor&type=timeline&theme=dark&legend=top-left" />
    <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/svg?repos=HKUDS/DeepTutor&type=timeline&legend=top-left" />
    <img alt="Star History" src="https://api.star-history.com/svg?repos=HKUDS/DeepTutor&type=timeline&legend=top-left" />
  </picture>
</a>
</div>

<p align="center">
 <a href="https://www.star-history.com/hkuds/deeptutor">
  <picture>
   <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/badge?repo=HKUDS/DeepTutor&theme=dark" />
   <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/badge?repo=HKUDS/DeepTutor" />
   <img alt="Star History Rank" src="https://api.star-history.com/badge?repo=HKUDS/DeepTutor" />
  </picture>
 </a>
</p>

<div align="center">

**[Data Intelligence Lab @ HKU](https://github.com/HKUDS)**

[⭐ Star](https://github.com/HKUDS/DeepTutor/stargazers) · [🐛 Issues](https://github.com/HKUDS/DeepTutor/issues) · [💬 Discussions](https://github.com/HKUDS/DeepTutor/discussions)

---

[Apache License 2.0](../../LICENSE)

<p>
  <img src="https://visitor-badge.laobi.icu/badge?page_id=HKUDS.DeepTutor&style=for-the-badge&color=00d4ff" alt="Views">
</p>

</div>
