# co_writer 路由契约补测 — 证据（2026-10-03）

对应任务卡：AGEN-289（test: co_writer 路由契约补测，覆盖率备选 20）。
基线：`origin/main` @ `ef2d9e5c3`（release: v1.6.12），来自 `audit/coverage-gaps-20261003` 证据的备选节：
`deeptutor/api/routers/co_writer.py` — 246 缺失 / 40.0%。

## 产物

- 测试文件：`tests/api/routers/test_co_writer_contract.py`（新增目录 `tests/api/routers/`，含空 `__init__.py`）
- 分支：`myfork/test/co-writer-contract-20261003`（基于 origin/main @ ef2d9e5c3）
- 本目录：`evidence/co-writer-tests-20261003/`（说明 + 完整 pytest 输出）

## 测试命令与数字

```bash
python -m pytest tests/api/routers/test_co_writer_contract.py -v
# 40 passed in 0.51s

python -m pytest tests/api/routers/test_co_writer_contract.py tests/api/test_co_writer.py -q
# 74 passed（与既有 co_writer 测试同跑无互相污染）

ruff check tests/api/routers/test_co_writer_contract.py   # 通过
ruff format --check 同文件                                  # 通过
```

运行环境：/Users/Shared/DeepTutor/.venv（Python 3.13.13, fastapi 0.141.1, pydantic 2.13.4, pytest 9.1.1）。

## 结论（跑通：PASS）

40/40 通过，0 失败。当前 origin/main 实现已满足本卡锁定的全部契约，**没有产生需要修复卡的失败用例**——"失败测试集"在此为空集；本集合的价值是把 40.0% 的路由契约空白固化为回归保护，后续任何改动破坏契约时会立即转红。

## 契约覆盖清单

会话/草稿 CRUD 请求形状（13 例）
- POST /documents：完整响应形状 {id,title,content,created_at,updated_at}；id 满足 ^[0-9a-f]{8,32}$；无标题时从首个 heading 派生；空请求体默认 "Untitled draft"
- GET /documents：仅返回 summary 视图（无 content 字段），按 updated_at 倒序，preview 截断 ≤161 字符并以 … 结尾
- GET/PUT/DELETE /documents/{id}：读写删除与持久化一致性；PUT 空对象为 no-op（字段保留）
- 未知/畸形 doc id（合法形状缺失、大写、非 hex、过短、过长）在三条路由上一律 404，detail 为 "Document not found"；DELETE 后重复删除 404（非幂等契约固化）

非法 payload 4xx（10 例）
- EditRequest：缺 text/instruction、非法 action/source 字面量、text 超 600,000、instruction 超 10,000 → 422，且验证失败不触达 agent
- ReactEditRequest：非法 mode/tools 字面量、selected_text 超 120,000 → 422；mode=none 且空 instruction → 400；空白选区 → 400
- edit-react/stream 预检：非法 payload 在进入 SSE 之前以 JSON 4xx 返回（不产生 event: 流）
- ExportDocxRequest：content 超 600,000 → 422
- CreateDocumentRequest/UpdateDocumentRequest：非字符串字段 → 422
- import/docx：.doc 与非 .docx 后缀 → 400；空文件 → 400（detail 含 "empty"）

导出/导入失败分支（4 例）
- export：converter 抛 DocxConversionError → 400（detail 透传）；抛任意异常 → 500
- export：Content-Disposition 对 `\/:*?"<>|` 等不安全字符统一替换为 "-"（filename="a-b-c-d-e-f-g-h-i.docx"）
- import：真实损坏字节 → 400（真实 DocxConversionError 路径）；converter 抛任意异常 → 500

Edit 动作与 agent 契约（7 例）
- /documents/actions/edit：请求字段逐一透传给 agent（text/instruction/action/source/kb_name），响应锁定 {edited_text, operation_id}
- /documents/actions/automark：text 透传，响应 {marked_text, operation_id}
- agent 抛异常 → edit/automark 均 500 且 detail 含原始异常信息
- edit-react：输出围栏剥离（```markdown…``` → 纯文本）、tools_used 上报、operation_id 形如 \d{8}_\d{6}_[0-9a-f]{6}；rag 无 kb_name 时跳过、重复 tool 去重、kb_name 透传 gather_context；每次编辑落 history（action=react_edit）

history / tool-calls 端点（2 例）
- GET /documents/history → {history, total}；GET /documents/history/{id} → 单条或 404 "Operation not found"
- GET /documents/tool-calls/{id} → 读取 {op}_*.json 或 404 "Tool call not found"

## 隔离与安全

- 存储经 monkeypatch 指向 tmp_path（_StubPathService），agent 为纯 stub，history/tool-calls 写入 tmp_path，不触碰真实 workspace、不发起任何 LLM 调用。
- 沿用 tests/api/test_co_writer.py 的模块级 load_config_with_main 桩（新 worktree 缺 data/user/settings/main.yaml，router 导入期需要）。
- 未修改任何产品代码（git diff 仅新增测试与证据文件）。

## 备注

- `markdown_to_docx` 实际不抛 DocxConversionError，export 的 400 分支当前不可自然触达（测试通过 monkeypatch 验证该分支行为正确）；这属于现状记录，不构成缺陷。
- 遵守卡面规则：不向上游开 PR；PR 草稿标题/描述见完成评论，由人决定是否提交。
