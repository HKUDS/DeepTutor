<div align="center">

<img src="../../assets/logo-ver2.png" alt="DeepTutor Logo" width="150" style="border-radius: 15px;">

# DeepTutor: Votre Assistant d'Apprentissage Personnel

[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?style=flat-square&logo=python&logoColor=white)](https://www.python.org/downloads/)
[![Next.js](https://img.shields.io/badge/Next.js-14-000000?style=flat-square&logo=next.js&logoColor=white)](https://nextjs.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-009688?style=flat-square&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![License](https://img.shields.io/badge/License-AGPL--3.0-blue?style=flat-square)](LICENSE)
[![Feishu](https://img.shields.io/badge/Feishu-Group-blue?style=flat)](./Communication.md)
[![WeChat](https://img.shields.io/badge/WeChat-Group-green?style=flat&logo=wechat)](./Communication.md)



[**Démarrage Rapide**](#démarrage-rapide) · [**Modules Principaux**](#modules-principaux) · [**FAQ**](#faq)

[🇬🇧 English](../../README.md) · [🇨🇳 中文](README_CN.md) · [🇯🇵 日本語](README_JA.md) · [🇪🇸 Español](README_ES.md) · [🇸🇦 العربية](README_AR.md) · [🇷🇺 Русский](README_RU.md) · [🇮🇳 हिन्दी](README_HI.md) · [🇵🇹 Português](README_PT.md)

</div>

<div align="center">

| ⚡ **Q&A de Connaissance de Documents Massifs**  |  📈 **Visualisation d'Apprentissage Interactive**  | <br>
| 🧠 **Renforcement des Connaissances**  |  🔬 **Recherche Approfondie et Génération d'Idées** |

</div>

---
> **[2026.1.1]** Bonne Année ! Rejoignez nos [GitHub Discussions](https://github.com/HKUDS/DeepTutor/discussions) — façonnez l'avenir de DeepTutor ! 💬

> **[2025.12.30]** Visitez notre [Site Web Officiel](https://hkuds.github.io/DeepTutor/) pour plus de détails !

> **[2025.12.29]** DeepTutor v0.1 est maintenant disponible ! ✨
---

## Caractéristiques Clés d'DeepTutor

### 📚 Q&A de Connaissance de Documents Massifs
• **Base de Connaissances Intelligente** : Téléchargez des manuels, des articles de recherche, des manuels techniques et des documents spécifiques au domaine. Construisez un référentiel de connaissances complet alimenté par l'IA pour un accès instantané.<br>
• **Résolution de Problèmes Multi-Agents** : Architecture de raisonnement à double boucle avec RAG, recherche web, recherche d'articles et exécution de code—fournissant des solutions étape par étape avec des citations précises.

### 🎨 Visualisation d'Apprentissage Interactive
• **Simplification et Explications des Connaissances** : Transformez des concepts complexes, des connaissances et des algorithmes en aides visuelles faciles à comprendre, des décompositions détaillées étape par étape et des démonstrations interactives engageantes.<br>
• **Q&R Personnalisé** : Conversations conscientes du contexte qui s'adaptent à votre progression d'apprentissage, avec des pages interactives et un suivi des connaissances basé sur les sessions.

### 🎯 Renforcement des Connaissances avec Générateur de Problèmes de Pratique
• **Création d'Exercices Intelligents** : Générez des quiz ciblés, des problèmes de pratique et des évaluations personnalisées adaptées à votre niveau actuel de connaissances et à vos objectifs d'apprentissage spécifiques.<br>
• **Simulation d'Examen Authentique** : Téléchargez des examens de référence pour générer des questions de pratique qui correspondent parfaitement au style, au format et à la difficulté originaux—vous donnant une préparation réaliste pour le test réel.

### 🔍 Recherche Approfondie et Génération d'Idées
• **Recherche Complète et Revue de Littérature** : Menez une exploration approfondie de sujets avec une analyse systématique. Identifiez les modèles, connectez des concepts connexes entre les disciplines et synthétisez les résultats de recherche existants.<br>
• **Découverte d'Insights Novateurs** : Générez des matériaux d'apprentissage structurés et découvrez les lacunes de connaissances. Identifiez de nouvelles directions de recherche prometteuses grâce à une synthèse intelligente des connaissances inter-domaines.

---

<div align="center">
  <img src="../../assets/figs/title_gradient.svg" alt="All-in-One Tutoring System" width="70%">
</div>

<br>

<!-- ━━━━━━━━━━━━━━━━ Core Learning Experience ━━━━━━━━━━━━━━━━ -->

<table>
<tr>
<td width="50%" align="center" valign="top">

<h3>📚 Q&A de Connaissance de Documents Massifs</h3>
<a href="#problem-solving-agent">
<img src="../../assets/gifs/solve.gif" width="100%">
</a>
<br>
<sub>Résolution de Problèmes Multi-Agents avec Citations Exactes</sub>

</td>
<td width="50%" align="center" valign="top">

<h3>🎨 Visualisation d'Apprentissage Interactive</h3>
<a href="#guided-learning">
<img src="../../assets/gifs/guided-learning.gif" width="100%">
</a>
<br>
<sub>Explications Visuelles Étape par Étape avec Q&R Personnalisé</sub>

</td>
</tr>
</table>

<!-- ━━━━━━━━━━━━━━━━ Practice & Reinforcement ━━━━━━━━━━━━━━━━ -->

<h3 align="center">🎯 Renforcement des Connaissances</h3>

<table>
<tr>
<td width="50%" valign="top" align="center">

<a href="#question-generator">
<img src="../../assets/gifs/question-1.gif" width="100%">
</a>

**Questions Personnalisées**  
<sub>Génération de Questions de Pratique Auto-Validées</sub>

</td>
<td width="50%" valign="top" align="center">

<a href="#question-generator">
<img src="../../assets/gifs/question-2.gif" width="100%">
</a>

**Questions Mimétiques**  
<sub>Cloner le Style d'Examen pour une Pratique Authentique</sub>

</td>
</tr>
</table>

<!-- ━━━━━━━━━━━━━━━━ Research & Creation ━━━━━━━━━━━━━━━━ -->

<h3 align="center">🔍 Recherche Approfondie et Génération d'Idées</h3>

<table>
<tr>
<td width="33%" align="center">

<a href="#deep-research">
<img src="../../assets/gifs/deepresearch.gif" width="100%">
</a>

**Recherche Approfondie**  
<sub>Extension des Connaissances depuis le Manuel avec RAG, Web et Recherche d'Articles</sub>

</td>
<td width="33%" align="center">

<a href="#idea-generation">
<img src="../../assets/gifs/ideagen.gif" width="100%">
</a>

**IdeaGen Automatisé**  
<sub>Remue-Méninges Systématique et Synthèse de Concepts avec Flux de Travail à Double Filtre</sub>

</td>
<td width="33%" align="center">

<a href="#co-writer">
<img src="../../assets/gifs/co-writer.gif" width="100%">
</a>

**IdeaGen Interactif**  
<sub>Co-Writer Alimenté par RAG et Recherche Web avec Génération de Podcasts</sub>

</td>
</tr>
</table>

<!-- ━━━━━━━━━━━━━━━━ Knowledge Infrastructure ━━━━━━━━━━━━━━━━ -->

<h3 align="center">🏗️ Système de Connaissances Tout-en-Un</h3>

<table>
<tr>
<td width="50%" align="center">

<a href="#dashboard--knowledge-base-management">
<img src="../../assets/gifs/knowledge_bases.png" width="100%">
</a>

**Base de Connaissances Personnelle**  
<sub>Construisez et Organisez Votre Propre Référentiel de Connaissances</sub>

</td>
<td width="50%" align="center">

<a href="#notebook">
<img src="../../assets/gifs/notebooks.png" width="100%">
</a>

**Carnet Personnel**  
<sub>Votre Mémoire Contextuelle pour les Sessions d'Apprentissage</sub>

</td>
</tr>
</table>

<p align="center">
  <sub>🌙 Utilisez DeepTutor en <b>Mode Sombre</b> !</sub>
</p>

<details>
<summary><b>Architecture du Système</b></summary>
<br>

![DeepTutor Full-Stack Workflow](../../assets/figs/full-pipe.png)

</details>

## 📋 À Faire

> Suivez-nous pour nos futures mises à jour!
- [ ] Support des services LLM locaux (ex. ollama)
- [ ] Refactorisation du module RAG (voir [Discussions](https://github.com/HKUDS/DeepTutor/discussions))
- [ ] Codage profond à partir de la génération d'idées
- [ ] Interaction personnalisée avec le carnet

## 🚀 Démarrage Rapide

### Étape 1: Cloner et Créer un Environnement Virtuel

```bash
# Cloner le référentiel
git clone https://github.com/HKUDS/DeepTutor.git
cd DeepTutor

# Créer un environnement virtuel (choisir une méthode)

# Option A: Utiliser conda (Recommandé)
conda create -n deeptutor python=3.10
conda activate deeptutor

# Option B: Utiliser venv
python -m venv venv
# Sur Windows:
venv\Scripts\activate
# Sur macOS/Linux:
source venv/bin/activate
```

### Étape 2: Installer les Dépendances

Exécutez le script d'installation en un clic pour installer automatiquement toutes les dépendances:

```bash
# Recommandé: Utiliser le script bash
bash scripts/install_all.sh

# Alternatif: Utiliser le script Python
python scripts/install_all.py

# Remarque: L'installeur détecte conda/venv pour l'isolation. Si aucun environnement isolé n'est détecté, il affichera un avertissement mais continuera l'installation.

# Ou installer manuellement
pip install -r requirements.txt
npm install
```

### Étape 3: Configurer les Variables d'Environnement

Créez un fichier `.env` dans le répertoire racine du projet basé sur `.env.example`:

```bash
# Copier du modèle .env.example (s'il existe)
cp .env.example .env

# Puis éditer le fichier .env avec vos clés API:
```

### Étape 4: Configurer les Ports *(Optionnel)*

Par défaut, l'application utilise:
- **Backend (FastAPI)**: `8001`
- **Frontend (Next.js)**: `3782`

Vous pouvez modifier ces ports dans `config/main.yaml` en éditant les valeurs `server.backend_port` et `server.frontend_port`.

### Étape 5: Utiliser nos Démos *(Optionnel)*

Pour expérimenter rapidement notre système, nous fournissons deux bases de connaissances prétraitées ainsi qu'une collection de questions difficiles et d'exemples d'utilisation.

<details>
<summary><b>Collection d'Articles de Recherche</b> — 5 articles (20-50 pages chacun)</summary>

Une collection sélectionnée de 5 articles de recherche dans les domaines RAG et Agent de notre laboratoire. Cette démo représente des scénarios avec **couverture de connaissances large** pour les objectifs de recherche.

**Articles Utilisés**: [AI-Researcher](https://github.com/HKUDS/AI-Researcher) | [AutoAgent](https://github.com/HKUDS/AutoAgent) | [RAG-Anything](https://github.com/HKUDS/RAG-Anything) | [LightRAG](https://github.com/HKUDS/LightRAG) | [VideoRAG](https://github.com/HKUDS/VideoRAG)

</details>

<details>
<summary><b>Manuel de Science des Données</b> — 8 chapitres, 296 pages</summary>

Un manuel de science des données complet et difficile. Cette démo représente des scénarios avec **profondeur de connaissances profonde** pour les objectifs d'apprentissage.

**Lien du Livre**: [Deep Representation Learning Book](https://ma-lab-berkeley.github.io/deep-representation-learning-book/)
</details>

<br>

**Télécharger et Configurer:**

1. Téléchargez le package de démonstration depuis: [Google Drive](https://drive.google.com/drive/folders/1iWwfZXiTuQKQqUYb5fGDZjLCeTUP6DA6?usp=sharing)
2. Extrayez les fichiers compressés directement dans le répertoire `data/`
3. Les bases de connaissances seront automatiquement disponibles dans le système après le démarrage du projet

> **Remarque:** Nous utilisons `text-embedding-3-large` comme modèle d'intégration lors de l'initialisation de nos bases de connaissances, avec `dimensions = 3072`. Assurez-vous que les dimensions de votre modèle d'intégration sont également 3072.

### Étape 6: Démarrer l'Application

```bash
# Assurez-vous que l'environnement virtuel est activé
conda activate deeptutor  # ou: source venv/bin/activate

# Démarrer l'interface web (frontend + backend)
python scripts/start_web.py

# Ou démarrer seulement l'interface CLI
python scripts/start.py

# Pour arrêter le service, appuyez sur Ctrl+C
```

### Étape 7: Créer Votre Propre Base de Connaissances

Après le démarrage de l'application, vous pouvez créer votre propre base de connaissances via l'interface web, sous n'importe quelle modalité.

1. **Accéder à la Page de Base de Connaissances**: Visitez http://localhost:{frontend_port}/knowledge
2. **Créer une Nouvelle Base de Connaissances**: Cliquez sur le bouton "New Knowledge Base"
3. **Nommer Votre Base de Connaissances**: Entrez un nom unique pour votre base de connaissances
4. **Télécharger les Fichiers**: Téléchargez un ou plusieurs fichiers
5. **Attendre le Traitement**: Le système traitera automatiquement vos fichiers en arrière-plan
   - Surveillez la progression de la création dans le terminal où `start_web.py` est en cours d'exécution
   - La base de connaissances sera disponible une fois le traitement terminé

> **Conseils:** Les gros fichiers peuvent prendre plusieurs minutes à traiter. Vous pouvez télécharger plusieurs fichiers à la fois pour traitement par lots.

### URLs d'Accès

| Service | URL | Description |
|:---:|:---|:---|
| **Frontend** | http://localhost:{frontend_port} | Interface web principale |
| **Documentation API** | http://localhost:{backend_port}/docs | Documentation API interactive |
| **Santé** | http://localhost:{backend_port}/api/v1/knowledge/health | Vérification de la santé du système |

---

## 📂 Stockage des Données

Tout le contenu généré par l'utilisateur et les données du système sont stockés dans le dossier `data/`:

```
data/
├── knowledge_bases/              # Stockage de la base de connaissances
└── user/                         # Données d'activité de l'utilisateur
    ├── solve/                    # Résultats de résolution de problèmes et artefacts
    ├── question/                 # Questions générées
    ├── research/                 # Rapports de recherche et cache
    ├── co-writer/                # Documents Co-Writer et fichiers audio
    ├── notebook/                 # Enregistrements de carnet et métadonnées
    ├── guide/                    # Sessions d'apprentissage guidé
    ├── logs/                     # Journaux système
    └── run_code_workspace/       # Espace de travail d'exécution de code
```

Tous les résultats sont automatiquement enregistrés lorsque vous effectuez n'importe quelle activité. Les dossiers sont créés automatiquement s'ils n'existent pas.

---

## 📖 Documentation des Modules

<table>
<tr>
<td align="center"><a href="../../config/README.md">Configuration</a></td>
<td align="center"><a href="../../data/README.md">Répertoire de Données</a></td>
<td align="center"><a href="../../src/api/README.md">Backend API</a></td>
<td align="center"><a href="../../src/core/README.md">Utilitaires Principaux</a></td>
</tr>
<tr>
<td align="center"><a href="../../src/knowledge/README.md">Base de Connaissances</a></td>
<td align="center"><a href="../../src/tools/README.md">Outils</a></td>
<td align="center"><a href="../../web/README.md">Frontend Web</a></td>
<td align="center"><a href="../../src/agents/solve/README.md">Module de Résolution</a></td>
</tr>
<tr>
<td align="center"><a href="../../src/agents/question/README.md">Module de Question</a></td>
<td align="center"><a href="../../src/agents/research/README.md">Module de Recherche</a></td>
<td align="center"><a href="../../src/agents/co_writer/README.md">Module Co-Writer</a></td>
<td align="center"><a href="../../src/agents/guide/README.md">Module de Guide</a></td>
</tr>
<tr>
<td align="center" colspan="4"><a href="../../src/agents/ideagen/README.md">Module de Génération d'Idées</a></td>
</tr>
</table>

---

## ❓ FAQ

<details>
<summary><b>Le backend ne démarre pas?</b></summary>

**Liste de Vérification**
- Confirmez que la version Python >= 3.10
- Confirmez que toutes les dépendances sont installées: `pip install -r requirements.txt`
- Vérifiez si le port 8001 est utilisé (configurable dans `config/main.yaml`)
- Vérifiez la configuration du fichier `.env`

**Solutions**
- **Changer le port**: Modifiez `config/main.yaml` server.backend_port
- **Vérifier les journaux**: Vérifiez les messages d'erreur du terminal

</details>

<details>
<summary><b>Port occupé après Ctrl+C?</b></summary>

**Problème**

Après avoir appuyé sur Ctrl+C pendant une tâche en cours (par exemple, recherche profonde), le redémarrage affiche une erreur "port déjà en utilisation".

**Cause**

Ctrl+C ne termine parfois que le processus frontend tandis que le backend continue de s'exécuter en arrière-plan.

**Solution**

```bash
# macOS/Linux: Trouver et tuer le processus
lsof -i :8001
kill -9 <PID>

# Windows: Trouver et tuer le processus
netstat -ano | findstr :8001
taskkill /PID <PID> /F
```

Puis redémarrez le service avec `python scripts/start_web.py`.

</details>

<details>
<summary><b>Erreur "npm: command not found"?</b></summary>

**Problème**

L'exécution de `scripts/start_web.py` affiche `npm: command not found` ou le code de sortie 127.

**Liste de Vérification**
- Vérifiez si npm est installé: `npm --version`
- Vérifiez si Node.js est installé: `node --version`
- Confirmez que l'environnement conda est activé (si vous utilisez conda)

**Solutions**
```bash
# Option A: Utiliser Conda (Recommandé)
conda install -c conda-forge nodejs

# Option B: Utiliser l'installateur officiel
# Télécharger depuis https://nodejs.org/

# Option C: Utiliser nvm
nvm install 18
nvm use 18
```

**Vérifier l'Installation**
```bash
node --version  # Devrait afficher v18.x.x ou supérieur
npm --version   # Devrait afficher le numéro de version
```

</details>

<details>
<summary><b>Le frontend ne peut pas se connecter au backend?</b></summary>

**Liste de Vérification**
- Confirmez que le backend est en cours d'exécution (visitez http://localhost:8001/docs)
- Vérifiez la console du navigateur pour les messages d'erreur

**Solution**

Créez `.env.local` dans le répertoire `web`:

```bash
NEXT_PUBLIC_API_BASE=http://localhost:8001
```

</details>

<details>
<summary><b>Échec de la connexion WebSocket?</b></summary>

**Liste de Vérification**
- Confirmez que le backend est en cours d'exécution
- Vérifiez les paramètres du pare-feu
- Confirmez que l'URL WebSocket est correcte

**Solution**
- **Vérifiez les journaux du backend**
- **Confirmez le format de l'URL**: `ws://localhost:8001/api/v1/...`

</details>

<details>
<summary><b>Où les sorties du module sont-elles stockées?</b></summary>

| Module | Chemin de Sortie |
|:---:|:---|
| Résoudre | `data/user/solve/solve_YYYYMMDD_HHMMSS/` |
| Question | `data/user/question/question_YYYYMMDD_HHMMSS/` |
| Recherche | `data/user/research/reports/` |
| Co-Writer | `data/user/co-writer/` |
| Carnet | `data/user/notebook/` |
| Guide | `data/user/guide/session_{session_id}.json` |
| Journaux | `data/user/logs/` |

</details>

<details>
<summary><b>Comment ajouter une nouvelle base de connaissances?</b></summary>

**Interface Web**
1. Visitez http://localhost:{frontend_port}/knowledge
2. Cliquez sur "New Knowledge Base"
3. Entrez le nom de la base de connaissances
4. Téléchargez des documents PDF/TXT/MD
5. Le système traitera les documents en arrière-plan

**CLI**
```bash
python -m src.knowledge.start_kb init <kb_name> --docs <pdf_path>
```

</details>

<details>
<summary><b>Comment ajouter des documents de manière incrémentale à une BC existante?</b></summary>

**CLI (Recommandé)**
```bash
python -m src.knowledge.add_documents <kb_name> --docs <new_document.pdf>
```

**Avantages**
- Traite uniquement les nouveaux documents, économise le temps et le coût de l'API
- Fusion automatique avec le graphique de connaissances existant
- Préserve toutes les données existantes

</details>

<details>
<summary><b>Erreur uvloop.Loop lors de l'extraction d'éléments numérotés?</b></summary>

**Problème**

Lors de l'initialisation d'une base de connaissances, vous pouvez rencontrer cette erreur:
```
ValueError: Can't patch loop of type <class 'uvloop.Loop'>
```

Ceci se produit car Uvicorn utilise la boucle d'événements `uvloop` par défaut, qui est incompatible avec `nest_asyncio`.

**Solution**

Utilisez l'une des méthodes suivantes pour extraire les éléments numérotés:

```bash
# Option 1: Utiliser le script shell (recommandé)
./scripts/extract_numbered_items.sh <kb_name>

# Option 2: Commande Python directe
python src/knowledge/extract_numbered_items.py --kb <kb_name> --base-dir ./data/knowledge_bases
```

Ceci extraira les éléments numérotés (Définitions, Théorèmes, Équations, etc.) de votre base de connaissances sans la réinitialiser.

</details>

<br>

---

## 📄 Licence

Ce projet est sous licence **[AGPL-3.0](LICENSE)**.


## ⭐ Historique des Stars

<div align="center">
<a href="https://star-history.com/#HKUDS/DeepTutor&Date">
 <picture>
   <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/svg?repos=HKUDS/DeepTutor&type=Date&theme=dark" />
   <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/svg?repos=HKUDS/DeepTutor&type=Date" />
   <img alt="Star History Chart" src="https://api.star-history.com/svg?repos=HKUDS/DeepTutor&type=Date" />
 </picture>
</a>
</div>


## 🤝 Contribution

Nous accueillons les contributions de la communauté! Pour assurer la qualité et la cohérence du code, veuillez suivre les directives ci-dessous.

<details>
<summary><b>Configuration de Développement</b></summary>

### Configuration des Pre-commit Hooks

Ce projet utilise **pre-commit hooks** pour formater automatiquement le code et vérifier les problèmes avant de valider.

**Étape 1: Installer pre-commit**
```bash
# Utiliser pip
pip install pre-commit

# Ou utiliser conda
conda install -c conda-forge pre-commit
```

**Étape 2: Installer les crochets Git**
```bash
cd DeepTutor
pre-commit install
```

**Étape 3: (Optionnel) Exécuter des vérifications sur tous les fichiers**
```bash
pre-commit run --all-files
```

Chaque fois que vous exécutez `git commit`, pre-commit hooks exécutera automatiquement:
- Formater le code Python avec Ruff
- Formater le code frontend avec Prettier
- Vérifier les erreurs de syntaxe
- Valider les fichiers YAML/JSON
- Détecter les problèmes de sécurité potentiels

### Outils de Qualité de Code

| Outil | Objectif | Configuration |
|:---:|:---|:---:|
| **Ruff** | Vérification et formatage du code Python | `pyproject.toml` |
| **Prettier** | Formatage du code frontend | `web/.prettierrc.json` |
| **detect-secrets** | Vérification de sécurité | `.secrets.baseline` |

> **Remarque**: Le projet utilise **Ruff format** au lieu de Black pour éviter les conflits de formatage.

### Commandes Courantes

```bash
# Commit normal (les hooks s'exécutent automatiquement)
git commit -m "Votre message de commit"

# Vérifier manuellement tous les fichiers
pre-commit run --all-files

# Mettre à jour les hooks vers les dernières versions
pre-commit autoupdate

# Ignorer les hooks (non recommandé, seulement pour les urgences)
git commit --no-verify -m "Correction d'urgence"
```

</details>

### Directives de Contribution

1. **Fork et Clone**: Fork le référentiel et clonez-le
2. **Créer une Branche**: Créer une branche de fonction à partir de `main`
3. **Installer Pre-commit**: Suivre les étapes de configuration ci-dessus
4. **Apporter des Modifications**: Écrire du code suivant le style du projet
5. **Tester**: Assurez-vous que vos modifications fonctionnent correctement
6. **Commit**: Pre-commit hooks formatera automatiquement votre code
7. **Pousser et PR**: Pousser vers votre fork et créer une Pull Request

### Signaler les Problèmes

- Utiliser GitHub Issues pour signaler des bogues ou suggérer des fonctionnalités
- Fournir des informations détaillées sur le problème
- Si c'est un bogue, inclure les étapes pour le reproduire

<div align="center">
<br>
❤️ Nous remercions tous nos contributeurs pour leurs précieuses contributions.

</div>

## 🔗 Projets Connexes

<div align="center">

| [⚡ LightRAG](https://github.com/HKUDS/LightRAG) | [🎨 RAG-Anything](https://github.com/HKUDS/RAG-Anything) | [💻 DeepCode](https://github.com/HKUDS/DeepCode) | [🔬 AI-Researcher](https://github.com/HKUDS/AI-Researcher) |
|:---:|:---:|:---:|:---:|
| RAG Simple et Rapide | RAG Multimodal | Assistant de Code IA | Automatisation de la Recherche |

**[Laboratoire d'Intelligence des Données @ HKU](https://github.com/HKUDS)**

[⭐ Suivez-nous](https://github.com/HKUDS/DeepTutor/stargazers) · [🐛 Signaler un bogue](https://github.com/HKUDS/DeepTutor/issues) · [💬 Discussions](https://github.com/HKUDS/DeepTutor/discussions)

---
*✨ Merci de visiter **DeepTutor**!*

<img src="https://visitor-badge.laobi.icu/badge?page_id=HKUDS.DeepTutor&style=for-the-badge&color=00d4ff" alt="Views">

</div>
