<div align="center">

<img src="../../assets/logo-ver2.png" alt="DeepTutor" width="140" style="border-radius: 15px;">

# DeepTutor: نحو تعليم شخصي قائم على الوكلاء

[![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-3776AB?style=flat-square&logo=python&logoColor=white)](https://www.python.org/downloads/)
[![Next.js 16](https://img.shields.io/badge/Next.js-16-000000?style=flat-square&logo=next.js&logoColor=white)](https://nextjs.org/)
[![License](https://img.shields.io/badge/License-Apache_2.0-blue?style=flat-square)](../../LICENSE)
[![GitHub release](https://img.shields.io/github/v/release/HKUDS/DeepTutor?style=flat-square&color=brightgreen)](https://github.com/HKUDS/DeepTutor/releases)
[![GitHub last commit](https://img.shields.io/github/last-commit/HKUDS/DeepTutor?style=flat-square)](https://github.com/HKUDS/DeepTutor/commits)

[![Discord](https://img.shields.io/badge/Discord-Community-5865F2?style=flat-square&logo=discord&logoColor=white)](https://discord.gg/eRsjPgMU4t)
[![Feishu](https://img.shields.io/badge/Feishu-Group-00D4AA?style=flat-square&logo=feishu&logoColor=white)](../../Communication.md)
[![WeChat](https://img.shields.io/badge/WeChat-Group-07C160?style=flat-square&logo=wechat&logoColor=white)](https://github.com/HKUDS/DeepTutor/issues/78)

[الميزات](#key-features) · [البدء](#get-started) · [استكشاف](#explore-deeptutor) · [TutorBot](#tutorbot) · [CLI](#deeptutor-cli-guide) · [المجتمع](#community)

[🇬🇧 English](../../README.md) · [🇨🇳 中文](README_CN.md) · [🇯🇵 日本語](README_JA.md) · [🇪🇸 Español](README_ES.md) · [🇫🇷 Français](README_FR.md) · [🇷🇺 Русский](README_RU.md) · [🇮🇳 हिन्दी](README_HI.md) · [🇵🇹 Português](README_PT.md)

</div>

---
### 📰 الأخبار

> **[2026.3.24]** DeepTutor v1.0.0 ✨ — تطور أصلي للوكلاء: إعادة هيكلة خفيفة، TutorBot، أوضاع مرنة بموجب Apache-2.0.

> **[2026.2.6]** 🚀 10k نجوم في 39 يومًا — شكرًا للمجتمع!

> **[2026.1.1]** سنة جديدة سعيدة! انضم إلى [Discord](https://discord.gg/eRsjPgMU4t) أو [WeChat](https://github.com/HKUDS/DeepTutor/issues/78) أو [Discussions](https://github.com/HKUDS/DeepTutor/discussions).

> **[2025.12.29]** إطلاق DeepTutor رسميًا.

### 📦 الإصدارات

> **[2026.3.24]** [v1.0.0](https://github.com/HKUDS/DeepTutor/releases/tag/v1.0.0) — إعادة هيكلة أصلية للوكلاء، تكامل مرن للأدوات، مداخل CLI وSDK، TutorBot بمحرك nanobot، Co-Writer، تعليم موجّه، ذاكرة دائمة.

<details>
<summary><b>إصدارات سابقة</b></summary>

> **[2026.1.23]** [v0.6.0](https://github.com/HKUDS/DeepTutor/releases/tag/v0.6.0) — استمرارية الجلسات، رفع تدريجي، RAG مرن، تعريب صيني كامل.

> **[2026.1.18]** [v0.5.2](https://github.com/HKUDS/DeepTutor/releases/tag/v0.5.2) — Docling، سجلات، إصلاحات.

> **[2026.1.15]** [v0.5.0](https://github.com/HKUDS/DeepTutor/releases/tag/v0.5.0) — إعداد موحّد، RAG لكل قاعدة معرفة، توليد أسئلة، شريط جانبي.

> **[2026.1.9]** [v0.4.0](https://github.com/HKUDS/DeepTutor/releases/tag/v0.4.0) — مزوّدو LLM/تضمينات متعددون، صفحة رئيسية جديدة، فصل RAG، متغيرات البيئة.

> **[2026.1.5]** [v0.3.0](https://github.com/HKUDS/DeepTutor/releases/tag/v0.3.0) — PromptManager، CI/CD، صور GHCR.

> **[2026.1.2]** [v0.2.0](https://github.com/HKUDS/DeepTutor/releases/tag/v0.2.0) — Docker، Next.js 16 وReact 19، WebSocket، ثغرات.

</details>

<a id="key-features"></a>
## ✨ أبرز الميزات

- **مساحة دردشة موحّدة** — خمسة أوضاع في سلسلة واحدة: دردشة، Deep Solve، اختبارات، Deep Research، Math Animator تتشارك السياق.
- **TutorBots شخصية** — ليست روبوتات دردشة: مدرّسون مستقلّون بمساحة عمل وذاكرة وشخصية ومهارات. يعمل بـ [nanobot](https://github.com/HKUDS/nanobot).
- **AI Co-Writer** — محرّر Markdown والذكاء الاصطناعي شريك: إعادة صياغة، توسيع، اختصار مع قاعدة المعرفة والويب.
- **تعليم موجّه** — تحويل موادك إلى رحلات تعلّم بصرية متدرّجة.
- **مركز المعرفة** — PDF وMarkdown ونص لقواعد جاهزة لـ RAG؛ دفاتر ملوّنة.
- **ذاكرة دائمة** — ملخّص التقدّم وملف المتعلّم؛ مشتركة مع TutorBots.
- **CLI أصلي للوكلاء** — القدرات وقواعد المعرفة والجلسات وTutorBot بأمر واحد؛ Rich وJSON. [`SKILL.md`](../../SKILL.md).

---

<a id="get-started"></a>
## 🚀 البدء

### الخيار A — جولة الإعداد (موصى به)

**سكربت تفاعلي واحد** للتبعيات والبيئة والاختبار والتشغيل.

```bash
git clone https://github.com/HKUDS/DeepTutor.git
cd DeepTutor

conda create -n deeptutor python=3.11 && conda activate deeptutor
# أو: python -m venv .venv && source .venv/bin/activate

python scripts/start_tour.py
```

- **وضع الويب** — ملف تعريف، pip + npm، خادم مؤقت، صفحة **الإعدادات**، 4 خطوات.
- **وضع CLI** — كل شيء في الطرفية.

افتح [http://localhost:3782](http://localhost:3782).

<a id="option-b-manual"></a>
### الخيار B — تثبيت يدوي محلي

```bash
git clone https://github.com/HKUDS/DeepTutor.git
cd DeepTutor

conda create -n deeptutor python=3.11 && conda activate deeptutor
pip install -e ".[server]"

cd web && npm install && cd ..
```

```bash
cp .env.example .env
```

```dotenv
LLM_BINDING=openai
LLM_MODEL=gpt-4o-mini
LLM_API_KEY=sk-xxx
LLM_HOST=https://api.openai.com/v1

EMBEDDING_BINDING=openai
EMBEDDING_MODEL=text-embedding-3-large
EMBEDDING_API_KEY=sk-xxx
EMBEDDING_HOST=https://api.openai.com/v1
EMBEDDING_DIMENSION=3072
```

```bash
python -m deeptutor.api.run_server
cd web && npm run dev -- -p 3782
```

| الخدمة | المنفذ |
|:---:|:---:|
| Backend | `8001` |
| Frontend | `3782` |

### الخيار C — Docker

```bash
git clone https://github.com/HKUDS/DeepTutor.git
cd DeepTutor
cp .env.example .env
```

كما في [الخيار B](#option-b-manual).

**2a. صورة رسمية** — [GHCR](https://github.com/HKUDS/DeepTutor/pkgs/container/deeptutor)

```bash
docker compose -f docker-compose.ghcr.yml up -d
```

**2b. بناء من المصدر** — `docker compose up -d`

**3.** [http://localhost:3782](http://localhost:3782)

```bash
docker compose logs -f
docker compose down
```

<details>
<summary><b>سحابة / خادم بعيد</b></summary>

```dotenv
NEXT_PUBLIC_API_BASE_EXTERNAL=https://your-server.com:8001
```

</details>

<details>
<summary><b>وضع التطوير (إعادة تحميل)</b></summary>

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up
```

</details>

<details>
<summary><b>منافذ مخصّصة</b></summary>

```dotenv
BACKEND_PORT=9001
FRONTEND_PORT=4000
```

</details>

<details>
<summary><b>استمرارية البيانات</b></summary>

| مسار الحاوية | المضيف | المحتوى |
|:---|:---|:---|
| `/app/data/user` | `./data/user` | الإعدادات، الذاكرة، مساحة العمل، الجلسات، السجلات |
| `/app/data/knowledge_bases` | `./data/knowledge_bases` | المستندات والمتجهات |

</details>

<details>
<summary><b>متغيرات البيئة</b></summary>

| المتغير | مطلوب | الوصف |
|:---|:---:|:---|
| `LLM_BINDING` | **نعم** | مزوّد LLM |
| `LLM_MODEL` | **نعم** | النموذج |
| `LLM_API_KEY` | **نعم** | المفتاح |
| `LLM_HOST` | **نعم** | الرابط |
| `EMBEDDING_BINDING` | **نعم** | التضمين |
| `EMBEDDING_MODEL` | **نعم** | النموذج |
| `EMBEDDING_API_KEY` | **نعم** | المفتاح |
| `EMBEDDING_HOST` | **نعم** | الرابط |
| `EMBEDDING_DIMENSION` | **نعم** | البعد |
| `SEARCH_PROVIDER` | لا | البحث |
| `SEARCH_API_KEY` | لا | المفتاح |
| `BACKEND_PORT` | لا | الافتراضي `8001` |
| `FRONTEND_PORT` | لا | الافتراضي `3782` |
| `NEXT_PUBLIC_API_BASE_EXTERNAL` | لا | URL العام |
| `DISABLE_SSL_VERIFY` | لا | الافتراضي `false` |

</details>

### الخيار D — CLI فقط

```bash
pip install -e ".[cli]"
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

خمسة أوضاع مع **إدارة سياق موحّدة**.

| الوضع | الوظيفة |
|:---|:---|
| **دردشة** | RAG، ويب، تنفيذ كود، تفكير، عصف ذهني، أوراق. |
| **Deep Solve** | حل متعدّد الوكلاء مع اقتباسات. |
| **توليد اختبارات** | تقييم مرتبط بقاعدة المعرفة. |
| **Deep Research** | مواضيع فرعية، وكلاء متوازيون، تقرير موثّق. |
| **Math Animator** | Manim. |

الأدوات **منفصلة عن سير العمل** — تختار ما تفعّله.

### ✍️ Co-Writer — الذكاء في المحرّر

<div align="center">
<img src="../../assets/figs/dt-cowriter.png" alt="Co-Writer" width="800">
</div>

**إعادة صياغة**، **توسيع**، **اختصار**؛ تراجع؛ دفاتر.

### 🎓 تعليم موجّه

<div align="center">
<img src="../../assets/figs/dt-guide.png" alt="تعليم موجّه" width="800">
</div>

1. خطة (3–5 نقاط).  
2. صفحات تفاعلية.  
3. أسئلة وأجوبة سياقية.  
4. ملخّص.

### 📚 إدارة المعرفة

<div align="center">
<img src="../../assets/figs/dt-knowledge.png" alt="المعرفة" width="800">
</div>

- **قواعد المعرفة** — PDF، TXT، MD.  
- **دفاتر** — جلسات وألوان.

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
```

```bash
deeptutor chat --capability deep_solve --kb my-kb
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

| الأمر | الوصف |
|:---|:---|
| `deeptutor run <capability> <message>` | جولة واحدة |
| `deeptutor chat` | REPL |
| `deeptutor serve` | خادم API |

**bot**، **kb**، **memory**، **session**، **notebook**، **config / plugin / provider** — كما في README الإنجليزي.

</details>

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

<div align="center">

**[Data Intelligence Lab @ HKU](https://github.com/HKUDS)**

[⭐ Star](https://github.com/HKUDS/DeepTutor/stargazers) · [🐛 Issues](https://github.com/HKUDS/DeepTutor/issues) · [💬 Discussions](https://github.com/HKUDS/DeepTutor/discussions)

---

[Apache License 2.0](../../LICENSE)

<p>
  <img src="https://visitor-badge.laobi.icu/badge?page_id=HKUDS.DeepTutor&style=for-the-badge&color=00d4ff" alt="Views">
</p>

</div>
