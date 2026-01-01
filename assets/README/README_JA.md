<div align="center">

<img src="../../assets/logo-ver2.png" alt="DeepTutor Logo" width="150" style="border-radius: 15px;">

# DeepTutor: あなたのパーソナル学習アシスタント

[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?style=flat-square&logo=python&logoColor=white)](https://www.python.org/downloads/)
[![Next.js](https://img.shields.io/badge/Next.js-14-000000?style=flat-square&logo=next.js&logoColor=white)](https://nextjs.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-009688?style=flat-square&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![License](https://img.shields.io/badge/License-AGPL--3.0-blue?style=flat-square)](LICENSE)
[![Feishu](https://img.shields.io/badge/Feishu-Group-blue?style=flat)](./Communication.md)
[![WeChat](https://img.shields.io/badge/WeChat-Group-green?style=flat&logo=wechat)](./Communication.md)



[**クイックスタート**](#クイックスタート) · [**コアモジュール**](#コアモジュール) · [**よくある質問**](#よくある質問)

[🇬🇧 English](../../README.md) · [🇨🇳 中文](README_CN.md) · [🇪🇸 Español](README_ES.md) · [🇫🇷 Français](README_FR.md) · [🇸🇦 العربية](README_AR.md) · [🇷🇺 Русский](README_RU.md) · [🇮🇳 हिन्दी](README_HI.md) · [🇵🇹 Português](README_PT.md)

</div>

<div align="center">

| ⚡ **大規模ドキュメント知識Q&A**  |  📈 **インタラクティブ学習可視化**  | <br>
| 🧠 **知識強化**  |  🔬 **深い研究とアイデア生成** |

</div>

---
> **[2026.1.1]** 新年あけましておめでとうございます！[GitHub Discussions](https://github.com/HKUDS/DeepTutor/discussions) に参加して、DeepTutor の未来を一緒に創りましょう！💬

> **[2025.12.30]** 詳細は [公式ウェブサイト](https://hkuds.github.io/DeepTutor/) をご覧ください！

> **[2025.12.29]** DeepTutor v0.1 がリリースされました！✨
---

## DeepTutor の主要機能

### 📚 大規模ドキュメント知識Q&A
• **スマート知識ベース**：教科書、研究論文、技術マニュアル、ドメイン固有のドキュメントをアップロード。包括的な AI 駆動の知識リポジトリを構築し、即座にアクセス可能にします。<br>
• **マルチエージェント問題解決**：RAG、ウェブ検索、論文検索、コード実行を統合したデュアルループ推論アーキテクチャ—正確な引用付きの段階的なソリューションを提供します。

### 🎨 インタラクティブ学習可視化
• **知識の簡素化と説明**：複雑な概念、知識、アルゴリズムを理解しやすい視覚補助、詳細な段階的分解、魅力的なインタラクティブデモンストレーションに変換します。<br>
• **パーソナライズされたQ&A**：学習の進捗に適応するコンテキスト対応の会話、インタラクティブページとセッションベースの知識追跡を提供します。

### 🎯 練習問題生成器による知識強化
• **インテリジェントな演習作成**：現在の知識レベルと特定の学習目標に合わせて、ターゲットを絞ったクイズ、練習問題、カスタマイズされた評価を生成します。<br>
• **本格的な試験シミュレーション**：参考試験をアップロードして、元のスタイル、形式、難易度に完全に一致する練習問題を生成—実際のテストのための現実的な準備を提供します。

### 🔍 深い研究とアイデア生成
• **包括的な研究と文献レビュー**：系統的な分析による深いトピック探索を実施。パターンを識別し、分野を超えた関連概念を接続し、既存の研究結果を統合します。<br>
• **新しい洞察の発見**：構造化された学習資料を生成し、知識のギャップを発見します。インテリジェントなクロスドメイン知識統合を通じて、有望な新しい研究方向を特定します。

---

<div align="center">
  <img src="../../assets/figs/title_gradient.svg" alt="All-in-One Tutoring System" width="70%">
</div>

<br>

<!-- ━━━━━━━━━━━━━━━━ Core Learning Experience ━━━━━━━━━━━━━━━━ -->

<table>
<tr>
<td width="50%" align="center" valign="top">

<h3>📚 大規模ドキュメント知識Q&A</h3>
<a href="#problem-solving-agent">
<img src="../../assets/gifs/solve.gif" width="100%">
</a>
<br>
<sub>正確な引用を伴うマルチエージェント問題解決</sub>

</td>
<td width="50%" align="center" valign="top">

<h3>🎨 インタラクティブ学習可視化</h3>
<a href="#guided-learning">
<img src="../../assets/gifs/guided-learning.gif" width="100%">
</a>
<br>
<sub>パーソナライズされたQ&Aを備えたステップバイステップの視覚的説明</sub>

</td>
</tr>
</table>

<!-- ━━━━━━━━━━━━━━━━ Practice & Reinforcement ━━━━━━━━━━━━━━━━ -->

<h3 align="center">🎯 知識強化</h3>

<table>
<tr>
<td width="50%" valign="top" align="center">

<a href="#question-generator">
<img src="../../assets/gifs/question-1.gif" width="100%">
</a>

**カスタム質問**  
<sub>自動検証された練習問題の生成</sub>

</td>
<td width="50%" valign="top" align="center">

<a href="#question-generator">
<img src="../../assets/gifs/question-2.gif" width="100%">
</a>

**模擬質問**  
<sub>本格的な練習のための試験スタイルのクローン</sub>

</td>
</tr>
</table>

<!-- ━━━━━━━━━━━━━━━━ Research & Creation ━━━━━━━━━━━━━━━━ -->

<h3 align="center">🔍 深い研究とアイデア生成</h3>

<table>
<tr>
<td width="33%" align="center">

<a href="#deep-research">
<img src="../../assets/gifs/deepresearch.gif" width="100%">
</a>

**深い研究**  
<sub>RAG、ウェブ、論文検索による教科書からの知識拡張</sub>

</td>
<td width="33%" align="center">

<a href="#idea-generation">
<img src="../../assets/gifs/ideagen.gif" width="100%">
</a>

**自動化されたアイデア生成**  
<sub>デュアルフィルターワークフローによる系統的なブレインストーミングと概念統合</sub>

</td>
<td width="33%" align="center">

<a href="#co-writer">
<img src="../../assets/gifs/co-writer.gif" width="100%">
</a>

**インタラクティブなアイデア生成**  
<sub>ポッドキャスト生成を備えたRAGとウェブ検索駆動のCo-Writer</sub>

</td>
</tr>
</table>

<!-- ━━━━━━━━━━━━━━━━ Knowledge Infrastructure ━━━━━━━━━━━━━━━━ -->

<h3 align="center">🏗️ オールインワン知識システム</h3>

<table>
<tr>
<td width="50%" align="center">

<a href="#dashboard--knowledge-base-management">
<img src="../../assets/gifs/knowledge_bases.png" width="100%">
</a>

**個人知識ベース**  
<sub>独自の知識リポジトリを構築・整理</sub>

</td>
<td width="50%" align="center">

<a href="#notebook">
<img src="../../assets/gifs/notebooks.png" width="100%">
</a>

**個人ノートブック**  
<sub>学習セッションのコンテキストメモリ</sub>

</td>
</tr>
</table>

<p align="center">
  <sub>🌙 <b>ダークモード</b> で DeepTutor を使用！</sub>
</p>

---

## 🏛️ DeepTutor のフレームワーク

<div align="center">
<img src="../../assets/figs/full-pipe.png" alt="DeepTutor Full-Stack Workflow" width="100%">
</div>

### 💬 ユーザーインターフェース層
• **直感的なインタラクション**：直感的なインタラクションのためのシンプルな双方向クエリ-レスポンスフロー。<br>
• **構造化された出力**：複雑な情報を実行可能な出力に整理する構造化レスポンス生成。

### 🤖 インテリジェントエージェントモジュール
• **問題解決と評価**：段階的な問題解決とカスタム評価生成。<br>
• **研究と学習**：トピック探索のための深い研究と可視化を備えたガイド付き学習。<br>
• **アイデア生成**：マルチソースの洞察を備えた自動化およびインタラクティブな概念開発。

### 🔧 ツール統合層
• **情報検索**：RAG ハイブリッド検索、リアルタイムウェブ検索、学術論文データベース。<br>
• **処理と分析**：Python コード実行、クエリ項目検索、ドキュメント分析のための PDF 解析。

### 🧠 知識とメモリ基盤
• **知識グラフ**：セマンティック接続と知識発見のためのエンティティ-関係マッピング。<br>
• **ベクトルストア**：インテリジェントなコンテンツ検索のための埋め込みベースのセマンティック検索。<br>
• **メモリシステム**：コンテキストの継続性のためのセッション状態管理と引用追跡。

## 📋 タスク

> 🌟 今後の更新をフォローするために Star してください！
- [ ] ローカル LLM サービスのサポート（例：ollama）
- [ ] RAG モジュールのリファクタリング（[Discussions](https://github.com/HKUDS/DeepTutor/discussions) を参照）
- [ ] アイデア生成からの深いコーディング
- [ ] ノートブックとのパーソナライズされたインタラクション

## 🚀 クイックスタート

### ステップ 1: リポジトリのクローンと仮想環境の作成

```bash
# リポジトリをクローン
git clone https://github.com/HKUDS/DeepTutor.git
cd DeepTutor

# 仮想環境を作成（方法を選択）

# オプション A: conda を使用（推奨）
conda create -n deeptutor python=3.10
conda activate deeptutor

# オプション B: venv を使用
python -m venv venv
# Windows:
venv\Scripts\activate
# macOS/Linux:
source venv/bin/activate
```

### ステップ 2: 依存関係をインストール

一鍵インストールスクリプトを実行して、すべての依存関係を自動インストール：

```bash
# 推奨：bash スクリプトを使用
bash scripts/install_all.sh

# または Python スクリプトを使用
python scripts/install_all.py

# 注：インストーラーは conda/venv の隔離環境を検出します。隔離環境が検出できない場合は警告を表示しますが、インストールは継続します。

# または手動でインストール
pip install -r requirements.txt
npm install
```

### ステップ 3: 環境変数を設定

プロジェクトのルートディレクトリに `.env.example` に基づいて `.env` ファイルを作成：

```bash
# .env.example テンプレートからコピー（存在する場合）
cp .env.example .env

# その後、.env ファイルを API キーで編集：
```

### ステップ 4: ポートを設定 *(オプション)*

デフォルトでは、アプリケーションは以下を使用：
- **バックエンド (FastAPI)**: `8001`
- **フロントエンド (Next.js)**: `3782`

`config/main.yaml` の `server.backend_port` および `server.frontend_port` 値を編集して、これらのポートを変更できます。

**LLM パラメータ**：すべてのエージェントの `temperature` と `max_tokens` 設定は `config/agents.yaml` に集中しています。各モジュール（guide、solve、research、question、ideagen、co_writer）には独自のパラメータセットがあります。詳細については[設定ドキュメント](config/README.md)を参照してください。

### ステップ 5: デモを使用 *(オプション)*

システムを素早く体験するために、2 つの前処理されたナレッジベースと、一連のチャレンジングな質問とユース例を提供しています。

<details>
<summary><b>研究論文集合</b> — 5 論文（各 20-50 ページ）</summary>

私たちのラボからの RAG と Agent フィールドの厳選された 5 つの研究論文。このデモは**幅広い知識カバレッジ**を持つ研究シナリオを表しています。

**使用論文**: [AI-Researcher](https://github.com/HKUDS/AI-Researcher) | [AutoAgent](https://github.com/HKUDS/AutoAgent) | [RAG-Anything](https://github.com/HKUDS/RAG-Anything) | [LightRAG](https://github.com/HKUDS/LightRAG) | [VideoRAG](https://github.com/HKUDS/VideoRAG)

</details>

<details>
<summary><b>データサイエンス教科書</b> — 8 章、296 ページ</summary>

包括的でチャレンジングなデータサイエンス教科書。このデモは**深い知識の深さ**を持つ学習シナリオを表しています。

**書籍リンク**: [Deep Representation Learning Book](https://ma-lab-berkeley.github.io/deep-representation-learning-book/)
</details>

<br>

**ダウンロードとセットアップ：**

1. デモパッケージをダウンロード: [Google Drive](https://drive.google.com/drive/folders/1iWwfZXiTuQKQqUYb5fGDZjLCeTUP6DA6?usp=sharing)
2. 圧縮ファイルを `data/` ディレクトリに直接抽出
3. プロジェクト開始後、ナレッジベースは自動的にシステムで利用可能

> **注意：** ナレッジベースを初期化する際、`text-embedding-3-large` を埋め込みモデルとして使用し、`dimensions = 3072` としています。埋め込みモデルの次元も 3072 であることを確認してください。

### ステップ 6: アプリケーションを開始

```bash
# 仮想環境が有効化されていることを確認
conda activate deeptutor  # または: source venv/bin/activate

# Web インターフェース（フロントエンド + バックエンド）を開始
python scripts/start_web.py

# または CLI インターフェースのみを開始
python scripts/start.py

# サービスを停止するには、Ctrl+C を押す
```

### ステップ 7: 独自のナレッジベースを作成

アプリケーション開始後、Web インターフェースを通じて独自のナレッジベースを作成できます。

1. **ナレッジベースページへアクセス**: http://localhost:{frontend_port}/knowledge にアクセス
2. **新規ナレッジベースを作成**: 「New Knowledge Base」ボタンをクリック
3. **ナレッジベースに名前を付ける**: ナレッジベースに一意の名前を入力
4. **ファイルをアップロード**: 1 つ以上のファイルをアップロード
5. **処理を待つ**: システムがファイルをバックグラウンドで自動処理
   - `start_web.py` を実行しているターミナルで作成進度を監視
   - 処理完了後、ナレッジベースが利用可能になる

> **ヒント：** 大きなファイルは処理に数分かかる場合があります。複数のファイルを一度にアップロードしてバッチ処理できます。

### アクセス URL

| サービス | URL | 説明 |
|:---:|:---|:---|
| **フロントエンド** | http://localhost:{frontend_port} | メイン Web インターフェース |
| **API ドキュメント** | http://localhost:{backend_port}/docs | インタラクティブ API ドキュメント |
| **ヘルスチェック** | http://localhost:{backend_port}/api/v1/knowledge/health | システムヘルスチェック |

---

## 📄 ライセンス

このプロジェクトは **[AGPL-3.0 ライセンス](LICENSE)** でライセンスされています。


## ⭐ Star History

<div align="center">
<a href="https://star-history.com/#HKUDS/DeepTutor&Date">
 <picture>
   <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/svg?repos=HKUDS/DeepTutor&type=Date&theme=dark" />
   <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/svg?repos=HKUDS/DeepTutor&type=Date" />
   <img alt="Star History Chart" src="https://api.star-history.com/svg?repos=HKUDS/DeepTutor&type=Date" />
 </picture>
</a>
</div>


## 🤝 貢献

コミュニティからの貢献を歓迎します！コード品質と一貫性を確保するため、以下のガイドラインに従ってください。

<details>
<summary><b>開発セットアップ</b></summary>

### Pre-commit Hooks セットアップ

このプロジェクトは **pre-commit hooks** を使用して、コミット前に自動的にコードをフォーマットし、問題をチェックします。

**ステップ 1: pre-commit をインストール**
```bash
# pip を使用
pip install pre-commit

# または conda を使用
conda install -c conda-forge pre-commit
```

**ステップ 2: Git hooks をインストール**
```bash
cd DeepTutor
pre-commit install
```

**ステップ 3: （オプション）すべてのファイルでチェックを実行**
```bash
pre-commit run --all-files
```

`git commit` を実行するたびに、pre-commit hooks は自動的に以下を行います：
- Ruff で Python コードをフォーマット
- Prettier でフロントエンドコードをフォーマット
- 構文エラーをチェック
- YAML/JSON ファイルを検証
- 潜在的なセキュリティ問題を検出

### コード品質ツール

| ツール | 目的 | 構成 |
|:---:|:---|:---:|
| **Ruff** | Python コード確認とフォーマット | `pyproject.toml` |
| **Prettier** | フロントエンドコード形式 | `web/.prettierrc.json` |
| **detect-secrets** | セキュリティチェック | `.secrets.baseline` |

> **注意**: プロジェクトはフォーマット競合を回避するため、Black の代わりに **Ruff format** を使用します。

### よく使うコマンド

```bash
# 通常のコミット（hooks が自動実行）
git commit -m "コミットメッセージ"

# すべてのファイルを手動でチェック
pre-commit run --all-files

# hooks を最新バージョンに更新
pre-commit autoupdate

# hooks をスキップ（推奨されません。緊急時のみ）
git commit --no-verify -m "緊急修正"
```

</details>

### 貢献ガイドライン

1. **Fork とクローン**: リポジトリを Fork してクローン
2. **ブランチを作成**: `main` からフィーチャーブランチを作成
3. **Pre-commit をインストール**: 上記セットアップステップに従う
4. **変更を実施**: プロジェクトのスタイルに従ってコードを記述
5. **テスト**: 変更が正しく機能することを確認
6. **コミット**: Pre-commit hooks が自動的にコードをフォーマット
7. **プッシュと PR**: Fork にプッシュして Pull Request を作成

### 問題を報告

- GitHub Issues を使用してバグを報告またはフィーチャーを提案
- 問題に関する詳細情報を提供
- バグの場合は、再現手順を含める

<div align="center">
<br>
❤️ すべての貢献者の貴重な貢献に感謝します。

</div>

## 🔗 関連プロジェクト

<div align="center">

| [⚡ LightRAG](https://github.com/HKUDS/LightRAG) | [🎨 RAG-Anything](https://github.com/HKUDS/RAG-Anything) | [💻 DeepCode](https://github.com/HKUDS/DeepCode) | [🔬 AI-Researcher](https://github.com/HKUDS/AI-Researcher) |
|:---:|:---:|:---:|:---:|
| シンプルで高速の RAG | マルチモーダル RAG | AI コードアシスタント | 研究自動化 |

**[香港大学データインテリジェンスラボ](https://github.com/HKUDS)**

[⭐ Star us](https://github.com/HKUDS/DeepTutor/stargazers) · [🐛 Report a bug](https://github.com/HKUDS/DeepTutor/issues) · [💬 Discussions](https://github.com/HKUDS/DeepTutor/discussions)

---
*✨ **DeepTutor** のご利用ありがとうございます！*

<img src="https://visitor-badge.laobi.icu/badge?page_id=HKUDS.DeepTutor&style=for-the-badge&color=00d4ff" alt="Views">

</div>
