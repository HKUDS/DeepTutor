# DeepTutor Codex OAuth Provider Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 DeepTutor v1.5.3 中实现完全独立于 `~/.codex` 的 Codex OAuth、账户动态模型目录，以及只有实时目录精确包含 `gpt-5.6-sol` 时的自动切换，并最终通过独立功能分支提交 Pull Request。

**Architecture:** 新增 `deeptutor.services.codex_auth` 作为唯一认证边界，分别封装类型、私有存储、OAuth loopback、模型目录和业务编排；现有 `OpenAICodexProvider` 只从该边界取得短期 token，不再访问 `oauth-cli-kit` 的 Codex 存储。Settings API 暴露脱敏操作状态，Web 通过一个 Codex OAuth 卡片启动登录并刷新现有模型目录；其他 Provider 和聊天架构不变。

**Tech Stack:** Python 3.11+、FastAPI、httpx、asyncio、pytest、Next.js 16、React 19、TypeScript、Node test runner、CSSwitch MIT 参考实现、OpenAI Codex 官方源码兼容契约。

---

## 0. 审计基线与交付边界

实现前固定以下上游审计记录：

- DeepTutor：`v1.5.3` / `3a19752a449c5adb09546add8cad0c6ebd6efc33`
- 设计提交：`d404e5a7`
- OpenAI Codex：`81da9deb065d7adb283816b19b40f89bcc484276`
- OpenAI Codex 发布版：`rust-v0.145.0`，模型请求 `client_version=0.145.0`
- CSSwitch：`4e0af6ba7909dca22f1257b168172ecbe4af4836`
- 目标 PR：`feat/codex-oauth-provider` → `HKUDS/DeepTutor:main`

官方源码核对结果：

```text
issuer       = https://auth.openai.com
client_id    = app_EMoamEEZ73f0CkXaXp7hrann
scope        = openid profile email offline_access api.connectors.read api.connectors.invoke
callback     = http://localhost:{1455|1457}/auth/callback
token        = https://auth.openai.com/oauth/token
revoke       = https://auth.openai.com/oauth/revoke
models       = https://chatgpt.com/backend-api/codex/models
responses    = https://chatgpt.com/backend-api/codex/responses
```

这些端点属于实验性 Codex 兼容面，不被描述成稳定公开 API。

- [x] **Step 0.1: 准备被 Git 忽略的本地 worktree 目录**

```powershell
git check-ignore -q .worktrees/probe
```

Expected: exit 0，证明 `.worktrees/` 不会进入版本控制。

- [x] **Step 0.2: 从已提交设计与计划的当前 HEAD 创建隔离功能 worktree**

```powershell
git worktree add '.worktrees/feat-codex-oauth-provider' `
  -b feat/codex-oauth-provider HEAD
git -C '.worktrees/feat-codex-oauth-provider' merge-base --is-ancestor origin/main HEAD
git -C '.worktrees/feat-codex-oauth-provider' rev-list --left-right --count origin/main...HEAD
```

Expected: worktree 和新分支创建成功；`origin/main` 是 HEAD 的祖先；右侧计数只包含设计、
计划和后续功能提交。

- [x] **Step 0.3: 修复 Windows 下 Web Node 测试入口**

在 Windows 上，`spawnSync()` 直接启动 `node_modules/.bin/tsc` 会返回 `EINVAL`。新增回归测试，
并改为用当前 Node 进程执行 TypeScript 的 JavaScript 入口：

```javascript
run(process.execPath, [
  path.join(webRoot, "node_modules", "typescript", "bin", "tsc"),
  "-p",
  "tsconfig.node-tests.json",
]);
```

验证：

```powershell
Set-Location web
npm run test:node
npx tsc --noEmit
```

Expected: Windows 回归测试、全部 Node 测试和 TypeScript 检查通过。

## 1. 文件结构

### 新增后端文件

- `deeptutor/services/codex_auth/__init__.py`
  - 导出服务入口和公开数据类型。
- `deeptutor/services/codex_auth/constants.py`
  - 集中保存已经审计的 OAuth、目录、Responses 和版本常量。
- `deeptutor/services/codex_auth/contracts.py`
  - 只包含凭据、模型、目录快照、状态、错误和 JWT 最小解析。
- `deeptutor/services/codex_auth/storage.py`
  - DeepTutor 私有目录、跨平台锁、原子写入、generation 和缓存文件。
- `deeptutor/services/codex_auth/oauth.py`
  - PKCE、authorize URL、loopback callback、token exchange/refresh/revoke。
- `deeptutor/services/codex_auth/catalog.py`
  - `/models` 请求、解析、ETag、5 分钟新鲜缓存和 24 小时最后可用缓存。
- `deeptutor/services/codex_auth/service.py`
  - 登录 operation、目录同步、Sol 自动切换、登出回退和推理活动计数。

### 新增后端测试

- `tests/services/codex_auth/test_contracts.py`
- `tests/services/codex_auth/test_storage.py`
- `tests/services/codex_auth/test_oauth.py`
- `tests/services/codex_auth/test_catalog.py`
- `tests/services/codex_auth/test_service.py`
- `tests/services/llm/test_openai_codex_oauth_provider.py`

### 修改后端文件

- `deeptutor/services/config/model_catalog.py`
- `deeptutor/services/provider_registry.py`
- `deeptutor/api/routers/settings.py`
- `deeptutor/services/llm/provider_core/openai_codex_provider.py`
- `deeptutor_cli/provider_cmd.py`
- `tests/services/test_model_catalog.py`
- `tests/services/test_provider_registry.py`
- `tests/api/test_settings_router.py`
- `tests/cli/test_provider_cli.py`
- `tests/services/llm/test_codex_disable_ssl_verify.py`

### 新增 Web 文件

- `web/lib/codex-oauth.ts`
  - API 类型、请求函数和脱敏状态到文案键的纯函数。
- `web/components/settings/CodexOAuthCard.tsx`
  - 登录、轮询、取消、刷新、登出和结果反馈。
- `web/tests/codex-oauth-client.test.ts`
- `web/tests/codex-oauth-settings-contract.test.ts`

### 修改 Web 与文档文件

- `web/components/settings/SettingsContext.tsx`
- `web/components/settings/ServiceConfigEditor.tsx`
- `web/locales/en/app.json`
- `web/locales/zh/app.json`
- `README.md`
- `deeptutor_cli/README.md`
- `THIRD_PARTY_NOTICES.md`

## 2. 任务拆分

### Task 1: 建立 Codex 兼容常量、类型与最小 JWT 解析

**Files:**

- Create: `deeptutor/services/codex_auth/constants.py`
- Create: `deeptutor/services/codex_auth/contracts.py`
- Create: `deeptutor/services/codex_auth/__init__.py`
- Test: `tests/services/codex_auth/test_contracts.py`

- [x] **Step 1: 写失败测试，固定上游常量和 JWT 只取必要字段**

```python
def test_codex_upstream_contract_is_pinned() -> None:
    assert CODEX_OAUTH_CLIENT_ID == "app_EMoamEEZ73f0CkXaXp7hrann"
    assert CODEX_CALLBACK_PORTS == (1455, 1457)
    assert CODEX_CLIENT_VERSION == "0.145.0"
    assert CODEX_MODELS_URL.endswith("/backend-api/codex/models")


