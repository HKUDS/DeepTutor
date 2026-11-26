---
title: 仅 CLI 安装
description: 选项 4 —— 给 headless 服务器、agent harness 以及 Claude Code / Codex / Hermes 用的轻量安装方式。
quadrant: how-to
---

当前 `dev` 的源码 CLI 安装使用主项目，并跳过前端 Node/npm 设置。源码包含全部模块，所以仍需安装 `requirements/full.txt`。1.7.x 的精简 core wheel 提供聊天和 SDK，功能模块可另行安装；`deeptutor-cli` 是 core 的元数据兼容别名。不要继续 editable 安装旧 `packaging/deeptutor-cli` 项目。

## 安装

```bash
git clone --branch dev https://github.com/HKUDS/DeepTutor.git
cd DeepTutor

# 创建 venv（macOS / Linux）
# Windows PowerShell：
#   py -3.11 -m venv .venv-cli ; .\.venv-cli\Scripts\Activate.ps1
python3 -m venv .venv-cli && source .venv-cli/bin/activate
python -m pip install --upgrade pip

python -m pip install -r requirements/full.txt
python -m pip install -e . --no-deps
deeptutor init --cli
deeptutor chat
```

`deeptutor init --cli` 和完整版应用共享同一份 `data/user/settings/` 目录结构，但是：

- **跳过**后端 / 前端端口的询问
- **Embedding picker 默认选当前 provider，否则选 OpenAI**（不需要 `deeptutor kb …` 或 RAG 工具时按 `s` 跳过）
- Search 仍是可选项——不需要 Web Search 时可跳过 provider picker
- 除核心设置外，还会写入 `document_parsing.json`、`pageindex.json`、`ima.json`、`llamaindex.json`、`graphrag.json` 和 `lightrag.json`
- 仍然会询问当前激活的 LLM 提供商和模型

## 什么场景用它

- 把 DeepTutor 当作工具，挂在另一个 agent 的 harness 里跑（Claude Code、Codex、OpenCode 等）
- 没有浏览器的 headless 服务器 / VM
- 想要不带 Node.js toolchain 的快速安装

## 常用命令

```bash
deeptutor chat                                          # 交互式 REPL
deeptutor chat --capability deep_solve --kb my-kb
deeptutor run chat "解释一下傅里叶变换"
deeptutor run deep_solve "解 x^2 = 4" --kb my-kb
deeptutor kb create my-kb --doc textbook.pdf
deeptutor memory show
deeptutor config show
```

完整命令面：[**DeepTutor CLI**](/zh-cn/developers/guides/cli/)。

## 源码 CLI 与精简 core 是两种安装

上面的源码流程暴露与源码 Web 应用相同的模块，只是不构建、启动前端。知识库、笔记本、记忆、伙伴和高级能力依赖对应依赖包及已启用模块。它不是过去那套独立精简 CLI 发行包。

| 安装方式 | 包含什么 | 如何检查 |
| --- | --- | --- |
| **当前源码 checkout** | 仓库模块、完整 Python 依赖；终端使用不需要 Node/npm | `deeptutor module list`、`deeptutor plugin list` |
| **1.7.x 裸 core wheel** | 共享运行时、chat、ask_questions、CLI、SDK、设置与会话 | 按需添加同版本功能 wheel |
| **1.7.x full 安装范围** | core、Web/API 与常用功能模块 | 从 PyPI 安装 `[full]`，或构建同版本本地 wheel |

例如，`deep_solve` 需要 Solve；知识库需要 Knowledge 与检索配置；伙伴需要对应模块及渠道 SDK。`--tool` 只接受八个用户可开关工具。通过 `--kb` 附加知识库后，检索按上下文挂载，`--tool rag` 不会启用它。

后续给这份源码增加 Web 时，安装 Node.js 22 LTS，在 `web/` 中运行 `npm ci --legacy-peer-deps`，然后用相同运行目录执行 `deeptutor start`。要测试本地构建的精简 wheel 环境，可按照[模块说明](https://github.com/HKUDS/DeepTutor/blob/dev/docs-for-dev/MODULES.md)构建、安装本地包家族。

## 补装可选渠道依赖

修改模块或依赖前先停止 DeepTutor。从仓库根目录运行源码助手：

```bash
python scripts/install_extras.py partners
python scripts/install_extras.py matrix       # 普通 Matrix 房间
# 加密 Matrix 房间先安装系统 libolm：
python scripts/install_extras.py matrix-e2e
python -m pip check
deeptutor module list
```

使用相同的 `DEEPTUTOR_HOME` 重启。账号伙伴状态保存在 `data/partners/<id>/` 下；伙伴绑定哪个内容工作区，与运行目录是两件不同的事。渠道凭据和私有关系历史仍属于伙伴状态。详见[伙伴](/zh-cn/channels/)。

## 让另一个 agent 来调用

CLI 是 **agent-native** 的。`deeptutor run --format json` 每行输出一个 JSON 事件，`kb list`、`kb search`、`session show`、`notebook show` 等数据查询命令在已实现的地方都暴露 JSON —— 方便接到另一个 agent 的 harness 里。

把项目根目录的 [`SKILL.md`](https://github.com/HKUDS/DeepTutor/blob/main/SKILL.md) 丢给任何会调工具的 LLM，它就能自己驱动 DeepTutor。具体模式见 [**Agent handoff**](/zh-cn/developers/guides/agent-handoff/)。

## 升级

```bash
cd DeepTutor
git pull
python -m pip install -r requirements/full.txt
python -m pip install -e . --no-deps
python -m pip check
deeptutor module list
```

## 常见错误

### 装完之后 `deeptutor: command not found`

console script 没装到 PATH 上。确认 venv 已激活，或直接调用：

```bash
python -m deeptutor_cli.main chat
```

### 跑 `deeptutor serve` 时报 `ModuleNotFoundError: No module named 'fastapi'`

上面的源码安装包含服务端依赖，出现这个错误说明环境与安装不一致；检查当前 Python 环境，重新安装 `requirements/full.txt`。精简 wheel 环境则需要同版本 Server 模块。

### Partner 渠道命令提示 SDK 缺失

先停止 DeepTutor，再从源码根目录补齐 Partner 依赖：

```bash
python scripts/install_extras.py partners
```

更多：[**故障排查**](/zh-cn/self-hosting/troubleshooting/)。

## 下一步

- [**DeepTutor CLI**](/zh-cn/developers/guides/cli/) —— 完整 CLI 参考
- [**Agent handoff**](/zh-cn/developers/guides/agent-handoff/) —— 让你的 agent 来驱动
- [**Partners 伙伴与渠道**](/zh-cn/channels/) —— 从 CLI 跑一个 Partner
