# 本地安装

本指南介绍用于开发或非 Docker 环境的手动安装。

## 前提条件

- **Python 3.10+** — [下载](https://www.python.org/downloads/)
- **Node.js 18+** — [下载](https://nodejs.org/)
- **Git** — [下载](https://git-scm.com/)

::: tip Windows 用户
如果在安装过程中遇到路径长度错误，请启用长路径支持：

```cmd
reg add "HKLM\SYSTEM\CurrentControlSet\Control\FileSystem" /v LongPathsEnabled /t REG_DWORD /d 1 /f
```

运行此命令后重启终端。
:::

## 步骤 1：设置虚拟环境

选择以下选项之一：

::: code-group

```bash [Conda（推荐）]
# 创建环境
conda create -n deeptutor python=3.10

# 激活环境
conda activate deeptutor
```

```bash [venv]
# 创建环境
python -m venv venv

# 激活 (Windows)
venv\Scripts\activate

# 激活 (macOS/Linux)
source venv/bin/activate
```

:::

## 步骤 2：安装依赖

### 选项 A：自动安装（推荐）

```bash
# 使用 Python 脚本
python scripts/install_all.py

# 或使用 shell 脚本 (macOS/Linux)
bash scripts/install_all.sh
```

### 选项 B：手动安装

```bash
# 安装 Python 依赖
pip install -r requirements.txt

# 安装 Node.js 依赖
npm install --prefix web
```

::: warning 常见问题
如果看到 `npm: command not found`：

```bash
# 使用 Conda
conda install -c conda-forge nodejs

# 或从 https://nodejs.org/ 安装
```
:::

## 步骤 3：配置环境

确保您已完成[预配置](/zh/guide/pre-config)步骤：

1. ✅ 创建了包含 API 密钥的 `.env` 文件
2. ✅ （可选）自定义了 `config/agents.yaml`
3. ✅ （可选）下载了示例知识库

## 步骤 4：启动应用

### 启动 Web 界面（推荐）

```bash
python scripts/start_web.py
```

这将同时启动 **前端**（Next.js）和 **后端**（FastAPI）服务器。

### 替代方案：仅 CLI 界面

```bash
python scripts/start.py
```

### 访问地址

| 服务 | URL | 说明 |
|:---:|:---|:---|
| **前端** | http://localhost:3782 | 主 Web 界面 |
| **API 文档** | http://localhost:8001/docs | 交互式 API 文档 |

## 高级：分别启动服务

对于开发，您可能想要分别运行前端和后端：

### 后端（FastAPI）

```bash
python src/api/run_server.py

# 或直接使用 uvicorn
uvicorn src.api.main:app --host 0.0.0.0 --port 8001 --reload
```

### 前端（Next.js）

首先，创建 `web/.env.local`：

```bash
NEXT_PUBLIC_API_BASE=http://localhost:8001
```

然后启动开发服务器：

```bash
cd web
npm install
npm run dev -- -p 3782
```

## 停止服务

在终端中按 `Ctrl+C` 停止服务。

::: warning 端口仍在使用？
如果按 Ctrl+C 后看到"端口已在使用"：

**macOS/Linux：**
```bash
lsof -i :8001
kill -9 <PID>
```

**Windows：**
```bash
netstat -ano | findstr :8001
taskkill /PID <PID> /F
```
:::

## 故障排除

### 后端启动失败

**检查清单：**
- 确认 Python 版本 >= 3.10：`python --version`
- 确认所有依赖已安装：`pip install -r requirements.txt`
- 检查端口 8001 是否被占用
- 验证 `.env` 文件配置

### 前端无法连接后端

**解决方案：**
1. 确认后端正在运行：访问 http://localhost:8001/docs
2. 检查浏览器控制台的错误信息
3. 创建 `web/.env.local`：
   ```bash
   NEXT_PUBLIC_API_BASE=http://localhost:8001
   ```

### WebSocket 连接失败

**检查清单：**
- 确认后端正在运行
- 检查防火墙设置
- 验证 WebSocket URL 格式：`ws://localhost:8001/api/v1/...`

---

**下一步：** [Docker 部署 →](/zh/guide/docker-start)
