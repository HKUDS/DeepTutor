# Tencent IMA 只读连接流程 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让用户在 DeepTutor 的“关联已有”流程中用 IMA Client ID/API Key 枚举、选择并连接一个腾讯 IMA 知识库，之后仅通过现有 `search_knowledge` 标题与命中片段做只读检索。

**Architecture:** 保留现有每知识库 IMA 凭据与服务端二次探测机制，在 `ImaClient` 增加官方只读知识库列表及批量详情调用，通过一个不持久化凭据的 FastAPI 路由暴露给 Web。前端在创建弹窗内提供独立 IMA 连接状态机；现有新建上传、文件夹关联和其他 RAG 引擎路径不改变。

**Tech Stack:** Python 3.11、FastAPI/Pydantic、httpx、pytest；Next.js/React、TypeScript、node:test、i18next；Playwright/Chrome 做浏览器验收。

---

## 实施前提与边界

- IMA 的“读取”只指 `search_knowledge` 返回的 `title` 与 `highlight_content`；不下载完整文件，不调用任何写接口。
- 自动列表每页最多 20 项，保留官方 `next_cursor` / `is_end`；普通界面不显示知识库 ID。
- `linkable` 继续仅表示“本地索引文件夹可关联”，IMA 由前端按 provider id 单独启用，不能把它改成 `linkable: true`。
- 列表路由不保存、不缓存、不记录 Client ID/API Key；IMA 401 必须以内联错误返回，不能触发 DeepTutor 登录跳转。
- 真实凭据只从用户授权的本地文件临时加载；不得写入仓库、测试夹具、快照、日志或常用运行时配置。
- 所有提交信息使用中文；每项任务只提交与该任务直接相关的改动。

## Task 1: 用失败测试固定 IMA 客户端列表协议

**Files:**

- Modify: `tests/services/rag/test_ima_pipeline.py`
- Test: `tests/services/rag/test_ima_pipeline.py::TestClientKnowledgeBaseList`

- [ ] **Step 1: 为官方列表请求写失败测试**

在 `TestClientWire` 后新增 `TestClientKnowledgeBaseList`，覆盖：

```python
class TestClientKnowledgeBaseList:
    def test_list_posts_empty_query_cursor_and_limit(self) -> None:
        seen: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["url"] = str(request.url)
            seen["body"] = json.loads(request.content)
            return _ok({"info_list": [], "is_end": True, "next_cursor": ""})

        page = asyncio.run(
            _client(handler).search_knowledge_bases(query="", cursor="", limit=20)
        )

        assert seen == {
            "url": f"{API_BASE_URL}/openapi/wiki/v1/search_knowledge_base",
            "body": {"query": "", "cursor": "", "limit": 20},
        }
        assert page == {"knowledge_bases": [], "next_cursor": "", "is_end": True}
```

再加入以下行为测试：

- `limit=0` 与 `limit=21` 抛出 `ValueError`，合法边界为 1–20。
- 搜索页中重复 ID 只保留第一次，缺 ID 或缺名称的条目丢弃。
- 下一页游标和 `is_end=False` 原样返回。
- `get_knowledge_bases(["kb-1", "kb-2"])` 发送 `{"ids": [...]}` 并返回详情 map。
- `get_knowledge_base()` 继续通过批量方法取得当前绑定 ID，保持既有探测兼容。
- 列表会用批量详情补充 `description`；详情调用发生协议错误时仍返回名称，描述为 `None`。
- 列表调用本身的凭据错误与限流错误仍分别抛出 `ImaAuthError` / `ImaRateLimitError`。

- [ ] **Step 2: 运行定向测试并确认因缺少方法而失败**

Run:

```powershell
python -m pytest tests/services/rag/test_ima_pipeline.py::TestClientKnowledgeBaseList -q
```

Expected: FAIL，错误指向 `ImaClient` 尚无 `search_knowledge_bases` / `get_knowledge_bases`。

