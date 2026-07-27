# Codex 远程 OAuth 引导 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让远程部署的 DeepTutor 在打开 OpenAI 授权页前展示实际 loopback 回调端口和可执行的 SSH 转发指引，同时保持本地一键登录、PKCE/state 和账号隔离行为不变。

**Architecture:** 后端继续只监听服务器 loopback，并在登录开始/状态响应中公开不敏感的 callback 元数据。Web 根据浏览器当前 hostname 判断是否需要远程引导；本地沿用预开窗口，远程先显示 SSH 命令再由用户显式打开授权页。CLI、错误文案和 README 使用同一套实际端口信息。

**Tech Stack:** Python 3.11+、asyncio、FastAPI、Typer、pytest/pytest-asyncio、Next.js 16、React 19、TypeScript、Node test runner、i18next、SSH loopback forwarding。

---

## 文件职责

- `deeptutor/services/codex_auth/service.py`：创建登录操作，输出 callback 元数据和 SSH 命令模板。
- `deeptutor/services/codex_auth/oauth.py`：维护 loopback listener，并产生包含实际端口的超时错误。
- `tests/services/codex_auth/test_service.py`：验证登录/状态公共契约、端口一致性和无敏感字段。
- `tests/services/codex_auth/test_oauth.py`：验证 callback 超时错误包含实际端口。
- `web/lib/codex-oauth.ts`：定义公共类型、hostname 判定、SSH 命令生成和稳定 JSON 错误。
- `web/components/settings/CodexOAuthCard.tsx`：实现本地一键流与远程引导流。
- `web/tests/codex-oauth-client.test.ts`：验证纯函数、错误映射和本地/远程交互契约。
- `web/tests/codex-oauth-settings-contract.test.ts`：验证中英文键和远程引导文案完整。
- `web/locales/en/app.json`、`web/locales/zh/app.json`：远程登录、复制、callback 和代理错误文案。
- `deeptutor_cli/provider_cmd.py`：输出 callback、授权 URL 和 SSH 模板。
- `tests/cli/test_provider_cli.py`：验证 CLI 输出和现有退出行为。
- `README.md`、`assets/README/README_CN.md`、`deeptutor_cli/README.md`：记录远程部署操作。

### Task 1: 建立干净基线

**Files:**
- Verify: `tests/services/codex_auth/test_oauth.py`
- Verify: `tests/services/codex_auth/test_service.py`
- Verify: `tests/cli/test_provider_cli.py`
- Verify: `web/tests/codex-oauth-client.test.ts`
- Verify: `web/tests/codex-oauth-settings-contract.test.ts`

- [ ] **Step 1: 安装 Web 锁定依赖**

Run:

```powershell
npm ci
```

Working directory: `web`

Expected: exit 0；只生成被忽略的 `web/node_modules`，`package-lock.json` 无修改。

- [ ] **Step 2: 运行现有 Python Codex 测试**

Run:

```powershell
C:\Users\15694\.venv\Scripts\python.exe -m pytest `
  tests/services/codex_auth/test_oauth.py `
  tests/services/codex_auth/test_service.py `
  tests/cli/test_provider_cli.py -q
