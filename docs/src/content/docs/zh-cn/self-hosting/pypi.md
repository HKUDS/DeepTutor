---
title: 从 PyPI 安装
description: 说明模块化 full 安装与旧包迁移，并在升级时保留运行数据。
quadrant: how-to
---

本页介绍 **1.7.x** 模块化包（当前发布版本为 1.7.4）及从 **1.6.15** 旧布局迁移的方法。Web 应用选择 full 安装范围，终端聊天可只安装 core。要体验当前开发版功能，请[从源码安装](/zh-cn/self-hosting/source/)，或在独立环境构建、安装完整且版本一致的本地 wheel 家族。

1.6.15 完整包包含 Web 与 CLI。1.7.x 家族中，**`deeptutor` 提供 core CLI/SDK**，**`deeptutor-cli` 是兼容别名**，完整 Web 应用使用 **`deeptutor[full]`**。功能 wheel 必须与 core 同版本。当前开发环境使用 Python 3.11–3.14 与 Node.js 22 LTS。

## 安装

```bash
mkdir -p my-deeptutor && cd my-deeptutor
python -m pip install "deeptutor[full]==1.7.4"
deeptutor init     # 提示输入端口 + LLM 提供商 + 可选 embedding/search
deeptutor start    # 同时启动后端 + 前端；保持终端开着
```

`deeptutor init` 会询问：

- **后端端口**（默认 `8001`）
- **前端端口**（默认 `3782`）
- **LLM 提供商** / base URL / API key / 模型
- **可选 embedding 提供商**（用于 RAG / 知识库）
- **可选搜索提供商**（用于 Web Search）

`deeptutor start` 之后，打开终端里打印的前端地址 —— 默认是 <http://127.0.0.1:3782>。按 `Ctrl+C` 同时停掉后端和前端。

> 跳过 `deeptutor init` 也行，应用会以默认端口和空配置启动，之后可到 **设置 → 模型与服务** 配置 提供方、语言模型、Task Models、Embedding、Search、语音与多模态生成。

## 模块化包发布后的安装

使用 1.7.x wheel 家族时，在独立 wheel 环境选择所需的安装范围：

```bash
python -m pip install "deeptutor[full]==1.7.4"  # Web、CLI 与功能模块
# 或只安装 core：
python -m pip install "deeptutor==1.7.4"
```

迁移旧 `deeptutor-cli` 时，先停止应用、备份运行目录，并在安装新家族**之前**执行 `python -m pip uninstall deeptutor-cli`。旧 wheel 拥有新 core 需要的文件，一次性升级可能造成文件被删除。保留 `DEEPTUTOR_HOME`，重启前运行 `python -m pip check` 和 `deeptutor module list`。仅升级裸 core 不会保留完整应用安装范围。

## 试用预发布版本

普通 `pip install -U deeptutor` 只会停在稳定版 —— PyPI 默认跳过预发布版本（如 `1.X.0b0` 这类 beta），除非显式选择：

```bash
pip install --pre -U "deeptutor[full]"
# 或精确锁定某个版本：
pip install -U "deeptutor[full]==<version>"
```

## 可选 extras

已发布的 1.6.15 完整 wheel 包含 Web 与 CLI；1.7.x 家族改用 `[full]` 选择这些模块。附加能力按 extras 安装 —— 例如全部内置 Partner channel SDK（WeCom、QQ、Slack、飞书、Telegram、钉钉等）：

```bash
pip install -U "deeptutor[partners]"
```

