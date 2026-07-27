# DeepTutor 远程部署 Codex OAuth 引导设计

## 背景与根因

DeepTutor 的 Codex OAuth 使用 PKCE 和一次性 loopback 回调。后端只在运行
DeepTutor 的机器上监听 `127.0.0.1`/`::1` 的 1455 或 1457 端口，而授权 URL
固定使用 `http://localhost:<port>/auth/callback`。

当用户通过另一台电脑的浏览器访问远程 DeepTutor 时，授权完成后的
`localhost` 指向浏览器所在电脑，不是 DeepTutor 服务器。现有 Web UI 又会
无条件在该浏览器中打开授权页，因此服务器永远收不到回调，最后只能报告
超时或通用请求错误。这是 loopback 回调的部署拓扑问题，不是普通代理路由
问题。

## 本次范围

本次保留 OpenAI 已接受的 loopback redirect URI，不引入公网回调服务，也不
改变 state、PKCE、令牌存储和账号隔离。

交付内容：

1. 本地访问继续保持一键打开授权页。
2. 非 loopback 地址访问时不自动打开授权页，先展示远程登录步骤。
3. 后端公开本次实际回调端口、redirect URI 和 SSH 转发命令模板。
4. UI 显示带实际端口和当前访问主机的可复制 SSH 命令。
5. 用户建立隧道后，通过显式按钮打开授权页；同时提供“无需隧道，直接继续”
   的高级入口，避免对特殊本地部署的误判形成死路。
6. CLI 输出实际回调端口、授权 URL 和 SSH 转发命令模板。
7. 将回调未到达服务器、API/反向代理返回非 JSON 两类错误分开说明。
8. 更新英文主 README、中文 README 和中文 CLI 文档。

不在本次范围：

- OAuth 设备授权流程；
- 公网 HTTPS callback；
- 自动配置 SSH、反向代理或防火墙；
- 修改 OpenAI OAuth 客户端注册；
- 在远程生产部署中自动安装未发布代码。

## 后端数据契约

`POST /api/v1/settings/providers/openai-codex/oauth/start` 在现有字段之外返回：

```json
{
  "operation_id": "...",
  "authorize_url": "https://auth.openai.com/...",
  "expires_in": 300,
  "callback_port": 1455,
  "redirect_uri": "http://localhost:1455/auth/callback",
  "ssh_forward_command": "ssh -N -L 1455:127.0.0.1:1455 <ssh-user>@<server-host>"
}
```

OAuth 状态接口在操作存在期间也返回 `callback_port` 和 `redirect_uri`，使页面
轮询、刷新或超时后仍能显示本次操作对应的端口。公共响应不得包含 token、
account ID、email 或 PKCE verifier。

`ssh_forward_command` 是明确标注占位符的完整模板。浏览器 UI 用当前页面的
hostname 替换 `<server-host>`；`<ssh-user>` 保留给用户填写，因为 HTTP 请求
无法可靠推断 SSH 用户名。反向代理域名不等于 SSH 主机时，用户可以直接编辑
复制后的命令。

## Web 交互

新增纯函数：

- `isLoopbackHostname(hostname)`：识别 `localhost`、`*.localhost`、
  `127.0.0.0/8`、`::1` 和 `[::1]`。
- `buildSshForwardCommand(port, hostname)`：生成只转发实际回调端口的命令。

本地流程：

1. 用户点击“使用 Codex 登录”。
2. UI 先预开空白窗口，避免浏览器弹窗拦截。
3. 后端启动 callback listener。
4. 空白窗口跳转到 `authorize_url`。
5. 页面轮询状态并沿用现有完成逻辑。

远程流程：

1. 用户点击“使用 Codex 登录”。
2. UI 调用后端启动 callback listener，但不打开授权页。
3. 卡片展示实际端口、redirect URI、SSH 命令、剩余时间和三个动作：
   “复制命令”“打开 OpenAI 授权页”“取消”。
