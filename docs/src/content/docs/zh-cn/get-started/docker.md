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

## 下一步

宿主机目录、后台运行、反向代理、本地模型和升级写在 [Docker 运维](/zh-cn/self-hosting/docker/)。

- [**探索 DeepTutor**](/zh-cn/learning-workspace/)
