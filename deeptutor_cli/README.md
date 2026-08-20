# DeepTutor CLI

Agent-first 的命令行界面。两条核心路径：

- **`run`** — 单次执行任意 capability（为 agent 调用设计）
- **`chat`** — 交互式 REPL（为人类设计）

## 安装

```bash
# 仅 CLI（本地源码安装，含 RAG / 文档解析 / 各家 LLM provider SDK）
git clone https://github.com/HKUDS/DeepTutor.git
cd DeepTutor
python3 -m venv .venv-cli
source .venv-cli/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ./packaging/deeptutor-cli
deeptutor init --cli

# CLI + Web/API 服务
pip install deeptutor
deeptutor init

# 源码开发
pip install -e .
deeptutor init

# 可选附加组件
pip install -e ".[partners]"       # Partners 渠道 SDK + MCP 客户端
pip install -e ".[math-animator]"  # 数学动画（另需系统 LaTeX/ffmpeg）
pip install -e ".[all]"            # 全部依赖（含开发工具）
```

`deeptutor init --cli` 和普通 `deeptutor init` 使用同一套 `data/user/settings/` 配置目录；区别是 `--cli` 不询问 Web 后端/前端端口，仍会创建 `system.json`、`auth.json`、`integrations.json`、`model_catalog.json`、`main.yaml` 和 `agents.yaml`，并继续询问 LLM 配置。Embedding 配置默认跳过；如果要使用 `deeptutor kb ...` 或 RAG，请在向导里选择配置 embedding，或稍后编辑 `data/user/settings/model_catalog.json`。

Windows PowerShell 可使用：

```powershell
py -3.11 -m venv .venv-cli
.\.venv-cli\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ./packaging/deeptutor-cli
deeptutor init --cli
```

---

## `run` — 执行 Capability

统一入口，单次执行任意 capability。Agent 只需掌握这一个命令。

```bash
deeptutor run <capability> <message> [options]
```

### 内置 Capability

| Capability | 说明 |
|------------|------|
| `chat` | 对话（默认，可挂载工具） |
| `deep_solve` | 多阶段深度解题 |
| `deep_question` | 智能出题 |
| `deep_research` | 多 agent 深度研究 |
| `visualize` | 生成图表、图解、Mermaid、HTML 或 Manim 可视化 |
| `math_animator` | 数学动画生成 |
| `mastery_path` | 掌握式学习路径与测评循环 |

### 选项

| 选项 | 缩写 | 说明 |
|------|------|------|
| `--tool` | `-t` | 启用工具（可多次指定）：`rag`, `web_search`, `code_execution`, `reason`, `brainstorm`, `paper_search`, `geogebra_analysis`, `imagegen`, `videogen` |
| `--kb` | | 挂载知识库 |
| `--language` | `-l` | 回复语言（默认 `en`） |
| `--session` | | 继续已有会话 |
| `--config` | | capability 配置 `key=value`（可多次指定） |
| `--config-json` | | capability 配置（JSON 字符串） |
| `--notebook-ref` | | 笔记本引用 |
| `--history-ref` | | 引用历史会话 |
| `--format` | `-f` | 输出格式：`rich`（默认）\| `json` |

### 示例

```bash
# 对话
deeptutor run chat "什么是傅里叶变换？" -l zh

# 深度解题
deeptutor run deep_solve "证明 n^3-n 能被 6 整除" -t rag --kb math-textbook

# 简要回答
deeptutor run deep_solve "求 sin(x) 的导数" --config detailed_answer=false

# 智能出题
deeptutor run deep_question "线性代数" --config num_questions=5 --config difficulty=hard

# 仿真出题
deeptutor run deep_question "模拟考试" --config mode=mimic --config paper_path=exam.json

# 深度研究
deeptutor run deep_research "Transformer 最新进展" \
  --config-json '{"mode":"report","depth":"deep","sources":["web","papers"]}'

# 可视化
deeptutor run visualize "画出注意力机制的数据流图" --config render_mode=mermaid

# 数学动画
deeptutor run math_animator "展示正弦函数变换" --config quality=high

# 掌握式学习
deeptutor run mastery_path "带我系统掌握特征值和特征向量"

# JSON 输出（适合 agent 解析）
deeptutor run deep_solve "求解 x^2=4" -f json
```

