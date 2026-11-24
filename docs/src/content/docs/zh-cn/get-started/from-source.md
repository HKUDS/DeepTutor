---
title: 从源码安装
description: 选项 2 —— clone 仓库、editable 安装、前端热重载。适合贡献者和高阶用户。
quadrant: how-to
---

适合基于 checkout 做开发。使用 **Python 3.11–3.14** 和 **Node.js 22 LTS**，与 CI 和 Docker 保持一致。

## 安装

```bash
git clone --branch dev https://github.com/HKUDS/DeepTutor.git
cd DeepTutor

# 创建 venv（macOS / Linux）
# Windows PowerShell：
#   py -3.11 -m venv .venv ; .\.venv\Scripts\Activate.ps1
python3 -m venv .venv && source .venv/bin/activate
python -m pip install --upgrade pip

# 安装后端 + 前端依赖
python -m pip install -r requirements/full.txt
python -m pip install -e . --no-deps
( cd web && npm ci --legacy-peer-deps )

deeptutor init
deeptutor start --dev
```

`deeptutor start` 会为本地 `web/` 前端构建一次生产版本并复用；`--dev` 则以 HMR 跑 Next.js。配置结构、端口、`Ctrl+C` 停止都和 [**PyPI 安装**](/zh-cn/get-started/pypi/) 一致。

修改模块或依赖分组前先停止 DeepTutor。安装后运行 `python -m pip check` 和 `deeptutor module list`。源码支持 `module enable/disable`；安装、卸载模块 wheel 应在独立 wheel 环境进行。重启时保留同一个运行目录。

## 用 Conda 代替 venv

```bash
conda create -n deeptutor python=3.11
conda activate deeptutor
python -m pip install --upgrade pip
# ...然后继续 `pip install -r requirements/full.txt`、`pip install -e . --no-deps` 和 `npm ci`
```

## 可选的安装 extras

当前 `dev` 源码暴露全部模块。先安装 `requirements/full.txt`，再以 `--no-deps` 注册 editable 源码；不要用 feature wheel 覆盖源码目录。增加可选依赖时，从仓库根目录运行助手：

```bash
python scripts/install_extras.py dev             # 测试 / lint 工具
python scripts/install_extras.py partners        # 全部 Partner channel SDK（含 wecom-aibot-sdk）
python scripts/install_extras.py matrix          # 不带 E2EE / libolm 的 Matrix channel
python scripts/install_extras.py matrix-e2e      # 带 E2EE 的 Matrix；需要 libolm
python scripts/install_extras.py math-animator   # Manim 插件；需要 LaTeX / ffmpeg / 系统库
```

也可以组合：`python scripts/install_extras.py dev,partners,math-animator`。

远程 MCP client 已包含在完整版和 CLI-only 的 core 安装中，不需要 `partners` extra。

模块清单拥有依赖定义，生成的 `requirements/*.txt` 用于源码、Docker 与 CI。extra 模板在 `tool.deeptutor.optional-dependencies` 中；助手会将内部模块引用展开为源码所需依赖。常用分组如下：

| Extra | 用途 | Requirements 镜像 |
|-------|------|-------------------|
| `cli` | 兼容性 extra —— CLI 依赖，默认安装已包含 | `requirements/cli.txt` |
| `server` | API 服务模块；包含在 full 源码依赖中 | `requirements/server.txt` |
| `partners` | 全部内置 Partner channel SDK（`wecom-aibot-sdk`、`qq-botpy`、`slack-sdk`、`lark-oapi`、`python-telegram-bot`、`dingtalk-stream` 等） | `requirements/partners.txt` |
| `tutorbot` | `partners` 的兼容别名，保留一个版本周期 | — |
| `matrix` | Matrix（Element）channel，非 E2EE —— 不需要 libolm | `requirements/matrix.txt` |
| `matrix-e2e` | Matrix E2EE 附加包 —— 需要系统级 **libolm** 库 | `requirements/matrix-e2e.txt` |
| `math-animator` | Manim 插件 —— 需要 LaTeX、pkg-config、cairo、cmake、ffmpeg | `requirements/math-animator.txt` |
| `graphrag` | GraphRAG 检索引擎——知识图谱索引，LLM 开销大；支持 Python 3.11–3.13 | —— |
| `rag-lightrag` | LightRAG 检索引擎——图 + 向量；解析引擎单独选 | —— |
| `rag-rerank` | LlamaIndex 可选的 cross-encoder 重排；支持 Python 3.11–3.13 | —— |
| `video-learning` | Reading 模块的兼容入口；裸 core 不包含 | —— |
| `parse` | 一次装上全部可选的文档解析引擎 | —— |
| `parse-docling` | Docling 解析——结构化的版面/表格转换 | —— |
| `parse-markitdown` | markitdown 解析——轻量、格式覆盖广，输出 Markdown | —— |
| `parse-pymupdf4llm` | PyMuPDF4LLM 解析——PDF / 电子书 / XPS / 图片 / 文本 → Markdown，无需下载模型 | —— |
| `parse-liteparse` | LiteParse 解析——轻量的结构化解析 | —— |
| `codebuddy` | CodeBuddy / WorkBuddy 提供商 SDK | —— |
| `guard` | 可选 HTTP 请求筛查；启用 `security_guard.enabled` 后才生效 | `requirements/guard.txt` |
| `dev` | pytest / pre-commit / lint 与安全检查工具 | `requirements/dev.txt` |
| `all` | full + Manim + 开发依赖（Matrix E2EE 仍单独选择） | — |