- [ ] **Step 3: 提交测试红灯**

```powershell
git add tests/services/rag/test_ima_pipeline.py
git commit -m "测试：固定 IMA 知识库列表协议"
```

## Task 2: 实现 IMA 只读知识库枚举

**Files:**

- Modify: `deeptutor/services/rag/pipelines/ima/client.py`
- Test: `tests/services/rag/test_ima_pipeline.py`

- [ ] **Step 1: 增加批量详情方法并让单项探测复用**

在 `ImaClient` 中加入：

```python
async def get_knowledge_bases(self, ids: list[str]) -> dict[str, dict[str, Any]]:
    normalized = list(dict.fromkeys(str(item).strip() for item in ids if str(item).strip()))
    if not normalized:
        return {}
    if len(normalized) > 20:
        raise ValueError("IMA accepts at most 20 knowledge base IDs per request.")
    data = await self._post("get_knowledge_base", {"ids": normalized})
    infos = data.get("infos")
    if not isinstance(infos, dict):
        return {}
    return {
        str(kb_id): info
        for kb_id, info in infos.items()
        if isinstance(info, dict)
    }

async def get_knowledge_base(self) -> dict[str, Any]:
    kb_id = self._config.knowledge_base_id
    return (await self.get_knowledge_bases([kb_id])).get(kb_id, {})
```

- [ ] **Step 2: 增加一页列表读取与非阻断描述增强**

实现签名：

```python
async def search_knowledge_bases(
    self,
    query: str = "",
    *,
    cursor: str = "",
    limit: int = 20,
) -> dict[str, Any]:
```

实现要求：

- 先验证 `1 <= limit <= 20`。
- 调用 `search_knowledge_base`，body 只含 `query`、`cursor`、`limit`。
- 仅接受有非空字符串 `id` 与 `name` 的 dict；按 ID 保序去重。
- 对本页 ID 调用一次 `get_knowledge_bases`；任何详情增强异常只令描述为空，不吞掉最初的列表异常。
- 返回固定结构：

```python
{
    "knowledge_bases": [
        {"id": kb_id, "name": name, "description": description_or_none}
    ],
    "next_cursor": str(data.get("next_cursor") or ""),
    "is_end": bool(data.get("is_end")),
}
```

- [ ] **Step 3: 更新模块说明和导出，不引入写接口**

把文件头部的“两种只读调用”改为三种，明确 `search_knowledge_base` 仅用于枚举可访问知识库。不要添加上传、创建、删除 IMA 内容的方法。

- [ ] **Step 4: 运行 IMA 客户端和既有检索管线测试**

```powershell
python -m pytest tests/services/rag/test_ima_pipeline.py -q
```

Expected: PASS，既有 `search_knowledge`、probe、pipeline 和 factory 测试继续通过。

- [ ] **Step 5: 提交客户端实现**

```powershell
git add deeptutor/services/rag/pipelines/ima/client.py
git commit -m "功能：支持枚举 IMA 知识库"
```

## Task 3: 新增安全的 IMA 列表 API

**Files:**

- Modify: `tests/api/test_knowledge_router.py`
- Modify: `deeptutor/api/routers/knowledge.py`
- Test: `tests/api/test_knowledge_router.py`

- [ ] **Step 1: 写列表路由失败测试和安全断言**

在 `tests/api/test_knowledge_router.py` 增加一个可注入的假客户端，并覆盖：

```python
def test_list_ima_returns_normalized_page(monkeypatch) -> None:
    captured: dict = {}

    class StubClient:
        def __init__(self, config) -> None:
            captured["config"] = config

        async def search_knowledge_bases(self, query="", *, cursor="", limit=20):
            captured["call"] = (query, cursor, limit)
            return {
                "knowledge_bases": [
                    {"id": "kb-1", "name": "My Library", "description": "notes"}
                ],
                "next_cursor": "c2",
                "is_end": False,
            }

    monkeypatch.setattr(knowledge_router_module, "ImaClient", StubClient)
    with TestClient(_build_app()) as client:
        response = client.post(
            "/api/v1/knowledge/list-ima",
            json={"client_id": "cid", "api_key": "secret-key", "cursor": "", "limit": 20},
        )

    assert response.status_code == 200
    assert captured["call"] == ("", "", 20)
    assert response.json()["knowledge_bases"][0]["name"] == "My Library"
    assert "secret-key" not in response.text
```