```

Expected: exit 0，0 failed。

- [ ] **Step 3: 运行现有 Web Node 测试**

Run:

```powershell
npm run test:node
```

Working directory: `web`

Expected: exit 0，0 failed。

- [ ] **Step 4: 确认基线未产生跟踪修改**

Run:

```powershell
git status --short
```

Expected: empty。

### Task 2: 后端公开实际 callback 元数据

**Files:**
- Modify: `tests/services/codex_auth/test_service.py`
- Modify: `tests/services/codex_auth/test_oauth.py`
- Modify: `deeptutor/services/codex_auth/service.py`
- Modify: `deeptutor/services/codex_auth/oauth.py`

- [ ] **Step 1: 编写登录开始公共契约失败测试**

在 `test_successful_live_login_keeps_the_existing_model_selection` 中把返回字段断言改为：

```python
assert started["callback_port"] == 1455
assert started["redirect_uri"] == "http://localhost:1455/auth/callback"
assert started["ssh_forward_command"] == (
    "ssh -N -L 1455:127.0.0.1:1455 <ssh-user>@<server-host>"
)
assert set(started) == {
    "operation_id",
    "authorize_url",
    "expires_in",
    "callback_port",
    "redirect_uri",
    "ssh_forward_command",
}
```

新增测试验证等待和超时后的 `public_status()` 仍返回同一个
`callback_port`/`redirect_uri`，并确认序列化响应不含
`state_secret`、`pkce`、`verifier`、token、account ID。

- [ ] **Step 2: 运行测试确认 RED**

Run:

```powershell
C:\Users\15694\.venv\Scripts\python.exe -m pytest `
  tests/services/codex_auth/test_service.py::test_successful_live_login_keeps_the_existing_model_selection `
  tests/services/codex_auth/test_service.py::test_login_status_keeps_callback_metadata_after_timeout -q
```

Expected: FAIL，因为当前响应没有 `callback_port`、`redirect_uri` 和
`ssh_forward_command`。

- [ ] **Step 3: 最小实现 callback 元数据**

在 `service.py` 新增：

```python
def ssh_forward_command(port: int) -> str:
    return (
        f"ssh -N -L {port}:127.0.0.1:{port} "
        "<ssh-user>@<server-host>"
    )
```

扩展 `_login_start_payload()`：

```python
return {
    "operation_id": operation.operation_id,
    "authorize_url": operation.authorize_url,
    "expires_in": max(0, int(operation.deadline - self._clock())),
    "callback_port": operation.callback.port,
    "redirect_uri": operation.redirect_uri,
    "ssh_forward_command": ssh_forward_command(operation.callback.port),
}
```

扩展 `public_status()`：

```python
"callback_port": operation.callback.port if operation is not None else None,
"redirect_uri": operation.redirect_uri if operation is not None else None,
```

- [ ] **Step 4: 编写实际端口超时错误失败测试**

在 `test_loopback_timeout_and_cancel_are_public_errors` 中增加：

```python
assert f"localhost:{timed_out.port}" in timeout_error.value.public_message
assert "did not receive" in timeout_error.value.public_message
```

- [ ] **Step 5: 运行超时测试确认 RED**

Run:

```powershell
C:\Users\15694\.venv\Scripts\python.exe -m pytest `
  tests/services/codex_auth/test_oauth.py::test_loopback_timeout_and_cancel_are_public_errors -q
```

Expected: FAIL，因为当前错误仅为 `Codex sign-in timed out.`。

- [ ] **Step 6: 最小实现准确超时错误**

把 `LoopbackCallback.wait()` 的 `login_timeout` 公共消息改为：

```python
(
    f"The DeepTutor server did not receive the Codex OAuth callback "
    f"on localhost:{self.port}. For a remote deployment, keep the SSH "
    "port-forwarding tunnel open and try again."
)
```

- [ ] **Step 7: 运行后端测试确认 GREEN**

Run:

```powershell
C:\Users\15694\.venv\Scripts\python.exe -m pytest `
  tests/services/codex_auth/test_oauth.py `
  tests/services/codex_auth/test_service.py -q
```

Expected: exit 0，0 failed。

- [ ] **Step 8: 提交后端契约**

```powershell
git add deeptutor/services/codex_auth/service.py `
  deeptutor/services/codex_auth/oauth.py `
  tests/services/codex_auth/test_service.py `
  tests/services/codex_auth/test_oauth.py
