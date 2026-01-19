<div align="center">

<img src="assets/logo-ver2.png" alt="DeepTutor Logo" width="150" style="border-radius: 15px;">

# DeepTutor: AI-Powered Personalized Learning Assistant

[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?style=flat-square&logo=python&logoColor=white)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.100%2B-009688?style=flat-square&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![React](https://img.shields.io/badge/React-19-61DAFB?style=flat-square&logo=react&logoColor=black)](https://react.dev/)
[![Next.js](https://img.shields.io/badge/Next.js-16-000000?style=flat-square&logo=next.js&logoColor=white)](https://nextjs.org/)
[![TailwindCSS](https://img.shields.io/badge/Tailwind-3.4-06B6D4?style=flat-square&logo=tailwindcss&logoColor=white)](https://tailwindcss.com/)
[![License](https://img.shields.io/badge/License-AGPL--3.0-blue?style=flat-square)](LICENSE)

<p align="center">
  <a href="https://discord.gg/eRsjPgMU4t"><img src="https://img.shields.io/badge/Discord-Join_Community-5865F2?style=for-the-badge&logo=discord&logoColor=white" alt="Discord"></a>
  &nbsp;&nbsp;
  <a href="./Communication.md"><img src="https://img.shields.io/badge/Feishu-Join_Group-00D4AA?style=for-the-badge&logo=feishu&logoColor=white" alt="Feishu"></a>
  &nbsp;&nbsp;
  <a href="https://github.com/HKUDS/DeepTutor/issues/78"><img src="https://img.shields.io/badge/WeChat-Join_Group-07C160?style=for-the-badge&logo=wechat&logoColor=white" alt="WeChat"></a>
</p>



[**Quick Start**](#quick-start) · [**Core Modules**](#core-modules) · [**FAQ**](#faq)

[🇨🇳 中文](assets/README/README_CN.md) · [🇯🇵 日本語](assets/README/README_JA.md) · [🇪🇸 Español](assets/README/README_ES.md) · [🇫🇷 Français](assets/README/README_FR.md) · [🇸🇦 العربية](assets/README/README_AR.md) · [🇷🇺 Русский](assets/README/README_RU.md) · [🇮🇳 हिन्दी](assets/README/README_HI.md) · [🇵🇹 Português](assets/README/README_PT.md)

</div>

<div align="center">

📚 **Massive Document Knowledge Q&A** &nbsp;•&nbsp; 🎨 **Interactive Learning Visualization**<br>
🎯 **Knowledge Reinforcement** &nbsp;•&nbsp; 🔍 **Deep Research & Idea Generation**

</div>

---
### 📰 News

> **[2026.1.1]** Happy New Year! Join our [Discord Community](https://discord.gg/zpP9cssj), [Wechat Community](https://github.com/HKUDS/DeepTutor/issues/78), or [Discussions](https://github.com/HKUDS/DeepTutor/discussions) - shape the future of DeepTutor! 💬

> **[2025.12.30]** Visit our [Official Website](https://hkuds.github.io/DeepTutor/) for more details!

> **[2025.12.29]** DeepTutor is now live! ✨

### 📦 Releases

> **[2026.1.18]** Release [v0.5.2](https://github.com/HKUDS/DeepTutor/releases/tag/v0.5.1) - Enhance RAG pipeline with Docling support and improve CI/CD workflows with several minor bugs fixed -- Thanks to all the feedbacks!

<details>
<summary>History releases</summary>

> **[2026.1.15]** Release [v0.5.0](https://github.com/HKUDS/DeepTutor/releases/tag/v0.5.0) - Unified LLM & Embedding services, RAG pipeline selection, and major enhancements to Home, History, QuestionGen & Settings modules -- Thanks to all the contributors!

> **[2026.1.9]** Release [v0.4.1](https://github.com/HKUDS/DeepTutor/releases/tag/v0.4.1) with LLM Provider system overhaul, Question Generation robustness improvements, and codebase cleanup - Thanks to all the contributors!

> **[2026.1.9]** Release [v0.4.0](https://github.com/HKUDS/DeepTutor/releases/tag/v0.4.0) with new code structure, multiple llm & embeddings support - Thanks to all the contributors!

> **[2026.1.5]** [v0.3.0](https://github.com/HKUDS/DeepTutor/releases/tag/v0.3.0) - Unified PromptManager architecture, CI/CD automation & pre-built Docker images on GHCR

> **[2026.1.2]** [v0.2.0](https://github.com/HKUDS/DeepTutor/releases/tag/v0.2.0) - Docker deployment, Next.js 16 & React 19 upgrade, WebSocket security & critical vulnerability fixes

</details>

---

## Key Features of DeepTutor

### 📚 Massive Document Knowledge Q&A
• **Smart Knowledge Base**: Upload textbooks, research papers, technical manuals, and domain-specific documents. Build a comprehensive AI-powered knowledge repository for instant access.<br>
• **Multi-Agent Problem Solving**: Dual-loop reasoning architecture with RAG, web search, and code execution -- delivering step-by-step solutions with precise citations.

### 🎨 Interactive Learning Visualization
• **Knowledge Simplification & Explanations**: Transform complex concepts, knowledge, and algorithms into easy-to-understand visual aids, detailed step-by-step breakdowns, and engaging interactive demonstrations.<br>
• **Personalized Q&A**: Context-aware conversations that adapt to your learning progress, with interactive pages and session-based knowledge tracking.

### 🎯 Knowledge Reinforcement with Practice Exercise Generator
• **Intelligent Exercise Creation**: Generate targeted quizzes, practice problems, and customized assessments tailored to your current knowledge level and specific learning objectives.<br>
• **Authentic Exam Simulation**: Upload reference exams to generate practice questions that perfectly match the original style, format, and difficulty—giving you realistic preparation for the actual test.

### 🔍 Deep Research & Idea Generation
• **Comprehensive Research & Literature Review**: Conduct in-depth topic exploration with systematic analysis. Identify patterns, connect related concepts across disciplines, and synthesize existing research findings.<br>
• **Novel Insight Discovery**: Generate structured learning materials and uncover knowledge gaps. Identify promising new research directions through intelligent cross-domain knowledge synthesis.

---

<div align="center">
  <img src="assets/figs/title_gradient.svg" alt="All-in-One Tutoring System" width="70%">
</div>

<!-- ━━━━━━━━━━━━━━━━ Core Learning Experience ━━━━━━━━━━━━━━━━ -->

<table>
<tr>
<td width="50%" align="center" valign="top">

<h3>📚 Massive Document Knowledge Q&A</h3>
<a href="#problem-solving-agent">
<img src="assets/gifs/solve.gif" width="100%">
</a>
<br>
<sub>Multi-agent Problem Solving with Exact Citations</sub>

</td>
<td width="50%" align="center" valign="top">

<h3>🎨 Interactive Learning Visualization</h3>
<a href="#guided-learning">
<img src="assets/gifs/guided-learning.gif" width="100%">
</a>
<br>
<sub>Step-by-step Visual Explanations with Personal QAs.</sub>

</td>
</tr>
</table>

<!-- ━━━━━━━━━━━━━━━━ Practice & Reinforcement ━━━━━━━━━━━━━━━━ -->

<h3 align="center">🎯 Knowledge Reinforcement</h3>

<table>
<tr>
<td width="50%" valign="top" align="center">

<a href="#question-generator">
<img src="assets/gifs/question-1.gif" width="100%">
</a>

**Custom Questions**  
<sub>Auto-Validated Practice Questions Generation</sub>

</td>
<td width="50%" valign="top" align="center">

<a href="#question-generator">
<img src="assets/gifs/question-2.gif" width="100%">
</a>

**Mimic Questions**  
<sub>Clone Exam Style for Authentic Practice</sub>

</td>
</tr>
</table>

<!-- ━━━━━━━━━━━━━━━━ Research & Creation ━━━━━━━━━━━━━━━━ -->

<h3 align="center">🔍 Deep Research & Idea Generation</h3>

<table>
<tr>
<td width="33%" align="center">

<a href="#deep-research">
<img src="assets/gifs/deepresearch.gif" width="100%">
</a>

**Deep Research**  
<sub>Knowledge Extension from Textbook with RAG, Web and Paper-search</sub>

</td>
<td width="33%" align="center">

<a href="#idea-generation">
<img src="assets/gifs/ideagen.gif" width="100%">
</a>

**Automated IdeaGen**  
<sub>Brainstorming and Concept Synthesis with Dual-filter Workflow</sub>

</td>
<td width="33%" align="center">

<a href="#co-writer">
<img src="assets/gifs/co-writer.gif" width="100%">
</a>

**Interactive IdeaGen**  
<sub>RAG and Web-search Powered Co-writer with Podcast Generation</sub>

</td>
</tr>
</table>

<!-- ━━━━━━━━━━━━━━━━ Knowledge Infrastructure ━━━━━━━━━━━━━━━━ -->

<h3 align="center">🏗️ All-in-One Knowledge System</h3>

<table>
<tr>
<td width="50%" align="center">

<a href="#dashboard--knowledge-base-management">
<img src="assets/gifs/knowledge_bases.png" width="100%">
</a>

**Personal Knowledge Base**  
<sub>Build and Organize Your Own Knowledge Repository</sub>

</td>
<td width="50%" align="center">

<a href="#notebook">
<img src="assets/gifs/notebooks.png" width="100%">
</a>

**Personal Notebook**  
<sub>Your Contextual Memory for Learning Sessions</sub>

</td>
</tr>
</table>

<p align="center">
  <sub>🌙 Use DeepTutor in <b>Dark Mode</b>!</sub>
</p>

---

## 🏛️ DeepTutor's Framework

<div align="center">
<img src="assets/figs/full-pipe.png" alt="DeepTutor Full-Stack Workflow" width="100%">
</div>

### 💬 User Interface Layer
• **Intuitive Interaction**: Simple bidirectional query-response flow for intuitive interaction.<br>
• **Structured Output**: Structured response generation that organizes complex information into actionable outputs.

### 🤖 Intelligent Agent Modules
• **Problem Solving & Assessment**: Step-by-step problem solving and custom assessment generation.<br>
• **Research & Learning**: Deep Research for topic exploration and Guided Learning with visualization.<br>
• **Idea Generation**: Automated and interactive concept development with multi-source insights.

### 🔧 Tool Integration Layer
• **Information Retrieval**: RAG hybrid retrieval, real-time web search, and academic paper databases.<br>
• **Processing & Analysis**: Python code execution, query item lookup, and PDF parsing for document analysis.

### 🧠 Knowledge & Memory Foundation
• **Knowledge Graph**: Entity-relation mapping for semantic connections and knowledge discovery.<br>
• **Vector Store**: Embedding-based semantic search for intelligent content retrieval.<br>
• **Memory System**: Session state management and citation tracking for contextual continuity.

## 📋 Todo
> 🌟 Star to follow our future updates!
- [ x ] Multi-linguistic support
- [ x ] DeepTutor Community
- [ x ] Video & Audio file support
- [ x ] Atomic RAG pipeline customize
- [ - ] Incremental Knowledge-base Edit
- [ - ] Personalized Workspace
- [ - ] DataBase Visualization
- [ - ] Online Demo

## 🚀 Getting Started

### Step 1: Pre-Configuration

**① Clone Repository**

```bash
git clone https://github.com/HKUDS/DeepTutor.git
cd DeepTutor
```

**② Set Up Environment Variables**

```bash
cp .env.example .env
# Edit .env file with your API keys
```

<details>
<summary>📋 <b>Environment Variables Reference</b></summary>

| Variable | Required | Description |
|:---|:---:|:---|
| `LLM_MODEL` | **Yes** | Model name (e.g., `gpt-4o`) |
| `LLM_API_VERSION` | No | API version for Azure OpenAI (e.g., `2024-02-15-preview`) |
| `LLM_API_KEY` | **Yes** | Your LLM API key |
| `LLM_HOST` | **Yes** | API endpoint URL |
| `EMBEDDING_MODEL` | **Yes** | Embedding model name |
| `EMBEDDING_API_VERSION` | No | API version for Azure OpenAI Embeddings |
| `EMBEDDING_API_KEY` | **Yes** | Embedding API key |
| `EMBEDDING_HOST` | **Yes** | Embedding API endpoint |
| `BACKEND_PORT` | No | Backend port (default: `8001`) |
| `FRONTEND_PORT` | No | Frontend port (default: `3782`) |
| `NEXT_PUBLIC_API_BASE` | No | **Frontend API URL** - Set this for remote/LAN access (e.g., `http://192.168.1.100:8001`) |
| `TTS_*` | No | Text-to-Speech settings |
| `SEARCH_PROVIDER` | No | Search provider (options: `perplexity`, `tavily`, `serper`, `jina`, `exa`, `baidu`, default: `perplexity`) |
| `SEARCH_API_KEY` | No | Unified API key for all search providers |

> 💡 **Remote Access**: If accessing from another device (e.g., `192.168.31.66:3782`), add to `.env`:
> ```bash
> NEXT_PUBLIC_API_BASE=http://192.168.31.66:8001
> ```

</details>

**③ Configure Ports & LLM** *(Optional)*

- **Ports**: Set in `.env` file → `BACKEND_PORT` / `FRONTEND_PORT` (defaults: 8001/3782)
- **LLM**: Edit `config/agents.yaml` → `temperature` / `max_tokens` per module
- See [Configuration Docs](config/README.md) for details

**④ Try Demo Knowledge Bases** *(Optional)*

<details>
<summary>📚 <b>Available Demos</b></summary>

- **Research Papers** — 5 papers from our lab ([AI-Researcher](https://github.com/HKUDS/AI-Researcher), [LightRAG](https://github.com/HKUDS/LightRAG), etc.)
- **Data Science Textbook** — 8 chapters, 296 pages ([Book Link](https://ma-lab-berkeley.github.io/deep-representation-learning-book/))

</details>

1. Download from [Google Drive](https://drive.google.com/drive/folders/1iWwfZXiTuQKQqUYb5fGDZjLCeTUP6DA6?usp=sharing)
2. Extract into `data/` directory

> Demo KBs use `text-embedding-3-large` with `dimensions = 3072`

**⑤ Create Your Own Knowledge Base** *(After Launch)*

1. Go to http://localhost:3782/knowledge
2. Click "New Knowledge Base" → Enter name → Upload PDF/TXT/MD files
3. Monitor progress in terminal

---

### Step 2: Choose Your Installation Method

#### 🐳 Option A: Docker Deployment

> No Python/Node.js setup required

**Prerequisites**: [Docker](https://docs.docker.com/get-docker/) & [Docker Compose](https://docs.docker.com/compose/install/)

**Quick Start** — Build from source:

```bash
docker compose up                  # Build and start (~11 min first run on mac mini M4)
docker compose build --no-cache    # Clear cache and rebuild after pull the newest repo
```

**Or use pre-built image** (faster):

```bash
# Linux/macOS (AMD64)
docker run -d --name deeptutor \
  -p 8001:8001 -p 3782:3782 \
  --env-file .env \
  -v $(pwd)/data:/app/data \
  -v $(pwd)/config:/app/config:ro \
  ghcr.io/hkuds/deeptutor:latest

# Apple Silicon (ARM64): use ghcr.io/hkuds/deeptutor:latest-arm64
# Windows PowerShell: use ${PWD} instead of $(pwd)
```

**Common Commands**:

```bash
docker compose up -d      # Start
docker compose down       # Stop
docker compose logs -f    # View logs
docker compose up --build # Rebuild after changes
```

<details>
<summary>📋 <b>More Docker Options</b> (Pre-built images, Cloud deployment, Custom ports)</summary>

**Pre-built Image Architecture Reference:**

| Architecture | Image Tag | Use Case |
|:-------------|:----------|:---------|
| **AMD64** | `ghcr.io/hkuds/deeptutor:latest` | Intel/AMD (most servers, Windows/Linux PCs) |
| **ARM64** | `ghcr.io/hkuds/deeptutor:latest-arm64` | Apple Silicon, AWS Graviton, Raspberry Pi |

> 💡 Run `uname -m` to check: `x86_64` = AMD64, `arm64`/`aarch64` = ARM64

**Cloud Deployment** — Must set external API URL:

```bash
docker run -d --name deeptutor \
  -p 8001:8001 -p 3782:3782 \
  -e NEXT_PUBLIC_API_BASE_EXTERNAL=https://your-server.com:8001 \
  --env-file .env \
  -v $(pwd)/data:/app/data \
  ghcr.io/hkuds/deeptutor:latest
```

**Custom Ports Example:**

```bash
docker run -d --name deeptutor \
  -p 9001:9001 -p 3000:3000 \
  -e BACKEND_PORT=9001 \
  -e FRONTEND_PORT=3000 \
  -e NEXT_PUBLIC_API_BASE_EXTERNAL=https://your-server.com:9001 \
  --env-file .env \
  -v $(pwd)/data:/app/data \
  ghcr.io/hkuds/deeptutor:latest
```

</details>

---

#### 💻 Option B: Manual Installation

> For development or non-Docker environments

**Prerequisites**: Python 3.10+, Node.js 18+

**1. Set Up Environment**:

```bash
# Using conda (Recommended)
conda create -n deeptutor python=3.10 && conda activate deeptutor

# Or using venv
python -m venv venv && source venv/bin/activate  # Windows: venv\Scripts\activate
```

**2. Install Dependencies**:

```bash
# One-click installation (Recommended)
python scripts/install_all.py
# Or: bash scripts/install_all.sh

# Or manual installation
pip install -r requirements.txt
npm install --prefix web
```

**3. Launch**:

```bash
python scripts/start_web.py    # Start frontend + backend
# Or: python scripts/start.py  # CLI only
# Stop: Ctrl+C
```

<details>
<summary>🔧 <b>Start Frontend & Backend Separately</b></summary>

**Backend** (FastAPI):
```bash
python src/api/run_server.py
# Or: uvicorn src.api.main:app --host 0.0.0.0 --port 8001 --reload
```

**Frontend** (Next.js):
```bash
cd web && npm install && npm run dev -- -p 3782
```

**Note**: Create `web/.env.local`:
```bash
NEXT_PUBLIC_API_BASE=http://localhost:8001
```

| Service | Default Port |
|:---:|:---:|
| Backend | `8001` |
| Frontend | `3782` |

</details>

### Access URLs

| Service | URL | Description |
|:---:|:---|:---|
| **Frontend** | http://localhost:3782 | Main web interface |
| **API Docs** | http://localhost:8001/docs | Interactive API documentation |

---

## 📂 Data Storage

All user content and system data are stored in the `data/` directory:

```
data/
├── knowledge_bases/              # Knowledge base storage
└── user/                         # User activity data
    ├── solve/                    # Problem solving results and artifacts
    ├── question/                 # Generated questions
    ├── research/                 # Research reports and cache
    ├── co-writer/                # Interactive IdeaGen documents and audio files
    ├── notebook/                 # Notebook records and metadata
    ├── guide/                    # Guided learning sessions
    ├── logs/                     # System logs
    └── run_code_workspace/       # Code execution workspace
```

Results are automatically saved during all activities. Directories are created automatically as needed.

## 📦 Core Modules

<details>
<summary><b>🧠 Smart Solver</b></summary>

<details>
<summary><b>Architecture Diagram</b></summary>

![Smart Solver Architecture](assets/figs/solve.png)

</details>

> **Intelligent problem-solving system** based on **Analysis Loop + Solve Loop** dual-loop architecture, supporting multi-mode reasoning and dynamic knowledge retrieval.

**Core Features**

| Feature | Description |
|:---:|:---|
| Dual-Loop Architecture | **Analysis Loop**: InvestigateAgent → NoteAgent<br>**Solve Loop**: PlanAgent → ManagerAgent → SolveAgent → CheckAgent → Format |
| Multi-Agent Collaboration | Specialized agents: InvestigateAgent, NoteAgent, PlanAgent, ManagerAgent, SolveAgent, CheckAgent |
| Real-time Streaming | WebSocket transmission with live reasoning process display |
| Tool Integration | RAG (naive/hybrid), Web Search, Query Item, Code Execution |
| Persistent Memory | JSON-based memory files for context preservation |
| Citation Management | Structured citations with reference tracking |

**Usage**

1. Visit http://localhost:{frontend_port}/solver
2. Select a knowledge base
3. Enter your question, click "Solve"
4. Watch the real-time reasoning process and final answer

<details>
<summary><b>Python API</b></summary>

```python
import asyncio
from src.agents.solve import MainSolver

async def main():
    solver = MainSolver(kb_name="ai_textbook")
    result = await solver.solve(
        question="Calculate the linear convolution of x=[1,2,3] and h=[4,5]",
        mode="auto"
    )
    print(result['formatted_solution'])

asyncio.run(main())
```

</details>

<details>
<summary><b>Output Location</b></summary>

```
data/user/solve/solve_YYYYMMDD_HHMMSS/
├── investigate_memory.json    # Analysis Loop memory
├── solve_chain.json           # Solve Loop steps & tool records
├── citation_memory.json       # Citation management
├── final_answer.md            # Final solution (Markdown)
├── performance_report.json    # Performance monitoring
└── artifacts/                 # Code execution outputs
```

</details>

</details>

---

<details>
<summary><b>📝 Question Generator</b></summary>

<details>
<summary><b>Architecture Diagram</b></summary>

![Question Generator Architecture](assets/figs/question-gen.png)

</details>

> **Dual-mode question generation system** supporting **custom knowledge-based generation** and **reference exam paper mimicking** with automatic validation.

**Core Features**

| Feature | Description |
|:---:|:---|
| Custom Mode | **Background Knowledge** → **Question Planning** → **Generation** → **Single-Pass Validation**<br>Analyzes question relevance without rejection logic |
| Mimic Mode | **PDF Upload** → **MinerU Parsing** → **Question Extraction** → **Style Mimicking**<br>Generates questions based on reference exam structure |
| ReAct Engine | QuestionGenerationAgent with autonomous decision-making (think → act → observe) |
| Validation Analysis | Single-pass relevance analysis with `kb_coverage` and `extension_points` |
| Question Types | Multiple choice, fill-in-the-blank, calculation, written response, etc. |
| Batch Generation | Parallel processing with progress tracking |
| Complete Persistence | All intermediate files saved (background knowledge, plan, individual results) |
| Timestamped Output | Mimic mode creates batch folders: `mimic_YYYYMMDD_HHMMSS_{pdf_name}/` |

**Usage**

**Custom Mode:**
1. Visit http://localhost:{frontend_port}/question
2. Fill in requirements (topic, difficulty, question type, count)
3. Click "Generate Questions"
4. View generated questions with validation reports

**Mimic Mode:**
1. Visit http://localhost:{frontend_port}/question
2. Switch to "Mimic Exam" tab
3. Upload PDF or provide parsed exam directory
4. Wait for parsing → extraction → generation
5. View generated questions alongside original references

<details>
<summary><b>Python API</b></summary>

**Custom Mode - Full Pipeline:**
```python
import asyncio
from src.agents.question import AgentCoordinator

async def main():
    coordinator = AgentCoordinator(
        kb_name="ai_textbook",
        output_dir="data/user/question"
    )

    # Generate multiple questions from text requirement
    result = await coordinator.generate_questions_custom(
        requirement_text="Generate 3 medium-difficulty questions about deep learning basics",
        difficulty="medium",
        question_type="choice",
        count=3
    )

    print(f"✅ Generated {result['completed']}/{result['requested']} questions")
    for q in result['results']:
        print(f"- Relevance: {q['validation']['relevance']}")

asyncio.run(main())
```

**Mimic Mode - PDF Upload:**
```python
from src.agents.question.tools.exam_mimic import mimic_exam_questions

result = await mimic_exam_questions(
    pdf_path="exams/midterm.pdf",
    kb_name="calculus",
    output_dir="data/user/question/mimic_papers",
    max_questions=5
)

print(f"✅ Generated {result['successful_generations']} questions")
print(f"Output: {result['output_file']}")
```

</details>

<details>
<summary><b>Output Location</b></summary>

**Custom Mode:**
```
data/user/question/custom_YYYYMMDD_HHMMSS/
├── background_knowledge.json      # RAG retrieval results
├── question_plan.json              # Question planning
├── question_1_result.json          # Individual question results
├── question_2_result.json
└── ...
```

**Mimic Mode:**
```
data/user/question/mimic_papers/
└── mimic_YYYYMMDD_HHMMSS_{pdf_name}/
    ├── {pdf_name}.pdf                              # Original PDF
    ├── auto/{pdf_name}.md                          # MinerU parsed markdown
    ├── {pdf_name}_YYYYMMDD_HHMMSS_questions.json  # Extracted questions
    └── {pdf_name}_YYYYMMDD_HHMMSS_generated_questions.json  # Generated questions
```

</details>

</details>

---

<details>
<summary><b>🎓 Guided Learning</b></summary>

<details>
<summary><b>Architecture Diagram</b></summary>

![Guided Learning Architecture](assets/figs/guide.png)

</details>

> **Personalized learning system** based on notebook content, automatically generating progressive learning paths through interactive pages and smart Q&A.

**Core Features**

| Feature | Description |
|:---:|:---|
| Multi-Agent Architecture | **LocateAgent**: Identifies 3-5 progressive knowledge points<br>**InteractiveAgent**: Converts to visual HTML pages<br>**ChatAgent**: Provides contextual Q&A<br>**SummaryAgent**: Generates learning summaries |
| Smart Knowledge Location | Automatic analysis of notebook content |
| Interactive Pages | HTML page generation with bug fixing |
| Smart Q&A | Context-aware answers with explanations |
| Progress Tracking | Real-time status with session persistence |
| Cross-Notebook Support | Select records from multiple notebooks |

**Usage Flow**

1. **Select Notebook(s)** — Choose one or multiple notebooks (cross-notebook selection supported)
2. **Generate Learning Plan** — LocateAgent identifies 3-5 core knowledge points
3. **Start Learning** — InteractiveAgent generates HTML visualization
4. **Learning Interaction** — Ask questions, click "Next" to proceed
5. **Complete Learning** — SummaryAgent generates learning summary

<details>
<summary><b>Output Location</b></summary>

```
data/user/guide/
└── session_{session_id}.json    # Complete session state, knowledge points, chat history
```

</details>

</details>

---

<details>
<summary><b>✏️ Interactive IdeaGen (Co-Writer)</b></summary>

<details>
<summary><b>Architecture Diagram</b></summary>

![Interactive IdeaGen Architecture](assets/figs/co-writer.png)

</details>

> **Intelligent Markdown editor** supporting AI-assisted writing, auto-annotation, and TTS narration.

**Core Features**

| Feature | Description |
|:---:|:---|
| Rich Text Editing | Full Markdown syntax support with live preview |
| EditAgent | **Rewrite**: Custom instructions with optional RAG/web context<br>**Shorten**: Compress while preserving key information<br>**Expand**: Add details and context |
| Auto-Annotation | Automatic key content identification and marking |
| NarratorAgent | Script generation, TTS audio, multiple voices (Cherry, Stella, Annie, Cally, Eva, Bella) |
| Context Enhancement | Optional RAG or web search for additional context |
| Multi-Format Export | Markdown, PDF, etc. |

**Usage**

1. Visit http://localhost:{frontend_port}/co_writer
2. Enter or paste text in the editor
3. Use AI features: Rewrite, Shorten, Expand, Auto Mark, Narrate
4. Export to Markdown or PDF

<details>
<summary><b>Output Location</b></summary>

```
data/user/co-writer/
├── audio/                    # TTS audio files
│   └── {operation_id}.mp3
├── tool_calls/               # Tool call history
│   └── {operation_id}_{tool_type}.json
└── history.json              # Edit history
```

</details>

</details>

---

<details>
<summary><b>🔬 Deep Research</b></summary>

<details>
<summary><b>Architecture Diagram</b></summary>

![Deep Research Architecture](assets/figs/deepresearch.png)

</details>

> **DR-in-KG** (Deep Research in Knowledge Graph) — A systematic deep research system based on **Dynamic Topic Queue** architecture, enabling multi-agent collaboration across three phases: **Planning → Researching → Reporting**.

**Core Features**

| Feature | Description |
|:---:|:---|
| Three-Phase Architecture | **Phase 1 (Planning)**: RephraseAgent (topic optimization) + DecomposeAgent (subtopic decomposition)<br>**Phase 2 (Researching)**: ManagerAgent (queue scheduling) + ResearchAgent (research decisions) + NoteAgent (info compression)<br>**Phase 3 (Reporting)**: Deduplication → Three-level outline generation → Report writing with citations |
| Dynamic Topic Queue | Core scheduling system with TopicBlock state management: `PENDING → RESEARCHING → COMPLETED/FAILED`. Supports dynamic topic discovery during research |
| Execution Modes | **Series Mode**: Sequential topic processing<br>**Parallel Mode**: Concurrent multi-topic processing with `AsyncCitationManagerWrapper` for thread-safe operations |
| Multi-Tool Integration | **RAG** (hybrid/naive), **Query Item** (entity lookup), **Paper Search**, **Web Search**, **Code Execution** — dynamically selected by ResearchAgent |
| Unified Citation System | Centralized CitationManager as single source of truth for citation ID generation, ref_number mapping, and deduplication |
| Preset Configurations | **quick**: Fast research (1-2 subtopics, 1-2 iterations)<br>**medium/standard**: Balanced depth (5 subtopics, 4 iterations)<br>**deep**: Thorough research (8 subtopics, 7 iterations)<br>**auto**: Agent autonomously decides depth |

**Citation System Architecture**

The citation system follows a centralized design with CitationManager as the single source of truth:

```
┌─────────────────────────────────────────────────────────────────┐
│                      CitationManager                            │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐  │
│  │  ID Generation  │  │  ref_number Map │  │   Deduplication │  │
│  │  PLAN-XX        │  │  citation_id →  │  │   (papers only) │  │
│  │  CIT-X-XX       │  │  ref_number     │  │                 │  │
│  └────────┬────────┘  └────────┬────────┘  └────────┬────────┘  │
└───────────┼────────────────────┼────────────────────┼───────────┘
            │                    │                    │
     ┌──────┴──────┐      ┌──────┴──────┐      ┌──────┴──────┐
     │DecomposeAgent│      │ReportingAgent│      │ References │
     │ ResearchAgent│      │ (inline [N]) │      │  Section   │
     │  NoteAgent   │      └─────────────┘      └────────────┘
     └─────────────┘
```

| Component | Description |
|:---:|:---|
| ID Format | **PLAN-XX** (planning stage RAG queries) + **CIT-X-XX** (research stage, X=block number) |
| ref_number Mapping | Sequential 1-based numbers built from sorted citation IDs, with paper deduplication |
| Inline Citations | Simple `[N]` format in LLM output, post-processed to clickable `[[N]](#ref-N)` links |
| Citation Table | Clear reference table provided to LLM: `Cite as [1] → (RAG) query preview...` |
| Post-processing | Automatic format conversion + validation to remove invalid citation references |
| Parallel Safety | Thread-safe async methods (`get_next_citation_id_async`, `add_citation_async`) for concurrent execution |

**Parallel Execution Architecture**

When `execution_mode: "parallel"` is enabled, multiple topic blocks are researched concurrently:

```
┌─────────────────────────────────────────────────────────────────────────┐
│                    Parallel Research Execution                          │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│   DynamicTopicQueue                    AsyncCitationManagerWrapper      │
│   ┌─────────────────┐                  ┌─────────────────────────┐      │
│   │ Topic 1 (PENDING)│ ──┐             │  Thread-safe wrapper    │      │
│   │ Topic 2 (PENDING)│ ──┼──→ asyncio  │  for CitationManager    │      │
│   │ Topic 3 (PENDING)│ ──┤   Semaphore │                         │      │
│   │ Topic 4 (PENDING)│ ──┤   (max=5)   │  • get_next_citation_   │      │
│   │ Topic 5 (PENDING)│ ──┘             │    id_async()           │      │
│   └─────────────────┘                  │  • add_citation_async() │      │
│            │                           └───────────┬─────────────┘      │
│            ▼                                       │                    │
│   ┌─────────────────────────────────────────────────────────────┐      │
│   │              Concurrent ResearchAgent Tasks                  │      │
│   │  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐        │      │
│   │  │ Task 1  │  │ Task 2  │  │ Task 3  │  │ Task 4  │  ...   │      │
│   │  │(Topic 1)│  │(Topic 2)│  │(Topic 3)│  │(Topic 4)│        │      │
│   │  └────┬────┘  └────┬────┘  └────┬────┘  └────┬────┘        │      │
│   │       │            │            │            │              │      │
│   │       └────────────┴────────────┴────────────┘              │      │
│   │                         │                                    │      │
│   │                         ▼                                    │      │
│   │              AsyncManagerAgentWrapper                        │      │
│   │              (Thread-safe queue updates)                     │      │
│   └─────────────────────────────────────────────────────────────┘      │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

| Component | Description |
|:---:|:---|
| `asyncio.Semaphore` | Limits concurrent tasks to `max_parallel_topics` (default: 5) |
| `AsyncCitationManagerWrapper` | Wraps CitationManager with `asyncio.Lock()` for thread-safe ID generation |
| `AsyncManagerAgentWrapper` | Ensures queue state updates are atomic across parallel tasks |
| Real-time Progress | Live display of all active research tasks with status indicators |

**Agent Responsibilities**

| Agent | Phase | Responsibility |
|:---:|:---:|:---|
| RephraseAgent | Planning | Optimizes user input topic, supports multi-turn user interaction for refinement |
| DecomposeAgent | Planning | Decomposes topic into subtopics with RAG context, obtains citation IDs from CitationManager |
| ManagerAgent | Researching | Queue state management, task scheduling, dynamic topic addition |
| ResearchAgent | Researching | Knowledge sufficiency check, query planning, tool selection, requests citation IDs before each tool call |
| NoteAgent | Researching | Compresses raw tool outputs into summaries, creates ToolTraces with pre-assigned citation IDs |
| ReportingAgent | Reporting | Builds citation map, generates three-level outline, writes report sections with citation tables, post-processes citations |

**Report Generation Pipeline**

```
1. Build Citation Map     →  CitationManager.build_ref_number_map()
2. Generate Outline       →  Three-level headings (H1 → H2 → H3)
3. Write Sections         →  LLM uses [N] citations with provided citation table
4. Post-process           →  Convert [N] → [[N]](#ref-N), validate references
5. Generate References    →  Academic-style entries with collapsible source details
```

**Usage**

1. Visit http://localhost:{frontend_port}/research
2. Enter research topic
3. Select research mode (quick/medium/deep/auto)
4. Watch real-time progress with parallel/series execution
5. View structured report with clickable inline citations
6. Export as Markdown or PDF (with proper page splitting and Mermaid diagram support)

<details>
<summary><b>CLI</b></summary>

```bash
# Quick mode (fast research)
python src/agents/research/main.py --topic "Deep Learning Basics" --preset quick

# Medium mode (balanced)
python src/agents/research/main.py --topic "Transformer Architecture" --preset medium

# Deep mode (thorough research)
python src/agents/research/main.py --topic "Graph Neural Networks" --preset deep

# Auto mode (agent decides depth)
python src/agents/research/main.py --topic "Reinforcement Learning" --preset auto
```

</details>

<details>
<summary><b>Python API</b></summary>

```python
import asyncio
from src.agents.research import ResearchPipeline
from src.core.core import get_llm_config, load_config_with_main

async def main():
    # Load configuration (main.yaml merged with any module-specific overrides)
    config = load_config_with_main("research_config.yaml")
    llm_config = get_llm_config()

    # Create pipeline (agent parameters loaded from agents.yaml automatically)
    pipeline = ResearchPipeline(
        config=config,
        api_key=llm_config["api_key"],
        base_url=llm_config["base_url"],
        kb_name="ai_textbook"  # Optional: override knowledge base
    )

    # Run research
    result = await pipeline.run(topic="Attention Mechanisms in Deep Learning")
    print(f"Report saved to: {result['final_report_path']}")

asyncio.run(main())
```

</details>

<details>
<summary><b>Output Location</b></summary>

```
data/user/research/
├── reports/                          # Final research reports
│   ├── research_YYYYMMDD_HHMMSS.md   # Markdown report with clickable citations [[N]](#ref-N)
│   └── research_*_metadata.json      # Research metadata and statistics
└── cache/                            # Research process cache
    └── research_YYYYMMDD_HHMMSS/
        ├── queue.json                # DynamicTopicQueue state (TopicBlocks + ToolTraces)
        ├── citations.json            # Citation registry with ID counters and ref_number mapping
        │                             #   - citations: {citation_id: citation_info}
        │                             #   - counters: {plan_counter, block_counters}
        ├── step1_planning.json       # Planning phase results (subtopics + PLAN-XX citations)
        ├── planning_progress.json    # Planning progress events
        ├── researching_progress.json # Researching progress events
        ├── reporting_progress.json   # Reporting progress events
        ├── outline.json              # Three-level report outline structure
        └── token_cost_summary.json   # Token usage statistics
```

**Citation File Structure** (`citations.json`):
```json
{
  "research_id": "research_20241209_120000",
  "citations": {
    "PLAN-01": {"citation_id": "PLAN-01", "tool_type": "rag_hybrid", "query": "...", "summary": "..."},
    "CIT-1-01": {"citation_id": "CIT-1-01", "tool_type": "paper_search", "papers": [...], ...}
  },
  "counters": {
    "plan_counter": 2,
    "block_counters": {"1": 3, "2": 2}
  }
}
```

</details>

<details>
<summary><b>Configuration Options</b></summary>

Key configuration in `config/main.yaml` (research section) and `config/agents.yaml`:

```yaml
# config/agents.yaml - Agent LLM parameters
research:
  temperature: 0.5
  max_tokens: 12000

# config/main.yaml - Research settings
research:
  # Execution Mode
  researching:
    execution_mode: "parallel"    # "series" or "parallel"
    max_parallel_topics: 5        # Max concurrent topics
    max_iterations: 5             # Max iterations per topic

  # Tool Switches
    enable_rag_hybrid: true       # Hybrid RAG retrieval
    enable_rag_naive: true        # Basic RAG retrieval
    enable_paper_search: true     # Academic paper search
    enable_web_search: true       # Web search (also controlled by tools.web_search.enabled)
    enable_run_code: true         # Code execution

  # Queue Limits
  queue:
    max_length: 5                 # Maximum topics in queue

  # Reporting
  reporting:
    enable_inline_citations: true # Enable clickable [N] citations in report

  # Presets: quick, medium, deep, auto

# Global tool switches in tools section
tools:
  web_search:
    enabled: true                 # Global web search switch (higher priority)
```

</details>

</details>

---

<details>
<summary><b>💡 Automated IdeaGen</b></summary>

<details>
<summary><b>Architecture Diagram</b></summary>

![Automated IdeaGen Architecture](assets/figs/ideagen.png)

</details>

> **Research idea generation system** that extracts knowledge points from notebook records and generates research ideas through multi-stage filtering.

**Core Features**

| Feature | Description |
|:---:|:---|
| MaterialOrganizerAgent | Extracts knowledge points from notebook records |
| Multi-Stage Filtering | **Loose Filter** → **Explore Ideas** (5+ per point) → **Strict Filter** → **Generate Markdown** |
| Idea Exploration | Innovative thinking from multiple dimensions |
| Structured Output | Organized markdown with knowledge points and ideas |
| Progress Callbacks | Real-time updates for each stage |

**Usage**

1. Visit http://localhost:{frontend_port}/ideagen
2. Select a notebook with records
3. Optionally provide user thoughts/preferences
4. Click "Generate Ideas"
5. View generated research ideas organized by knowledge points

<details>
<summary><b>Python API</b></summary>

```python
import asyncio
from src.agents.ideagen import IdeaGenerationWorkflow, MaterialOrganizerAgent
from src.core.core import get_llm_config

async def main():
    llm_config = get_llm_config()

    # Step 1: Extract knowledge points from materials
    organizer = MaterialOrganizerAgent(
        api_key=llm_config["api_key"],
        base_url=llm_config["base_url"]
    )
    knowledge_points = await organizer.extract_knowledge_points(
        "Your learning materials or notebook content here"
    )

    # Step 2: Generate research ideas
    workflow = IdeaGenerationWorkflow(
        api_key=llm_config["api_key"],
        base_url=llm_config["base_url"]
    )
    result = await workflow.process(knowledge_points)
    print(result)  # Markdown formatted research ideas

asyncio.run(main())
```

</details>

</details>

---

<details>
<summary><b>📊 Dashboard + Knowledge Base Management</b></summary>

> **Unified system entry** providing activity tracking, knowledge base management, and system status monitoring.

**Key Features**

| Feature | Description |
|:---:|:---|
| Activity Statistics | Recent solving/generation/research records |
| Knowledge Base Overview | KB list, statistics, incremental updates |
| Notebook Statistics | Notebook counts, record distribution |
| Quick Actions | One-click access to all modules |

**Usage**

- **Web Interface**: Visit http://localhost:{frontend_port} to view system overview
- **Create KB**: Click "New Knowledge Base", upload PDF/Markdown documents
- **View Activity**: Check recent learning activities on Dashboard

</details>

---

<details>
<summary><b>📓 Notebook</b></summary>

> **Unified learning record management**, connecting outputs from all modules to create a personalized learning knowledge base.

**Core Features**

| Feature | Description |
|:---:|:---|
| Multi-Notebook Management | Create, edit, delete notebooks |
| Unified Record Storage | Integrate solving/generation/research/Interactive IdeaGen records |
| Categorization Tags | Auto-categorize by type, knowledge base |
| Custom Appearance | Color, icon personalization |

**Usage**

1. Visit http://localhost:{frontend_port}/notebook
2. Create new notebook (set name, description, color, icon)
3. After completing tasks in other modules, click "Add to Notebook"
4. View and manage all records on the notebook page

</details>

---

### 📖 Module Documentation

<table>
<tr>
<td align="center"><a href="config/README.md">Configuration</a></td>
<td align="center"><a href="data/README.md">Data Directory</a></td>
<td align="center"><a href="src/api/README.md">API Backend</a></td>
<td align="center"><a href="src/core/README.md">Core Utilities</a></td>
</tr>
<tr>
<td align="center"><a href="src/knowledge/README.md">Knowledge Base</a></td>
<td align="center"><a href="src/tools/README.md">Tools</a></td>
<td align="center"><a href="web/README.md">Web Frontend</a></td>
<td align="center"><a href="src/agents/solve/README.md">Solve Module</a></td>
</tr>
<tr>
<td align="center"><a href="src/agents/question/README.md">Question Module</a></td>
<td align="center"><a href="src/agents/research/README.md">Research Module</a></td>
<td align="center"><a href="src/agents/co_writer/README.md">Interactive IdeaGen Module</a></td>
<td align="center"><a href="src/agents/guide/README.md">Guide Module</a></td>
</tr>
<tr>
<td align="center" colspan="4"><a href="src/agents/ideagen/README.md">Automated IdeaGen Module</a></td>
</tr>
</table>

## ❓ FAQ

<details>
<summary><b>Backend fails to start?</b></summary>

**Checklist**
- Confirm Python version >= 3.10
- Confirm all dependencies installed: `pip install -r requirements.txt`
- Check if port 8001 is in use
- Check `.env` file configuration

**Solutions**
- **Change port**: Set `BACKEND_PORT=9001` in `.env` file
- **Check logs**: Review terminal error messages

</details>

<details>
<summary><b>Port occupied after Ctrl+C?</b></summary>

**Problem**

After pressing Ctrl+C during a running task (e.g., deep research), restarting shows "port already in use" error.

**Cause**

Ctrl+C sometimes only terminates the frontend process while the backend continues running in the background.

**Solution**

```bash
# macOS/Linux: Find and kill the process
lsof -i :8001
kill -9 <PID>

# Windows: Find and kill the process
netstat -ano | findstr :8001
taskkill /PID <PID> /F
```

Then restart the service with `python scripts/start_web.py`.

</details>

<details>
<summary><b>npm: command not found error?</b></summary>

**Problem**

Running `scripts/start_web.py` shows `npm: command not found` or exit status 127.

**Checklist**
- Check if npm is installed: `npm --version`
- Check if Node.js is installed: `node --version`
- Confirm conda environment is activated (if using conda)

**Solutions**
```bash
# Option A: Using Conda (Recommended)
conda install -c conda-forge nodejs

# Option B: Using Official Installer
# Download from https://nodejs.org/

# Option C: Using nvm
nvm install 18
nvm use 18
```

**Verify Installation**
```bash
node --version  # Should show v18.x.x or higher
npm --version   # Should show version number
```

</details>

<details>
<summary><b>Long path names on Windows installation?</b></summary>

**Problem**

On Windows, you may encounter errors related to long file paths during installation, such as "The filename or extension is too long" or similar path length issues.

**Cause**

Windows has a default limitation on path lengths (260 characters), which can be exceeded by DeepTutor's nested directory structures and dependencies.

**Solution**

Enable long path support system-wide by running the following command in an Administrator Command Prompt:

```cmd
reg add "HKLM\SYSTEM\CurrentControlSet\Control\FileSystem" /v LongPathsEnabled /t REG_DWORD /d 1 /f
```

After running this command, restart your terminal for the changes to take effect.

</details>

<details>
<summary><b>Frontend cannot connect to backend?</b></summary>

**Checklist**
- Confirm backend is running (visit http://localhost:8001/docs)
- Check browser console for error messages

**Solution**

Create `.env.local` in `web` directory:

```bash
NEXT_PUBLIC_API_BASE=http://localhost:8001
```

</details>

<details>
<summary><b>Docker: Frontend cannot connect in cloud deployment?</b></summary>

**Problem**

When deploying to a cloud server, the frontend shows connection errors like "Failed to fetch" or "NEXT_PUBLIC_API_BASE is not configured".

**Cause**

The default API URL is `localhost:8001`, which points to the user's local machine in the browser, not your server.

**Solution**

Set the `NEXT_PUBLIC_API_BASE_EXTERNAL` environment variable to your server's public URL:

```bash
# Using docker run
docker run -d --name deeptutor \
  -e NEXT_PUBLIC_API_BASE_EXTERNAL=https://your-server.com:8001 \
  ... other options ...
  ghcr.io/hkuds/deeptutor:latest

# Or in .env file
NEXT_PUBLIC_API_BASE_EXTERNAL=https://your-server.com:8001
```

**Custom Port Example:**
```bash
# If using backend port 9001
-e BACKEND_PORT=9001 \
-e NEXT_PUBLIC_API_BASE_EXTERNAL=https://your-server.com:9001
```

</details>

<details>
<summary><b>Docker: How to use custom ports?</b></summary>

**Solution**

Set both the port environment variables AND the port mappings:

```bash
docker run -d --name deeptutor \
  -p 9001:9001 -p 4000:4000 \
  -e BACKEND_PORT=9001 \
  -e FRONTEND_PORT=4000 \
  -e NEXT_PUBLIC_API_BASE_EXTERNAL=http://localhost:9001 \
  ... other env vars ...
  ghcr.io/hkuds/deeptutor:latest
```

**Important**: The `-p` port mapping must match the `BACKEND_PORT`/`FRONTEND_PORT` values.

</details>

<details>
<summary><b>WebSocket connection fails?</b></summary>

**Checklist**
- Confirm backend is running
- Check firewall settings
- Confirm WebSocket URL is correct

**Solution**
- **Check backend logs**
- **Confirm URL format**: `ws://localhost:8001/api/v1/...`

</details>

<details>
<summary><b>Settings page shows "Error loading data" with HTTPS reverse proxy?</b></summary>

**Problem**

When deploying behind an HTTPS reverse proxy (e.g., nginx), the Settings page shows "Error loading data" and browser DevTools reveals that HTTPS requests are being redirected to HTTP (307 redirect).

**Cause**

This issue has been fixed in v0.5.0+. If you're using an older version, the problem was caused by FastAPI's automatic trailing slash redirects generating HTTP URLs instead of preserving the original HTTPS protocol.

**Solution (for v0.5.0+)**

Update to the latest version. The fix disables automatic slash redirects to prevent protocol downgrade.

**Recommended nginx Configuration**

When using nginx as an HTTPS reverse proxy, use the following configuration:

```nginx
# Frontend
location / {
    proxy_pass http://localhost:3782;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
}

# Backend API
location /api/ {
    proxy_pass http://localhost:8001;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;  # Important: preserves original protocol
}

# WebSocket support
location /api/v1/ {
    proxy_pass http://localhost:8001;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-Proto $scheme;
}
```

**Environment Variable**

Set in `.env`:
```bash
NEXT_PUBLIC_API_BASE=https://your-domain.com:port
```

See: [GitHub Issue #112](https://github.com/HKUDS/DeepTutor/issues/112)

</details>

<details>
<summary><b>Where are module outputs stored?</b></summary>

| Module | Output Path |
|:---:|:---|
| Solve | `data/user/solve/solve_YYYYMMDD_HHMMSS/` |
| Question | `data/user/question/question_YYYYMMDD_HHMMSS/` |
| Research | `data/user/research/reports/` |
| Interactive IdeaGen | `data/user/co-writer/` |
| Notebook | `data/user/notebook/` |
| Guide | `data/user/guide/session_{session_id}.json` |
| Logs | `data/user/logs/` |

</details>

<details>
<summary><b>How to add a new knowledge base?</b></summary>

**Web Interface**
1. Visit http://localhost:{frontend_port}/knowledge
2. Click "New Knowledge Base"
3. Enter knowledge base name
4. Upload PDF/TXT/MD documents
5. System will process documents in background

**CLI**
```bash
python -m src.knowledge.start_kb init <kb_name> --docs <pdf_path>
```

</details>

<details>
<summary><b>How to incrementally add documents to existing KB?</b></summary>

**CLI (Recommended)**
```bash
python -m src.knowledge.add_documents <kb_name> --docs <new_document.pdf>
```

**Benefits**
- Only processes new documents, saves time and API costs
- Automatically merges with existing knowledge graph
- Preserves all existing data

</details>

<details>
<summary><b>Numbered items extraction failed with uvloop.Loop error?</b></summary>

**Problem**

When initializing a knowledge base, you may encounter this error:
```
ValueError: Can't patch loop of type <class 'uvloop.Loop'>
```

This occurs because Uvicorn uses `uvloop` event loop by default, which is incompatible with `nest_asyncio`.

**Solution**

Use one of the following methods to extract numbered items:

```bash
# Option 1: Using the shell script (recommended)
./scripts/extract_numbered_items.sh <kb_name>

# Option 2: Direct Python command
python src/knowledge/extract_numbered_items.py --kb <kb_name> --base-dir ./data/knowledge_bases
```

This will extract numbered items (Definitions, Theorems, Equations, etc.) from your knowledge base without reinitializing it.

</details>


</div>

## ⭐ Star History

<div align="center">

<p>
  <a href="https://github.com/HKUDS/DeepTutor/stargazers"><img src="assets/roster/stargazers.svg" alt="Stargazers"/></a>
  &nbsp;&nbsp;
  <a href="https://github.com/HKUDS/DeepTutor/network/members"><img src="assets/roster/forkers.svg" alt="Forkers"/></a>
</p>

<a href="https://www.star-history.com/#HKUDS/DeepTutor&type=timeline&legend=top-left">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/svg?repos=HKUDS/DeepTutor&type=timeline&theme=dark&legend=top-left" />
    <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/svg?repos=HKUDS/DeepTutor&type=timeline&legend=top-left" />
    <img alt="Star History Chart" src="https://api.star-history.com/svg?repos=HKUDS/DeepTutor&type=timeline&legend=top-left" />
  </picture>
</a>

</div>

## 🤝 Contribution

<div align="center">

We hope DeepTutor could become a gift for the community. 🎁

<a href="https://github.com/HKUDS/DeepTutor/graphs/contributors">
  <img src="https://contrib.rocks/image?repo=HKUDS/DeepTutor&max=999" alt="Contributors to HKUDS/DeepTutor" />
</a>

</div>

## 🔗 Related Projects

<div align="center">

| [⚡ LightRAG](https://github.com/HKUDS/LightRAG) | [🎨 RAG-Anything](https://github.com/HKUDS/RAG-Anything) | [💻 DeepCode](https://github.com/HKUDS/DeepCode) | [🔬 AI-Researcher](https://github.com/HKUDS/AI-Researcher) |
|:---:|:---:|:---:|:---:|
| Simple and Fast RAG | Multimodal RAG | AI Code Assistant | Research Automation |

**[Data Intelligence Lab @ HKU](https://github.com/HKUDS)**

[⭐ Star us](https://github.com/HKUDS/DeepTutor/stargazers) · [🐛 Report a bug](https://github.com/HKUDS/DeepTutor/issues) · [💬 Discussions](https://github.com/HKUDS/DeepTutor/discussions)

---

This project is licensed under the ***[AGPL-3.0 License](LICENSE)***.

*✨ Thanks for visiting **DeepTutor**!*

</div>
