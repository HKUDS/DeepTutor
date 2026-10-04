# test: tex_downloader / tex_chunker 工具链补测 — 证据说明

- 日期：2026-10-04
- 分支：`test/tex-tools-20261004`（基线 `origin/main` @ `ef2d9e5c3`，release v1.6.12）
- 运行环境：`/Users/Shared/DeepTutor/.venv`（Python 3.13.13，pytest 9.1.1，tiktoken 已装）
- 新增文件：`tests/tools/test_tex_tools.py`（44 个用例，全部本地 mock，无真实网络）
- 产品代码改动：无（`git status` 仅新增上述测试文件与本证据目录）

## 测试命令与结果

```
/Users/Shared/DeepTutor/.venv/bin/python -m pytest tests/tools/test_tex_tools.py -q
→ 44 passed, 5 warnings in 0.48s
```

回归确认（未影响既有工具测试）：

```
/Users/Shared/DeepTutor/.venv/bin/python -m pytest tests/tools/ -q
→ 294 passed, 5 warnings in 2.86s
```

## 覆盖清单

tex_downloader（TexDownloader / TexDownloadResult / read_tex_file）：
- 正常下载分块：tar 源包落盘 `paper_<id>/main.tex`、临时目录清理；zip 源包；非压缩字节按单 tex 文件处理；arxiv_id 从 URL 提取（abs/pdf/带版本号）与显式传入
- 失败分支（全部 mock）：无法提取 ID；`ConnectionError` / `HTTPError` → "Download failed"；处理异常 → "Processing failed"；压缩包内无 tex → "Main tex file not found"
- 边界输入：TarSlip 路径穿越成员（`../evil.tex`）被安全过滤且不落盘；损坏字节流；`main.tex` 选择优先级（命名 > documentclass > 最大文件）；大小写混合 `Main.tex` 可命中；`MAIN.TEX` 因 glob 大小写敏感完全不可见（已知限制，见下）
- `read_tex_file`：UTF-8 内容；非法字节以 errors="ignore" 容错

tex_chunker（TexChunker）：
- 构造：无 model → 回退 cl100k_base；不支持的 model 名 → 回退 cl100k_base；支持的 model → 正常编码器
- estimate_tokens：空串为 0；单调性；编码器异常时按 len//4 兜底
- _clean_text：连续空白折叠（>100 次折叠为 10）；单行 >10000 字符截断加 "...[truncated]" 标记；正常文本不变
- split_tex_into_chunks：短文本原样透传；空输入返回 `[""]`；多 section 文档按 max_tokens 切分且每块不超限；单 section 超长走段落切分；无 section 文档走段落合并；overlap>0 时相邻块首尾衔接（chunk[1] 开头 40 字符出现在 chunk[0] 尾部）；极小 max_tokens 不崩溃
- _get_overlap_text：请求 overlap 大于整块 token 时整块返回；正常 overlap 为前块尾部子串

## 发现（只记录，未改产品代码）

1. 失效 docstring 引用（DT-22 §4 确认项）：
   - `deeptutor/tools/tex_downloader.py:11` — "Based on: TODO.md specification"，仓库根目录无 `TODO.md`（`git ls-tree origin/main --name-only | grep -i todo` 为空）
   - `deeptutor/tools/tex_chunker.py:11` — 同上

2. tarfile 兼容性风险（测试过程中发现的额外信号）：
   - `tex_downloader.py` 的 `_extract_tar` 调用 `tar.extractall(extract_dir, members=...)` 未传 `filter=` 参数。Python 3.12+ 触发 DeprecationWarning（本机 3.13.13 可复现）；在 `-W error::DeprecationWarning` 下 5 个 tar 路径用例全部转为 "Processing failed" 失败
   - pyproject 声明 `requires-python = ">=3.11,<3.15"`，即 3.14 在支持范围内，该调用存在前向兼容风险。建议后续单独开卡处理（如传 `filter="data"`，可同时替代手写 safe_members 过滤）

3. 边界行为基线（测试已固化，供后续回归对照）：
   - `_find_main_tex` 的发现层 `rglob("*.tex")` 大小写敏感，`MAIN.TEX` 这类全大写扩展名文件永远不会成为候选；命中层 `name.lower()` 的大小写不敏感仅对已匹配 glob 的文件生效
   - 无句读的超大单段落无法继续切分，会输出超过 max_tokens 的单块（可能伴随一个空白尾块），为当前策略的已知退化行为
   - 空输入 `split_tex_into_chunks("")` 返回 `[""]` 而非空列表

## 产物文件

- `tests/tools/test_tex_tools.py`
- `evidence/test-tex-tools-20261004/report.md`（本文件）
- `evidence/test-tex-tools-20261004/pytest-tex-tools.txt`（本卡用例运行输出）
- `evidence/test-tex-tools-20261004/pytest-tools-regression.txt`（tests/tools 回归输出）
- `evidence/test-tex-tools-20261004/SHA256SUMS`
