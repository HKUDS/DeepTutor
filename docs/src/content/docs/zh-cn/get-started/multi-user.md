---
title: 多用户部署
description: 打开认证开关，DeepTutor 就变成多租户部署 —— 每个用户拥有独立的工作区，资源由管理员统一编排。
---

打开认证开关，DeepTutor 就变成多租户部署 —— **每个用户拥有独立的工作区**，**资源由管理员统一编排**。第一个注册的人成为 admin，代表其他人配置模型、API key 与知识库。后续账号由 admin 创建（邀请制），每个人有自己作用域内的对话历史 / 记忆 / 笔记本 / 知识库和私密个人书。他们能看到获分配的 LLM、KB 与 skill，自己创建或获分配的 partner，以及按 read/edit 等级授权的管理员共享书。

## 快速上手（5 步）

```bash
# 1. 在 data/user/settings/auth.json 里开启 auth：
#    {"enabled": true, "token_expire_hours": 24, "cookie_secure": false}
#    Web 和 API 跨站的 HTTPS 部署请用 cookie_secure=true。

# 2. 重启 web 栈。
deeptutor start

# 3. 打开 http://localhost:3782/register 并创建第一个账号。
#    第一次注册是唯一一次公开注册；那个用户成为 admin，之后
#    /register 端点会自动关闭。

# 4. 以 admin 身份进入 /admin/users → "Add user" 给团队成员开账号。

# 5. 对每个用户，点击 slider 图标 → 分配资源 grant，再设置 Book access
#    （个人书创建、默认访问与逐书 read/edit）。保存后用户即可登录使用。
```


## admin 能看到什么

- **完整的设置页面**，在 `/settings` —— 管理可复用的 vendor Connections，以及 LLM、Task Models、embedding、search、TTS、STT、图像与视频服务的 profiles。Task Models 负责会话标题、Home 起始建议、阅读辅助以及 Math Animator/Video Lesson 修复；留空时继承 LLM。
- **用户管理**，在 `/admin/users` —— 创建 Standard、Learner 或 Custom 账号（或从 CSV 批量导入），再提升、降级或删除，可单个也可批量。创建 Learner 时会初始化受限学习授权与资料；第一个 admin 出现后公开 `/register` 会关闭，后续账号通过管理员接口创建。
- **授权编辑器** —— 对每个非 admin 用户，挑选他们可用的 LLM 模型、知识库、skill 和 partner，把系统工具（联网搜索、论文搜索……）、MCP 工具和已安装的 CLI 应用收窄成白名单，也可以彻底关掉代码执行。工具白名单与 partner 配置同语义：*Default* 全部放行，*Custom* 是显式白名单。授权只带**逻辑 ID**；API key 永远不会越过授权边界。
- **Book access 编辑器** —— 允许创建个人书，为共享管理员书设置默认权限（`none` 或 `read`），并逐书覆盖为 `none`、`read` 或协作 `edit`。共享删除不下放；进度、书签、测验作答、capture 与 Page Chat 关联保持私密。
- **Hub skill 安装** —— `POST /api/multi-user/admin/skills/install`（admin-only）把 ClawHub 等外部 hub 的 skill 导入 admin catalog。安装 ≠ 分配：在 grant 分配之前，其他用户看不到这个 skill，admin 可以先自己验证。每次安装都进审计追踪。
- **审计追踪** —— 每次授权变更和被授权资源的访问都会追加到 `data/system/audit/usage.jsonl`。

## 普通用户得到什么

- **独立工作区**，在 `data/users/<uid>/` 下 —— 自己的对话历史（`chat_history.db`）、记忆、笔记本和个人知识库。只有 Docker 内容工作区是共享的。
- **只读访问** admin 分配的知识库和 skill，在他们自己的资源旁边以 "Assigned by admin" 徽章并列展示。
- **受限的共享书访问** —— 获准的管理员书可以只读，也可以协作编辑；标准内容保持共享，而每位读者的进度、书签、测验作答、capture 与 Page Chat 关联保持私密。
- **删减版设置页面** —— 展示主题、语言、已授权模型摘要、自己的 **OpenAI Codex** 登录、学习者账号的 Learner profile，以及获授权时的 Guardian 管理。API key、base URL 和 provider endpoint 不会返回给非 admin 请求。
- **作用域内的 LLM** —— 对话轮次通过 admin 分配的模型走。如果没有授权的 LLM，那一轮会被直接拒绝（不会偷偷 fallback 到 admin 的 key）。
- **作用域内的工具** —— 输入框、`/settings/tools` 页面以及每一轮对话都只暴露授权白名单内的系统工具、MCP 工具和 CLI 应用；代码执行在部署沙箱策略之上再尊重每用户开关。

## 工作区布局

所有数据都在 `data/` 下 —— 挂载和备份只需要这一棵树：

```text
data/
├── user/                        # Admin 工作区（设置、API key、admin 任务）
├── system/
│   ├── auth/users.json          # 凭证哈希、角色、逐用户 Book ACL
│   ├── auth/auth_secret         # JWT 签名密钥（自动生成）
│   ├── auth/device_credentials.json # 可撤销的学习者设备凭据
│   ├── guardians.json           # Guardian ↔ learner 授权关系
│   ├── grants/<uid>.json        # 每个用户的资源授权（admin 管理）
│   ├── audit/usage.jsonl        # 审计追踪
│   └── user-secrets/<owner>/    # 按归属账号存放的凭据（Codex OAuth 令牌）
├── cli-apps/                    # 已安装的 CLI 应用（沙箱内只读）
├── users/<uid>/
│   ├── user/
│   │   ├── chat_history.db
│   │   ├── settings/interface.json
│   │   └── workspace/{chat,co-writer,book,...}
│   ├── memory/
│   └── knowledge_bases/...
└── partners/<id>/               # Partner 工作区
```