同组测试还要覆盖：

- 空列表与下一页结构。
- Client ID/API Key 为空或仅空白返回 400。
- `limit` 不在 1–20 时由请求模型返回 422。
- `ImaAuthError` → 401，`ImaRateLimitError` → 429，`ImaAPIError` 或网络异常 → 502。
- 每种错误响应都不含提交的 Client ID/API Key，也不返回 IMA 原始响应正文。

- [ ] **Step 2: 运行路由测试并确认 404/缺少模型失败**

```powershell
python -m pytest tests/api/test_knowledge_router.py -q -k "list_ima"
```

Expected: FAIL，路由不存在。

- [ ] **Step 3: 实现请求模型、响应模型和常量错误映射**

在 `knowledge.py` 顶部导入 `Field` 及 IMA 客户端类型：

```python
from pydantic import BaseModel, Field

from deeptutor.services.rag.pipelines.ima.client import (
    ImaAPIError,
    ImaAuthError,
    ImaClient,
    ImaRateLimitError,
)
from deeptutor.services.rag.pipelines.ima.config import ImaConfig
```

在现有 `ProbeImaRequest` 前加入：

```python
class ListImaRequest(BaseModel):
    client_id: str
    api_key: str
    cursor: str = ""
    limit: int = Field(default=20, ge=1, le=20)


class ImaKnowledgeBaseSummary(BaseModel):
    id: str
    name: str
    description: str | None = None


class ListImaResponse(BaseModel):
    knowledge_bases: list[ImaKnowledgeBaseSummary]
    next_cursor: str
    is_end: bool


@router.post("/list-ima", response_model=ListImaResponse)
async def list_ima_route(payload: ListImaRequest):
    client_id = payload.client_id.strip()
    api_key = payload.api_key.strip()
    if not client_id or not api_key:
        raise HTTPException(status_code=400, detail="Client ID and API key are required.")
    client = ImaClient(
        ImaConfig(client_id=client_id, api_key=api_key, knowledge_base_id="")
    )
    try:
        return await client.search_knowledge_bases(
            query="", cursor=payload.cursor.strip(), limit=payload.limit
        )
    except ImaAuthError:
        raise HTTPException(status_code=401, detail="IMA rejected the supplied credentials.")
    except ImaRateLimitError:
        raise HTTPException(status_code=429, detail="IMA rate limit reached. Try again shortly.")
    except ImaAPIError:
        raise HTTPException(status_code=502, detail="IMA returned an invalid response.")
    except Exception:
        raise HTTPException(status_code=502, detail="Could not reach Tencent IMA.")
```

不要在此路径记录异常对象或请求 payload。

- [ ] **Step 4: 运行定向及 IMA 相关后端测试**

```powershell
python -m pytest tests/api/test_knowledge_router.py -q -k "ima or rag_providers"
python -m pytest tests/services/rag/test_ima_pipeline.py tests/knowledge/test_ima_kb.py -q
```

Expected: PASS。

- [ ] **Step 5: 提交 API 实现**

```powershell
git add deeptutor/api/routers/knowledge.py tests/api/test_knowledge_router.py
git commit -m "功能：新增安全的 IMA 知识库列表接口"
```

## Task 4: 修复 IMA 预检和误导性的状态语义

**Files:**

- Create: `tests/services/rag/test_preflight.py`
- Modify: `deeptutor/services/rag/preflight.py`
- Modify: `web/components/knowledge/KnowledgeHome.tsx`
- Modify: `web/components/knowledge/EngineDetail.tsx`
- Test: `tests/services/rag/test_preflight.py`

