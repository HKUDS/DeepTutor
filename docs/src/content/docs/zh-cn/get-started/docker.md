---
title: Docker
description: 选项 3 —— 一个容器跑完整 Web 应用，镜像来自 GHCR。
quadrant: how-to
---

一个容器跑完整 Web 应用。镜像在 GitHub Container Registry 上：

- `ghcr.io/hkuds/deeptutor:latest` —— 当前稳定版
- `ghcr.io/hkuds/deeptutor:<version>` —— 精确版本；预发布只发版本 tag，不更新 `latest`

## 运行

```bash
docker run --rm --name deeptutor \
  -p 127.0.0.1:3782:3782 \
  -v deeptutor-data:/app/data \
  ghcr.io/hkuds/deeptutor:latest
```

> **只需要映射 `3782`。** 浏览器只跟前端 origin 通信；容器里的 Next.js 中间件（`web/proxy.ts`）会把每个 `/api/*` 和 `/ws/*` 请求**在容器内部**转发给 FastAPI 后端，所以为了让 UI 正常工作，你不需要把 `8001` 暴露到宿主机。映射它（`-p 127.0.0.1:8001:8001`）是可选的 —— 只在你想用 curl 或脚本直接调 API 时才有用。

打开 <http://127.0.0.1:3782>。容器首次启动时会创建 `/app/data/user/settings/*.json`；从 Web 的设置页面里配置模型 provider。配置、API key、日志、默认内容工作区、记忆、知识库、Partner 工作区（`data/partners/<id>/`）全部持久化在 `deeptutor-data` volume 里。可选依赖声明在部署上，别钻进容器里装：设好 `DEEPTUTOR_EXTRAS`（系统库用 `DEEPTUTOR_APT_PACKAGES`），每个容器启动时自动补齐。

## 选择宿主机上的内容工作区

默认情况下，内容工作区的存储位于 `deeptutor-data` volume 内部。想改用宿主机上的文件夹，就把它挂到固定的容器路径 `/workspace`，并把 DeepTutor 锁到该路径：

```bash
mkdir -p "$PWD/deeptutor-workspace/outputs"
docker run --rm --name deeptutor \
  -p 127.0.0.1:3782:3782 \
  -v deeptutor-data:/app/data \
  -v "$PWD/deeptutor-workspace:/workspace" \
  -e DEEPTUTOR_WORKSPACE_ROOT=/workspace \
  -e DEEPTUTOR_WORKSPACE_ALLOWED_ROOTS=/workspace \
  ghcr.io/hkuds/deeptutor:latest
```

首次运行前请自己建好 `outputs/`——否则 Docker 会以 root 身份创建这个挂载源，非特权的应用进程写不进去。

容器看到的始终是 `/workspace`，因此路径在宿主机间保持可移植。该部署根目录约束所有账号；托管工作区使用 `outputs/.deeptutor/chat/` 下按账号隔离的目录。**Settings → Workspace** 管理各工作区与存储，不会暴露私有运行设置。

用 Compose 时，在 `python scripts/docker_compose.py up -d` 之前设好 `DEEPTUTOR_WORKSPACE_HOST=/absolute/host/folder`；辅助脚本会替你建好该文件夹及其 `outputs/`。不设则继续使用 `./data/user/workspace`。

## 后台模式

加 `-d` 让它在后台跑：

```bash
docker run -d --name deeptutor \
  -p 127.0.0.1:3782:3782 \
  -v deeptutor-data:/app/data \
  ghcr.io/hkuds/deeptutor:latest

docker logs -f deeptutor      # 跟踪日志
docker stop deeptutor         # 停止
docker rm deeptutor           # 删除（volume 仍保留）
```

`deeptutor-data` volume 会在 `stop` / `rm` 之间保留设置和默认内容工作区。如果真要从头来：`docker volume rm deeptutor-data`。

## 远程 Docker / 反向代理

浏览器始终只跟前端 origin（`:3782`）通信；容器里的 Next.js 中间件会在服务端把 `/api/*` 和 `/ws/*` 转发给 `localhost:8001` 上的后端。所以常见的**单容器**场景下，你完全**不需要**配置任何 API base —— 把反向代理 / TLS 终止器指向发布出来的 `:3782` 即可：

```text
deeptutor.example.com {
    reverse_proxy localhost:3782
}
```

只有**拆分部署**（后端跑在另一个容器或主机上）才需要设置 API base。在挂载 volume 里的 `data/user/settings/system.json` 中，把它设成**前端服务器**用来访问后端的内网地址 —— 这个值由代理在服务端读取，不会发给浏览器：

```json
{
  "next_public_api_base": "http://backend:8001"
}
```

`next_public_api_base_external`（及其别名 `public_api_base`）作为更低优先级的回退被接受，保存时会归一化。