---

## `chat` — 交互式 REPL

进入多轮对话界面，在 REPL 内通过 `/` 命令切换 capability、工具、知识库等。

```bash
deeptutor chat [options]
```

| 选项 | 说明 |
|------|------|
| `--session` | 恢复已有会话 |
| `--tool`, `-t` | 预启用工具 |
| `--capability`, `-c` | 初始 capability（默认 `chat`） |
| `--kb` | 预挂载知识库 |
| `--language`, `-l` | 回复语言 |

### REPL 内置命令

| 命令 | 说明 |
|------|------|
| `/quit` | 退出 |
| `/session` | 显示当前 session ID |
| `/new` | 新建会话 |
| `/tool on\|off <name>` | 启用/关闭工具 |
| `/cap <name>` | 切换 capability |
| `/kb <name>\|none` | 切换知识库 |
| `/history add <id>\|clear` | 管理历史引用 |
| `/notebook add <ref>\|clear` | 管理笔记本引用 |
| `/regenerate`（别名 `/retry`） | 重跑上一条用户消息 |
| `/show last\|<n>` | 展开被截断的工具结果或折叠的思考过程 |
| `/refs` | 查看当前设置 |
| `/config show\|set\|clear` | 管理 capability 配置 |

回答生成期间按 `Ctrl-C` 会取消当前 turn 并回到输入提示符;模型通过
`ask_user` 提问时,会在终端内渲染选项卡片并等待输入(非交互式 stdin
下自动提交空回复,turn 不会挂起)。

---

## `serve` — 启动 API 服务

```bash
deeptutor serve [--host 0.0.0.0] [--port 8001] [--reload]
```

`deeptutor serve` 需要完整 Web/API 依赖；如果你是通过本地 `./packaging/deeptutor-cli` 安装的 CLI-only 包，请先卸载本地 CLI 包并切换到 `pip install -U deeptutor`。

---

## 资源管理命令

### `kb` — 知识库

```bash
deeptutor kb list                                # 列出所有知识库
deeptutor kb info <name>                         # 查看详情
deeptutor kb create <name> --doc file.pdf        # 创建并导入文档
deeptutor kb create <name> --docs-dir ./docs/    # 从目录批量导入
deeptutor kb add <name> --doc extra.pdf          # 追加文档
deeptutor kb set-default <name>                  # 设为默认
deeptutor kb search <name> "查询内容"             # 搜索
deeptutor kb delete <name> --force               # 删除
```

### `session` — 会话

```bash
deeptutor session list [--limit 20]
deeptutor session show <id>
deeptutor session open <id>                      # 进入 REPL 继续对话
deeptutor session rename <id> --title "新标题"
deeptutor session delete <id>
```

### `notebook` — 笔记本

```bash
deeptutor notebook list
deeptutor notebook create "笔记" --description "描述"
deeptutor notebook show <id>
deeptutor notebook add-md <id> ./notes.md
deeptutor notebook replace-md <id> <record_id> ./updated.md
deeptutor notebook remove-record <id> <record_id>
```

### `memory` — 长期记忆

```bash
deeptutor memory show
deeptutor memory clear --force
```

### `plugin` — 插件信息

```bash
deeptutor plugin list                            # 查看所有工具和 capability
deeptutor plugin info <name>                     # 查看详情
```

### `config` — 配置

```bash
deeptutor config show
```

### `provider` — 提供方认证 / 校验

```bash
deeptutor provider login openai-codex      # 执行 OpenAI Codex OAuth 登录
deeptutor provider login github-copilot    # 校验现有 GitHub Copilot 认证是否可用
deeptutor provider login codebuddy         # 校验 CodeBuddy SDK 登录；未登录时打开登录入口
```