完整 extras 总表（`matrix`、`matrix-e2e`、`math-animator`、`dev`、`all`）见 [**从源码安装**](/zh-cn/self-hosting/source/#可选的安装-extras) —— 同样的 extra 名对 PyPI 包同样有效。

## 文件存在哪里

工作区位于运行命令时所在的目录（首次启动会在那里创建 `data/` 目录）。覆盖位置：

```bash
DEEPTUTOR_HOME=/opt/deeptutor deeptutor start
# 或：
deeptutor start --home /opt/deeptutor
```

首次 init 后的目录结构：

```text
my-deeptutor/
└── data/
    ├── memory/
    └── user/
        ├── settings/
        │   ├── system.json
        │   ├── auth.json
        │   ├── integrations.json
        │   ├── interface.json
        │   ├── model_catalog.json
        │   ├── document_parsing.json
        │   ├── pageindex.json
        │   ├── ima.json
        │   ├── llamaindex.json
        │   ├── graphrag.json
        │   ├── lightrag.json
        │   ├── lightrag_server.json
        │   ├── main.yaml
        │   └── agents.yaml
        └── workspace/
```

各配置文件的含义在下面 [**配置参考**](#datausersettings-配置文件) 一节。

## 安装之后能直接用什么

不用离开工作区，随时进 CLI：

```bash
deeptutor chat                                          # 交互式 REPL
deeptutor run chat "解释一下傅里叶变换"                   # 单次执行
deeptutor kb create my-kb --doc textbook.pdf            # 建一个知识库
deeptutor memory show                                   # 查看记忆
deeptutor config show                                   # 查看当前配置
```

完整命令面：[**DeepTutor CLI**](/zh-cn/developers/guides/cli/)。

## 升级

```bash
pip install --upgrade "deeptutor[full]"
deeptutor start
```

工作区会在升级中保留。

浏览器里的 **设置 → 关于** 检查稳定版，但自动命令仅升级裸 core。完整模块化安装或从 1.6.15 迁移时，请停止应用并使用上面的 `[full]` 命令；先卸载旧 CLI 包。保留运行目录，用 `deeptutor module list` 检查结果。源码和 Docker 使用各自升级方式。

## `data/user/settings/` 配置文件

`data/user/settings/` 下的所有文件都是纯 JSON / YAML。浏览器里的 **设置** 页是推荐的编辑入口。

| 文件 | 用途 |
|------|------|
| `model_catalog.json` | Connections，以及 LLM、task、embedding、search、TTS、STT、图像与视频服务的 profiles |
| `document_parsing.json`、`pageindex.json`、`ima.json`、`llamaindex.json`、`graphrag.json`、`lightrag.json`、`lightrag_server.json` | 文档解析与知识库引擎设置 |
| `system.json` | 后端 / 前端端口、对外 API base、CORS、SSL 校验、附件目录与上传/提取上限 |
| `auth.json` | 可选的认证开关、用户名、密码哈希、token / cookie 设置 |
| `integrations.json` | 可选的 PocketBase 与 sidecar 集成设置 |
| `interface.json` | UI 语言与模型输出语言 / 主题 / 侧边栏偏好 |
| `main.yaml` | 运行时默认行为与路径注入 |
| `agents.yaml` | 各 capability / 工具的温度和 token 设置 |

> 项目根目录的 `.env` **不会** 被当作应用配置加载。建议从浏览器里的 **设置 → 模型与服务** 配置，或直接编辑 `model_catalog.json`。

## 常见错误

### macOS 上 `python: command not found`

```bash
python3 -m pip install -U "deeptutor[full]"
python3 -m deeptutor init   # 或者，如果 entry point 在 PATH 上，直接 `deeptutor init`
```

### Node.js 不在 PATH 上

`deeptutor start` 会拉起内置 Next.js 服务器，需要 PATH 上有 `node`。从 <https://nodejs.org> 装 Node 22 LTS，或 `brew install node@22`。

### 端口 `3782` 或 `8001` 被占用

```bash
lsof -i :3782          # macOS
ss -ltnp | grep :3782  # Linux
```

杀掉占用进程，或重跑 `deeptutor init` 改端口。

### LLM provider 401 Unauthorized

API key 被 provider 拒绝。在 **设置 → 语言模型** 重新输入，或：

```bash
deeptutor init   # 重跑向导，工作区会保留
```

更多问题：[**故障排查**](/zh-cn/self-hosting/troubleshooting/)。

## 下一步

- [**探索 DeepTutor**](/zh-cn/learning-workspace/) —— 看看跑起来的应用
- [**多用户部署**](/zh-cn/self-hosting/multi-user/) —— 部署成团队服务器
