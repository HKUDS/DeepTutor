# DeepTutor 快速部署指南

本文档提供 DeepTutor 的快速部署方案，涵盖依赖项、配置和多种部署方式。

---

## 环境依赖

### 系统要求

| 项目 | 最低要求 | 推荐配置 |
|:-----|:---------|:---------|
| 操作系统 | macOS / Linux / Windows | Linux (Ubuntu 22.04+) |
| 内存 | 8 GB | 16 GB+ |
| 磁盘空间 | 10 GB | 20 GB+ (含知识库) |

### 软件依赖

| 软件 | 版本要求 | 用途 |
|:-----|:---------|:-----|
| Python | 3.10+ | 后端运行时 |
| Node.js | 18+ | 前端运行时 |
| npm | 9+ | 前端包管理 |
| Docker | 24+ | 容器化部署（可选） |

---

## 环境变量配置

### 必填变量

```bash
# LLM 配置（必填）
LLM_MODEL=gpt-4o                          # 模型名称
LLM_API_KEY=your_api_key                  # API 密钥
LLM_HOST=https://api.openai.com/v1        # API 端点

# Embedding 配置（必填）
EMBEDDING_MODEL=text-embedding-3-large    # 嵌入模型
EMBEDDING_API_KEY=your_api_key            # 嵌入 API 密钥
EMBEDDING_HOST=https://api.openai.com/v1  # 嵌入 API 端点
EMBEDDING_DIM=3072                        # 嵌入维度
```

### 可选变量

```bash
# 服务端口
BACKEND_PORT=8001                         # 后端端口（默认 8001）
FRONTEND_PORT=3782                        # 前端端口（默认 3782）

# 远程访问（局域网/公网部署必填）
NEXT_PUBLIC_API_BASE=http://your-ip:8001  # 前端访问后端的地址

# 网络搜索
SEARCH_PROVIDER=perplexity                # 或 baidu
PERPLEXITY_API_KEY=your_key               # Perplexity API 密钥
BAIDU_API_KEY=your_key                    # 百度 AI 搜索密钥

# TTS 语音合成（可选）
TTS_MODEL=                                # TTS 模型
TTS_URL=                                  # TTS 服务地址
TTS_API_KEY=                              # TTS API 密钥

# PPT 生成（BananaPPT 集成）
PPT_LLM_MODEL=                            # PPT 专用模型（可选）
PPT_LLM_API_KEY=                          # PPT 模型 API 密钥
PPT_LLM_HOST=                             # PPT 模型端点
```

---

## 部署方案

### 方案一：Docker 部署（推荐）

> 无需本地安装 Python/Node.js，开箱即用

**1. 准备工作**

```bash
# 克隆仓库
git clone https://github.com/HKUDS/DeepTutor.git
cd DeepTutor

# 配置环境变量
cp .env.example .env
# 编辑 .env 填入 API 密钥
```

**2. 启动服务**

```bash
# 方式 A：使用 docker-compose（推荐）
docker compose up --build -d

# 方式 B：使用预构建镜像
docker run -d --name deeptutor \
  -p 8001:8001 -p 3782:3782 \
  --env-file .env \
  -v $(pwd)/data:/app/data \
  -v $(pwd)/config:/app/config:ro \
  ghcr.io/hkuds/deeptutor:latest
```

**3. 镜像选择**

| 架构 | 镜像标签 | 适用场景 |
|:-----|:---------|:---------|
| AMD64 | `ghcr.io/hkuds/deeptutor:latest` | Intel/AMD (大多数服务器) |
| ARM64 | `ghcr.io/hkuds/deeptutor:latest-arm64` | Apple Silicon, AWS Graviton |

**4. 云服务器部署**

```bash
# 必须设置外部访问地址
docker run -d --name deeptutor \
  -p 8001:8001 -p 3782:3782 \
  -e NEXT_PUBLIC_API_BASE_EXTERNAL=https://your-server.com:8001 \
  --env-file .env \
  -v $(pwd)/data:/app/data \
  ghcr.io/hkuds/deeptutor:latest
```

---

### 方案二：手动安装

> 适用于开发或无 Docker 环境

**1. 创建 Python 环境**

```bash
# 使用 conda（推荐）
conda create -n deeptutor python=3.10 && conda activate deeptutor

# 或使用 venv
python -m venv venv && source venv/bin/activate
```

**2. 安装依赖**

```bash
# 后端依赖
pip install -r requirements.txt

# 前端依赖
npm install --prefix web
```

**3. 配置环境**

```bash
cp .env.example .env
# 编辑 .env 配置 API 密钥
```

**4. 启动服务**

```bash
# 一键启动（前端 + 后端）
python scripts/start_web.py

# 或分别启动
# 后端
python src/api/run_server.py
# 前端（新终端）
cd web && npm run dev -- -p 3782
```

---

### 方案三：开发模式

> 适用于代码开发和调试

**1. 后端开发**

```bash
# 热重载模式
uvicorn src.api.main:app --host 0.0.0.0 --port 8001 --reload
```

**2. 前端开发**

```bash
cd web

# 创建本地环境配置
echo "NEXT_PUBLIC_API_BASE=http://localhost:8001" > .env.local

# 启动开发服务器
npm run dev
```

---

## 访问地址

| 服务 | 地址 | 说明 |
|:-----|:-----|:-----|
| 前端界面 | http://localhost:3782 | 主应用入口 |
| API 文档 | http://localhost:8001/docs | Swagger 接口文档 |
| API 文档 | http://localhost:8001/redoc | ReDoc 接口文档 |

---

## 目录结构

```
DeepTutor/
├── config/                 # 配置文件
│   ├── main.yaml          # 主配置
│   └── agents.yaml        # Agent 参数配置
├── data/                   # 数据目录
│   ├── knowledge_bases/   # 知识库存储
│   └── user/              # 用户数据
├── src/                    # 后端源码
│   ├── api/               # FastAPI 接口
│   ├── agents/            # AI Agent 模块
│   ├── services/          # 服务层
│   └── tools/             # 工具集成
├── web/                    # 前端源码
│   ├── app/               # Next.js 页面
│   ├── components/        # React 组件
│   └── lib/               # 工具函数
├── scripts/                # 脚本工具
└── docs/                   # 文档
```

---

## 常见问题

### 端口被占用

```bash
# macOS/Linux
lsof -i :8001
kill -9 <PID>

# Windows
netstat -ano | findstr :8001
taskkill /PID <PID> /F
```

### 前端连接后端失败

1. 确认后端运行中：访问 http://localhost:8001/docs
2. 检查 `.env.local` 配置：`NEXT_PUBLIC_API_BASE=http://localhost:8001`
3. 检查防火墙设置

### npm 命令未找到

```bash
# 使用 conda 安装
conda install -c conda-forge nodejs

# 或使用 nvm
nvm install 18 && nvm use 18
```

---

## 相关文档

- [配置指南](docs/guide/configuration.md)
- [故障排查](docs/guide/troubleshooting.md)
- [BananaPPT 集成](docs/banana_ppt_integration_zh.md)
- [完整 README](README.md)