- [ ] **Step 1: 写 IMA 预检失败测试**

```python
from deeptutor.services.rag.preflight import engine_preflight


def test_ima_preflight_explains_per_kb_credentials_without_network() -> None:
    report = engine_preflight("ima")
    assert report["ok"] is True
    assert report["checks"] == [
        {
            "key": "per_kb_credentials",
            "label": "Credentials supplied when connecting a knowledge base",
            "ok": True,
            "detail": "Enter the IMA Client ID and API key in the link-existing flow.",
            "optional": False,
        }
    ]
```

- [ ] **Step 2: 运行并确认当前裸 `KeyError('ima')`**

```powershell
python -m pytest tests/services/rag/test_preflight.py -q
```

Expected: FAIL，`engine_preflight("ima")` 尚未注册。

- [ ] **Step 3: 注册无网络的说明性预检**

从 `factory` 导入 `IMA_PROVIDER`，实现 `_ima_preflight()`，并加入 `_PREFLIGHTS`：

```python
def _ima_preflight() -> dict:
    return _finalize(
        [
            _check(
                "per_kb_credentials",
                "Credentials supplied when connecting a knowledge base",
                True,
                "Enter the IMA Client ID and API key in the link-existing flow.",
            )
        ]
    )
```

- [ ] **Step 4: 把前端状态扩为 `per_kb`**

两个组件中的状态类型改为：

```ts
type EngineStatus = "ready" | "per_kb" | "needs_key" | "unavailable";
```

`engineStatus` / `resolveStatus` 首先判断 `provider.id === "ima"` 并返回 `per_kb`。两个 badge 都为该状态展示 `t("Connect per knowledge base")`，使用中性/蓝色样式，不显示绿色 Ready。

在 `EngineDetail`：

- `ENGINE_PREREQUISITES.ima` 说明凭据在“关联已有”时输入、检索只读且只返回命中片段。
- `EnvRequirements` 的 report 总结在 IMA 时使用 `t("Configured per knowledge base")`，其他 provider 保持 `Ready to use`。
- IMA 详情默认展开要求区，因为 `per_kb !== ready`。

- [ ] **Step 5: 运行后端测试和 TypeScript build（文案暂时允许 i18n 检查在 Task 7 修复）**

```powershell
python -m pytest tests/services/rag/test_preflight.py tests/api/test_knowledge_router.py -q -k "preflight or ima"
Set-Location web
npm run build
Set-Location ..
```

Expected: pytest 与 build PASS；若 i18n 尚缺键，留到 Task 7 一次补齐。

- [ ] **Step 6: 提交预检和状态代码**

```powershell
git add deeptutor/services/rag/preflight.py tests/services/rag/test_preflight.py web/components/knowledge/KnowledgeHome.tsx web/components/knowledge/EngineDetail.tsx
git commit -m "修复：说明 IMA 按知识库连接状态"
```

## Task 5: 增加 Web IMA API 与纯逻辑测试

**Files:**

- Modify: `web/lib/knowledge-api.ts`
- Create: `web/lib/ima-connection.ts`
- Create: `web/tests/ima-knowledge-api.test.ts`
- Create: `web/tests/ima-connection.test.ts`
- Test: `web/tests/ima-knowledge-api.test.ts`
- Test: `web/tests/ima-connection.test.ts`

- [ ] **Step 1: 为 provider 归属、名称自动填写、分页合并和连接门禁写失败测试**

`ima-connection.test.ts` 覆盖：

```ts
assert.deepEqual(
  createProviders([{ id: "ima" }, { id: "llamaindex" }] as RagProviderSummary[]).map((p) => p.id),
  ["llamaindex"],
);
assert.equal(linkSourceEnabled({ id: "ima" } as RagProviderSummary), true);
assert.equal(linkSourceEnabled({ id: "pageindex", linkable: false } as RagProviderSummary), false);
assert.equal(nextAutoName("", null, "IMA Notes"), "IMA Notes");
assert.equal(nextAutoName("IMA Old", "IMA Old", "IMA New"), "IMA New");
assert.equal(nextAutoName("My manual name", "IMA Old", "IMA New"), "My manual name");
```

