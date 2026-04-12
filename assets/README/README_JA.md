<div align="center">

<img src="../../assets/logo-ver2.png" alt="DeepTutor" width="140" style="border-radius: 15px;">

# DeepTutor: エージェント型パーソナライズドチュータリングへ

[![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-3776AB?style=flat-square&logo=python&logoColor=white)](https://www.python.org/downloads/)
[![Next.js 16](https://img.shields.io/badge/Next.js-16-000000?style=flat-square&logo=next.js&logoColor=white)](https://nextjs.org/)
[![License](https://img.shields.io/badge/License-Apache_2.0-blue?style=flat-square)](../../LICENSE)
[![GitHub release](https://img.shields.io/github/v/release/HKUDS/DeepTutor?style=flat-square&color=brightgreen)](https://github.com/HKUDS/DeepTutor/releases)
[![GitHub last commit](https://img.shields.io/github/last-commit/HKUDS/DeepTutor?style=flat-square)](https://github.com/HKUDS/DeepTutor/commits)

[![Discord](https://img.shields.io/badge/Discord-Community-5865F2?style=flat-square&logo=discord&logoColor=white)](https://discord.gg/eRsjPgMU4t)
[![Feishu](https://img.shields.io/badge/Feishu-Group-00D4AA?style=flat-square&logo=feishu&logoColor=white)](../../Communication.md)
[![WeChat](https://img.shields.io/badge/WeChat-Group-07C160?style=flat-square&logo=wechat&logoColor=white)](https://github.com/HKUDS/DeepTutor/issues/78)

[主な機能](#key-features) · [はじめる](#get-started) · [DeepTutor を探る](#explore-deeptutor) · [TutorBot](#tutorbot) · [CLI](#deeptutor-cli-guide) · [コミュニティ](#community)

[🇬🇧 English](../../README.md) · [🇨🇳 中文](README_CN.md) · [🇪🇸 Español](README_ES.md) · [🇫🇷 Français](README_FR.md) · [🇸🇦 العربية](README_AR.md) · [🇷🇺 Русский](README_RU.md) · [🇮🇳 हिन्दी](README_HI.md) · [🇵🇹 Português](README_PT.md)

</div>

---
### 📰 ニュース

> **[2026.3.24]** お待たせしました！✨ DeepTutor v1.0.0 を Apache-2.0 で公開 — 軽量リファクタ、TutorBot、柔軟なモード切替を備えたエージェントネイティブな進化です。

> **[2026.2.6]** 🚀 わずか 39 日で 10k スターに到達。コミュニティに感謝します！

> **[2026.1.1]** 新年あけましておめでとうございます。[Discord](https://discord.gg/eRsjPgMU4t)、[WeChat](https://github.com/HKUDS/DeepTutor/issues/78)、[Discussions](https://github.com/HKUDS/DeepTutor/discussions) で一緒に未来を作りましょう。

> **[2025.12.29]** DeepTutor を正式リリースしました。

### 📦 リリース

> **[2026.3.24]** [v1.0.0](https://github.com/HKUDS/DeepTutor/releases/tag/v1.0.0) — エージェントネイティブな再設計、柔軟なツール統合、CLI と SDK の入口、nanobot 駆動の TutorBot、Co-Writer、ガイド付き学習、永続メモリ。より軽く、速く、使いやすく。

<details>
<summary><b>過去のリリース</b></summary>

> **[2026.1.23]** [v0.6.0](https://github.com/HKUDS/DeepTutor/releases/tag/v0.6.0) — セッション永続化、増分アップロード、柔軟な RAG パイプライン、中国語ローカライズ。

> **[2026.1.18]** [v0.5.2](https://github.com/HKUDS/DeepTutor/releases/tag/v0.5.2) — Docling 対応、ログ改善、バグ修正。

> **[2026.1.15]** [v0.5.0](https://github.com/HKUDS/DeepTutor/releases/tag/v0.5.0) — 統一サービス設定、KB ごとの RAG 選択、問題生成刷新、サイドバー。

> **[2026.1.9]** [v0.4.0](https://github.com/HKUDS/DeepTutor/releases/tag/v0.4.0) — マルチプロバイダ LLM/埋め込み、新ホーム、RAG 分離、環境変数整理。

> **[2026.1.5]** [v0.3.0](https://github.com/HKUDS/DeepTutor/releases/tag/v0.3.0) — PromptManager、CI/CD、GHCR イメージ。

> **[2026.1.2]** [v0.2.0](https://github.com/HKUDS/DeepTutor/releases/tag/v0.2.0) — Docker、Next.js 16 / React 19、WebSocket 強化、脆弱性修正。

</details>

<a id="key-features"></a>
## ✨ 主な機能

- **統一チャットワークスペース** — 5 モードを 1 スレッドで。チャット、Deep Solve、クイズ、Deep Research、Math Animator が同じ文脈を共有。
- **パーソナル TutorBot** — チャットボットではなく自律チューター。独立ワークスペース、記憶、人格、スキル。[nanobot](https://github.com/HKUDS/nanobot) 搭載。
- **AI Co-Writer** — Markdown で AI が第一級の共同編集者。書き換え・拡張・要約、KB と Web を参照。
- **ガイド付き学習** — 資料を段階的・視覚的な学習ジャーニーへ。
- **ナレッジハブ** — PDF / MD / テキストで RAG 対応 KB、カラー付きノートブックで整理。
- **永続メモリ** — 学習の要約と学習者プロファイル。全機能と TutorBot で共有。
- **エージェントネイティブ CLI** — 能力・KB・セッション・TutorBot をコマンド一つで。Rich と JSON。ルートの [`SKILL.md`](../../SKILL.md) をエージェントに渡せば自律操作。

---

<a id="get-started"></a>
## 🚀 はじめる

### オプション A — セットアップツアー（推奨）

**対話型スクリプト**が依存関係、環境、接続テスト、起動まで案内。手動 `.env` 編集は不要。

```bash
git clone https://github.com/HKUDS/DeepTutor.git
cd DeepTutor

conda create -n deeptutor python=3.11 && conda activate deeptutor
# または: python -m venv .venv && source .venv/bin/activate

python scripts/start_tour.py
```

- **Web モード**（推奨）— プロファイル選択、pip + npm インストール、一時サーバと**設定**ページ、4 ステップで LLM / 埋め込み / 検索を検証。完了後に再起動。
- **CLI モード** — ターミナルだけで完結。

[http://localhost:3782](http://localhost:3782) で利用開始。

<a id="option-b-manual"></a>
### オプション B — 手動ローカルインストール

**1. 依存関係**

```bash
git clone https://github.com/HKUDS/DeepTutor.git
cd DeepTutor

conda create -n deeptutor python=3.11 && conda activate deeptutor
pip install -e ".[server]"

cd web && npm install && cd ..
```

**2. 環境**

```bash
cp .env.example .env
```

`.env` に最低限を記入：

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

**3. 起動**

```bash
python -m deeptutor.api.run_server
cd web && npm run dev -- -p 3782
```

| サービス | 既定ポート |
|:---:|:---:|
| バックエンド | `8001` |
| フロントエンド | `3782` |

### オプション C — Docker

```bash
git clone https://github.com/HKUDS/DeepTutor.git
cd DeepTutor
cp .env.example .env
```

`.env` は[オプション B](#option-b-manual)と同様。

**2a. 公式イメージ** — [GHCR](https://github.com/HKUDS/DeepTutor/pkgs/container/deeptutor)

```bash
docker compose -f docker-compose.ghcr.yml up -d
```

**2b. ソースビルド** — `docker compose up -d`

**3.** [http://localhost:3782](http://localhost:3782)

```bash
docker compose logs -f
docker compose down
```

<details>
<summary><b>クラウド / リモート</b></summary>

```dotenv
NEXT_PUBLIC_API_BASE_EXTERNAL=https://your-server.com:8001
```

</details>

<details>
<summary><b>開発モード（ホットリロード）</b></summary>

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up
```

</details>

<details>
<summary><b>カスタムポート</b></summary>

```dotenv
BACKEND_PORT=9001
FRONTEND_PORT=4000
```

```bash
docker compose up -d
```

</details>

<details>
<summary><b>データ永続化</b></summary>

| コンテナ | ホスト | 内容 |
|:---|:---|:---|
| `/app/data/user` | `./data/user` | 設定、メモリ、ワークスペース、セッション、ログ |
| `/app/data/knowledge_bases` | `./data/knowledge_bases` | ドキュメントとベクトル |

</details>

<details>
<summary><b>環境変数一覧</b></summary>

| 変数 | 必須 | 説明 |
|:---|:---:|:---|
| `LLM_BINDING` | **はい** | LLM プロバイダ |
| `LLM_MODEL` | **はい** | モデル名 |
| `LLM_API_KEY` | **はい** | API キー |
| `LLM_HOST` | **はい** | エンドポイント |
| `EMBEDDING_BINDING` | **はい** | 埋め込み |
| `EMBEDDING_MODEL` | **はい** | モデル名 |
| `EMBEDDING_API_KEY` | **はい** | キー |
| `EMBEDDING_HOST` | **はい** | エンドポイント |
| `EMBEDDING_DIMENSION` | **はい** | 次元 |
| `SEARCH_PROVIDER` | いいえ | 検索プロバイダ |
| `SEARCH_API_KEY` | いいえ | 検索キー |
| `BACKEND_PORT` | いいえ | 既定 `8001` |
| `FRONTEND_PORT` | いいえ | 既定 `3782` |
| `NEXT_PUBLIC_API_BASE_EXTERNAL` | いいえ | 公開 URL |
| `DISABLE_SSL_VERIFY` | いいえ | 既定 `false` |

</details>

### オプション D — CLI のみ

```bash
pip install -e ".[cli]"
deeptutor chat
deeptutor run chat "Explain Fourier transform"
deeptutor run deep_solve "Solve x^2 = 4"
deeptutor kb create my-kb --doc textbook.pdf
```

> 詳細は [DeepTutor CLI](#deeptutor-cli-guide)。

---

<a id="explore-deeptutor"></a>
## 📖 DeepTutor を探る

<div align="center">
<img src="../../assets/figs/deeptutor-architecture.png" alt="DeepTutor アーキテクチャ" width="800">
</div>

### 💬 チャット — 統一インテリジェントワークスペース

<div align="center">
<img src="../../assets/figs/dt-chat.png" alt="チャット" width="800">
</div>

**統一コンテキスト**で 5 モードが共存。履歴・KB・参照はモード間で保持。

| モード | 役割 |
|:---|:---|
| **チャット** | RAG、検索、コード実行、深い推論、ブレスト、論文検索を組み合わせ。 |
| **Deep Solve** | 計画・調査・解答・検証と引用。 |
| **クイズ生成** | KB に根ざした評価と検証。 |
| **Deep Research** | サブトピック分解と並列調査、引用付きレポート。 |
| **Math Animator** | Manim による可視化。 |

ツールは**ワークフローから分離** — モードごとに有効化を選択。

### ✍️ Co-Writer — エディタ内の AI

<div align="center">
<img src="../../assets/figs/dt-cowriter.png" alt="Co-Writer" width="800">
</div>

フル Markdown エディタで AI が共同編集。**書き換え / 拡張 / 要約**、KB や Web を参照。ノートブックへ保存可能。

### 🎓 ガイド付き学習

<div align="center">
<img src="../../assets/figs/dt-guide.png" alt="ガイド付き学習" width="800">
</div>

1. **学習計画** — 3〜5 の段階的知識点。  
2. **インタラクティブページ** — HTML で図解と例。  
3. **文脈 QA** — 各ステップでチャット。  
4. **まとめ** — 完了時にサマリ。

### 📚 ナレッジ管理

<div align="center">
<img src="../../assets/figs/dt-knowledge.png" alt="ナレッジ" width="800">
</div>

- **ナレッジベース** — PDF / TXT / MD、増分追加。  
- **ノートブック** — セッション横断で色分け整理。

### 🧠 メモリ

<div align="center">
<img src="../../assets/figs/dt-memory.png" alt="メモリ" width="800">
</div>

- **サマリ** — 学習の流れ。  
- **プロファイル** — 嗜好・レベル・目標・文体。TutorBot と共有。

---

<a id="tutorbot"></a>
### 🦞 TutorBot — 永続的で自律的な AI チューター

<div align="center">
<img src="../../assets/figs/tutorbot-architecture.png" alt="TutorBot アーキテクチャ" width="800">
</div>

[nanobot](https://github.com/HKUDS/nanobot) ベースの**マルチインスタンス**自律エージェント。各インスタンスは独立ループ・ワークスペース・記憶・人格。

<div align="center">
<img src="../../assets/figs/tb.png" alt="TutorBot" width="800">
</div>

- **Soul テンプレート** — 人格と教育哲学。  
- **独立ワークスペース** — メモリ・セッション・スキル。共有 KB 層にもアクセス。  
- **プロアクティブ Heartbeat** — 定期リマインダとタスク。  
- **フルツール** — RAG、コード、Web、論文、推論、ブレスト。  
- **スキル学習** — ワークスペースにスキルファイルを追加。  
- **マルチチャネル** — Telegram、Discord、Slack、Feishu、企業微信、DingTalk、メール 等。  
- **チーム / サブエージェント** — 長時間タスク向け。

```bash
deeptutor bot create math-tutor --persona "Socratic math teacher who uses probing questions"
deeptutor bot create writing-coach --persona "Patient, detail-oriented writing mentor"
deeptutor bot list
```

---

<a id="deeptutor-cli-guide"></a>
### ⌨️ DeepTutor CLI

<div align="center">
<img src="../../assets/figs/cli-architecture.png" alt="CLI アーキテクチャ" width="800">
</div>

ブラウザ不要で能力・KB・セッション・メモリ・TutorBot を操作。Rich と JSON。[`SKILL.md`](../../SKILL.md) をツール利用エージェントに渡すと自律設定・操作。

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
<summary><b>CLI コマンド一覧</b></summary>

| コマンド | 説明 |
|:---|:---|
| `deeptutor run <capability> <message>` | 1 ターン実行 |
| `deeptutor chat` | REPL |
| `deeptutor serve` | API サーバ |

**`deeptutor bot`** — `list` / `create` / `start` / `stop`

**`deeptutor kb`** — `list` / `info` / `create` / `add` / `search` / `set-default` / `delete`

**`deeptutor memory`** — `show` / `clear`

**`deeptutor session`** — `list` / `show` / `open` / `rename` / `delete`

**`deeptutor notebook`** — `list` / `create` / `show` / `add-md` / `replace-md` / `remove-record`

**`config` / `plugin` / `provider`** — `config show`、`plugin list/info`、`provider login`

</details>

<a id="community"></a>
## 🌐 コミュニティとエコシステム

| プロジェクト | 役割 |
|:---|:---|
| [**nanobot**](https://github.com/HKUDS/nanobot) | TutorBot の軽量エンジン |
| [**LlamaIndex**](https://github.com/run-llama/llama_index) | RAG とインデックス |
| [**ManimCat**](https://github.com/Wing900/ManimCat) | Math Animator |

| [⚡ LightRAG](https://github.com/HKUDS/LightRAG) | [🤖 AutoAgent](https://github.com/HKUDS/AutoAgent) | [🔬 AI-Researcher](https://github.com/HKUDS/AI-Researcher) | [🧬 nanobot](https://github.com/HKUDS/nanobot) |
|:---:|:---:|:---:|:---:|
| 高速 RAG | ノーコードエージェント | 自動研究 | 超軽量エージェント |

## 🤝 コントリビューション

<div align="center">

<a href="https://github.com/HKUDS/DeepTutor/graphs/contributors">
  <img src="https://contrib.rocks/image?repo=HKUDS/DeepTutor&max=999" alt="Contributors" />
</a>

</div>

[CONTRIBUTING.md](../../CONTRIBUTING.md) を参照。

## ⭐ Star 履歴

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