git commit -m "修复：公开远程 OAuth 回调端口与准确超时提示"
```

### Task 3: 增加 Web 远程判定和稳定 API 错误

**Files:**
- Modify: `web/tests/codex-oauth-client.test.ts`
- Modify: `web/lib/codex-oauth.ts`

- [ ] **Step 1: 编写 hostname 和 SSH 命令失败测试**

在 `web/tests/codex-oauth-client.test.ts` 导入并测试：

```typescript
for (const host of [
  "localhost",
  "deeptutor.localhost",
  "127.0.0.1",
  "127.12.34.56",
  "::1",
  "[::1]",
]) {
  assert.equal(isLoopbackHostname(host), true);
}
for (const host of ["192.168.1.10", "deeptutor.example.com", "10.0.0.8"]) {
  assert.equal(isLoopbackHostname(host), false);
}
assert.equal(
  buildSshForwardCommand(1457, "deeptutor.example.com"),
  "ssh -N -L 1457:127.0.0.1:1457 <ssh-user>@deeptutor.example.com",
);
```

- [ ] **Step 2: 运行 Web 测试确认 RED**

Run:

```powershell
npm run test:node
```

Working directory: `web`

Expected: TypeScript 编译失败，因为两个 helper 尚不存在。

- [ ] **Step 3: 实现公共类型和纯函数**

扩展 `CodexLoginStart`：

```typescript
export type CodexLoginStart = {
  operation_id: string;
  authorize_url: string;
  expires_in: number;
  callback_port: number;
  redirect_uri: string;
  ssh_forward_command: string;
};
```

扩展 `CodexOAuthStatus`：

```typescript
callback_port: number | null;
redirect_uri: string | null;
```

新增：

```typescript
export function isLoopbackHostname(hostname: string): boolean {
  const normalized = hostname.trim().toLowerCase();
  if (
    normalized === "localhost" ||
    normalized.endsWith(".localhost") ||
    normalized === "::1" ||
    normalized === "[::1]"
  ) {
    return true;
  }
  const match = /^127\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$/.exec(normalized);
  return Boolean(
    match &&
      match.slice(1).every((part) => Number(part) >= 0 && Number(part) <= 255),
  );
}

