<div align="center">

<img src="../../assets/logo-ver2.png" alt="DeepTutor" width="140" style="border-radius: 15px;">

# DeepTutor : tutorat personnalisé natif aux agents

<a href="https://trendshift.io/repositories/17099" target="_blank"><img src="https://trendshift.io/api/badge/repositories/17099" alt="HKUDS%2FDeepTutor | Trendshift" style="width: 250px; height: 55px;" width="250" height="55"/></a>

[![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-3776AB?style=flat-square&logo=python&logoColor=white)](https://www.python.org/downloads/)
[![Next.js 16](https://img.shields.io/badge/Next.js-16-000000?style=flat-square&logo=next.js&logoColor=white)](https://nextjs.org/)
[![License](https://img.shields.io/badge/License-Apache_2.0-blue?style=flat-square)](../../LICENSE)
[![GitHub release](https://img.shields.io/github/v/release/HKUDS/DeepTutor?style=flat-square&color=brightgreen)](https://github.com/HKUDS/DeepTutor/releases)
[![arXiv](https://img.shields.io/badge/arXiv-2604.26962-b31b1b?style=flat-square&logo=arxiv&logoColor=white)](https://arxiv.org/abs/2604.26962)

[![Discord](https://img.shields.io/badge/Discord-Community-5865F2?style=flat-square&logo=discord&logoColor=white)](https://discord.gg/eRsjPgMU4t)
[![Feishu](https://img.shields.io/badge/Feishu-Group-00D4AA?style=flat-square&logo=feishu&logoColor=white)](../../Communication.md)
[![WeChat](https://img.shields.io/badge/WeChat-Group-07C160?style=flat-square&logo=wechat&logoColor=white)](https://github.com/HKUDS/DeepTutor/issues/78)

[Fonctionnalités](#key-features) · [Démarrage](#get-started) · [Découvrir](#explore-deeptutor) · [TutorBot](#tutorbot) · [CLI](#deeptutor-cli) · [Multi-utilisateur](#multi-user) · [Feuille de route](#roadmap) · [Communauté](#community)

[🇬🇧 English](../../README.md) · [🇨🇳 中文](README_CN.md) · [🇯🇵 日本語](README_JA.md) · [🇪🇸 Español](README_ES.md) · [🇸🇦 العربية](README_AR.md) · [🇷🇺 Русский](README_RU.md) · [🇮🇳 हिन्दी](README_HI.md) · [🇵🇹 Português](README_PT.md) · [🇹🇭 ภาษาไทย](README_TH.md) · 🇵🇱 [Polski](README_PL.md)

</div>

---

> 🤝 **Toute contribution est la bienvenue !** Stratégie de branches, normes de code et prise en main : [CONTRIBUTING](../../CONTRIBUTING.md).

### 📦 Versions

> **[2026.5.9]** [v1.3.9](https://github.com/HKUDS/DeepTutor/releases/tag/v1.3.9) — TutorBot prend en charge Zulip et NVIDIA NIM, routage plus sûr des modèles de raisonnement, `deeptutor start`, infobulles latérales et parité du stockage de sessions.

> **[2026.5.8]** [v1.3.8](https://github.com/HKUDS/DeepTutor/releases/tag/v1.3.8) — Déploiements multi-utilisateurs optionnels avec espaces isolés, droits admin, routes d’authentification et accès runtime limité.

> **[2026.5.4]** [v1.3.7](https://github.com/HKUDS/DeepTutor/releases/tag/v1.3.7) — Correctifs modèles de raisonnement / fournisseurs, historique d’index des connaissances visible, vidage Co-Writer et édition de modèles plus sûrs.

> **[2026.5.3]** [v1.3.6](https://github.com/HKUDS/DeepTutor/releases/tag/v1.3.6) — Sélection de modèles par catalogue (chat et TutorBot), réindexation RAG plus sûre, plafonds de tokens OpenAI Responses, validation de l’éditeur Skills.

> **[2026.5.2]** [v1.3.5](https://github.com/HKUDS/DeepTutor/releases/tag/v1.3.5) — Paramètres de lancement locaux plus fluides, requêtes RAG plus sûres, auth embeddings locale clarifiée, mode sombre des réglages peaufiné.

> **[2026.5.1]** [v1.3.4](https://github.com/HKUDS/DeepTutor/releases/tag/v1.3.4) — Persistance du chat sur les pages livre et flux de reconstruction, références chat→livre, langage/raisonnement renforcés, extraction RAG durcie.

> **[2026.4.30]** [v1.3.3](https://github.com/HKUDS/DeepTutor/releases/tag/v1.3.3) — Embeddings NVIDIA NIM et Gemini, contexte Space unifié, instantanés de session, résilience de réindexation RAG.

> **[2026.4.29]** [v1.3.2](https://github.com/HKUDS/DeepTutor/releases/tag/v1.3.2) — URLs d’embedding visibles, réindexation si vecteurs invalides, nettoyage mémoire pour sortie « thinking », correctif Deep Solve.

> **[2026.4.28]** [v1.3.1](https://github.com/HKUDS/DeepTutor/releases/tag/v1.3.1) — Stabilité : routage RAG et validation embeddings, persistance Docker, saisie compatible IME, robustesse Windows/GBK.

> **[2026.4.27]** [v1.3.0](https://github.com/HKUDS/DeepTutor/releases/tag/v1.3.0) — Index KB versionnés et flux de réindexation, espace connaissances refait, auto-détection d’embeddings, hub Space.

> **[2026.4.25]** [v1.2.5](https://github.com/HKUDS/DeepTutor/releases/tag/v1.2.5) — Pièces jointes persistantes et tiroir d’aperçu, pipelines sensibles aux PJ, export Markdown TutorBot.

> **[2026.4.25]** [v1.2.4](https://github.com/HKUDS/DeepTutor/releases/tag/v1.2.4) — PJ texte/code/SVG, Setup Tour en une commande, export Markdown du chat, UI KB compacte.

<details>
<summary><b>Anciennes versions (plus de 2 semaines)</b></summary>

> **[2026.4.24]** [v1.2.3](https://github.com/HKUDS/DeepTutor/releases/tag/v1.2.3) — PJ documents, blocs de raisonnement, éditeur de modèles Soul, Co-Writer vers carnet.

> **[2026.4.22]** [v1.2.2](https://github.com/HKUDS/DeepTutor/releases/tag/v1.2.2) — Skills utilisateur, perf. saisie chat, démarrage auto TutorBot, UI bibliothèque, plein écran visualisation.

> **[2026.4.21]** [v1.2.1](https://github.com/HKUDS/DeepTutor/releases/tag/v1.2.1) — Plafonds de tokens par étape, régénérer partout, compatibilité RAG & Gemma.

> **[2026.4.20]** [v1.2.0](https://github.com/HKUDS/DeepTutor/releases/tag/v1.2.0) — Compilateur Book Engine « livre vivant », Co-Writer multi-documents, HTML interactif, @ dans la banque de questions.

> **[2026.4.18]** [v1.1.2](https://github.com/HKUDS/DeepTutor/releases/tag/v1.1.2) — Onglet Channels piloté par schéma, pipeline RAG unique, prompts externalisés.

> **[2026.4.17]** [v1.1.1](https://github.com/HKUDS/DeepTutor/releases/tag/v1.1.1) — « Répondre maintenant », sync défilement Co-Writer, panneau réglages unifié, bouton Stop streaming.

> **[2026.4.15]** [v1.1.0](https://github.com/HKUDS/DeepTutor/releases/tag/v1.1.0) — Blocs LaTeX, sonde diagnostic LLM, guide Docker & LLM local.

> **[2026.4.14]** [v1.1.0-beta](https://github.com/HKUDS/DeepTutor/releases/tag/v1.1.0-beta) — Sessions URL, thème Snow, heartbeat WebSocket, registre d’embeddings refondu.

> **[2026.4.13]** [v1.0.3](https://github.com/HKUDS/DeepTutor/releases/tag/v1.0.3) — Carnet de questions avec marque-pages, Mermaid dans Visualize, détection mismatch embeddings, Qwen/vLLM, LM Studio & llama.cpp, thème Glass.

> **[2026.4.11]** [v1.0.2](https://github.com/HKUDS/DeepTutor/releases/tag/v1.0.2) — Recherche unifiée + SearXNG, correctif changement fournisseur, fuites ressources frontend.

> **[2026.4.10]** [v1.0.1](https://github.com/HKUDS/DeepTutor/releases/tag/v1.0.1) — Visualize (Chart.js/SVG), anti-doublons quiz, o4-mini.

> **[2026.4.10]** [v1.0.0-beta.4](https://github.com/HKUDS/DeepTutor/releases/tag/v1.0.0-beta.4) — Progression embeddings avec retry, dépendances multi-plateformes, validation MIME.

> **[2026.4.8]** [v1.0.0-beta.3](https://github.com/HKUDS/DeepTutor/releases/tag/v1.0.0-beta.3) — SDK natifs OpenAI/Anthropic, Math Animator Windows, JSON robuste, i18n chinois complet.

> **[2026.4.7]** [v1.0.0-beta.2](https://github.com/HKUDS/DeepTutor/releases/tag/v1.0.0-beta.2) — Rechargement à chaud des réglages, sortie MinerU imbriquée, correctif WebSocket, Python 3.11+ minimum.

> **[2026.4.4]** [v1.0.0-beta.1](https://github.com/HKUDS/DeepTutor/releases/tag/v1.0.0-beta.1) — Réécriture agent-native (~200k lignes) : plugins Tools/Capabilities, CLI & SDK, TutorBot, Co-Writer, apprentissage guidé, mémoire persistante.

> **[2026.1.23]** [v0.6.0](https://github.com/HKUDS/DeepTutor/releases/tag/v0.6.0) — Persistance de session, upload incrémental, import pipeline RAG flexible, localisation chinoise complète.

> **[2026.1.18]** [v0.5.2](https://github.com/HKUDS/DeepTutor/releases/tag/v0.5.2) — Docling pour RAG-Anything, logs optimisés et correctifs.

> **[2026.1.15]** [v0.5.0](https://github.com/HKUDS/DeepTutor/releases/tag/v0.5.0) — Config unifiée, pipeline RAG par KB, refonte génération de questions, barre latérale personnalisable.

> **[2026.1.9]** [v0.4.0](https://github.com/HKUDS/DeepTutor/releases/tag/v0.4.0) — LLM & embeddings multi-fournisseurs, nouvelle page d’accueil, découplage RAG, refactor des variables d’environnement.

> **[2026.1.5]** [v0.3.0](https://github.com/HKUDS/DeepTutor/releases/tag/v0.3.0) — PromptManager unifié, CI/CD GitHub Actions, images Docker GHCR.

> **[2026.1.2]** [v0.2.0](https://github.com/HKUDS/DeepTutor/releases/tag/v0.2.0) — Déploiement Docker, Next.js 16 & React 19, durcissement WebSocket et correctifs critiques.

</details>

### 📰 Actualités

> **[2026.4.19]** 🎉 20k étoiles en 111 jours — merci !

> **[2026.4.10]** 📄 Article arXiv : [preprint](https://arxiv.org/abs/2604.26962).

> **[2026.4.4]** DeepTutor v1.0.0 sous Apache-2.0 — évolution agent-native.

> **[2026.2.6]** 🚀 10k étoiles en 39 jours.

> **[2026.1.1]** Bonne année — [Discord](https://discord.gg/eRsjPgMU4t), [WeChat](https://github.com/HKUDS/DeepTutor/issues/78), [Discussions](https://github.com/HKUDS/DeepTutor/discussions).

> **[2025.12.29]** DeepTutor est officiellement publié !

<a id="key-features"></a>
## ✨ Fonctionnalités clés

- **Espace de chat unifié** — Six modes, un fil : Chat, Deep Solve, quiz, Deep Research, Math Animator, Visualize partagent le contexte.
- **AI Co-Writer** — Markdown multi-documents ; réécrire, développer ou résumer avec KB et web.
- **Book Engine** — « Livres vivants » avec **13** types de blocs (quiz, cartes mémoire, frises, graphes de concepts, démos…).
- **Knowledge Hub** — PDF, Markdown, texte ; carnets ; banque de questions ; Skills via `SKILL.md`.
- **Mémoire persistante** — Profil partagé avec toutes les fonctions et TutorBots.
- **TutorBots personnels** — Tuteurs autonomes, espaces séparés ; [nanobot](https://github.com/HKUDS/nanobot).
- **CLI agent-native** — Tout en une commande ; Rich pour humains, JSON pour agents ; [`SKILL.md`](../../SKILL.md).
- **Authentification optionnelle** — Désactivée en local ; deux variables pour l’exiger en public. Multi-utilisateur (bcrypt, JWT, inscription, admin). **PocketBase** optionnel (OAuth, concurrence), sidecar sans changer le code.

---

<a id="get-started"></a>
## 🚀 Démarrage

### Prérequis

| Exigence | Version | Vérifier | Notes |
|:---|:---|:---|:---|
| [Git](https://git-scm.com/) | Toute | `git --version` | Cloner |
| [Python](https://www.python.org/downloads/) | 3.11+ | `python --version` | Backend |
| [Node.js](https://nodejs.org/) | 20.9+ | `node --version` | Web local |
| [npm](https://www.npmjs.com/) | Avec Node | `npm --version` | |

> **Windows uniquement :** sans Visual Studio, installez les [Build Tools](https://visualstudio.microsoft.com/visual-cpp-build-tools/) avec la charge **Développement Desktop en C++**.

Au moins une **clé API** LLM. Le Setup Tour guide la saisie.

### Option A — Setup Tour (recommandé)

Assistant CLI pour première installation web : environnement, dépendances Python/Node, `.env`, options TutorBot/Matrix/Math Animator. Commandes identiques au [README anglais](../../README.md) : clone, `venv`/PowerShell/Conda, puis `python scripts/start_tour.py`, puis `python scripts/start_web.py`. Mise à jour : `python scripts/update.py`.

<a id="option-b--manual-local-install"></a>
### Option B — Installation locale manuelle

```bash
python -m pip install -e ".[server]"
cd web && npm install && cd ..
cp .env.example .env
```

Extras : `.[tutorbot]`, `.[tutorbot,matrix]`, `.[math-animator]`, `.[all]`. Node **20.9+**.

Exemple `.env` (LLM requis ; embeddings pour les KB) — voir [README anglais](../../README.md) pour les tableaux complets des fournisseurs.

Démarrage : `python scripts/start_web.py` ou `python -m deeptutor.api.run_server` + `cd web && npm run dev -- -p 3782`. Ports **8001** / **3782**.

### Option C — Docker

`docker compose -f docker-compose.ghcr.yml up -d` ou `docker compose up -d`. Variable distante `NEXT_PUBLIC_API_BASE_EXTERNAL`. Détails auth/PocketBase identiques à la version anglaise ; multi-tenant : [Multi-utilisateur](#multi-user).

### Option D — CLI seule

`python -m pip install -e ".[cli]"` — voir [CLI](#deeptutor-cli).

---

<a id="explore-deeptutor"></a>
## 📖 Découvrir DeepTutor

<img src="../../assets/figs/deeptutor-architecture.png" alt="Architecture" width="800">

### 💬 Chat — six modes, contexte unifié

<img src="../../assets/figs/dt-chat.png" alt="Chat" width="800">

### ✍️ Co-Writer · 📖 Book Engine · 📚 Connaissances · 🧠 Mémoire

<img src="../../assets/figs/dt-cowriter.png" alt="Co-Writer" width="800">

<img src="../../assets/figs/dt-book-0.png" width="270"><img src="../../assets/figs/dt-book-1.png" width="270"><img src="../../assets/figs/dt-book-2.png" width="270">

<img src="../../assets/figs/dt-knowledge.png" alt="Knowledge" width="800">

<img src="../../assets/figs/dt-memory.png" alt="Memory" width="800">

**13** types de blocs pour les livres. Bases Office/PDF/Markdown/code ; carnets ; banque avec @ ; Skills. Mémoire : résumé et profil.

---

<a id="tutorbot"></a>
### 🦞 TutorBot

<img src="../../assets/figs/tutorbot-architecture.png" alt="TutorBot" width="800">

<img src="../../assets/figs/tb.png" alt="TutorBot" width="800">

Agent persistant multi-instance ([nanobot](https://github.com/HKUDS/nanobot)) : Soul, espace dédié, Heartbeat, outils complets, skills, multicanal, sous-agents.

```bash
deeptutor bot create math-tutor --persona "Socratic math teacher who uses probing questions"
deeptutor bot list
```

---

<a id="deeptutor-cli"></a>
### ⌨️ CLI DeepTutor

<img src="../../assets/figs/cli-architecture.png" alt="CLI" width="800">

Référence complète des sous-commandes : [README anglais](../../README.md).

---

<a id="multi-user"></a>
### 👥 Multi-utilisateur — espaces séparés par utilisateur

<img src="../../assets/figs/dt-multi-user.png" alt="Multi-user" width="800">

Activez l’auth pour un déploiement multi-locataire : premier inscrit = admin ; comptes suivants sur invitation. Ressources (LLM, KB, skills) attribuées par l’admin.

```bash
echo 'AUTH_ENABLED=true' >> .env
echo 'AUTH_SECRET=<64+ caractères aléatoires>' >> .env
python scripts/start_web.py
# http://localhost:3782/register puis /admin/users
```

Admin : `/settings` complet, gestion utilisateurs, grants (IDs logiques uniquement), audit `multi-user/_system/audit/usage.jsonl`. Utilisateur : arborescence `multi-user/<uid>/`, ressources assignées en lecture seule, réglages sans secrets, modèle imposé sans repli silencieux.

> ⚠️ **PocketBase** (`POCKETBASE_URL`) : **mono-utilisateur** pour l’instant — pas de champ `role`, pas de filtre `user_id`. Multi-utilisateur : laissez `POCKETBASE_URL` vide.

> ⚠️ **Processus unique recommandé** pour la promotion du premier admin ; plusieurs workers : provisionnement hors ligne ou stockage externe.

<a id="roadmap"></a>
## 🗺️ Feuille de route

| Statut | Jalons |
|:---:|:---|
| 🎯 | Authentification & connexion multi-utilisateur |
| 🎯 | Thèmes & apparence |
| 🎯 | Amélioration des interactions |
| 🔜 | Meilleures mémoires |
| 🔜 | [LightRAG](https://github.com/HKUDS/LightRAG) |
| 🔜 | Site de documentation |

> Une étoile sur [GitHub](https://github.com/HKUDS/DeepTutor/stargazers) aide beaucoup.

---

<a id="community"></a>
## 🌐 Communauté & écosystème

| Projet | Rôle |
|:---|:---|
| [**nanobot**](https://github.com/HKUDS/nanobot) | Moteur TutorBot |
| [**LlamaIndex**](https://github.com/run-llama/llama_index) | RAG |
| [**ManimCat**](https://github.com/Wing900/ManimCat) | Math Animator |

HKUDS : [LightRAG](https://github.com/HKUDS/LightRAG) · [AutoAgent](https://github.com/HKUDS/AutoAgent) · [AI-Researcher](https://github.com/HKUDS/AI-Researcher) · [nanobot](https://github.com/HKUDS/nanobot)

## 🤝 Contribuer

<div align="center">

Nous espérons que DeepTutor soit un cadeau pour la communauté. 🎁

<a href="https://github.com/HKUDS/DeepTutor/graphs/contributors">
  <img src="https://contrib.rocks/image?repo=HKUDS/DeepTutor&max=999" alt="Contributors" />
</a>

</div>

[CONTRIBUTING.md](../../CONTRIBUTING.md)

## ⭐ Star History

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

[⭐ Star](https://github.com/HKUDS/DeepTutor/stargazers) · [🐛 Issues](https://github.com/HKUDS/DeepTutor/issues) · [💬 Discussions](https://github.com/HKUDS/DeepTutor/discussions)

---

[Licence Apache 2.0](../../LICENSE)

<p>
  <img src="https://visitor-badge.laobi.icu/badge?page_id=HKUDS.DeepTutor&style=for-the-badge&color=00d4ff" alt="Views">
</p>

</div>
