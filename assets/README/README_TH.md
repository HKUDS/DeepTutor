<div align="center">

<img src="../../assets/logo-ver2.png" alt="DeepTutor" width="140" style="border-radius: 15px;">

# DeepTutor: ผู้ช่วยติวส่วนบุคคลแบบ Agent-Native

<a href="https://trendshift.io/repositories/17099" target="_blank"><img src="https://trendshift.io/api/badge/repositories/17099" alt="HKUDS%2FDeepTutor | Trendshift" style="width: 250px; height: 55px;" width="250" height="55"/></a>

[![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-3776AB?style=flat-square&logo=python&logoColor=white)](https://www.python.org/downloads/)
[![Next.js 16](https://img.shields.io/badge/Next.js-16-000000?style=flat-square&logo=next.js&logoColor=white)](https://nextjs.org/)
[![License](https://img.shields.io/badge/License-Apache_2.0-blue?style=flat-square)](../../LICENSE)
[![GitHub release](https://img.shields.io/github/v/release/HKUDS/DeepTutor?style=flat-square&color=brightgreen)](https://github.com/HKUDS/DeepTutor/releases)
[![arXiv](https://img.shields.io/badge/arXiv-2604.26962-b31b1b?style=flat-square&logo=arxiv&logoColor=white)](https://arxiv.org/abs/2604.26962)

[![Discord](https://img.shields.io/badge/Discord-Community-5865F2?style=flat-square&logo=discord&logoColor=white)](https://discord.gg/eRsjPgMU4t)
[![Feishu](https://img.shields.io/badge/Feishu-Group-00D4AA?style=flat-square&logo=feishu&logoColor=white)](../../Communication.md)
[![WeChat](https://img.shields.io/badge/WeChat-Group-07C160?style=flat-square&logo=wechat&logoColor=white)](https://github.com/HKUDS/DeepTutor/issues/78)

[คุณสมบัติเด่น](#-คุณสมบัติเด่น) · [เริ่มต้นใช้งาน](#-เริ่มต้นใช้งาน) · [สำรวจความสามารถ](#-สำรวจ-deeptutor) · [TutorBot](#-tutorbot--ติวเตอร์-ai-แบบถาวรและอัตโนมัติ) · [CLI](#%EF%B8%8F-deeptutor-cli--อินเทอร์เฟซแบบ-agent-native) · [ชุมชน](#-ชุมชนและระบบนิเวศ)

[🇺🇸 English](../../README.md) · [🇨🇳 中文](README_CN.md) · [🇯🇵 日本語](README_JA.md) · [🇪🇸 Español](README_ES.md) · [🇫🇷 Français](README_FR.md) · [🇸🇦 العربية](README_AR.md) · [🇷🇺 Русский](README_RU.md) · [🇮🇳 हिन्दी](README_HI.md) · [🇵🇹 Português](README_PT.md) · [🇹🇭 ภาษาไทย](README_TH.md) · 🇵🇱 [Polski](README_PL.md)

</div>

---

> 🤝 **ยินดีรับทุกรูปแบบการมีส่วนร่วม!** ดู [คู่มือการมีส่วนร่วม](../../CONTRIBUTING.md) สำหรับกลยุทธ์สาขา มาตรฐานโค้ด และจุดเริ่มต้น

### 📦 ประวัติการเผยแพร่

> **[2026.5.9]** [v1.3.9](https://github.com/HKUDS/DeepTutor/releases/tag/v1.3.9) — TutorBot รองรับ Zulip และ NVIDIA NIM, routing ของ thinking-model ปลอดภัยขึ้น, `deeptutor start`, tooltip ใน sidebar, และ session-store parity

> **[2026.5.8]** [v1.3.8](https://github.com/HKUDS/DeepTutor/releases/tag/v1.3.8) — deployment แบบ multi-user ที่เปิดได้ตามต้องการ พร้อม workspace แยกผู้ใช้, admin grants, auth routes, และ scoped runtime access

> **[2026.5.4]** [v1.3.7](https://github.com/HKUDS/DeepTutor/releases/tag/v1.3.7) — แก้ไข thinking-model/provider, แสดงประวัติ Knowledge index, และ Co-Writer clear/template editing ปลอดภัยขึ้น

> **[2026.5.3]** [v1.3.6](https://github.com/HKUDS/DeepTutor/releases/tag/v1.3.6) — เลือกโมเดลจากคาตาล็อกสำหรับแชตและ TutorBot, RAG re-indexing ปลอดภัยขึ้น, แก้ token-limit ของ OpenAI Responses, และตรวจสอบ Skills editor

> **[2026.5.2]** [v1.3.5](https://github.com/HKUDS/DeepTutor/releases/tag/v1.3.5) — ตั้งค่าการเปิดใช้งานในเครื่องราบรื่นขึ้น, RAG queries ปลอดภัยขึ้น, local embedding auth ชัดเจนขึ้น, และปรับแต่ง dark-mode ของ Settings

> **[2026.5.1]** [v1.3.4](https://github.com/HKUDS/DeepTutor/releases/tag/v1.3.4) — Chat persistence บนหน้าหนังสือและ rebuild flows, อ้างอิงจากแชตไปหนังสือ, จัดการภาษา/การให้เหตุผลแข็งแกร่งขึ้น, เสริมความแข็งแกร่งการดึงเอกสาร RAG

> **[2026.4.30]** [v1.3.3](https://github.com/HKUDS/DeepTutor/releases/tag/v1.3.3) — รองรับ embedding NVIDIA NIM และ Gemini, Space context รวมสำหรับประวัติแชต / สกิล / หน่วยความจำ, snapshot ของเซสชัน, ความทนทานของการทำดัชนี RAG ใหม่

> **[2026.4.29]** [v1.3.2](https://github.com/HKUDS/DeepTutor/releases/tag/v1.3.2) — URL ปลายทาง embedding โปร่งใส, ความทนทาน re-index RAG เมื่อเวกเตอร์ที่ persist ไม่ถูกต้อง, ทำความสะอาดหน่วยความจำสำหรับเอาต์พุตโมเดล thinking, แก้รันไทม์ Deep Solve

> **[2026.4.28]** [v1.3.1](https://github.com/HKUDS/DeepTutor/releases/tag/v1.3.1) — เสถียรภาพ: RAG routing ปลอดภัยขึ้นและตรวจสอบ embedding, Docker persistence, อินพุตปลอดภัยกับ IME, ความทนทาน Windows/GBK

> **[2026.4.27]** [v1.3.0](https://github.com/HKUDS/DeepTutor/releases/tag/v1.3.0) — ดัชนี KB แบบมีเวอร์ชันพร้อมเวิร์กโฟลว์ re-index, รีบิลด์ Knowledge workspace, embedding auto-discovery กับอะแดปเตอร์ใหม่, Space hub

> **[2026.4.25]** [v1.2.5](https://github.com/HKUDS/DeepTutor/releases/tag/v1.2.5) — แนบไฟล์ในแชตถาวรพร้อมลิ้นชักพรีวิว, pipeline ความสามารถที่รับรู้แนบไฟล์, ส่งออก Markdown ของ TutorBot

> **[2026.4.25]** [v1.2.4](https://github.com/HKUDS/DeepTutor/releases/tag/v1.2.4) — แนบข้อความ / โค้ด / SVG, Setup Tour คำสั่งเดียว, ส่งออกแชต Markdown, UI จัดการ KB แบบกะทัดรัด

<details>
<summary><b>รุ่นที่ผ่านมา (มากกว่า 2 สัปดาห์ที่แล้ว)</b></summary>

> **[2026.4.24]** [v1.2.3](https://github.com/HKUDS/DeepTutor/releases/tag/v1.2.3) — แนบเอกสาร (PDF/DOCX/XLSX/PPTX), แสดงบล็อกการคิดของโมเดลให้เหตุผล, ตัวแก้เทมเพลต Soul, บันทึก Co-Writer ลงสมุด

> **[2026.4.22]** [v1.2.2](https://github.com/HKUDS/DeepTutor/releases/tag/v1.2.2) — ระบบ Skills ที่ผู้ใช้สร้าง, ปรับประสิทธิ์อินพุตแชต, TutorBot สตาร์ทอัตโนมัติ, UI ห้องสมุดหนังสือ, โหมดเต็มจอของการแสดงผล

> **[2026.4.21]** [v1.2.1](https://github.com/HKUDS/DeepTutor/releases/tag/v1.2.1) — จำกัดโทเคนต่อขั้นตอน, สร้างคำตอบใหม่ได้ทุกจุดเข้า, แก้ความเข้ากันได้ของ RAG และ Gemma

> **[2026.4.20]** [v1.2.0](https://github.com/HKUDS/DeepTutor/releases/tag/v1.2.0) — คอมไพเลอร์ Book Engine «หนังสือมีชีวิต», Co-Writer หลายเอกสาร, การแสดงผล HTML แบบโต้ตอบ, @-mention ธนาคารคำถามในแชต

> **[2026.4.18]** [v1.1.2](https://github.com/HKUDS/DeepTutor/releases/tag/v1.1.2) — แท็บ Channels แบบ schema-driven, รวม RAG เป็น pipeline เดียว, แยก chat prompts ออกเป็นไฟล์ภายนอก

> **[2026.4.17]** [v1.1.1](https://github.com/HKUDS/DeepTutor/releases/tag/v1.1.1) — ปุ่ม "ตอบเลย" ครอบคลุมทุกความสามารถ, Co-Writer scroll sync, แผงตั้งค่ารวม, ปุ่ม Stop ระหว่างสตรีม

> **[2026.4.15]** [v1.1.0](https://github.com/HKUDS/DeepTutor/releases/tag/v1.1.0) — ปรับปรุงการ parse LaTeX block math, ตั้งค่า LLM probe ผ่าน agents.yaml, forward extra headers ใน LLM factory, แก้ UUID ของ SaveToNotebookModal, คำแนะนำ Docker + local LLM และขยาย test suite

> **[2026.4.14]** [v1.1.0-beta](https://github.com/HKUDS/DeepTutor/releases/tag/v1.1.0-beta) — URL-based chat routing พร้อม bookmark ได้, ธีม Snow, WebSocket heartbeat & auto-reconnect พร้อม resume, ปรับ ChatComposer ให้เร็วขึ้น, overhaul embedding provider registry, Serper search provider, streaming idle timeout และขยาย test suite

> **[2026.4.13]** [v1.0.3](https://github.com/HKUDS/DeepTutor/releases/tag/v1.0.3) — Question Notebook สำหรับทบทวนแบบทดสอบรวมศูนย์พร้อม bookmark & หมวดหมู่, รองรับ Mermaid diagram ใน Visualize, ตรวจจับ embedding model ไม่ตรง, รวม system message สำหรับ Qwen/vLLM, รองรับ LM Studio & llama.cpp และธีม Glass

> **[2026.4.11]** [v1.0.2](https://github.com/HKUDS/DeepTutor/releases/tag/v1.0.2) — ปรับโครงสร้าง search consolidation ให้ง่ายขึ้นพร้อม SearXNG fallback, แก้ไข provider switch fix, ตั้ง runtime config ชัดเจนใน test runner และแก้ resource leak ฝั่ง frontend

> **[2026.4.10]** [v1.0.1](https://github.com/HKUDS/DeepTutor/releases/tag/v1.0.1) — เพิ่ม Visualize capability ใหม่พร้อม Chart.js/SVG rendering pipeline, ป้องกัน quiz ซ้ำด้วย generation history, รองรับ o4-mini model และปรับปรุง server logging

> **[2026.4.10]** [v1.0.0-beta.4](https://github.com/HKUDS/DeepTutor/releases/tag/v1.0.0-beta.4) — แสดงความคืบหน้า Embedding พร้อม retry เมื่อเจอ HTTP 429, จัดการ dependency ข้ามแพลตฟอร์มใน start tour และแก้ MIME validation ให้ case-insensitive

> **[2026.4.8]** [v1.0.0-beta.3](https://github.com/HKUDS/DeepTutor/releases/tag/v1.0.0-beta.3) — ลบ litellm dependency ใช้ native OpenAI/Anthropic SDK providers แทน, รองรับ Math Animator บน Windows, parse JSON จาก LLM ให้ robust ขึ้น, แก้ KaTeX & navigation ใน Guided Learning และ i18n ภาษาจีนครบ

> **[2026.4.7]** [v1.0.0-beta.2](https://github.com/HKUDS/DeepTutor/releases/tag/v1.0.0-beta.2) — ล้าง runtime cache สำหรับ hot settings reload, รองรับ MinerU nested output, แก้ mimic WebSocket, กำหนดขั้นต่ำ Python 3.11+ และปรับปรุง CI

> **[2026.4.4]** [v1.0.0-beta.1](https://github.com/HKUDS/DeepTutor/releases/tag/v1.0.0-beta.1) — เขียนสถาปัตยกรรมใหม่แบบ Agent-native (~200k บรรทัด) พร้อมโมเดลปลั๊กอิน 2 ชั้น (Tools + Capabilities), CLI & SDK entry points, TutorBot มัลติแชนแนล, Co-Writer, Guided Learning และ persistent memory

> **[2026.1.23]** [v0.6.0](https://github.com/HKUDS/DeepTutor/releases/tag/v0.6.0) — Session persistence, อัปโหลดเอกสารเพิ่มทีละไฟล์, import RAG pipeline ที่ยืดหยุ่น และ localization ภาษาจีนครบ

> **[2026.1.18]** [v0.5.2](https://github.com/HKUDS/DeepTutor/releases/tag/v0.5.2) — รองรับ Docling สำหรับ RAG-Anything, ปรับ logging system และแก้บั๊ก

> **[2026.1.15]** [v0.5.0](https://github.com/HKUDS/DeepTutor/releases/tag/v0.5.0) — Unified service configuration, เลือก RAG pipeline ต่อ knowledge base, ปรับ question generation ใหม่ และปรับแต่ง sidebar

> **[2026.1.9]** [v0.4.0](https://github.com/HKUDS/DeepTutor/releases/tag/v0.4.0) — รองรับ Multi-provider LLM & embedding, หน้า home ใหม่, แยก RAG module และ refactor environment variable

> **[2026.1.5]** [v0.3.0](https://github.com/HKUDS/DeepTutor/releases/tag/v0.3.0) — สถาปัตยกรรม PromptManager รวม, GitHub Actions CI/CD และ Docker image สำเร็จรูปบน GHCR

> **[2026.1.2]** [v0.2.0](https://github.com/HKUDS/DeepTutor/releases/tag/v0.2.0) — Docker deployment, อัปเกรด Next.js 16 & React 19, WebSocket security hardening และแก้ช่องโหว่สำคัญ

</details>

### 📰 ข่าวสาร

> **[2026.4.19]** 🎉 ครบ 20k ดาวหลัง 111 วัน! ขอบคุณที่สนับสนุน — เราจะพัฒนาต่อเพื่อติวเตอร์เชิงบุคคลและฉลาดอย่างแท้จริง

> **[2026.4.10]** 📄 งานวิจัยของเราลง arXiv แล้ว! อ่าน [พรีปรินต์](https://arxiv.org/abs/2604.26962) เพื่อทำความเข้าใจการออกแบบและแนวคิดของ DeepTutor

> **[2026.4.4]** นานมาแล้ว ✨ DeepTutor v1.0.0 มาถึงแล้ว — วิวัฒนาการแบบ agent-native ที่เขียนสถาปัตยกรรมใหม่ตั้งแต่ต้น พร้อม TutorBot และการสลับโหมดอย่างยืดหยุ่น ภายใต้สัญญาอนุญาต Apache-2.0 บทใหม่เริ่มต้นขึ้น เรื่องราวของเรายังดำเนินต่อไป!

> **[2026.2.6]** 🚀 เราไปถึง 10,000 ดาวภายในเพียง 39 วัน! ขอบคุณชุมชนที่ยอดเยี่ยมของเราสำหรับการสนับสนุน!

> **[2026.1.1]** สวัสดีปีใหม่! มาร่วม [Discord](https://discord.gg/eRsjPgMU4t), [WeChat](https://github.com/HKUDS/DeepTutor/issues/78) หรือ [Discussions](https://github.com/HKUDS/DeepTutor/discussions) ของเรา — มาร่วมกำหนดอนาคตของ DeepTutor กัน!

> **[2025.12.29]** DeepTutor เปิดตัวอย่างเป็นทางการ!


## ✨ คุณสมบัติเด่น

- **พื้นที่แชตแบบรวมศูนย์** — 6 โหมดในเธรดเดียว: Chat, Deep Solve, Quiz Generation, Deep Research, Math Animator และ Visualize ใช้บริบทร่วมกัน เริ่มจากถามง่าย ไปสู่การแก้ปัญหาแบบหลายเอเจนต์ สร้างภาพความคิด ออกแบบทดสอบ และเจาะลึกงานวิจัยโดยไม่เสียประวัติ
- **AI Co-Writer** — พื้นที่ Markdown หลายเอกสาร AI เป็นผู้ร่วมเขียนระดับแรก: Rewrite, Expand, Shorten ดึงบริบทจาก knowledge base และเว็บ
- **Book Engine** — เปลี่ยนวัสดุของคุณเป็น «หนังสือมีชีวิต» แบบมีโครงสร้างและโต้ตอบได้ ไปป์ไลน์หลายเอเจนต์ 13 ประเภทบล็อก (แบบทดสอบ แฟลชการ์ด ไทม์ไลน์ กราฟแนวคิด ฯลฯ)
- **Knowledge Hub** — สร้าง knowledge base แบบ RAG-ready สมุดบันทึกสีสัน ธนาคารคำถาม และ Skills กำหนดสไตล์การสอน
- **Persistent Memory** — DeepTutor สร้างโปรไฟล์ผู้เรียนที่เติบโตอยู่ตลอดเวลา ใช้ร่วมกันข้ามทุกฟีเจอร์และทุก TutorBot ยิ่งใช้ยิ่งแม่นยำ
- **TutorBot ส่วนตัว** — ไม่ใช่แค่ chatbot แต่เป็นติวเตอร์อัตโนมัติที่มี workspace, memory, บุคลิก และทักษะของตัวเอง ขับเคลื่อนโดย [nanobot](https://github.com/HKUDS/nanobot)
- **Agent-Native CLI** — ทุกความสามารถ, knowledge base, session และ TutorBot ผ่านคำสั่งเดียว Rich และ JSON มอบ [`SKILL.md`](../../SKILL.md) ให้ agent

---

## 🚀 เริ่มต้นใช้งาน

### ข้อกำหนดเบื้องต้น

ก่อนเริ่ม ตรวจสอบว่ามีเครื่องมือต่อไปนี้ติดตั้งแล้ว:

| ข้อกำหนด | เวอร์ชัน | ตรวจสอบ | หมายเหตุ |
|:---|:---|:---|:---|
| [Git](https://git-scm.com/) | ใดก็ได้ | `git --version` | สำหรับ clone โปรเจกต์ |
| [Python](https://www.python.org/downloads/) | 3.11+ | `python --version` | รัน backend |
| [Node.js](https://nodejs.org/) | 20.9+ | `node --version` | frontend runtime สำหรับการติดตั้ง Web ในเครื่อง |
| [npm](https://www.npmjs.com/) | มากับ Node.js | `npm --version` | ติดตั้งพร้อม Node.js |

คุณยังต้องมี **API Key** จากผู้ให้บริการ LLM อย่างน้อยหนึ่งราย (เช่น [OpenAI](https://platform.openai.com/api-keys), [DeepSeek](https://platform.deepseek.com/), [Anthropic](https://console.anthropic.com/)) Setup Tour จะนำทางการกรอก

### ตัวเลือก A — Setup Tour (แนะนำ)

**สคริปต์ CLI แบบโต้ตอบเพียงตัวเดียว** พาคุณจาก clone สดใหม่ไปจนถึงแอปที่รันได้ — ไม่ต้อง `pip install` หรือ `npm install` หรือแก้ `.env` เอง ทุกอย่างถูกตรวจหา ติดตั้ง และตั้งค่าในขั้นแนะนำ 7 ขั้น

```bash
git clone https://github.com/HKUDS/DeepTutor.git
cd DeepTutor

# สร้าง Python virtual environment (เลือกอย่างใดอย่างหนึ่ง):
conda create -n deeptutor python=3.11 && conda activate deeptutor   # Anaconda/Miniconda
python -m venv .venv && source .venv/bin/activate                    # macOS/Linux
python -m venv .venv && .venv\Scripts\activate                       # Windows

# เริ่ม guided tour
python scripts/start_tour.py
```

เมื่อตัวช่วยจบ:

```bash
python scripts/start_web.py
```

> **การเปิดใช้งานประจำวัน** — โดยทั่วไปรัน Tour แค่ครั้งเดียว หลังจากนั้นใช้ `python scripts/start_web.py` เพื่อสตาร์ท backend กับ frontend พร้อมกัน (URL ฝั่ง frontend แสดงในเทอร์มินัล) รัน `start_tour.py` อีกครั้งเฉพาะเมื่อต้องตั้งค่า provider ใหม่ เปลี่ยนพอร์ต หรือติดตั้งส่วนเสริมที่ขาด ในหน้า **Settings** ของเว็บกด **Run Tour** เพื่อเล่น walkthrough แบบเน้นจุดอีกครั้ง

### ตัวเลือก B — ติดตั้งเองแบบ Local

หากคุณต้องการควบคุมทุกขั้นตอนด้วยตัวเอง ให้ติดตั้งและตั้งค่าตามนี้

**1. ติดตั้ง dependency**

```bash
git clone https://github.com/HKUDS/DeepTutor.git
cd DeepTutor

conda create -n deeptutor python=3.11 && conda activate deeptutor
pip install -e ".[server]"

# Frontend
cd web && npm install && cd ..
```

**2. ตั้งค่า environment**

```bash
cp .env.example .env
```

แก้ไขไฟล์ `.env` และกรอกค่าที่จำเป็นอย่างน้อยดังนี้:

```dotenv
# LLM (จำเป็น)
LLM_BINDING=openai
LLM_MODEL=gpt-4o-mini
LLM_API_KEY=sk-xxx
LLM_HOST=https://api.openai.com/v1

# Embedding (จำเป็นสำหรับ Knowledge Base)
EMBEDDING_BINDING=openai
EMBEDDING_MODEL=text-embedding-3-large
EMBEDDING_API_KEY=sk-xxx
EMBEDDING_HOST=https://api.openai.com/v1
EMBEDDING_DIMENSION=3072
```

<details>
<summary><b>ผู้ให้บริการ LLM ที่รองรับ</b></summary>

| ผู้ให้บริการ | Binding | Base URL เริ่มต้น |
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
<summary><b>ผู้ให้บริการ Embedding ที่รองรับ</b></summary>

| ผู้ให้บริการ | Binding | ตัวอย่างโมเดล | Dimension เริ่มต้น |
|:--|:--|:--|:--|
| OpenAI | `openai` | `text-embedding-3-large` | 3072 |
| Azure OpenAI | `azure_openai` | deployment name | — |
| Cohere | `cohere` | `embed-v4.0` | 1024 |
| Jina | `jina` | `jina-embeddings-v3` | 1024 |
| Ollama | `ollama` | `nomic-embed-text` | 768 |
| vLLM / LM Studio | `vllm` | โมเดล embedding ใดก็ได้ | — |
| OpenAI-compatible | `custom` | — | — |

ผู้ให้บริการที่เข้ากันได้กับ OpenAI (DashScope, SiliconFlow ฯลฯ) ใช้ผ่าน binding `custom` หรือ `openai` ได้

</details>

<details>
<summary><b>ผู้ให้บริการ Web Search ที่รองรับ</b></summary>

| ผู้ให้บริการ | Env Key | หมายเหตุ |
|:--|:--|:--|
| Brave | `BRAVE_API_KEY` | แนะนำ, มี free tier |
| Tavily | `TAVILY_API_KEY` | |
| Serper | `SERPER_API_KEY` | ผลการค้นหา Google ผ่าน Serper |
| Jina | `JINA_API_KEY` | |
| SearXNG | — | Self-hosted, ไม่ต้องใช้ API key |
| DuckDuckGo | — | ไม่ต้องใช้ API key |
| Perplexity | `PERPLEXITY_API_KEY` | ต้องใช้ API key |

</details>

**3. เริ่มบริการ**

วิธีที่เร็วที่สุด:

```bash
python scripts/start_web.py
```

คำสั่งนี้จะสตาร์ททั้ง backend และ frontend พร้อมเปิดเบราว์เซอร์ให้โดยอัตโนมัติ

หรือรันแยกเทอร์มินัล:

```bash
# Backend (FastAPI)
python -m deeptutor.api.run_server

# Frontend (Next.js) — เปิดอีกเทอร์มินัลหนึ่ง
cd web && npm run dev -- -p 3782
```

| Service | Port เริ่มต้น |
|:---:|:---:|
| Backend | `8001` |
| Frontend | `3782` |

เปิด [http://localhost:3782](http://localhost:3782) แล้วพร้อมใช้งาน

### ตัวเลือก C — ติดตั้งด้วย Docker

Docker ช่วยรวม backend และ frontend ไว้ในคอนเทนเนอร์เดียว จึงไม่จำเป็นต้องติดตั้ง Python หรือ Node.js บนเครื่องโดยตรง

**1. ตั้งค่า environment variable** (จำเป็นสำหรับทุกตัวเลือก)

```bash
git clone https://github.com/HKUDS/DeepTutor.git
cd DeepTutor
cp .env.example .env
```

แก้ไข `.env` และกรอกค่าที่จำเป็น (เหมือน [ตัวเลือก B](#ตัวเลือก-b--ติดตั้งเองแบบ-local) ด้านบน)

**2a. ดึง image ทางการ (แนะนำ)**

Image ทางการเผยแพร่ที่ [GitHub Container Registry](https://github.com/HKUDS/DeepTutor/pkgs/container/deeptutor) ทุกครั้งที่ release สำหรับ `linux/amd64` และ `linux/arm64`

```bash
docker compose -f docker-compose.ghcr.yml up -d
```

หากต้องการ pin เวอร์ชันเฉพาะ ให้แก้ image tag ใน `docker-compose.ghcr.yml`:

```yaml
image: ghcr.io/hkuds/deeptutor:1.0.0  # หรือ :latest
```

**2b. Build จาก source**

```bash
docker compose up -d
```

คำสั่งนี้จะ build image จาก `Dockerfile` และเริ่มคอนเทนเนอร์

**3. ตรวจสอบและจัดการ**

เปิด [http://localhost:3782](http://localhost:3782) เมื่อคอนเทนเนอร์พร้อมแล้ว

```bash
docker compose logs -f   # ดู log
docker compose down       # หยุดและลบคอนเทนเนอร์
```

<details>
<summary><b>Deploy บน Cloud / เซิร์ฟเวอร์ระยะไกล</b></summary>

เมื่อ deploy บนเซิร์ฟเวอร์ระยะไกล เบราว์เซอร์ต้องรู้ URL สาธารณะของ backend API เพิ่มตัวแปรอีกหนึ่งตัวใน `.env`:

```dotenv
# ตั้งเป็น URL สาธารณะที่สามารถเข้าถึง backend ได้
NEXT_PUBLIC_API_BASE_EXTERNAL=https://your-server.com:8001
```

Frontend startup script จะใช้ค่านี้ตอน runtime — ไม่ต้อง rebuild

</details>

<details>
<summary><b>การยืนยันตัวตน (สำหรับการ deploy สาธารณะ)</b></summary>

การยืนยันตัวตน **ปิดใช้งานโดยค่าเริ่มต้น** — ไม่ต้องเข้าสู่ระบบบน localhost สำหรับการ deploy แบบ multi-tenant ดูส่วน [มัลติยูเซอร์](#multi-user) ด้านล่าง

**ผู้ใช้คนเดียวแบบ headless (ไม่มีขั้นตอน `/register`):** กำหนดค่าล่วงหน้าผ่าน env vars:

```bash
python -c "from deeptutor.services.auth import hash_password; print(hash_password('yourpassword'))"
```

```dotenv
AUTH_ENABLED=true
AUTH_USERNAME=admin
AUTH_PASSWORD_HASH=<วางแฮชที่นี่>
AUTH_SECRET=your-secret-here
```

</details>

<details>
<summary><b>PocketBase sidecar (ยืนยันตัวตนและจัดเก็บข้อมูลเสริม)</b></summary>

PocketBase เป็น backend เบาแบบ optional ที่แทนที่การยืนยันตัวตน SQLite/JSON ในตัว

> ⚠️ **PocketBase mode ใช้ได้กับผู้ใช้คนเดียวเท่านั้นในปัจจุบัน** สคีมาเริ่มต้นไม่มีฟิลด์ `role` ใน `users` และ queries ไม่ถูกกรองตาม `user_id` Multi-user: ปล่อย `POCKETBASE_URL` ว่างไว้

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
<summary><b>Development mode (hot-reload)</b></summary>

เพิ่ม dev override เพื่อ mount source code และเปิด hot-reload สำหรับทั้งสองบริการ:

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up
```

การเปลี่ยนแปลงใน `deeptutor/`, `deeptutor_cli/`, `scripts/` และ `web/` จะมีผลทันที

</details>

<details>
<summary><b>กำหนด Port เอง</b></summary>

แก้ไข port เริ่มต้นใน `.env`:

```dotenv
BACKEND_PORT=9001
FRONTEND_PORT=4000
```

จากนั้นรีสตาร์ท:

```bash
docker compose up -d     # หรือ docker compose -f docker-compose.ghcr.yml up -d
```

</details>

<details>
<summary><b>การเก็บข้อมูลถาวร (Data persistence)</b></summary>

ข้อมูลผู้ใช้และ knowledge base เก็บผ่าน Docker volume ที่ map กับ directory ในเครื่อง:

| Container path | Host path | เนื้อหา |
|:---|:---|:---|
| `/app/data/user` | `./data/user` | Settings, workspace, sessions, logs |
| `/app/data/memory` | `./data/memory` | หน่วยความจำระยะยาวที่ใช้ร่วมกัน (`SUMMARY.md`, `PROFILE.md`) |
| `/app/data/knowledge_bases` | `./data/knowledge_bases` | เอกสารที่อัปโหลด & vector indices |

Directory เหล่านี้จะอยู่หลังจาก `docker compose down` และถูกนำมาใช้ใหม่เมื่อ `docker compose up` ครั้งต่อไป

</details>

<details>
<summary><b>ตารางอ้างอิง Environment Variables</b></summary>

| ตัวแปร | จำเป็น | คำอธิบาย |
|:---|:---:|:---|
| `LLM_BINDING` | **ใช่** | ผู้ให้บริการ LLM (`openai`, `anthropic` ฯลฯ) |
| `LLM_MODEL` | **ใช่** | ชื่อโมเดล (เช่น `gpt-4o`) |
| `LLM_API_KEY` | **ใช่** | API key สำหรับ LLM |
| `LLM_HOST` | **ใช่** | URL endpoint ของ API |
| `EMBEDDING_BINDING` | **ใช่** | ผู้ให้บริการ Embedding |
| `EMBEDDING_MODEL` | **ใช่** | ชื่อ Embedding model |
| `EMBEDDING_API_KEY` | **ใช่** | API key สำหรับ Embedding |
| `EMBEDDING_HOST` | **ใช่** | Endpoint สำหรับ Embedding |
| `EMBEDDING_DIMENSION` | **ใช่** | มิติของ vector |
| `SEARCH_PROVIDER` | ไม่ | ผู้ให้บริการ Search (`tavily`, `jina`, `serper`, `perplexity` ฯลฯ) |
| `SEARCH_API_KEY` | ไม่ | API key สำหรับ Search |
| `BACKEND_PORT` | ไม่ | Port ฝั่ง backend (ค่าเริ่มต้น `8001`) |
| `FRONTEND_PORT` | ไม่ | Port ฝั่ง frontend (ค่าเริ่มต้น `3782`) |
| `NEXT_PUBLIC_API_BASE_EXTERNAL` | ไม่ | URL สาธารณะของ backend สำหรับ cloud deployment |
| `DISABLE_SSL_VERIFY` | ไม่ | ปิดการตรวจสอบ SSL (ค่าเริ่มต้น `false`) |

</details>

### ตัวเลือก D — ใช้เฉพาะ CLI

หากคุณต้องการเฉพาะ command-line interface โดยไม่ใช้เว็บ frontend:

```bash
pip install -e ".[cli]"
deeptutor chat                                   # Interactive REPL
deeptutor run chat "Explain Fourier transform"   # เรียกใช้ capability แบบ one-shot
deeptutor run deep_solve "Solve x^2 = 4"         # แก้ปัญหาแบบหลายเอเจนต์
deeptutor kb create my-kb --doc textbook.pdf     # สร้าง knowledge base
```

> ดูรายละเอียดเพิ่มเติมที่ [DeepTutor CLI](#%EF%B8%8F-deeptutor-cli--อินเทอร์เฟซแบบ-agent-native)

---

## 📖 สำรวจ DeepTutor

<div align="center">
<img src="../../assets/figs/deeptutor-architecture.png" alt="สถาปัตยกรรม DeepTutor" width="800">
</div>

### 💬 Chat — พื้นที่ทำงานอัจฉริยะแบบรวม

<div align="center">
<img src="../../assets/figs/dt-chat.png" alt="พื้นที่ Chat" width="800">
</div>

DeepTutor รวม 6 โหมดหลักไว้ใน workspace เดียว โดยใช้ **ระบบจัดการบริบทร่วมกัน** ทำให้ประวัติการสนทนา knowledge base และแหล่งอ้างอิงต่อเนื่องข้ามโหมดได้ — สลับไปมาได้อิสระในหัวข้อเดียวกัน

| โหมด | หน้าที่ |
|:---|:---|
| **Chat** | สนทนาแบบยืดหยุ่น พร้อมเปิดใช้ RAG, web search, code execution, deep reasoning, brainstorming และ paper search ได้ตามต้องการ |
| **Deep Solve** | แก้ปัญหาแบบหลายเอเจนต์ โดยวางแผน สืบค้น แก้โจทย์ และตรวจสอบ พร้อม citation อย่างเป็นระบบ |
| **Quiz Generation** | สร้างแบบทดสอบจาก knowledge base พร้อมตรวจสอบคุณภาพของคำถาม |
| **Deep Research** | แยกหัวข้อออกเป็นประเด็นย่อย ส่งเอเจนต์ค้นคว้าแบบขนานจาก RAG, เว็บ และงานวิชาการ แล้วสรุปเป็นรายงานที่มีอ้างอิง |
| **Math Animator** | เปลี่ยนแนวคิดคณิตศาสตร์ให้เป็นภาพเคลื่อนไหวและ storyboard ด้วย Manim |
| **Visualize** | สร้าง SVG, Chart.js, Mermaid หรือหน้า HTML แบบรวมไฟล์เดียวจากคำอธิบายภาษาธรรมดา |

เครื่องมือ **แยกอิสระจาก workflow** — ในทุกโหมด คุณเลือกได้ว่าจะเปิดเครื่องมือตัวไหน ใช้กี่ตัว หรือจะไม่ใช้เลย Workflow จัดการเรื่องการให้เหตุผล ส่วนเครื่องมือเป็นของคุณที่จะประกอบเข้าด้วยกัน

> เริ่มจากถามคำถามง่าย ๆ ยกระดับเป็น Deep Solve เมื่อยากขึ้น แสดงภาพความคิด สร้างแบบทดสอบเพื่อตรวจสอบตัวเอง จากนั้นเปิด Deep Research เพื่อลงลึก — ทั้งหมดในเธรดเดียว

### ✍️ Co-Writer — พื้นที่เขียนหลายเอกสารกับ AI

<div align="center">
<img src="../../assets/figs/dt-cowriter.png" alt="Co-Writer" width="800">
</div>

สร้างและจัดการหลายเอกสาร แต่ละไฟล์ถูกเก็บถาวร — ไม่ใช่แค่ฉบับร่างครั้งเดียว: Markdown เต็มรูปแบบที่ AI เป็นผู้ร่วมเขียนระดับแรก เลือกข้อความแล้วสั่ง **Rewrite**, **Expand** หรือ **Shorten** ดึงบริบทจาก knowledge base หรือเว็บ undo/redo เต็มรูปแบบ บันทึกลง notebook ได้

### 📖 Book Engine — หนังสือมีชีวิตแบบโต้ตอบ

<div align="center">
<img src="../../assets/figs/dt-book-0.png" alt="ห้องสมุด" width="270"><img src="../../assets/figs/dt-book-1.png" alt="ตัวอ่าน" width="270"><img src="../../assets/figs/dt-book-2.png" alt="แอนิเมชัน" width="270">
</div>

ระบุหัวข้อชี้ไปที่ knowledge base — ได้หนังสือที่มีโครงสร้างและโต้ตอบได้ ไม่ใช่ไฟล์ส่งออกคงที่ แต่เป็นเอกสารมีชีวิตสำหรับอ่าน ทดสอบตัวเอง และพูดคุยในบริบท

เบื้องหลังเป็นไปป์ไลน์หลายเอเจนต์: เสนอโครงร่าง ดึงแหล่งอ้างอิง รวมต้นไม้บท วางแผนหน้า และคอมไพล์บล็อก คุณยังคุมได้: ตรวจโครงร่าง จัดเรียบบท แชตข้างหน้าใดก็ได้

13 ประเภทบล็อก — ข้อความ callout แบบทดสอบ แฟลชการ์ด โค้ด รูป ดำดิ่งลึก แอนิเมชัน แบบโต้ตอบ ไทม์ไลน์ กราฟแนวคิด ส่วน โน้ตผู้ใช้ — แต่ละแบบมีคอมโพเนนต์โต้ตอบ ไทม์ไลน์ความคืบหน้าแบบเรียลไทม์

### 📚 การจัดการความรู้ — โครงสร้างพื้นฐานการเรียนของคุณ

<div align="center">
<img src="../../assets/figs/dt-knowledge.png" alt="การจัดการความรู้" width="800">
</div>

คอลเลกชันเอกสาร โน้ต และบุคลิกการสอน

- **Knowledge Bases** — อัปโหลด PDF, TXT หรือ Markdown เพิ่มทีละไฟล์
- **Notebooks** — บันทึกจาก Chat, Co-Writer, Book หรือ Deep Research จัดหมวดและสี
- **Question Bank** — ทบทวนคำถามที่สร้างแล้ว บุ๊กมาร์กและ @ ในแชตเพื่อวิเคราะห์ผลในอดีต
- **Skills** — สร้างบุคลิกการสอนด้วย `SKILL.md`: ชื่อ คำอธิบาย ทริกเกอร์ (ถ้ามี) และ Markdown ที่ฉีดเข้า system prompt เมื่อเปิดใช้

Knowledge base ของคุณไม่ใช่แค่ที่เก็บ — มันมีส่วนร่วมอย่างแข็งขันในทุกการสนทนา ทุกเซสชันวิจัย และทุกเส้นทางการเรียนรู้

### 🧠 Memory — DeepTutor เรียนรู้ไปพร้อมกับคุณ

<div align="center">
<img src="../../assets/figs/dt-memory.png" alt="Memory" width="800">
</div>

DeepTutor มี memory แบบถาวรที่เติบโตอยู่ตลอดเวลาผ่าน 2 มิติ:

- **Summary** — สรุปว่าคุณเรียนอะไรไปแล้ว สำรวจประเด็นใดบ้าง และความเข้าใจพัฒนาอย่างไร
- **Profile** — โปรไฟล์ผู้เรียน เช่น ระดับความรู้ เป้าหมาย สไตล์การสื่อสาร และความชอบ — ปรับปรุงอัตโนมัติผ่านทุกการโต้ตอบ

Memory นี้ถูกใช้ร่วมกันข้ามทุกฟีเจอร์และทุก TutorBot ยิ่งคุณใช้ DeepTutor มากเท่าไร มันก็ยิ่งตอบได้เฉพาะตัวและมีประสิทธิภาพมากขึ้น

---

### 🦞 TutorBot — ติวเตอร์ AI แบบถาวรและอัตโนมัติ

<div align="center">
<img src="../../assets/figs/tutorbot-architecture.png" alt="สถาปัตยกรรม TutorBot" width="800">
</div>

TutorBot ไม่ใช่ chatbot ธรรมดา แต่เป็น **เอเจนต์แบบถาวร หลายอินสแตนซ์** ที่ทำงานบน [nanobot](https://github.com/HKUDS/nanobot) โดยแต่ละ TutorBot รัน agent loop เป็นของตัวเองพร้อม workspace, memory และบุคลิกแยกจากกัน คุณสามารถสร้างติวเตอร์คณิตศาสตร์แบบโสเครติส, โค้ชการเขียนที่ใจเย็น หรือผู้ช่วยวิจัยที่เข้มงวดได้พร้อมกันหลายตัว แต่ละตัวเติบโตไปพร้อมกับคุณ

<div align="center">
<img src="../../assets/figs/tb.png" alt="TutorBot" width="800">
</div>

- **Soul Templates** — กำหนดบุคลิก โทนการสอน และปรัชญาการสอนผ่านไฟล์ Soul ที่แก้ไขได้ เลือกจาก archetype ในตัว (โสเครติส, ให้กำลังใจ, เข้มงวด) หรือออกแบบเอง — soul กำหนดทุกการตอบ
- **Independent Workspace** — แต่ละบอตมี directory ของตัวเองพร้อม memory, sessions, skills และ config แยกจากกัน — แยกตัวเต็มที่แต่ยังเข้าถึงชั้นความรู้ร่วมของ DeepTutor ได้
- **Proactive Heartbeat** — บอตไม่ใช่แค่ตอบ — มันริเริ่มเอง ระบบ Heartbeat ในตัวเปิดให้เช็กอินการเรียนซ้ำ เตือนทบทวน และจัดตารางงาน ติวเตอร์ของคุณมาหาแม้คุณไม่เริ่ม
- **Full Tool Access** — ทุกบอตเข้าถึงเครื่องมือครบชุดของ DeepTutor: RAG retrieval, code execution, web search, academic paper search, deep reasoning และ brainstorming
- **Skill Learning** — สอนบอตความสามารถใหม่โดยเพิ่มไฟล์ skill ลงใน workspace ของมัน เมื่อความต้องการของคุณเปลี่ยน ความสามารถของติวเตอร์ก็เปลี่ยนตาม
- **Multi-Channel Presence** — เชื่อมต่อกับ Telegram, Discord, Slack, Feishu, WeChat Work, DingTalk, Email และช่องทางอื่น ๆ ติวเตอร์ไปหาคุณไม่ว่าคุณจะอยู่ที่ไหน
- **Team & Sub-Agents** — สร้าง sub-agent ทำงานเบื้องหลังหรือจัด multi-agent team ภายในบอตเดียวสำหรับงานซับซ้อนและใช้เวลานาน

```bash
deeptutor bot create math-tutor --persona "Socratic math teacher who uses probing questions"
deeptutor bot create writing-coach --persona "Patient, detail-oriented writing mentor"
deeptutor bot list                  # ดูติวเตอร์ทั้งหมดที่กำลังทำงาน
```

---

### ⌨️ DeepTutor CLI — อินเทอร์เฟซแบบ Agent-Native

<div align="center">
<img src="../../assets/figs/cli-architecture.png" alt="สถาปัตยกรรม DeepTutor CLI" width="800">
</div>

DeepTutor รองรับ CLI อย่างเต็มรูปแบบ ทุก capability, knowledge base, session, memory และ TutorBot อยู่ห่างแค่คำสั่งเดียว — ไม่ต้องเปิดเบราว์เซอร์ CLI ให้บริการทั้งมนุษย์ (แสดงผลสวยงามในเทอร์มินัล) และ AI agent (ส่งออกเป็น JSON ที่มีโครงสร้าง)

มอบ [`SKILL.md`](../../SKILL.md) ที่ root ของโปรเจกต์ให้ agent ที่ใช้เครื่องมือ ([nanobot](https://github.com/HKUDS/nanobot) หรือ LLM ใดก็ตามที่มี tool access) แล้วมันจะตั้งค่าและใช้งาน DeepTutor ได้เอง

**One-shot execution** — เรียกใช้ capability ใดก็ได้จากเทอร์มินัล:

```bash
deeptutor run chat "Explain the Fourier transform" -t rag --kb textbook
deeptutor run deep_solve "Prove that √2 is irrational" -t reason
deeptutor run deep_question "Linear algebra" --config num_questions=5
deeptutor run deep_research "Attention mechanisms in transformers"
deeptutor run visualize "Draw the architecture of a transformer"
```

**Interactive REPL** — เซสชันแชตแบบถาวรพร้อมสลับโหมดขณะใช้งาน:

```bash
deeptutor chat --capability deep_solve --kb my-kb
# ภายใน REPL: /cap, /tool, /kb, /history, /notebook, /config เพื่อสลับขณะใช้งาน
```

**Knowledge base lifecycle** — สร้าง ค้นหา และจัดการคลัง RAG-ready ทั้งหมดจากเทอร์มินัล:

```bash
deeptutor kb create my-kb --doc textbook.pdf       # สร้างจากเอกสาร
deeptutor kb add my-kb --docs-dir ./papers/         # เพิ่มโฟลเดอร์เอกสาร
deeptutor kb search my-kb "gradient descent"        # ค้นหาโดยตรง
deeptutor kb set-default my-kb                      # ตั้งเป็น KB เริ่มต้น
```

**Dual output mode** — แสดงผลสวยงามสำหรับมนุษย์, JSON สำหรับ pipeline:

```bash
deeptutor run chat "Summarize chapter 3" -f rich    # แสดงผลสี สวยงาม
deeptutor run chat "Summarize chapter 3" -f json    # JSON events แบบ line-delimited
```

**Session continuity** — กลับมาทำต่อจากจุดที่ค้างไว้:

```bash
deeptutor session list                              # แสดงรายการเซสชัน
deeptutor session open <id>                         # กลับมาทำต่อใน REPL
```

<details>
<summary><b>ตารางอ้างอิงคำสั่ง CLI ทั้งหมด</b></summary>

**คำสั่งหลัก**

| คำสั่ง | คำอธิบาย |
|:---|:---|
| `deeptutor run <capability> <message>` | เรียกใช้ capability แบบ single turn (`chat`, `deep_solve`, `deep_question`, `deep_research`, `math_animator`, `visualize`) |
| `deeptutor chat` | Interactive REPL พร้อมตัวเลือก `--capability`, `--tool`, `--kb`, `--language` |
| `deeptutor serve` | เริ่ม DeepTutor API server |

**`deeptutor bot`**

| คำสั่ง | คำอธิบาย |
|:---|:---|
| `deeptutor bot list` | แสดงรายการ TutorBot ทั้งหมด |
| `deeptutor bot create <id>` | สร้างและเริ่มบอตใหม่ (`--name`, `--persona`, `--model`) |
| `deeptutor bot start <id>` | เริ่มบอต |
| `deeptutor bot stop <id>` | หยุดบอต |

**`deeptutor kb`**

| คำสั่ง | คำอธิบาย |
|:---|:---|
| `deeptutor kb list` | แสดงรายการ knowledge base ทั้งหมด |
| `deeptutor kb info <name>` | แสดงรายละเอียด knowledge base |
| `deeptutor kb create <name>` | สร้างจากเอกสาร (`--doc`, `--docs-dir`) |
| `deeptutor kb add <name>` | เพิ่มเอกสารทีละไฟล์ |
| `deeptutor kb search <name> <query>` | ค้นหา knowledge base |
| `deeptutor kb set-default <name>` | ตั้งเป็น KB เริ่มต้น |
| `deeptutor kb delete <name>` | ลบ knowledge base (`--force`) |

**`deeptutor memory`**

| คำสั่ง | คำอธิบาย |
|:---|:---|
| `deeptutor memory show [file]` | ดู memory (`summary`, `profile` หรือ `all`) |
| `deeptutor memory clear [file]` | ล้าง memory (`--force`) |

**`deeptutor session`**

| คำสั่ง | คำอธิบาย |
|:---|:---|
| `deeptutor session list` | แสดงรายการเซสชัน (`--limit`) |
| `deeptutor session show <id>` | ดูข้อความในเซสชัน |
| `deeptutor session open <id>` | กลับมาทำต่อใน REPL |
| `deeptutor session rename <id>` | เปลี่ยนชื่อเซสชัน (`--title`) |
| `deeptutor session delete <id>` | ลบเซสชัน |

**`deeptutor notebook`**

| คำสั่ง | คำอธิบาย |
|:---|:---|
| `deeptutor notebook list` | แสดงรายการ notebook |
| `deeptutor notebook create <name>` | สร้าง notebook (`--description`) |
| `deeptutor notebook show <id>` | ดูบันทึกใน notebook |
| `deeptutor notebook add-md <id> <path>` | นำเข้า markdown เป็นบันทึก |
| `deeptutor notebook replace-md <id> <rec> <path>` | เปลี่ยนบันทึก markdown |
| `deeptutor notebook remove-record <id> <rec>` | ลบบันทึก |

**`deeptutor book`**

| คำสั่ง | คำอธิบาย |
|:---|:---|
| `deeptutor book list` | แสดงรายการหนังสือทั้งหมดใน workspace |
| `deeptutor book health <book_id>` | ตรวจ KB drift และสุขภาพของหนังสือ |
| `deeptutor book refresh-fingerprints <book_id>` | รีเฟรช fingerprint ของ KB และล้างหน้าที่ล้าสมัย |

**`deeptutor config` / `plugin` / `provider`**

| คำสั่ง | คำอธิบาย |
|:---|:---|
| `deeptutor config show` | แสดงสรุป configuration ปัจจุบัน |
| `deeptutor plugin list` | แสดงรายการ tools และ capabilities ที่ลงทะเบียน |
| `deeptutor plugin info <name>` | แสดงรายละเอียด tool หรือ capability |
| `deeptutor provider login <provider>` | ยืนยันตัวตนกับผู้ให้บริการ (OAuth กับ `openai-codex`; `github-copilot` ตรวจเซสชัน Copilot ที่มีอยู่) |

</details>

---

<a id="multi-user"></a>
### 👥 มัลติยูเซอร์ — การ deploy ร่วมกันพร้อม workspace แยกต่อผู้ใช้

<div align="center">
<img src="../../assets/figs/dt-multi-user.png" alt="มัลติยูเซอร์" width="800">
</div>

เปิดใช้การยืนยันตัวตน และ DeepTutor จะกลายเป็น deployment แบบ multi-tenant พร้อม **workspace แยกต่อผู้ใช้** และ **ทรัพยากรที่ผู้ดูแลจัดการ** ผู้ที่ลงทะเบียนคนแรกจะเป็นผู้ดูแล บัญชีถัดไปสร้างโดยผู้ดูแล (แบบ invite-only) แต่ละคนได้รับประวัติแชต/หน่วยความจำ/สมุดบันทึก/ฐานความรู้ของตนเอง

**เริ่มต้นด่วน (5 ขั้นตอน):**

```bash
# 1. เปิดใช้การยืนยันตัวตนใน .env ที่ root ของโปรเจกต์
echo 'AUTH_ENABLED=true' >> .env
echo 'AUTH_SECRET=<วางอักขระสุ่ม 64+ ตัว>' >> .env

# 2. รีสตาร์ท web stack
python scripts/start_web.py

# 3. เปิด http://localhost:3782/register และสร้างบัญชีแรก
#    การลงทะเบียนครั้งแรกเป็นครั้งเดียวที่เปิดสาธารณะ ผู้ใช้นั้น
#    จะเป็นผู้ดูแล และ /register จะถูกปิดอัตโนมัติ

# 4. ในฐานะผู้ดูแล ไปที่ /admin/users → "เพิ่มผู้ใช้"

# 5. สำหรับแต่ละผู้ใช้ คลิกไอคอนสไลเดอร์ → กำหนด LLM profiles,
#    knowledge bases, และ skills → บันทึก
```

**สิ่งที่ผู้ดูแลเห็น:**

- **หน้า Settings ครบ** ที่ `/settings` — LLM/embedding/search, API keys, model catalog
- **จัดการผู้ใช้** ที่ `/admin/users` — สร้าง เลื่อนตำแหน่ง ลดตำแหน่ง ลบบัญชี
- **Grant editor** — เลือก model profiles, KBs, skills สำหรับผู้ใช้ที่ไม่ใช่ผู้ดูแล; grants มีแค่ **logical IDs** ไม่มี API key ข้ามขอบเขต
- **Audit trail** — ทุกการเปลี่ยนแปลง grant บันทึกใน `multi-user/_system/audit/usage.jsonl`

**สิ่งที่ผู้ใช้ทั่วไปได้รับ:**

- **Workspace แยก** ใต้ `multi-user/<uid>/` — `chat_history.db`, หน่วยความจำ, สมุดบันทึก, KB ส่วนตัว
- **สิทธิ์อ่านอย่างเดียว** สำหรับ KBs/skills ที่ผู้ดูแลกำหนด พร้อมป้าย "กำหนดโดยผู้ดูแล"
- **หน้า Settings แบบจำกัด** — ธีม ภาษา และสรุป models ที่ได้รับ ไม่มี API keys
- **LLM ที่กำหนด** — การสนทนาผ่าน model ที่ผู้ดูแลกำหนด; ไม่มี grant จะถูกปฏิเสธตั้งแต่ต้น

**โครงสร้าง workspace:**

```
multi-user/
├── _system/
│   ├── auth/users.json
│   ├── auth/auth_secret
│   ├── grants/<uid>.json
│   └── audit/usage.jsonl
└── <uid>/
    ├── user/
    │   ├── chat_history.db
    │   ├── settings/interface.json
    │   └── workspace/{chat,co-writer,book,...}
    ├── memory/{SUMMARY.md,PROFILE.md}
    └── knowledge_bases/...
```

**การอ้างอิงการกำหนดค่า:**

| ตัวแปร | จำเป็น | คำอธิบาย |
|:---|:---|:---|
| `AUTH_ENABLED` | ใช่ | `true` เพื่อเปิดใช้ multi-user auth ค่าเริ่มต้น `false` |
| `AUTH_SECRET` | แนะนำ | JWT signing secret; ว่างจะสร้างอัตโนมัติใน `multi-user/_system/auth/auth_secret` |
| `AUTH_TOKEN_EXPIRE_HOURS` | ไม่ | อายุ JWT; ค่าเริ่มต้น 24 ชั่วโมง |
| `AUTH_USERNAME` / `AUTH_PASSWORD_HASH` | ไม่ | ข้อมูลสำรองสำหรับผู้ใช้คนเดียว ปล่อยว่างในโหมด multi-user |
| `NEXT_PUBLIC_AUTH_ENABLED` | อัตโนมัติ | สะท้อนจาก `AUTH_ENABLED` โดย `start_web.py` |

> ⚠️ **PocketBase mode (`POCKETBASE_URL` ตั้งค่า) ใช้ได้กับผู้ใช้คนเดียวเท่านั้น** — ไม่มีฟิลด์ `role`, ไม่มีการกรองตาม `user_id` Multi-user: ปล่อย `POCKETBASE_URL` ว่างไว้

> ⚠️ **แนะนำ single process** การเลื่อนตำแหน่งผู้ดูแลคนแรกป้องกันด้วย `threading.Lock` หลาย workers: สร้างผู้ดูแลคนแรกแบบออฟไลน์

## 🗺️ แผนงานในอนาคต

| สถานะ | หมุดหมาย |
|:---:|:---|
| 🎯 | **Authentication & Login** — รองรับหน้าเข้าสู่ระบบแบบเลือกใช้สำหรับการ deploy สาธารณะและผู้ใช้หลายคน |
| 🎯 | **Themes & Appearance** — ธีมและการปรับแต่งหน้าตา UI ที่หลากหลายขึ้น |
| 🎯 | **Interaction Improvement** — ปรับปรุง icon และรายละเอียดการโต้ตอบ |
| 🔜 | **Better Memories** — ยกระดับระบบจัดการ memory |
| 🔜 | **LightRAG Integration** — รวม [LightRAG](https://github.com/HKUDS/LightRAG) เป็น knowledge base engine ขั้นสูง |
| 🔜 | **Documentation Site** — เว็บไซต์เอกสารที่ครบถ้วนขึ้น ทั้งคู่มือ, API reference และ tutorial |

> หาก DeepTutor มีประโยชน์สำหรับคุณ [ฝากกดดาว](https://github.com/HKUDS/DeepTutor/stargazers) — มันช่วยให้เราพัฒนาต่อไปได้!

---

## 🌐 ชุมชนและระบบนิเวศ

DeepTutor สร้างขึ้นบนโครงการโอเพนซอร์สคุณภาพหลายตัว:

| โครงการ | บทบาทใน DeepTutor |
|:---|:---|
| [**nanobot**](https://github.com/HKUDS/nanobot) | เอนจินเอเจนต์น้ำหนักเบาที่ขับเคลื่อน TutorBot |
| [**LlamaIndex**](https://github.com/run-llama/llama_index) | แกนหลักสำหรับ RAG pipeline และการทำดัชนีเอกสาร |
| [**ManimCat**](https://github.com/Wing900/ManimCat) | ระบบสร้างแอนิเมชันคณิตศาสตร์สำหรับ Math Animator |

**จาก ecosystem ของ HKUDS:**

| [⚡ LightRAG](https://github.com/HKUDS/LightRAG) | [🤖 AutoAgent](https://github.com/HKUDS/AutoAgent) | [🔬 AI-Researcher](https://github.com/HKUDS/AI-Researcher) | [🧬 nanobot](https://github.com/HKUDS/nanobot) |
|:---:|:---:|:---:|:---:|
| Simple & Fast RAG | Zero-Code Agent Framework | Automated Research | Ultra-Lightweight AI Agent |


## 🤝 การมีส่วนร่วม

<div align="center">

เราหวังว่า DeepTutor จะเป็นของขวัญแก่ชุมชน 🎁

<a href="https://github.com/HKUDS/DeepTutor/graphs/contributors">
  <img src="https://contrib.rocks/image?repo=HKUDS/DeepTutor&max=999" alt="Contributors" />
</a>

</div>

อ่าน [CONTRIBUTING.md](../../CONTRIBUTING.md) สำหรับคำแนะนำเกี่ยวกับการตั้งค่าสภาพแวดล้อมสำหรับนักพัฒนา มาตรฐานโค้ด และขั้นตอนการส่ง pull request

## ⭐ ประวัติดาว

<div align="center">

<a href="https://www.star-history.com/#HKUDS/DeepTutor&type=timeline&legend=top-left">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/svg?repos=HKUDS/DeepTutor&type=timeline&theme=dark&legend=top-left" />
    <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/svg?repos=HKUDS/DeepTutor&type=timeline&legend=top-left" />
    <img alt="Star History Chart" src="https://api.star-history.com/svg?repos=HKUDS/DeepTutor&type=timeline&legend=top-left" />
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

[⭐ กดดาว](https://github.com/HKUDS/DeepTutor/stargazers) · [🐛 รายงานบั๊ก](https://github.com/HKUDS/DeepTutor/issues) · [💬 Discussions](https://github.com/HKUDS/DeepTutor/discussions)

---

เผยแพร่ภายใต้สัญญาอนุญาต [Apache License 2.0](../../LICENSE)

<p>
  <img src="https://visitor-badge.laobi.icu/badge?page_id=HKUDS.DeepTutor&style=for-the-badge&color=00d4ff" alt="Views">
</p>

</div>