`openai-codex` 使用 DeepTutor 自己的独立 OAuth 流程登录。它不需要 `OPENAI_API_KEY`，也不会读取或同步本机 `~/.codex`；凭据保存在 `data/system/user-secrets/<owner>/private/openai-codex/`（沙箱访问不到的目录），与 Web 设置页共用。

远程部署时，浏览器的 `localhost` 和服务器的 `localhost` 不是同一台机器，仅有普通反向代理无法把浏览器的 localhost callback 送到服务器，必须用 SSH 隧道建立 callback 桥。隧道通向已发布的 Web 端口；Next.js 只把精确的 callback 路径改写到 public callback broker，broker 校验 `state` 后才路由到原 OAuth operation。callback listener 仍位于后端 loopback，不发布 `1455`/`1457`，并支持默认 Docker bridge 网络。

```bash
ssh -N -L 1455:127.0.0.1:3782 <ssh-user>@<server-host>
```

若 DeepTutor 显示 fallback callback 端口 `1457`，则使用：

```bash
ssh -N -L 1457:127.0.0.1:3782 <ssh-user>@<server-host>
```

只运行与实际 callback 端口对应的其中一条命令，不能两条都运行。`3782` 只是示例 Web 端口：它是 DeepTutor 配置并作为 `callback_forward_port` 显示的 frontend/container 端口，不保证 SSH 主机的 `127.0.0.1` 正在监听同一端口。若 Docker/Podman 映射到不同宿主机端口，或反向代理监听不同端口，只替换 SSH 命令右侧的目标端口（上例中的 `3782`）为 SSH 主机 `127.0.0.1` 实际监听的 Web 端口；左侧 callback 端口仍保持 `1455` 或 `1457`。`<server-host>` 是该 loopback 监听端口所在的 SSH 主机；若浏览器域名指向反向代理或负载均衡器，请替换为正确的 SSH 前端主机。

CLI 会先打印隧道命令，随后立即尝试打开浏览器。远程用户应先保持授权页打开但不要完成授权，在另一终端建立所显示的隧道，然后再继续授权。

localhost 检测存在边界：若 Web 本身已通过 SSH 或 IDE localhost 转发访问，浏览器无法判断服务器是远程的。对于当前 Web operation，应保持其授权页未完成，从该 operation 的 authorize URL 中读取 `redirect_uri`，确认 callback 是 `1455` 还是 `1457`，再把该本地端口通过第二条隧道转到实际 Web 端口。另一种方法是取消该 Web operation，再通过 CLI 启动一个新 operation；CLI 输出只属于新 operation，不能用于当前 Web operation。

Codex 令牌授权的是**你本人**的 ChatGPT 套餐，因此凭据只归当前登录用户，不会通过模型授权共享给部署内的其他用户——每位用户各自登录。登录成功后，模型列表来自该账号的动态目录；仅当此前尚未配置任何 LLM 时，Codex 才会被自动设为活动模型，否则不改动你已选的模型。目录刷新失败、上游 `429` 或其他错误都会如实报告，不会回退到付费 API Provider。这条 Codex backend 兼容路径目前属于实验性能力。

---

## 典型工作流

```bash
# 1. 创建知识库
deeptutor kb create calculus --doc 微积分教材.pdf

# 2. 用知识库解题
deeptutor run deep_solve "求 ∫sin(x)cos(x)dx" -t rag --kb calculus -l zh

# 3. 基于知识库出题
deeptutor run deep_question "微积分" --kb calculus \
  --config num_questions=5 --config difficulty=medium -l zh

# 4. 深度研究某课题
deeptutor run deep_research "注意力机制演进" \
  --config-json '{"mode":"report","depth":"deep","sources":["papers","web"]}' -l zh

# 5. 查看会话记录
deeptutor session list
```