并验证：

- `mergeImaKnowledgeBases` 按 ID 保序去重，下一页可覆盖同 ID 的描述但不重复。
- `canConnectIma` 自动模式要求名称、凭据和已选 ID；手填模式还要求当前三元组对应的 probe `ok=true`。
- `emptyImaLookupState()` 会清空列表、选择、游标、probe 与上一次自动名称，状态回到 `idle`。

- [ ] **Step 2: 为 API 请求写 mock fetch 失败测试**

`ima-knowledge-api.test.ts` 替换 `globalThis.fetch`，调用以下三个新函数并断言：

- `listImaKnowledgeBases` POST `/api/v1/knowledge/list-ima`，body 含 `client_id/api_key/cursor/limit`，保留分页响应。
- `probeImaKnowledgeBase` POST `/probe-ima`。
- `connectImaKnowledgeBase` POST `/connect-ima`。
- 将运行时 auth 打开并返回 IMA 401，`listImaKnowledgeBases` 必须正常 reject 为内联错误，fake `window.location.href` 保持未改变；这固定 `skipAuthRedirect: true`。
- 错误提取只使用归一化 `detail`，测试凭据不出现在抛出的 message。

- [ ] **Step 3: 运行 Node tests 并确认缺少模块/导出而失败**

```powershell
Set-Location web
npm run test:node
Set-Location ..
```

Expected: FAIL。

- [ ] **Step 4: 实现最小纯逻辑模块**

`web/lib/ima-connection.ts` 只导出当前表单使用的常量、类型与纯函数：

```ts
export const IMA_PROVIDER = "ima";
export type ImaConnectionMode = "automatic" | "manual";
export type ImaLookupStatus =
  | "idle"
  | "loading"
  | "ready"
  | "empty"
  | "error"
  | "manual_verified";

export interface ImaKnowledgeBaseOption {
  id: string;
  name: string;
  description: string | null;
}
```

仅实现测试所要求的 `createProviders`、`linkSourceEnabled`、`nextAutoName`、`mergeImaKnowledgeBases`、`emptyImaLookupState` 和 `canConnectIma`，不抽象成通用外部连接器。

- [ ] **Step 5: 在知识库 API 客户端增加类型与三个调用**

在 `knowledge-api.ts` 加入：

```ts
export interface ImaKnowledgeBasePage {
  knowledge_bases: ImaKnowledgeBaseOption[];
  next_cursor: string;
  is_end: boolean;
}

export interface ImaProbe {
  knowledge_base_id: string;
  ok: boolean;
  credentials_ok: boolean;
  knowledge_base_name: string | null;
  description: string | null;
  error: string | null;
}
```

所有 IMA credential 校验请求调用 `apiFetch(..., { skipAuthRedirect: true })`。列表与探测不触发 client cache；只有连接成功后调用 `invalidateKnowledgeCaches()`。

- [ ] **Step 6: 运行新增及完整 Node tests**

```powershell
Set-Location web
npm run test:node
Set-Location ..
```

Expected: PASS。

- [ ] **Step 7: 提交 Web API 和纯逻辑**

```powershell
git add web/lib/knowledge-api.ts web/lib/ima-connection.ts web/tests/ima-knowledge-api.test.ts web/tests/ima-connection.test.ts
git commit -m "功能：增加 IMA Web 连接接口"
```

## Task 6: 接入 IMA 专用连接表单

**Files:**

- Modify: `web/components/knowledge/CreateKbModal.tsx`
- Modify: `web/hooks/useKnowledgeBases.ts`
- Modify: `web/components/knowledge/KnowledgePage.tsx`
- Test: `web/tests/ima-connection.test.ts`