def test_decode_token_claims_drops_email() -> None:
    token = jwt_for_test(
        {
            "exp": 2_000_000_000,
            "email": "must-not-leave-backend@example.test",
            "https://api.openai.com/auth": {
                "chatgpt_account_id": "account-123",
                "chatgpt_plan_type": "plus",
            },
        }
    )
    claims = decode_codex_jwt(token)
    assert claims == TokenClaims(expires_at=2_000_000_000, account_id="account-123")
    assert "email" not in repr(claims).lower()
```

- [x] **Step 2: 运行测试并确认因模块不存在而失败**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/services/codex_auth/test_contracts.py -q
```

Expected: collection fails with `ModuleNotFoundError: deeptutor.services.codex_auth`.

- [x] **Step 3: 实现最小常量与不可变数据契约**

`constants.py` 必须集中定义：

```python
CODEX_UPSTREAM_COMMIT = "81da9deb065d7adb283816b19b40f89bcc484276"
CODEX_CLIENT_VERSION = "0.145.0"
CODEX_OAUTH_ISSUER = "https://auth.openai.com"
CODEX_OAUTH_CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
CODEX_OAUTH_SCOPE = (
    "openid profile email offline_access "
    "api.connectors.read api.connectors.invoke"
)
CODEX_OAUTH_ORIGINATOR = "codex_cli_rs"
CODEX_CALLBACK_PORTS = (1455, 1457)
CODEX_CALLBACK_PATH = "/auth/callback"
CODEX_LOGIN_TIMEOUT_SECONDS = 300
CODEX_TOKEN_URL = f"{CODEX_OAUTH_ISSUER}/oauth/token"
CODEX_REVOKE_URL = f"{CODEX_OAUTH_ISSUER}/oauth/revoke"
CODEX_MODELS_URL = "https://chatgpt.com/backend-api/codex/models"
CODEX_RESPONSES_URL = "https://chatgpt.com/backend-api/codex/responses"
CODEX_FRESH_CACHE_SECONDS = 300
CODEX_STALE_CACHE_SECONDS = 86_400
CODEX_MAX_MODELS = 512
CODEX_MAX_CATALOG_BYTES = 8 * 1024 * 1024
CODEX_DEFAULT_MODEL = "gpt-5.6-sol"
```

`contracts.py` 定义并完整序列化以下类型：

```python
@dataclass(frozen=True)
class TokenClaims:
    expires_at: int | None
    account_id: str | None


@dataclass(frozen=True)
class CodexCredentials:
    schema_version: int
    access_token: str
    refresh_token: str
    id_token: str
    account_id: str
    expires_at: int
    generation: int

    def public_token(self) -> "CodexToken":
        return CodexToken(
            access_token=self.access_token,
            account_id=self.account_id,
            expires_at=self.expires_at,
            generation=self.generation,
        )


@dataclass(frozen=True)
class CodexToken:
    access_token: str
    account_id: str
    expires_at: int
    generation: int


@dataclass(frozen=True)
class CodexModel:
    slug: str
    display_name: str
    priority: int
    visibility: str
    default_reasoning_level: str | None
    supported_reasoning_levels: tuple[str, ...]
    supports_reasoning_summary: bool
    supports_parallel_tool_calls: bool
    use_responses_lite: bool


@dataclass(frozen=True)
class CatalogSnapshot:
    models: tuple[CodexModel, ...]
    source: Literal["live", "fresh-cache", "revalidated-cache", "stale-cache"]
    fetched_at: int
    etag: str | None
    generation: int
    account_hash: str
```

`decode_codex_jwt()` 仅 Base64URL 解码 JWT payload，不保存或返回 email；账户 ID 依次从
`https://api.openai.com/auth.chatgpt_account_id` 和显式 token response 字段取得。TLS token
exchange 是信任边界，JWT 解码不被描述成签名验证。

`CodexAuthError` 固定包含 `code`、`public_message` 和 `http_status`，`str(error)` 只能返回
公开消息。

- [x] **Step 4: 运行测试确认通过**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/services/codex_auth/test_contracts.py -q
```

Expected: all tests pass.

- [x] **Step 5: 中文提交**

```powershell
git add deeptutor/services/codex_auth tests/services/codex_auth/test_contracts.py
git commit -m "feat: 定义 Codex OAuth 兼容契约"
```

### Task 2: 实现独立私有凭据存储、文件锁与 generation

**Files:**

- Create: `deeptutor/services/codex_auth/storage.py`
- Test: `tests/services/codex_auth/test_storage.py`

- [x] **Step 1: 写失败测试覆盖路径、原子提交、并发和 `~/.codex` 隔离**

```python
def test_store_is_scoped_below_deeptutor_user_root(tmp_path: Path) -> None:
    store = CodexCredentialStore(tmp_path)
    assert store.root == tmp_path / "private" / "openai-codex"
    assert ".codex" not in str(store.root)


def test_refresh_generation_cannot_overwrite_new_login(tmp_path: Path) -> None:
    store = CodexCredentialStore(tmp_path)
    first = store.commit_credentials(credentials("old"), expected_generation=0)
    second = store.commit_credentials(credentials("new"), expected_generation=first.generation)
    with pytest.raises(CodexAuthError, match="changed"):
        store.commit_credentials(credentials("late-refresh"), expected_generation=first.generation)
    assert store.load_credentials().access_token == second.access_token


def test_store_never_calls_path_home(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: (_ for _ in ()).throw(AssertionError())))
    store = CodexCredentialStore(tmp_path)
    store.commit_credentials(credentials("token"), expected_generation=0)
    store.clear_credentials(expected_generation=1)
```

另写测试覆盖：

- `credentials.v1.json`、`state.v1.json`、`models-cache.v1.json` 和 `auth.lock`；
- JSON 损坏返回 `credential_corrupt`；
- 临时文件不会残留；
- 符号链接和 Windows reparse point 被拒绝；
- 登出递增 generation，迟到刷新不能复活凭据；
- 两个线程同时刷新只有一个 generation 可以提交；
- 支持平台上的 owner-only 权限。

- [x] **Step 2: 运行测试确认失败**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/services/codex_auth/test_storage.py -q
```

Expected: import or attribute failures.

- [x] **Step 3: 实现存储**

`CodexCredentialStore` 的公开接口固定为 `current_generation()`、`load_credentials()`、
`commit_credentials()`（接收 credentials 和整数 expected_generation）、
`clear_credentials()`（接收整数或 None 的 expected_generation）、`load_state()`、
`save_state(state)`、`load_catalog_cache()`、`save_catalog_cache(payload)` 和
`clear_catalog_cache()`。构造函数只接受 DeepTutor `user_root`，并把 `root` 固定为
`user_root / "private" / "openai-codex"`。

实现要求：

