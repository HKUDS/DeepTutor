<div align="center">

<img src="../../assets/logo-ver2.png" alt="DeepTutor" width="140" style="border-radius: 15px;">

# DeepTutor : vers un tutorat personnalisé fondé sur les agents

[![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-3776AB?style=flat-square&logo=python&logoColor=white)](https://www.python.org/downloads/)
[![Next.js 16](https://img.shields.io/badge/Next.js-16-000000?style=flat-square&logo=next.js&logoColor=white)](https://nextjs.org/)
[![License](https://img.shields.io/badge/License-Apache_2.0-blue?style=flat-square)](../../LICENSE)
[![GitHub release](https://img.shields.io/github/v/release/HKUDS/DeepTutor?style=flat-square&color=brightgreen)](https://github.com/HKUDS/DeepTutor/releases)
[![GitHub last commit](https://img.shields.io/github/last-commit/HKUDS/DeepTutor?style=flat-square)](https://github.com/HKUDS/DeepTutor/commits)

[![Discord](https://img.shields.io/badge/Discord-Community-5865F2?style=flat-square&logo=discord&logoColor=white)](https://discord.gg/eRsjPgMU4t)
[![Feishu](https://img.shields.io/badge/Feishu-Group-00D4AA?style=flat-square&logo=feishu&logoColor=white)](../../Communication.md)
[![WeChat](https://img.shields.io/badge/WeChat-Group-07C160?style=flat-square&logo=wechat&logoColor=white)](https://github.com/HKUDS/DeepTutor/issues/78)

[Fonctionnalités](#key-features) · [Démarrage](#get-started) · [Explorer](#explore-deeptutor) · [TutorBot](#tutorbot) · [CLI](#deeptutor-cli-guide) · [Communauté](#community)

[🇬🇧 English](../../README.md) · [🇨🇳 中文](README_CN.md) · [🇯🇵 日本語](README_JA.md) · [🇪🇸 Español](README_ES.md) · [🇸🇦 العربية](README_AR.md) · [🇷🇺 Русский](README_RU.md) · [🇮🇳 हिन्दी](README_HI.md) · [🇵🇹 Português](README_PT.md)

</div>

---
### 📰 Actualités

> **[2026.3.24]** DeepTutor v1.0.0 est là ✨ — évolution native agents : refactor léger, TutorBot, modes flexibles sous Apache-2.0.

> **[2026.2.6]** 🚀 10k étoiles en 39 jours — merci à la communauté !

> **[2026.1.1]** Bonne année ! Rejoignez [Discord](https://discord.gg/eRsjPgMU4t), [WeChat](https://github.com/HKUDS/DeepTutor/issues/78) ou [Discussions](https://github.com/HKUDS/DeepTutor/discussions).

> **[2025.12.29]** DeepTutor est officiellement publié.

### 📦 Versions

> **[2026.3.24]** [v1.0.0](https://github.com/HKUDS/DeepTutor/releases/tag/v1.0.0) — Refonte native agents, outils flexibles, entrées CLI et SDK, TutorBot nanobot, Co-Writer, apprentissage guidé, mémoire persistante.

<details>
<summary><b>Versions précédentes</b></summary>

> **[2026.1.23]** [v0.6.0](https://github.com/HKUDS/DeepTutor/releases/tag/v0.6.0) — Persistance de session, import incrémental, RAG flexible, localisation chinoise complète.

> **[2026.1.18]** [v0.5.2](https://github.com/HKUDS/DeepTutor/releases/tag/v0.5.2) — Docling, journaux, correctifs.

> **[2026.1.15]** [v0.5.0](https://github.com/HKUDS/DeepTutor/releases/tag/v0.5.0) — Config unifiée, RAG par KB, génération de questions, barre latérale.

> **[2026.1.9]** [v0.4.0](https://github.com/HKUDS/DeepTutor/releases/tag/v0.4.0) — Multi-fournisseurs LLM/embeddings, nouvelle page d’accueil, découplage RAG, variables d’environnement.

> **[2026.1.5]** [v0.3.0](https://github.com/HKUDS/DeepTutor/releases/tag/v0.3.0) — PromptManager, CI/CD, images GHCR.

> **[2026.1.2]** [v0.2.0](https://github.com/HKUDS/DeepTutor/releases/tag/v0.2.0) — Docker, Next.js 16 et React 19, WebSocket, vulnérabilités.

</details>

<a id="key-features"></a>
## ✨ Points clés

- **Espace de chat unifié** — Cinq modes, un fil : Chat, Deep Solve, quiz, Deep Research, Math Animator partagent le contexte.
- **TutorBots personnels** — Pas des chatbots : tuteurs autonomes, espace de travail, mémoire, personnalité, compétences. [nanobot](https://github.com/HKUDS/nanobot).
- **AI Co-Writer** — Markdown : réécrire, développer, raccourcir avec KB et web.
- **Apprentissage guidé** — Parcours visuels par étapes à partir de vos documents.
- **Hub de connaissances** — PDF, Markdown, texte pour des bases RAG ; carnets colorés.
- **Mémoire persistante** — Synthèse de progression et profil d’apprenant ; partagé avec les TutorBots.
- **CLI natif agents** — Capacités, KB, sessions, TutorBot en une commande ; Rich et JSON. [`SKILL.md`](../../SKILL.md) pour les agents.

---

<a id="get-started"></a>
## 🚀 Démarrage

### Option A — Visite guidée (recommandé)

Un **script interactif** : dépendances, configuration, tests, lancement.

```bash
git clone https://github.com/HKUDS/DeepTutor.git
cd DeepTutor

conda create -n deeptutor python=3.11 && conda activate deeptutor
# ou : python -m venv .venv && source .venv/bin/activate

python scripts/start_tour.py
```

- **Mode web** — Profil, pip + npm, serveur temporaire, page **Paramètres**, tour en 4 étapes (LLM, embeddings, recherche).
- **Mode CLI** — Tout dans le terminal.

[http://localhost:3782](http://localhost:3782)

<a id="option-b-manual"></a>
### Option B — Installation locale manuelle

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

| Service | Port |
|:---:|:---:|
| Backend | `8001` |
| Frontend | `3782` |

### Option C — Docker

```bash
git clone https://github.com/HKUDS/DeepTutor.git
cd DeepTutor
cp .env.example .env
```

Comme [option B](#option-b-manual).

**2a. Image officielle** — [GHCR](https://github.com/HKUDS/DeepTutor/pkgs/container/deeptutor)

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
<summary><b>Cloud / serveur distant</b></summary>

```dotenv
NEXT_PUBLIC_API_BASE_EXTERNAL=https://your-server.com:8001
```

</details>

<details>
<summary><b>Mode développement (rechargement)</b></summary>

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up
```

</details>

<details>
<summary><b>Ports personnalisés</b></summary>

```dotenv
BACKEND_PORT=9001
FRONTEND_PORT=4000
```

</details>

<details>
<summary><b>Persistance des données</b></summary>

| Conteneur | Hôte | Contenu |
|:---|:---|:---|
| `/app/data/user` | `./data/user` | Réglages, mémoire, espace de travail, sessions, journaux |
| `/app/data/knowledge_bases` | `./data/knowledge_bases` | Documents et vecteurs |

</details>

<details>
<summary><b>Variables d’environnement</b></summary>

| Variable | Obligatoire | Description |
|:---|:---:|:---|
| `LLM_BINDING` | **Oui** | Fournisseur LLM |
| `LLM_MODEL` | **Oui** | Modèle |
| `LLM_API_KEY` | **Oui** | Clé |
| `LLM_HOST` | **Oui** | URL |
| `EMBEDDING_BINDING` | **Oui** | Embeddings |
| `EMBEDDING_MODEL` | **Oui** | Modèle |
| `EMBEDDING_API_KEY` | **Oui** | Clé |
| `EMBEDDING_HOST` | **Oui** | URL |
| `EMBEDDING_DIMENSION` | **Oui** | Dimension |
| `SEARCH_PROVIDER` | Non | Recherche |
| `SEARCH_API_KEY` | Non | Clé |
| `BACKEND_PORT` | Non | Défaut `8001` |
| `FRONTEND_PORT` | Non | Défaut `3782` |
| `NEXT_PUBLIC_API_BASE_EXTERNAL` | Non | URL publique |
| `DISABLE_SSL_VERIFY` | Non | Défaut `false` |

</details>

### Option D — CLI uniquement

```bash
pip install -e ".[cli]"
deeptutor chat
deeptutor run chat "Explain Fourier transform"
deeptutor run deep_solve "Solve x^2 = 4"
deeptutor kb create my-kb --doc textbook.pdf
```

> Guide complet : [DeepTutor CLI](#deeptutor-cli-guide).

---

<a id="explore-deeptutor"></a>
## 📖 Explorer DeepTutor

<div align="center">
<img src="../../assets/figs/deeptutor-architecture.png" alt="Architecture DeepTutor" width="800">
</div>

### 💬 Chat — Espace intelligent unifié

<div align="center">
<img src="../../assets/figs/dt-chat.png" alt="Chat" width="800">
</div>

Cinq modes, **contexte unifié**.

| Mode | Rôle |
|:---|:---|
| **Chat** | RAG, web, code, raisonnement, brainstorming, articles. |
| **Deep Solve** | Multi-agents avec citations. |
| **Génération de quiz** | Évaluations ancrées à la KB. |
| **Deep Research** | Sous-sujets, agents parallèles, rapport cité. |
| **Math Animator** | Manim. |

Les outils sont **découplés des flux** — vous choisissez ce qui est actif.

### ✍️ Co-Writer — IA dans l’éditeur

<div align="center">
<img src="../../assets/figs/dt-cowriter.png" alt="Co-Writer" width="800">
</div>

**Réécrire**, **Développer**, **Raccourcir** ; annuler/refaire ; carnets.

### 🎓 Apprentissage guidé

<div align="center">
<img src="../../assets/figs/dt-guide.png" alt="Guidé" width="800">
</div>

1. Plan (3–5 points).  
2. Pages interactives.  
3. Q&R contextuelles.  
4. Synthèse.

### 📚 Gestion des connaissances

<div align="center">
<img src="../../assets/figs/dt-knowledge.png" alt="Connaissances" width="800">
</div>

- **Bases de connaissances** — PDF, TXT, MD.  
- **Carnets** — Couleurs et sessions.

### 🧠 Mémoire

<div align="center">
<img src="../../assets/figs/dt-memory.png" alt="Mémoire" width="800">
</div>

- **Synthèse** — Progression.  
- **Profil** — Préférences, niveau, objectifs. Partagé avec TutorBots.

---

<a id="tutorbot"></a>
### 🦞 TutorBot — Tuteurs IA persistants et autonomes

<div align="center">
<img src="../../assets/figs/tutorbot-architecture.png" alt="Architecture TutorBot" width="800">
</div>

Agent **multi-instance** persistant sur [nanobot](https://github.com/HKUDS/nanobot) : boucle, espace, mémoire, personnalité propres.

<div align="center">
<img src="../../assets/figs/tb.png" alt="TutorBot" width="800">
</div>

- **Modèles Soul** — Personnalité et pédagogie.  
- **Espace indépendant** — Mémoire, sessions, compétences ; couche partagée DeepTutor.  
- **Heartbeat proactif** — Rappels et tâches.  
- **Outils complets** — RAG, code, web, papers, raisonnement, brainstorming.  
- **Compétences** — Fichiers skill.  
- **Multicanal** — Telegram, Discord, Slack, Feishu, WeCom, DingTalk, e-mail, etc.  
- **Équipes et sous-agents**.

```bash
deeptutor bot create math-tutor --persona "Socratic math teacher who uses probing questions"
deeptutor bot create writing-coach --persona "Patient, detail-oriented writing mentor"
deeptutor bot list
```

---

<a id="deeptutor-cli-guide"></a>
### ⌨️ DeepTutor CLI — Interface native pour agents

<div align="center">
<img src="../../assets/figs/cli-architecture.png" alt="CLI" width="800">
</div>

Sans navigateur : capacités, KB, sessions, mémoire, TutorBot. Rich + JSON. [`SKILL.md`](../../SKILL.md).

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
<summary><b>Référence CLI complète</b></summary>

| Commande | Description |
|:---|:---|
| `deeptutor run <capability> <message>` | Un tour |
| `deeptutor chat` | REPL |
| `deeptutor serve` | API |

**bot**, **kb**, **memory**, **session**, **notebook**, **config / plugin / provider** — comme la version anglaise.

</details>

<a id="community"></a>
## 🌐 Communauté et écosystème

| Projet | Rôle |
|:---|:---|
| [**nanobot**](https://github.com/HKUDS/nanobot) | Moteur TutorBot |
| [**LlamaIndex**](https://github.com/run-llama/llama_index) | RAG |
| [**ManimCat**](https://github.com/Wing900/ManimCat) | Math Animator |

| [⚡ LightRAG](https://github.com/HKUDS/LightRAG) | [🤖 AutoAgent](https://github.com/HKUDS/AutoAgent) | [🔬 AI-Researcher](https://github.com/HKUDS/AI-Researcher) | [🧬 nanobot](https://github.com/HKUDS/nanobot) |
|:---:|:---:|:---:|:---:|
| RAG rapide | Agents sans code | Recherche auto | Agent léger |

## 🤝 Contribuer

<div align="center">
<a href="https://github.com/HKUDS/DeepTutor/graphs/contributors">
  <img src="https://contrib.rocks/image?repo=HKUDS/DeepTutor&max=999" alt="Contributors" />
</a>
</div>

Voir [CONTRIBUTING.md](../../CONTRIBUTING.md).

## ⭐ Historique des étoiles

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

[Licence Apache 2.0](../../LICENSE)

<p>
  <img src="https://visitor-badge.laobi.icu/badge?page_id=HKUDS.DeepTutor&style=for-the-badge&color=00d4ff" alt="Views">
</p>

</div>