- [ ] **Step 1: 将连接 mutation 接入页面**

在 `useKnowledgeBases` 导入 `connectImaKnowledgeBase as connectImaApi`，增加：

```ts
const connectIma = useCallback(
  async (params: {
    name: string;
    clientId: string;
    apiKey: string;
    knowledgeBaseId: string;
  }) => {
    await connectImaApi(params);
    invalidateKnowledgeCaches();
    await load({ force: true, showSpinner: false });
  },
  [load],
);
```

将 `connectIma` 加入 hook 返回值；`KnowledgePage` 解构并传给 modal 的 `onConnectIma`。

- [ ] **Step 2: 让 provider 出现在正确模式**

在 `CreateKbModal`：

- 新建 provider grid 使用 `createProviders(providers)`，因此 IMA 不出现在上传型“新建”。
- 关联 source grid 使用 `linkSourceEnabled(p)`；IMA 可点击，其他 `linkable: false` provider 仍禁用。
- `linkIsIma = linkSource === IMA_PROVIDER` 时渲染 `ImaConnectionFields`；不要渲染 Folder path、Check folder 或文件上传。
- `submitLabel` 对 IMA 使用 `t("Connect")`。

- [ ] **Step 3: 增加 IMA 状态并在打开/关闭、凭据/模式变化时失效**

在 modal 内维护：

```ts
const [imaClientId, setImaClientId] = useState("");
const [imaApiKey, setImaApiKey] = useState("");
const [imaMode, setImaMode] = useState<ImaConnectionMode>("automatic");
const [imaKnowledgeBaseId, setImaKnowledgeBaseId] = useState("");
const [imaLookup, setImaLookup] = useState(emptyImaLookupState);
const imaRequestVersionRef = useRef(0);
```

要求：

- 弹窗 closed→open 时清空所有 IMA state；关闭后组件即使保留挂载也不能复用凭据。
- 增加 `!isOpen` 清理 effect，在关闭发生时立即把 Client ID/API Key 设为空并重置全部 IMA session，而不是只等下次打开才清理。
- Client ID、API Key、自动/手填模式、手填 ID 变化时递增 request version 并清除不再有效的列表、选择或 probe。
- 每个 async handler 捕获当前 version，响应返回时若 version 已变化则丢弃，防止旧凭据的慢响应重新写入界面。
- 切换 source 离开 IMA 时也清空 IMA session。

- [ ] **Step 4: 实现自动列表与分页**

`handleLoadIma(reset: boolean)`：

- 首次验证用 cursor `""` 并把状态设为 `loading`。
- “加载更多”使用当前 `nextCursor`，保留已有列表；失败时列表保持不变并显示 error，可重试。
- 成功用 `mergeImaKnowledgeBases` 合并；0 项且首页结束 → `empty`，否则 → `ready`。
- 选择项后调用 `nextAutoName`；只有名称为空或等于上次自动名称时才覆盖，并记录新的 auto name。
- 自动列表界面只显示 `name` 和非空 `description`，不 render `id`。

- [ ] **Step 5: 实现高级手填 ID 探测**

- 默认折叠，按钮文案 `Use knowledge base ID instead`。
- 切换后显示 Knowledge Base ID 输入框和 `Verify knowledge base`。
- 调用现有 `probeImaKnowledgeBase`；成功状态为 `manual_verified`，展示返回的知识库名称/描述。
- `canSubmit` 必须使用 `canConnectIma`；自动模式选中即可，手填模式必须是当前 Client ID/API Key/ID 对应的成功 probe。

- [ ] **Step 6: 提交时只调用现有服务端二次探测连接**

在 `handleSubmit` 的 link 分支优先处理 IMA：

```ts
await onConnectIma({
  name: trimmed,
  clientId: imaClientId.trim(),
  apiKey: imaApiKey.trim(),
  knowledgeBaseId:
    imaMode === "automatic" ? imaLookup.selectedId : imaKnowledgeBaseId.trim(),
});
```

