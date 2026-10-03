# launcher 生命周期边界补测 · 2026-10-03（AGEN-287）

## 基线与运行环境

| 项 | 值 |
|---|---|
| 代码基线 | `origin/main` @ `ef2d9e5c3`（release: v1.6.12） |
| 分支 | `myfork/test/launcher-lifecycle-20261003` |
| Python | 3.13.13（复用主 checkout `.venv`，只读，未改动） |
| pytest | 9.1.1（pytest-cov 7.1.0） |
| 新增文件 | `tests/runtime/test_launcher_lifecycle.py`（19 个用例） |
| 产品代码 | 零改动；全部子进程 mock，未启动任何真实服务 |

## 覆盖范围

对应覆盖率缺口：`deeptutor/runtime/launcher.py`（295 缺失 / 66.7%）。

1. **`_send_tree_signal` 树终止原语**（POSIX killpg / 单 PID 回退 / 缺 PID 忽略 / Windows taskkill 仅在 KILL 时加 `/F`）
2. **`_terminate` 树终止**：已退出进程跳过、SIGTERM → wait 成功、wait 超时升级 KILL_SIGNAL、信号异常吞掉后仍 reap
3. **`_kill_port_listeners` 端口清理**：SIGTERM 释放端口（只发一轮）、端口持续占用时升级 KILL、始终不释放时记录失败日志、信号异常容错（不中断清理循环）
4. **标记文件损坏容错**：
   - `_copy_packaged_web_if_needed`：marker 非法 JSON → 重建缓存（rmtree + copytree + 占位符替换 + 重写合法 marker）；合法 marker → 命中缓存不重建
   - `_ensure_source_production_build`：marker 损坏 → 触发重建且 `next-env.d.ts` 快照恢复；重建后 marker 合法 → 复用
   - `_read_detached_state`：文件缺失 / 非法 JSON / 非 dict 载荷 → 一律返回 None
   - `_clear_detached_runtime`：token 不匹配保留文件；token 匹配清除 state + stop；仅 stop 匹配时消费 stop

## 复跑命令（在仓库根目录执行）

```bash
PYTHONPATH=. python -m pytest tests/runtime/test_launcher_lifecycle.py -q

# launcher 相关全套 + 覆盖率（基线与对照）
PYTHONPATH=. python -m pytest tests/runtime/test_launcher.py \
  tests/runtime/test_launcher_allocator_env.py \
  tests/runtime/test_macos_command_launcher.py \
  tests/runtime/test_launcher_lifecycle.py \
  -q --cov=deeptutor.runtime.launcher --cov-report=term-missing
```

## 结果数字

- 新增用例：**19 passed**（0.3s 内，无网络、无子进程、无端口监听）
- launcher 相关全套（新旧合计 57 用例）：**57 passed**
- `tests/runtime/` 全目录回归：**219 passed / 4 skipped**（连续 3 次稳定）
- `launcher.py` 行覆盖：**295 缺失 / 66.7% → 262 缺失 / 70.4%**（本组用例新覆盖 33 行语句）

对照文件：`coverage-before.txt`（仅既有 3 个 launcher 测试文件）、`coverage-after.txt`（含本卡新增文件）。

## 备注

- 时间控制：`_kill_port_listeners` 的等待循环用可快进的 `time.monotonic`/`time.sleep` 替身，避免真实 sleep。
- 既有 `test_launcher.py` 已覆盖 `_kill_port_listeners` 的间接 happy path 与 `_ensure_source_production_build` 的正常复用/输入变更重建；本卡只补损坏容错与终止/清理分支，无重复。
- 未发现上游已有关联 PR（`HKUDS/DeepTutor` 检索 "launcher" 全状态 PR，无生命周期补测类 PR）。
