# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

# deeptutor

HKU DeepTutor（GitHub 21k ⭐，Apache-2.0）— 开源 AI 学习辅导系统。提供 Chat、Deep Solve、Quiz Generation、Math Animator 等 6 大学习模式。

## 技术栈

- 后端：Python + FastAPI
- 前端：Next.js (web/)
- AI：DeepSeek API（已配置）
- 向量：LlamaIndex RAG + bge-m3 embedding
- 数据库：SQLite + 文件系统

## 目录结构

```
deeptutor/
├── deeptutor/           核心库（agents, tools, services, knowledge...）
├── deeptutor_cli/       CLI 接口
├── deeptutor_web/       Web 后端
├── web/                 Next.js 前端
├── data/                数据（含 knowledge_bases 目录）
├── scripts/             工具脚本
│   └── start_web.py     启动脚本
└── tests/               测试
```

## 常用命令

```bash
# 启动
cd deeptutor && source .venv/bin/activate && python scripts/start_web.py

# 知识库 CLI 管理（需先激活 venv）
python -m deeptutor_cli kb list
python -m deeptutor_cli kb create MathNet --docs-dir <path>
python -m deeptutor_cli kb add MathNet --docs-dir <path>
```

## 相关项目

- `code/mathnet-kb/` — MathNet 竞赛数学题库（供本项目的知识库使用）

## 已做定制

1. 新增 `POST /api/v1/knowledge/sync-mathnet` 端点 — 一键从云端拉取 MathNet 数据更新知识库
2. 前端知识库 Settings 页新增"一键更新"按钮
3. 环境变量 `MATHNET_CLOUD_URL` 配置云端服务器地址
