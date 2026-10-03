# deep_research 四阶段编排契约补测说明（AGEN-143）

基线：`origin/main` @ `ef2d9e5c3`（release: v1.6.12），2026-10-03。
对应缺口：覆盖率报告 Top 15 第 7 项 — `deeptutor/agents/research/pipeline.py`（408 缺失 / 62.6%）。

## 产物

- 测试集：`tests/agents/research/test_pipeline_stage_contract.py`（6 个用例，全绿回归锁）
- 本说明目录：`evidence/research-pipeline-tests-2026-10-03/`

## 契约覆盖点

1. **规划运行（confirmed_outline=None）**：阶段顺序 `rephrasing → decomposing`；预览载荷字段契约
   （`response=""`、`output_dir=""`、`outline_preview=True`、`topic=精炼后主题`、`sub_topics=[{title, overview}]`）；
   decompose 接收 rephrase 精炼后的主题；规划阶段**不得**自行 emit capability result（由 capability 统一补
   `research_config` 后再发）。
2. **rephrase_enabled=False**：`rephrasing` 阶段上下文仍发出，但不进 LLM 循环，原题 strip 后透传。
3. **确认运行（confirmed_outline 非空）**：阶段顺序 `researching → reporting`；跳过 rephrase/decompose
   （不再二次追问）；结果载荷 `metadata` 契约：`mode="agentic_research"`、`topic`、`block_count`、
   `citation_count`、`partial`、`failed_block_count`、`failed_block_titles`；`emit_capability_result` 恰好一次、
   `source="deep_research"`；报告装配顺序 `# 标题 → ## 1. Introduction → ## 2./3. 小节 → ## 4. Conclusion`
   且与 report outline 的 sections 顺序一致。
4. **检索为空短路**：`confirmed_outline=[]` → 队列零 block，仍按序走 `researching → reporting`，
   产出完整结果载荷（`block_count=0, citation_count=0, partial=False`），不抛错。
5. **空知识块**：block COMPLETED 但 knowledge 为空 → 报告照常生成，`partial=False`（partial 只看状态）。

## Mock 策略（单元级 mock LLM）

在 `deeptutor.runtime.agentic` 原语层打桩，编排代码全真运行、无网络访问：

- `run_agentic_loop` → `_FakeAgenticLoopLLM`：rephrase 返回 FINISH 精炼主题；block 返回 FINISH 知识文本。
- `run_labeled_step` → `_FakeLabeledStepLLM`：按 `allowed_labels`/`stage` 返回 canned OUTLINE / INTRO /
  SECTION / CONCLUSION 应答，正文满足 ≥80 字符与编号标题校验，SECTION 标题取自 canned report outline。
- 构造期补丁沿用 `test_pipeline_partial_failure.py` 约定（`get_llm_config` / `get_tool_registry`），
  另补 `_prepare_pageindex_tools`（no-op）与 `_build_client`（哨兵对象）。

## 运行命令与结果

```bash
PYTHONPATH=<worktree> .venv/bin/python -m pytest tests/agents/research/test_pipeline_stage_contract.py -q
# 6 passed in 0.49s

PYTHONPATH=<worktree> .venv/bin/python -m pytest tests/agents/research/ -q
# 83 passed in 0.74s（无回归）
```

## 覆盖率数字

环境无 pytest-cov/coverage，用 stdlib `trace` + AST 语句计数在独立进程各测一次（口径与 coverage.py 略有差异）：

| 口径 | 语句覆盖 |
| --- | --- |
| 仅既有测试（基线） | 683/1104 = 61.9% |
| 加入本契约测试后 | 815/1104 = 73.8%（+132 条语句，约 +11.9pp） |

## 结论

- **跑通：PASS**。当前 `origin/main` 的编排实现满足四阶段契约，6 个用例全部通过，定位为**绿色回归锁**：
  覆盖缺口即缺口本身，无需修复卡改产品代码；后续若有人改编排（阶段顺序、载荷字段、短路逻辑）会被此集拦下。
- 未修改任何产品代码；仅新增 1 个测试文件 + 本说明目录。
