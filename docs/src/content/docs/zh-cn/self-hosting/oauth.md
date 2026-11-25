---
title: Codex 登录
description: 用自己的 ChatGPT 订阅登录 OpenAI Codex，并确认回调已经收到。
quadrant: how-to
---

OpenAI Codex 登录使用你自己的 ChatGPT 订阅，不需要 `OPENAI_API_KEY`。

## 登录

1. 打开 **设置 → 模型与服务**，添加 **OpenAI Codex**。
2. 完成 DeepTutor 打开的浏览器登录。
3. 提供方把浏览器重定向到 `GET /api/auth/openai-codex/callback`，带上 `code` 和 `state`；如果登录被拒绝，则带上 `error`。
4. 成功的回调页会写明已经收到认证。回到 DeepTutor。

模型列表来自该账号的实时目录。登录会发布一个配置；只有还没有配置任何 LLM 时，它才会成为当前模型。

## 令牌放在哪里

令牌只保存在 `data/system/user-secrets/<owner>/private/openai-codex/`。DeepTutor 不会读取或修改 `~/.codex` 的 CLI 登录。令牌只授权一个人的订阅，不能通过用户授权分享。每个账号，包括非管理员，都为自己登录。产生的模型、目录和退出登录只属于该账号。

## 容器

默认的本地 Docker 或 Podman 使用自己的回环网络，登录期间浏览器回调需要一条临时桥接。具体的 Docker、Compose、Podman 和拆除命令在仓库的[容器化指南](https://github.com/HKUDS/DeepTutor/blob/dev/docs-for-dev/CONTAINERIZATION.md#temporary-local-codex-oauth-bridge)。
