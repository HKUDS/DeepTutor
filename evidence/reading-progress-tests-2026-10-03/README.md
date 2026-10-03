# 沉浸阅读进度 API 契约补测（覆盖率缺口 11）

基线：`origin/main` @ `ef2d9e5c3`（release: v1.6.12），对应审计分支
`audit/coverage-gaps-20261003` 的 `evidence/coverage-2026-10-02/top15-gaps.md` 第 11 项。

## 产物

- `tests/api/routers/__init__.py`（空包文件）
- `tests/api/routers/test_reading_progress.py` — 20 个用例，全部驱动真实
  `ReadingStore`（`DEEPTUTOR_HOME` 重定向到 tmp），无 stub、无产品代码改动。

## 覆盖的契约

1. **保存→取回一致**：`PUT /materials/{id}/position` 后 `GET` 逐字段一致；
   未保存时默认返回 locator=1 / percentage=0.0 / updated_at>0。
2. **重复保存幂等**：同一 payload 保存两次 → 磁盘 `positions/` 恰好 1 个文件且
   状态收敛；`updated_at` 单调不减；账号级学习记录（`LearningStore`）仍只有
   1 条且 latest 正确。书签同 locator 二次 POST 返回既有 `bookmark_id`，列表不重复。
3. **非法 payload 4xx**：locator=0、percentage 越界（±）、source_anchor 超长、
   类型错误、缺字段 → 422；locator 超出物料范围、书签 label/anchor 超长 → 400/422；
   且**被拒绝的保存不落盘**（GET 仍返回保存前状态）。
4. **失败不损状态**：越界 locator 保存返回 400 后，先前已存进度原样保留；
   未知物料 position/bookmark 路由均 404。
5. **书签删除**：删除返回 ok，重复删除 404，列表随之清空。

## 与审计基线的对应数字

- 审计基线：`reading.py` 843 语句，缺失 279（66.9%）。
- 其中进度处理器区域（`position` GET/PUT、`bookmarks` GET/POST/DELETE，
  源码 1392–1470 行）基线缺失 25 行，本次补测直接覆盖其中 **23 行**
  （coverage.json 逐行比对，见 `coverage-delta.txt`）。
- 残留：`delete_bookmark` 路由的 `except` 分支（1466–1467 行）仍无任何测试触发；
  `save_position` 的学习记录失败分支（1424–1425 行）由既有
  `tests/reading/test_router.py::test_position_save_succeeds_when_activity_store_fails`
  覆盖。领取修复卡时可顺手为 1466–1467 行补一个 store 抛错的用例。

## 运行命令与结果（本机 macOS，Python 3.13.13）

```bash
# 新增文件单独跑
python -m pytest tests/api/routers/test_reading_progress.py -q
# → 20 passed

# 与既有阅读路由测试合跑（无相互污染）
python -m pytest tests/api/routers/test_reading_progress.py tests/reading/test_router.py -q
# → 65 passed

# 覆盖率（仅新文件，pytest-cov 未入仓库依赖，用临时环境测得）
python -m pytest tests/api/routers/test_reading_progress.py \
  --cov=deeptutor.api.routers.reading --cov-report=term-missing -q
# → reading.py 单文件 38%（843 语句 / 缺 522）；进度处理器 1392–1470 全绿
```

完整输出见本目录 `pytest-standalone.txt`、`pytest-combined.txt`、`coverage-delta.txt`。

## 说明

- 结论：**PASS**（20/20 通过；合跑 65/65 通过）。
- 当前 `origin/main` 的进度契约实现是正确的；本套件的价值是把"进度丢失"类
  回归从不可见变为必挂：任何破坏保存→取回一致、幂等或 4xx 校验的改动都会在此挂掉。
- 测试通过 `DEEPTUTOR_HOME=tmp_path + PathService.reset_instance()` 隔离，
  不触碰真实用户目录；物料夹具用 `store.ingest_units` 生成纯文本物料，
  不依赖 pymupdf。
