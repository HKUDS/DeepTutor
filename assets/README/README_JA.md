<div align="center">

<p align="center"><img src="../../assets/figs/logo/logo.png" alt="DeepTutor ロゴ" height="56" style="vertical-align: middle;">&nbsp;<img src="../../assets/figs/logo/banner.png" alt="DeepTutor" height="48" style="vertical-align: middle;"></p>

# DeepTutor：生涯にわたるパーソナライズド個別指導

<p align="center">
  <a href="https://deeptutor.info" target="_blank"><img alt="Docs — deeptutor.info" src="https://img.shields.io/badge/Docs-deeptutor.info%20%E2%86%97-0A0A0A?style=for-the-badge&labelColor=F5F5F4" height="36"></a>
</p>

<p align="center">
  <a href="https://trendshift.io/repositories/17099?utm_source=repository-badge&amp;utm_medium=badge&amp;utm_campaign=badge-repository-17099" target="_blank" rel="noopener noreferrer"><img src="https://trendshift.io/api/badge/repositories/17099" alt="HKUDS%2FDeepTutor | Trendshift" width="250" height="55"/></a>&nbsp;
  <a href="https://trendshift.io/repositories/17099?utm_source=trendshift-badge&amp;utm_medium=badge&amp;utm_campaign=badge-trendshift-17099" target="_blank" rel="noopener noreferrer"><img src="https://trendshift.io/api/badge/trendshift/repositories/17099/daily" alt="HKUDS%2FDeepTutor | Trendshift" width="250" height="55"/></a>&nbsp;
  <a href="https://trendshift.io/repositories/17099?utm_source=trendshift-badge&amp;utm_medium=badge&amp;utm_campaign=badge-trendshift-17099" target="_blank" rel="noopener noreferrer"><img src="https://trendshift.io/api/badge/trendshift/repositories/17099/weekly?language=Python" alt="HKUDS%2FDeepTutor | Trendshift" width="250" height="55"/></a>
</p>

<p align="center">
  <a href="../../README.md"><img alt="English" height="40" src="https://img.shields.io/badge/English-CDCFD4"></a>&nbsp;
  <a href="README_CN.md"><img alt="简体中文" height="40" src="https://img.shields.io/badge/简体中文-CDCFD4"></a>&nbsp;
  <a href="README_JA.md"><img alt="日本語" height="40" src="https://img.shields.io/badge/日本語-BCDCF7"></a>&nbsp;
  <a href="README_ES.md"><img alt="Español" height="40" src="https://img.shields.io/badge/Español-CDCFD4"></a>&nbsp;
  <a href="README_FR.md"><img alt="Français" height="40" src="https://img.shields.io/badge/Français-CDCFD4"></a>&nbsp;
  <a href="README_AR.md"><img alt="Arabic" height="40" src="https://img.shields.io/badge/Arabic-CDCFD4"></a>&nbsp;
  <a href="README_RU.md"><img alt="Русский" height="40" src="https://img.shields.io/badge/Русский-CDCFD4"></a>&nbsp;
  <a href="README_HI.md"><img alt="Hindi" height="40" src="https://img.shields.io/badge/Hindi-CDCFD4"></a>&nbsp;
  <a href="README_PT.md"><img alt="Português" height="40" src="https://img.shields.io/badge/Português-CDCFD4"></a>&nbsp;
  <a href="README_TH.md"><img alt="Thai" height="40" src="https://img.shields.io/badge/Thai-CDCFD4"></a>&nbsp;
  <a href="README_PL.md"><img alt="Polski" height="40" src="https://img.shields.io/badge/Polski-CDCFD4"></a>
</p>

