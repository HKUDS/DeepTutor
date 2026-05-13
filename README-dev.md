# DeepTutor 开发者快速上手指南

这份文档面向首次参与 **DeepTutor** 开发、调试或提交 PR 的开发者，重点覆盖本地开发环境、常用命令、代码结构和提交流程。若你只想快速运行项目，优先参考主文档 `README.md`；若你要修改代码、排查问题或参与贡献，建议先读完本页。

## 1. 项目概览

DeepTutor 是一个 **agent-native** 的智能学习平台，提供三类主要入口：

- **CLI**：`deeptutor`
- **Web / API**：FastAPI + WebSocket，统一入口为 `/api/v1/ws`
- **Python SDK**：复用统一运行时

核心运行时由 `ChatOrchestrator` 负责，将请求路由到默认 `chat` 能力或其他深层 Capability。

### 核心分层

| 层级 | 目录 / 组件 | 作用 |
| --- | --- | --- |
| Entry Points | `deeptutor_cli/`、`deeptutor/api/` | CLI、Web/API 入口 |
| Runtime | `deeptutor/runtime/` | 编排、注册表、模式切换 |
| Capabilities | `deeptutor/capabilities/` | 多阶段 Agent 能力，如 `chat`、`deep_solve`、`deep_question` |
| Tools | `deeptutor/tools/` | RAG、联网搜索、代码执行、推理等可调用工具 |
| Services | `deeptutor/services/` | 配置、会话、知识库、认证、模型接入等服务层 |
| Web Frontend | `web/` | Next.js 16 + React 19 前端 |
| Tests | `tests/` | Python 测试，按模块分目录组织 |

### 你最常会接触的目录

```text
deeptutor/
  api/             # FastAPI 路由、WebSocket、HTTP 接口
  runtime/         # ChatOrchestrator、工具/能力注册
  capabilities/    # 多步骤能力实现
  tools/           # 内置工具封装
  services/        # 配置、会话、知识库、认证等
deeptutor_cli/     # Typer CLI 入口与子命令
web/               # Next.js 前端
scripts/           # 启停、引导安装、更新脚本
tests/             # 后端测试
```

## 2. 开发环境要求

开始前请确保本机具备以下环境：

| 依赖 | 最低版本 | 用途 |
| --- | --- | --- |
| Python | 3.11+ | 后端、CLI、测试 |
| Node.js | 20.9+ | 前端开发 |
| npm | 与 Node.js 配套 | 前端依赖管理 |
| Git | 任意较新版本 | 拉取代码、提交 PR |

如果你在 Windows 上缺少本地编译环境，主文档建议安装 Visual Studio Build Tools，并勾选 **Desktop development with C++**。

## 3. 5 分钟开发环境启动

### 方式 A：推荐的引导式安装

首次参与开发、还没有 `.env` 时，最省事的方式是运行向导：

```bash
git clone https://github.com/HKUDS/DeepTutor.git
cd DeepTutor

python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip

python scripts/start_tour.py
```

`start_tour.py` 会帮助你：

- 检查 Python / Node.js / npm
- 安装 Python 与前端依赖
- 生成或更新 `.env`
- 选择安装档位（Web / TutorBot / Matrix / Math Animator）

安装完成后直接启动：

```bash
python scripts/start_web.py
```

该命令会同时启动后端和前端，并在终端输出访问地址。

### 方式 B：手动安装（更适合开发者）

如果你希望明确控制依赖与命令，使用下面的方式：

```bash
git clone https://github.com/HKUDS/DeepTutor.git
cd DeepTutor

python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip

# 后端 + API + 开发工具
python -m pip install -e ".[dev]"

# 前端依赖
cd web
npm install
cd ..

# 复制环境变量模板
cp .env.example .env
```

最少需要在 `.env` 中配置一组可用的 LLM；如果要开发知识库 / RAG 功能，还需要补充 Embedding 配置。不了解配置项时，可重新运行：

```bash
python scripts/start_tour.py
```

## 4. 本地启动方式

### 一键启动前后端

```bash
python scripts/start_web.py
```

- 默认同时拉起后端和前端
- 若上次异常退出残留了状态文件，可用 `python scripts/stop_web.py` 清理

### 分开启动（推荐用于调试）

**终端 1：后端**

```bash
source .venv/bin/activate
deeptutor serve --reload
```

**终端 2：前端**

```bash
cd web
npm run dev
```

默认端口通常是：