不要把前端列表成功当成持久化授权；`connect-ima` 仍在后端再次 probe。

- [ ] **Step 7: 运行 Node tests、build 与 lint**

```powershell
Set-Location web
npm run test:node
npm run build
npm run lint
Set-Location ..
```

Expected: Node tests、Next/TypeScript build、lint PASS（新增翻译键在下一任务补齐后再跑 i18n）。

- [ ] **Step 8: 提交表单接入**

```powershell
git add web/components/knowledge/CreateKbModal.tsx web/hooks/useKnowledgeBases.ts web/components/knowledge/KnowledgePage.tsx
git commit -m "功能：接入 IMA 只读知识库连接表单"
```

## Task 7: 补齐中英文文案与静态验收

**Files:**

- Modify: `web/locales/en/app.json`
- Modify: `web/locales/zh/app.json`
- Modify if required by actual UI copy: `web/components/knowledge/CreateKbModal.tsx`
- Modify if required by actual UI copy: `web/components/knowledge/EngineDetail.tsx`

- [ ] **Step 1: 收集本 PR 新增的全部 `t("...")` key**

至少覆盖：

- `Connect per knowledge base` / `按知识库连接`
- `Configured per knowledge base` / `按知识库配置`
- `Client ID`
- `Verify and load knowledge bases` / `验证并读取知识库`
- `Loading knowledge bases...` / `正在读取知识库…`
- `No accessible knowledge bases found.` / `未找到可访问的知识库。`
- `Load more` / `加载更多`
- `Use knowledge base ID instead` / `改用知识库 ID`
- `Back to knowledge base list` / `返回知识库列表`
- `Knowledge Base ID` / `知识库 ID`
- `Verify knowledge base` / `验证知识库`
- `Knowledge base verified` / `知识库验证成功`
- IMA 只读检索、凭据位置、认证/限流/网络重试相关说明。

英文 locale 的 value 与英文 key 保持一致；中文 locale 使用自然简体中文。不要把 API Key 示例或真实凭据放进 locale。

- [ ] **Step 2: 验证 JSON 和 i18n 完整性**

```powershell
Set-Location web
npm run i18n:check
npm run test:node
npm run build
npm run lint
Set-Location ..
```

Expected: 全部 PASS；两份 JSON 可解析，新增 key 无遗漏、占位符一致。

- [ ] **Step 3: 提交翻译**

```powershell
git add web/locales/en/app.json web/locales/zh/app.json web/components/knowledge/CreateKbModal.tsx web/components/knowledge/EngineDetail.tsx
git commit -m "文案：补齐 IMA 连接流程中英文"
```

## Task 8: 全量验证、真实只读 smoke、Chrome 视觉验收与 PR

**Files:**

- Verify only: all changed files
- Local secret source, never stage: an operator-provided credential file outside the repository
- Temporary runtime only: a newly created directory under `$env:TEMP`

- [ ] **Step 1: 运行后端相关全套测试**

```powershell
python -m pytest tests/services/rag/test_ima_pipeline.py tests/services/rag/test_preflight.py tests/api/test_knowledge_router.py tests/knowledge/test_ima_kb.py -q
```

Expected: PASS，无 secret、warning traceback 或网络依赖。

- [ ] **Step 2: 运行 Web 全套验证**

```powershell
Set-Location web
npm run test:node
npm run build
npm run lint
npm run i18n:check
Set-Location ..
```

Expected: 全部 PASS。

- [ ] **Step 3: 安全加载本地凭据并执行真实只读 smoke**

先只检查文件格式和字段数，不把内容打印到终端。将 Client ID/API Key 放入当前进程的任务专用环境变量；不要使用 `$HOME`/`$CODEX_HOME`，不要写 `.env`。

真实 smoke 顺序：