### 部分 extras 需要的系统依赖

| Extra | 系统库 |
|-------|--------|
| `matrix-e2e` | **libolm**：`brew install libolm`（macOS）/ `sudo apt install libolm-dev`（Debian） |
| `math-animator` | **LaTeX + ffmpeg**：`brew install --cask mactex && brew install ffmpeg`（macOS）/ `sudo apt install texlive-full ffmpeg`（Linux） |

## 前端依赖调整

新增或升级前端依赖时：

```bash
cd web
npm install --legacy-peer-deps
# 同时提交 web/package.json 和 web/package-lock.json
```

## Dev server 故障排查

**dev server 卡住**：如果 `deeptutor start --dev` 报告已有前端但实际无响应，先停掉它打印出的 PID。如果根本没有 Next.js 进程在跑，那是 lock 文件过期了 —— 删掉重试：

```bash
rm -f web/.next/dev/lock web/.next/lock
deeptutor start --dev
```

## 热重载

后端支持 `--reload`。在两个独立终端里分别启后端和前端，开发体验最好：

```bash
# 终端 A —— 带热重载的后端
python -m uvicorn deeptutor.api.main:app \
  --host 0.0.0.0 --port 8001 \
  --reload --reload-exclude "web/*" --reload-exclude "data/*"

# 终端 B —— 前端 dev server
cd web && npm run dev -- -p 3782
```

## 升级

```bash
git pull
python -m pip install -r requirements/full.txt
python -m pip install -e . --no-deps
python -m pip check
deeptutor module list
cd web && npm ci --legacy-peer-deps
```

如果某次发布动了配置 schema，再跑一次 `deeptutor init` 把新增字段补上。已有配置会保留。

**设置 → 关于** 会把当前环境识别为源码 checkout 并显示 Git revision，但不会替你 pull、merge 或覆盖工作树。源码安装需要显式使用 Git 更新，让本地分支和未提交修改始终由你掌控。

## 常见错误

### `error: Microsoft Visual C++ 14.0 is required`（Windows）

部分 Python 依赖会编译 C 扩展。装 [**Build Tools for Visual Studio**](https://visualstudio.microsoft.com/visual-cpp-build-tools/)，勾选 "Desktop development with C++"。

### 找不到 `libolm`（装了 `matrix-e2e` 时）

```bash
brew install libolm                   # macOS
sudo apt install libolm-dev           # Debian / Ubuntu
python scripts/install_extras.py matrix-e2e
```

### `npm ci` 慢或超时

```bash
npm config set fetch-timeout 600000
cd web && npm ci --legacy-peer-deps
```

### 后端 `--reload` 每次保存都疯狂重启

`--reload-exclude` 漏了。用下面命令重启：

```bash
python -m uvicorn deeptutor.api.main:app \
  --host 0.0.0.0 --port 8001 \
  --reload --reload-exclude "web/*" --reload-exclude "data/*"
```

更多修复方法：[**故障排查**](/zh-cn/get-started/troubleshooting/)。

## 下一步

- [**DeepTutor CLI**](/zh-cn/cli/) —— 在同一个工作区里使用 CLI
- [**探索 DeepTutor**](/zh-cn/explore/) —— 看看跑起来的应用
