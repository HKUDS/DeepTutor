<div align="center">

<p align="center"><img src="../../assets/figs/logo/logo.png" alt="DeepTutor logo" height="56" style="vertical-align: middle;">&nbsp;<img src="../../assets/figs/logo/banner.png" alt="DeepTutor" height="48" style="vertical-align: middle;"></p>

# DeepTutor: การสอนพิเศษส่วนตัวตลอดชีวิต

<p align="center">
  <a href="https://deeptutor.info" target="_blank"><img alt="Docs — deeptutor.info" src="https://img.shields.io/badge/Docs-deeptutor.info%20%E2%86%97-0A0A0A?style=for-the-badge&labelColor=F5F5F4" height="36"></a>
</p>

<p align="center">
  <a href="https://trendshift.io/repositories/17099?utm_source=repository-badge&amp;utm_medium=badge&amp;utm_campaign=badge-repository-17099" target="_blank" rel="noopener noreferrer"><img src="https://trendshift.io/api/badge/repositories/17099" alt="HKUDS%2FDeepTutor | Trendshift" width="250" height="55"/></a>&nbsp;
  <a href="https://trendshift.io/repositories/17099?utm_source=trendshift-badge&amp;utm_medium=badge&amp;utm_campaign=badge-trendshift-17099" target="_blank" rel="noopener noreferrer"><img src="https://trendshift.io/api/badge/trendshift/repositories/17099/daily" alt="HKUDS%2FDeepTutor | Trendshift" width="250" height="55"/></a>&nbsp;
  <a href="https://trendshift.io/repositories/17099?utm_source=trendshift-badge&amp;utm_medium=badge&amp;utm_campaign=badge-trendshift-17099" target="_blank" rel="noopener noreferrer"><img src="https://trendshift.io/api/badge/trendshift/repositories/17099/weekly?language=Python" alt="HKUDS%2FDeepTutor | Trendshift" width="250" height="55"/></a>
</p>

<p align="center">
  <a href="../../README.md"><img alt="English" height="40" src="https://img.shields.io/badge/English-CDCFD4"></a>&nbsp;
  <a href="README_CN.md"><img alt="简体中文" height="40" src="https://img.shields.io/badge/简体中文-CDCFD4"></a>&nbsp;
  <a href="README_JA.md"><img alt="日本語" height="40" src="https://img.shields.io/badge/日本語-CDCFD4"></a>&nbsp;
  <a href="README_ES.md"><img alt="Español" height="40" src="https://img.shields.io/badge/Español-CDCFD4"></a>&nbsp;
  <a href="README_FR.md"><img alt="Français" height="40" src="https://img.shields.io/badge/Français-CDCFD4"></a>&nbsp;
  <a href="README_AR.md"><img alt="Arabic" height="40" src="https://img.shields.io/badge/Arabic-CDCFD4"></a>&nbsp;
  <a href="README_RU.md"><img alt="Русский" height="40" src="https://img.shields.io/badge/Русский-CDCFD4"></a>&nbsp;
  <a href="README_HI.md"><img alt="Hindi" height="40" src="https://img.shields.io/badge/Hindi-CDCFD4"></a>&nbsp;
  <a href="README_PT.md"><img alt="Português" height="40" src="https://img.shields.io/badge/Português-CDCFD4"></a>&nbsp;
  <a href="README_TH.md"><img alt="Thai" height="40" src="https://img.shields.io/badge/Thai-BCDCF7"></a>&nbsp;
  <a href="README_PL.md"><img alt="Polski" height="40" src="https://img.shields.io/badge/Polski-CDCFD4"></a>
</p>

