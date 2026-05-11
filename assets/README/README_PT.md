<div align="center">

<img src="../../assets/logo-ver2.png" alt="DeepTutor" width="140" style="border-radius: 15px;">

# DeepTutor: tutoria personalizada nativa para agentes

<a href="https://trendshift.io/repositories/17099" target="_blank"><img src="https://trendshift.io/api/badge/repositories/17099" alt="HKUDS%2FDeepTutor | Trendshift" style="width: 250px; height: 55px;" width="250" height="55"/></a>

[![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-3776AB?style=flat-square&logo=python&logoColor=white)](https://www.python.org/downloads/)
[![Next.js 16](https://img.shields.io/badge/Next.js-16-000000?style=flat-square&logo=next.js&logoColor=white)](https://nextjs.org/)
[![License](https://img.shields.io/badge/License-Apache_2.0-blue?style=flat-square)](../../LICENSE)
[![GitHub release](https://img.shields.io/github/v/release/HKUDS/DeepTutor?style=flat-square&color=brightgreen)](https://github.com/HKUDS/DeepTutor/releases)
[![arXiv](https://img.shields.io/badge/arXiv-2604.26962-b31b1b?style=flat-square&logo=arxiv&logoColor=white)](https://arxiv.org/abs/2604.26962)

[![Discord](https://img.shields.io/badge/Discord-Community-5865F2?style=flat-square&logo=discord&logoColor=white)](https://discord.gg/eRsjPgMU4t)
[![Feishu](https://img.shields.io/badge/Feishu-Group-00D4AA?style=flat-square&logo=feishu&logoColor=white)](../../Communication.md)
[![WeChat](https://img.shields.io/badge/WeChat-Group-07C160?style=flat-square&logo=wechat&logoColor=white)](https://github.com/HKUDS/DeepTutor/issues/78)

[Recursos](#key-features) · [Começar](#get-started) · [Explorar](#explore-deeptutor) · [TutorBot](#tutorbot) · [CLI](#deeptutor-cli-guide) · [Roteiro](#roadmap) · [Comunidade](#community)

[🇬🇧 English](../../README.md) · [🇨🇳 中文](README_CN.md) · [🇯🇵 日本語](README_JA.md) · [🇪🇸 Español](README_ES.md) · [🇫🇷 Français](README_FR.md) · [🇸🇦 العربية](README_AR.md) · [🇷🇺 Русский](README_RU.md) · [🇮🇳 हिन्दी](README_HI.md) · [🇵🇹 Português](README_PT.md) · [🇹🇭 ภาษาไทย](README_TH.md) · 🇵🇱 [Polski](README_PL.md)

</div>

---

> 🤝 **Aceitamos todo tipo de contribuição!** Veja o [Guia de contribuição](../../CONTRIBUTING.md) para estratégia de branches, padrões de código e como começar.

### 📦 Lançamentos

> **[2026.5.10]** [v1.3.10](https://github.com/HKUDS/DeepTutor/releases/tag/v1.3.10) — Correção de CORS em Docker remoto, `DISABLE_SSL_VERIFY` nos provedores SDK, citações seguras em blocos de código e E2EE do Matrix como add-on opcional.

> **[2026.5.9]** [v1.3.9](https://github.com/HKUDS/DeepTutor/releases/tag/v1.3.9) — TutorBot com Zulip e NVIDIA NIM, roteamento mais seguro para modelos de raciocínio, `deeptutor start`, tooltips na barra lateral e paridade do store de sessões.

> **[2026.5.8]** [v1.3.8](https://github.com/HKUDS/DeepTutor/releases/tag/v1.3.8) — Deploys multiusuário opcionais com workspaces isolados, concessões de admin, rotas de autenticação e acesso runtime com escopo.

> **[2026.5.4]** [v1.3.7](https://github.com/HKUDS/DeepTutor/releases/tag/v1.3.7) — Correções de modelos de raciocínio/provedores, histórico de índice de conhecimento visível e edição de templates e limpeza do Co-Writer mais seguros.

> **[2026.5.3]** [v1.3.6](https://github.com/HKUDS/DeepTutor/releases/tag/v1.3.6) — Seleção de modelos por catálogo no chat e TutorBot, reindexação RAG mais segura, correções de limite de tokens do OpenAI Responses e validação do editor Skills.

> **[2026.5.2]** [v1.3.5](https://github.com/HKUDS/DeepTutor/releases/tag/v1.3.5) — Configurações de lançamento local mais fluidas, consultas RAG mais seguras, autenticação de embedding local mais clara e polimento do modo escuro das Configurações.

> **[2026.5.1]** [v1.3.4](https://github.com/HKUDS/DeepTutor/releases/tag/v1.3.4) — Persistência de chat em página de livro e fluxos de reconstrução, referências de chat para livro, melhor tratamento de idioma/raciocínio, endurecimento da extração de documentos RAG.

> **[2026.4.30]** [v1.3.3](https://github.com/HKUDS/DeepTutor/releases/tag/v1.3.3) — Suporte a embeddings NVIDIA NIM e Gemini, contexto Space unificado para histórico do chat / skills / memória, instantâneos de sessão, resiliência de reindexação RAG.

> **[2026.4.29]** [v1.3.2](https://github.com/HKUDS/DeepTutor/releases/tag/v1.3.2) — URLs de endpoint de embedding transparentes, resiliência de reindexação RAG para vetores persistidos inválidos, limpeza de memória para saída de modelos de raciocínio, correção de runtime do Deep Solve.

> **[2026.4.28]** [v1.3.1](https://github.com/HKUDS/DeepTutor/releases/tag/v1.3.1) — Estabilidade: roteamento RAG mais seguro e validação de embeddings, persistência Docker, entrada segura com IME, robustez Windows/GBK.

> **[2026.4.27]** [v1.3.0](https://github.com/HKUDS/DeepTutor/releases/tag/v1.3.0) — Índices KB versionados com fluxo de reindexação, espaço de conhecimento reconstruído, autodetecção de embeddings com novos adaptadores, hub Space.

<details>
<summary><b>Lançamentos anteriores (há mais de 2 semanas)</b></summary>

> **[2026.4.25]** [v1.2.5](https://github.com/HKUDS/DeepTutor/releases/tag/v1.2.5) — Anexos de chat persistentes com gaveta de pré-visualização, pipelines de capacidade cientes de anexos, exportação Markdown do TutorBot.

> **[2026.4.25]** [v1.2.4](https://github.com/HKUDS/DeepTutor/releases/tag/v1.2.4) — Anexos de texto / código / SVG, tour de configuração em um comando, exportação do chat Markdown, UI compacta de gestão de KB.

> **[2026.4.24]** [v1.2.3](https://github.com/HKUDS/DeepTutor/releases/tag/v1.2.3) — Anexos de documentos (PDF/DOCX/XLSX/PPTX), exibição do bloco de raciocínio, editor de modelos Soul, salvar no caderno a partir do Co-Writer.

> **[2026.4.22]** [v1.2.2](https://github.com/HKUDS/DeepTutor/releases/tag/v1.2.2) — Skills criados pelo usuário, melhoria de desempenho do input de chat, início automático do TutorBot, UI da biblioteca de livros, visualização em tela cheia.

> **[2026.4.21]** [v1.2.1](https://github.com/HKUDS/DeepTutor/releases/tag/v1.2.1) — Limites de tokens por etapa, regenerar resposta em todos os pontos de entrada, correções de compatibilidade RAG e Gemma.

> **[2026.4.20]** [v1.2.0](https://github.com/HKUDS/DeepTutor/releases/tag/v1.2.0) — Compilador Book Engine de «livros vivos», Co-Writer multidocumento, visualizações HTML interativas, menções @ do banco de questões no chat.

> **[2026.4.18]** [v1.1.2](https://github.com/HKUDS/DeepTutor/releases/tag/v1.1.2) — Aba Channels orientada por schema, consolidação RAG em pipeline único, prompts de chat externalizados.

> **[2026.4.17]** [v1.1.1](https://github.com/HKUDS/DeepTutor/releases/tag/v1.1.1) — «Responder agora» universal, sincronização de rolagem no Co-Writer, painel de configurações unificado, botão Stop em streaming.

> **[2026.4.15]** [v1.1.0](https://github.com/HKUDS/DeepTutor/releases/tag/v1.1.0) — Reformulação do parsing de LaTeX em bloco; sonda de diagnóstico LLM via `agents.yaml`; correção do encaminhamento de cabeçalhos extras; correção de UUID no SaveToNotebook; guia Docker + LLM local.

> **[2026.4.14]** [v1.1.0-beta](https://github.com/HKUDS/DeepTutor/releases/tag/v1.1.0-beta) — Sessões com URL marcável; tema Snow; heartbeat WebSocket e reconexão automática; desempenho do ChatComposer; reformulação do registro de provedores de embeddings; provedor de busca Serper.

> **[2026.4.13]** [v1.0.3](https://github.com/HKUDS/DeepTutor/releases/tag/v1.0.3) — Caderno de questões com favoritos e categorias; Mermaid no Visualize; detecção de incompatibilidade de embeddings; compatibilidade Qwen/vLLM; suporte LM Studio e llama.cpp; tema Glass.

> **[2026.4.11]** [v1.0.2](https://github.com/HKUDS/DeepTutor/releases/tag/v1.0.2) — Consolidação de busca com fallback SearXNG; correção da troca de provedor; vazamentos de recursos no frontend.

> **[2026.4.10]** [v1.0.1](https://github.com/HKUDS/DeepTutor/releases/tag/v1.0.1) — Capacidade Visualize (Chart.js/SVG); prevenção de duplicatas em questionários; suporte ao modelo o4-mini.

> **[2026.4.10]** [v1.0.0-beta.4](https://github.com/HKUDS/DeepTutor/releases/tag/v1.0.0-beta.4) — Acompanhamento de embeddings com nova tentativa sob limite de taxa; dependências multiplataforma; validação MIME.

> **[2026.4.8]** [v1.0.0-beta.3](https://github.com/HKUDS/DeepTutor/releases/tag/v1.0.0-beta.3) — SDK nativo OpenAI/Anthropic (sem litellm); Math Animator no Windows; parsing JSON mais robusto; i18n chinês completo.

> **[2026.4.7]** [v1.0.0-beta.2](https://github.com/HKUDS/DeepTutor/releases/tag/v1.0.0-beta.2) — Recarga a quente de configurações; saída aninhada MinerU; correção WebSocket; mínimo Python 3.11+.

> **[2026.4.4]** [v1.0.0-beta.1](https://github.com/HKUDS/DeepTutor/releases/tag/v1.0.0-beta.1) — Reescrita nativa de agentes (~200k linhas): plugins Tools + Capabilities, CLI e SDK, TutorBot, Co-Writer, aprendizado guiado e memória persistente.

> **[2026.1.23]** [v0.6.0](https://github.com/HKUDS/DeepTutor/releases/tag/v0.6.0) — Persistência de sessão, upload incremental, RAG flexível, localização em chinês.

> **[2026.1.18]** [v0.5.2](https://github.com/HKUDS/DeepTutor/releases/tag/v0.5.2) — Docling, logs, correções.

> **[2026.1.15]** [v0.5.0](https://github.com/HKUDS/DeepTutor/releases/tag/v0.5.0) — Config unificada, RAG por KB, geração de questões, barra lateral.

> **[2026.1.9]** [v0.4.0](https://github.com/HKUDS/DeepTutor/releases/tag/v0.4.0) — Multi-provedor LLM/embeddings, nova home, desacoplamento RAG, variáveis de ambiente.

> **[2026.1.5]** [v0.3.0](https://github.com/HKUDS/DeepTutor/releases/tag/v0.3.0) — PromptManager, CI/CD, imagens GHCR.

> **[2026.1.2]** [v0.2.0](https://github.com/HKUDS/DeepTutor/releases/tag/v0.2.0) — Docker, Next.js 16 e React 19, WebSocket, vulnerabilidades.

</details>

### 📰 Notícias

> **[2026.4.19]** 🎉 Alcançamos 20k estrelas em 111 dias! Obrigado pelo apoio — seguimos iterando rumo a um ensino realmente personalizado e inteligente.

> **[2026.4.10]** 📄 Nosso artigo está no arXiv! Leia o [preprint](https://arxiv.org/abs/2604.26962) para conhecer o desenho e as ideias por trás do DeepTutor.

> **[2026.4.4]** Há quanto tempo! ✨ DeepTutor v1.0.0 chegou — evolução nativa de agentes com reescrita da arquitetura do zero, TutorBot e modos flexíveis sob Apache-2.0. Um novo capítulo começa!

> **[2026.2.6]** 🚀 10k estrelas em 39 dias — obrigado à comunidade!

> **[2026.1.1]** Feliz Ano Novo! Junte-se ao [Discord](https://discord.gg/eRsjPgMU4t), [WeChat](https://github.com/HKUDS/DeepTutor/issues/78) ou [Discussions](https://github.com/HKUDS/DeepTutor/discussions).

> **[2025.12.29]** DeepTutor é lançado oficialmente.

<a id="key-features"></a>
## ✨ Principais recursos

- **Workspace de chat unificado** — Seis modos, um fio: Chat, Deep Solve, quiz, Deep Research, Math Animator e Visualize compartilham contexto.
- **AI Co-Writer** — Espaço Markdown multidocumento com IA como colaborador: reescrever, expandir ou encurtar com KB e web.
- **Book Engine** — Transforme materiais em «livros vivos» estruturados e interativos: pipeline multiagente, 13 tipos de blocos (quiz, flashcards, linhas do tempo, grafos de conceitos e mais).
- **Hub de conhecimento** — Bases RAG, cadernos coloridos, banco de questões e Skills personalizados que moldam o ensino.
- **Memória persistente** — Resumo de progresso e perfil do aprendiz; compartilhado com TutorBots.
- **TutorBots pessoais** — Não são chatbots: tutores autônomos com espaço de trabalho, memória, personalidade e habilidades. [nanobot](https://github.com/HKUDS/nanobot).
- **CLI nativo para agentes** — Capacidades, KB, sessões e TutorBot em um comando; Rich e JSON. [`SKILL.md`](../../SKILL.md).

---

<a id="get-started"></a>
## 🚀 Começar

### Pré-requisitos

Antes de começar, certifique-se de ter instalado:

| Requisito | Versão | Verificar | Notas |
|:---|:---|:---|:---|
| [Git](https://git-scm.com/) | Qualquer | `git --version` | Para clonar o repositório |
| [Python](https://www.python.org/downloads/) | 3.11+ | `python --version` | Backend |
| [Node.js](https://nodejs.org/) | 20.9+ | `node --version` | Runtime do frontend para instalações web locais |
| [npm](https://www.npmjs.com/) | Incluído com Node.js | `npm --version` | Instalado com o Node.js |

Você também precisa de uma **chave API** de pelo menos um provedor LLM (por exemplo [OpenAI](https://platform.openai.com/api-keys), [DeepSeek](https://platform.deepseek.com/), [Anthropic](https://console.anthropic.com/)). O tour guiado orienta o preenchimento.

### Opção A — Tour de configuração (recomendado)

Um **único script CLI interativo** leva do clone novo ao app em execução — sem `pip install` ou `npm install` manuais nem edição de `.env`. Tudo é detectado, instalado e configurado em um fluxo guiado de 7 passos.

```bash
git clone https://github.com/HKUDS/DeepTutor.git
cd DeepTutor

# Ambiente virtual Python (escolha um):
conda create -n deeptutor python=3.11 && conda activate deeptutor   # Anaconda/Miniconda
python -m venv .venv && source .venv/bin/activate                    # macOS/Linux
python -m venv .venv && .venv\Scripts\activate                       # Windows

# Iniciar o tour
python scripts/start_tour.py
```

Após o assistente:

```bash
python scripts/start_web.py
```

> **Início diário** — O tour costuma bastar uma vez. Depois use `python scripts/start_web.py` para subir backend e frontend (a URL do frontend aparece no terminal). Só execute `start_tour.py` de novo para reconfigurar provedores, mudar portas ou instalar extras. Na **Configurações** da web também há **Run Tour** para repetir o guia com destaque na UI.

<a id="option-b-manual"></a>
### Opção B — Instalação local manual

Se preferir controle total, instale e configure tudo manualmente.

**1. Instalar dependências**

```bash
git clone https://github.com/HKUDS/DeepTutor.git
cd DeepTutor

# Criar e ativar ambiente virtual (igual à opção A)
conda create -n deeptutor python=3.11 && conda activate deeptutor

# DeepTutor com dependências de backend + servidor web
pip install -e ".[server]"

# Frontend (requer Node.js 18+)
cd web && npm install && cd ..
```

**2. Configurar ambiente**

```bash
cp .env.example .env
```

Edite `.env` e preencha pelo menos os campos obrigatórios:

```dotenv
# LLM (obrigatório)
LLM_BINDING=openai
LLM_MODEL=gpt-4o-mini
LLM_API_KEY=sk-xxx
LLM_HOST=https://api.openai.com/v1

# Embeddings (obrigatório para a base de conhecimento)
EMBEDDING_BINDING=openai
EMBEDDING_MODEL=text-embedding-3-large
EMBEDDING_API_KEY=sk-xxx
EMBEDDING_HOST=https://api.openai.com/v1
EMBEDDING_DIMENSION=3072
```

<details>
<summary><b>Provedores LLM suportados</b></summary>

| Provedor | Binding | URL base padrão |
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
<summary><b>Provedores de embedding suportados</b></summary>

| Provedor | Binding | Exemplo de modelo | Dimensão padrão |
|:--|:--|:--|:--|
| OpenAI | `openai` | `text-embedding-3-large` | 3072 |
| Azure OpenAI | `azure_openai` | nome do deployment | — |
| Cohere | `cohere` | `embed-v4.0` | 1024 |
| Jina | `jina` | `jina-embeddings-v3` | 1024 |
| Ollama | `ollama` | `nomic-embed-text` | 768 |
| vLLM / LM Studio | `vllm` | Qualquer modelo de embedding | — |
| Compatível OpenAI | `custom` | — | — |

Provedores compatíveis com OpenAI (DashScope, SiliconFlow, etc.) funcionam com o binding `custom` ou `openai`.

</details>

<details>
<summary><b>Provedores de busca web suportados</b></summary>

| Provedor | Variável de ambiente | Notas |
|:--|:--|:--|
| Brave | `BRAVE_API_KEY` | Recomendado, há nível gratuito |
| Tavily | `TAVILY_API_KEY` | |
| Serper | `SERPER_API_KEY` | Resultados Google via Serper |
| Jina | `JINA_API_KEY` | |
| SearXNG | — | Auto-hospedado, sem chave API |
| DuckDuckGo | — | Sem chave API |
| Perplexity | `PERPLEXITY_API_KEY` | Requer chave API |

</details>

**3. Iniciar serviços**

A forma mais rápida:

```bash
python scripts/start_web.py
```

Inicia backend e frontend e abre o navegador automaticamente.

Ou inicie cada serviço manualmente em terminais separados:

```bash
# Backend (FastAPI)
python -m deeptutor.api.run_server

# Frontend (Next.js) — outro terminal
cd web && npm run dev -- -p 3782
```

| Serviço | Porta padrão |
|:---:|:---:|
| Backend | `8001` |
| Frontend | `3782` |

Abra [http://localhost:3782](http://localhost:3782).

### Opção C — Docker

O Docker empacota backend e frontend em um único contêiner; não é necessário Python ou Node.js locais. Basta [Docker Desktop](https://www.docker.com/products/docker-desktop/) (ou Docker Engine + Compose no Linux).

**1. Variáveis de ambiente** (necessárias nas duas variantes abaixo)

```bash
git clone https://github.com/HKUDS/DeepTutor.git
cd DeepTutor
cp .env.example .env
```

Edite `.env` e preencha pelo menos os campos obrigatórios (como na [opção B](#option-b-manual)).

**2a. Puxar imagem oficial (recomendado)**

As imagens oficiais são publicadas no [GitHub Container Registry](https://github.com/HKUDS/DeepTutor/pkgs/container/deeptutor) a cada release, para `linux/amd64` e `linux/arm64`.

```bash
docker compose -f docker-compose.ghcr.yml up -d
```

Para fixar uma versão, edite a tag da imagem em `docker-compose.ghcr.yml`:

```yaml
image: ghcr.io/hkuds/deeptutor:1.0.0  # ou :latest
```

**2b. Build a partir do código-fonte**

```bash
docker compose up -d
```

Constrói a imagem localmente a partir do `Dockerfile` e inicia o contêiner.

**3. Verificar e gerenciar**

Abra [http://localhost:3782](http://localhost:3782) quando o contêiner estiver healthy.

```bash
docker compose logs -f   # acompanhar logs
docker compose down       # parar e remover o contêiner
```

<details>
<summary><b>Nuvem / servidor remoto</b></summary>

Em um servidor remoto, o navegador precisa da URL pública da API backend. Adicione em `.env`:

```dotenv
# URL pública onde o backend é acessível
NEXT_PUBLIC_API_BASE_EXTERNAL=https://your-server.com:8001
```

O script de inicialização do frontend aplica esse valor em tempo de execução — não é necessário rebuild.

</details>

<details>
<summary><b>Autenticação (implantações públicas)</b></summary>

A autenticação está **desativada por padrão** — não é necessário login no localhost. Para implantações multi-tenant, consulte a seção [Multi-usuário](#multi-user) abaixo.

**Usuário único sem interface (sem fluxo `/register`):** pré-configure as credenciais via env vars:

```bash
python -c "from deeptutor.services.auth import hash_password; print(hash_password('yourpassword'))"
```

```dotenv
AUTH_ENABLED=true
AUTH_USERNAME=admin
AUTH_PASSWORD_HASH=<cole o hash aqui>
AUTH_SECRET=your-secret-here
```

</details>

<details>
<summary><b>Sidecar PocketBase (autenticação + armazenamento opcionais)</b></summary>

PocketBase é um backend leve opcional que substitui a autenticação SQLite/JSON embutida.

> ⚠️ **Modo PocketBase é apenas para usuário único atualmente.** O esquema padrão não tem campo `role` em `users` e as queries não são filtradas por `user_id`. Implantações multi-usuário: deixe `POCKETBASE_URL` vazio.

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
<summary><b>Modo desenvolvimento (hot-reload)</b></summary>

Sobreponha o override de desenvolvimento para montar o código-fonte e habilitar hot-reload em ambos os serviços:

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up
```

Alterações em `deeptutor/`, `deeptutor_cli/`, `scripts/` e `web/` refletem-se imediatamente.

</details>

<details>
<summary><b>Portas personalizadas</b></summary>

Substitua as portas padrão em `.env`:

```dotenv
BACKEND_PORT=9001
FRONTEND_PORT=4000
```

Depois reinicie:

```bash
docker compose up -d     # ou docker compose -f docker-compose.ghcr.yml up -d
```

</details>

<details>
<summary><b>Persistência de dados</b></summary>

Dados do usuário e bases de conhecimento persistem via volumes Docker mapeados para diretórios locais:

| Caminho no contêiner | Caminho no host | Conteúdo |
|:---|:---|:---|
| `/app/data/user` | `./data/user` | Configurações, workspace, sessões, logs |
| `/app/data/memory` | `./data/memory` | Memória compartilhada de longo prazo (`SUMMARY.md`, `PROFILE.md`) |
| `/app/data/knowledge_bases` | `./data/knowledge_bases` | Documentos enviados e índices vetoriais |

Esses diretórios permanecem após `docker compose down` e são reutilizados no próximo `docker compose up`.

</details>

<details>
<summary><b>Referência de variáveis de ambiente</b></summary>

| Variável | Obrigatório | Descrição |
|:---|:---:|:---|
| `LLM_BINDING` | **Sim** | Provedor LLM (`openai`, `anthropic`, etc.) |
| `LLM_MODEL` | **Sim** | Nome do modelo (ex.: `gpt-4o`) |
| `LLM_API_KEY` | **Sim** | Chave API do LLM |
| `LLM_HOST` | **Sim** | URL do endpoint |
| `EMBEDDING_BINDING` | **Sim** | Provedor de embeddings |
| `EMBEDDING_MODEL` | **Sim** | Nome do modelo de embedding |
| `EMBEDDING_API_KEY` | **Sim** | Chave API de embeddings |
| `EMBEDDING_HOST` | **Sim** | Endpoint de embeddings |
| `EMBEDDING_DIMENSION` | **Sim** | Dimensão do vetor |
| `SEARCH_PROVIDER` | Não | Busca (`tavily`, `jina`, `serper`, `perplexity`, etc.) |
| `SEARCH_API_KEY` | Não | Chave API de busca |
| `BACKEND_PORT` | Não | Porta backend (padrão `8001`) |
| `FRONTEND_PORT` | Não | Porta frontend (padrão `3782`) |
| `NEXT_PUBLIC_API_BASE_EXTERNAL` | Não | URL pública do backend para nuvem |
| `DISABLE_SSL_VERIFY` | Não | Desativar verificação SSL (padrão `false`) |

</details>

### Opção D — Apenas CLI

Se quiser apenas a CLI sem o frontend web:

```bash
pip install -e ".[cli]"
```

Ainda é necessário configurar o provedor LLM. O caminho mais rápido:

```bash
cp .env.example .env   # depois edite .env com suas chaves API
```

Após configurar:

```bash
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

Seis modos com **contexto unificado**.

| Modo | Função |
|:---|:---|
| **Chat** | RAG, web, código, raciocínio, brainstorming, papers. |
| **Deep Solve** | Multiagente com citações. |
| **Geração de quiz** | Avaliações na KB. |
| **Deep Research** | Subtópicos, agentes paralelos, relatório citado. |
| **Math Animator** | Manim. |
| **Visualize** | SVG, Chart.js, Mermaid ou HTML autocontido a partir de linguagem natural. |

Ferramentas **desacopladas dos fluxos**.

### ✍️ Co-Writer — Espaço de escrita multidocumento com IA

<div align="center">
<img src="../../assets/figs/dt-cowriter.png" alt="Co-Writer" width="800">
</div>

Crie e gerencie vários documentos, cada um persistido — não um rascunho único: Markdown completo com IA como coautora. **Reescrever**, **Expandir**, **Encurtar**; desfazer/refazer; cadernos.

### 📖 Book Engine — «Livros vivos» interativos

<div align="center">
<img src="../../assets/figs/dt-book-0.png" alt="Biblioteca" width="270"><img src="../../assets/figs/dt-book-1.png" alt="Leitor" width="270"><img src="../../assets/figs/dt-book-2.png" alt="Animação" width="270">
</div>

Dê um tema, aponte para a sua base de conhecimento: o DeepTutor produz um livro estruturado e interativo — documento vivo para ler, autoavaliar e discutir em contexto.

Por trás, um pipeline multiagente propõe o esquema, recupera fontes, funde a árvore de capítulos, planeja cada página e compila cada bloco. Você continua no controle: revisão da proposta, reordenação de capítulos e chat ao lado de cada página.

13 tipos de blocos — texto, destaque, quiz, flashcards, código, figura, mergulho profundo, animação, interativo, linha do tempo, grafo de conceitos, seção, nota do usuário — cada um com componente interativo. Linha do tempo de progresso em tempo real.

### 📚 Gestão do conhecimento

<div align="center">
<img src="../../assets/figs/dt-knowledge.png" alt="Conhecimento" width="800">
</div>

Coleções de documentos, notas e personas de ensino.

- **Bases de conhecimento** — PDF, TXT, MD.  
- **Cadernos** — Insights de Chat, Co-Writer, Book ou Deep Research, por cores.
- **Banco de questões** — Revise quizzes gerados; favoritos e @menções no chat para analisar desempenho passado.
- **Skills** — Personas com `SKILL.md`: nome, descrição, gatilhos opcionais e corpo Markdown injetado no prompt do sistema do chat quando ativos.

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
deeptutor run visualize "Draw the architecture of a transformer"
```

```bash
deeptutor chat --capability deep_solve --kb my-kb
# No REPL: /cap, /tool, /kb, /history, /notebook, /config para alternar em tempo real
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

**Nível superior**

| Comando | Descrição |
|:---|:---|
| `deeptutor run <capability> <message>` | Executa uma capacidade em um turno (`chat`, `deep_solve`, `deep_question`, `deep_research`, `math_animator`, `visualize`) |
| `deeptutor chat` | REPL interativo com `--capability`, `--tool`, `--kb`, `--language`, etc. |
| `deeptutor serve` | Inicia o servidor API do DeepTutor |

**`deeptutor bot`**

| Comando | Descrição |
|:---|:---|
| `deeptutor bot list` | Lista instâncias do TutorBot |
| `deeptutor bot create <id>` | Cria e inicia um bot (`--name`, `--persona`, `--model`) |
| `deeptutor bot start <id>` | Inicia um bot |
| `deeptutor bot stop <id>` | Para um bot |

**`deeptutor kb`**

| Comando | Descrição |
|:---|:---|
| `deeptutor kb list` | Lista bases de conhecimento |
| `deeptutor kb info <name>` | Detalhes da base |
| `deeptutor kb create <name>` | Cria a partir de documentos (`--doc`, `--docs-dir`) |
| `deeptutor kb add <name>` | Adiciona documentos |
| `deeptutor kb search <name> <query>` | Busca na base |
| `deeptutor kb set-default <name>` | Define KB padrão |
| `deeptutor kb delete <name>` | Remove (`--force`) |

**`deeptutor memory`**

| Comando | Descrição |
|:---|:---|
| `deeptutor memory show [file]` | Ver (`summary`, `profile`, `all`) |
| `deeptutor memory clear [file]` | Limpar (`--force`) |

**`deeptutor session`**

| Comando | Descrição |
|:---|:---|
| `deeptutor session list` | Lista sessões (`--limit`) |
| `deeptutor session show <id>` | Mensagens da sessão |
| `deeptutor session open <id>` | Retomar no REPL |
| `deeptutor session rename <id>` | Renomear (`--title`) |
| `deeptutor session delete <id>` | Excluir |

**`deeptutor notebook`**

| Comando | Descrição |
|:---|:---|
| `deeptutor notebook list` | Lista cadernos |
| `deeptutor notebook create <name>` | Criar (`--description`) |
| `deeptutor notebook show <id>` | Registros |
| `deeptutor notebook add-md <id> <path>` | Importar Markdown |
| `deeptutor notebook replace-md <id> <rec> <path>` | Substituir registro |
| `deeptutor notebook remove-record <id> <rec>` | Remover registro |

**`deeptutor book`**

| Comando | Descrição |
|:---|:---|
| `deeptutor book list` | Lista todos os livros do espaço de trabalho |
| `deeptutor book health <book_id>` | Verifica deriva da KB e saúde do livro |
| `deeptutor book refresh-fingerprints <book_id>` | Atualiza impressões digitais da KB e limpa páginas obsoletas |

**`deeptutor config` / `plugin` / `provider`**

| Comando | Descrição |
|:---|:---|
| `deeptutor config show` | Resumo da configuração |
| `deeptutor plugin list` | Ferramentas e capacidades registradas |
| `deeptutor plugin info <name>` | Detalhe de ferramenta ou capacidade |
| `deeptutor provider login <provider>` | Autenticação do provedor (OAuth com `openai-codex`; `github-copilot` valida uma sessão Copilot existente) |

</details>

---

<a id="multi-user"></a>
### 👥 Multi-usuário — Implantações compartilhadas com espaços de trabalho por usuário

<div align="center">
<img src="../../assets/figs/dt-multi-user.png" alt="Multi-usuário" width="800">
</div>

Ative a autenticação e o DeepTutor se torna uma implantação multi-tenant com **espaços de trabalho isolados por usuário** e **recursos curados pelo administrador**. O primeiro a se registrar torna-se administrador e configura modelos, chaves de API e bases de conhecimento para todos. As contas seguintes são criadas pelo administrador (somente por convite), cada uma obtendo histórico de chat/memória/notebooks/bases de conhecimento com escopo.

**Início rápido (5 passos):**

```bash
# 1. Ative a autenticação no .env da raiz do projeto
echo 'AUTH_ENABLED=true' >> .env
echo 'AUTH_SECRET=<cole 64+ caracteres aleatórios>' >> .env

# 2. Reinicie o web stack
python scripts/start_web.py

# 3. Abra http://localhost:3782/register e crie a primeira conta
#    O primeiro registro é o único público; esse usuário torna-se admin
#    e o endpoint /register é fechado automaticamente

# 4. Como admin, acesse /admin/users → "Adicionar usuário"

# 5. Para cada usuário, clique no ícone deslizante → atribua perfis LLM,
#    bases de conhecimento e skills → salve
```

**O que o administrador vê:**

- **Página de Configurações completa** em `/settings` — provedores LLM/embedding/busca, chaves de API, catálogo de modelos.
- **Gerenciamento de usuários** em `/admin/users` — criar, promover, rebaixar e excluir contas.
- **Editor de concessões** — selecionar perfis de modelo, KBs e skills para usuários não-admin; as concessões contêm **apenas IDs lógicos**, as chaves de API nunca cruzam a fronteira.
- **Trilha de auditoria** — toda alteração de concessão e acesso a recursos em `multi-user/_system/audit/usage.jsonl`.

**O que os usuários comuns obtêm:**

- **Espaço de trabalho isolado** em `multi-user/<uid>/` — `chat_history.db`, memória, notebooks e bases de conhecimento pessoais.
- **Acesso somente leitura** às KBs e skills atribuídas pelo admin, exibidas com o badge "Atribuído pelo admin".
- **Página de Configurações reduzida** — apenas tema, idioma e resumo dos modelos concedidos.
- **LLM com escopo** — as conversas são roteadas pelo modelo atribuído pelo admin; se nenhum LLM foi concedido, a conversa é rejeitada antecipadamente.

**Layout do espaço de trabalho:**

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

**Referência de configuração:**

| Variável | Obrigatório | Descrição |
|:---|:---|:---|
| `AUTH_ENABLED` | Sim | `true` para habilitar autenticação multi-usuário. Padrão `false`. |
| `AUTH_SECRET` | Recomendado | Segredo de assinatura JWT; vazio gera em `multi-user/_system/auth/auth_secret`. |
| `AUTH_TOKEN_EXPIRE_HOURS` | Não | Duração do JWT; padrão 24 horas. |
| `AUTH_USERNAME` / `AUTH_PASSWORD_HASH` | Não | Credenciais de fallback para usuário único. Deixe em branco no modo multi-usuário. |
| `NEXT_PUBLIC_AUTH_ENABLED` | Auto | Espelhado de `AUTH_ENABLED` por `start_web.py`. |

> ⚠️ **Modo PocketBase (`POCKETBASE_URL` definido) é apenas para usuário único** — sem campo `role`, sem filtragem por `user_id`. Multi-usuário: deixe `POCKETBASE_URL` vazio.

> ⚠️ **Processo único recomendado.** A promoção do primeiro admin é protegida por `threading.Lock`. Multi-worker: provisione o primeiro admin offline.

<a id="roadmap"></a>
## 🗺️ Roteiro

| Status | Marco |
|:---:|:---|
| 🎯 | **Autenticação e login** — Página de login opcional para implantações públicas com multiusuário |
| 🎯 | **Temas e aparência** — Mais temas e personalização da interface |
| 🎯 | **Melhoria de interação** — Refinar ícones e detalhes de interação |
| 🔜 | **Memórias melhores** — Integrar gestão de memória mais robusta |
| 🔜 | **Integração LightRAG** — Integrar [LightRAG](https://github.com/HKUDS/LightRAG) como motor avançado de bases de conhecimento |
| 🔜 | **Site de documentação** — Documentação completa com guias, referência de API e tutoriais |

> Se o DeepTutor for útil para você, [dê uma estrela](https://github.com/HKUDS/DeepTutor/stargazers) — isso nos ajuda a continuar!

---

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

Esperamos que o DeepTutor seja um presente para a comunidade. 🎁

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
