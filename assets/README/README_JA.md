<div align="center">

<img src="../../assets/logo-ver2.png" alt="DeepTutor" width="140" style="border-radius: 15px;">

# DeepTutor：エージェントネイティブなパーソナライズド個別指導

<a href="https://trendshift.io/repositories/17099" target="_blank"><img src="https://trendshift.io/api/badge/repositories/17099" alt="HKUDS%2FDeepTutor | Trendshift" style="width: 250px; height: 55px;" width="250" height="55"/></a>

[![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-3776AB?style=flat-square&logo=python&logoColor=white)](https://www.python.org/downloads/)
[![Next.js 16](https://img.shields.io/badge/Next.js-16-000000?style=flat-square&logo=next.js&logoColor=white)](https://nextjs.org/)
[![License](https://img.shields.io/badge/License-Apache_2.0-blue?style=flat-square)](../../LICENSE)
[![GitHub release](https://img.shields.io/github/v/release/HKUDS/DeepTutor?style=flat-square&color=brightgreen)](https://github.com/HKUDS/DeepTutor/releases)
[![arXiv](https://img.shields.io/badge/arXiv-2604.26962-b31b1b?style=flat-square&logo=arxiv&logoColor=white)](https://arxiv.org/abs/2604.26962)

[![Discord](https://img.shields.io/badge/Discord-Community-5865F2?style=flat-square&logo=discord&logoColor=white)](https://discord.gg/eRsjPgMU4t)
[![Feishu](https://img.shields.io/badge/Feishu-Group-00D4AA?style=flat-square&logo=feishu&logoColor=white)](../../Communication.md)
[![WeChat](https://img.shields.io/badge/WeChat-Group-07C160?style=flat-square&logo=wechat&logoColor=white)](https://github.com/HKUDS/DeepTutor/issues/78)

[主な機能](#key-features) · [はじめに](#get-started) · [機能を探る](#explore-deeptutor) · [TutorBot](#tutorbot) · [CLI](#deeptutor-cli) · [マルチユーザー](#multi-user) · [ロードマップ](#roadmap) · [コミュニティ](#community)

[🇬🇧 English](../../README.md) · [🇨🇳 中文](README_CN.md) · [🇪🇸 Español](README_ES.md) · [🇫🇷 Français](README_FR.md) · [🇸🇦 العربية](README_AR.md) · [🇷🇺 Русский](README_RU.md) · [🇮🇳 हिन्दी](README_HI.md) · [🇵🇹 Português](README_PT.md) · [🇹🇭 ภาษาไทย](README_TH.md) · 🇵🇱 [Polski](README_PL.md)

</div>

---

> 🤝 **あらゆる形の貢献を歓迎します！** ブランチ戦略・コーディング規約・参加方法については [コントリビューションガイド](../../CONTRIBUTING.md) をご覧ください。

### 📦 リリース

> **[2026.5.4]** [v1.3.7](https://github.com/HKUDS/DeepTutor/releases/tag/v1.3.7) — 思考モデル／プロバイダー修正、ナレッジインデックス履歴の表示、Co-Writer のクリア・テンプレート編集の安全性向上。

> **[2026.5.3]** [v1.3.6](https://github.com/HKUDS/DeepTutor/releases/tag/v1.3.6) — チャットと TutorBot のカタログベースモデル選択、RAG 再インデックスの安全性向上、OpenAI Responses トークン上限修正、Skills エディター検証。

> **[2026.5.2]** [v1.3.5](https://github.com/HKUDS/DeepTutor/releases/tag/v1.3.5) — ローカル起動設定の改善、RAG クエリの安全性向上、ローカル埋め込み認証の整理、設定画面ダークモードの改善。

> **[2026.5.1]** [v1.3.4](https://github.com/HKUDS/DeepTutor/releases/tag/v1.3.4) — 書籍ページのチャット永続化と再構築フロー、チャットから書籍への参照、言語・推論処理の強化、RAG ドキュメント抽出の堅牢化。

> **[2026.4.30]** [v1.3.3](https://github.com/HKUDS/DeepTutor/releases/tag/v1.3.3) — NVIDIA NIM・Gemini 埋め込みサポート、チャット履歴／スキル／メモリの統合 Space コンテキスト、セッションスナップショット、RAG 再インデックスの耐障害性。

> **[2026.4.29]** [v1.3.2](https://github.com/HKUDS/DeepTutor/releases/tag/v1.3.2) — 埋め込みエンドポイント URL の透明化、無効ベクトル時の RAG 再インデックス耐障害性、思考モデル出力のメモリクリーンアップ、Deep Solve ランタイム修正。

> **[2026.4.28]** [v1.3.1](https://github.com/HKUDS/DeepTutor/releases/tag/v1.3.1) — 安定性：RAG ルーティングと埋め込み検証の強化、Docker 永続化、IME 対応入力、Windows/GBK 堅牢性向上。

> **[2026.4.27]** [v1.3.0](https://github.com/HKUDS/DeepTutor/releases/tag/v1.3.0) — バージョン管理付き KB インデックスと再インデックスワークフロー、ナレッジワークスペース再設計、埋め込み自動検出と新アダプター、Space ハブ。

> **[2026.4.25]** [v1.2.5](https://github.com/HKUDS/DeepTutor/releases/tag/v1.2.5) — チャット添付ファイルの永続化とファイルプレビュードロワー、添付ファイル対応機能パイプライン、TutorBot Markdown エクスポート。

> **[2026.4.25]** [v1.2.4](https://github.com/HKUDS/DeepTutor/releases/tag/v1.2.4) — テキスト/コード/SVG 添付ファイル、一コマンド Setup Tour、Markdown チャットエクスポート、コンパクトな KB 管理 UI。

> **[2026.4.24]** [v1.2.3](https://github.com/HKUDS/DeepTutor/releases/tag/v1.2.3) — ドキュメント添付ファイル（PDF/DOCX/XLSX/PPTX）、推論思考ブロック表示、Soul テンプレートエディター、Co-Writer からノートブックへの保存。

> **[2026.4.22]** [v1.2.2](https://github.com/HKUDS/DeepTutor/releases/tag/v1.2.2) — ユーザー作成 Skills システム、チャット入力パフォーマンス改善、TutorBot 自動起動、書籍ライブラリ UI、ビジュアライゼーション全画面表示。

> **[2026.4.21]** [v1.2.1](https://github.com/HKUDS/DeepTutor/releases/tag/v1.2.1) — 各ステージのトークン制限、全エントリーポイントでの回答再生成、RAG と Gemma 互換性修正。

> **[2026.4.20]** [v1.2.0](https://github.com/HKUDS/DeepTutor/releases/tag/v1.2.0) — Book Engine「生きた本」コンパイラー、マルチドキュメント Co-Writer、インタラクティブ HTML ビジュアライゼーション、質問バンク @-メンション。

<details>
<summary><b>過去のリリース（2週間以上前）</b></summary>

> **[2026.4.18]** [v1.1.2](https://github.com/HKUDS/DeepTutor/releases/tag/v1.1.2) — スキーマ駆動の Channels タブ、RAG 単一パイプライン統合、チャットプロンプトの外部化。

> **[2026.4.17]** [v1.1.1](https://github.com/HKUDS/DeepTutor/releases/tag/v1.1.1) — ユニバーサル「今すぐ回答」、Co-Writer スクロール同期、統一設定パネル、ストリーミング停止ボタン。

> **[2026.4.15]** [v1.1.0](https://github.com/HKUDS/DeepTutor/releases/tag/v1.1.0) — LaTeX ブロック数式の刷新、LLM 診断プローブ、Docker + ローカル LLM ガイド。

> **[2026.4.14]** [v1.1.0-beta](https://github.com/HKUDS/DeepTutor/releases/tag/v1.1.0-beta) — URL ブックマーク可能セッション、Snow テーマ、WebSocket ハートビートと自動再接続、埋め込みレジストリ刷新。

> **[2026.4.13]** [v1.0.3](https://github.com/HKUDS/DeepTutor/releases/tag/v1.0.3) — ブックマークとカテゴリ付き質問ノートブック、Visualize での Mermaid 対応、埋め込みミスマッチ検出、Qwen/vLLM 互換性、LM Studio と llama.cpp サポート、Glass テーマ。

> **[2026.4.11]** [v1.0.2](https://github.com/HKUDS/DeepTutor/releases/tag/v1.0.2) — SearXNG フォールバック付き検索統合、プロバイダー切り替え修正、フロントエンドリソースリーク修正。

> **[2026.4.10]** [v1.0.1](https://github.com/HKUDS/DeepTutor/releases/tag/v1.0.1) — Visualize 機能（Chart.js/SVG）、クイズ重複防止、o4-mini モデルサポート。

> **[2026.4.10]** [v1.0.0-beta.4](https://github.com/HKUDS/DeepTutor/releases/tag/v1.0.0-beta.4) — レート制限リトライ付き埋め込み進捗追跡、クロスプラットフォーム依存関係修正、MIME 検証修正。

> **[2026.4.8]** [v1.0.0-beta.3](https://github.com/HKUDS/DeepTutor/releases/tag/v1.0.0-beta.3) — ネイティブ OpenAI/Anthropic SDK（litellm 廃止）、Windows 対応 Math Animator、堅牢な JSON パース、中国語完全 i18n。

> **[2026.4.7]** [v1.0.0-beta.2](https://github.com/HKUDS/DeepTutor/releases/tag/v1.0.0-beta.2) — 設定ホットリロード、MinerU ネスト出力、WebSocket 修正、Python 3.11+ 最低要件。

> **[2026.4.4]** [v1.0.0-beta.1](https://github.com/HKUDS/DeepTutor/releases/tag/v1.0.0-beta.1) — エージェントネイティブアーキテクチャ再設計（約20万行）：Tools + Capabilities プラグインモデル、CLI & SDK、TutorBot、Co-Writer、ガイド付き学習、永続メモリ。

> **[2026.1.23]** [v0.6.0](https://github.com/HKUDS/DeepTutor/releases/tag/v0.6.0) — セッション永続化、増分アップロード、柔軟な RAG インポート、中国語完全ローカライズ。

> **[2026.1.18]** [v0.5.2](https://github.com/HKUDS/DeepTutor/releases/tag/v0.5.2) — RAG-Anything の Docling サポート、ログ最適化とバグ修正。

> **[2026.1.15]** [v0.5.0](https://github.com/HKUDS/DeepTutor/releases/tag/v0.5.0) — 統合サービス設定、KB ごとの RAG パイプライン選択、質問生成の刷新、サイドバーカスタマイズ。

> **[2026.1.9]** [v0.4.0](https://github.com/HKUDS/DeepTutor/releases/tag/v0.4.0) — マルチプロバイダー LLM・埋め込みサポート、新ホームページ、RAG モジュール分離、環境変数リファクタリング。

> **[2026.1.5]** [v0.3.0](https://github.com/HKUDS/DeepTutor/releases/tag/v0.3.0) — 統合 PromptManager、GitHub Actions CI/CD、GHCR プリビルドイメージ。

> **[2026.1.2]** [v0.2.0](https://github.com/HKUDS/DeepTutor/releases/tag/v0.2.0) — Docker デプロイ、Next.js 16 & React 19、WebSocket セキュリティ強化、重大脆弱性修正。

</details>

### 📰 ニュース

> **[2026.4.19]** 🎉 111日で20k スター達成！温かいサポートに感謝します — 真にパーソナライズされた、インテリジェントな個別指導を目指して継続的に改善します。

> **[2026.4.10]** 📄 論文が arXiv で公開されました！[プレプリント](https://arxiv.org/abs/2604.26962)を読んで DeepTutor の設計と背景にあるアイデアをご確認ください。

> **[2026.4.4]** お久しぶりです！✨ DeepTutor v1.0.0 がついに登場 — アーキテクチャを一から書き直したエージェントネイティブな進化。TutorBot、柔軟なモード切り替えを Apache-2.0 ライセンスで。新しい章の始まりです！

> **[2026.2.6]** 🚀 わずか39日で10k スター達成！素晴らしいコミュニティに感謝します！

> **[2026.1.1]** 明けましておめでとうございます！[Discord](https://discord.gg/eRsjPgMU4t)、[WeChat](https://github.com/HKUDS/DeepTutor/issues/78)、または [Discussions](https://github.com/HKUDS/DeepTutor/discussions) にご参加ください。

> **[2025.12.29]** DeepTutor 正式リリース！

<a id="key-features"></a>
## ✨ 主な機能

- **統合チャットワークスペース** — 6つのモード、1つのスレッド。Chat、Deep Solve、クイズ生成、Deep Research、Math Animator、Visualize が同一コンテキストを共有 — 会話を始め、マルチエージェント問題解決にエスカレートし、クイズ生成、概念の可視化、深掘り調査をメッセージを失うことなく実行。
- **AI Co-Writer** — AI がファーストクラスのコラボレーターとして参加するマルチドキュメント Markdown ワークスペース。テキストを選択して、ナレッジベースやウェブから情報を引き出しながら書き直し・拡張・要約。あらゆる成果物が学習エコシステムに還流。
- **Book Engine** — 教材を構造化・インタラクティブな「生きた本」に変換。マルチエージェントパイプラインがアウトライン設計、関連ソース取得、13種のブロックタイプ（クイズ、フラッシュカード、タイムライン、概念グラフ、インタラクティブデモなど）を含むリッチなページをコンパイル。
- **ナレッジハブ** — PDF、Markdown、テキストファイルをアップロードして RAG 対応ナレッジベースを構築。色分けされたノートブックに洞察を整理し、質問バンクでクイズを振り返り、DeepTutor の教え方を形成するカスタム Skills を作成。ドキュメントは静的に置かれているだけでなく、あらゆる会話を積極的に支援。
- **永続メモリ** — DeepTutor があなたのプロフィールを構築：何を学んだか、どのように学ぶか、どこへ向かっているか。すべての機能と TutorBot で共有され、インタラクションを重ねるごとに精度が向上。
- **パーソナル TutorBot** — チャットボットではなく自律型チューター。各 TutorBot は独自のワークスペース、メモリ、人格、スキルセットを持つ。リマインダーを設定し、新しい能力を学び、あなたとともに成長。[nanobot](https://github.com/HKUDS/nanobot) で動作。
- **エージェントネイティブ CLI** — すべての機能、ナレッジベース、セッション、TutorBot に一コマンドでアクセス。人間には Rich ターミナル出力、AI エージェントとパイプラインには構造化 JSON。プロジェクトルートの [`SKILL.md`](../../SKILL.md) を任意のツール対応エージェントに渡せば自律的に操作可能。
- **オプション認証** — ローカル使用時はデフォルト無効。公開ホスティング時は環境変数2つでログイン要求。bcrypt ハッシュパスワード、JWT セッション、セルフサービス登録ページ、組み込み管理ダッシュボードによるマルチユーザーサポート。オプションで **PocketBase** を認証・ストレージのサイドカーとして使用可能（OAuth 対応、マルチユーザー並行処理改善）。

---

<a id="get-started"></a>
## 🚀 はじめに

### 前提条件

開始前に以下がインストールされていることを確認してください：

| 要件 | バージョン | 確認方法 | 備考 |
|:---|:---|:---|:---|
| [Git](https://git-scm.com/) | 任意 | `git --version` | リポジトリのクローン用 |
| [Python](https://www.python.org/downloads/) | 3.11+ | `python --version` | バックエンドランタイム |
| [Node.js](https://nodejs.org/) | 20.9+ | `node --version` | ローカル Web インストールのフロントエンドランタイム |
| [npm](https://www.npmjs.com/) | Node.js に同梱 | `npm --version` | Node.js と一緒にインストール |

> **Windows のみ（コンパイラー不足の修正）：** Visual Studio をインストールしていない場合は、[Visual Studio Build Tools](https://visualstudio.microsoft.com/visual-cpp-build-tools/) をインストールし、**C++ によるデスクトップ開発**ワークロードを選択してください。

また、少なくとも1つの LLM プロバイダーの **API キー**が必要です（例：[OpenAI](https://platform.openai.com/api-keys)、[DeepSeek](https://platform.deepseek.com/)、[Anthropic](https://console.anthropic.com/)）。Setup Tour が入力をガイドします。

### オプション A — Setup Tour（推奨）

初めてのローカル Web セットアップのためのガイド付き CLI ウィザード。環境チェック、Python と Node.js 依存関係のインストール、`.env` の作成、TutorBot・Matrix・Math Animator などのオプションアドオン選択ができます。

**1. リポジトリをクローン**

```bash
git clone https://github.com/HKUDS/DeepTutor.git
cd DeepTutor
```

**2. Python 環境の作成と有効化**

システムに応じて以下のいずれかを選択してください。

macOS / Linux（`venv`）：

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
```

Windows PowerShell（`venv`）：

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
```

Anaconda / Miniconda：

```bash
conda create -n deeptutor python=3.11
conda activate deeptutor
python -m pip install --upgrade pip
```

**3. ガイドツアーを起動**

```bash
python scripts/start_tour.py
```

インストール手順では使用する依存関係プロファイルを選択します：

| 選択肢 | インストール内容 | 選択タイミング |
|:---|:---|:---|
| Web app（推奨） | CLI + API サーバー + RAG/ドキュメント解析 | 初めてのほとんどのユーザー |
| Web + TutorBot | TutorBot エンジンと一般的なチャンネル SDK を追加 | 自律型チューターやチャンネル統合が必要な場合 |
| Web + TutorBot + Matrix | Matrix / Element チャンネルサポートを追加 | `libolm` がインストール済みか準備できている場合のみ |
| Math Animator アドオン | Manim を別途インストール | アニメーション生成が必要で LaTeX/ffmpeg/ビルドツールが準備できている場合のみ |

ウィザード完了後：

```bash
python scripts/start_web.py
```

> **日常的な起動** — ツアーは一度だけ必要です。以降は Python 環境を有効化した状態で `python scripts/start_web.py` を実行してバックエンドとフロントエンドを起動。フロントエンド URL がターミナルに表示されます。プロバイダーの変更、ポート変更、オプションアドオンのインストール時のみ `start_tour.py` を再実行してください。

> **ローカルインストールの更新** — オプション A または B で git クローンからインストールした場合は `python scripts/update.py` を実行。現在のブランチのリモートを取得し、ローカルとリモートのコミット差分を表示し、ブランチマッピングを確認後に安全な fast-forward プルを実行します。

<a id="option-b--manual-local-install"></a>
### オプション B — 手動ローカルインストール

各セットアップコマンドを自分で実行する場合はこの方法を使用してください。

**1. リポジトリをクローン**

```bash
git clone https://github.com/HKUDS/DeepTutor.git
cd DeepTutor
```

**2. Python 環境の作成と有効化**

上記と同様に venv/conda のいずれかを選択してください。

**3. 依存関係のインストール**

```bash
# バックエンド + Web サーバー依存関係（CLI、RAG、ドキュメント解析、組み込み LLM プロバイダー SDK を含む）
python -m pip install -e ".[server]"

# オプションアドオン（必要なものだけインストール）：
#   python -m pip install -e ".[tutorbot]"       # TutorBot エンジン + チャンネル SDK
#   python -m pip install -e ".[tutorbot,matrix]" # TutorBot + Matrix チャンネル（libolm が必要）
#   python -m pip install -e ".[math-animator]"  # Manim（LaTeX/ffmpeg/ビルドツールも必要）
#   python -m pip install -e ".[all]"            # 上記すべて + 開発ツール

# フロントエンド依存関係（Node.js 20.9+ が必要）
cd web
npm install
cd ..
```

**4. 環境設定**

```bash
cp .env.example .env
```

`.env` を編集して少なくとも LLM フィールドを入力してください。埋め込みフィールドはナレッジベース機能に必要ですが、チャットを試すだけであれば後回しにできます。

```dotenv
# LLM（チャットに必要）
LLM_BINDING=openai
LLM_MODEL=gpt-4o-mini
LLM_API_KEY=sk-xxx
LLM_HOST=https://api.openai.com/v1

# 埋め込み（ナレッジベース / RAG に必要）
EMBEDDING_BINDING=openai
EMBEDDING_MODEL=text-embedding-3-large
EMBEDDING_API_KEY=sk-xxx
# v1.3.0+: https://api.openai.com/v1 だけでなくエンドポイント URL 全体を使用
EMBEDDING_HOST=https://api.openai.com/v1/embeddings
# 特定の次元を強制する必要がない場合は空のままにしてください
EMBEDDING_DIMENSION=
```

<details>
<summary><b>サポートされている LLM プロバイダー</b></summary>

| プロバイダー | Binding | デフォルトベース URL |
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
<summary><b>サポートされている埋め込みプロバイダー</b></summary>

| プロバイダー | Binding | モデル例 | デフォルト次元 |
|:--|:--|:--|:--|
| OpenAI | `openai` | `text-embedding-3-large` | 3072 |
| Azure OpenAI | `azure_openai` | デプロイ名 | — |
| Cohere | `cohere` | `embed-v4.0` | 1024 |
| Jina | `jina` | `jina-embeddings-v3` | 1024 |
| Ollama | `ollama` | `nomic-embed-text` | 768 |
| vLLM / LM Studio | `vllm` | 任意の埋め込みモデル | — |
| OpenAI 互換 | `custom` | — | — |

OpenAI 互換プロバイダー（DashScope、SiliconFlow など）は `custom` または `openai` バインディング経由で使用できます。

</details>

<details>
<summary><b>サポートされている Web 検索プロバイダー</b></summary>

| プロバイダー | 環境変数キー | 備考 |
|:--|:--|:--|
| Brave | `BRAVE_API_KEY` | 推奨、無料ティアあり |
| Tavily | `TAVILY_API_KEY` | |
| Serper | `SERPER_API_KEY` | Serper 経由の Google 検索結果 |
| Jina | `JINA_API_KEY` | |
| SearXNG | — | セルフホスト、API キー不要 |
| DuckDuckGo | — | API キー不要 |
| Perplexity | `PERPLEXITY_API_KEY` | API キーが必要 |

</details>

**5. サービスの起動**

最速の起動方法：

```bash
python scripts/start_web.py
```

バックエンドとフロントエンドの両方を起動します。ターミナルを開いたままにして、表示されたフロントエンド URL を開いてください。

または、別のターミナルで各サービスを手動起動：

```bash
# バックエンド（FastAPI）
python -m deeptutor.api.run_server

# フロントエンド（Next.js）— 別のターミナルで
cd web && npm run dev -- -p 3782
```

| サービス | デフォルトポート |
|:---:|:---:|
| バックエンド | `8001` |
| フロントエンド | `3782` |

[http://localhost:3782](http://localhost:3782) を開けば準備完了です。

### オプション C — Docker デプロイ

Docker はバックエンドとフロントエンドを1つのコンテナにまとめます。ローカルの Python や Node.js は不要です。[Docker Desktop](https://www.docker.com/products/docker-desktop/)（または Linux では Docker Engine + Compose）だけが必要です。

**1. 環境変数の設定**（以下の両方のオプションで必要）

```bash
git clone https://github.com/HKUDS/DeepTutor.git
cd DeepTutor
cp .env.example .env
```

`.env` を編集して少なくとも必須フィールドを入力してください（[オプション B](#option-b--manual-local-install) と同様）。

**2a. 公式イメージをプル（推奨）**

公式イメージは各リリース時に [GitHub Container Registry](https://github.com/HKUDS/DeepTutor/pkgs/container/deeptutor) に `linux/amd64` と `linux/arm64` 向けに公開されます。

```bash
docker compose -f docker-compose.ghcr.yml up -d
```

特定のバージョンに固定するには `docker-compose.ghcr.yml` のイメージタグを編集：

```yaml
image: ghcr.io/hkuds/deeptutor:1.3.4  # または :latest
```

**2b. ソースからビルド**

```bash
docker compose up -d
```

`Dockerfile` からローカルでイメージをビルドしてコンテナを起動します。

**3. 確認と管理**

コンテナが healthy になったら [http://localhost:3782](http://localhost:3782) を開いてください。

```bash
docker compose logs -f   # ログのフォロー
docker compose down       # コンテナの停止と削除
```

<details>
<summary><b>クラウド / リモートサーバーデプロイ</b></summary>

リモートサーバーにデプロイする場合、ブラウザはバックエンド API の公開 URL を知る必要があります。`.env` にもう1つ変数を追加してください：

```dotenv
# バックエンドが到達可能な公開 URL を設定
NEXT_PUBLIC_API_BASE_EXTERNAL=https://your-server.com:8001
```

フロントエンド起動スクリプトがランタイムでこの値を適用します — 再ビルドは不要です。

</details>

<details>
<summary><b>認証（公開デプロイ）</b></summary>

認証は**デフォルト無効**です — localhost ではログイン不要です。マルチテナントデプロイ（ユーザーごとのワークスペース、管理者による モデル/KB/スキルのキュレーション、監査ログ）については、以下の専用[マルチユーザー](#multi-user)セクションを参照してください。

**ヘッドレスシングルユーザー（`/register` フローなし）：** ブラウザで最初の管理者を作成できない場合（例：無人コンテナ）、環境変数で事前設定：

```bash
python -c "from deeptutor.services.auth import hash_password; print(hash_password('yourpassword'))"
```

```dotenv
AUTH_ENABLED=true
AUTH_USERNAME=admin
AUTH_PASSWORD_HASH=<ハッシュをここに貼り付け>
AUTH_SECRET=your-secret-here
```

このパスは1つのアカウントとして扱われ、管理者として機能します。ブラウザでの登録フローを完了すると、ディスク上の `multi-user/_system/auth/users.json` が優先され、環境変数はフォールバックになります。

</details>

<details>
<summary><b>PocketBase サイドカー（オプション認証 + ストレージ）</b></summary>

PocketBase は組み込みの SQLite/JSON 認証とセッションストレージを置き換えるオプションの軽量バックエンドです。OAuth 対応認証、リアルタイムサブスクリプション、ビジュアル管理パネルを追加します — `POCKETBASE_URL` を設定しなければいつでも元に戻せます。

> ⚠️ **PocketBase モードは現在シングルユーザーのみ対応。** デフォルトスキーマには `users` に `role` フィールドがなく（すべてのログインが `role=user` になり、管理者を作成できない）、セッション/メッセージ/ターンのクエリが `user_id` でフィルタリングされていません。マルチユーザーデプロイは `POCKETBASE_URL` を空白のままにしてデフォルトの JSON/SQLite バックエンドを使用してください。

**Quick start（Docker Compose）：**

```bash
docker compose up -d
open http://localhost:8090/_/
pip install pocketbase
python scripts/pb_setup.py
# .env で PocketBase を有効化して再起動
```

**必須 `.env` 追加：**

```dotenv
POCKETBASE_URL=http://localhost:8090
POCKETBASE_ADMIN_EMAIL=admin@example.com
POCKETBASE_ADMIN_PASSWORD=your-admin-password
```

`POCKETBASE_URL` を未設定（または削除）にすれば、いつでも組み込みバックエンドに戻れます — 新しいセッションのデータ移行は不要です。

</details>

<details>
<summary><b>開発モード（ホットリロード）</b></summary>

ソースコードをマウントし、両サービスのホットリロードを有効化：

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up
```

`deeptutor/`、`deeptutor_cli/`、`scripts/`、`web/` への変更が即座に反映されます。

</details>

<details>
<summary><b>カスタムポート</b></summary>

`.env` でデフォルトポートをオーバーライド：

```dotenv
BACKEND_PORT=9001
FRONTEND_PORT=4000
```

再起動：

```bash
docker compose up -d     # または docker compose -f docker-compose.ghcr.yml up -d
```

</details>

<details>
<summary><b>データ永続化</b></summary>

ユーザーデータとナレッジベースは Docker ボリューム経由でローカルディレクトリにマップされます：

| コンテナパス | ホストパス | コンテンツ |
|:---|:---|:---|
| `/app/data/user` | `./data/user` | 設定、ワークスペース、セッション、ログ |
| `/app/data/memory` | `./data/memory` | 共有長期メモリ（`SUMMARY.md`、`PROFILE.md`） |
| `/app/data/knowledge_bases` | `./data/knowledge_bases` | アップロードドキュメントとベクターインデックス |

これらのディレクトリは `docker compose down` 後も残り、次の `docker compose up` で再利用されます。

</details>

<details>
<summary><b>環境変数リファレンス</b></summary>

> 正規の完全コメント付きリストは [`.env.example`](../../.env.example) を参照。下表はほとんどのユーザーが触れる変数を網羅。

| 変数 | 必須 | 説明 |
|:---|:---:|:---|
| `LLM_BINDING` | **Yes** | LLM プロバイダー（`openai`、`anthropic`、`deepseek` など） |
| `LLM_MODEL` | **Yes** | モデル名（例：`gpt-4o`） |
| `LLM_API_KEY` | **Yes** | LLM API キー |
| `LLM_HOST` | **Yes** | チャット補完ベース URL |
| `LLM_API_VERSION` | No | Azure OpenAI に必要、それ以外は空白 |
| `LLM_REASONING_EFFORT` | No | DeepSeek `high`/`max`/`minimal` または OpenAI o シリーズ `low`/`medium`/`high` |
| `EMBEDDING_BINDING` | ナレッジベースのみ | 埋め込みプロバイダー |
| `EMBEDDING_MODEL` | ナレッジベースのみ | 埋め込みモデル名 |
| `EMBEDDING_API_KEY` | ナレッジベースのみ | 埋め込み API キー |
| `EMBEDDING_HOST` | ナレッジベースのみ | 埋め込みエンドポイント URL（v1.3.0+、パスを追加せずそのまま呼び出し） |
| `EMBEDDING_DIMENSION` | No | ベクター次元、自動検出には空白 |
| `EMBEDDING_SEND_DIMENSIONS` | No | 三状態 — `true`/`false`/空白（自動） |
| `SEARCH_PROVIDER` | No | `brave`、`tavily`、`serper`、`jina`、`perplexity`、`searxng`、`duckduckgo` |
| `SEARCH_API_KEY` | No | 検索 API キー |
| `SEARCH_BASE_URL` | No | セルフホスト SearXNG に必要 |
| `SEARCH_PROXY` | No | 発信検索トラフィックのオプション HTTP/HTTPS プロキシ |
| `BACKEND_PORT` | No | バックエンドポート（デフォルト `8001`） |
| `FRONTEND_PORT` | No | フロントエンドポート（デフォルト `3782`） |
| `POCKETBASE_PORT` | No | オプション PocketBase サイドカーの Docker ポートマッピング（デフォルト `8090`） |
| `NEXT_PUBLIC_API_BASE_EXTERNAL` | No | クラウドデプロイ用のバックエンド公開 URL |
| `NEXT_PUBLIC_API_BASE` | No | Next.js クライアント用のバックエンド URL 直接オーバーライド |
| `CORS_ORIGIN` | No | FastAPI CORS 許可リストに追加する余分なオリジン |
| `DISABLE_SSL_VERIFY` | No | 発信 TLS 検証を無効化（デフォルト `false`） |
| `AUTH_ENABLED` | No | `true` の時にログインを要求（デフォルト `false`） |
| `NEXT_PUBLIC_AUTH_ENABLED` | No | オプションのフロントエンドオーバーライド、空白は `AUTH_ENABLED` から導出 |
| `AUTH_SECRET` | No | JWT 署名秘密鍵、空白は `multi-user/_system/auth/auth_secret` に自動生成 |
| `AUTH_TOKEN_EXPIRE_HOURS` | No | セッション期間（時間単位、デフォルト `24`） |
| `AUTH_COOKIE_SECURE` | No | HTTPS 提供時に認証クッキーを `Secure` にマーク（デフォルト `false`） |
| `AUTH_USERNAME` | No | シングルユーザーモード：管理者ユーザー名 |
| `AUTH_PASSWORD_HASH` | No | シングルユーザーモード：管理者パスワードの bcrypt ハッシュ |
| `POCKETBASE_URL` | No | 設定で PocketBase サイドカーを有効化（シングルユーザーのみ） |
| `POCKETBASE_ADMIN_EMAIL` / `POCKETBASE_ADMIN_PASSWORD` | No | Python バックエンドが PocketBase コレクションを管理するための管理者資格情報 |
| `POCKETBASE_EXTERNAL_URL` | No | OAuth リダイレクト用 PocketBase 公開 URL（リモートデプロイのみ） |
| `CHAT_ATTACHMENT_DIR` | No | チャット添付ファイルストレージルートのオーバーライド |

</details>

### オプション D — CLI のみ

フロントエンドなしで CLI だけが必要な場合：

```bash
python -m pip install -e ".[cli]"
```

LLM プロバイダーの設定はまだ必要です：

```bash
cp .env.example .env   # .env を編集して API キーを入力
```

設定後、すぐに使用できます：

```bash
deeptutor chat                                   # インタラクティブ REPL
deeptutor run chat "Explain Fourier transform"   # ワンショット機能
deeptutor run deep_solve "Solve x^2 = 4"         # マルチエージェント問題解決
deeptutor kb create my-kb --doc textbook.pdf     # ナレッジベース作成
```

> 完全な機能ガイドとコマンドリファレンスは [DeepTutor CLI](#deeptutor-cli) を参照。

---

<a id="explore-deeptutor"></a>
## 📖 DeepTutor を探る

<div align="center">
<img src="../../assets/figs/deeptutor-architecture.png" alt="DeepTutor アーキテクチャ" width="800">
</div>

### 💬 チャット — 統合インテリジェントワークスペース

<div align="center">
<img src="../../assets/figs/dt-chat.png" alt="チャットワークスペース" width="800">
</div>

6つのモードが1つのワークスペースに共存し、**統合コンテキスト管理システム**によって結びついています。会話履歴、ナレッジベース、参照がモード間で保持され、同じトピック内で必要なときにいつでも自由に切り替えられます。

| モード | 機能 |
|:---|:---|
| **Chat** | 流暢なツール拡張会話。RAG 取得、Web 検索、コード実行、深い推論、ブレインストーミング、論文検索から選択し、必要に応じて組み合わせ。 |
| **Deep Solve** | マルチエージェント問題解決：計画、調査、解決、検証 — 各ステップで正確なソース引用付き。 |
| **Quiz Generation** | ナレッジベースに基づいた評価を組み込み検証付きで生成。 |
| **Deep Research** | トピックをサブトピックに分解し、RAG、Web、学術論文に並列研究エージェントを派遣して完全に引用されたレポートを作成。 |
| **Math Animator** | Manim を活用して数学的概念をビジュアルアニメーションと絵コンテに変換。 |
| **Visualize** | 自然言語の説明からインタラクティブな SVG ダイアグラム、Chart.js チャート、Mermaid グラフ、または自己完結型 HTML ページを生成。 |

ツールはワークフローから**分離**されています — 各モードで有効にするツール、使用数、または全く使用しないかを自由に決定できます。

> 簡単なチャット質問から始め、難しくなったら Deep Solve にエスカレートし、概念を可視化し、クイズ質問で自己テストし、さらに深く掘り下げるために Deep Research を起動 — すべて1つの継続的なスレッドで。

### ✍️ Co-Writer — マルチドキュメント AI 執筆ワークスペース

<div align="center">
<img src="../../assets/figs/dt-cowriter.png" alt="Co-Writer" width="800">
</div>

Co-Writer はチャットのインテリジェンスを執筆面に直接もたらします。複数のドキュメントを作成・管理し、各ドキュメントは独自のワークスペースに永続化されます — 使い捨てのスクラッチパッドではなく、AI がファーストクラスのコラボレーターとして参加する本格的なマルチドキュメント Markdown エディターです。

任意のテキストを選択して **Rewrite**、**Expand**、**Shorten** を選択 — オプションでナレッジベースや Web からコンテキストを引き出します。編集フローは完全な undo/redo を備えた非破壊的なもので、書いたコンテンツはすべてノートブックに直接保存でき、学習エコシステムに還流します。

### 📖 Book Engine — インタラクティブな「生きた本」

<div align="center">
<img src="../../assets/figs/dt-book-0.png" alt="書籍ライブラリ" width="270"><img src="../../assets/figs/dt-book-1.png" alt="書籍リーダー" width="270"><img src="../../assets/figs/dt-book-2.png" alt="書籍アニメーション" width="270">
</div>

DeepTutor にトピックを与え、ナレッジベースを指定すると、構造化されたインタラクティブな本を作成します — 静的なエクスポートではなく、読んで、クイズを受けて、文脈の中で議論できる生きたドキュメントです。

マルチエージェントパイプラインが重労働を担います：アウトライン提案、ナレッジベースからの関連ソース取得、章ツリーの合成、各ページの計画、すべてのブロックのコンパイル。あなたはコントロールを保持 — 提案のレビュー、章の並び替え、任意のページの横でのチャット。

ページは13種のブロックタイプで組み立てられます — テキスト、コールアウト、クイズ、フラッシュカード、コード、フィギュア、ディープダイブ、アニメーション、インタラクティブデモ、タイムライン、概念グラフ、セクション、ユーザーノート — 各ブロックは独自のインタラクティブコンポーネントでレンダリングされます。リアルタイム進捗タイムラインで本が形成される様子を観察できます。

### 📚 ナレッジ管理 — 学習インフラ

<div align="center">
<img src="../../assets/figs/dt-knowledge.png" alt="ナレッジ管理" width="800">
</div>

ナレッジは DeepTutor の他のすべてを動かすドキュメントコレクション、ノート、教授ペルソナを構築・管理する場所です。

- **ナレッジベース** — PDF、Office ファイル（DOCX/XLSX/PPTX）、Markdown、テキストやコードファイルをアップロードして検索可能な RAG 対応コレクションを作成。ライブラリの成長に合わせて段階的にドキュメントを追加。
- **ノートブック** — セッションをまたいで学習記録を整理。チャット、Co-Writer、書籍、Deep Research からの洞察を色分けされたノートブックに保存。
- **質問バンク** — 生成されたすべてのクイズ質問を閲覧・再確認。エントリをブックマークし、過去のパフォーマンスを分析するためにチャットで @-メンション。
- **Skills** — `SKILL.md` ファイルでカスタム教授ペルソナを作成。各スキルは名前、説明、オプショントリガー、有効化時にチャットシステムプロンプトに注入される Markdown 本文を定義 — DeepTutor をソクラテス式チューター、学習パートナー、研究アシスタント、または自分でデザインする任意のロールに変える。

あなたのナレッジベースは受動的なストレージではありません — あらゆる会話、あらゆる研究セッション、あなたが作成するあらゆる学習パスに積極的に参加します。

### 🧠 メモリ — DeepTutor があなたと一緒に学ぶ

<div align="center">
<img src="../../assets/figs/dt-memory.png" alt="メモリ" width="800">
</div>

DeepTutor は2つの補完的な次元を通じて、あなたについての永続的で進化するプロファイルを維持します：

- **サマリー** — 学習進捗の実行中のダイジェスト：何を学んだか、どのトピックを探求したか、理解がどう発展したか。
- **プロフィール** — 学習者のアイデンティティ：好み、知識レベル、目標、コミュニケーションスタイル — あらゆるインタラクションを通じて自動的に洗練。

メモリはすべての機能とすべての TutorBot で共有されます。DeepTutor を使えば使うほど、よりパーソナライズされ効果的になります。

---

<a id="tutorbot"></a>
### 🦞 TutorBot — 永続的な自律型 AI チューター

<div align="center">
<img src="../../assets/figs/tutorbot-architecture.png" alt="TutorBot アーキテクチャ" width="800">
</div>

TutorBot はチャットボットではありません — [nanobot](https://github.com/HKUDS/nanobot) 上に構築された**永続的なマルチインスタンスエージェント**です。各 TutorBot は独立したワークスペース、メモリ、人格で独自のエージェントループを実行します。ソクラテス式数学チューター、忍耐強い文章コーチ、厳格な研究アドバイザーを同時に作成 — すべて並行して実行され、あなたとともに進化します。

<div align="center">
<img src="../../assets/figs/tb.png" alt="TutorBot" width="800">
</div>

- **Soul テンプレート** — 編集可能な Soul ファイルを通じてチューターの人格、トーン、教授哲学を定義。組み込みアーキタイプ（ソクラテス式、励まし型、厳格型）から選択するか自分でデザイン — soul がすべての回答を形成。
- **独立ワークスペース** — 各ボットは独自のディレクトリを持ち、メモリ、セッション、スキル、設定が分離 — 完全に独立しながら DeepTutor の共有ナレッジ層にアクセス可能。
- **プロアクティブ Heartbeat** — ボットは応答するだけでなく、主体的に動きます。組み込み Heartbeat システムで定期的な学習チェックイン、復習リマインダー、スケジュールタスクが可能。
- **フルツールアクセス** — 各ボットが DeepTutor の完全なツールキットにアクセス：RAG 取得、コード実行、Web 検索、学術論文検索、深い推論、ブレインストーミング。
- **スキル学習** — ワークスペースにスキルファイルを追加して新しい能力を教える。ニーズが進化するにつれ、チューターの能力も進化。
- **マルチチャンネルプレゼンス** — Telegram、Discord、Slack、Feishu、WeChat Work、DingTalk、Matrix、QQ、WhatsApp、Email などに接続。チューターはあなたがいる場所に会いに来ます。
- **チームとサブエージェント** — 単一ボット内でバックグラウンドサブエージェントを生成するか、複雑で長時間実行されるタスクのためにマルチエージェントチームをオーケストレーション。

```bash
deeptutor bot create math-tutor --persona "Socratic math teacher who uses probing questions"
deeptutor bot create writing-coach --persona "Patient, detail-oriented writing mentor"
deeptutor bot list                  # すべてのアクティブなチューターを確認
```

---

<a id="deeptutor-cli"></a>
### ⌨️ DeepTutor CLI — エージェントネイティブインターフェース

<div align="center">
<img src="../../assets/figs/cli-architecture.png" alt="DeepTutor CLI アーキテクチャ" width="800">
</div>

DeepTutor は完全に CLI ネイティブです。すべての機能、ナレッジベース、セッション、メモリ、TutorBot に一コマンドでアクセス — ブラウザ不要。CLI は人間（リッチターミナルレンダリング）と AI エージェント（構造化 JSON 出力）の両方に対応。

プロジェクトルートの [`SKILL.md`](../../SKILL.md) を任意のツール対応エージェント（[nanobot](https://github.com/HKUDS/nanobot) または任意の LLM）に渡せば、DeepTutor を自律的に設定・操作できます。

**ワンショット実行** — 任意の機能をターミナルから直接実行：

```bash
deeptutor run chat "Explain the Fourier transform" -t rag --kb textbook
deeptutor run deep_solve "Prove that √2 is irrational" -t reason
deeptutor run deep_question "Linear algebra" --config num_questions=5
deeptutor run deep_research "Attention mechanisms in transformers"
deeptutor run visualize "Draw the architecture of a transformer"
```

**インタラクティブ REPL** — ライブモード切り替え付きの永続チャットセッション：

```bash
deeptutor chat --capability deep_solve --kb my-kb
# REPL 内：/cap、/tool、/kb、/history、/notebook、/config でオンザフライで切り替え
```

**ナレッジベースライフサイクル** — RAG 対応コレクションをターミナルから完全に構築・クエリ・管理：

```bash
deeptutor kb create my-kb --doc textbook.pdf       # ドキュメントから作成
deeptutor kb add my-kb --docs-dir ./papers/         # 論文フォルダを追加
deeptutor kb search my-kb "gradient descent"        # 直接検索
deeptutor kb set-default my-kb                      # すべてのコマンドのデフォルトとして設定
```

**デュアル出力モード** — 人間向けリッチレンダリング、パイプライン向け構造化 JSON：

```bash
deeptutor run chat "Summarize chapter 3" -f rich    # カラー、フォーマット済み出力
deeptutor run chat "Summarize chapter 3" -f json    # 行区切り JSON イベント
```

**セッション継続性** — 中断したところから会話を再開：

```bash
deeptutor session list                              # すべてのセッションを表示
deeptutor session open <id>                         # REPL で再開
```

<details>
<summary><b>完全な CLI コマンドリファレンス</b></summary>

**トップレベル**

| コマンド | 説明 |
|:---|:---|
| `deeptutor run <capability> <message>` | 任意の機能を1ターンで実行（`chat`、`deep_solve`、`deep_question`、`deep_research`、`math_animator`、`visualize`） |
| `deeptutor chat` | オプション `--capability`、`--tool`、`--kb`、`--language` 付きインタラクティブ REPL |
| `deeptutor serve` | DeepTutor API サーバーを起動 |

**`deeptutor bot`**

| コマンド | 説明 |
|:---|:---|
| `deeptutor bot list` | すべての TutorBot インスタンスを表示 |
| `deeptutor bot create <id>` | 新しいボットを作成・起動（`--name`、`--persona`、`--model`） |
| `deeptutor bot start <id>` | ボットを起動 |
| `deeptutor bot stop <id>` | ボットを停止 |

**`deeptutor kb`**

| コマンド | 説明 |
|:---|:---|
| `deeptutor kb list` | すべてのナレッジベースを表示 |
| `deeptutor kb info <name>` | ナレッジベースの詳細を表示 |
| `deeptutor kb create <name>` | ドキュメントから作成（`--doc`、`--docs-dir`） |
| `deeptutor kb add <name>` | 段階的にドキュメントを追加 |
| `deeptutor kb search <name> <query>` | ナレッジベースを検索 |
| `deeptutor kb set-default <name>` | デフォルト KB として設定 |
| `deeptutor kb delete <name>` | ナレッジベースを削除（`--force`） |

**`deeptutor memory`**

| コマンド | 説明 |
|:---|:---|
| `deeptutor memory show [file]` | メモリを表示（`summary`、`profile`、`all`） |
| `deeptutor memory clear [file]` | メモリをクリア（`--force`） |

**`deeptutor session`**

| コマンド | 説明 |
|:---|:---|
| `deeptutor session list` | セッションを表示（`--limit`） |
| `deeptutor session show <id>` | セッションメッセージを表示 |
| `deeptutor session open <id>` | REPL でセッションを再開 |
| `deeptutor session rename <id>` | セッションを名前変更（`--title`） |
| `deeptutor session delete <id>` | セッションを削除 |

**`deeptutor notebook`**

| コマンド | 説明 |
|:---|:---|
| `deeptutor notebook list` | ノートブックを表示 |
| `deeptutor notebook create <name>` | ノートブックを作成（`--description`） |
| `deeptutor notebook show <id>` | ノートブックレコードを表示 |
| `deeptutor notebook add-md <id> <path>` | Markdown をレコードとしてインポート |
| `deeptutor notebook replace-md <id> <rec> <path>` | Markdown レコードを置換 |
| `deeptutor notebook remove-record <id> <rec>` | レコードを削除 |

**`deeptutor book`**

| コマンド | 説明 |
|:---|:---|
| `deeptutor book list` | ワークスペース内のすべての書籍を表示 |
| `deeptutor book health <book_id>` | KB ドリフトと書籍の健全性を確認 |
| `deeptutor book refresh-fingerprints <book_id>` | KB フィンガープリントを更新し古いページをクリア |

**`deeptutor config` / `plugin` / `provider`**

| コマンド | 説明 |
|:---|:---|
| `deeptutor config show` | 現在の設定サマリーを表示 |
| `deeptutor plugin list` | 登録されたツールと機能を表示 |
| `deeptutor plugin info <name>` | ツールまたは機能の詳細を表示 |
| `deeptutor provider login <provider>` | プロバイダー認証（`openai-codex` OAuth ログイン、`github-copilot` は既存の Copilot 認証セッションを検証） |

</details>

---

<a id="multi-user"></a>
### 👥 マルチユーザー — ユーザーごとのワークスペースを持つ共有デプロイ

<div align="center">
<img src="../../assets/figs/dt-multi-user.png" alt="マルチユーザー" width="800">
</div>

認証を有効にすると、DeepTutor は**ユーザーごとの独立ワークスペース**と**管理者によるリソースキュレーション**を持つマルチテナントデプロイに変わります。最初に登録した人が管理者となり、全員のためにモデル、API キー、ナレッジベースを設定します。その後のアカウントは管理者が作成（招待制）し、各ユーザーはスコープ付きのチャット履歴/メモリ/ノートブック/ナレッジベースを持ち、管理者が割り当てた LLM、KB、スキルのみにアクセス可能です。

**クイックスタート（5ステップ）：**

```bash
# 1. プロジェクトルートの .env で認証を有効化
echo 'AUTH_ENABLED=true' >> .env
# オプション — JWT 署名秘密鍵。空白の場合は最初の起動時に自動生成
echo 'AUTH_SECRET=<64文字以上のランダム文字を貼り付け>' >> .env

# 2. Web スタックを再起動 — start_web.py が AUTH_ENABLED をフロントエンドにミラー
python scripts/start_web.py

# 3. http://localhost:3782/register を開いて最初のアカウントを作成
#    最初の登録のみ公開、そのユーザーが管理者になり
#    /register エンドポイントは自動的に閉じられる

# 4. 管理者として /admin/users → 「ユーザーを追加」でチームメンバーのアカウントを作成

# 5. 各ユーザーのスライダーアイコンをクリック → LLM プロファイル、ナレッジベース、
#    スキルを割り当て → 保存。ユーザーはサインインして作業を開始できる
```

**管理者が見るもの：**

- `/settings` の**完全な設定ページ** — LLM/埋め込み/検索プロバイダー、API キー、モデルカタログ、ランタイム「適用」の管理。
- `/admin/users` の**ユーザー管理** — アカウントの作成、昇格、降格、削除。最初の管理者が存在したら公開 `/register` エンドポイントは閉じられ、以降のアカウントは `POST /api/v1/auth/users`（管理者専用）経由。
- **グラントエディター** — 非管理者ユーザーに使用するモデルプロファイル、ナレッジベース、スキルを選択。グラントは**論理 ID のみ**を保持し、API キーはグラント境界を越えません。
- **監査証跡** — すべてのグラント変更と割り当てリソースアクセスが `multi-user/_system/audit/usage.jsonl` に追記。

**一般ユーザーが得るもの：**

- `multi-user/<uid>/` 下の**独立ワークスペース** — 独自の `chat_history.db`、メモリ（`SUMMARY.md` / `PROFILE.md`）、ノートブック、個人ナレッジベース。デフォルトでは何も共有されない。
- 管理者が割り当てたナレッジベースとスキルへの**読み取り専用アクセス**、独自のリソースの横に「管理者が割り当て」バッジとともに表示。
- **削除済み設定ページ** — テーマ、言語、付与されたモデルのサマリーのみ。API キー、ベース URL、プロバイダーエンドポイントは非管理者リクエストには返されない。
- **スコープ付き LLM** — チャットターンは管理者が割り当てたモデルを通じてルーティング。LLM が付与されていない場合、ターンは事前に拒否（管理者のキーへのサイレントフォールバックなし）。

**ワークスペースレイアウト：**

```
multi-user/
├── _system/
│   ├── auth/users.json          # ハッシュ化された資格情報、ロール
│   ├── auth/auth_secret         # JWT 署名秘密鍵（自動生成）
│   ├── grants/<uid>.json        # ユーザーごとのリソースグラント（管理者管理）
│   └── audit/usage.jsonl        # 監査証跡
└── <uid>/
    ├── user/
    │   ├── chat_history.db
    │   ├── settings/interface.json
    │   └── workspace/{chat,co-writer,book,...}
    ├── memory/{SUMMARY.md,PROFILE.md}
    └── knowledge_bases/...
```

**設定リファレンス：**

| 変数 | 必須 | 説明 |
|:---|:---|:---|
| `AUTH_ENABLED` | Yes | `true` でマルチユーザー認証を有効化。デフォルト `false`（シングルユーザーモード）。 |
| `AUTH_SECRET` | 推奨 | JWT 署名秘密鍵。空白の場合は `multi-user/_system/auth/auth_secret` に自動生成。 |
| `AUTH_TOKEN_EXPIRE_HOURS` | No | JWT の有効期限、デフォルト `24` 時間。 |
| `AUTH_USERNAME` / `AUTH_PASSWORD_HASH` | No | シングルユーザーフォールバック資格情報（レガシーの環境変数パス）。マルチユーザー時は空白のままにしてください。 |
| `NEXT_PUBLIC_AUTH_ENABLED` | 自動 | `start_web.py` が `AUTH_ENABLED` からミラーし、Next.js ミドルウェアが未認証リクエストを `/login` にリダイレクト。 |

> ⚠️ **PocketBase モード（`POCKETBASE_URL` 設定済み）はシングルユーザーのみ対応。** デフォルトの PocketBase スキーマには `users` に `role` フィールドがなく（すべてのログインが `role=user` になり、管理者を作成できない）、`sessions` / `messages` / `turns` クエリが `user_id` でフィルタリングされていません。マルチユーザーデプロイは `POCKETBASE_URL` を空白のままにしてデフォルトの JSON/SQLite バックエンドを使用してください。

> ⚠️ **シングルプロセス推奨。** 最初のユーザーの管理者昇格はプロセス内 `threading.Lock` で保護されています。マルチワーカーデプロイは最初の管理者をオフラインでプロビジョニングする（`AUTH_ENABLED=false` で起動してブートストラップフローを完了してからフラグを切り替え）か、外部システムでユーザーストアをバックアップしてください。

<a id="roadmap"></a>
## 🗺️ ロードマップ

| ステータス | マイルストーン |
|:---:|:---|
| 🎯 | **認証とログイン** — 公開デプロイ向けのオプションログインページとマルチユーザーサポート |
| 🎯 | **テーマと外観** — 多様なテーマオプションとカスタマイズ可能な UI 外観 |
| 🎯 | **インタラクション改善** — アイコンデザインとインタラクション詳細の最適化 |
| 🔜 | **より良いメモリ** — より優れたメモリ管理の統合 |
| 🔜 | **LightRAG 統合** — [LightRAG](https://github.com/HKUDS/LightRAG) を高度なナレッジベースエンジンとして統合 |
| 🔜 | **ドキュメントサイト** — ガイド、API リファレンス、チュートリアルを含む総合ドキュメントページ |

> DeepTutor が役立つと感じたら、[スターを付けてください](https://github.com/HKUDS/DeepTutor/stargazers) — 継続の励みになります！

---

<a id="community"></a>
## 🌐 コミュニティとエコシステム

DeepTutor は優れたオープンソースプロジェクトの肩の上に立っています：

| プロジェクト | DeepTutor での役割 |
|:---|:---|
| [**nanobot**](https://github.com/HKUDS/nanobot) | TutorBot を動かす超軽量エージェントエンジン |
| [**LlamaIndex**](https://github.com/run-llama/llama_index) | RAG パイプラインとドキュメントインデックスのバックボーン |
| [**ManimCat**](https://github.com/Wing900/ManimCat) | Math Animator 向けの AI 駆動数学アニメーション生成 |

**HKUDS エコシステムから：**

| [⚡ LightRAG](https://github.com/HKUDS/LightRAG) | [🤖 AutoAgent](https://github.com/HKUDS/AutoAgent) | [🔬 AI-Researcher](https://github.com/HKUDS/AI-Researcher) | [🧬 nanobot](https://github.com/HKUDS/nanobot) |
|:---:|:---:|:---:|:---:|
| シンプル＆高速 RAG | ゼロコードエージェントフレームワーク | 自動化研究 | 超軽量 AI エージェント |


## 🤝 コントリビューション

<div align="center">

DeepTutor がコミュニティへの贈り物になることを願っています。🎁

<a href="https://github.com/HKUDS/DeepTutor/graphs/contributors">
  <img src="https://contrib.rocks/image?repo=HKUDS/DeepTutor&max=999" alt="Contributors" />
</a>

</div>

開発環境のセットアップ、コーディング規約、プルリクエストワークフローのガイドラインは [CONTRIBUTING.md](../../CONTRIBUTING.md) をご覧ください。

## ⭐ スター履歴

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

[⭐ スターを付ける](https://github.com/HKUDS/DeepTutor/stargazers) · [🐛 バグを報告](https://github.com/HKUDS/DeepTutor/issues) · [💬 ディスカッション](https://github.com/HKUDS/DeepTutor/discussions)

---

[Apache License 2.0](../../LICENSE) の下でライセンス。

<p>
  <img src="https://visitor-badge.laobi.icu/badge?page_id=HKUDS.DeepTutor&style=for-the-badge&color=00d4ff" alt="Views">
</p>

</div>
