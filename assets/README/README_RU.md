<div align="center">

<img src="../../assets/logo-ver2.png" alt="DeepTutor" width="140" style="border-radius: 15px;">

# DeepTutor: агентно-нативное персонализированное обучение

<a href="https://trendshift.io/repositories/17099" target="_blank"><img src="https://trendshift.io/api/badge/repositories/17099" alt="HKUDS%2FDeepTutor | Trendshift" style="width: 250px; height: 55px;" width="250" height="55"/></a>

[![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-3776AB?style=flat-square&logo=python&logoColor=white)](https://www.python.org/downloads/)
[![Next.js 16](https://img.shields.io/badge/Next.js-16-000000?style=flat-square&logo=next.js&logoColor=white)](https://nextjs.org/)
[![License](https://img.shields.io/badge/License-Apache_2.0-blue?style=flat-square)](../../LICENSE)
[![GitHub release](https://img.shields.io/github/v/release/HKUDS/DeepTutor?style=flat-square&color=brightgreen)](https://github.com/HKUDS/DeepTutor/releases)
[![arXiv](https://img.shields.io/badge/arXiv-2604.26962-b31b1b?style=flat-square&logo=arxiv&logoColor=white)](https://arxiv.org/abs/2604.26962)

[![Discord](https://img.shields.io/badge/Discord-Community-5865F2?style=flat-square&logo=discord&logoColor=white)](https://discord.gg/eRsjPgMU4t)
[![Feishu](https://img.shields.io/badge/Feishu-Group-00D4AA?style=flat-square&logo=feishu&logoColor=white)](../../Communication.md)
[![WeChat](https://img.shields.io/badge/WeChat-Group-07C160?style=flat-square&logo=wechat&logoColor=white)](https://github.com/HKUDS/DeepTutor/issues/78)

[Возможности](#key-features) · [Быстрый старт](#get-started) · [Обзор](#explore-deeptutor) · [TutorBot](#tutorbot) · [CLI](#deeptutor-cli-guide) · [Дорожная карта](#roadmap) · [Сообщество](#community)

[🇬🇧 English](../../README.md) · [🇨🇳 中文](README_CN.md) · [🇯🇵 日本語](README_JA.md) · [🇪🇸 Español](README_ES.md) · [🇫🇷 Français](README_FR.md) · [🇸🇦 العربية](README_AR.md) · [🇮🇳 हिन्दी](README_HI.md) · [🇵🇹 Português](README_PT.md) · [🇹🇭 ภาษาไทย](README_TH.md) · 🇵🇱 [Polski](README_PL.md)

</div>

---

> 🤝 **Мы рады любому вкладу!** См. [руководство по участию](../../CONTRIBUTING.md): ветвление, стиль кода и с чего начать.

### 📦 Релизы

> **[2026.5.9]** [v1.3.9](https://github.com/HKUDS/DeepTutor/releases/tag/v1.3.9) — TutorBot получил Zulip и NVIDIA NIM, более безопасный роутинг thinking-моделей, `deeptutor start`, подсказки сайдбара и паритет хранилищ сессий.

> **[2026.5.8]** [v1.3.8](https://github.com/HKUDS/DeepTutor/releases/tag/v1.3.8) — Опциональные multi-user развёртывания с изолированными рабочими пространствами, admin grants, auth routes и scoped runtime access.

> **[2026.5.4]** [v1.3.7](https://github.com/HKUDS/DeepTutor/releases/tag/v1.3.7) — Исправления для thinking-моделей/провайдеров, видимая история индекса знаний, более безопасные очистка Co-Writer и редактирование шаблонов.

> **[2026.5.3]** [v1.3.6](https://github.com/HKUDS/DeepTutor/releases/tag/v1.3.6) — Выбор моделей через каталог в чате и TutorBot, более безопасная переиндексация RAG, исправления лимита токенов OpenAI Responses, валидация редактора Skills.

> **[2026.5.2]** [v1.3.5](https://github.com/HKUDS/DeepTutor/releases/tag/v1.3.5) — Более плавные настройки локального запуска, более безопасные запросы RAG, более чёткая аутентификация локальных эмбеддингов, улучшение тёмной темы настроек.

> **[2026.5.1]** [v1.3.4](https://github.com/HKUDS/DeepTutor/releases/tag/v1.3.4) — Персистентность чата на странице книги и потоки пересборки, ссылки из чата в книгу, более надёжная обработка языка/рассуждений, укрепление извлечения документов RAG.

> **[2026.4.30]** [v1.3.3](https://github.com/HKUDS/DeepTutor/releases/tag/v1.3.3) — Поддержка эмбеддингов NVIDIA NIM и Gemini, единый контекст Space для истории чата / навыков / памяти, снимки сессий, устойчивость повторной индексации RAG.

> **[2026.4.29]** [v1.3.2](https://github.com/HKUDS/DeepTutor/releases/tag/v1.3.2) — Прозрачные URL эндпоинтов эмбеддингов, устойчивость повторной индексации RAG при неверных сохранённых векторах, очистка памяти для вывода thinking-моделей, исправление рантайма Deep Solve.

> **[2026.4.28]** [v1.3.1](https://github.com/HKUDS/DeepTutor/releases/tag/v1.3.1) — Стабильность: более безопасный роутинг RAG и проверка эмбеддингов, персистентность Docker, ввод безопасный для IME, устойчивость Windows/GBK.

> **[2026.4.27]** [v1.3.0](https://github.com/HKUDS/DeepTutor/releases/tag/v1.3.0) — Версионированные индексы KB с процессом переиндексации, перестроенное рабочее пространство знаний, автообнаружение эмбеддингов с новыми адаптерами, хаб Space.

> **[2026.4.25]** [v1.2.5](https://github.com/HKUDS/DeepTutor/releases/tag/v1.2.5) — Постоянные вложения в чате с ящиком предпросмотра, пайплайны возможностей с учётом вложений, экспорт Markdown для TutorBot.

> **[2026.4.25]** [v1.2.4](https://github.com/HKUDS/DeepTutor/releases/tag/v1.2.4) — Вложения текста / кода / SVG, тур настройки одной командой, экспорт чата в Markdown, компактный UI управления KB.

<details>
<summary><b>Прошлые релизы (более 2 недель назад)</b></summary>

> **[2026.4.24]** [v1.2.3](https://github.com/HKUDS/DeepTutor/releases/tag/v1.2.3) — Вложения документов (PDF/DOCX/XLSX/PPTX), блок размышлений модели рассуждений, редактор шаблонов Soul, сохранение из Co-Writer в блокнот.

> **[2026.4.22]** [v1.2.2](https://github.com/HKUDS/DeepTutor/releases/tag/v1.2.2) — Пользовательские Skills, оптимизация ввода в чате, авто-старт TutorBot, UI библиотеки книг, полноэкранные визуализации.

> **[2026.4.21]** [v1.2.1](https://github.com/HKUDS/DeepTutor/releases/tag/v1.2.1) — Лимиты токенов по этапам, повторная генерация ответа во всех точках входа, исправления совместимости RAG и Gemma.

> **[2026.4.20]** [v1.2.0](https://github.com/HKUDS/DeepTutor/releases/tag/v1.2.0) — Компилятор Book Engine «живых книг», многодокументный Co-Writer, интерактивные HTML-визуализации, @-упоминания банка вопросов в чате.

> **[2026.4.18]** [v1.1.2](https://github.com/HKUDS/DeepTutor/releases/tag/v1.1.2) — Вкладка Channels на схеме, единый конвейер RAG, вынесенные промпты чата.

> **[2026.4.17]** [v1.1.1](https://github.com/HKUDS/DeepTutor/releases/tag/v1.1.1) — Универсальный «Ответить сейчас», синхронизация прокрутки Co-Writer, единая панель настроек, кнопка Stop при стриминге.

> **[2026.4.15]** [v1.1.0](https://github.com/HKUDS/DeepTutor/releases/tag/v1.1.0) — переработка разбора блочных формул LaTeX; LLM-диагностика через `agents.yaml`; исправление пересылки дополнительных заголовков; исправление UUID в SaveToNotebook; руководство по Docker и локальным LLM.

> **[2026.4.14]** [v1.1.0-beta](https://github.com/HKUDS/DeepTutor/releases/tag/v1.1.0-beta) — сессии с URL-закладками; тема Snow; heartbeat WebSocket и авто-переподключение; ускорение ChatComposer; переработка реестра провайдеров эмбеддингов; провайдер поиска Serper.

> **[2026.4.13]** [v1.0.3](https://github.com/HKUDS/DeepTutor/releases/tag/v1.0.3) — блокнот вопросов с закладками и категориями; Mermaid в Visualize; обнаружение несоответствия эмбеддингов; совместимость Qwen/vLLM; поддержка LM Studio и llama.cpp; тема Glass.

> **[2026.4.11]** [v1.0.2](https://github.com/HKUDS/DeepTutor/releases/tag/v1.0.2) — консолидация поиска с резервом SearXNG; исправление переключения провайдера; утечки ресурсов на фронтенде.

> **[2026.4.10]** [v1.0.1](https://github.com/HKUDS/DeepTutor/releases/tag/v1.0.1) — возможность Visualize (Chart.js/SVG); защита от дубликатов тестов; поддержка модели o4-mini.

> **[2026.4.10]** [v1.0.0-beta.4](https://github.com/HKUDS/DeepTutor/releases/tag/v1.0.0-beta.4) — прогресс эмбеддингов с повтором при лимите; кроссплатформенные зависимости; проверка MIME.

> **[2026.4.8]** [v1.0.0-beta.3](https://github.com/HKUDS/DeepTutor/releases/tag/v1.0.0-beta.3) — нативные SDK OpenAI/Anthropic (без litellm); Math Animator на Windows; более устойчичный разбор JSON; полная китайская i18n.

> **[2026.4.7]** [v1.0.0-beta.2](https://github.com/HKUDS/DeepTutor/releases/tag/v1.0.0-beta.2) — горячая перезагрузка настроек; вложенный вывод MinerU; исправление WebSocket; минимум Python 3.11+.

> **[2026.4.4]** [v1.0.0-beta.1](https://github.com/HKUDS/DeepTutor/releases/tag/v1.0.0-beta.1) — агентно-нативная переработка (~200k строк): плагины Tools + Capabilities, CLI и SDK, TutorBot, Co-Writer, Guided Learning и постоянная память.

> **[2026.1.23]** [v0.6.0](https://github.com/HKUDS/DeepTutor/releases/tag/v0.6.0) — сессии, инкрементальная загрузка, гибкий RAG, полная китайская локализация.

> **[2026.1.18]** [v0.5.2](https://github.com/HKUDS/DeepTutor/releases/tag/v0.5.2) — Docling, логи, исправления.

> **[2026.1.15]** [v0.5.0](https://github.com/HKUDS/DeepTutor/releases/tag/v0.5.0) — единая конфигурация, RAG по KB, генерация вопросов, боковая панель.

> **[2026.1.9]** [v0.4.0](https://github.com/HKUDS/DeepTutor/releases/tag/v0.4.0) — мульти-провайдеры LLM/эмбеддинги, новая главная, разделение RAG, переменные окружения.

> **[2026.1.5]** [v0.3.0](https://github.com/HKUDS/DeepTutor/releases/tag/v0.3.0) — PromptManager, CI/CD, образы GHCR.

> **[2026.1.2]** [v0.2.0](https://github.com/HKUDS/DeepTutor/releases/tag/v0.2.0) — Docker, Next.js 16 и React 19, WebSocket, уязвимости.

</details>

### 📰 Новости

> **[2026.4.19]** 🎉 20k звёзд за 111 дней! Спасибо за поддержку — продолжим итерации к по-настоящему персональному и умному обучению.

> **[2026.4.10]** 📄 Наша статья опубликована на arXiv! Читайте [препринт](https://arxiv.org/abs/2604.26962), чтобы узнать о дизайне и идеях DeepTutor.

> **[2026.4.4]** Давно не виделись! ✨ Вышел DeepTutor v1.0.0 — агентно-нативная эволюция: архитектура переписана с нуля, TutorBot и гибкие режимы под Apache-2.0. Начинается новая глава!

> **[2026.2.6]** 🚀 10k звёзд за 39 дней — спасибо сообществу!

> **[2026.1.1]** С Новым годом! [Discord](https://discord.gg/eRsjPgMU4t), [WeChat](https://github.com/HKUDS/DeepTutor/issues/78), [Discussions](https://github.com/HKUDS/DeepTutor/discussions).

> **[2025.12.29]** Официальный релиз DeepTutor.

<a id="key-features"></a>
## ✨ Ключевые возможности

- **Единое чат-пространство** — шесть режимов в одной ветке: Chat, Deep Solve, квизы, Deep Research, Math Animator и Visualize с общим контекстом.
- **AI Co-Writer** — мультидокументный Markdown: переписать, расширить, сократить с KB и вебом.
- **Book Engine** — структурированные интерактивные «живые книги»: мультиагентный конвейер, 13 типов блоков (квизы, карточки, таймлайны, графы концепций и др.).
- **Центр знаний** — RAG-базы, цветные блокноты, банк вопросов, пользовательские Skills.
- **Постоянная память** — сводка прогресса и профиль ученика; общая с TutorBot.
- **Персональные TutorBot** — не чат-боты: автономные репетиторы со своей памятью, личностью и навыками. [nanobot](https://github.com/HKUDS/nanobot).
- **Агентно-нативный CLI** — возможности, KB, сессии, TutorBot одной командой; Rich и JSON. [`SKILL.md`](../../SKILL.md).

---

<a id="get-started"></a>
## 🚀 Быстрый старт

### Предварительные требования

Перед началом убедитесь, что установлено:

| Требование | Версия | Проверка | Примечание |
|:---|:---|:---|:---|
| [Git](https://git-scm.com/) | любая | `git --version` | для клонирования |
| [Python](https://www.python.org/downloads/) | 3.11+ | `python --version` | backend |
| [Node.js](https://nodejs.org/) | 20.9+ | `node --version` | фронтенд-рантайм для локальных веб-установок |
| [npm](https://www.npmjs.com/) | входит в Node.js | `npm --version` | устанавливается вместе с Node.js |

Нужен как минимум один **API-ключ** LLM-провайдера (например [OpenAI](https://platform.openai.com/api-keys), [DeepSeek](https://platform.deepseek.com/), [Anthropic](https://console.anthropic.com/)). Мастер настройки подскажет, как его ввести.

### Вариант A — интерактивный тур (рекомендуется)

**Один интерактивный CLI-скрипт** ведёт от свежего клона к запущенному приложению — без ручного `pip install`, `npm install` и правки `.env`. В пошаговом сценарии из 7 этапов всё определяется, устанавливается и настраивается.

```bash
git clone https://github.com/HKUDS/DeepTutor.git
cd DeepTutor

# Виртуальное окружение Python (выберите одно):
conda create -n deeptutor python=3.11 && conda activate deeptutor   # Anaconda / Miniconda
python -m venv .venv && source .venv/bin/activate                    # macOS / Linux
python -m venv .venv && .venv\Scripts\activate                       # Windows

# Запуск тура
python scripts/start_tour.py
```

После завершения мастера:

```bash
python scripts/start_web.py
```

> **Ежедневный запуск** — обычно достаточно одного прохождения тура. Далее запускайте `python scripts/start_web.py` (URL фронтенда печатается в терминале). Повторно `start_tour.py` — только при смене провайдеров, портов или доработке зависимостей. В веб-**Настройках** также есть **Run Tour** для повторения подсвеченного тура по интерфейсу.

<a id="option-b-manual"></a>
### Вариант B — ручная локальная установка

Если нужен полный контроль, установите и настройте всё вручную.

**1. Установка зависимостей**

```bash
git clone https://github.com/HKUDS/DeepTutor.git
cd DeepTutor

# Создать и активировать окружение (как в варианте A)
conda create -n deeptutor python=3.11 && conda activate deeptutor

# DeepTutor с зависимостями backend + web-сервера
pip install -e ".[server]"

# Фронтенд (нужен Node.js 18+)
cd web && npm install && cd ..
```

**2. Настройка окружения**

```bash
cp .env.example .env
```

Отредактируйте `.env` и заполните как минимум обязательные поля:

```dotenv
# LLM (обязательно)
LLM_BINDING=openai
LLM_MODEL=gpt-4o-mini
LLM_API_KEY=sk-xxx
LLM_HOST=https://api.openai.com/v1

# Эмбеддинги (обязательно для базы знаний)
EMBEDDING_BINDING=openai
EMBEDDING_MODEL=text-embedding-3-large
EMBEDDING_API_KEY=sk-xxx
EMBEDDING_HOST=https://api.openai.com/v1
EMBEDDING_DIMENSION=3072
```

<details>
<summary><b>Поддерживаемые провайдеры LLM</b></summary>

| Провайдер | Binding | Базовый URL по умолчанию |
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
<summary><b>Поддерживаемые провайдеры эмбеддингов</b></summary>

| Провайдер | Binding | Пример модели | Размерность по умолчанию |
|:--|:--|:--|:--|
| OpenAI | `openai` | `text-embedding-3-large` | 3072 |
| Azure OpenAI | `azure_openai` | имя развёртывания | — |
| Cohere | `cohere` | `embed-v4.0` | 1024 |
| Jina | `jina` | `jina-embeddings-v3` | 1024 |
| Ollama | `ollama` | `nomic-embed-text` | 768 |
| vLLM / LM Studio | `vllm` | Любая embedding-модель | — |
| OpenAI-совместимый | `custom` | — | — |

OpenAI-совместимые провайдеры (DashScope, SiliconFlow и др.) работают через binding `custom` или `openai`.

</details>

<details>
<summary><b>Поддерживаемые веб-поисковые провайдеры</b></summary>

| Провайдер | Переменная окружения | Примечания |
|:--|:--|:--|
| Brave | `BRAVE_API_KEY` | Рекомендуется, есть бесплатный уровень |
| Tavily | `TAVILY_API_KEY` | |
| Serper | `SERPER_API_KEY` | Результаты Google через Serper |
| Jina | `JINA_API_KEY` | |
| SearXNG | — | Самохостинг, без API-ключа |
| DuckDuckGo | — | Без API-ключа |
| Perplexity | `PERPLEXITY_API_KEY` | Нужен API-ключ |

</details>

**3. Запуск сервисов**

Самый быстрый способ:

```bash
python scripts/start_web.py
```

Запускает backend и frontend и открывает браузер.

Или запускайте вручную в отдельных терминалах:

```bash
# Backend (FastAPI)
python -m deeptutor.api.run_server

# Frontend (Next.js) — другой терминал
cd web && npm run dev -- -p 3782
```

| Сервис | Порт по умолчанию |
|:---:|:---:|
| Backend | `8001` |
| Frontend | `3782` |

Откройте [http://localhost:3782](http://localhost:3782).

### Вариант C — Docker

Docker упаковывает backend и frontend в один контейнер; локальные Python и Node.js не нужны. Достаточно [Docker Desktop](https://www.docker.com/products/docker-desktop/) (или Docker Engine + Compose на Linux).

**1. Переменные окружения** (нужны для обоих вариантов ниже)

```bash
git clone https://github.com/HKUDS/DeepTutor.git
cd DeepTutor
cp .env.example .env
```

Заполните `.env` как минимум обязательные поля (как в [варианте B](#option-b-manual)).

**2a. Официальный образ (рекомендуется)**

Официальные образы публикуются в [GitHub Container Registry](https://github.com/HKUDS/DeepTutor/pkgs/container/deeptutor) для `linux/amd64` и `linux/arm64`.

```bash
docker compose -f docker-compose.ghcr.yml up -d
```

Чтобы зафиксировать версию, измените тег образа в `docker-compose.ghcr.yml`:

```yaml
image: ghcr.io/hkuds/deeptutor:1.0.0  # или :latest
```

**2b. Сборка из исходников**

```bash
docker compose up -d
```

Собирает образ из `Dockerfile` локально и запускает контейнер.

**3. Проверка и управление**

Откройте [http://localhost:3782](http://localhost:3782), когда контейнер станет healthy.

```bash
docker compose logs -f   # логи
docker compose down       # остановить и удалить контейнер
```

<details>
<summary><b>Облако / удалённый сервер</b></summary>

На удалённом сервере браузеру нужен публичный URL backend API. Добавьте в `.env`:

```dotenv
# Публичный URL, по которому доступен backend
NEXT_PUBLIC_API_BASE_EXTERNAL=https://your-server.com:8001
```

Скрипт запуска фронтенда подставляет значение во время выполнения — пересборка не нужна.

</details>

<details>
<summary><b>Аутентификация (публичные деплои)</b></summary>

Аутентификация **отключена по умолчанию** — на localhost логин не нужен. Для мультитенантного деплоя смотрите раздел [Мультипользователь](#multi-user) ниже.

**Одиночный пользователь без браузера (без `/register`):** предварительная настройка через env-переменные:

```bash
python -c "from deeptutor.services.auth import hash_password; print(hash_password('yourpassword'))"
```

```dotenv
AUTH_ENABLED=true
AUTH_USERNAME=admin
AUTH_PASSWORD_HASH=<вставьте хеш>
AUTH_SECRET=your-secret-here
```

</details>

<details>
<summary><b>PocketBase сайдкар (опциональные аутентификация и хранилище)</b></summary>

PocketBase — опциональный лёгкий бэкенд, заменяющий встроенные SQLite/JSON аутентификацию и хранилище сессий.

> ⚠️ **PocketBase режим только для одиночного пользователя.** Нет поля `role` в `users`, запросы не фильтруются по `user_id`. Мультипользователь: оставьте `POCKETBASE_URL` пустым.

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
<summary><b>Режим разработки (hot-reload)</b></summary>

Подключите dev-override, чтобы смонтировать исходники и включить hot-reload для обоих сервисов:

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up
```

Изменения в `deeptutor/`, `deeptutor_cli/`, `scripts/` и `web/` применяются сразу.

</details>

<details>
<summary><b>Свои порты</b></summary>

Переопределите порты в `.env`:

```dotenv
BACKEND_PORT=9001
FRONTEND_PORT=4000
```

Затем перезапустите:

```bash
docker compose up -d     # или docker compose -f docker-compose.ghcr.yml up -d
```

</details>

<details>
<summary><b>Персистентность данных</b></summary>

Данные пользователя и базы знаний сохраняются через Docker-тома в локальные каталоги:

| Путь в контейнере | Путь на хосте | Содержимое |
|:---|:---|:---|
| `/app/data/user` | `./data/user` | Настройки, workspace, сессии, логи |
| `/app/data/memory` | `./data/memory` | Общая долгосрочная память (`SUMMARY.md`, `PROFILE.md`) |
| `/app/data/knowledge_bases` | `./data/knowledge_bases` | Загруженные документы и векторные индексы |

Каталоги сохраняются после `docker compose down` и используются снова при следующем `up`.

</details>

<details>
<summary><b>Справочник переменных окружения</b></summary>

| Переменная | Обяз. | Описание |
|:---|:---:|:---|
| `LLM_BINDING` | **Да** | Провайдер LLM (`openai`, `anthropic`, …) |
| `LLM_MODEL` | **Да** | Имя модели (напр. `gpt-4o`) |
| `LLM_API_KEY` | **Да** | API-ключ LLM |
| `LLM_HOST` | **Да** | URL эндпоинта |
| `EMBEDDING_BINDING` | **Да** | Провайдер эмбеддингов |
| `EMBEDDING_MODEL` | **Да** | Имя модели эмбеддингов |
| `EMBEDDING_API_KEY` | **Да** | Ключ API эмбеддингов |
| `EMBEDDING_HOST` | **Да** | Эндпоинт эмбеддингов |
| `EMBEDDING_DIMENSION` | **Да** | Размерность вектора |
| `SEARCH_PROVIDER` | Нет | Поиск (`tavily`, `jina`, `serper`, `perplexity`, …) |
| `SEARCH_API_KEY` | Нет | Ключ поиска |
| `BACKEND_PORT` | Нет | Порт backend (по умолч. `8001`) |
| `FRONTEND_PORT` | Нет | Порт frontend (по умолч. `3782`) |
| `NEXT_PUBLIC_API_BASE_EXTERNAL` | Нет | Публичный URL backend для облака |
| `DISABLE_SSL_VERIFY` | Нет | Отключить проверку SSL (по умолч. `false`) |

</details>

### Вариант D — только CLI

Если нужен только CLI без веб-интерфейса:

```bash
pip install -e ".[cli]"
```

Провайдер LLM всё равно нужно настроить. Быстрый путь:

```bash
cp .env.example .env   # затем отредактируйте .env и укажите ключи
```

После настройки:

```bash
deeptutor chat
deeptutor run chat "Explain Fourier transform"
deeptutor run deep_solve "Solve x^2 = 4"
deeptutor kb create my-kb --doc textbook.pdf
```

> Полное руководство: [DeepTutor CLI](#deeptutor-cli-guide).

---

<a id="explore-deeptutor"></a>
## 📖 Обзор DeepTutor

<div align="center">
<img src="../../assets/figs/deeptutor-architecture.png" alt="Архитектура DeepTutor" width="800">
</div>

### 💬 Чат — единое интеллектуальное пространство

<div align="center">
<img src="../../assets/figs/dt-chat.png" alt="Чат" width="800">
</div>

Шесть режимов, **единый контекст**.

| Режим | Назначение |
|:---|:---|
| **Chat** | RAG, веб, код, рассуждения, мозговой штурм, статьи. |
| **Deep Solve** | Мультиагенты с цитатами. |
| **Генерация квизов** | Оценки по KB. |
| **Deep Research** | Подтемы, параллельные агенты, отчёт с ссылками. |
| **Math Animator** | Manim. |
| **Visualize** | SVG, Chart.js, Mermaid или автономный HTML из естественного языка. |

Инструменты **отделены от сценариев**.

### ✍️ Co-Writer — мультидокументное пространство с ИИ

<div align="center">
<img src="../../assets/figs/dt-cowriter.png" alt="Co-Writer" width="800">
</div>

Создавайте несколько документов с отдельным хранением — не одноразовый черновик: полноценный Markdown, ИИ как соавтор. **Переписать**, **Расширить**, **Сократить**; отмена/повтор; блокноты.

### 📖 Book Engine — интерактивные «живые книги»

<div align="center">
<img src="../../assets/figs/dt-book-0.png" alt="Библиотека" width="270"><img src="../../assets/figs/dt-book-1.png" alt="Читалка" width="270"><img src="../../assets/figs/dt-book-2.png" alt="Анимация" width="270">
</div>

Задайте тему и укажите базу знаний — получите структурированную интерактивную книгу: живой документ для чтения, самопроверки и обсуждения в контексте.

Сзади мультиагенты предлагают план, извлекают источники, собирают дерево глав, планируют страницы и компилируют блоки. Вы управляете: проверка плана, порядок глав, чат рядом со страницей.

13 типов блоков — текст, выноска, квиз, карточки, код, рисунок, углубление, анимация, интерактив, таймлайн, граф концепций, раздел, заметка пользователя — с отдельными интерактивными компонентами. Линия прогресса в реальном времени.

### 📚 Управление знаниями

<div align="center">
<img src="../../assets/figs/dt-knowledge.png" alt="Знания" width="800">
</div>

Коллекции документов, заметки и учебные персоны.

- **Базы знаний** — PDF, TXT, MD.  
- **Блокноты** — записи из Chat, Co-Writer, Book или Deep Research, по цветам.
- **Банк вопросов** — просмотр квизов; закладки и @-упоминания в чате для анализа прошлых результатов.
- **Skills** — персоны через `SKILL.md`: имя, описание, триггеры, Markdown в системный промпт чата при активации.

### 🧠 Память

<div align="center">
<img src="../../assets/figs/dt-memory.png" alt="Память" width="800">
</div>

- **Сводка** — прогресс.  
- **Профиль** — предпочтения, уровень, цели. Общая с TutorBot.

---

<a id="tutorbot"></a>
### 🦞 TutorBot — постоянные автономные ИИ-репетиторы

<div align="center">
<img src="../../assets/figs/tutorbot-architecture.png" alt="Архитектура TutorBot" width="800">
</div>

**Мультиинстансный** агент на [nanobot](https://github.com/HKUDS/nanobot): свой цикл, workspace, память, личность.

<div align="center">
<img src="../../assets/figs/tb.png" alt="TutorBot" width="800">
</div>

- **Шаблоны Soul** — личность и педагогика.  
- **Отдельный workspace** — память, сессии, навыки; общий слой DeepTutor.  
- **Проактивный Heartbeat** — напоминания и задачи.  
- **Полный набор инструментов** — RAG, код, веб, статьи, рассуждения, мозговой штурм.  
- **Навыки** — файлы skill.  
- **Мультиканал** — Telegram, Discord, Slack, Feishu, WeCom, DingTalk, почта и др.  
- **Команды и субагенты**.

```bash
deeptutor bot create math-tutor --persona "Socratic math teacher who uses probing questions"
deeptutor bot create writing-coach --persona "Patient, detail-oriented writing mentor"
deeptutor bot list
```

---

<a id="deeptutor-cli-guide"></a>
### ⌨️ DeepTutor CLI — интерфейс для агентов

<div align="center">
<img src="../../assets/figs/cli-architecture.png" alt="CLI" width="800">
</div>

Без браузера: возможности, KB, сессии, память, TutorBot. Rich + JSON. [`SKILL.md`](../../SKILL.md).

```bash
deeptutor run chat "Explain the Fourier transform" -t rag --kb textbook
deeptutor run deep_solve "Prove that √2 is irrational" -t reason
deeptutor run deep_question "Linear algebra" --config num_questions=5
deeptutor run deep_research "Attention mechanisms in transformers"
deeptutor run visualize "Draw the architecture of a transformer"
```

```bash
deeptutor chat --capability deep_solve --kb my-kb
# В REPL: /cap, /tool, /kb, /history, /notebook, /config для переключения на лету
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
<summary><b>Полная справка по CLI</b></summary>

**Верхний уровень**

| Команда | Описание |
|:---|:---|
| `deeptutor run <capability> <message>` | Запуск возможности за один ход (`chat`, `deep_solve`, `deep_question`, `deep_research`, `math_animator`, `visualize`) |
| `deeptutor chat` | Интерактивный REPL с `--capability`, `--tool`, `--kb`, `--language` и др. |
| `deeptutor serve` | Запуск сервера API DeepTutor |

**`deeptutor bot`**

| Команда | Описание |
|:---|:---|
| `deeptutor bot list` | Список экземпляров TutorBot |
| `deeptutor bot create <id>` | Создать и запустить бота (`--name`, `--persona`, `--model`) |
| `deeptutor bot start <id>` | Запустить бота |
| `deeptutor bot stop <id>` | Остановить бота |

**`deeptutor kb`**

| Команда | Описание |
|:---|:---|
| `deeptutor kb list` | Список баз знаний |
| `deeptutor kb info <name>` | Детали базы |
| `deeptutor kb create <name>` | Создать из документов (`--doc`, `--docs-dir`) |
| `deeptutor kb add <name>` | Добавить документы |
| `deeptutor kb search <name> <query>` | Поиск по базе |
| `deeptutor kb set-default <name>` | База по умолчанию |
| `deeptutor kb delete <name>` | Удалить (`--force`) |

**`deeptutor memory`**

| Команда | Описание |
|:---|:---|
| `deeptutor memory show [file]` | Просмотр (`summary`, `profile`, `all`) |
| `deeptutor memory clear [file]` | Очистить (`--force`) |

**`deeptutor session`**

| Команда | Описание |
|:---|:---|
| `deeptutor session list` | Список сессий (`--limit`) |
| `deeptutor session show <id>` | Сообщения сессии |
| `deeptutor session open <id>` | Продолжить в REPL |
| `deeptutor session rename <id>` | Переименовать (`--title`) |
| `deeptutor session delete <id>` | Удалить |

**`deeptutor notebook`**

| Команда | Описание |
|:---|:---|
| `deeptutor notebook list` | Список блокнотов |
| `deeptutor notebook create <name>` | Создать (`--description`) |
| `deeptutor notebook show <id>` | Записи |
| `deeptutor notebook add-md <id> <path>` | Импорт Markdown |
| `deeptutor notebook replace-md <id> <rec> <path>` | Заменить запись |
| `deeptutor notebook remove-record <id> <rec>` | Удалить запись |

**`deeptutor book`**

| Команда | Описание |
|:---|:---|
| `deeptutor book list` | Список всех книг в рабочей области |
| `deeptutor book health <book_id>` | Дрейф KB и состояние книги |
| `deeptutor book refresh-fingerprints <book_id>` | Обновить отпечатки KB и очистить устаревшие страницы |

**`deeptutor config` / `plugin` / `provider`**

| Команда | Описание |
|:---|:---|
| `deeptutor config show` | Сводка конфигурации |
| `deeptutor plugin list` | Зарегистрированные инструменты и возможности |
| `deeptutor plugin info <name>` | Детали инструмента или возможности |
| `deeptutor provider login <provider>` | Аутентификация у провайдера (OAuth для `openai-codex`; `github-copilot` проверяет существующую сессию Copilot) |

</details>

---

<a id="multi-user"></a>
### 👥 Мультипользователь — совместные деплои с рабочими пространствами для каждого пользователя

<div align="center">
<img src="../../assets/figs/dt-multi-user.png" alt="Мультипользователь" width="800">
</div>

Включите аутентификацию — и DeepTutor превращается в мультитенантный деплой с **изолированными рабочими пространствами** и **ресурсами, курируемыми администратором**. Первый зарегистрировавшийся становится администратором и настраивает модели, API-ключи и базы знаний для всех. Последующие аккаунты создаёт администратор (только по приглашению).

**Быстрый старт (5 шагов):**

```bash
# 1. Включите аутентификацию в .env в корне проекта
echo 'AUTH_ENABLED=true' >> .env
echo 'AUTH_SECRET=<вставьте 64+ случайных символа>' >> .env

# 2. Перезапустите веб-стек
python scripts/start_web.py

# 3. Откройте http://localhost:3782/register и создайте первый аккаунт
#    Первая регистрация — единственная публичная; этот пользователь
#    становится администратором, и /register автоматически закрывается

# 4. Как администратор, откройте /admin/users → «Добавить пользователя»

# 5. Для каждого пользователя нажмите значок ползунка → назначьте
#    профили LLM, базы знаний и навыки → сохраните
```

**Что видит администратор:**

- **Полная страница настроек** в `/settings` — LLM/эмбеддинг/поиск, API-ключи, каталог моделей.
- **Управление пользователями** в `/admin/users` — создание, повышение, понижение и удаление аккаунтов.
- **Редактор грантов** — выбор профилей моделей, КБ и навыков для не-администраторов; гранты содержат **только логические ID**, API-ключи не пересекают границу.
- **Журнал аудита** — каждое изменение гранта в `multi-user/_system/audit/usage.jsonl`.

**Что получают обычные пользователи:**

- **Изолированное рабочее пространство** в `multi-user/<uid>/` — собственные `chat_history.db`, память, блокноты и базы знаний.
- **Доступ только для чтения** к назначенным администратором КБ и навыкам с пометкой «Назначено администратором».
- **Сокращённая страница настроек** — только тема, язык и сводка предоставленных моделей.
- **Ограниченный LLM** — разговоры маршрутизируются через назначенную администратором модель; без гранта — отказ на входе.

**Структура рабочего пространства:**

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

**Справочник конфигурации:**

| Переменная | Обяз. | Описание |
|:---|:---|:---|
| `AUTH_ENABLED` | Да | `true` для включения мультипользовательской аутентификации. По умолчанию `false`. |
| `AUTH_SECRET` | Рекомендуется | Секрет подписи JWT; пустое значение — автогенерация в `multi-user/_system/auth/auth_secret`. |
| `AUTH_TOKEN_EXPIRE_HOURS` | Нет | Срок JWT; по умолчанию 24 часа. |
| `AUTH_USERNAME` / `AUTH_PASSWORD_HASH` | Нет | Резервные учётные данные для одиночного пользователя. Оставьте пустым в мультипользовательском режиме. |
| `NEXT_PUBLIC_AUTH_ENABLED` | Авто | Зеркалируется из `AUTH_ENABLED` через `start_web.py`. |

> ⚠️ **PocketBase режим (`POCKETBASE_URL` задан) — только для одиночного пользователя** — нет поля `role`, нет фильтрации по `user_id`. Мультипользователь: оставьте `POCKETBASE_URL` пустым.

> ⚠️ **Рекомендуется один процесс.** Повышение первого администратора защищено `threading.Lock`. Несколько воркеров: создайте первого администратора офлайн.

<a id="roadmap"></a>
## 🗺️ Дорожная карта

| Статус | Этап |
|:---:|:---|
| 🎯 | **Аутентификация и вход** — опциональная страница входа для публичных развёртываний и мультипользовательский режим |
| 🎯 | **Темы и оформление** — разнообразные темы и настройка интерфейса |
| 🎯 | **Улучшение интерфейса** — доработка иконок и деталей взаимодействия |
| 🔜 | **Улучшенная память** — более мощное управление памятью |
| 🔜 | **Интеграция LightRAG** — подключение [LightRAG](https://github.com/HKUDS/LightRAG) как продвинутого движка баз знаний |
| 🔜 | **Сайт документации** — полная документация: руководства, справочник API и учебные материалы |

> Если DeepTutor вам полезен, [поставьте звезду](https://github.com/HKUDS/DeepTutor/stargazers) — это помогает проекту!

---

<a id="community"></a>
## 🌐 Сообщество и экосистема

| Проект | Роль |
|:---|:---|
| [**nanobot**](https://github.com/HKUDS/nanobot) | Движок TutorBot |
| [**LlamaIndex**](https://github.com/run-llama/llama_index) | RAG |
| [**ManimCat**](https://github.com/Wing900/ManimCat) | Math Animator |

| [⚡ LightRAG](https://github.com/HKUDS/LightRAG) | [🤖 AutoAgent](https://github.com/HKUDS/AutoAgent) | [🔬 AI-Researcher](https://github.com/HKUDS/AI-Researcher) | [🧬 nanobot](https://github.com/HKUDS/nanobot) |
|:---:|:---:|:---:|:---:|
| Быстрый RAG | Агенты без кода | Автоисследования | Лёгкий агент |

## 🤝 Участие

<div align="center">

Надеемся, что DeepTutor станет подарком сообществу. 🎁

<a href="https://github.com/HKUDS/DeepTutor/graphs/contributors">
  <img src="https://contrib.rocks/image?repo=HKUDS/DeepTutor&max=999" alt="Contributors" />
</a>
</div>

См. [CONTRIBUTING.md](../../CONTRIBUTING.md).

## ⭐ История звёзд

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