| 服务 | 默认端口 |
| --- | --- |
| Backend | `8001` |
| Frontend | `3782` |

### CLI 调试

```bash
deeptutor chat
deeptutor run chat "Explain Fourier transform"
deeptutor run deep_solve "Solve x^2=4" -t rag --kb my-kb
deeptutor plugin list
deeptutor config show
```

## 5. 常用开发命令

### Python / 后端

```bash
# 安装开发依赖
python -m pip install -e ".[dev]"

# 启动 API（热重载）
deeptutor serve --reload

# 运行测试
pytest
```

### Frontend

```bash
cd web

# 本地开发
npm run dev

# 生产构建检查
npm run build

# ESLint
npm run lint

# Node 侧测试
npm run test:node

# i18n 一致性检查
npm run i18n:check
```

### 统一质量检查

仓库已经配置了 `pre-commit`，建议第一次安装后启用：

```bash
pre-commit install
pre-commit run --all-files
```

当前仓库主要会执行：

- `ruff` / `ruff-format`
- `prettier`
- `detect-secrets`
- `bandit`
- `mypy`
- 基础文件格式校验（YAML / JSON / TOML / EOF / whitespace）

## 6. 依赖档位说明

`pyproject.toml` 中使用可选依赖分层，常见组合如下：

| 安装方式 | 说明 |
| --- | --- |
| `.[cli]` | CLI + RAG + 文档解析 + 常见模型 SDK |
| `.[server]` | `.[cli]` + FastAPI / uvicorn / WebSocket |
| `.[tutorbot]` | `.[server]` + TutorBot 与渠道 SDK |
| `.[matrix]` | Matrix 渠道支持 |
| `.[math-animator]` | Manim 动画能力 |
| `.[dev]` | `.[server]` + 测试与质量工具 |
| `.[all]` | 全量依赖 |

通常：

- **只开发后端 / Web**：`.[dev]`
- **还要调 TutorBot**：`.[tutorbot]`
- **要体验全部能力**：`.[all]`

## 7. 修改代码时的建议入口

根据你要改的内容，可以优先从这些位置开始：

| 目标 | 建议先看 |
| --- | --- |
| CLI 命令行为 | `deeptutor_cli/main.py` 与对应子命令文件 |
| 会话编排 / 路由 | `deeptutor/runtime/orchestrator.py` |
| WebSocket 协议 | `deeptutor/api/routers/unified_ws.py` |
| 工具注册与调用 | `deeptutor/runtime/registry/`、`deeptutor/tools/` |
| Capability 流程 | `deeptutor/capabilities/` |
| 前端页面与状态 | `web/app/`、`web/components/`、`web/features/` |
| 配置与启动脚本 | `scripts/`、`deeptutor/services/config/` |

## 8. 提交流程

提交前建议遵循仓库现有约定：

1. 从目标开发分支拉取最新代码，通常是 `dev`
2. 新建功能分支，例如 `feature/xxx` 或 `fix/xxx`
3. 完成功能后运行质量检查
4. 提交 PR 到正确分支，不要直接提交到 `main`

分支建议以 `CONTRIBUTING.md` 为准：

- 默认目标分支：`dev`
- 多用户 / 多租户相关改动：`multi-user`

提交信息推荐格式：

```text
<type>: <short description>
```

常见类型：`feat`、`fix`、`docs`、`refactor`、`test`、`chore`

## 9. 常见问题

### Node.js 版本过低

DeepTutor Web 需要 **Node.js >= 20.9.0**。如果版本过低，`start_tour.py` 会直接提示并终止安装。

### 前端或后端端口被占用

先确认是否有残留进程，再执行：

```bash
python scripts/stop_web.py
```

### 修改 `.env` 后没有生效

重新启动后端或重新执行：

```bash
python scripts/start_web.py
```

### 本地代码需要同步上游

仓库提供了保守更新脚本：

```bash
python scripts/update.py
```

它会先拉取远端、展示本地与远端差异，再执行安全的 fast-forward 更新。

## 10. 推荐的日常开发流

如果你已经完成一次初始化，后续大多数开发场景可以直接使用下面这组命令：

```bash
source .venv/bin/activate
deeptutor serve --reload
```

另开一个终端：

```bash
cd web
npm run dev
```

改完代码后执行：

```bash
pre-commit run --all-files
pytest
cd web && npm run lint
```

这套流程足以覆盖绝大部分后端、前端和接口联调工作。