```python
@contextmanager
def _locked_file(path: Path) -> Iterator[BinaryIO]:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as handle:
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"\0")
            handle.flush()
        handle.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield handle
        finally:
            handle.seek(0)
            if os.name == "nt":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp_path, stat.S_IRUSR | stat.S_IWUSR)
        os.replace(temp_path, path)
    finally:
        temp_path.unlink(missing_ok=True)
```

所有读写前调用 `_assert_safe_regular_path()`；该函数拒绝 `Path.is_symlink()` 和
`stat.FILE_ATTRIBUTE_REPARSE_POINT`。`clear_credentials()` 在锁内先写入新的持久化
generation，再删除凭据与模型缓存。

- [x] **Step 4: 运行存储测试**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/services/codex_auth/test_storage.py -q
```

Expected: all tests pass.

- [x] **Step 5: 中文提交**

```powershell
git add deeptutor/services/codex_auth/storage.py tests/services/codex_auth/test_storage.py
git commit -m "feat: 添加 Codex 独立凭据存储"
```

### Task 3: 实现 PKCE、loopback callback 与 OAuth HTTP 客户端

**Files:**

- Create: `deeptutor/services/codex_auth/oauth.py`
- Test: `tests/services/codex_auth/test_oauth.py`

- [x] **Step 1: 写失败测试**

```python
def test_authorize_url_matches_audited_codex_contract() -> None:
    pkce = PkceCodes(verifier="v" * 64, challenge="challenge")
    url = build_authorize_url(
        redirect_uri="http://localhost:1455/auth/callback",
        state="state-123",
        pkce=pkce,
    )
    query = parse_qs(urlsplit(url).query)
    assert query["client_id"] == [CODEX_OAUTH_CLIENT_ID]
    assert query["scope"] == [CODEX_OAUTH_SCOPE]
    assert query["code_challenge_method"] == ["S256"]
    assert query["state"] == ["state-123"]
    assert query["id_token_add_organizations"] == ["true"]
    assert query["codex_cli_simplified_flow"] == ["true"]


@pytest.mark.asyncio
async def test_loopback_accepts_one_matching_callback() -> None:
    callback = await LoopbackCallback.start(ports=(0,))
    await send_get(
        callback.port,
        "/auth/callback?code=secret-code&state=expected",
    )
    result = await callback.wait(timeout=1)
    assert result.code == "secret-code"
    assert result.state == "expected"
```

另写测试覆盖错误 path、OAuth error query、取消、超时、1455 被占用后使用 1457、只绑定
`127.0.0.1`、HTML 响应不回显 code/state，以及 token exchange/refresh/revoke 的请求体。

- [x] **Step 2: 运行测试确认失败**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/services/codex_auth/test_oauth.py -q
```

Expected: missing `oauth` module.

- [x] **Step 3: 实现 OAuth 边界**

以下数据结构作为固定接口：

```python
@dataclass(frozen=True)
class PkceCodes:
    verifier: str
    challenge: str


@dataclass(frozen=True)
class OAuthCallbackResult:
    code: str | None
    state: str | None
    error: str | None
```

`LoopbackCallback` 实现 `start(ports)`、`wait(timeout)` 和 `cancel()`；
`CodexOAuthClient` 实现 `exchange_code(code, redirect_uri, verifier)`、`refresh(refresh_token)`
和 `revoke(credentials)`。每个方法的返回类型分别为 callback 实例、
`OAuthCallbackResult`、`None`、token mapping、token mapping 和 `None`。

授权码交换使用 `application/x-www-form-urlencoded`；刷新使用官方当前 JSON 请求：

```json
{
  "client_id": "app_EMoamEEZ73f0CkXaXp7hrann",
  "grant_type": "refresh_token",
  "refresh_token": "test-refresh-token"
}
```

撤销优先 refresh token，并发送 `token_type_hint=refresh_token` 和 client ID；失败只抛
脱敏异常。httpx 异常和上游 body 不进入普通日志。

- [x] **Step 4: 运行 OAuth 测试**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/services/codex_auth/test_oauth.py -q
```

Expected: all tests pass.

- [x] **Step 5: 中文提交**

```powershell
git add deeptutor/services/codex_auth/oauth.py tests/services/codex_auth/test_oauth.py
git commit -m "feat: 实现 Codex 浏览器 OAuth 流程"
```

### Task 4: 实现真实账户模型目录、ETag 与缓存隔离

**Files:**

- Create: `deeptutor/services/codex_auth/catalog.py`
- Test: `tests/services/codex_auth/test_catalog.py`
- Add fixture: `tests/services/codex_auth/fixtures/models-response.json`

- [x] **Step 1: 写官方 schema 风格 fixture 与失败测试**

Fixture 至少包含：

```json
{
  "models": [
    {
      "slug": "gpt-5.6-sol",
      "display_name": "GPT-5.6-Sol",
      "visibility": "list",
      "priority": 1,
      "default_reasoning_level": "medium",
      "supported_reasoning_levels": [
        {"effort": "medium", "description": "Balanced"},
        {"effort": "high", "description": "Deeper"}
      ],
      "supports_reasoning_summary_parameter": true,
      "supports_parallel_tool_calls": true,
      "use_responses_lite": false
    },
    {
      "slug": "internal-hidden",
      "display_name": "Hidden",
      "visibility": "hide",
      "priority": 0,
      "supported_reasoning_levels": []
    }
  ]
}
```

测试：

```python
def test_parse_catalog_keeps_only_picker_visible_raw_models(fixture_json) -> None:
    models = parse_models_response(fixture_json)
    assert [model.slug for model in models] == ["gpt-5.6-sol"]
    assert models[0].display_name == "GPT-5.6-Sol"


@pytest.mark.asyncio
async def test_live_catalog_uses_account_headers_and_client_version(
    catalog: CodexModelCatalog,
    credentials: CodexCredentials,
    transport: RecordingTransport,
) -> None:
    snapshot = await catalog.get(credentials, force=True)
    request = transport.requests[0]
    assert request.url.params["client_version"] == "0.145.0"
    assert request.headers["chatgpt-account-id"] == "account-123"
    assert snapshot.source == "live"
```

另覆盖：

- `supports_reasoning_summary_parameter` 和 CSSwitch 旧字段
  `supports_reasoning_summaries` 的兼容解析；
- 按 `priority, slug` 排序；
- 512 模型和 8 MiB 上限；
- ETag/304；
- 5 分钟新鲜缓存；
- 网络失败时同 account hash + generation 的 24 小时 stale cache；
- 旧 generation、另一账户、401 和 403 不使用缓存；
- stale cache 不能作为自动切换依据。

- [x] **Step 2: 运行目录测试确认失败**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/services/codex_auth/test_catalog.py -q
```

Expected: missing `catalog` module.

- [x] **Step 3: 实现目录客户端**

`CodexModelCatalog` 构造函数接受 `CodexCredentialStore`、可注入的
`httpx.AsyncClient` 和 `clock`。公开异步方法固定为
`get(credentials, force: bool) -> CatalogSnapshot` 与 `invalidate() -> None`。