从 v1.5 之前的布局（与 `data/` 平级的 `multi-user/` 目录）升级的部署会在首次启动时自动迁移：`multi-user/_system` 移到 `data/system`，每个 `multi-user/<uid>` 移到 `data/users/<uid>`。

## 配置参考

| 设置 | 必填 | 说明 |
|------|------|------|
| `data/user/settings/auth.json: enabled` | 是 | 设为 `true` 开启多用户 auth。默认 `false`（单用户模式 —— 各处都走 admin 路径）。 |
| `data/system/auth/auth_secret` | 推荐 | JWT 签名密钥。首次带认证启动时，若缺失会自动生成。 |
| `data/user/settings/auth.json: token_expire_hours` | 否 | JWT 寿命；默认 `24`。 |
| `data/user/settings/auth.json: cookie_secure` | HTTPS / 跨站认证 | 设为 `true` 后 session cookie 使用 `SameSite=None; Secure`。本地 HTTP 保持 `false`。 |
| `data/user/settings/auth.json: username` / `password_hash` | 否 | 可选的 headless 单用户引导凭证。用浏览器注册时留空。 |
| `data/user/settings/system.json` | 否 | `deeptutor start` 会从运行时设置推导前端 auth flag、public API base 和 CORS origins。 |

## 重要注意事项

> ⚠️ **PocketBase 模式（设置了 `integrations.pocketbase_url`）只支持单用户。** 默认 PocketBase schema 在 `users` 上没有 `role` 字段（每次登录解析为 `role=user`，无法创建 admin），因此即便 `sessions` 记录现在已按 `user_id` 隔离，PocketBase 仍无法支撑真正的多用户部署。多用户部署必须把 `integrations.pocketbase_url` 留空，使用默认的 JSON/SQLite 后端。

> ⚠️ **单进程引导。** “第一个用户自动提升为 admin” 由进程内的 `threading.Lock` 保护。先开启 auth，只启动一个后端进程并注册首位 admin，再增加 workers。`auth.json.enabled=false` 时注册端点会直接拒绝请求。

## 生产 checklist

- ✅ 设置一个强 `auth_secret` 并备份
- ✅ 在 `auth.json` 里设 `cookie_secure: true`，让 session cookie 必须走 HTTPS
- ✅ 把 DeepTutor 放在反向代理后面（Caddy、nginx、Traefik），用 TLS termination，指向前端端口（前端会在内部把 `/api/*` 转发给后端 —— 除非后端和前端分开跑，否则不需要配置 API base）
- ✅ auth 开启且 Web/API 跨 origin 时，把 `cors_origins` 设成精确前端 origin
- ✅ 定期备份 `data/` —— 账号、授权和所有工作区都在这一棵树下
- ✅ Docker：保留 `docker-compose.yml` 里的 `./data:/app/data` 卷。runner 不再挂载 `data/user/workspace` 和 `data/users`，改为只读挂载 `/workspace` 加可写的 `/workspace/outputs`，`DEEPTUTOR_RUNNER_ALLOWED_WORKDIRS=/workspace/outputs` 拒绝其他 workdir。`data/system`、`data/users` 与 admin 的 `data/user/settings` 都不再可见
- ✅ Docker：三个 Compose 文件都设了 `DEEPTUTOR_WORKSPACE_ROOT=/workspace`，所有账号（含 admin）共用这一个内容工作区，而非各自的 `data/users/<uid>/user/workspace`

## Caddyfile 示例

```text
deeptutor.example.com {
    reverse_proxy localhost:3782
}
```

前端会自己把 `/api/*` 和 `/ws/*` 转发给后端，所以只要一条指向前端端口的 `reverse_proxy` 就够了。然后在 `data/user/settings/system.json` 里只配 CORS（这种单机部署不需要 API base）：

```json
{
  "cors_origins": ["https://deeptutor.example.com"]
}
```

只有**拆分部署**（后端在另一台主机/容器上）才需要 API base —— 把 `next_public_api_base` 设成后端的内网地址；它由前端代理在服务端读取，不会发给浏览器。`public_api_base` 和 `next_public_api_base_external` 作为更低优先级的回退被接受。

在 `data/user/settings/auth.json` 里：

```json
{
  "enabled": true,
  "token_expire_hours": 24,
  "cookie_secure": true
}
```

## 常见错误

### 开启 auth 后 `404 /register`

前端 bundle 可能被缓存了。用 Docker 的话，重新创建容器。从源码起的话，编辑完 `auth.json` 后重启 `deeptutor start`。

### 第一次登录能进但没有 admin 链接

确认 `data/system/auth/users.json` 里第一个用户的 `"role": "admin"`。如果不是，手动改掉并重启。

### 重启后所有请求都返回 401，像是被登出

`auth_secret` 丢了或被重新生成，旧 token 无法解码；服务端不会专门报错，只会当作未认证处理。从备份恢复 secret，或者接受新的 secret 然后要求所有用户重新登录。

## headless 单用户引导

对于没人能在浏览器里注册的自动化场景，直接在 `auth.json` 里设凭证：

```json
{
  "enabled": true,
  "username": "alice",
  "password_hash": "<bcrypt-hash>",
  "token_expire_hours": 24
}
```

生成 hash：

```python
import bcrypt
print(bcrypt.hashpw(b"your-password", bcrypt.gensalt()).decode())
```

然后 `deeptutor start`，用 `alice` + your-password 登录。

更多修复方法：[**故障排查**](/zh-cn/get-started/troubleshooting/)。