CORS 只在开启 auth 且前端跨 origin 时才有意义：`cors_origins` 列出哪些前端页面 origin 可以调用后端。未开启 auth 时，DeepTutor 默认允许正常 HTTP/HTTPS 浏览器 origin。

```json
{
  "cors_origins": ["https://deeptutor.example.com"]
}
```

## 改宿主机端口

改 `-p host:container` 映射的左边即可：

```bash
docker run --rm --name deeptutor \
  -p 127.0.0.1:8088:3782 \
  -v deeptutor-data:/app/data \
  ghcr.io/hkuds/deeptutor:latest
```

如果还想把 API 暴露到宿主机，再加 `-p 127.0.0.1:8089:8001`。如果你在 `/app/data/user/settings/system.json` 里改了容器侧端口，重启并把每条映射右侧同步改掉。

## 连本地 LLM（Ollama / LM Studio / llama.cpp / vLLM）

Docker 里的 `localhost` 指的是容器本身，不是宿主机。要访问宿主机上跑的模型服务，用 host gateway：

```bash
docker run --rm --name deeptutor \
  -p 127.0.0.1:3782:3782 \
  --add-host=host.docker.internal:host-gateway \
  -v deeptutor-data:/app/data \
  ghcr.io/hkuds/deeptutor:latest
```

然后在 **设置 → LLM**（或 **Embedding**）里，把 provider Base URL 指到 `host.docker.internal`：

| 服务 | Base URL |
|------|----------|
| Ollama LLM | `http://host.docker.internal:11434/v1` |
| Ollama embedding | `http://host.docker.internal:11434/api/embed` |
| LM Studio | `http://host.docker.internal:1234/v1` |
| llama.cpp | `http://host.docker.internal:8080/v1` |

Docker Desktop（macOS / Windows）通常**不需要** `--add-host` 就能解析 `host.docker.internal`。Linux 上，这个 flag 是在现代 Docker Engine 上创建这个 hostname 的可移植方式。

### Linux 替代方案 —— host networking

加 `--network=host`，去掉 `-p` flags：

```bash
docker run --rm --name deeptutor \
  --network=host \
  -v deeptutor-data:/app/data \
  ghcr.io/hkuds/deeptutor:latest
```

容器直接共享宿主机网络，所以打开 <http://127.0.0.1:3782>（或 `system.json` 里的 `frontend_port`），宿主机服务也能用普通的 localhost URL 访问，比如 `http://127.0.0.1:11434/v1`。

> Host networking 把容器端口直接暴露在宿主机上，可能跟已有服务冲突。

## 升级

```bash
docker pull ghcr.io/hkuds/deeptutor:latest
docker rm -f deeptutor 2>/dev/null
docker run --rm --name deeptutor \
  -p 127.0.0.1:3782:3782 \
  -v deeptutor-data:/app/data \
  ghcr.io/hkuds/deeptutor:latest
```

volume 会保留 —— 你的设置、KB、记忆都能撑过升级。

**设置 → 关于** 会识别 Docker 镜像并检查是否有新版本，但替换容器仍属于部署操作：按上面的步骤拉取新镜像并重建容器。DeepTutor 不会在运行中的容器里原地升级包。

## 常见错误

### `Bind for 0.0.0.0:3782 failed: port is already allocated`

```bash
lsof -i :3782          # macOS
ss -ltnp | grep :3782  # Linux
```

干掉冲突进程，或者在 `-p` 映射里换一个宿主机端口。

### 容器立刻退出

```bash
docker logs deeptutor | tail -30
```

无效的 LLM 凭据会被捕获并记为 warning，**不会**让后端启动失败。如果容器已经退出，请从日志中寻找其他致命错误。Web UI 可用后，到 **设置 → 模型与服务** 修正凭据即可。

### 前端能加载但 API 调用失败（拆分部署）

用单容器镜像时不该出现这种情况 —— 容器内的代理会自动把 `/api/*` 转发给后端。如果你跑的是**拆分部署**（后端在另一个容器或主机上），在 volume 里的 `data/user/settings/system.json` 把 `next_public_api_base` 设成前端服务器访问后端用的内网地址，然后重启。

### Docker 里的多用户模式

直接在 volume 的 `data/user/settings/auth.json` 里把 auth 开关打开（`"enabled": true`），然后重启。容器会自动 pick up。完整配置见 [**多用户部署**](/zh-cn/get-started/multi-user/)。

更多：[**故障排查**](/zh-cn/get-started/troubleshooting/)。

## 下一步

- [**多用户部署**](/zh-cn/get-started/multi-user/) —— 团队配置
- [**探索 DeepTutor**](/zh-cn/explore/) —— 看看跑起来的应用