账户分区键：

```python
account_hash = hashlib.sha256(credentials.account_id.encode("utf-8")).hexdigest()
```

请求头只包括需要的认证和兼容字段；日志不得记录 headers。401/403 抛出固定
`catalog_unauthorized` / `catalog_forbidden` 并清缓存。只有 HTTP 200 或 304 能产生
`live` / `revalidated-cache`；磁盘新鲜缓存为 `fresh-cache`，网络降级为 `stale-cache`。

- [x] **Step 4: 运行目录测试**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/services/codex_auth/test_catalog.py -q
```

Expected: all tests pass.

- [x] **Step 5: 中文提交**

```powershell
git add deeptutor/services/codex_auth/catalog.py tests/services/codex_auth
git commit -m "feat: 添加 Codex 动态模型目录"
```

### Task 5: 增加原子模型目录更新与受管理 Codex Profile

**Files:**

- Modify: `deeptutor/services/config/model_catalog.py`
- Test: `tests/services/test_model_catalog.py`
- Test: `tests/services/codex_auth/test_service.py`

- [x] **Step 1: 写失败测试固定受管理条目和回退语义**

```python
def test_sync_creates_read_only_managed_codex_profile(tmp_path: Path) -> None:
    service = ModelCatalogService(tmp_path / "model_catalog.json")
    original = seeded_catalog(provider="siliconflow", model="deepseek-ai/DeepSeek-V3")
    service.save(original)

    result = sync_codex_catalog(
        service,
        live_snapshot("gpt-5.6-sol", "gpt-5.6-terra"),
        activate_sol=True,
        state={},
    )

    profile = next(
        p for p in result.catalog["services"]["llm"]["profiles"]
        if p.get("managed_by") == "openai_codex_oauth"
    )
    assert profile["binding"] == "openai_codex"
    assert profile["api_key"] == ""
    assert result.auto_switched is True
    assert result.previous_selection == {
        "profile_id": original["services"]["llm"]["active_profile_id"],
        "model_id": original["services"]["llm"]["active_model_id"],
    }


def test_stale_or_missing_sol_never_changes_active_selection(
    tmp_path: Path,
) -> None:
    catalog_service = ModelCatalogService(tmp_path / "model_catalog.json")
    original = seeded_catalog(provider="siliconflow", model="deepseek-ai/DeepSeek-V3")
    catalog_service.save(original)
    result = sync_codex_catalog(
        catalog_service,
        snapshot_with_models("stale-cache", ["gpt-5.6-sol"]),
        activate_sol=True,
        state={},
    )
    assert result.auto_switched is False
    assert active_selection(result.catalog) == active_selection(original)
```

另覆盖：

- 精确、大小写敏感的 `gpt-5.6-sol`；
- display name 或 alias 不触发；
- 刷新目录更新/移除受管理模型但不碰其他 Profile；
- 登出时当前仍为受管理模型才恢复备份；
- 用户已切到其他 Provider 时登出不覆盖；
- 备份模型已删除时保持当前选择；
- 聊天历史文件不被访问。

- [x] **Step 2: 运行测试确认失败**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/services/test_model_catalog.py tests/services/codex_auth/test_service.py -q
```

Expected: missing atomic update and sync functions.

- [x] **Step 3: 给 `ModelCatalogService` 增加最小原子更新能力**

新增实例锁和方法：

```python
def update(self, mutator: Callable[[dict[str, Any]], None]) -> dict[str, Any]:
    with self._lock:
        catalog = self.load()
        mutator(catalog)
        return self.save(catalog)
```

`save()` 改为同目录临时文件、UTF-8 flush/fsync、`os.replace()`；不修改 catalog schema 的
既有默认值。

- [x] **Step 4: 在 `service.py` 实现目录同步纯函数**

稳定 ID：

```python
MANAGED_BY = "openai_codex_oauth"
CODEX_PROFILE_ID = "llm-profile-openai-codex-managed"


def codex_model_id(slug: str) -> str:
    digest = hashlib.sha256(slug.encode("utf-8")).hexdigest()[:16]
    return f"llm-model-openai-codex-{digest}"
```

受管理模型保留：

```python
{
    "id": codex_model_id(model.slug),
    "name": model.display_name,
    "model": model.slug,
    "managed_by": MANAGED_BY,
    "codex_priority": model.priority,
    "codex_default_reasoning_level": model.default_reasoning_level,
    "codex_supported_reasoning_levels": list(model.supported_reasoning_levels),
    "codex_supports_reasoning_summary": model.supports_reasoning_summary,
    "codex_supports_parallel_tool_calls": model.supports_parallel_tool_calls,
    "codex_use_responses_lite": model.use_responses_lite,
}
```

- [x] **Step 5: 运行目录同步测试**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/services/test_model_catalog.py tests/services/codex_auth/test_service.py -q
```

Expected: all selected tests pass.

- [x] **Step 6: 中文提交**

```powershell
git add deeptutor/services/config/model_catalog.py deeptutor/services/codex_auth/service.py tests/services
git commit -m "feat: 同步受管理的 Codex 模型配置"
```

### Task 6: 编排登录 operation、token 刷新、登出与推理活动

**Files:**

- Modify: `deeptutor/services/codex_auth/service.py`
- Modify: `deeptutor/services/codex_auth/__init__.py`
- Test: `tests/services/codex_auth/test_service.py`

- [x] **Step 1: 扩展失败测试覆盖完整状态机**

```python
@pytest.mark.asyncio
async def test_successful_live_login_switches_only_exact_sol(
    service_fixture: ServiceFixture,
) -> None:
    service = service_fixture.service
    callback = service_fixture.callback
    started = await service.start_login()
    await callback.complete_from_authorize_url(
        started["authorize_url"],
        code="code",
    )
    await wait_until_terminal(service)
    status = service.public_status()
    assert status["connection"] == "connected"
    assert status["operation_state"] == "completed"
    assert status["catalog_source"] == "live"
    assert status["active_model"] == "gpt-5.6-sol"
    assert status["auto_switched"] is True


@pytest.mark.asyncio
async def test_catalog_failure_keeps_auth_but_not_selection(
    catalog_failure_fixture: ServiceFixture,
) -> None:
    service = catalog_failure_fixture.service
    original_selection = active_selection(
        catalog_failure_fixture.model_catalog.load()
    )
    started = await service.start_login()
    await catalog_failure_fixture.callback.complete_from_authorize_url(
        started["authorize_url"],
        code="code",
    )
    await wait_until_terminal(service)
    assert service.public_status()["connection"] == "connected"
    assert active_selection(catalog_failure_fixture.model_catalog.load()) == original_selection


@pytest.mark.asyncio
async def test_logout_rejected_while_inference_is_active(
    connected_service: CodexOAuthService,
) -> None:
    service = connected_service
    async with service.inference_guard():
        with pytest.raises(CodexAuthError) as exc:
            await service.logout()
    assert exc.value.code == "inference_in_progress"
