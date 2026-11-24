---
title: 快速上手
description: DeepTutor 提供四种安装方式 —— PyPI、源码、Docker、纯 CLI。挑一个适合你的。
---

DeepTutor 提供 **四种安装路径**，全部使用相同的运行数据目录（runtime home）布局：设置文件位于运行命令所在目录下的 `data/user/settings/`（或者你显式指定的 `DEEPTUTOR_HOME` / `deeptutor start --home` 位置）。知识库、记忆、Partners runtime、多用户账号和审计日志也都在同一棵 `data/` 树里，部署时需要持久化它，以及另外指定的内容工作区目录。运行数据目录是部署的存储根目录，与应用内切换的工作区是不同概念。

对完整 Web 应用，推荐流程是：**挑一个运行数据目录 → 安装 → `deeptutor init` → `deeptutor start`**。

## 选择安装路径

| 方式 | 适用场景 | 页面 |
|------|---------|------|
| **PyPI** | 已发布安装包；1.7.0 完整应用使用 [full] | [**PyPI 安装**](/zh-cn/get-started/pypi/) |
| **源码** | 当前 dev、源码开发与可选热重载 | [**源码安装**](/zh-cn/get-started/from-source/) |
| **Docker** | 生产部署、托管主机、需要持久化卷 | [**Docker**](/zh-cn/get-started/docker/) |
| **纯 CLI** | 无界面服务器、被其他 agent 调度、不需要 Web UI | [**纯 CLI 安装**](/zh-cn/get-started/cli-only/) |

> **1.7.0 安装：** `deeptutor[full]` 安装完整 Web 应用，裸 `deeptutor` 安装最小 CLI/SDK。修改模块前停止应用，功能 wheel 与 core 保持同版本。开发时使用源码安装，或[构建本地 wheels](https://github.com/HKUDS/DeepTutor/blob/dev/docs-for-dev/MODULES.md)；升级旧环境前请备份运行目录。

## 最低环境要求

| 组件 | 版本 |
|------|------|
| Python | **3.11–3.14** |
| Node.js | **20+**（PyPI 安装） / **22 LTS**（源码安装，对齐 CI 与 Docker） |
| 内存 | 取决于所选模型和工作负载 |
| 磁盘 | 取决于安装 extras 和工作区数据 |

还需要一个 **LLM provider**。托管服务通常需要 API key；Ollama、LM Studio、llama.cpp、vLLM 等本地 provider 不需要密钥也能运行。Embedding provider 是可选的，只有使用知识库时才需要配置。

## 启动后会监听什么

执行 `deeptutor start` 之后会起两个服务：

| 服务 | 默认端口 |
|------|---------|
| FastAPI 后端 | `8001` |
| Next.js 前端 | `3782` |

两个端口都可以在 `data/user/settings/system.json` 中改，或在 `deeptutor init` 向导里现场指定。

## 装好之后

只要你能打开 `http://localhost:3782/`：

- [**探索 DeepTutor**](/zh-cn/explore/) —— 从工作区出发，串起主页、学习、资料、伙伴与个性化
- [**DeepTutor CLI**](/zh-cn/cli/) —— 在终端里驱动核心运行时与工作区操作
- [**伙伴：渠道**](/zh-cn/partners/) —— 把持久化的 AI 导师连到 WeChat、WeCom、QQ、Telegram、Slack、飞书等渠道
- [**多用户部署**](/zh-cn/get-started/multi-user/) —— 部署给一个团队

如果遇到问题，跳到 [**故障排查**](/zh-cn/get-started/troubleshooting/)。