[![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-3776AB?style=flat-square&logo=python&logoColor=white)](https://www.python.org/downloads/)
[![Next.js 16](https://img.shields.io/badge/Next.js-16-000000?style=flat-square&logo=next.js&logoColor=white)](https://nextjs.org/)
[![License](https://img.shields.io/badge/License-Apache_2.0-blue?style=flat-square)](../../LICENSE)
[![GitHub release](https://img.shields.io/github/v/release/HKUDS/DeepTutor?style=flat-square&color=brightgreen)](https://github.com/HKUDS/DeepTutor/releases)
[![arXiv](https://img.shields.io/badge/arXiv-2604.26962-b31b1b?style=flat-square&logo=arxiv&logoColor=white)](https://arxiv.org/abs/2604.26962)

[![Discord](https://img.shields.io/badge/Discord-Community-5865F2?style=flat-square&logo=discord&logoColor=white)](https://discord.gg/eRsjPgMU4t)
[![Feishu](https://img.shields.io/badge/Feishu-Group-00D4AA?style=flat-square&logo=feishu&logoColor=white)](../../Communication.md)
[![WeChat](https://img.shields.io/badge/WeChat-Group-07C160?style=flat-square&logo=wechat&logoColor=white)](https://github.com/HKUDS/DeepTutor/issues/78)

[คุณสมบัติ](#-คุณสมบัติหลัก) · [เริ่มต้น](#-เริ่มต้น) · [สำรวจ](#-สำรวจ-deeptutor) · [CLI](#️-deeptutor-cli--อินเทอร์เฟซ-agent-native) · [ระบบนิเวศ](#-ระบบนิเวศ--eduhub--ชุมชน-skills) · [ชุมชน](#-ชุมชน)

</div>

---

> 🤝 **เรายินดีรับการมีส่วนร่วมทุกรูปแบบ!** โหวตรายการ roadmap หรือเสนอรายการใหม่ที่ [`Roadmap`](https://github.com/HKUDS/DeepTutor/issues/498) และดู [คู่มือการมีส่วนร่วม](../../CONTRIBUTING.md) สำหรับกลยุทธ์ branching มาตรฐานการเขียนโค้ด และวิธีเริ่มต้น

### 📰 ข่าวสาร

- **2026-05-22** 🌐 เว็บไซต์เอกสารอย่างเป็นทางการเปิดตัวแล้วที่ [**deeptutor.info**](https://deeptutor.info/) — คู่มือ การอ้างอิง และ capability tours ทั้งหมดในที่เดียว
- **2026-04-19** 🎉 ถึง 20k stars ใน 111 วัน! ขอบคุณสำหรับการสนับสนุนที่มุ่งสู่การสอนพิเศษที่เป็นส่วนตัวและชาญฉลาดอย่างแท้จริง
- **2026-04-10** 📄 บทความของเราตอนนี้มีบน arXiv แล้ว! อ่าน [preprint](https://arxiv.org/abs/2604.26962) เพื่อเรียนรู้เกี่ยวกับการออกแบบและแนวคิดที่อยู่เบื้องหลัง DeepTutor
- **2026-02-06** 🚀 ถึง 10k stars ในเพียง 39 วัน! ขอบคุณชุมชนที่น่าเหลือเชื่ออย่างยิ่ง!
- **2026-01-01** 🎊 สวัสดีปีใหม่! เข้าร่วม [Discord](https://discord.gg/eRsjPgMU4t), [WeChat](https://github.com/HKUDS/DeepTutor/issues/78) หรือ [Discussions](https://github.com/HKUDS/DeepTutor/discussions) — มาร่วมกันกำหนดอนาคตของ DeepTutor
- **2025-12-29** 🎓 DeepTutor ได้รับการเปิดตัวอย่างเป็นทางการแล้ว!

## ✨ คุณสมบัติหลัก

DeepTutor คือ workspace การเรียนรู้แบบ agent-native ที่เชื่อมต่อการสอนพิเศษ, การแก้ปัญหา, การสร้าง quiz, การวิจัย, การสร้างภาพ และการฝึกความเชี่ยวชาญในระบบที่ขยายได้หนึ่งเดียว

- **รันไทม์เดียวสำหรับทุกโหมด** — Chat, Quiz, Research, Visualize, Solve และ Mastery Path บนลูป agent เดียวกัน คุณเปลี่ยนวัตถุประสงค์ ไม่ใช่เอ็นจิน และบริบทเดินทางไปพร้อมกับผู้เรียน
- **บริบทการเรียนรู้ที่เชื่อมต่อกัน** — ฐานความรู้, หนังสือ, ร่าง Co-Writer, สมุดบันทึก, คลังคำถาม, บุคลิกภาพ และ Memory พร้อมใช้งานในทุกเวิร์กโฟลว์ แทนที่จะอยู่ในเครื่องมือที่แยกจากกัน
- **ซับเอเจนต์และ Partners** — ปรึกษา Claude Code, Codex หรือ Partner แบบสดจากทุก turn (หรือนำเข้าบทสนทนาในอดีต) และรันเพื่อนถาวรบน IM ด้วยสมองเดียวกัน
- **ความรู้หลายเอ็นจิน** — ไลบรารี RAG แบบเวอร์ชันผ่าน LlamaIndex, PageIndex, GraphRAG, LightRAG หรือ Obsidian vault ที่เชื่อมโยง พร้อมการแยกวิเคราะห์เอกสารแบบ pluggable
- **เครื่องมือและทักษะที่ขยายได้** — เครื่องมือในตัว, เซิร์ฟเวอร์ MCP, โมเดลสร้างรูปภาพ/วิดีโอ/เสียง และทักษะชุมชนที่ติดตั้งได้จาก EduHub
- **หน่วยความจำที่ตรวจสอบได้** — การติดตาม L1, สรุปพื้นผิว L2 และการสังเคราะห์ L3 ทำให้การปรับแต่งส่วนบุคคลมองเห็นได้และแก้ไขได้ พร้อม Memory Graph ที่ติดตามทุกการอ้างสิทธิ์กลับไปสู่หลักฐาน

---

## 🚀 เริ่มต้น

DeepTutor มีเส้นทางการติดตั้งสี่เส้นทาง ทั้งหมดแชร์ layout workspace เดียว: การตั้งค่าอยู่ใน `data/user/settings/` ภายใต้ไดเร็กทอรีที่คุณเปิดตัว (หรือภายใต้ `DEEPTUTOR_HOME` / `deeptutor start --home` หากคุณตั้งค่าไว้อย่างชัดเจน) สำหรับแอปเต็มรูปแบบ ขั้นตอนที่แนะนำคือ **เลือกไดเร็กทอรี workspace → ติดตั้ง → `deeptutor init` → `deeptutor start`**

<details>
<summary><b>ตัวเลือกที่ 1 — ติดตั้งจาก PyPI</b> · แอป Web local แบบเต็มรูปแบบ + CLI ไม่ต้องโคลน</summary>

แอป Web local แบบเต็มรูปแบบ + CLI ไม่ต้องโคลน ต้องการ **Python 3.11+** และ runtime **Node.js 20+** บน PATH (เซิร์ฟเวอร์ standalone Next.js ที่แพ็คไว้จะถูกเปิดตัวโดย `deeptutor start`)

```bash
mkdir -p my-deeptutor && cd my-deeptutor
pip install -U deeptutor
deeptutor init     # ขอพอร์ต + LLM provider + embedding แบบเสริม
deeptutor start    # เริ่ม backend + frontend; เปิด terminal ไว้
```

`deeptutor init` จะขอพอร์ต backend (ค่าเริ่มต้น `8001`), พอร์ต frontend (ค่าเริ่มต้น `3782`), LLM provider / base URL / API key / model และ embedding provider แบบเสริมสำหรับ Knowledge Base / RAG

หลังจาก `deeptutor start` ให้เปิด URL ของ frontend ที่พิมพ์ใน terminal — ค่าเริ่มต้น [http://127.0.0.1:3782](http://127.0.0.1:3782) กด `Ctrl+C` ใน terminal นั้นเพื่อหยุดทั้ง backend และ frontend การข้าม `deeptutor init` ก็ใช้ได้สำหรับการทดลองอย่างรวดเร็ว แอปจะบูตด้วยพอร์ตเริ่มต้นและการตั้งค่า model ว่าง กำหนดค่าในภายหลังใน **Settings → Models**

</details>

<details>
<summary><b>ตัวเลือกที่ 2 — ติดตั้งจากซอร์สโค้ด</b> · พัฒนาจาก checkout</summary>

สำหรับการพัฒนาจาก checkout ใช้ **Python 3.11+** และ **Node.js 22 LTS** เพื่อให้ตรงกับ CI และ Docker

```bash
git clone https://github.com/HKUDS/DeepTutor.git
cd DeepTutor

# สร้าง venv (macOS/Linux). Windows PowerShell:
#   py -3.11 -m venv .venv ; .\.venv\Scripts\Activate.ps1
python3 -m venv .venv && source .venv/bin/activate
python -m pip install --upgrade pip

# ติดตั้ง backend + frontend deps
python -m pip install -e .
( cd web && npm ci --legacy-peer-deps )

deeptutor init
deeptutor start
```

การติดตั้งจากซอร์สจะรัน Next.js ในโหมด dev กับไดเร็กทอรี `web/` ในเครื่อง ทุกอย่างอื่น (layout ของ config, พอร์ต, หยุดด้วย `Ctrl+C`) ตรงกับตัวเลือกที่ 1

<details>
<summary><b>สภาพแวดล้อม Conda</b> (แทน <code>venv</code>)</summary>

```bash
conda create -n deeptutor python=3.11
conda activate deeptutor
python -m pip install --upgrade pip
```

</details>

<details>
<summary><b>ส่วนเสริมการติดตั้ง</b> — dev / partners / matrix / math-animator</summary>

```bash
pip install -e ".[dev]"             # เครื่องมือ tests/lint
pip install -e ".[partners]"        # SDKs ช่องทาง IM ของ Partners + MCP client
pip install -e ".[matrix]"          # ช่องทาง Matrix โดยไม่มี E2EE/libolm
pip install -e ".[matrix-e2e]"      # Matrix E2EE; ต้องการ libolm
pip install -e ".[math-animator]"   # Manim addon; ต้องการ LaTeX/ffmpeg/system libs
```

</details>

<details>
<summary><b>การปรับแก้ dependency ของ frontend และการแก้ปัญหาเซิร์ฟเวอร์ dev</b></summary>

**การเปลี่ยน dependency ของ frontend:** รัน `npm install --legacy-peer-deps` เพื่อรีเฟรช `web/package-lock.json` จากนั้น commit ทั้ง `web/package.json` และ `web/package-lock.json`

**เซิร์ฟเวอร์ dev ค้าง:** หาก `deeptutor start` รายงาน frontend ที่มีอยู่แต่ไม่ตอบสนอง ให้หยุด PID ที่พิมพ์ออกมา หากไม่มีกระบวนการ Next.js จริง ๆ ที่รันอยู่ ไฟล์ lock จะล้าสมัย — ลบออกแล้วลองใหม่:

```bash
rm -f web/.next/dev/lock web/.next/lock
deeptutor start
```

</details>

</details>

<details>
<summary><b>ตัวเลือกที่ 3 — Docker</b> · container เดียวที่ครบในตัว</summary>

Container เดียวสำหรับแอป Web แบบเต็มรูปแบบ ภาพบน GitHub Container Registry:

- `ghcr.io/hkuds/deeptutor:latest` — stable release
- `ghcr.io/hkuds/deeptutor:pre` — pre-release เมื่อพร้อมใช้งาน

> ดู [CONTAINERIZATION.md](../../CONTAINERIZATION.md) สำหรับการปรับใช้ podman/rootless/read-only-rootfs และคู่มือต่อการติดตั้งแบบครบถ้วน

```bash
docker run --rm --name deeptutor \
  -p 127.0.0.1:3782:3782 \
  -v deeptutor-data:/app/data \
  ghcr.io/hkuds/deeptutor:latest
```

> **จำเป็นต้อง publish เฉพาะ `3782`** เบราว์เซอร์คุยกับ frontend origin เท่านั้น; Next.js middleware (`web/proxy.ts`) ส่งต่อ `/api/*` และ `/ws/*` ไปยัง FastAPI backend **ภายใน container** การ publish `8001` (`-p 127.0.0.1:8001:8001`) เป็นทางเลือก — มีประโยชน์เฉพาะเมื่อต้องการเรียก API โดยตรงด้วย curl หรือ scripts

เปิด [http://127.0.0.1:3782](http://127.0.0.1:3782) Container จะสร้าง `/app/data/user/settings/*.json` เมื่อบูตครั้งแรก กำหนดค่า model providers จากหน้า Web Settings Config, API keys, logs, ไฟล์ workspace, memory และ knowledge bases จะคงอยู่ใน volume `deeptutor-data`

- **พอร์ต host ที่แตกต่าง:** เปลี่ยนด้านซ้ายของการ mapping `-p host:container` แต่ละอัน (เช่น `-p 127.0.0.1:8088:3782`) หากคุณเปลี่ยนพอร์ตฝั่ง container ใน `/app/data/user/settings/system.json` ให้รีสตาร์ทและอัปเดตด้านขวาของการ mapping แต่ละอันให้ตรงกัน
- **แบบ detached:** เพิ่ม `-d` จากนั้น `docker logs -f deeptutor` เพื่อติดตาม, `docker stop deeptutor` เพื่อหยุด, `docker rm deeptutor` ก่อนนำชื่อมาใช้ซ้ำ Volume `deeptutor-data` จะเก็บการตั้งค่าและ workspace ของคุณข้ามการรีสตาร์ท

**Remote Docker / reverse proxy:** เบราว์เซอร์คุยกับ frontend origin (`:3782`) เท่านั้น; Next.js middleware ภายใน container ส่งต่อ `/api/*` และ `/ws/*` ไปยัง backend server-side สำหรับกรณี single-container ทั่วไปคุณไม่ต้องกำหนดค่า API base เลย — แค่ชี้ reverse proxy / TLS terminator ไปที่ `:3782` คุณต้องการ API base เฉพาะสำหรับ **split deployment** (backend ใน container/host แยกต่างหาก): ตั้งค่า `next_public_api_base` ใน `data/user/settings/system.json` เป็นที่อยู่ in-network ที่ frontend server ใช้เข้าถึง backend (อ่านฝั่ง server ไม่ส่งไปยังเบราว์เซอร์)

```json
{
  "next_public_api_base": "http://backend:8001"
}
```

`next_public_api_base_external` (และ alias `public_api_base`) ยอมรับเป็น fallback ลำดับความสำคัญต่ำกว่า CORS ใช้ frontend **origins** ไม่ใช่ API URLs เมื่อปิด auth DeepTutor อนุญาต HTTP/HTTPS browser origins ปกติโดยค่าเริ่มต้น เมื่อเปิด auth ให้เพิ่ม frontend origins ที่แน่นอน:

```json
{
  "cors_origins": ["https://deeptutor.example.com"]
}
```

<details>
<summary><b>การเชื่อมต่อกับ Ollama / LM Studio / llama.cpp / vLLM / Lemonade บน host</b></summary>

ภายใน Docker, `localhost` คือ container เอง ไม่ใช่เครื่อง host ของคุณ ในการเข้าถึง model service ที่รันบน host ให้ใช้ host gateway (แนะนำ):

```bash
docker run --rm --name deeptutor \
  -p 127.0.0.1:3782:3782 -p 127.0.0.1:8001:8001 \
  --add-host=host.docker.internal:host-gateway \
  -v deeptutor-data:/app/data \
  ghcr.io/hkuds/deeptutor:latest
```

จากนั้นใน **Settings → Models** ชี้ Base URL ของ provider ไปที่ `host.docker.internal`:

- Ollama LLM: `http://host.docker.internal:11434/v1`
- Ollama embedding: `http://host.docker.internal:11434/api/embed`
- LM Studio: `http://host.docker.internal:1234/v1`
- llama.cpp: `http://host.docker.internal:8080/v1`
- Lemonade: `http://host.docker.internal:13305/api/v1`

Docker Desktop (macOS/Windows) มักจะ resolve `host.docker.internal` ได้โดยไม่ต้องใช้ `--add-host` บน Linux ตัวเลือกนี้คือวิธีที่ portable ในการสร้าง hostname บน Docker Engine สมัยใหม่

**ทางเลือกบน Linux — host networking:** เพิ่ม `--network=host` และลบ flags `-p` ออก Container จะแชร์ network ของ host โดยตรง เปิด [http://127.0.0.1:3782](http://127.0.0.1:3782) (หรือ `frontend_port` ใน `system.json`) และ services ของ host สามารถเข้าถึงได้ด้วย localhost URLs ปกติ เช่น `http://127.0.0.1:11434/v1` โปรดทราบว่า host networking จะเปิดเผยพอร์ต container โดยตรงบน host และอาจขัดแย้งกับ services ที่มีอยู่ — หากต้องการเก็บไว้บน loopback ให้ตั้ง `BACKEND_HOST=127.0.0.1` และ `FRONTEND_HOST=127.0.0.1` (ดู [CONTAINERIZATION.md](../../CONTAINERIZATION.md))

</details>

</details>

<details>
<summary><b>ตัวเลือกที่ 4 — CLI เท่านั้น</b> · ไม่มี Web UI จาก source checkout</summary>

เมื่อคุณไม่ต้องการ Web UI แพ็คเกจ CLI-only ติดตั้งจาก source checkout ไม่ใช่จาก PyPI

```bash
git clone https://github.com/HKUDS/DeepTutor.git
cd DeepTutor

# สร้าง venv (macOS/Linux). Windows PowerShell:
#   py -3.11 -m venv .venv-cli ; .\.venv-cli\Scripts\Activate.ps1
python3 -m venv .venv-cli && source .venv-cli/bin/activate
python -m pip install --upgrade pip

python -m pip install -e ./packaging/deeptutor-cli
deeptutor init --cli
deeptutor chat
```

`deeptutor init --cli` แชร์ layout `data/user/settings/` เดียวกับแอปเต็มรูปแบบ แต่ข้ามการขอพอร์ต backend/frontend และตั้งค่า embeddings เป็น **ปิด** โดยค่าเริ่มต้น (เลือก `Yes` หากคุณวางแผนใช้ `deeptutor kb …` หรือเครื่องมือ RAG) ยังคงเขียน layout runtime ที่ครบถ้วน (`system.json`, `auth.json`, `integrations.json`, `model_catalog.json`, `main.yaml`, `agents.yaml`) และยังคงขอ LLM provider และ model ที่ใช้งานอยู่

<details>
<summary><b>คำสั่งทั่วไป</b></summary>

```bash
deeptutor chat                                          # interactive REPL
deeptutor chat --capability deep_solve --tool rag --kb my-kb
deeptutor run chat "Explain Fourier transform"
deeptutor run deep_solve "Solve x^2 = 4" --tool rag --kb my-kb
deeptutor kb create my-kb --doc textbook.pdf
deeptutor memory show
deeptutor config show
```

</details>

แพ็คเกจ `deeptutor-cli` ในเครื่องไม่มี Web assets หรือ server dependencies เก็บ source checkout ไว้ — การติดตั้งแบบ editable ชี้ไปที่มัน หากต้องการเพิ่มแอป Web ในภายหลัง ให้ติดตั้งแพ็คเกจ PyPI (ตัวเลือกที่ 1) และรัน `deeptutor init` + `deeptutor start` จาก workspace เดียวกัน

</details>

<details>
<summary><b>Sandbox การรันโค้ด (office skills)</b> · รันโค้ดที่ model สร้างสำหรับ docx / pdf / pptx / xlsx</summary>

office skills ที่ติดตั้งมา — **docx / pdf / pptx / xlsx** — ทำงานโดยให้ model เขียน Python script สั้น ๆ (`python-docx`, `reportlab`, `openpyxl`, …), รันผ่านเครื่องมือ `exec` / `code_execution` และส่งคืน URL ดาวน์โหลด เครื่องมือเหล่านี้จะ mount เมื่อ sandbox backend ทำงานอยู่ ซึ่งเป็น **ค่าเริ่มต้น** ในทุกรูปแบบการปรับใช้:

- **Local (ตัวเลือกที่ 1 / 2) และ Docker (ตัวเลือกที่ 3, single container):** sandbox ย่อย subprocess ที่จำกัดจะรันโค้ดของ model (บน host ในเครื่อง หรือภายใน container ภายใต้ Docker — container เป็น isolation boundary ของมันเอง)
- **docker-compose:** แทนที่จะเป็นเช่นนั้น จะ route ไปยัง **runner sidecar** ที่มีสิทธิ์น้อยที่สุดและมีความปลอดภัยสูง (`Dockerfile.runner`) ผ่าน `DEEPTUTOR_SANDBOX_RUNNER_URL` — ท่าทีที่แข็งแกร่งที่สุด และถูกเลือกโดยอัตโนมัติเมื่อมี

sandbox ย่อย subprocess ถูกควบคุมโดยการตั้งค่า `sandbox_allow_subprocess` ใน `data/user/settings/system.json` (ค่าเริ่มต้น `true`) การรันโค้ดที่ model สร้างบน host ของคุณเป็นการตัดสินใจด้านความน่าเชื่อถือจริง ๆ — ตั้งเป็น `false` (หรือ export `DEEPTUTOR_SANDBOX_ALLOW_SUBPROCESS=0`) เพื่อปิดการรันฝั่ง host โดยแลกกับ office skills ที่ไม่สามารถสร้างไฟล์ได้อีกต่อไป

</details>

<details>
<summary><b>เอกสารอ้างอิงการตั้งค่า</b> — ไฟล์การกำหนดค่าภายใต้ <code>data/user/settings/</code> (JSON/YAML)</summary>

ทุกอย่างภายใต้ `data/user/settings/` เป็น JSON/YAML ธรรมดา หน้า **Settings** ในเบราว์เซอร์คือโปรแกรมแก้ไขที่แนะนำ

| ไฟล์ | วัตถุประสงค์ |
|:---|:---|
| `model_catalog.json` | โปรไฟล์ provider LLM, embedding และ search; API keys; models ที่ใช้งานอยู่ |
| `system.json` | พอร์ต backend/frontend, public API base, CORS, SSL verification, ไดเร็กทอรีไฟล์แนบ |
| `auth.json` | สวิตช์ auth แบบเสริม, ชื่อผู้ใช้, password hash, การตั้งค่า token/cookie |
| `integrations.json` | การตั้งค่า PocketBase แบบเสริมและการรวม sidecar |
| `interface.json` | ความชอบภาษา / ธีม / แถบด้านข้างของ UI |
| `main.yaml` | ค่าเริ่มต้นพฤติกรรม runtime และการ inject path |
| `agents.yaml` | การตั้งค่า temperature และ token ของ capability/tool |

`.env` ที่ root ของโปรเจกต์จะ **ไม่** ถูกอ่านเป็นไฟล์ config ของแอปพลิเคชัน สำหรับการตั้งค่า model เบื้องต้น เปิด **Settings → Models** เพิ่มโปรไฟล์ LLM (Base URL / API key / ชื่อ model) และบันทึก เพิ่มโปรไฟล์ embedding เฉพาะเมื่อคุณวางแผนใช้ Knowledge Base / RAG features

</details>

## 📖 สำรวจ DeepTutor

เริ่มต้นด้วยพื้นผิวหลักที่คุณจะใช้ทุกวัน: Chat, Partners, My Agents, Co-Writer, Book, Knowledge Center, Learning Space, Memory และ Settings จากนั้นจะครอบคลุมการปรับใช้ Multi-User สำหรับ workspace แบบแชร์และแยกส่วน

<div align="center">
<img src="../../assets/figs/web-1.4.6+/OVERVIEW.png" alt="DeepTutor home — workspace Chat พร้อมทุกพื้นผิวใน sidebar" width="900">
</div>

<details>
<summary><b>🏗️ สถาปัตยกรรมระบบ</b></summary>

<div align="center">
<img src="../../assets/figs/system/system%20architecture.png" alt="สถาปัตยกรรมระบบ DeepTutor" width="900">
</div>

</details>

<details>
<summary><b>💬 Chat — ลูป Agent ที่คุณใช้จริง</b></summary>

Chat คือความสามารถเริ่มต้นและสถานที่ที่งานส่วนใหญ่เริ่มต้น thread เดียวสามารถพูดคุยตามปกติ, เรียกเครื่องมือ, อ้างอิงใน knowledge bases ที่เลือก, อ่านไฟล์แนบ, สร้างรูปภาพ, ปรึกษา subagents, เขียน notebook records และดำเนินการต่อด้วยบริบทเดียวกันตลอด turns

<div align="center">
<img src="../../assets/figs/web-1.4.6+/home/00-overview.png" alt="DeepTutor workspace chat" width="900">
</div>

ลูปนั้นเรียบง่ายโดยเจตนา: model คิดในรอบ ๆ, เรียกเครื่องมือเมื่อมีประโยชน์, สังเกตผลลัพธ์ และจบด้วยข้อความที่ไม่มีเครื่องมือ `ask_user` เป็นพิเศษ — แทนที่จะเดา agent สามารถหยุด turn, ถามคำถามชี้แจงที่มีโครงสร้าง และดำเนินการต่อเมื่อคุณตอบ

<div align="center">
<img src="../../assets/figs/system/chat-agent-loop.png" alt="DeepTutor chat agent loop" width="900">
</div>

เครื่องมือที่ผู้ใช้สลับได้ ได้แก่ `brainstorm`, `web_search`, `paper_search`, `reason`, และ `geogebra_analysis` — รวมถึง `imagegen` และ `videogen` เมื่อคุณกำหนดค่าโมเดลสร้างที่ตรงกัน เครื่องมือตามบริบทเช่น `rag`, `read_source`, `read_memory`, `write_memory`, `read_skill`, `load_tools`, `exec`, `web_fetch`, `ask_user`, `list_notebook`, `write_note`, `github`, และ `consult_subagent` จะ mount อัตโนมัติเมื่อ turn มีบริบทที่ถูกต้อง

บริบทมีสองประเภท: **sticky session context** (subagent, knowledge bases, persona, model, voice) อยู่บน composer toolbar และคงอยู่ตลอด turns; **one-time references** (ไฟล์, ประวัติ chat, หนังสือ, notebooks, question bank, imported agents) มาจากเมนู `+` สำหรับ turn เดียว

Chat ยังเป็นจุดเปิดตัวสำหรับความสามารถที่ลึกกว่า: **Quiz** สำหรับการสร้างคำถาม, **Research** สำหรับรายงานที่อ้างอิง, **Visualize** สำหรับ charts / diagrams / animations และ — ภายใต้ *More Capabilities* — **Solve** สำหรับการให้เหตุผลแบบมีขั้นตอน และ **Mastery Path** สำหรับ learning-plan flows

</details>

<details>
<summary><b>🤝 Partner — เพื่อนถาวรบนสมองเดียวกัน</b></summary>

<div align="center">
<img src="../../assets/figs/web-1.4.6+/partners/00-partners%20overview.png" alt="DeepTutor workspace partners" width="900">
</div>

Partners คือเพื่อนถาวรที่มี soul, นโยบาย model, ห้องสมุด, memory และช่องทางของตัวเอง พวกเขาไม่ใช่เอ็นจิน bot แยกต่างหาก: ทุกข้อความ web หรือ IM ที่เข้ามาจะกลายเป็น turn ปกติของ `ChatOrchestrator` ภายใน workspace ที่มีขอบเขต partner partner คือ "chat ที่มีบุคลิกภาพและหมายเลขโทรศัพท์"

<div align="center">
<img src="../../assets/figs/system/partners-architecture.png" alt="สถาปัตยกรรม partners DeepTutor" width="900">
</div>

แต่ละ partner มี `SOUL.md`, การเลือก model, ช่องทาง, นโยบายเครื่องมือ และห้องสมุดที่กำหนด Knowledge bases, skills และ notebooks ถูกคัดลอกไปยัง `data/partners/<id>/workspace/` ดังนั้น RAG, skill, notebook และเครื่องมือ memory เดิมทำงานได้โดยไม่มีกรณีพิเศษ partner อ่าน memory ของเจ้าของแต่เขียนเฉพาะของตัวเอง

<div align="center">
<img src="../../assets/figs/web-1.4.6+/partners/02-IM%20config%20for%20each%20partner.png" alt="การกำหนดค่าช่องทาง IM ต่อ partner" width="900">
</div>

ชั้น channel ที่ขับเคลื่อนด้วย schema สามารถเชื่อมต่อกับแพลตฟอร์ม IM ได้แก่ Feishu, Telegram, Slack, Discord, DingTalk, QQ/NapCat, WeCom, WhatsApp, Zulip, Mattermost, Matrix, Mochat และ Microsoft Teams ขึ้นอยู่กับ extras ที่ติดตั้งและ credentials ที่กำหนดค่า partner ยังสามารถเชื่อมต่อเป็น subagent และปรึกษาได้จาก chat turn ปกติ — ดู **My Agents** ด้านล่าง

</details>

<details>
<summary><b>🧑‍🚀 My Agents — ปรึกษาและนำเข้า Agents อื่น ๆ</b></summary>

<div align="center">
<img src="../../assets/figs/web-1.4.6+/myagents/00-overview.png" alt="DeepTutor workspace My Agents" width="900">
</div>

My Agents เปลี่ยน agent อื่น ๆ ให้กลายเป็นบริบทสำหรับ DeepTutor และทำสองสิ่งที่แตกต่างกัน **เชื่อมต่อ agent แบบสด** — Claude Code หรือ Codex CLI บนเครื่องของคุณ หรือหนึ่งใน Partners ของคุณ — และปรึกษามันจากภายใน chat turn: DeepTutor จริง ๆ *รัน* agent อื่นและ stream งานเข้าสู่แผง Activity ผ่านเครื่องมือ `consult_subagent` เลือกด้วย Agent chip (หรือพิมพ์ `@`) และตั้งค่าจำนวนรอบที่การปรึกษาอาจทำได้

<div align="center">
<img src="../../assets/figs/web-1.4.6+/home/08-subagent%20demo%20with%20claude%20code.png" alt="การปรึกษา subagent Claude Code แบบสด" width="900">
</div>

**นำเข้าบทสนทนาในอดีต** — นำประวัติ Claude Code และ Codex ที่มีอยู่ของคุณมาเป็น agent ที่มีชื่อ, ค้นหาได้ และสามารถดำเนินการต่อได้ เลือกวันที่จะนำเข้า การรีเฟรชจะ re-sync ข้อมูล อ้างอิงบทสนทนาที่นำเข้าจาก chat turn ใด ๆ ผ่าน `+` → My Agents และ DeepTutor จะอ่านมันเป็น transcript ของบุคคลที่สาม — มันยังคงเป็นบทสนทนา *ของพวกเขา* ไม่ใช่เสียงของ DeepTutor เอง

</details>

<details>
<summary><b>✍️ Co-Writer — การร่าง Markdown ที่รับรู้การเลือก</b></summary>

<div align="center">
<img src="../../assets/figs/web-1.4.6+/co-writer/00-overview.png" alt="DeepTutor workspace Co-Writer" width="900">
</div>

Co-Writer คือ workspace Markdown แบบ split-view สำหรับรายงาน, บทเรียน, บันทึก และ artifacts การเรียนรู้แบบยาว เอกสารบันทึกอัตโนมัติและแสดงตัวอย่างสด (คณิตศาสตร์ KaTeX, diagram fences) และสามารถบันทึกกลับเข้า notebooks เมื่อร่างกลายเป็นบริบทที่นำมาใช้ซ้ำได้

<div align="center">
<img src="../../assets/figs/web-1.4.6+/co-writer/01-edit%20panel.png" alt="Co-Writer editor พร้อม live preview" width="900">
</div>

แนวคิดหลักคือ **การแก้ไขแบบผ่าตัด**: เลือกช่วงและขอให้ DeepTutor เขียนใหม่, ขยาย หรือย่อ agent การแก้ไขสามารถอ้างอิงใน knowledge base หรือหลักฐานเว็บ, เก็บ trace ของ tool calls และแสดงทุกการเปลี่ยนแปลงเป็น accept/reject diff — ดังนั้นไม่มีอะไรลงจนกว่าคุณจะอนุมัติ

</details>

<details>
<summary><b>📖 Book — หนังสือมีชีวิตจากเนื้อหาของคุณ</b></summary>

<div align="center">
<img src="../../assets/figs/web-1.4.6+/book/00-book_overview.png" alt="DeepTutor book library" width="900">
</div>

Book แปลงแหล่งที่มาที่เลือกให้เป็น **หนังสือมีชีวิต** แบบโต้ตอบ — ไม่ใช่ PDF แบบคงที่ แต่เป็นสภาพแวดล้อมการอ่านที่สร้างจาก typed blocks หนังสือสามารถเริ่มจาก knowledge bases, notebooks, question banks หรือประวัติ chat; ขั้นตอนการสร้างจะเสนอ outline บทก่อนที่จะสร้างเนื้อหา ดังนั้นคุณจะตรวจสอบรูปร่างแทนที่จะยอมรับ output แบบ one-shot ที่มองไม่เห็น

<p align="center">
<img src="../../assets/figs/web-1.4.6+/book/01-book-demo-quiz%20card.png" alt="Book quiz block" width="31%">
&nbsp;
<img src="../../assets/figs/web-1.4.6+/book/02-book-demo-manim%20video.png" alt="Book Manim animation block" width="31%">
&nbsp;
<img src="../../assets/figs/web-1.4.6+/book/03-book-demo%20interactive%20module.png" alt="Book interactive widget block" width="31%">
</p>

แต่ละบทคอมไพล์เป็น typed blocks — text, callouts, quizzes, flash cards, timelines, code, figures, interactive HTML, animations, concept graphs, deep dives และ user notes — และทุกหน้ามี Page Chat ของตัวเอง Blocks สามารถแก้ไขได้: แทรก, ย้าย, สร้างใหม่ หรือเปลี่ยนประเภทของ block โดยไม่ต้องเขียนบทใหม่ คำสั่ง maintenance เช่น `deeptutor book health` และ `deeptutor book refresh-fingerprints` ช่วยตรวจจับว่าเมื่อใดที่ความรู้ต้นทางเปลี่ยนแปลงไปจากหน้าที่คอมไพล์แล้ว

</details>

<details>
<summary><b>📚 Knowledge Center — ไลบรารี RAG หลายเอ็นจิน</b></summary>

<div align="center">
<img src="../../assets/figs/web-1.4.6+/knowledge/00-overview.png" alt="DeepTutor Knowledge Center" width="900">
</div>

Knowledge bases คือคอลเลกชันเอกสารที่อยู่เบื้องหลัง RAG — รองรับ Chat turns, Co-Writer edits, Book generation และบทสนทนา Partner สิ่งที่โดดเด่นคือ **การเลือกเอ็นจิน retrieval**: **LlamaIndex** (ค่าเริ่มต้น, local vector + BM25), **PageIndex** (hosted, reasoning retrieval พร้อม page-level citations), **GraphRAG** และ **LightRAG** (knowledge-graph retrieval), **LightRAG Server** (retrieval ที่ offload ไปยัง LightRAG instance ภายนอกที่คุณเชื่อมต่อผ่าน HTTP) หรือ **Obsidian** vault ที่เชื่อมโยง tutor อ่านและเขียนในที่ KB แต่ละอันถูกผูกกับเอ็นจินหนึ่ง

<div align="center">
<img src="../../assets/figs/web-1.4.6+/knowledge/01-create%20knowledge%20base.png" alt="สร้าง knowledge base" width="900">
</div>

เมื่อสร้าง KB คุณ **สร้างใหม่** (อัพโหลดเอกสารและสร้าง index ใหม่) หรือ **เชื่อมโยงที่มีอยู่** (นำ index ที่สร้างไว้มาใช้ซ้ำ อ่านในที่โดยไม่ต้อง re-index) การ re-indexing จะเขียน directory `version-N` ใหม่และเก็บอันก่อนหน้าไว้ ดังนั้น index ที่ทำงานอยู่จะไม่ถูกทำลายระหว่างการสร้างใหม่ การแยกวิเคราะห์เอกสาร — Text-only, MinerU, Docling, markitdown หรือ PyMuPDF4LLM — ถูกเลือกใน **Settings → Knowledge Base** โดยการดาวน์โหลด local model ปิดโดยค่าเริ่มต้น CLI ครอบคลุม lifecycle ด้วย `deeptutor kb list`, `info`, `create`, `add`, `search`, `set-default` และ `delete`

</details>

<details>
<summary><b>🌐 Learning Space — Skills, Personas และบริบทที่นำมาใช้ซ้ำได้</b></summary>

<div align="center">
<img src="../../assets/figs/web-1.4.6+/learning-space/00-overview.png" alt="DeepTutor Learning Space hub" width="900">
</div>

Learning Space คือชั้น library และ personalization — ที่ซึ่งสิ่งที่คงอยู่ถาวรอาศัยอยู่ **Conversations & Materials** เก็บประวัติ chat, notebooks และ question bank (แต่ละคำถามที่บันทึกเก็บคำตอบของคุณ, คำตอบอ้างอิง และคำอธิบาย) **Personalization** เก็บ mastery paths, personas (พฤติกรรมที่ตั้งค่าล่วงหน้าเช่น *peer*, *research-assistant*, *teacher*) และ skills (`SKILL.md` playbooks ที่ model อ่านตามต้องการ) ทุกอย่างที่นี่สามารถนำมาใช้ซ้ำได้จาก Chat, Partners, Co-Writer และ Book

<div align="center">
<img src="../../assets/figs/web-1.4.6+/learning-space/07-%20download%20skills%20from%20eduhub.png" alt="นำเข้า skills จาก EduHub" width="900">
</div>

คุณไม่จำเป็นต้องเขียน skill ทุกอันเอง — **นำเข้าจาก EduHub** จะเรียกดู catalog ชุมชนและดาวน์โหลด skill ตรงเข้า library ผ่านประตูความปลอดภัย (ดู [ระบบนิเวศ](#-ระบบนิเวศ--eduhub--ชุมชน-skills))

</details>

<details>
<summary><b>🧠 Memory — การปรับแต่งส่วนบุคคลที่ตรวจสอบได้</b></summary>

<div align="center">
<img src="../../assets/figs/web-1.4.6+/memory/00-overview.png" alt="DeepTutor memory overview" width="900">
</div>

Memory คือระบบไฟล์สามชั้นที่คุณอ่าน, จัดการ และตรวจสอบได้ — โดยเจตนาไม่ใช่ vector store ที่ซ่อนอยู่ **L1** คือ workspace mirror พร้อม append-only event trace (`trace/<surface>/<date>.jsonl`); **L2** คือข้อเท็จจริงที่จัดการต่อพื้นผิว (`L2/<surface>.md`); **L3** คือการสังเคราะห์ข้ามพื้นผิว (`L3/<profile|recent|scope|preferences>.md`) เนื่องจาก L2 อ้างอิง L1 และ L3 อ้างอิง L2 ไม่มีอะไรในโปรไฟล์ของคุณที่ตรวจสอบไม่ได้

<div align="center">
<img src="../../assets/figs/web-1.4.6+/memory/01-3%20layer%20memory%20graph.png" alt="DeepTutor memory graph" width="900">
</div>

Memory Graph แสดงพีระมิดทั้งหมด — การสังเคราะห์ L3 ที่ศูนย์กลาง, L2 ในวงกลางกลาง, L1 traces ด้านนอก — เพื่อให้คุณติดตามการอ้างสิทธิ์ที่สังเคราะห์ใด ๆ กลับไปสู่เหตุการณ์ดิบที่แน่นอน Memory ถูกติดตามใน surfaces: `chat`, `notebook`, `quiz`, `kb`, `book`, partner และ `cowriter`; งบประมาณ Update / Audit / Dedup ของ consolidator ปรับได้ใน **Settings → Memory**

</details>

<details>
<summary><b>⚙️ Settings — Control Plane เดียว</b></summary>

<div align="center">
<img src="../../assets/figs/web-1.4.6+/settings/00-setting%20overview.png" alt="DeepTutor settings hub" width="900">
</div>

Settings คือ control plane การดำเนินงาน พร้อม live status strip (Backend, LLM, Embedding, Search) และหนึ่งการ์ดต่อพื้นที่: **Appearance** (ธีม + ภาษา UI), **Network** (API base, ports, CORS), **Models** (LLM, Embedding, Search, Text-to-Speech, Speech-to-Text, Image Generation, Video Generation), **Knowledge Base** (เอ็นจินการแยกวิเคราะห์เอกสาร), **Chat** (เครื่องมือ, MCP servers, พารามิเตอร์ต่อความสามารถ), **Partners & Agents** (subagents ที่คุณปรึกษาได้จาก turn) และ **Memory** (งบประมาณของ consolidator)

<div align="center">
<img src="../../assets/figs/web-1.4.6+/settings/01-appearance%20settings.png" alt="DeepTutor appearance settings and themes" width="900">
</div>

ส่วนส่วนใหญ่ใช้ draft-and-apply flow เพื่อให้คุณทดสอบ provider ก่อนยืนยัน ธีมสี่แบบมาในกล่อง — Default, Cream, Dark และ Glass ไฟล์ `.env` ที่ root ของโปรเจกต์ถูกเพิกเฉยโดยเจตนา; การกำหนดค่า runtime อยู่ใน `data/user/settings/*.json` เว้นแต่ `DEEPTUTOR_HOME` หรือ `deeptutor start --home` จะชี้แอปไปที่อื่น

</details>

<details>
<summary><b>👥 Multi-User — การปรับใช้แบบแชร์</b> · auth แบบเสริม, workspace ต่อผู้ใช้แบบแยกส่วน</summary>

การยืนยันตัวตน **ปิดอยู่โดยค่าเริ่มต้น** — DeepTutor ทำงานแบบผู้ใช้คนเดียว เปิดใช้งานและ tree `data/` หนึ่งจะโฮสต์ workspace ของ admin, workspace ต่อผู้ใช้แบบแยกส่วน และ workspace ของ partner ไว้ด้วยกัน:

```text
data/
├── user/                    # Workspace ของ Admin + การตั้งค่าทั่วไป
├── users/<uid>/             # ขอบเขตต่อผู้ใช้: ประวัติ chat, memory, notebooks, KBs
├── partners/<id>/workspace/ # ขอบเขต partner (synthetic-user)
└── system/                  # auth/users.json · grants/<uid>.json · audit/usage.jsonl
```

**ผู้ใช้คนแรกที่ลงทะเบียนจะกลายเป็น admin** และเป็นเจ้าของ model catalogs, provider credentials, shared knowledge bases, skills และ per-user grants ทุกคนอื่นจะได้รับ workspace แบบแยกส่วนและหน้า Settings ที่ถูก redact — models, KBs และ skills ที่ admin กำหนดจะแสดงเป็นตัวเลือก scoped แบบอ่านอย่างเดียว ไม่ใช่ API keys ดิบ

**เปิดใช้งาน:** เปิด auth ใน `data/user/settings/auth.json`, รีสตาร์ท `deeptutor start`, ลงทะเบียน admin คนแรกที่ `/register` จากนั้นเพิ่มผู้ใช้จาก `/admin/users` และกำหนด models, KBs, skills, Partners, นโยบาย tool/MCP และสิทธิ์การรันโค้ดผ่าน grants

> PocketBase ยังคงเป็น integration สำหรับผู้ใช้คนเดียว — เว้น `integrations.pocketbase_url` ว่างสำหรับการปรับใช้ multi-user เว้นแต่คุณจะเชื่อมต่อ user store ภายนอก

</details>

## ⌨️ DeepTutor CLI — อินเทอร์เฟซ Agent-Native

binary `deeptutor` เดียว, สองวิธีเข้า: **REPL** แบบโต้ตอบสำหรับคนที่อยู่ใน terminal และ **JSON** ที่มีโครงสร้างสำหรับ agents อื่น ๆ ที่ขับเคลื่อน DeepTutor เป็นเครื่องมือ ความสามารถ, เครื่องมือ และ knowledge bases เหมือนกันทั้งสองแบบ

<details>
<summary><b>ขับเคลื่อนด้วยตัวเอง</b></summary>

`deeptutor chat` เปิด interactive REPL; `deeptutor run <capability> "<message>"` รัน turn เดียวแล้วออก ทั้งสองใช้ flags `--capability`, `--tool`, `--kb` และ `--config` เหมือนกัน

```bash
deeptutor chat                                              # interactive REPL
deeptutor chat --capability deep_solve --kb my-kb --tool rag
deeptutor run chat "Explain the Fourier transform" --tool rag --kb textbook
deeptutor run deep_research "Survey 2026 papers on RAG" \
  --config mode=report --config depth=standard
```

ทุกอย่างที่แอป Web ทำก็มีที่นี่ด้วย — knowledge bases (`kb`), sessions (`session`), partners (`partner`), skills (`skill`), notebooks, memory และ config รายการเต็มด้านล่าง

</details>

<details>
<summary><b>ให้ agent ขับเคลื่อน</b></summary>

DeepTutor ถูกสร้างมาเพื่อ *ดำเนินการโดย agent อื่น* เพิ่ม `--format json` ใน `run` ใด ๆ และแต่ละ turn จะ stream **NDJSON — หนึ่ง event ต่อบรรทัด** (`content`, `tool_call`, `tool_result`, `done`, …) ทุกบรรทัดมี `session_id` กำกับ การรันปลอดภัยสำหรับ headless: การหยุด `ask_user` ที่ไม่มี TTY จะ auto-resolve ด้วยการตอบกลับว่างแทนที่จะหยุดรอ

```bash
# One shot แบบ machine-readable
deeptutor run deep_solve "Find d/dx[sin(x^2)]" --tool reason --format json

# เชื่อม turns ใน session เดียวที่มีสถานะ — จับ id แล้วนำมาใช้ซ้ำ
SID=$(deeptutor run deep_research "Survey 2026 papers on RAG" \
  --config mode=report --config depth=standard --format json \
  | jq -r 'select(.type=="done").session_id')
deeptutor run deep_question "Quiz me on that survey" --session "$SID" --format json
```

repo มี root [`SKILL.md`](../../SKILL.md) — เอกสาร handover ~150 บรรทัดที่สอน LLM ที่ใช้เครื่องมือใด ๆ ให้รู้จัก surface ทั้งหมดในการอ่านครั้งเดียว ส่งให้ Claude Code, Codex หรือ OpenCode (พวกเขาหยิบ `SKILL.md` โดยอัตโนมัติ) หรือ wrap `deeptutor run` เป็นเครื่องมือใน LangChain / AutoGen loop สูตรเต็ม: [Agent Handoff](https://deeptutor.info/docs/cli/agent-handoff/)

</details>

<details>
<summary><b>เอกสารอ้างอิงคำสั่ง</b></summary>

| คำสั่ง | คำอธิบาย |
|:---|:---|
| `deeptutor init` | สร้างหรืออัพเดต `data/user/settings` สำหรับ workspace ปัจจุบัน |
| `deeptutor start [--home PATH]` | เปิดตัว backend + frontend ด้วยกัน |
| `deeptutor serve [--port PORT]` | เริ่มเฉพาะ FastAPI backend |
| `deeptutor run <capability> <message>` | รัน capability turn เดียว (`chat`, `deep_solve`, `deep_question`, `deep_research`, `visualize`, `math_animator`, `mastery_path`); เพิ่ม `--format json` สำหรับ NDJSON output |
| `deeptutor chat` | Interactive REPL พร้อม capability, tool, KB, notebook และ history controls |
| `deeptutor partner list/create/start/stop` | จัดการ partners ที่เชื่อมต่อผ่าน IM |
| `deeptutor kb list/info/create/add/search/set-default/delete` | จัดการ knowledge bases LlamaIndex |
| `deeptutor skill search/install/list/remove/login/logout/publish/update` | จัดการทักษะ ติดตั้งจากฮับ และเผยแพร่ของคุณเอง (`eduhub:<slug>` โดยค่าเริ่มต้น ดู Ecosystem) |
| `deeptutor memory show/clear` | ตรวจสอบ L2/L3 memory docs หรือล้าง L1/all memory |
| `deeptutor session list/show/open/rename/delete` | จัดการ shared sessions |
| `deeptutor notebook list/create/show/add-md/replace-md/remove-record` | จัดการ notebooks จากไฟล์ Markdown |
| `deeptutor book list/health/refresh-fingerprints` | ตรวจสอบ books และรีเฟรช source fingerprints |
| `deeptutor plugin list/info` | ตรวจสอบเครื่องมือและ capabilities ที่ลงทะเบียน |
| `deeptutor config show` | พิมพ์สรุปการกำหนดค่า |
| `deeptutor provider login <provider>` | Provider auth (OAuth login สำหรับ `openai-codex`; `github-copilot` ตรวจสอบ session auth Copilot ที่มีอยู่) |

</details>

<details>
<summary><b>การแจกจ่าย CLI เท่านั้น</b></summary>

แพ็คเกจ CLI เท่านั้นอยู่ใน `packaging/deeptutor-cli` ใน checkout นี้ ติดตั้งจากซอร์ส:

```bash
python -m pip install -e ./packaging/deeptutor-cli
```

ยังไม่ได้เผยแพร่บน PyPI ดังนั้นส่วน [เริ่มต้น](#-เริ่มต้น) หลักจึงคงเส้นทางการติดตั้งจากซอร์สไว้

</details>

## 🧩 ระบบนิเวศ — EduHub และชุมชน Skills

DeepTutor skills ใช้รูปแบบ **Agent-Skills** แบบเปิด — โฟลเดอร์ที่มี `SKILL.md` playbook (YAML frontmatter + Markdown) และไฟล์อ้างอิงแบบเสริม ไม่มีอะไรเกี่ยวกับมันที่เจาะจงสำหรับ DeepTutor ดังนั้น registry ใด ๆ ที่พูด format นี้ก็กลายเป็นแหล่งสำหรับ library ของคุณ DeepTutor มาพร้อมกับ **[EduHub](https://eduhub.deeptutor.info/)** — registry ทักษะที่เน้นการศึกษาของเรา — เชื่อมต่อเป็นฮับเริ่มต้น

<details>
<summary><b>EduHub — ระบบนิเวศทักษะของ DeepTutor</b></summary>

[**EduHub**](https://eduhub.deeptutor.info/) คือ community hub ที่ DeepTutor เปิดตัวสำหรับแชร์ agent skills เชิงสอน — Socratic tutors, flashcard builders, essay feedback, exam blueprints, concept explainers และอื่น ๆ อีกมาก มันถูกสร้างเข้า DeepTutor ดังนั้นไม่มีอะไรต้องกำหนดค่า: slug เปล่าหรือ prefix `eduhub:` จะ resolve ไปยังมัน

**ค้นหาและติดตั้ง** — ในเบราว์เซอร์ เปิด **Learning Space → Skills → นำเข้าจาก EduHub** เพื่อเรียกดู catalog และดาวน์โหลด skill ตรงเข้า library จาก terminal:

```bash
deeptutor skill search "socratic tutor"               # ค้นหา EduHub (ฮับเริ่มต้น)
deeptutor skill install socratic-tutor                # fetch → verify → register
deeptutor skill install eduhub:socratic-tutor@1.2.0   # ระบุ hub และเวอร์ชัน
deeptutor skill list                                  # skills ในเครื่องพร้อม hub provenance
```

**เผยแพร่ของคุณเอง** — แพ็ค `SKILL.md` และแชร์กลับสู่ชุมชน:

```bash
deeptutor skill login                                 # browser sign-in ไปยัง EduHub
deeptutor skill publish ./my-skill                    # interactive: เลือก track + tags แล้วอัพโหลด
deeptutor skill update                                # rollback หรือ release เวอร์ชันใหม่
```

EduHub ยังเป็น registry แบบ standalone ที่เข้ากันได้กับ ClawHub ดังนั้น agents ที่ไม่ใช่ DeepTutor (Claude Code, Codex, …) สามารถใช้มันโดยตรงผ่าน CLI `eduhub` — `npx eduhub install socratic-tutor`

</details>

<details>
<summary><b>ประตูความปลอดภัยในการนำเข้า</b></summary>

ไม่ว่าแหล่งที่มาจะเป็นอะไร ทุกการนำเข้าจะผ่าน **ประตูความปลอดภัยเดียวกัน** ก่อนที่อะไรจะแตะ workspace ของคุณ:

- **security verdict** ของ registry จะถูกตรวจสอบก่อน — แพ็คเกจที่ถูกตั้งค่าสถานะจะถูกปฏิเสธเว้นแต่คุณจะส่ง `--allow-unverified`;
- archives จะถูก extract อย่างระมัดระวัง (ป้องกัน zip-slip / zip-bomb) หลัง **suffix whitelist** แบบ text/script ดังนั้น binaries จะไม่ลงใน workspace เลย;
- frontmatter จะถูก normalize เป็น schema ของ DeepTutor และ `always:` จะถูก **ลบออก** ดังนั้น skill ที่ดาวน์โหลดมาไม่สามารถบังคับตัวเองเข้าสู่ system prompt ทุกอัน;
- provenance — hub, version, verdict และเวลาติดตั้ง — จะถูกเขียนลง `.hub-lock.json` สำหรับการตรวจสอบและอัพเดต

ในการปรับใช้ multi-user การติดตั้งเป็นสิทธิ์ของ admin เท่านั้น: skill ใหม่จะลงใน admin catalog และมองไม่เห็นสำหรับผู้ใช้อื่นจนกว่า grant จะกำหนดมัน ดังนั้น admin สามารถตรวจสอบก่อนนำออกใช้

</details>

<details>
<summary><b>รองรับ ClawHub ด้วย</b></summary>

เนื่องจาก DeepTutor พูดรูปแบบ Agent-Skills แบบเปิด **[ClawHub](https://clawhub.ai/)** ทำงานเป็นแหล่งระดับ first-class ด้วย — มันถูกสร้างเข้าพร้อมกับ EduHub เลือกด้วย hub prefix:

```bash
deeptutor skill search "git release notes" --hub clawhub
deeptutor skill install clawhub:git-release-notes@1.0.1
```

เพิ่ม registries เพิ่มเติมใน `settings/skill_hubs.json`: entry `type: "clawhub"` ชี้ไปที่ HTTP API ที่เข้ากันได้ใด ๆ (ทั้ง EduHub และ ClawHub พูด API นี้), `type: "command"` ห่อ CLI ที่ registry ส่งมา และ `"default"` เลือกฮับที่ใช้สำหรับ slugs เปล่า ทั้งหมดนี้ป้อนข้อมูลผ่านประตูนำเข้าเดียวกัน

</details>

## 🌐 ชุมชน

### 📮 ติดต่อ

DeepTutor คือโปรเจกต์โอเพนซอร์สที่นำโดย [Bingxi Zhao](https://github.com/pancacake) ภายในกลุ่ม [HKUDS](https://github.com/HKUDS) และพัฒนาใน **รูปแบบโอเพนซอร์สอย่างสมบูรณ์** สร้างร่วมกับชุมชน จนถึงปัจจุบัน เรา **ไม่มี** ผลิตภัณฑ์ออนไลน์แบบชำระเงินในรูปแบบใด ๆ ติดต่อได้ที่ **bingxizhao39@gmail.com** สำหรับการสนทนา, ไอเดีย หรือการร่วมมือ

### 🙏 ขอบคุณ

ขอบคุณอย่างจริงใจถึง [**Chao Huang**](https://sites.google.com/view/chaoh), ผู้อำนวยการ Data Intelligence Lab @ HKU และเพื่อน ๆ ใน HKUDS lab สำหรับการสนับสนุนอย่างอบอุ่น — โดยเฉพาะ [**Jiahao Zhang**](https://github.com/zzhtx258), [**Zirui Guo**](https://github.com/LarFii) และ [**Xubin Ren**](https://github.com/Re-bin) เรายังขอบคุณอย่างสุดซึ้งถึง **ชุมชนโอเพนซอร์ส**: stars, issues, pull requests และ discussions ของคุณกำหนดรูปร่าง DeepTutor ทุกวัน

DeepTutor ยังยืนอยู่บนไหล่ของโปรเจกต์โอเพนซอร์สที่โดดเด่นที่ให้ทั้งเครื่องมือและแรงบันดาลใจแก่เรา:

| โปรเจกต์ | บทบาท / แรงบันดาลใจ |
|:---|:---|
| [**LlamaIndex**](https://github.com/run-llama/llama_index) | กระดูกสันหลังของ RAG pipeline และการ indexing เอกสาร |
| [**nanobot**](https://github.com/HKUDS/nanobot) | Ultra-lightweight agent engine ที่ขับเคลื่อน TutorBot ดั้งเดิม *(HKUDS)* |
| [**LightRAG**](https://github.com/HKUDS/LightRAG) | RAG ที่ง่ายและเร็ว *(HKUDS)* |
| [**AutoAgent**](https://github.com/HKUDS/AutoAgent) | Zero-code agent framework *(HKUDS)* |
| [**AI-Researcher**](https://github.com/HKUDS/AI-Researcher) | Pipeline การวิจัยอัตโนมัติ *(HKUDS)* |
| [**OpenClaw**](https://github.com/openclaw/openclaw) | Open agent gateway และ skill ecosystem เบื้องหลัง ClawHub |
| [**Codex**](https://github.com/openai/codex) | Agent-native coding CLI ที่เป็นแรงบันดาลใจให้ CLI workflow ของเรา |
| [**Claude Code**](https://github.com/anthropics/claude-code) | Agentic coding CLI ที่เป็นแรงบันดาลใจให้ DeepTutor agent loop |
| [**ManimCat**](https://github.com/Wing900/ManimCat) | การสร้าง animation คณิตศาสตร์ที่ขับเคลื่อนด้วย AI สำหรับ Math Animator |

### 🗺️ Roadmap และการมีส่วนร่วม

เราต้องการให้ DeepTutor พัฒนาและปรับปรุงต่อเนื่อง — และสุดท้ายกลายเป็นของขวัญที่เรามอบคืนสู่ชุมชนโอเพนซอร์ส [**roadmap**](https://github.com/HKUDS/DeepTutor/issues/498) ของเราอัพเดตต่อเนื่อง โหวตรายการที่นั่นหรือเสนอรายการใหม่ หากต้องการมีส่วนร่วม ดู [**คู่มือการมีส่วนร่วม**](../../CONTRIBUTING.md) สำหรับกลยุทธ์ branching มาตรฐานโค้ด และวิธีเริ่มต้น

<div align="center">

เราหวังว่า DeepTutor จะกลายเป็นของขวัญสำหรับชุมชน 🎁

<a href="https://github.com/HKUDS/DeepTutor/graphs/contributors">
  <img src="https://contrib.rocks/image?repo=HKUDS/DeepTutor&max=999" alt="ผู้มีส่วนร่วม" />
</a>

</div>

<div align="center">

<a href="https://www.star-history.com/#HKUDS/DeepTutor&type=timeline&legend=top-left">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/svg?repos=HKUDS/DeepTutor&type=timeline&theme=dark&legend=top-left" />
    <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/svg?repos=HKUDS/DeepTutor&type=timeline&legend=top-left" />
    <img alt="กราฟประวัติดาว" src="https://api.star-history.com/svg?repos=HKUDS/DeepTutor&type=timeline&legend=top-left" />
  </picture>
</a>

</div>

<p align="center">
 <a href="https://www.star-history.com/hkuds/deeptutor">
  <picture>
   <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/badge?repo=HKUDS/DeepTutor&theme=dark" />
   <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/badge?repo=HKUDS/DeepTutor" />
   <img alt="อันดับประวัติดาว" src="https://api.star-history.com/badge?repo=HKUDS/DeepTutor" />
  </picture>
 </a>
</p>

<div align="center">

ได้รับอนุญาตภายใต้ [Apache License 2.0](../../LICENSE)

<p>
  <img src="https://visitor-badge.laobi.icu/badge?page_id=HKUDS.DeepTutor&style=for-the-badge&color=00d4ff" alt="จำนวนผู้เข้าชม">
</p>

</div>