4. 用户先在本机终端保持 SSH 命令运行，再显式打开授权页。
5. 对于浏览器虽然使用域名但实际运行在服务器上的情况，用户可直接点击
   “打开 OpenAI 授权页”，无需额外隧道。

远程检测只决定交互提示，不参与安全判断；服务端仍只信任 state、PKCE 和
loopback callback。

## 错误处理

- `login_timeout`：显示“DeepTutor 服务器未在 localhost:<port> 收到 OAuth
  回调；远程部署请保持 SSH 隧道并重试。”
- `callback_unavailable`：显示服务器无法监听 1455/1457，请检查端口占用。
- OAuth 状态 API 返回 2xx 但不是 JSON：前端转换为稳定的
  `invalid_response`，提示检查反向代理是否把
  `/api/v1/settings/providers/openai-codex/*` 路由到 DeepTutor 后端。
- 不向用户显示原始 HTML、content-type、上游 OAuth 响应正文或凭据。
- 取消、state 不匹配、拒绝授权和目录刷新错误继续使用现有独立错误码。

## CLI 行为

`deeptutor provider login openai-codex` 启动监听后，先输出：

- callback 地址；
- 授权 URL；
- 使用实际端口的 SSH 转发模板。

CLI 仍尝试打开本机浏览器；无图形环境或远程服务器上打开失败时，用户已拥有
完整的隧道和授权指引，不再只得到一个最终会回到错误 localhost 的 URL。

## 安全边界

- callback 继续只绑定 loopback，不监听 `0.0.0.0`。
- redirect URI 继续使用 OpenAI 客户端允许的 `http://localhost:<port>`。
- state 使用常量时间比较，PKCE verifier 不进入任何公共响应。
- SSH 命令只转发单个 callback 端口，不建议开放公网端口。
- OAuth 凭据继续存放在当前用户的
  `<user-root>/private/openai-codex/`，不跨账号共享。
- 浏览器 hostname 仅用于生成提示命令，不被后端当作可信身份信息。

## 测试计划

后端：

- 登录启动响应包含实际 callback 端口、redirect URI 和一致的 SSH 模板。
- 1455 被占用时所有字段同步使用 1457。
- 状态响应在等待和超时后保留 callback 元数据。
- callback listener 仍只绑定 loopback。
- 公共响应不包含 token、account ID、email 或 PKCE verifier。

前端：

- loopback hostname 判定覆盖 IPv4、IPv6、localhost 子域和远程域名/IP。
- SSH 命令使用实际端口并正确处理普通域名和 IPv6 host。
- 本地流程仍在等待 API 前预开窗口。
- 远程流程不会自动打开授权 URL，而是渲染显式继续按钮。
- `login_timeout`、`callback_unavailable`、`invalid_response` 映射到中英文
  稳定文案。
- 中英文 OAuth key 保持一致。

CLI：

- 输出实际 callback 地址、授权 URL 和 SSH 转发模板。
- 成功、失败和取消行为保持现有退出码。

真实远程验收：

1. 在服务器临时目录和独立端口运行待测分支，不覆盖生产安装。
2. 从客户端通过非 localhost 地址访问设置页，确认不会自动跳转。
3. 确认页面显示后端实际选中的 1455 或 1457。
4. 建立页面给出的 SSH 隧道。
5. 用无敏感参数的模拟 callback 请求验证服务器 listener 能收到回调。
6. 如需执行真实 OpenAI 授权，由用户在授权页面确认；测试过程不读取、输出或
   复制 OAuth 凭据。

## 验收标准

- 本地 OAuth 登录行为无回归。
- 远程用户在打开授权页前即可获得可执行的端口转发指引。
- 页面、CLI 和后端状态报告同一个实际 callback 端口。
- 远程 callback 通过 SSH 隧道到达服务器。
- 回调缺失和反向代理响应异常有不同且可操作的错误提示。
- 新增测试通过，现有 Codex OAuth 后端、前端和 CLI 测试全部通过。
