# DeepTutor CLI

Agent-first 的命令行界面。两条核心路径：

- **`run`** — 单次执行任意 capability（为 agent 调用设计）
- **`chat`** — 交互式 REPL（为人类设计）

## 安装

```bash
# 仅 CLI
pip install -r requirements/cli.txt && pip install -e .

# CLI + Web/API 服务
pip install -r requirements/server.txt && pip install -e .

# 数学动画（可选）
pip install -r requirements/math-animator.txt
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
| `math_animator` | 数学动画生成 |

### 选项

| 选项 | 缩写 | 说明 |
|------|------|------|
| `--tool` | `-t` | 启用工具（可多次指定）：`rag`, `web_search`, `code_execution`, `reason`, `brainstorm`, `paper_search` |
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

# 数学动画
deeptutor run math_animator "展示正弦函数变换" --config quality=high

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
| `/refs` | 查看当前设置 |
| `/config show\|set\|clear` | 管理 capability 配置 |

---

## `serve` — 启动 API 服务

```bash
deeptutor serve [--host 0.0.0.0] [--port 8001] [--reload]
```

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
deeptutor memory export ./backup/
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

### `provider` — OAuth 登录

```bash
deeptutor provider login openai-codex
deeptutor provider login github-copilot
```

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