1. 以 `ImaConfig(client_id=..., api_key=..., knowledge_base_id="")` 调用 `search_knowledge_bases("", cursor="", limit=20)`。
2. 断言返回有 `knowledge_bases` list、`next_cursor` string、`is_end` bool；不要求账户一定有知识库。
3. 如存在条目，选择第一项，以其 ID 构造临时 `ImaClient`，调用一次无副作用 `search_knowledge("DeepTutor", limit=3)`。
4. 零命中视为有效；若命中，断言每个可用条目有标题或 `highlight_content`，并且没有调用任何写接口。
5. 终端只打印 `list_ok/count/is_end/search_ok/hit_count` 这类布尔或计数，绝不打印 header、请求 body、ID、名称或片段正文。

- [ ] **Step 4: 用隔离数据目录做真实 connect smoke**

- 用 `New-Item -ItemType Directory` 在 `$env:TEMP` 创建本任务专用目录，解析后确认绝对路径位于 `$env:TEMP` 下。
- 让 smoke 进程的知识库根目录只指向该临时目录，连接第一个可访问知识库。
- 断言注册 entry 的 `type`/`rag_provider` 为 `ima`，随后通过现有 `ImaPipeline.search` 做一次检索。
- 测试结束后先再次校验目标绝对路径仍在任务临时目录内，再用同一个 PowerShell 会话 `Remove-Item -LiteralPath ... -Recurse -Force` 删除；报告该目录已删除且不可恢复。
- 不启动或修改用户当前常用后端的数据配置。

- [ ] **Step 5: 在已启动的 DeepTutor Chrome 页面做交互验收**

使用现有登录/页面状态完成：

- “新建”中不出现 Tencent IMA。
- “关联已有”中 IMA 可选，且不显示文件上传、Folder path、Check folder。
- API Key 为 password 输入；验证能加载列表，自动选择不显示内部 ID。
- 选择时名称只在空白/自动值时更新，手工名称不被覆盖。
- 高级手填模式与自动模式互斥，修改凭据或 ID 后旧验证失效。
- 有 `next_cursor` 时可加载更多；真实账户无法覆盖的 empty/pagination/error 状态用 mock 响应验证。
- 引擎首页和详情显示“按知识库连接”，环境检查不再 500，也不显示裸 `'ima'` 或绿色“就绪”。
- 连接成功后该 KB 出现在知识中心，RAG 调用仍只使用检索片段。

- [ ] **Step 6: 检查 diff、secret 和提交状态**

```powershell
git diff --check
git status --short
git log --oneline origin/main..HEAD
git diff --stat origin/main...HEAD
```

使用 `rg` 只搜索凭据文件中值的哈希或明确的测试占位符策略，不把真实 secret 作为命令参数或终端输出；确认本地凭据、临时文件、构建产物均未被 stage。

- [ ] **Step 7: 请求代码审查并修复发现的问题**

按 `requesting-code-review` skill 检查：协议正确性、凭据泄露、异步 stale response、现有上传/关联流程回归、测试缺口。任何修复都先补失败测试，再改实现并重跑相应验证。

- [ ] **Step 8: 推送分支并创建 Draft PR**

按 `github:yeet` skill：

- 分支：`fix/ima-connection-flow`
- PR 标题建议：`修复 IMA 只读知识库连接流程`
- PR 正文用中文，说明“检索式只读”的边界、自动列表＋手填 fallback、预检修复、安全措施和实际执行过的测试。
- PR 正文不包含 memory citation、真实知识库名称/ID、Client ID、API Key 或 smoke 片段。

## 最终完成标准

- 所有后端/Web 自动化检查和真实只读 smoke 通过。
- Chrome 可完成 IMA 凭据验证、列表选择、可选分页、手填 fallback、连接和检索。
- 现有 `search_knowledge` 仍只向回答链路提供标题与 `highlight_content`。
- 无 IMA 写接口、无全文下载、无凭据泄露或额外持久化。
- Draft PR 已创建，范围只包含本计划与设计文档直接要求的文件。
