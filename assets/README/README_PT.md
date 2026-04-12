<div align="center">

<img src="../../assets/logo-ver2.png" alt="DeepTutor" width="140" style="border-radius: 15px;">

# DeepTutor: Rumo a um tutorado personalizado baseado em agentes

[![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-3776AB?style=flat-square&logo=python&logoColor=white)](https://www.python.org/downloads/)
[![Next.js 16](https://img.shields.io/badge/Next.js-16-000000?style=flat-square&logo=next.js&logoColor=white)](https://nextjs.org/)
[![License](https://img.shields.io/badge/License-Apache_2.0-blue?style=flat-square)](../../LICENSE)
[![GitHub release](https://img.shields.io/github/v/release/HKUDS/DeepTutor?style=flat-square&color=brightgreen)](https://github.com/HKUDS/DeepTutor/releases)
[![GitHub last commit](https://img.shields.io/github/last-commit/HKUDS/DeepTutor?style=flat-square)](https://github.com/HKUDS/DeepTutor/commits)

[![Discord](https://img.shields.io/badge/Discord-Community-5865F2?style=flat-square&logo=discord&logoColor=white)](https://discord.gg/eRsjPgMU4t)
[![Feishu](https://img.shields.io/badge/Feishu-Group-00D4AA?style=flat-square&logo=feishu&logoColor=white)](../../Communication.md)
[![WeChat](https://img.shields.io/badge/WeChat-Group-07C160?style=flat-square&logo=wechat&logoColor=white)](https://github.com/HKUDS/DeepTutor/issues/78)

[Recursos](#key-features) · [Começar](#get-started) · [Explorar](#explore-deeptutor) · [TutorBot](#tutorbot) · [CLI](#deeptutor-cli-guide) · [Comunidade](#community)

[🇬🇧 English](../../README.md) · [🇨🇳 中文](README_CN.md) · [🇯🇵 日本語](README_JA.md) · [🇪🇸 Español](README_ES.md) · [🇫🇷 Français](README_FR.md) · [🇸🇦 العربية](README_AR.md) · [🇷🇺 Русский](README_RU.md) · [🇮🇳 हिन्दी](README_HI.md)

</div>

---
### 📰 Notícias

> **[2026.3.24]** DeepTutor v1.0.0 chegou ✨ — evolução nativa de agentes: refactor leve, TutorBot e modos flexíveis sob Apache-2.0.

> **[2026.2.6]** 🚀 10k estrelas em 39 dias — obrigado à comunidade!

> **[2026.1.1]** Feliz Ano Novo! Junte-se ao [Discord](https://discord.gg/eRsjPgMU4t), [WeChat](https://github.com/HKUDS/DeepTutor/issues/78) ou [Discussions](https://github.com/HKUDS/DeepTutor/discussions).

> **[2025.12.29]** DeepTutor é lançado oficialmente.

### 📦 Lançamentos

> **[2026.3.24]** [v1.0.0](https://github.com/HKUDS/DeepTutor/releases/tag/v1.0.0) — Refatoração nativa de agentes, integração flexível de ferramentas, entradas CLI e SDK, TutorBot com nanobot, Co-Writer, aprendizado guiado e memória persistente.

<details>
<summary><b>Lançamentos anteriores</b></summary>

> **[2026.1.23]** [v0.6.0](https://github.com/HKUDS/DeepTutor/releases/tag/v0.6.0) — Persistência de sessão, upload incremental, RAG flexível, localização em chinês.

> **[2026.1.18]** [v0.5.2](https://github.com/HKUDS/DeepTutor/releases/tag/v0.5.2) — Docling, logs, correções.

> **[2026.1.15]** [v0.5.0](https://github.com/HKUDS/DeepTutor/releases/tag/v0.5.0) — Config unificada, RAG por KB, geração de questões, barra lateral.

> **[2026.1.9]** [v0.4.0](https://github.com/HKUDS/DeepTutor/releases/tag/v0.4.0) — Multi-provedor LLM/embeddings, nova home, desacoplamento RAG, variáveis de ambiente.

> **[2026.1.5]** [v0.3.0](https://github.com/HKUDS/DeepTutor/releases/tag/v0.3.0) — PromptManager, CI/CD, imagens GHCR.

> **[2026.1.2]** [v0.2.0](https://github.com/HKUDS/DeepTutor/releases/tag/v0.2.0) — Docker, Next.js 16 e React 19, WebSocket, vulnerabilidades.

</details>

<a id="key-features"></a>
## ✨ Principais recursos

- **Workspace de chat unificado** — Cinco modos, um fio: Chat, Deep Solve, quiz, Deep Research e Math Animator compartilham contexto.
- **TutorBots pessoais** — Não são chatbots: tutores autônomos com espaço de trabalho, memória, personalidade e habilidades. [nanobot](https://github.com/HKUDS/nanobot).
- **AI Co-Writer** — Markdown com IA como colaborador: reescrever, expandir ou encurtar com KB e web.
- **Aprendizado guiado** — Jornadas visuais passo a passo a partir dos seus materiais.
- **Hub de conhecimento** — PDF, Markdown e texto para bases RAG; cadernos coloridos.
- **Memória persistente** — Resumo de progresso e perfil do aprendiz; compartilhado com TutorBots.
- **CLI nativo para agentes** — Capacidades, KB, sessões e TutorBot em um comando; Rich e JSON. [`SKILL.md`](../../SKILL.md).

---

<a id="get-started"></a>
## 🚀 Começar

### Opção A — Tour de configuração (recomendado)

**Script interativo**: dependências, ambiente, testes de conexão e inicialização.

```bash
git clone https://github.com/HKUDS/DeepTutor.git
cd DeepTutor

conda create -n deeptutor python=3.11 && conda activate deeptutor
# ou: python -m venv .venv && source .venv/bin/activate

python scripts/start_tour.py
```

- **Modo web** — Perfil, pip + npm, servidor temporário, página **Configurações**, tour em 4 passos.
- **Modo CLI** — Tudo no terminal.

[http://localhost:3782](http://localhost:3782)

<a id="option-b-manual"></a>
### Opção B — Instalação local manual

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

| Serviço | Porta |
|:---:|:---:|
| Backend | `8001` |
| Frontend | `3782` |

### Opção C — Docker

```bash
git clone https://github.com/HKUDS/DeepTutor.git
cd DeepTutor
cp .env.example .env
```

Como na [opção B](#option-b-manual).

**2a. Imagem oficial** — [GHCR](https://github.com/HKUDS/DeepTutor/pkgs/container/deeptutor)

```bash
docker compose -f docker-compose.ghcr.yml up -d
```

**2b. Build** — `docker compose up -d`

**3.** [http://localhost:3782](http://localhost:3782)

```bash
docker compose logs -f
docker compose down
```

<details>
<summary><b>Nuvem / servidor remoto</b></summary>

```dotenv
NEXT_PUBLIC_API_BASE_EXTERNAL=https://your-server.com:8001
```

</details>

<details>
<summary><b>Modo desenvolvimento (hot-reload)</b></summary>

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up
```

</details>

<details>
<summary><b>Portas personalizadas</b></summary>

```dotenv
BACKEND_PORT=9001
FRONTEND_PORT=4000
```

</details>

<details>
<summary><b>Persistência de dados</b></summary>

| Caminho no contêiner | Host | Conteúdo |
|:---|:---|:---|
| `/app/data/user` | `./data/user` | Configurações, memória, workspace, sessões, logs |
| `/app/data/knowledge_bases` | `./data/knowledge_bases` | Documentos e vetores |

</details>

<details>
<summary><b>Variáveis de ambiente</b></summary>

| Variável | Obrigatório | Descrição |
|:---|:---:|:---|
| `LLM_BINDING` | **Sim** | Provedor LLM |
| `LLM_MODEL` | **Sim** | Modelo |
| `LLM_API_KEY` | **Sim** | Chave |
| `LLM_HOST` | **Sim** | URL |
| `EMBEDDING_BINDING` | **Sim** | Embeddings |
| `EMBEDDING_MODEL` | **Sim** | Modelo |
| `EMBEDDING_API_KEY` | **Sim** | Chave |
| `EMBEDDING_HOST` | **Sim** | URL |
| `EMBEDDING_DIMENSION` | **Sim** | Dimensão |
| `SEARCH_PROVIDER` | Não | Busca |
| `SEARCH_API_KEY` | Não | Chave |
| `BACKEND_PORT` | Não | Padrão `8001` |
| `FRONTEND_PORT` | Não | Padrão `3782` |
| `NEXT_PUBLIC_API_BASE_EXTERNAL` | Não | URL pública |
| `DISABLE_SSL_VERIFY` | Não | Padrão `false` |

</details>

### Opção D — Apenas CLI

```bash
pip install -e ".[cli]"
deeptutor chat
deeptutor run chat "Explain Fourier transform"
deeptutor run deep_solve "Solve x^2 = 4"
deeptutor kb create my-kb --doc textbook.pdf
```

> Guia completo: [DeepTutor CLI](#deeptutor-cli-guide).

---

<a id="explore-deeptutor"></a>
## 📖 Explorar o DeepTutor

<div align="center">
<img src="../../assets/figs/deeptutor-architecture.png" alt="Arquitetura DeepTutor" width="800">
</div>

### 💬 Chat — Workspace inteligente unificado

<div align="center">
<img src="../../assets/figs/dt-chat.png" alt="Chat" width="800">
</div>

Cinco modos com **contexto unificado**.

| Modo | Função |
|:---|:---|
| **Chat** | RAG, web, código, raciocínio, brainstorming, papers. |
| **Deep Solve** | Multiagente com citações. |
| **Geração de quiz** | Avaliações na KB. |
| **Deep Research** | Subtópicos, agentes paralelos, relatório citado. |
| **Math Animator** | Manim. |

Ferramentas **desacopladas dos fluxos**.

### ✍️ Co-Writer — IA no editor

<div align="center">
<img src="../../assets/figs/dt-cowriter.png" alt="Co-Writer" width="800">
</div>

**Reescrever**, **Expandir**, **Encurtar**; desfazer/refazer; cadernos.

### 🎓 Aprendizado guiado

<div align="center">
<img src="../../assets/figs/dt-guide.png" alt="Guiado" width="800">
</div>

1. Plano (3–5 pontos).  
2. Páginas interativas.  
3. P&R contextuais.  
4. Resumo.

### 📚 Gestão do conhecimento

<div align="center">
<img src="../../assets/figs/dt-knowledge.png" alt="Conhecimento" width="800">
</div>

- **Bases de conhecimento** — PDF, TXT, MD.  
- **Cadernos** — Cores e sessões.

### 🧠 Memória

<div align="center">
<img src="../../assets/figs/dt-memory.png" alt="Memória" width="800">
</div>

- **Resumo** — Progresso.  
- **Perfil** — Preferências, nível, metas. Compartilhado com TutorBots.

---

<a id="tutorbot"></a>
### 🦞 TutorBot — Tutores de IA persistentes e autônomos

<div align="center">
<img src="../../assets/figs/tutorbot-architecture.png" alt="Arquitetura TutorBot" width="800">
</div>

Agente **multi-instância** persistente com [nanobot](https://github.com/HKUDS/nanobot).

<div align="center">
<img src="../../assets/figs/tb.png" alt="TutorBot" width="800">
</div>

- **Modelos Soul** — Personalidade e pedagogia.  
- **Workspace independente** — Memória, sessões, habilidades; camada compartilhada.  
- **Heartbeat proativo** — Lembretes e tarefas.  
- **Ferramentas completas** — RAG, código, web, papers, raciocínio, brainstorming.  
- **Habilidades** — Arquivos skill.  
- **Multicanal** — Telegram, Discord, Slack, Feishu, WeCom, DingTalk, e-mail, etc.  
- **Equipes e subagentes**.

```bash
deeptutor bot create math-tutor --persona "Socratic math teacher who uses probing questions"
deeptutor bot create writing-coach --persona "Patient, detail-oriented writing mentor"
deeptutor bot list
```

---

<a id="deeptutor-cli-guide"></a>
### ⌨️ DeepTutor CLI — Interface nativa para agentes

<div align="center">
<img src="../../assets/figs/cli-architecture.png" alt="CLI" width="800">
</div>

Sem navegador: capacidades, KB, sessões, memória, TutorBot. Rich + JSON. [`SKILL.md`](../../SKILL.md).

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
<summary><b>Referência completa da CLI</b></summary>

| Comando | Descrição |
|:---|:---|
| `deeptutor run <capability> <message>` | Uma passagem |
| `deeptutor chat` | REPL |
| `deeptutor serve` | Servidor API |

**bot**, **kb**, **memory**, **session**, **notebook**, **config / plugin / provider** — como no README em inglês.

</details>

<a id="community"></a>
## 🌐 Comunidade e ecossistema

| Projeto | Papel |
|:---|:---|
| [**nanobot**](https://github.com/HKUDS/nanobot) | Motor do TutorBot |
| [**LlamaIndex**](https://github.com/run-llama/llama_index) | RAG |
| [**ManimCat**](https://github.com/Wing900/ManimCat) | Math Animator |

| [⚡ LightRAG](https://github.com/HKUDS/LightRAG) | [🤖 AutoAgent](https://github.com/HKUDS/AutoAgent) | [🔬 AI-Researcher](https://github.com/HKUDS/AI-Researcher) | [🧬 nanobot](https://github.com/HKUDS/nanobot) |
|:---:|:---:|:---:|:---:|
| RAG rápido | Agentes sem código | Pesquisa automática | Agente ultraleve |

## 🤝 Contribuir

<div align="center">
<a href="https://github.com/HKUDS/DeepTutor/graphs/contributors">
  <img src="https://contrib.rocks/image?repo=HKUDS/DeepTutor&max=999" alt="Contributors" />
</a>
</div>

Veja [CONTRIBUTING.md](../../CONTRIBUTING.md).

## ⭐ Histórico de estrelas

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