[![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-3776AB?style=flat-square&logo=python&logoColor=white)](https://www.python.org/downloads/)
[![Next.js 16](https://img.shields.io/badge/Next.js-16-000000?style=flat-square&logo=next.js&logoColor=white)](https://nextjs.org/)
[![License](https://img.shields.io/badge/License-Apache_2.0-blue?style=flat-square)](../../LICENSE)
[![GitHub release](https://img.shields.io/github/v/release/HKUDS/DeepTutor?style=flat-square&color=brightgreen)](https://github.com/HKUDS/DeepTutor/releases)
[![arXiv](https://img.shields.io/badge/arXiv-2604.26962-b31b1b?style=flat-square&logo=arxiv&logoColor=white)](https://arxiv.org/abs/2604.26962)

[![Discord](https://img.shields.io/badge/Discord-Community-5865F2?style=flat-square&logo=discord&logoColor=white)](https://discord.gg/eRsjPgMU4t)
[![Feishu](https://img.shields.io/badge/Feishu-Group-00D4AA?style=flat-square&logo=feishu&logoColor=white)](../../Communication.md)
[![WeChat](https://img.shields.io/badge/WeChat-Group-07C160?style=flat-square&logo=wechat&logoColor=white)](https://github.com/HKUDS/DeepTutor/issues/78)

[機能](#-主な機能) · [はじめに](#-はじめに) · [探索](#-deeptuitorを探索する) · [CLI](#%EF%B8%8F-deeptutor-cli--エージェントネイティブインターフェース) · [エコシステム](#-エコシステム--eduhubとスキルコミュニティ) · [コミュニティ](#-コミュニティ)

</div>

---

> 🤝 **あらゆる形の貢献を歓迎します！** [`ロードマップ`](https://github.com/HKUDS/DeepTutor/issues/498) でアイテムに投票したり新しいアイデアを提案したりできます。ブランチ戦略、コーディング基準、参加方法については [貢献ガイド](../../CONTRIBUTING.md) をご覧ください。

### 📰 ニュース

- **2026-05-22** 🌐 公式ドキュメントサイトが [**deeptutor.info**](https://deeptutor.info/) で公開 — ガイド、リファレンス、機能ツアーを一か所に。
- **2026-04-19** 🎉 111日間で20kスター達成！真にパーソナライズされたインテリジェント個別指導に向けた支援に感謝します。
- **2026-04-10** 📄 arXivに論文を公開 — DeepTutorの設計とアイデアについては[プレプリント](https://arxiv.org/abs/2604.26962)をご覧ください。
- **2026-02-06** 🚀 わずか39日間で10kスター達成！素晴らしいコミュニティに心から感謝します。
- **2026-01-01** 🎊 あけましておめでとうございます！[Discord](https://discord.gg/eRsjPgMU4t)、[WeChat](https://github.com/HKUDS/DeepTutor/issues/78)、または[Discussions](https://github.com/HKUDS/DeepTutor/discussions)に参加して一緒にDeepTutorを形作りましょう。
- **2025-12-29** 🎓 DeepTutor正式リリース！

## ✨ 主な機能

DeepTutorは、個別指導、問題解決、クイズ生成、研究、ビジュアライゼーション、習熟度練習を1つの拡張可能なシステムに統合したエージェントネイティブな学習ワークスペースです。

- **すべてのモードで1つのランタイム** — Chat、Quiz、Research、Visualize、Solve、Mastery Pathが同じエージェントループで実行されるため、エンジンではなく目的を切り替えます。コンテキストは学習者とともに移動します。
- **接続された学習コンテキスト** — 知識ベース、本、Co-Writerの下書き、ノートブック、問題バンク、ペルソナ、Memoryが孤立したツールに閉じ込められることなく、すべてのワークフローで利用可能です。
- **サブエージェントとPartners** — 任意のターンからライブのClaude Code、Codex、またはPartnerに相談（または過去の会話をインポート）し、同じブレインで永続的なIMコンパニオンを実行します。
- **マルチエンジン知識** — LlamaIndex、PageIndex、GraphRAG、LightRAG、またはリンクされたObsidianボールトにまたがるバージョン管理されたRAGライブラリ（プラグ可能なドキュメント解析付き）。
- **拡張可能なツールとスキル** — 組み込みツール、MCPサーバー、画像/ビデオ/音声生成モデル、EduHubからインストール可能なコミュニティスキル。
- **検査可能なメモリ** — L1トレース、L2サーフェスサマリー、L3合成によりパーソナライズが可視化・編集可能となり、Memory Graphですべての主張を証拠まで追跡できます。

---

## 🚀 はじめに

DeepTutorは4つのインストールパスを提供しています。すべてのパスは同じワークスペースレイアウトを共有します。設定はデプロイするディレクトリ下の`data/user/settings/`に保存されます（明示的に設定した場合は`DEEPTUTOR_HOME`/`deeptutor start --home`の下）。完全なアプリの場合は **ワークスペースディレクトリの選択 → インストール → `deeptutor init` → `deeptutor start`** がお勧めのフローです。

<details>
<summary><b>オプション1 — PyPIからインストール</b> · クローン不要のフルローカルWebアプリ + CLI</summary>

クローン不要のフルローカルWebアプリ + CLI。**Python 3.11+** とPATH上の**Node.js 20+**ランタイムが必要です（パッケージ済みのNext.jsスタンドアロンサーバーは`deeptutor start`によって起動されます）。

```bash
mkdir -p my-deeptutor && cd my-deeptutor
pip install -U deeptutor
deeptutor init     # ポート + LLMプロバイダー + オプション埋め込みを設定
deeptutor start    # バックエンド + フロントエンドを起動; ターミナルを開いたまま
```

`deeptutor init`はバックエンドポート（デフォルト`8001`）、フロントエンドポート（デフォルト`3782`）、LLMプロバイダー / ベースURL / APIキー / モデル、およびKnowledge Base / RAG用のオプション埋め込みプロバイダーを設定します。

`deeptutor start`後、ターミナルに出力されたフロントエンドURLを開いてください（デフォルトは[http://127.0.0.1:3782](http://127.0.0.1:3782)）。そのターミナルで`Ctrl+C`を押すとバックエンドとフロントエンドが両方停止します。手軽に試すために`deeptutor init`をスキップしても問題ありません。アプリはデフォルトのポートと空のモデル設定で起動し、後から**Settings → Models**で設定できます。

</details>

<details>
<summary><b>オプション2 — ソースからインストール</b> · チェックアウトに対して開発</summary>

チェックアウトに対して開発する場合。CIとDockerに合わせて**Python 3.11+**と**Node.js 22 LTS**を使用してください。

```bash
git clone https://github.com/HKUDS/DeepTutor.git
cd DeepTutor

# venvを作成(macOS/Linux)。Windows PowerShell:
#   py -3.11 -m venv .venv ; .\.venv\Scripts\Activate.ps1
python3 -m venv .venv && source .venv/bin/activate
python -m pip install --upgrade pip

# バックエンド + フロントエンドの依存関係をインストール
python -m pip install -e .
( cd web && npm ci --legacy-peer-deps )

deeptutor init
deeptutor start
```

ソースインストールはローカルの`web/`ディレクトリに対してNext.jsをdevモードで実行します。その他（設定レイアウト、ポート、`Ctrl+C`での停止）はオプション1と同じです。

<details>
<summary><b>Conda環境</b>（<code>venv</code>の代わり）</summary>

```bash
conda create -n deeptutor python=3.11
conda activate deeptutor
python -m pip install --upgrade pip
```

</details>

<details>
<summary><b>オプションインストールエクストラ</b> — dev / partners / matrix / math-animator</summary>

```bash
pip install -e ".[dev]"             # テスト/lintツール
pip install -e ".[partners]"        # Partner IMチャンネルSDK + MCPクライアント
pip install -e ".[matrix]"          # MatrixチャンネルE2EE/libolmなし
pip install -e ".[matrix-e2e]"      # Matrix E2EE; libolmが必要
pip install -e ".[math-animator]"   # Maninアドオン; LaTeX/ffmpeg/システムライブラリが必要
```

</details>

<details>
<summary><b>フロントエンド依存関係の調整とdevサーバーのトラブルシューティング</b></summary>

**フロントエンド依存関係の変更：** `npm install --legacy-peer-deps`を実行して`web/package-lock.json`を更新し、`web/package.json`と`web/package-lock.json`の両方をコミットしてください。

**devサーバーが動かない場合：** `deeptutor start`が応答しない既存のフロントエンドを報告する場合は、表示されたPIDを停止してください。実際にNext.jsプロセスが実行されていない場合、ロックファイルが古くなっています — それらを削除して再試行してください：

```bash
rm -f web/.next/dev/lock web/.next/lock
deeptutor start
```

</details>

</details>

<details>
<summary><b>オプション3 — Docker</b> · 自己完結型コンテナ1つ</summary>

フルWebアプリ用のコンテナ1つ。GitHub Container Registryのイメージ：

- `ghcr.io/hkuds/deeptutor:latest` — 安定版リリース
- `ghcr.io/hkuds/deeptutor:pre` — プレリリース（利用可能な場合）

> ポッドマン/rootless/読み取り専用rootfsデプロイメントと完全なインストール別ガイドについては [CONTAINERIZATION.md](../../CONTAINERIZATION.md) を参照してください。

```bash
docker run --rm --name deeptutor \
  -p 127.0.0.1:3782:3782 \
  -v deeptutor-data:/app/data \
  ghcr.io/hkuds/deeptutor:latest
```

> **公開が必要なのは`3782`のみです。** ブラウザはフロントエンドオリジンのみと通信し、Next.jsミドルウェア（`web/proxy.ts`）が`/api/*`と`/ws/*`をコンテナ**内部の**FastAPIバックエンドに転送します。`8001`を公開（`-p 127.0.0.1:8001:8001`）するのはオプションで、curlやスクリプトでAPIに直接アクセスする場合にのみ便利です。

[http://127.0.0.1:3782](http://127.0.0.1:3782)を開いてください。コンテナは初回起動時に`/app/data/user/settings/*.json`を作成します。Web Settingsページからモデルプロバイダーを設定してください。設定、APIキー、ログ、ワークスペースファイル、メモリ、知識ベースは`deeptutor-data`ボリュームに永続化されます。

- **異なるホストポート：** 各`-p host:container`マッピングの左側を変更してください（例：`-p 127.0.0.1:8088:3782`）。`/app/data/user/settings/system.json`のコンテナ側ポートを変更する場合は、再起動して各マッピングの右側を一致するよう更新してください。
- **デタッチ：** `-d`を追加し、`docker logs -f deeptutor`でログを追跡、`docker stop deeptutor`で停止、名前を再利用する前に`docker rm deeptutor`を実行。`deeptutor-data`ボリュームは再起動をまたいで設定とワークスペースを保持します。

**リモートDocker / リバースプロキシ：** ブラウザはフロントエンドオリジン（`:3782`）のみと通信します。コンテナ内のNext.jsミドルウェアが`/api/*`と`/ws/*`をバックエンドサーバーサイドに転送します。一般的な単一コンテナの場合、APIベースをまったく設定しません — リバースプロキシ/TLS終端を`:3782`に向けるだけです。APIベースが必要なのは**分割デプロイメント**（バックエンドが別のコンテナ/ホスト）のみです：`data/user/settings/system.json`の`next_public_api_base`をフロントエンドサーバーがバックエンドに到達するためのネットワーク内アドレスに設定してください（サーバーサイドで読み取られ、ブラウザには送信されません）。

```json
{
  "next_public_api_base": "http://backend:8001"
}
```

`next_public_api_base_external`（およびそのエイリアス`public_api_base`）は低優先度のフォールバックとして受け入れられます。CORSはAPIのURLではなくフロントエンドの**オリジン**を使用します。認証が無効の場合、DeepTutorはデフォルトで通常のHTTP/HTTPSブラウザオリジンを許可します。認証が有効の場合、正確なフロントエンドオリジンを追加してください：

```json
{
  "cors_origins": ["https://deeptutor.example.com"]
}
```

<details>
<summary><b>ホスト上のOllama / LM Studio / llama.cpp / vLLM / Lemonadeへの接続</b></summary>

Docker内では、`localhost`はホストマシンではなくコンテナ自体です。ホスト上で実行中のモデルサービスに接続するには、ホストゲートウェイ（推奨）を使用してください：

```bash
docker run --rm --name deeptutor \
  -p 127.0.0.1:3782:3782 -p 127.0.0.1:8001:8001 \
  --add-host=host.docker.internal:host-gateway \
  -v deeptutor-data:/app/data \
  ghcr.io/hkuds/deeptutor:latest
```

**Settings → Models**でプロバイダーのBase URLを`host.docker.internal`に向けてください：

- Ollama LLM: `http://host.docker.internal:11434/v1`
- Ollama embedding: `http://host.docker.internal:11434/api/embed`
- LM Studio: `http://host.docker.internal:1234/v1`
- llama.cpp: `http://host.docker.internal:8080/v1`
- Lemonade: `http://host.docker.internal:13305/api/v1`

Docker Desktop（macOS/Windows）は通常`--add-host`なしで`host.docker.internal`を解決します。Linuxでは、このフラグが最新のDocker Engineでそのホスト名を作成するポータブルな方法です。

**Linuxの代替 — ホストネットワーキング：** `--network=host`を追加して`-p`フラグを削除します。コンテナはホストネットワークを直接共有するため、[http://127.0.0.1:3782](http://127.0.0.1:3782)（または`system.json`の`frontend_port`）を開き、ホストサービスには`http://127.0.0.1:11434/v1`のような通常のlocalhostのURLでアクセスできます。ホストネットワーキングはコンテナのポートをホスト上に直接公開し、既存のサービスと競合する可能性があります — それらをループバックに保つには`BACKEND_HOST=127.0.0.1`と`FRONTEND_HOST=127.0.0.1`を設定してください（[CONTAINERIZATION.md](../../CONTAINERIZATION.md)参照）。

</details>

</details>

<details>
<summary><b>オプション4 — CLIのみ</b> · ソースチェックアウトからWeb UIなし</summary>

Web UIが不要な場合。CLIのみのパッケージはPyPIからではなく、ソースチェックアウトからインストールします。

```bash
git clone https://github.com/HKUDS/DeepTutor.git
cd DeepTutor

# venvを作成(macOS/Linux)。Windows PowerShell:
#   py -3.11 -m venv .venv-cli ; .\.venv-cli\Scripts\Activate.ps1
python3 -m venv .venv-cli && source .venv-cli/bin/activate
python -m pip install --upgrade pip

python -m pip install -e ./packaging/deeptutor-cli
deeptutor init --cli
deeptutor chat
```

`deeptutor init --cli`はフルアプリと同じ`data/user/settings/`レイアウトを共有しますが、バックエンド/フロントエンドのポートプロンプトをスキップし、埋め込みをデフォルトで**オフ**にします（`deeptutor kb …`やRAGツールを使用する予定がある場合は`Yes`を選択してください）。完全なランタイムレイアウト（`system.json`、`auth.json`、`integrations.json`、`model_catalog.json`、`main.yaml`、`agents.yaml`）を書き込み、アクティブなLLMプロバイダーとモデルのプロンプトも表示します。

<details>
<summary><b>よく使うコマンド</b></summary>

```bash
deeptutor chat                                          # インタラクティブREPL
deeptutor chat --capability deep_solve --tool rag --kb my-kb
deeptutor run chat "Explain Fourier transform"
deeptutor run deep_solve "Solve x^2 = 4" --tool rag --kb my-kb
deeptutor kb create my-kb --doc textbook.pdf
deeptutor memory show
deeptutor config show
```

</details>

ローカルの`deeptutor-cli`インストールにはWebアセットやサーバー依存関係がありません。ソースチェックアウトはそのままにしておいてください — 編集可能インストールはそれを参照します。後からWebアプリを追加するには、PyPIパッケージ（オプション1）をインストールして、同じワークスペースから`deeptutor init` + `deeptutor start`を実行してください。

</details>

<details>
<summary><b>コード実行サンドボックス（オフィススキル）</b> · docx / pdf / pptx / xlsx 用にモデル生成コードを実行</summary>

組み込みオフィススキル — **docx / pdf / pptx / xlsx** — は、モデルが短いPythonスクリプト（`python-docx`、`reportlab`、`openpyxl`など）を書き、`exec` / `code_execution`ツールで実行し、ダウンロードURLを返すことで機能します。これらのツールはサンドボックスバックエンドがアクティブなときにマウントされ、すべてのデプロイメント形態でデフォルトでアクティブです：

- **ローカル（オプション1/2）とDocker（オプション3、単一コンテナ）：** 制限付きサブプロセスサンドボックスがモデルのコードを実行します（ローカルではホスト上、Dockerでは独自の隔離境界であるコンテナ内）。
- **docker-compose：** `DEEPTUTOR_SANDBOX_RUNNER_URL`経由でハードニングされた最小権限の**ランナーサイドカー**（`Dockerfile.runner`）にルーティングされます — 最も強固な姿勢であり、利用可能な場合は自動的に優先されます。

サブプロセスサンドボックスは`data/user/settings/system.json`の`sandbox_allow_subprocess`設定で制御されます（デフォルト`true`）。ホスト上でモデル生成コードを実行することは実際の信頼上の決定です — ホスト側実行を無効にするには`false`に設定するか（または`DEEPTUTOR_SANDBOX_ALLOW_SUBPROCESS=0`をエクスポート）、オフィススキルがファイルを生成できなくなることに注意してください。

</details>

<details>
<summary><b>設定リファレンス</b> — <code>data/user/settings/</code>下の設定ファイル（JSON/YAML）</summary>

`data/user/settings/`以下のものはすべてプレーンなJSON/YAMLです。ブラウザの**Settings**ページが推奨エディターです。

| ファイル | 目的 |
|:---|:---|
| `model_catalog.json` | LLM、埋め込み、検索プロバイダープロフィール；APIキー；アクティブモデル |
| `system.json` | バックエンド/フロントエンドポート、公開APIベース、CORS、SSL検証、添付ファイルディレクトリ |
| `auth.json` | オプション認証トグル、ユーザー名、パスワードハッシュ、トークン/クッキー設定 |
| `integrations.json` | オプションのPocketBaseとサイドカー統合設定 |
| `interface.json` | UIの言語/テーマ/サイドバー設定 |
| `main.yaml` | ランタイム動作のデフォルトとパス注入 |
| `agents.yaml` | 機能/ツールのtemperatureとトークン設定 |

プロジェクトルートの`.env`はアプリケーション設定ファイルとして**読み込まれません**。最小限のモデル設定では、**Settings → Models**を開き、LLMプロフィール（ベースURL / APIキー / モデル名）を追加して保存してください。Knowledge Base / RAG機能を使用する予定がある場合のみ埋め込みプロフィールを追加してください。

</details>

## 📖 DeepTutorを探索する

日常的に使用するメインサーフェスから始めましょう：Chat、Partners、My Agents、Co-Writer、Book、Knowledge Center、Learning Space、Memory、Settings。ツアーの最後はマルチユーザーデプロイメントとして共有・分離ワークスペースをカバーします。

<div align="center">
<img src="../../assets/figs/web-1.4.6+/OVERVIEW.png" alt="DeepTutorホーム — サイドバーにすべてのサーフェスを含むチャットワークスペース" width="900">
</div>

<details>
<summary><b>🏗️ システムアーキテクチャ</b></summary>

<div align="center">
<img src="../../assets/figs/system/system%20architecture.png" alt="DeepTutorシステムアーキテクチャ" width="900">
</div>

</details>

<details>
<summary><b>💬 Chat — 実際に使うエージェントループ</b></summary>

Chatはデフォルト機能であり、ほとんどの作業が始まる場所です。1つのスレッドで通常の会話、ツールの呼び出し、選択した知識ベースへのグラウンディング、添付ファイルの読み取り、画像生成、サブエージェントとの相談、ノートブックレコードの書き込みが可能で、ターンをまたいで同じコンテキストを維持します。

<div align="center">
<img src="../../assets/figs/web-1.4.6+/home/00-overview.png" alt="DeepTutorチャットワークスペース" width="900">
</div>

ループは意図的にシンプルです。モデルはラウンドで考え、役に立つときにツールを呼び出し、結果を観察し、ツールなしのメッセージで終了します。`ask_user`は特別で、推測する代わりに、エージェントはターンを一時停止し、構造化された明確化の質問をして、あなたが答えた後に再開できます。

<div align="center">
<img src="../../assets/figs/system/chat-agent-loop.png" alt="DeepTutorチャットエージェントループ" width="900">
</div>

ユーザーが切り替えられるツールは`brainstorm`、`web_search`、`paper_search`、`reason`、`geogebra_analysis` — 加えて、対応する生成モデルを設定すれば`imagegen`と`videogen`も利用できます。`rag`、`read_source`、`read_memory`、`write_memory`、`read_skill`、`load_tools`、`exec`、`web_fetch`、`ask_user`、`list_notebook`、`write_note`、`github`、`consult_subagent`などのコンテキスト依存ツールは、ターンに適切なコンテキストがある場合に自動的にマウントされます。

コンテキストには2種類あります：**スティッキーセッションコンテキスト**（サブエージェント、知識ベース、ペルソナ、モデル、音声）はコンポーザーツールバーに常駐し、ターンをまたいで持続します。**ワンタイム参照**（ファイル、チャット履歴、本、ノートブック、問題バンク、インポートしたエージェント）は単一のターンのために`+`メニューから追加します。

Chatはより深い機能へのローンチポイントでもあります：問題生成には**Quiz**、引用付きレポートには**Research**、チャート/図/アニメーションには**Visualize**、推論問題解決には**Solve**（「その他の機能」下）、学習計画フローには**Mastery Path**。

</details>

<details>
<summary><b>🤝 Partner — 同じブレインで動く永続コンパニオン</b></summary>

<div align="center">
<img src="../../assets/figs/web-1.4.6+/partners/00-partners%20overview.png" alt="DeepTutor Partnersワークスペース" width="900">
</div>

Partnersは独自のソウル、モデルポリシー、ライブラリ、メモリ、チャンネルを持つ永続コンパニオンです。別個のボットエンジンではありません。ウェブまたはIMからの受信メッセージは、パートナースコープのワークスペース内の通常の`ChatOrchestrator`ターンになります。Partnerは「個性を持ったチャットであり、電話番号を持っている」存在です。

<div align="center">
<img src="../../assets/figs/system/partners-architecture.png" alt="DeepTutor Partnersアーキテクチャ" width="900">
</div>

各Partnerには`SOUL.md`、モデル選択、チャンネル、ツールポリシー、割り当てられたライブラリがあります。知識ベース、スキル、ノートブックは`data/partners/<id>/workspace/`にコピーされるため、同じRAG、スキル、ノートブック、メモリツールが特別なケースなしに機能します。Partnerはオーナーのメモリを読み取れますが、自分自身のメモリにのみ書き込めます。

<div align="center">
<img src="../../assets/figs/web-1.4.6+/partners/02-IM%20config%20for%20each%20partner.png" alt="Partner ごとのIMチャンネル設定" width="900">
</div>

チャンネル層はスキーマ駆動で、インストール済みエクストラと設定された認証情報に応じて、Feishu、Telegram、Slack、Discord、DingTalk、QQ/NapCat、WeCom、WhatsApp、Zulip、Mattermost、Matrix、Mochat、Microsoft Teamsなどのプラットフォームに接続できます。PartnerはサブエージェントとしてMy Agentsに接続でき、通常のチャットターンから相談できます。詳細は以下の**My Agents**を参照してください。

</details>

<details>
<summary><b>🧑‍🚀 My Agents — 他のエージェントと相談・インポート</b></summary>

<div align="center">
<img src="../../assets/figs/web-1.4.6+/myagents/00-overview.png" alt="DeepTutor My Agentsワークスペース" width="900">
</div>

My Agentsは他のエージェントをDeepTutorのコンテキストにし、2つの異なることを行います。**ライブエージェントを接続** — マシン上のClaude CodeやCodex CLI、またはPartnerの1つ — してチャットターン内から相談できます。DeepTutorは実際に他のエージェントを*実行*し、`consult_subagent`ツールを介してその作業をActivityパネルにストリーミングします。Agentチップ（または`@`入力）で選択し、相談で取れるラウンド数を設定します。

<div align="center">
<img src="../../assets/figs/web-1.4.6+/home/08-subagent%20demo%20with%20claude%20code.png" alt="Claude Codeサブエージェントをライブで相談" width="900">
</div>

**過去の会話をインポート** — 既存のClaude CodeやCodexの履歴を名前付き、検索可能、再開可能なエージェントとして取り込みます。インポートする日を選択してください。更新すると再同期されます。チャットターンから`+` → My Agentsでインポートした会話を参照でき、DeepTutorはそれをサードパーティのトランスクリプトとして読み取ります — それはDeepTutor自身の声ではなく、*相手の*会話として保持されます。

</details>

<details>
<summary><b>✍️ Co-Writer — 選択対応Markdownドラフトツール</b></summary>

<div align="center">
<img src="../../assets/figs/web-1.4.6+/co-writer/00-overview.png" alt="DeepTutor Co-Writerワークスペース" width="900">
</div>

Co-Writerはレポート、チュートリアル、メモ、長文学習コンテンツのための分割表示Markdownワークスペースです。ドキュメントは自動保存され、ライブプレビュー（KaTeXの数式、図表フェンス）を表示し、下書きが再利用可能なコンテキストになったときにノートブックに保存できます。

<div align="center">
<img src="../../assets/figs/web-1.4.6+/co-writer/01-edit%20panel.png" alt="Co-Writerエディターとライブプレビュー" width="900">
</div>

その定義的なアイデアは**外科的編集**です。テキストの範囲を選択し、DeepTutorに書き直し、拡張、または短縮を依頼します。編集エージェントは知識ベースまたはウェブの証拠に基づいて変更をグラウンドし、ツール呼び出しのトレースを保持し、各変更を承認/拒否の差分として表示します — あなたが承認するまで何も適用されません。

</details>

<details>
<summary><b>📖 Book — 素材から生きている本を作成</b></summary>

<div align="center">
<img src="../../assets/figs/web-1.4.6+/book/00-book_overview.png" alt="DeepTutor Bookライブラリ" width="900">
</div>

Bookは選択したソースをインタラクティブな**生きている本**に変換します。静的なPDFではなく、タイプ指定されたブロックから構築された読書環境です。知識ベース、ノートブック、問題バンク、チャット履歴から本を開始できます。作成フローではコンテンツが生成される前に章のアウトラインを提案するため、盲目的な一発生成を受け入れるのではなく、構造を確認できます。

<p align="center">
<img src="../../assets/figs/web-1.4.6+/book/01-book-demo-quiz%20card.png" alt="Bookクイズブロック" width="31%">
&nbsp;
<img src="../../assets/figs/web-1.4.6+/book/02-book-demo-manim%20video.png" alt="Book Maninアニメーションブロック" width="31%">
&nbsp;
<img src="../../assets/figs/web-1.4.6+/book/03-book-demo%20interactive%20module.png" alt="Bookインタラクティブウィジェットブロック" width="31%">
</p>

各章はタイプ指定されたブロックにコンパイルされます — テキスト、コールアウト、クイズ、フラッシュカード、タイムライン、コード、図、インタラクティブHTML、アニメーション、概念グラフ、詳細解説、ユーザーノート — 各ページには独自のPage Chatがあります。ブロックは編集可能です：章全体を書き直すことなく、挿入、移動、再生成、またはブロックの種類を変更できます。`deeptutor book health`や`deeptutor book refresh-fingerprints`などのメンテナンスコマンドは、ソース知識がコンパイル済みページからドリフトした場合に検出するのに役立ちます。

</details>

<details>
<summary><b>📚 Knowledge Center — マルチエンジンRAGライブラリ</b></summary>

<div align="center">
<img src="../../assets/figs/web-1.4.6+/knowledge/00-overview.png" alt="DeepTutor Knowledge Center" width="900">
</div>

知識ベースはRAGの背後にあるドキュメントコレクションです — Chatターン、Co-Writerの編集、Book生成、Partnerの会話をグラウンドします。特徴的なのは**検索エンジンの選択**です：**LlamaIndex**（デフォルト、ローカルベクター + BM25）、**PageIndex**（ホスト型、ページレベル引用付き推論検索）、**GraphRAG**と**LightRAG**（知識グラフ検索）、**LightRAG Server**（HTTP経由で接続する外部LightRAGインスタンスに検索をオフロード）、またはチューターがその場で読み書きするリンクされた**Obsidian**ボールト。各KBは1つのエンジンにバインドされます。

<div align="center">
<img src="../../assets/figs/web-1.4.6+/knowledge/01-create%20knowledge%20base.png" alt="知識ベースの作成" width="900">
</div>

KBを作成する際は、**新規作成**（ドキュメントをアップロードして新しいインデックスを構築）または**既存をリンク**（再インデックスなしで既に構築されたインデックスを再利用）を選択します。再インデックスは新しいフラットな`version-N`ディレクトリを書き込み、以前のものを保持するため、再構築中に作業中のインデックスが破壊されることはありません。解析に失敗したファイルを完全な削除・再構築なしで取り除けるよう、**error**状態のベースからでも単一のドキュメントを削除できます。ドキュメント解析（Text-only、MinerU、Docling、markitdown、PyMuPDF4LLM）は**Settings → Knowledge Base**で選択し、ローカルモデルのダウンロードはデフォルトでオフです。CLIは`deeptutor kb list`、`info`、`create`、`add`、`search`、`set-default`、`delete`でライフサイクルをミラーします。

</details>

<details>
<summary><b>🌐 Learning Space — スキル、ペルソナ、再利用可能なコンテキスト</b></summary>

<div align="center">
<img src="../../assets/figs/web-1.4.6+/learning-space/00-overview.png" alt="DeepTutor Learning Spaceハブ" width="900">
</div>

Learning Spaceはライブラリとパーソナライゼーション層です — 永続するものが置かれる場所です。**会話と素材**にはチャット履歴、ノートブック、問題バンク（各保存された質問にはあなたの回答、参照回答、説明が含まれます）が含まれます。**パーソナライゼーション**には習熟パス、ペルソナ（*peer*、*research-assistant*、*teacher*などの動作プリセット）、スキル（モデルがオンデマンドで読み取る`SKILL.md`プレイブック）が含まれます。ここのものはすべてChat、Partners、Co-Writer、Bookから再利用できます。

<div align="center">
<img src="../../assets/figs/web-1.4.6+/learning-space/07-%20download%20skills%20from%20eduhub.png" alt="EduHubからスキルをインポート" width="900">
</div>

すべてのスキルを自分で書く必要はありません。**EduHubからインポート**でコミュニティカタログを参照し、セキュリティゲートを通じてスキルをライブラリに直接ダウンロードできます（[エコシステム](#-エコシステム--eduhubとスキルコミュニティ)参照）。

</details>

<details>
<summary><b>🧠 Memory — 検査可能なパーソナライゼーション</b></summary>

<div align="center">
<img src="../../assets/figs/web-1.4.6+/memory/00-overview.png" alt="DeepTutor Memoryの概要" width="900">
</div>

Memoryはファイルバックの3層システムで、読み取り、キュレーション、監査が可能です — 意図的に隠されたベクターストアではありません。**L1**はワークスペースミラーに加えた追記のみのイベントトレース（`trace/<surface>/<date>.jsonl`）、**L2**はサーフェスごとのキュレートされた事実（`L2/<surface>.md`）、**L3**はクロスサーフェス合成（`L3/<profile|recent|scope|preferences>.md`）です。L2はL1を引用し、L3はL2を引用するため、プロフィールの何も説明不能なものはありません。

<div align="center">
<img src="../../assets/figs/web-1.4.6+/memory/01-3%20layer%20memory%20graph.png" alt="DeepTutor Memoryグラフ" width="900">
</div>

Memory Graphはピラミッド全体を表示します — L3合成が中心、L2が中間リング、L1トレースが外側 — どんな合成された主張も背後にある正確な生のイベントまで追跡できます。Memoryは`chat`、`notebook`、`quiz`、`kb`、`book`、partner、`cowriter`サーフェスで追跡されます。コンソリデーターのUpdate / Audit / Dedupバジェットは**Settings → Memory**で調整します。

</details>

<details>
<summary><b>⚙️ Settings — ワンコントロールプレーン</b></summary>

<div align="center">
<img src="../../assets/figs/web-1.4.6+/settings/00-setting%20overview.png" alt="DeepTutor Settingsハブ" width="900">
</div>

Settingsはオペレーションコントロールプレーンで、ライブステータスストリップ（バックエンド、LLM、埋め込み、検索）とエリアごとのカードがあります：**外観**（テーマ + UI言語）、**ネットワーク**（APIベース、ポート、CORS）、**モデル**（LLM、埋め込み、検索、TTS、STT、画像生成、動画生成）、**Knowledge Base**（ドキュメント解析エンジン）、**Chat**（ツール、MCPサーバー、機能パラメーター）、**Partners & Agents**（ターンから相談できるサブエージェント）、**Memory**（コンソリデーターのバジェット）。

<div align="center">
<img src="../../assets/figs/web-1.4.6+/settings/01-appearance%20settings.png" alt="DeepTutor外観設定とテーマ" width="900">
</div>

ほとんどのセクションはドラフトと適用フローを使用するため、コミットする前にプロバイダーをテストできます。4つのテーマが箱に入っています：Default、Cream、Dark、Glass。プロジェクトルートの`.env`ファイルは意図的に無視されます。ランタイム設定は`DEEPTUTOR_HOME`または`deeptutor start --home`でアプリを別の場所に向けない限り、`data/user/settings/*.json`に保存されます。

</details>

<details>
<summary><b>👥 マルチユーザー — 共有デプロイメント</b> · オプション認証、分離されたユーザーワークスペース</summary>

認証はデフォルトで**オフ**です — DeepTutorはシングルユーザーで動作します。オンにすると、1つの`data/`ツリーで管理者ワークスペース、分離されたユーザーワークスペース、Partnerワークスペースが同居します：

```text
data/
├── user/                    # 管理者ワークスペース + グローバル設定
├── users/<uid>/             # ユーザー単位スコープ：チャット履歴、メモリ、ノートブック、KB
├── partners/<id>/workspace/ # Partner（合成ユーザー）スコープ
└── system/                  # auth/users.json · grants/<uid>.json · audit/usage.jsonl
```

**最初に登録したユーザーが管理者**になり、モデルカタログ、プロバイダー認証情報、共有知識ベース、スキル、ユーザー単位グラントを所有します。それ以外のユーザーは分離されたワークスペースと編集されたSettingsページを取得します — 管理者が割り当てたモデル、KB、スキルはスコープ付きの読み取り専用オプションとして表示され、生のAPIキーは見えません。

**有効化：** `data/user/settings/auth.json`で認証をオンにし、`deeptutor start`を再起動し、`/register`で最初の管理者を登録し、`/admin/users`からユーザーを追加し、グラントを通じてモデル、KB、スキル、Partner、ツール/MCPポリシー、コード実行アクセスを割り当てます。

> PocketBaseはシングルユーザー統合のままです — 外部ユーザーストアを組み込まない限り、マルチユーザーデプロイメントでは`integrations.pocketbase_url`を空白にしてください。

</details>

## ⌨️ DeepTutor CLI — エージェントネイティブインターフェース

1つの`deeptutor`バイナリで2つの使い方：ターミナルで生活する人のためのインタラクティブな**REPL**と、DeepTutorをツールとして動かす他のエージェントのための構造化された**JSON**。同じ機能、ツール、知識ベースがどちらでも利用できます。

<details>
<summary><b>自分で操作する</b></summary>

`deeptutor chat`でインタラクティブなREPLを開きます。`deeptutor run <capability> "<message>"`で1回のターンを実行して終了します。どちらも同じ`--capability`、`--tool`、`--kb`、`--config`フラグを使用します。

```bash
deeptutor chat                                              # インタラクティブREPL
deeptutor chat --capability deep_solve --kb my-kb --tool rag
deeptutor run chat "Explain the Fourier transform" --tool rag --kb textbook
deeptutor run deep_research "Survey 2026 papers on RAG" \
  --config mode=report --config depth=standard
```

Webアプリのすべてもここにあります — 知識ベース（`kb`）、セッション（`session`）、パートナー（`partner`）、スキル（`skill`）、ノートブック、メモリ、設定。全リストは以下を参照。

</details>

<details>
<summary><b>エージェントに操作させる</b></summary>

DeepTutorは*別のエージェントによって操作される*ように設計されています。任意の`run`に`--format json`を追加すると、各ターンが**NDJSON — 1行1イベント**（`content`、`tool_call`、`tool_result`、`done`など）としてストリームされ、各行が`session_id`でタグ付けされます。実行はヘッドレスセーフです：TTYなしの`ask_user`一時停止は、ハングする代わりに空の応答で自動解決されます。

```bash
# 1回実行、マシン読み取り可能
deeptutor run deep_solve "Find d/dx[sin(x^2)]" --tool reason --format json

# 1つのステートフルセッションでターンを連鎖 — IDをキャプチャして再利用
SID=$(deeptutor run deep_research "Survey 2026 papers on RAG" \
  --config mode=report --config depth=standard --format json \
  | jq -r 'select(.type=="done").session_id')
deeptutor run deep_question "Quiz me on that survey" --session "$SID" --format json
```

リポジトリにはルートの[`SKILL.md`](../../SKILL.md)が含まれています — ツール使用可能なLLMにサーフェス全体を1回の読み取りで教える約150行のハンドオーバードキュメント。Claude Code、Codex、OpenCodeに渡してください（これらは`SKILL.md`を自動的に取得します）、または`deeptutor run`をLangChain / AutoGenループのツールとしてラップしてください。完全なレシピ：[Agent Handoff](https://deeptutor.info/docs/cli/agent-handoff/)。

</details>

<details>
<summary><b>コマンドリファレンス</b></summary>

| コマンド | 説明 |
|:---|:---|
| `deeptutor init` | 現在のワークスペースの`data/user/settings`を作成または更新 |
| `deeptutor start [--home PATH]` | バックエンド + フロントエンドを一緒に起動 |
| `deeptutor serve [--port PORT]` | FastAPIバックエンドのみ起動 |
| `deeptutor run <capability> <message>` | 単一機能ターンを実行（`chat`、`deep_solve`、`deep_question`、`deep_research`、`visualize`、`math_animator`、`mastery_path`）；`--format json`でNDJSON出力 |
| `deeptutor chat` | 機能、ツール、KB、ノートブック、履歴コントロール付きインタラクティブREPL |
| `deeptutor partner list/create/start/stop` | IM接続Partnersを管理 |
| `deeptutor kb list/info/create/add/search/set-default/delete` | LlamaIndex知識ベースを管理 |
| `deeptutor skill search/install/list/remove/login/logout/publish/update` | スキルを管理、ハブからインストール、自分のスキルを公開（デフォルトは`eduhub:<slug>`、エコシステム参照） |
| `deeptutor memory show/clear` | L2/L3メモリドキュメントを検査またはL1/全メモリをクリア |
| `deeptutor session list/show/open/rename/delete` | 共有セッションを管理 |
| `deeptutor notebook list/create/show/add-md/replace-md/remove-record` | Markdownファイルからノートブックを管理 |
| `deeptutor book list/health/refresh-fingerprints` | 本を検査してソースフィンガープリントを更新 |
| `deeptutor plugin list/info` | 登録済みツールと機能を検査 |
| `deeptutor config show` | 設定サマリーを出力 |
| `deeptutor provider login <provider>` | プロバイダー認証（`openai-codex` OAuthログイン；`github-copilot`は既存のCopilot認証セッションを検証） |

</details>

<details>
<summary><b>CLIのみのディストリビューション</b></summary>

CLIのみのパッケージは`packaging/deeptutor-cli`にあります。このチェックアウトから、ソースからインストールしてください：

```bash
python -m pip install -e ./packaging/deeptutor-cli
```

まだPyPIには公開されていないため、メインの[はじめに](#-はじめに)セクションにはソースインストールのパスが記載されています。

</details>

## 🧩 エコシステム — EduHubとスキルコミュニティ

DeepTutorスキルはオープンな**Agent-Skills**フォーマットを使用します — `SKILL.md`プレイブック（YAMLフロントマター + Markdown）と任意の参照ファイルを含むフォルダです。これはDeepTutor固有のものではないため、このフォーマットを話すどんなレジストリもあなたのライブラリのソースになります。DeepTutorには**[EduHub](https://eduhub.deeptutor.info/)** — 独自の教育特化スキルレジストリ — がデフォルトハブとして組み込まれています。

<details>
<summary><b>EduHub — DeepTutorのスキルエコシステム</b></summary>

[**EduHub**](https://eduhub.deeptutor.info/)は、DeepTutorが教育指向のエージェントスキルを共有するために立ち上げたコミュニティハブです — ソクラテス式チューター、フラッシュカードビルダー、エッセイフィードバック、試験ブループリント、概念説明者など。DeepTutorに組み込まれているため、設定不要です：ベアスラッグまたは`eduhub:`プレフィックスでそこに解決されます。

**検索とインストール** — ブラウザで**Learning Space → スキル → EduHubからインポート**を開いてカタログを参照し、スキルをライブラリに直接ダウンロードできます。ターミナルから：

```bash
deeptutor skill search "socratic tutor"               # EduHubを検索（デフォルトハブ）
deeptutor skill install socratic-tutor                # 取得 → 検証 → 登録
deeptutor skill install eduhub:socratic-tutor@1.2.0   # ハブとバージョンを指定
deeptutor skill list                                  # ハブの出所付きローカルスキル
```

**自分のスキルを公開** — `SKILL.md`をパッケージ化してコミュニティに共有：

```bash
deeptutor skill login                                 # EduHubへのブラウザサインイン
deeptutor skill publish ./my-skill                    # インタラクティブ：トラック + タグを選択してアップロード
deeptutor skill update                                # ロールバックまたは新バージョンをリリース
```

EduHubはまたスタンドアロンのClawHub互換レジストリでもあり、DeepTutor以外のエージェント（Claude Code、Codexなど）が`eduhub` CLI経由で直接使用できます — `npx eduhub install socratic-tutor`。

</details>

<details>
<summary><b>インポートセキュリティゲート</b></summary>

ソースに関わらず、すべてのインポートはワークスペースに触れる前に**同じセキュリティゲート**を通過します：

- レジストリの**セキュリティ判定**が最初にチェックされます — フラグが立てられたパッケージは`--allow-unverified`を渡さない限り拒否されます；
- アーカイブはテキスト/スクリプト**サフィックスホワイトリスト**の後ろで防御的に展開されます（zip-slip / zip-bombガード）、バイナリはワークスペースに入れません；
- フロントマターはDeepTutorのスキーマに正規化され、`always:`が**削除**されるため、ダウンロードしたスキルはすべてのシステムプロンプトに自分自身を強制できません；
- 出所 — ハブ、バージョン、判定、インストール時間 — が監査と更新のために`.hub-lock.json`に記録されます。

マルチユーザーデプロイメントでは、インストールは管理者のみです：新しいスキルは管理者カタログに入り、グラントが割り当てるまで他のユーザーには見えません。管理者はロールアウトする前にそれを審査できます。

</details>

<details>
<summary><b>ClawHubとも互換性あり</b></summary>

DeepTutorはオープンなAgent-Skillsフォーマットに対応しているため、**[ClawHub](https://clawhub.ai/)**も一流のソースとして機能します — EduHubとともに組み込まれています。ハブプレフィックスで選択：

```bash
deeptutor skill search "git release notes" --hub clawhub
deeptutor skill install clawhub:git-release-notes@1.0.1
```

`settings/skill_hubs.json`にさらにレジストリを追加できます：`type: "clawhub"`エントリは互換性のあるHTTP APIを指し（EduHubとClawHubはどちらもそれを話します）、`type: "command"`はレジストリが配布するフェッチCLIをラップし、`"default"`はベアスラッグに使用するハブを選択します。すべて同じインポートゲートを通過します。

</details>

## 🌐 コミュニティ

### 📮 連絡先

DeepTutorは[Bingxi Zhao](https://github.com/pancacake)が[HKUDS](https://github.com/HKUDS)グループ内でリードするオープンソースプロジェクトで、**完全にオープンソースの形で**コミュニティと共に反復されています。現在、**いかなる有料オンライン製品も存在しません**。議論、アイデア、協力については**bingxizhao39@gmail.com**までお気軽にご連絡ください。

### 🙏 感謝

[**Chao Huang**](https://sites.google.com/view/chaoh)（HKUデータインテリジェンスラボディレクター）、HKUDSのラボメイト — 特に[**Jiahao Zhang**](https://github.com/zzhtx258)、[**Zirui Guo**](https://github.com/LarFii)、[**Xubin Ren**](https://github.com/Re-bin) — の温かいサポートに心から感謝します。また、毎日DeepTutorを形作ってくれる**オープンソースコミュニティ**にも深く感謝します：あなたたちのスター、Issue、プルリクエスト、ディスカッションがDeepTutorを形作っています。

DeepTutorは優れたオープンソースプロジェクトの肩の上に立っています。ツールとインスピレーションの両方を与えてくれた以下のプロジェクトに深く感謝します：

| プロジェクト | 役割 / インスピレーション |
|:---|:---|
| [**LlamaIndex**](https://github.com/run-llama/llama_index) | RAGパイプラインとドキュメントインデックスのバックボーン |
| [**nanobot**](https://github.com/HKUDS/nanobot) | オリジナルTutorBotを動かした超軽量エージェントエンジン *(HKUDS)* |
| [**LightRAG**](https://github.com/HKUDS/LightRAG) | シンプルで高速なRAG *(HKUDS)* |
| [**AutoAgent**](https://github.com/HKUDS/AutoAgent) | ゼロコードエージェントフレームワーク *(HKUDS)* |
| [**AI-Researcher**](https://github.com/HKUDS/AI-Researcher) | 自動化研究パイプライン *(HKUDS)* |
| [**OpenClaw**](https://github.com/openclaw/openclaw) | ClawHubの背後にあるオープンエージェントゲートウェイとスキルエコシステム |
| [**Codex**](https://github.com/openai/codex) | CLIワークフローにインスピレーションを与えたエージェントネイティブコーディングCLI |
| [**Claude Code**](https://github.com/anthropics/claude-code) | DeepTutorエージェントループにインスピレーションを与えたエージェントコーディングCLI |
| [**ManimCat**](https://github.com/Wing900/ManimCat) | Math AnimatorのためのAI駆動数学アニメーション生成 |

### 🗺️ ロードマップと貢献

DeepTutorが反復し改善し続け、最終的にオープンソースコミュニティへのギフトになることを望んでいます。[**ロードマップ**](https://github.com/HKUDS/DeepTutor/issues/498)は継続的に更新されています。アイテムに投票したり新しいものを提案したりできます。貢献したい方は、ブランチ戦略、コーディング基準、参加方法について[**貢献ガイド**](../../CONTRIBUTING.md)をご覧ください。

<div align="center">

DeepTutorがコミュニティへのギフトになることを願っています。 🎁

<a href="https://github.com/HKUDS/DeepTutor/graphs/contributors">
  <img src="https://contrib.rocks/image?repo=HKUDS/DeepTutor&max=999" alt="Contributors" />
</a>

</div>

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

[Apache License 2.0](../../LICENSE)に基づきライセンス。

<p>
  <img src="https://visitor-badge.laobi.icu/badge?page_id=HKUDS.DeepTutor&style=for-the-badge&color=00d4ff" alt="Views">
</p>

</div>