```

另覆盖：

- 一个管理员作用域只存在一个活动 operation；
- state mismatch、取消、超时、exchange 失败都不覆盖旧凭据；
- 凭据提交后目录失败仍保持 connected；
- refresh 在五分钟窗口内触发并验证 generation/account；
- 迟到 refresh 不能覆盖重登或登出；
- revoke 失败不阻止本地清理；
- operation 不持久化，重新实例化只恢复 connected 状态；
- public status 不含 token、email、完整 account ID 和上游正文。

- [x] **Step 2: 运行测试并确认失败**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/services/codex_auth/test_service.py -q
```

Expected: state-machine methods are missing.

- [x] **Step 3: 实现 `CodexOAuthService`**

`CodexOAuthService` 的公开接口固定为：

- `start_login() -> dict[str, Any]`
- `public_status() -> dict[str, Any]`
- `cancel_login() -> dict[str, Any]`
- `refresh_models() -> dict[str, Any]`
- `logout() -> dict[str, Any]`
- `get_token() -> CodexToken`
- `recover_after_unauthorized(generation: int) -> None`
- 异步 context manager `inference_guard()`

登录后台任务顺序固定为 callback → state → exchange → 原子提交 credentials →
`catalog.get(force=True)` → 同步受管理目录 → 精确 Sol 自动切换。每个阶段更新
`waiting/exchanging/fetching_models/completed`，所有失败只保存错误码。

`get_codex_oauth_service()` 以解析后的 `PathService.get_user_root()` 为 key 维护实例，构造：

```python
user_root = get_path_service().get_user_root()
store = CodexCredentialStore(user_root)
catalog = CodexModelCatalog(store)
return CodexOAuthService(store, catalog, get_model_catalog_service())
```

- [x] **Step 4: 运行服务测试**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/services/codex_auth -q
```

Expected: all Codex auth tests pass.

- [x] **Step 5: 中文提交**

```powershell
git add deeptutor/services/codex_auth tests/services/codex_auth
git commit -m "feat: 编排 Codex 登录与登出状态机"
```

### Task 7: 暴露 Provider 元数据和管理员 Settings OAuth API

**Files:**

- Modify: `deeptutor/services/provider_registry.py`
- Modify: `deeptutor/api/routers/settings.py`
- Modify: `tests/services/test_provider_registry.py`
- Modify: `tests/api/test_settings_router.py`

- [ ] **Step 1: 写失败测试**

```python
def test_openai_codex_provider_exposes_oauth_dynamic_policy() -> None:
    spec = find_by_name("openai_codex")
    assert spec.auth_mode == "oauth"
    assert spec.model_policy == "dynamic_catalog"
    assert spec.requires_api_key is False
    assert spec.experimental is True


@pytest.mark.asyncio
async def test_codex_oauth_status_is_admin_only(monkeypatch) -> None:
    monkeypatch.setattr(settings_router, "get_current_user", lambda: user(is_admin=False))
    with pytest.raises(HTTPException) as exc:
        await settings_router.get_openai_codex_oauth_status()
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_codex_oauth_start_returns_only_public_fields(monkeypatch) -> None:
    fake = FakeCodexService()
    monkeypatch.setattr(settings_router, "get_codex_oauth_service", lambda: fake)
    payload = await settings_router.start_openai_codex_oauth()
    assert set(payload) == {"operation_id", "authorize_url", "expires_in"}
    assert "token" not in json.dumps(payload).lower()
```

- [ ] **Step 2: 运行测试确认失败**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/services/test_provider_registry.py tests/api/test_settings_router.py -q
```

Expected: missing metadata and route functions.

- [ ] **Step 3: 扩展 Provider 元数据**

`ProviderSpec` 新增最小字段：

```python
model_policy: str = "configured"
experimental: bool = False
requires_api_key: bool = True

@property
def auth_mode(self) -> str:
    return "oauth" if self.is_oauth else "api_key"
```

`openai_codex` 指定 `model_policy="dynamic_catalog"`、`experimental=True` 和
`requires_api_key=False`；`github_copilot` 也显式指定 `requires_api_key=False`，避免改变
其既有 OAuth 语义。
`_provider_choices()` 返回 `auth_mode`、`model_policy`、`requires_api_key`、`experimental`。

- [ ] **Step 4: 新增五个管理员 API**

```python
@router.post("/providers/openai-codex/oauth/start")
async def start_openai_codex_oauth() -> dict[str, Any]:
    _require_settings_admin()
    return await get_codex_oauth_service().start_login()

@router.get("/providers/openai-codex/oauth/status")
async def get_openai_codex_oauth_status() -> dict[str, Any]:
    _require_settings_admin()
    return get_codex_oauth_service().public_status()

@router.post("/providers/openai-codex/oauth/cancel")
async def cancel_openai_codex_oauth() -> dict[str, Any]:
    _require_settings_admin()
    return await get_codex_oauth_service().cancel_login()

@router.post("/providers/openai-codex/oauth/logout")
async def logout_openai_codex_oauth() -> dict[str, Any]:
    _require_settings_admin()
    return await get_codex_oauth_service().logout()

@router.post("/providers/openai-codex/models/refresh")
async def refresh_openai_codex_models() -> dict[str, Any]:
    _require_settings_admin()
    return await get_codex_oauth_service().refresh_models()
```

每个入口先调用 `_require_settings_admin()`。`CodexAuthError` 转为
`HTTPException(status_code=error.http_status, detail={"code": error.code,
"message": error.public_message})`；Settings router 不记录异常对象或上游 body。

- [ ] **Step 5: 运行 API 测试**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/services/test_provider_registry.py tests/api/test_settings_router.py -q
```

Expected: all selected tests pass.

- [ ] **Step 6: 中文提交**

```powershell
git add deeptutor/services/provider_registry.py deeptutor/api/routers/settings.py tests
git commit -m "feat: 添加 Codex OAuth 设置接口"
```

### Task 8: 将现有 Responses Provider 切换到独立认证服务

**Files:**

- Modify: `deeptutor/services/llm/provider_core/openai_codex_provider.py`
- Modify: `tests/services/llm/test_codex_disable_ssl_verify.py`
- Create: `tests/services/llm/test_openai_codex_oauth_provider.py`

- [ ] **Step 1: 写失败测试固定不重放和不回退**

```python
@pytest.mark.asyncio
async def test_provider_uses_deeptutor_token_service_not_oauth_cli_kit(monkeypatch) -> None:
    service = FakeCodexService(
        token=CodexToken(
            access_token="test-access-token",
            account_id="account-123",
            expires_at=2_000_000_000,
            generation=7,
        )
    )
    monkeypatch.setattr(module, "get_codex_oauth_service", lambda: service)
    result = await OpenAICodexProvider().chat(
        [{"role": "user", "content": "hello"}],
        model="gpt-5.6-sol",
    )
    assert result.finish_reason == "stop"
    assert service.token_calls == 1