export function buildSshForwardCommand(
  port: number,
  hostname: string,
): string {
  return (
    `ssh -N -L ${port}:127.0.0.1:${port} ` +
    `<ssh-user>@${hostname || "<server-host>"}`
  );
}
```

- [ ] **Step 4: 编写 2xx 非 JSON 失败测试**

将 `request` 导出为测试可调用的 `requestCodex`，使用可注入 fetch 或现有
`apiFetch` mock，断言 200 HTML 响应抛出：

```typescript
await assert.rejects(
  () => requestCodex("/oauth/status", "GET", fakeFetchReturningHtml),
  (error: unknown) =>
    error instanceof CodexOAuthApiError &&
    error.code === "invalid_response",
);
```

- [ ] **Step 5: 运行测试确认 RED**

Run: `npm run test:node`

Expected: FAIL，当前 `response.ok` 分支直接执行 `response.json()` 并抛出原始
解析错误。

- [ ] **Step 6: 实现稳定 JSON 错误**

把成功响应解析包在 `try/catch` 中；解析失败时抛出：

```typescript
throw new CodexOAuthApiError(
  "invalid_response",
  "DeepTutor returned an invalid Codex OAuth response.",
);
```

不得把 HTML 或 content-type 拼进错误。

- [ ] **Step 7: 运行测试确认 GREEN 并提交**

Run: `npm run test:node`

Expected: exit 0，0 failed。

```powershell
git add web/lib/codex-oauth.ts web/tests/codex-oauth-client.test.ts
git commit -m "修复：识别远程 OAuth 访问并稳定代理错误"
```

### Task 4: 实现远程引导 UI

**Files:**
- Modify: `web/tests/codex-oauth-client.test.ts`
- Modify: `web/components/settings/CodexOAuthCard.tsx`

- [ ] **Step 1: 编写本地与远程交互契约失败测试**

保留已有“本地登录在等待 API 前预开窗口”断言，并新增源码契约：

```typescript
assert.match(source, /isLoopbackHostname\(window\.location\.hostname\)/);
assert.match(source, /setLoginStart\(started\)/);
assert.match(source, /buildSshForwardCommand/);
assert.match(source, /codex\.oauth\.openAuthorization/);
```

同时限定 `window.open("about:blank"` 只位于 loopback 分支，远程分支先
`await startCodexLogin()`，不调用 `location.assign()`。

- [ ] **Step 2: 运行测试确认 RED**

Run: `npm run test:node`

Expected: FAIL，因为当前组件没有远程分支或 `loginStart` 状态。

- [ ] **Step 3: 最小实现双路径登录**

组件增加：

```typescript
const [loginStart, setLoginStart] = useState<CodexLoginStart | null>(null);
const remoteAccess =
  typeof window !== "undefined" &&
  !isLoopbackHostname(window.location.hostname);
```

`signIn()` 逻辑：

```typescript
if (remoteAccess) {
  setPending(true);
  try {
    const started = await startCodexLogin();
    setLoginStart(started);
    setStatus(await getCodexStatus());
  } finally {
    setPending(false);
  }
  return;
}
// 原有预开窗口逻辑保持不变
```

远程操作进行中时显示：

```typescript
const sshCommand = loginStart
  ? buildSshForwardCommand(
      loginStart.callback_port,
      window.location.hostname,
    )
  : null;
```

提供“复制命令”“打开 OpenAI 授权页”“取消”。复制失败时显示稳定 toast，
不输出剪贴板异常；打开授权页必须来自用户点击并使用
`window.open(loginStart.authorize_url, "_blank", "noopener")`。

- [ ] **Step 4: 运行 Web 测试确认 GREEN**

Run: `npm run test:node`

Expected: exit 0，0 failed。

- [ ] **Step 5: 提交 UI 行为**

```powershell
git add web/components/settings/CodexOAuthCard.tsx `
  web/tests/codex-oauth-client.test.ts
git commit -m "修复：为远程 Codex 登录增加 SSH 隧道引导"
```

### Task 5: 增加可操作的中英文错误与引导文案

**Files:**
- Modify: `web/tests/codex-oauth-settings-contract.test.ts`
- Modify: `web/lib/codex-oauth.ts`
- Modify: `web/locales/en/app.json`
- Modify: `web/locales/zh/app.json`

- [ ] **Step 1: 编写文案键失败测试**

要求中英文都包含：

```typescript
for (const key of [
  "codex.oauth.remoteTitle",
  "codex.oauth.remoteSteps",
  "codex.oauth.callbackAddress",
  "codex.oauth.copyCommand",
  "codex.oauth.commandCopied",
  "codex.oauth.copyFailed",
  "codex.oauth.openAuthorization",
  "codex.oauth.callbackMissing",
  "codex.oauth.callbackUnavailable",
  "codex.oauth.invalidResponse",
]) {
  assert.ok(codexKeys(en).includes(key));
}
```

并新增 error code 映射断言：

```typescript
assert.equal(codexErrorMessageKey("login_timeout"), "codex.oauth.callbackMissing");
assert.equal(
  codexErrorMessageKey("callback_unavailable"),
  "codex.oauth.callbackUnavailable",
);
assert.equal(
  codexErrorMessageKey("invalid_response"),
  "codex.oauth.invalidResponse",
);
```

- [ ] **Step 2: 运行测试确认 RED**

Run: `npm run test:node`

Expected: FAIL，因为键和映射尚不存在。

- [ ] **Step 3: 添加映射和中英文文案**

中文核心文案：

```json
"codex.oauth.callbackMissing": "DeepTutor 服务器未在 localhost:{{port}} 收到 OAuth 回调。远程部署请保持 SSH 隧道运行并重试。",
"codex.oauth.invalidResponse": "DeepTutor OAuth 接口返回了异常响应。请检查反向代理是否正确转发 /api/v1/settings/providers/openai-codex/。"
```

英文文案表达相同含义。`codexErrorMessageKey()` 使用上述稳定 key，不回落到
通用 `requestFailed`。

- [ ] **Step 4: 运行 Web 测试和 i18n 检查**

Run:

```powershell
npm run test:node
npm run i18n:check
```

Expected: 两条命令 exit 0。

- [ ] **Step 5: 提交文案**

```powershell
git add web/lib/codex-oauth.ts `
  web/locales/en/app.json `
  web/locales/zh/app.json `
  web/tests/codex-oauth-settings-contract.test.ts
git commit -m "文案：说明远程 OAuth 回调与反向代理错误"
```

### Task 6: 让 CLI 输出远程登录信息

**Files:**
- Modify: `tests/cli/test_provider_cli.py`
- Modify: `deeptutor_cli/provider_cmd.py`

- [ ] **Step 1: 扩展 fake 响应并编写失败断言**

`_FakeCliCodexService.start_login()` 增加：

```python
"callback_port": 1457,
"redirect_uri": "http://localhost:1457/auth/callback",
"ssh_forward_command": (
    "ssh -N -L 1457:127.0.0.1:1457 <ssh-user>@<server-host>"
),
```

在 CLI 测试中断言：

```python
assert "http://localhost:1457/auth/callback" in result.stdout
assert "ssh -N -L 1457:127.0.0.1:1457" in result.stdout
assert "https://auth.openai.com/oauth/authorize" in result.stdout
```

- [ ] **Step 2: 运行测试确认 RED**

Run:

```powershell
C:\Users\15694\.venv\Scripts\python.exe -m pytest `
  tests/cli/test_provider_cli.py::test_cli_opens_authorize_url_and_waits_for_completion -q
```

Expected: FAIL，因为 CLI 尚未打印 callback 和 SSH 信息。

- [ ] **Step 3: 实现 CLI 输出**

在尝试 `webbrowser.open()` 前输出：

```python
typer.echo(f"Callback: {started['redirect_uri']}")
typer.echo(f"Authorization URL: {authorize_url}")
typer.echo(
    "Remote server? Keep this tunnel running before opening the URL: "
    f"{started['ssh_forward_command']}"
)
```

本地浏览器打开、失败、取消和退出码逻辑不变。

- [ ] **Step 4: 运行 CLI 测试确认 GREEN 并提交**

Run:

```powershell
C:\Users\15694\.venv\Scripts\python.exe -m pytest tests/cli/test_provider_cli.py -q
```

Expected: exit 0，0 failed。

```powershell
git add deeptutor_cli/provider_cmd.py tests/cli/test_provider_cli.py
git commit -m "修复：CLI 显示远程 OAuth 隧道命令"
```

### Task 7: 更新远程部署文档

**Files:**
- Modify: `README.md`
- Modify: `assets/README/README_CN.md`
- Modify: `deeptutor_cli/README.md`
- Modify: `tests/cli/test_provider_cli.py`

- [ ] **Step 1: 编写文档契约失败测试**

在 `test_readmes_match_the_cli_contract` 增加：

```python
for document in (ROOT_README, CLI_README):
    self.assertIn("ssh -N -L", document)
    self.assertIn("1455", document)
    self.assertIn("1457", document)
```

再读取 `assets/README/README_CN.md`，断言包含“浏览器的 localhost”和
“服务器的 localhost”不是同一台机器的说明。

- [ ] **Step 2: 运行测试确认 RED**

Run:

```powershell
C:\Users\15694\.venv\Scripts\python.exe -m pytest `
  tests/cli/test_provider_cli.py::ProviderCliDocsContractTest::test_readmes_match_the_cli_contract -q
```

Expected: FAIL，因为现有文档仅说“在服务器运行 CLI”，没有端口转发步骤。

- [ ] **Step 3: 更新英文与中文文档**

文档必须包含：

```bash
ssh -N -L 1455:127.0.0.1:1455 <ssh-user>@<server-host>
```

并说明如果 1455 被占用，必须使用页面/CLI 显示的 1457，而不是同时开放两个
端口。强调 SSH 隧道应在打开授权 URL 前建立，并保持到页面报告登录成功。

- [ ] **Step 4: 运行文档契约确认 GREEN 并提交**

Run:

```powershell
C:\Users\15694\.venv\Scripts\python.exe -m pytest tests/cli/test_provider_cli.py -q
```

Expected: exit 0，0 failed。

```powershell
git add README.md assets/README/README_CN.md `
  deeptutor_cli/README.md tests/cli/test_provider_cli.py
git commit -m "文档：补充服务器 Codex OAuth 端口转发说明"
```

### Task 8: 完整验证与服务器远程验收

**Files:**
- Verify: all modified files
- Do not modify: production server deployment

- [ ] **Step 1: 运行针对性 Python 回归**

```powershell
C:\Users\15694\.venv\Scripts\python.exe -m pytest `
  tests/services/codex_auth/test_oauth.py `
  tests/services/codex_auth/test_service.py `
  tests/cli/test_provider_cli.py -q
```

Expected: exit 0，0 failed。

- [ ] **Step 2: 运行 Web 测试、类型/构建和 i18n**

```powershell
npm run test:node
npm run i18n:check
npm run build
```

Working directory: `web`

Expected: 三条命令均 exit 0。

- [ ] **Step 3: 运行格式和差异检查**

```powershell
git diff --check origin/main...HEAD
git status --short
```

Expected: 无 whitespace 错误；状态只包含预期提交后的空工作区。

- [ ] **Step 4: 只读核验服务器目标**

从本机 SSH 配置解析用户明确授权的服务器 alias，执行：

```powershell
ssh -o BatchMode=yes -o ConnectTimeout=8 <server-alias> `
  "uname -a && python3 --version && command -v deeptutor || true"
```

Expected: SSH 成功；不修改生产目录或进程。

- [ ] **Step 5: 在服务器临时目录验证 loopback 拓扑**

使用服务器临时目录和临时 Python 进程启动 `LoopbackCallback`，选取实际
1455/1457。客户端建立：

```powershell
ssh -N -L <port>:127.0.0.1:<port> <server-alias>
```

随后从客户端向：

```text
http://localhost:<port>/auth/callback?code=non-secret-test&state=test-state
```

发送模拟请求。Expected: 服务器 callback future 收到 code/state；listener
仍只绑定 loopback。测试结束后终止临时进程并确认端口释放。

- [ ] **Step 6: 真实浏览器 UI 验收**

在不覆盖生产部署的临时服务或本地模拟远程 hostname 环境中确认：

- 非 loopback 页面点击登录不会自动跳转；
- 页面显示实际 callback 端口和 SSH 命令；
- 显式“打开授权页”按钮存在；
- 本地 localhost 页面仍一键打开；
- 浏览器控制台 0 个新增 error。

若真实 OpenAI 授权需要账户确认，停在授权页并请用户操作；不得读取或输出
凭据。

- [ ] **Step 7: 最终审查和中文提交**

确认每一处变更都能追溯到规格，且无公网 callback、设备流或相邻重构。若完整
验证产生必要修复，测试先行并单独提交：

```powershell
git commit -m "测试：补强远程 Codex OAuth 回归验证"
```

- [ ] **Step 8: 准备 PR**

总结根因、交互变化、安全边界、测试命令和服务器验收结果。推送分支和创建 PR
前再次确认工作区干净；PR 标题使用：

```text
fix: guide remote Codex OAuth loopback callbacks
```

PR 正文不包含服务器地址、用户名、token、account ID 或内部路径。
