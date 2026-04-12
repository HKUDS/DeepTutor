<div align="center">

<img src="../../assets/logo-ver2.png" alt="DeepTutor" width="140" style="border-radius: 15px;">

# DeepTutor: Hacia un tutorizado personalizado basado en agentes

[![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-3776AB?style=flat-square&logo=python&logoColor=white)](https://www.python.org/downloads/)
[![Next.js 16](https://img.shields.io/badge/Next.js-16-000000?style=flat-square&logo=next.js&logoColor=white)](https://nextjs.org/)
[![License](https://img.shields.io/badge/License-Apache_2.0-blue?style=flat-square)](../../LICENSE)
[![GitHub release](https://img.shields.io/github/v/release/HKUDS/DeepTutor?style=flat-square&color=brightgreen)](https://github.com/HKUDS/DeepTutor/releases)
[![GitHub last commit](https://img.shields.io/github/last-commit/HKUDS/DeepTutor?style=flat-square)](https://github.com/HKUDS/DeepTutor/commits)

[![Discord](https://img.shields.io/badge/Discord-Community-5865F2?style=flat-square&logo=discord&logoColor=white)](https://discord.gg/eRsjPgMU4t)
[![Feishu](https://img.shields.io/badge/Feishu-Group-00D4AA?style=flat-square&logo=feishu&logoColor=white)](../../Communication.md)
[![WeChat](https://img.shields.io/badge/WeChat-Group-07C160?style=flat-square&logo=wechat&logoColor=white)](https://github.com/HKUDS/DeepTutor/issues/78)

[Funciones](#key-features) · [Primeros pasos](#get-started) · [Explorar](#explore-deeptutor) · [TutorBot](#tutorbot) · [CLI](#deeptutor-cli-guide) · [Comunidad](#community)

[🇬🇧 English](../../README.md) · [🇨🇳 中文](README_CN.md) · [🇯🇵 日本語](README_JA.md) · [🇫🇷 Français](README_FR.md) · [🇸🇦 العربية](README_AR.md) · [🇷🇺 Русский](README_RU.md) · [🇮🇳 हिन्दी](README_HI.md) · [🇵🇹 Português](README_PT.md)

</div>

---
### 📰 Noticias

> **[2026.3.24]** ¡DeepTutor v1.0.0 ya está aquí! ✨ Evolución nativa de agentes: refactor ligero, TutorBot y modos flexibles bajo Apache-2.0.

> **[2026.2.6]** 🚀 ¡10k estrellas en solo 39 días! Gracias a la comunidad.

> **[2026.1.1]** Feliz año nuevo. Únete a [Discord](https://discord.gg/eRsjPgMU4t), [WeChat](https://github.com/HKUDS/DeepTutor/issues/78) o [Discussions](https://github.com/HKUDS/DeepTutor/discussions).

> **[2025.12.29]** DeepTutor se publica oficialmente.

### 📦 Lanzamientos

> **[2026.3.24]** [v1.0.0](https://github.com/HKUDS/DeepTutor/releases/tag/v1.0.0) — Refactor nativo de agentes, integración flexible de herramientas, entradas CLI y SDK, TutorBot con nanobot, Co-Writer, aprendizaje guiado y memoria persistente.

<details>
<summary><b>Lanzamientos anteriores</b></summary>

> **[2026.1.23]** [v0.6.0](https://github.com/HKUDS/DeepTutor/releases/tag/v0.6.0) — Persistencia de sesión, carga incremental, importación flexible de RAG, localización completa al chino.

> **[2026.1.18]** [v0.5.2](https://github.com/HKUDS/DeepTutor/releases/tag/v0.5.2) — Docling, logs y correcciones.

> **[2026.1.15]** [v0.5.0](https://github.com/HKUDS/DeepTutor/releases/tag/v0.5.0) — Configuración unificada, RAG por KB, generación de preguntas, barra lateral.

> **[2026.1.9]** [v0.4.0](https://github.com/HKUDS/DeepTutor/releases/tag/v0.4.0) — Multi-proveedor LLM/embeddings, nueva home, desacoplamiento RAG, variables de entorno.

> **[2026.1.5]** [v0.3.0](https://github.com/HKUDS/DeepTutor/releases/tag/v0.3.0) — PromptManager, CI/CD, imágenes GHCR.

> **[2026.1.2]** [v0.2.0](https://github.com/HKUDS/DeepTutor/releases/tag/v0.2.0) — Docker, Next.js 16 y React 19, WebSocket, vulnerabilidades.

</details>

<a id="key-features"></a>
## ✨ Funciones principales

- **Espacio de chat unificado** — Cinco modos, un hilo: Chat, Deep Solve, generación de cuestionarios, Deep Research y Math Animator comparten contexto.
- **TutorBots personales** — No son chatbots: tutores autónomos con espacio de trabajo, memoria, personalidad y habilidades. Impulsados por [nanobot](https://github.com/HKUDS/nanobot).
- **AI Co-Writer** — Markdown con la IA como colaborador de primer nivel: reescribir, ampliar o acortar con KB y web.
- **Aprendizaje guiado** — Convierte tus materiales en recorridos visuales por pasos.
- **Centro de conocimiento** — PDF, Markdown y texto para bases RAG; cuadernos por color.
- **Memoria persistente** — Resumen de progreso y perfil del aprendiz; compartido con TutorBots.
- **CLI nativo para agentes** — Capacidades, KB, sesiones y TutorBot en un comando; Rich y JSON. Entrega [`SKILL.md`](../../SKILL.md) a tu agente.

---

<a id="get-started"></a>
## 🚀 Primeros pasos

### Opción A — Tour de configuración (recomendado)

Un **script interactivo** cubre dependencias, entorno, pruebas de conexión y arranque.

```bash
git clone https://github.com/HKUDS/DeepTutor.git
cd DeepTutor

conda create -n deeptutor python=3.11 && conda activate deeptutor
# o: python -m venv .venv && source .venv/bin/activate

python scripts/start_tour.py
```

- **Modo web** (recomendado) — Perfil de dependencias, pip + npm, servidor temporal y página de **Ajustes** con tour de 4 pasos (LLM, embeddings, búsqueda).
- **Modo CLI** — Todo en terminal.

Abre [http://localhost:3782](http://localhost:3782).

<a id="option-b-manual"></a>
### Opción B — Instalación local manual

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

| Servicio | Puerto |
|:---:|:---:|
| Backend | `8001` |
| Frontend | `3782` |

### Opción C — Docker

```bash
git clone https://github.com/HKUDS/DeepTutor.git
cd DeepTutor
cp .env.example .env
```

Igual que [opción B](#option-b-manual).

**2a. Imagen oficial** — [GHCR](https://github.com/HKUDS/DeepTutor/pkgs/container/deeptutor)

```bash
docker compose -f docker-compose.ghcr.yml up -d
```

**2b. Compilar** — `docker compose up -d`

**3.** [http://localhost:3782](http://localhost:3782)

```bash
docker compose logs -f
docker compose down
```

<details>
<summary><b>Nube / servidor remoto</b></summary>

```dotenv
NEXT_PUBLIC_API_BASE_EXTERNAL=https://your-server.com:8001
```

</details>

<details>
<summary><b>Modo desarrollo (recarga en caliente)</b></summary>

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up
```

</details>

<details>
<summary><b>Puertos personalizados</b></summary>

```dotenv
BACKEND_PORT=9001
FRONTEND_PORT=4000
```

</details>

<details>
<summary><b>Persistencia de datos</b></summary>

| Ruta contenedor | Host | Contenido |
|:---|:---|:---|
| `/app/data/user` | `./data/user` | Ajustes, memoria, espacio de trabajo, sesiones, logs |
| `/app/data/knowledge_bases` | `./data/knowledge_bases` | Documentos e índices |

</details>

<details>
<summary><b>Variables de entorno</b></summary>

| Variable | Obligatorio | Descripción |
|:---|:---:|:---|
| `LLM_BINDING` | **Sí** | Proveedor LLM |
| `LLM_MODEL` | **Sí** | Modelo |
| `LLM_API_KEY` | **Sí** | Clave |
| `LLM_HOST` | **Sí** | URL |
| `EMBEDDING_BINDING` | **Sí** | Proveedor de embeddings |
| `EMBEDDING_MODEL` | **Sí** | Modelo |
| `EMBEDDING_API_KEY` | **Sí** | Clave |
| `EMBEDDING_HOST` | **Sí** | URL |
| `EMBEDDING_DIMENSION` | **Sí** | Dimensión |
| `SEARCH_PROVIDER` | No | Búsqueda |
| `SEARCH_API_KEY` | No | Clave |
| `BACKEND_PORT` | No | Predeterminado `8001` |
| `FRONTEND_PORT` | No | Predeterminado `3782` |
| `NEXT_PUBLIC_API_BASE_EXTERNAL` | No | URL pública |
| `DISABLE_SSL_VERIFY` | No | Predeterminado `false` |

</details>

### Opción D — Solo CLI

```bash
pip install -e ".[cli]"
deeptutor chat
deeptutor run chat "Explain Fourier transform"
deeptutor run deep_solve "Solve x^2 = 4"
deeptutor kb create my-kb --doc textbook.pdf
```

> Guía completa: [DeepTutor CLI](#deeptutor-cli-guide).

---

<a id="explore-deeptutor"></a>
## 📖 Explorar DeepTutor

<div align="center">
<img src="../../assets/figs/deeptutor-architecture.png" alt="Arquitectura DeepTutor" width="800">
</div>

### 💬 Chat — Espacio inteligente unificado

<div align="center">
<img src="../../assets/figs/dt-chat.png" alt="Chat" width="800">
</div>

Cinco modos en un solo espacio con **gestión unificada del contexto**.

| Modo | Qué hace |
|:---|:---|
| **Chat** | RAG, búsqueda web, ejecución de código, razonamiento, lluvia de ideas, papers. |
| **Deep Solve** | Resolución multiagente con citas. |
| **Generación de cuestionarios** | Evaluaciones ancladas a la KB. |
| **Deep Research** | Subtemas, agentes paralelos, informe citado. |
| **Math Animator** | Animaciones con Manim. |

Las herramientas están **desacopladas de los flujos** — eliges qué activar.

### ✍️ Co-Writer — IA en el editor

<div align="center">
<img src="../../assets/figs/dt-cowriter.png" alt="Co-Writer" width="800">
</div>

Editor Markdown completo: **Reescribir**, **Ampliar**, **Acortar** con KB o web; deshacer/rehacer; guardar en cuadernos.

### 🎓 Aprendizaje guiado

<div align="center">
<img src="../../assets/figs/dt-guide.png" alt="Aprendizaje guiado" width="800">
</div>

1. Plan de aprendizaje (3–5 puntos).  
2. Páginas interactivas HTML.  
3. Preguntas en contexto por paso.  
4. Resumen al terminar.

### 📚 Gestión del conocimiento

<div align="center">
<img src="../../assets/figs/dt-knowledge.png" alt="Conocimiento" width="800">
</div>

- **Bases de conocimiento** — PDF, TXT, Markdown; añadir de forma incremental.  
- **Cuadernos** — Registros por sesiones y colores.

### 🧠 Memoria

<div align="center">
<img src="../../assets/figs/dt-memory.png" alt="Memoria" width="800">
</div>

- **Resumen** — Progreso de estudio.  
- **Perfil** — Preferencias, nivel, objetivos, estilo. Compartido con TutorBots.

---

<a id="tutorbot"></a>
### 🦞 TutorBot — Tutores de IA persistentes y autónomos

<div align="center">
<img src="../../assets/figs/tutorbot-architecture.png" alt="Arquitectura TutorBot" width="800">
</div>

No es un chatbot: es un **agente multiinstancia** persistente basado en [nanobot](https://github.com/HKUDS/nanobot). Cada instancia tiene su bucle, espacio de trabajo, memoria y personalidad.

<div align="center">
<img src="../../assets/figs/tb.png" alt="TutorBot" width="800">
</div>

- **Plantillas Soul** — Personalidad y filosofía docente.  
- **Espacio independiente** — Memoria, sesiones, habilidades; acceso a la capa compartida de DeepTutor.  
- **Heartbeat proactivo** — Recordatorios y tareas programadas.  
- **Acceso completo a herramientas** — RAG, código, web, papers, razonamiento, lluvia de ideas.  
- **Aprendizaje de habilidades** — Archivos de skill en el espacio de trabajo.  
- **Multicanal** — Telegram, Discord, Slack, Feishu, WeCom, DingTalk, correo, etc.  
- **Equipos y subagentes** — Tareas largas y complejas.

```bash
deeptutor bot create math-tutor --persona "Socratic math teacher who uses probing questions"
deeptutor bot create writing-coach --persona "Patient, detail-oriented writing mentor"
deeptutor bot list
```

---

<a id="deeptutor-cli-guide"></a>
### ⌨️ DeepTutor CLI — Interfaz nativa para agentes

<div align="center">
<img src="../../assets/figs/cli-architecture.png" alt="CLI" width="800">
</div>

CLI completo: capacidades, KB, sesiones, memoria y TutorBot sin navegador. Salida Rich para humanos y JSON para agentes. [`SKILL.md`](../../SKILL.md) para agentes con herramientas.

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
<summary><b>Referencia completa de comandos CLI</b></summary>

| Comando | Descripción |
|:---|:---|
| `deeptutor run <capability> <message>` | Una pasada |
| `deeptutor chat` | REPL |
| `deeptutor serve` | Servidor API |

**`deeptutor bot`** — list, create, start, stop

**`deeptutor kb`** — list, info, create, add, search, set-default, delete

**`deeptutor memory`** — show, clear

**`deeptutor session`** — list, show, open, rename, delete

**`deeptutor notebook`** — list, create, show, add-md, replace-md, remove-record

**config / plugin / provider** — config show, plugin list/info, provider login

</details>

<a id="community"></a>
## 🌐 Comunidad y ecosistema

| Proyecto | Papel |
|:---|:---|
| [**nanobot**](https://github.com/HKUDS/nanobot) | Motor ligero de TutorBot |
| [**LlamaIndex**](https://github.com/run-llama/llama_index) | RAG e indexación |
| [**ManimCat**](https://github.com/Wing900/ManimCat) | Math Animator |

| [⚡ LightRAG](https://github.com/HKUDS/LightRAG) | [🤖 AutoAgent](https://github.com/HKUDS/AutoAgent) | [🔬 AI-Researcher](https://github.com/HKUDS/AI-Researcher) | [🧬 nanobot](https://github.com/HKUDS/nanobot) |
|:---:|:---:|:---:|:---:|
| RAG rápido | Agentes sin código | Investigación automática | Agente ultraligero |

## 🤝 Contribuir

<div align="center">
<a href="https://github.com/HKUDS/DeepTutor/graphs/contributors">
  <img src="https://contrib.rocks/image?repo=HKUDS/DeepTutor&max=999" alt="Contributors" />
</a>
</div>

Consulta [CONTRIBUTING.md](../../CONTRIBUTING.md).

## ⭐ Historial de estrellas

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

[Licencia Apache 2.0](../../LICENSE)

<p>
  <img src="https://visitor-badge.laobi.icu/badge?page_id=HKUDS.DeepTutor&style=for-the-badge&color=00d4ff" alt="Views">
</p>

</div>