@pytest.mark.asyncio
async def test_401_refreshes_for_next_request_without_replay(
    monkeypatch,
    fake_codex_service: FakeCodexService,
) -> None:
    request_count = 0

    async def rejected_request(*args, **kwargs):
        nonlocal request_count
        request_count += 1
        raise CodexHTTPError(401, "Codex login expired.")

    monkeypatch.setattr(module, "get_codex_oauth_service", lambda: fake_codex_service)
    monkeypatch.setattr(module, "_request_codex", rejected_request)
    token = fake_codex_service.token
    result = await OpenAICodexProvider().chat(
        [{"role": "user", "content": "hello"}],
        model="gpt-5.6-sol",
    )
    assert request_count == 1
    assert fake_codex_service.recovered_generation == token.generation
    assert result.finish_reason == "error"


@pytest.mark.asyncio
async def test_429_never_reads_openai_api_key(
    monkeypatch,
    fake_codex_service: FakeCodexService,
    recording_transport: RecordingTransport,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-be-used")
    monkeypatch.setattr(module, "get_codex_oauth_service", lambda: fake_codex_service)
    recording_transport.respond_with(429, {"error": {"message": "rate limited"}})
    monkeypatch.setattr(module, "_request_codex", recording_transport.request_codex)
    result = await OpenAICodexProvider().chat(
        [{"role": "user", "content": "hello"}],
        model="gpt-5.6-sol",
    )
    assert "Codex usage quota" in result.content
    assert recording_transport.destinations == [CODEX_RESPONSES_URL]
```

另覆盖 account header、Sol 原始 ID、工具转换、reasoning、SSE、403 失效、网络错误和
推理 guard。

- [ ] **Step 2: 运行测试确认失败**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/services/llm/test_openai_codex_oauth_provider.py -q
```

Expected: provider still imports `oauth_cli_kit`.

- [ ] **Step 3: 最小修改 Provider**

修改要点：

```python
async def _load_token(self) -> CodexToken:
    return await get_codex_oauth_service().get_token()


service = get_codex_oauth_service()
async with service.inference_guard():
    token = await self._load_token()
    try:
        return await _request_codex(
            CODEX_RESPONSES_URL,
            _build_headers(token.account_id, token.access_token),
            body,
            verify=not disable_ssl_verify_enabled(),
            on_content_delta=on_content_delta,
        )
    except CodexHTTPError as exc:
        if exc.status_code == 401:
            await service.recover_after_unauthorized(token.generation)
        raise
```

`CodexHTTPError` 只保存 status 和安全消息；`_friendly_error()` 不拼接 raw response。
默认模型改为 `openai-codex/gpt-5.6-sol`，但活动模型仍由已验证 catalog 选择传入。
401 当前请求只调用一次 `_request_codex()`。

- [ ] **Step 4: 运行 Provider 回归**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest `
  tests/services/llm/test_openai_codex_oauth_provider.py `
  tests/services/llm/test_codex_disable_ssl_verify.py `
  tests/core/test_agentic_client_provider_kwargs.py -q
```

Expected: all selected tests pass.

- [ ] **Step 5: 中文提交**

```powershell
git add deeptutor/services/llm/provider_core/openai_codex_provider.py tests/services/llm
git commit -m "feat: 接入 DeepTutor 独立 Codex 凭据"
```

### Task 9: 让 CLI 复用同一认证服务

**Files:**

- Modify: `deeptutor_cli/provider_cmd.py`
- Modify: `tests/cli/test_provider_cli.py`

- [ ] **Step 1: 写失败测试**

```python
def test_openai_codex_cli_does_not_import_codex_cli_credentials() -> None:
    assert "oauth_cli_kit" not in PROVIDER_CMD
    assert "get_codex_oauth_service" in PROVIDER_CMD
    assert ".codex" not in PROVIDER_CMD


def test_cli_opens_authorize_url_and_waits_for_completion(monkeypatch) -> None:
    service = FakeCliCodexService()
    browser = RecordingBrowser()
    monkeypatch.setattr(provider_cmd, "get_codex_oauth_service", lambda: service)
    monkeypatch.setattr(provider_cmd.webbrowser, "open", browser.open)
    result = CliRunner().invoke(app, ["provider", "login", "openai-codex"])
    assert len(browser.urls) == 1
    assert browser.urls[0].startswith("https://auth.openai.com/oauth/authorize?")
    assert result.exit_code == 0
    assert "DeepTutor 私有凭据" in result.stdout
```

- [ ] **Step 2: 运行测试确认失败**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/cli/test_provider_cli.py -q
```

Expected: source contract still finds `oauth_cli_kit`.

- [ ] **Step 3: 改造 CLI**

CLI 使用 `maybe_run(_login_openai_codex())`。协程调用同一
`get_codex_oauth_service().start_login()`，用 `webbrowser.open(authorize_url)` 打开页面，
每 500ms 查询 public status，直至 completed/failed/expired/cancelled。Ctrl+C 调用
`cancel_login()`。

`oauth-cli-kit` 依赖继续保留给 GitHub Copilot，不再用于 OpenAI Codex。

- [ ] **Step 4: 运行 CLI 测试**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/cli/test_provider_cli.py -q
```

Expected: all tests pass.

- [ ] **Step 5: 中文提交**

```powershell
git add deeptutor_cli/provider_cmd.py tests/cli/test_provider_cli.py
git commit -m "feat: 统一 Codex Web 与 CLI 登录"
```

### Task 10: 新增 Web OAuth API 客户端和状态卡片

**Files:**

- Create: `web/lib/codex-oauth.ts`
- Create: `web/components/settings/CodexOAuthCard.tsx`
- Create: `web/tests/codex-oauth-client.test.ts`
- Modify: `web/components/settings/SettingsContext.tsx`

- [ ] **Step 1: 写纯函数失败测试**

```typescript
test("terminal operation states stop polling", () => {
  for (const state of ["completed", "cancelled", "expired", "failed"]) {
    assert.equal(shouldPollCodexStatus({ operation_state: state }), false);
  }
});

test("public types contain no secret fields", () => {
  const source = readFileSync(CODEX_CLIENT, "utf8");
  for (const forbidden of ["access_token", "refresh_token", "account_id", "email"]) {
    assert.equal(source.includes(forbidden), false);
  }
});

test("Sol missing message preserves the current model", () => {
  assert.equal(
    codexStatusMessageKey({ connection: "connected", sol_available: false }),
    "codex.oauth.solMissing",
  );
});
```

- [ ] **Step 2: 运行测试确认失败**

Run:

```powershell
Set-Location web
npm run test:node -- --test-name-pattern=Codex
Set-Location ..
```

Expected: module missing or compiled test failure.

- [ ] **Step 3: 实现 API 类型和请求函数**

`CodexOAuthStatus` 精确包含：

```typescript
export type CodexOAuthStatus = {
  connection: "disconnected" | "authorizing" | "connected" | "error";
  operation_id: string | null;
  operation_state:
    | "waiting"
    | "exchanging"
    | "fetching_models"
    | "completed"
    | "cancelled"
    | "expired"
    | "failed"
    | null;
  model_count: number;
  catalog_source: "live" | "fresh-cache" | "revalidated-cache" | "stale-cache" | null;
  catalog_fetched_at: number | null;
  active_model: string | null;
  auto_switched: boolean;
  sol_available: boolean;
  error_code: string | null;
};
```

导出 `getCodexStatus()`、`startCodexLogin()`、`cancelCodexLogin()`、
`refreshCodexModels()`、`logoutCodex()` 和纯函数 `shouldPollCodexStatus()`。

- [ ] **Step 4: 实现 `CodexOAuthCard`**

组件行为：

```tsx
const started = await startCodexLogin();
window.open(started.authorize_url, "_blank", "noopener,noreferrer");
setStatus(await getCodexStatus());
```

authorizing 时每秒轮询；进入终态即停止。completed、refresh 和 logout 后调用
`reloadSettings()`，使 catalog/draft 同步。按钮在请求中禁用，错误只使用稳定
`error_code` 到翻译键的映射。

- [ ] **Step 5: 扩展 Provider/Catalog TypeScript 类型**

`ProviderOption` 增加：

```typescript
auth_mode?: "api_key" | "oauth";
model_policy?: "configured" | "dynamic_catalog";
requires_api_key?: boolean;
experimental?: boolean;
```

`CatalogProfile` 和 `CatalogModel` 增加可选 `managed_by` 及 Codex capability 字段，类型与
Task 5 JSON 一致。

- [ ] **Step 6: 运行 Web 测试和 typecheck**

Run:

```powershell
Set-Location web
npm run test:node
npx tsc --noEmit
Set-Location ..
```

Expected: node tests and typecheck pass.

- [ ] **Step 7: 中文提交**

```powershell
git add web/lib/codex-oauth.ts web/components/settings/CodexOAuthCard.tsx web/tests web/components/settings/SettingsContext.tsx
git commit -m "feat: 添加 Codex OAuth 网页状态卡片"
```

### Task 11: 将 Settings 表单切换为 OAuth 体验并保护受管理模型

**Files:**

- Modify: `web/components/settings/ServiceConfigEditor.tsx`
- Modify: `web/locales/en/app.json`
- Modify: `web/locales/zh/app.json`
- Create: `web/tests/codex-oauth-settings-contract.test.ts`

- [ ] **Step 1: 写失败的 Settings 源码契约测试**

```typescript
test("Codex OAuth profile renders the OAuth card", () => {
  const source = readFileSync(EDITOR, "utf8");
  assert.match(source, /auth_mode === "oauth"/);
  assert.match(source, /<CodexOAuthCard/);
});

test("managed Codex profiles cannot expose API key or model editing", () => {
  const source = readFileSync(EDITOR, "utf8");
  assert.match(source, /managed_by === "openai_codex_oauth"/);
  assert.match(source, /isManagedCodex/);
});
```

- [ ] **Step 2: 运行测试确认失败**

Run:

```powershell
Set-Location web
npm run test:node
Set-Location ..
```

Expected: new contract tests fail.

- [ ] **Step 3: 修改 `ProfileFields`**

计算当前 Provider 元数据：

```tsx
const providerOption = (providers[service] || []).find(
  (option) => option.value === providerValue,
);
const isCodexOAuth =
  service === "llm" &&
  providerValue === "openai_codex" &&
  providerOption?.auth_mode === "oauth";
const isManagedCodex = profile.managed_by === "openai_codex_oauth";
```

`isCodexOAuth` 时在 Provider selector 下渲染 `<CodexOAuthCard />`，并且完全不渲染
Base URL、API Key、Extra headers 和手工新增模型。其他 OAuth Provider 保持现有渲染，
本功能不为其误用 Codex API。受管理 Profile：

- provider selector disabled；
-不能删除 Profile；
-不能双击重命名模型；
-不能删除或新增模型；
-仍可从受管理模型列表选择活动模型；
-“+ Profile”保留，使用户可以新增其他 Provider Profile。

- [ ] **Step 4: 添加中英文文案**

至少增加以下翻译键：

```json
{
  "codex.oauth.signIn": "使用 Codex 登录",
  "codex.oauth.waiting": "等待浏览器授权…",
  "codex.oauth.connected": "Codex 已连接",
  "codex.oauth.refresh": "刷新模型",
  "codex.oauth.logout": "退出 Codex",
  "codex.oauth.experimental": "实验性连接：上游 Codex 兼容接口可能变化。",
  "codex.oauth.isolated": "凭据只保存在 DeepTutor，不读取本机 Codex CLI 登录。",
  "codex.oauth.solActive": "已切换到 Codex / GPT-5.6-Sol。",
  "codex.oauth.solMissing": "当前账户目录未返回 gpt-5.6-sol，已保留原模型。",
  "codex.oauth.catalogFailed": "登录成功，但暂时无法读取模型目录，原模型未变。",
  "codex.oauth.inferenceActive": "请先停止当前 Codex 生成，再退出登录。"
}
```

英文文件提供等义英文，不把实验性接口描述为官方第三方 API。

- [ ] **Step 5: 运行 Web 完整检查**

Run:

```powershell
Set-Location web
npm run test:node
npm run lint
npm run i18n:check
npx tsc --noEmit
npm run build
Set-Location ..
```

Expected: all commands exit 0.

- [ ] **Step 6: 中文提交**

```powershell
git add web/components/settings/ServiceConfigEditor.tsx web/locales web/tests
git commit -m "feat: 在模型设置中启用 Codex OAuth"
```

### Task 12: 补充来源声明、中文文档和安全回归

**Files:**

- Create: `THIRD_PARTY_NOTICES.md`
- Modify: `README.md`
- Modify: `deeptutor_cli/README.md`
- Modify: all affected tests

- [ ] **Step 1: 写 CSSwitch MIT 来源声明**

`THIRD_PARTY_NOTICES.md` 包含：

```markdown
## CSSwitch

- Project: SuperJJ007/CSSwitch
- Source commit: 4e0af6ba7909dca22f1257b168172ecbe4af4836
- License: MIT
- Copyright: Copyright (c) 2026 shanjunjie
- Adapted concepts: PKCE loopback login, auth generation, atomic credential
  updates, model-catalog cache invalidation, and redacted operation states.

The MIT license text from the pinned source is reproduced below.
```

随后原样附上 CSSwitch `LICENSE` 的 MIT 正文。不得把 OpenAI Codex 源码复制进项目；官方
源码只作为协议核对来源。

- [ ] **Step 2: 更新中文 README**

Root README 和 CLI README 说明：

- Web 路径：Settings → Models → LLM → OpenAI Codex → 使用 Codex 登录；
- 凭据位于 `<user-root>/private/openai-codex/`；
- 不读取或同步 `~/.codex`；
- 不需要 `OPENAI_API_KEY`；
- 登录后目录含 `gpt-5.6-sol` 才自动切换；
- 429/上游失败不会自动转付费 Provider；
- 该 Codex backend 兼容路径是实验性的。

- [ ] **Step 3: 运行敏感信息静态回归**

Run:

```powershell
rg -n "access_token|refresh_token|chatgpt_account_id|email" `
  deeptutor/api/routers/settings.py `
  web/lib/codex-oauth.ts `
  web/components/settings/CodexOAuthCard.tsx
rg -n "oauth_cli_kit" `
  deeptutor/services/llm/provider_core/openai_codex_provider.py `
  deeptutor_cli/provider_cmd.py
rg -n "\\.codex" deeptutor/services/codex_auth deeptutor_cli/provider_cmd.py
```

Expected:

- API/Web 不出现 secret 字段；
- Codex Provider/CLI 不出现 `oauth_cli_kit`；
- auth 实现不出现 `~/.codex` 或 Codex CLI auth path；仅测试和用户文档可出现隔离说明。

- [ ] **Step 4: 运行后端聚焦测试**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest `
  tests/services/codex_auth `
  tests/services/llm/test_openai_codex_oauth_provider.py `
  tests/services/llm/test_codex_disable_ssl_verify.py `
  tests/services/test_model_catalog.py `
  tests/services/test_provider_registry.py `
  tests/api/test_settings_router.py `
  tests/cli/test_provider_cli.py `
  tests/core/test_agentic_client_provider_kwargs.py -q
```

Expected: all selected tests pass.

- [ ] **Step 5: 中文提交**

```powershell
git add THIRD_PARTY_NOTICES.md README.md deeptutor_cli/README.md tests
git commit -m "docs: 说明 Codex OAuth 安全边界与来源"
```

### Task 13: 全量验证、medium 深度审查、人工 OAuth 验收与 PR

**Files:**

- Review: every file changed from `origin/main...HEAD`
- Update only files needed to fix discovered issues

- [ ] **Step 1: 后端全量测试**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Expected: zero failures; existing environment-only skips are reported as skips.

- [ ] **Step 2: Python lint 与依赖检查**

Run:

```powershell
.\.venv\Scripts\python.exe -m ruff check deeptutor/services/codex_auth `
  deeptutor/services/llm/provider_core/openai_codex_provider.py `
  deeptutor/api/routers/settings.py `
  deeptutor_cli/provider_cmd.py `
  tests/services/codex_auth
.\.venv\Scripts\python.exe -m pip check
```

Expected: both commands exit 0.

- [ ] **Step 3: Web 全量验证**

Run:

```powershell
Set-Location web
npm run test:node
npm run lint
npm run i18n:check
npx tsc --noEmit
npm run build
Set-Location ..
```

Expected: all commands exit 0.

- [ ] **Step 4: medium 深度代码审查**

按 `origin/main...HEAD` 逐文件审查：

1. token/account/email 是否可能进入 response、日志、异常或 Settings；
2. 是否存在任何 `Path.home()`、`~/.codex` 或 Codex CLI 凭据导入；
3. callback 是否只绑定 loopback、校验 state、单次消费并按时关闭；
4. generation 是否覆盖登录、刷新、登出和迟到任务；
5. stale cache 是否绝不触发 Sol 自动切换；
6. 401 是否只发一次 Responses 请求；
7. 429/网络错误是否不存在其他 Provider fallback；
8. 登出是否尊重用户后来主动选择的 Provider；
9. managed profile 是否不会破坏其他 catalog 条目；
10. CSSwitch 复用是否有 MIT 声明且没有复制无关网关逻辑。

每个发现先写最小回归测试，再修复并重新运行相应测试。审查完成后运行：

```powershell
git diff --check origin/main...HEAD
git status --short
```

Expected: diff check clean；提交前工作树只包含有意修复。

- [ ] **Step 5: 用户在场的真实 OAuth 验收**

PowerShell 先生成不含内容的 `~/.codex` 元数据快照：

```powershell
$codexPath = Join-Path $env:USERPROFILE '.codex'
Get-ChildItem -LiteralPath $codexPath -File -Recurse -ErrorAction SilentlyContinue |
  Select-Object FullName,Length,LastWriteTimeUtc |
  Sort-Object FullName |
  ConvertTo-Json -Depth 3 |
  Set-Content -LiteralPath (Join-Path $env:TEMP 'deeptutor-codex-before.json') -Encoding UTF8
```

启动 DeepTutor 后由用户点击一次 OAuth：

1. Web 只出现 OAuth 跳转，不出现 API Key/Base URL。
2. 登录后模型目录来自账户实时响应。
3. 若含原始 `gpt-5.6-sol`，活动模型变为 Sol；否则原模型不变。
4. 运行普通聊天、reasoning 和一次工具调用。
5. 登出前停止生成；登出后凭据清理、目录移除、模型按规则恢复。
6. 重新生成 `~/.codex` 元数据快照并用 `Compare-Object` 确认无变化。

- [ ] **Step 6: 最终验证提交**

如果审查或人工验收产生修复：

```powershell
git add -- deeptutor deeptutor_cli tests web README.md THIRD_PARTY_NOTICES.md
git commit -m "fix: 修正 Codex OAuth 验收问题"
```

随后重新执行 Steps 1–4 的全部自动验证。

- [ ] **Step 7: 推送功能分支**

```powershell
git push -u fork feat/codex-oauth-provider
```

Expected: remote branch created or updated successfully.

- [ ] **Step 8: 创建 Pull Request**

PR 标题：

```text
feat: 为 DeepTutor 添加独立 Codex OAuth 与动态模型目录
```

PR body 使用中文，包含：

- 背景与现状修正；
- 独立凭据和 `~/.codex` 隔离；
- Web OAuth 与 CLI 共用服务；
- 动态目录与 Sol 精确自动切换；
- 401/429/no-fallback 安全策略；
- CSSwitch MIT 来源与 OpenAI Codex 审计基线；
- 自动测试命令和结果；
- 真实 OAuth 验收结果；
- 实验性上游兼容风险。

先通过 `apply_patch` 创建
`C:\Users\15694\AppData\Local\Temp\deeptutor-codex-oauth-pr.md`，正文逐项写入上述实际
验证结果。随后使用：

```powershell
gh pr create `
  --repo HKUDS/DeepTutor `
  --base main `
  --head TyrionH-is-coding:feat/codex-oauth-provider `
  --title "feat: 为 DeepTutor 添加独立 Codex OAuth 与动态模型目录" `
  --body-file "$env:TEMP\deeptutor-codex-oauth-pr.md"
```

Expected: 返回可访问的 PR URL。不得自动合并。

## 3. 完成定义

只有以下全部满足，目标才可标记完成：

- 独立 Web/CLI OAuth 成功；
- `~/.codex` 元数据前后无变化；
- secrets 不出现在 API、Settings、Web 或日志；
- 实时账户目录可见；
- 只有精确 `gpt-5.6-sol` 的 live 目录触发自动切换；
- 失败不改变原模型、不调用付费 API；
- 登出安全清理并按规则回退；
- Responses、SSE、reasoning 和工具调用回归通过；
- Python/Web 全量测试、lint、typecheck、build 和 diff check 通过；
- medium 深度审查无未解决问题；
- CSSwitch MIT 来源声明完整；
- 功能分支已推送并创建 PR，未合并。
