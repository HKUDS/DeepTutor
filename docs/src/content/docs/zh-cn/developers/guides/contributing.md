---
title: 参与贡献
description: 如何为 DeepTutor 贡献代码、文档或修复 bug —— 分支策略、环境搭建、PR 检查清单。
quadrant: how-to
---

感谢你对 DeepTutor 的兴趣。分诊员与维护者招募详情见根目录的 [`CONTRIBUTING.md`](https://github.com/HKUDS/DeepTutor/blob/main/CONTRIBUTING.md)。

## 路线图

DeepTutor 的公开路线图维护在 [`HKUDS/DeepTutor#498`](https://github.com/HKUDS/DeepTutor/issues/498)。你可以在那里查看计划中的工作、表达优先级、或在开始较大的贡献前提出新方向。

## PR 应该提到哪个分支

**所有贡献都提到 `dev`。** `main` 仅在发布版本时更新。

| 分支 | 适合 |
|------|------|
| `dev` | 默认目标 —— 新功能、重构、bug 修复、API / 配置改动 |
| `main` | 发布分支 —— 指向它的 PR 会改为指向 `dev` |

功能先讨论，PR 保持聚焦。

## 快速上手

```bash
# 1. Fork + clone，先与目标分支同步
git checkout dev && git pull origin dev

# 2. 拉新分支
git checkout -b feature/your-feature-name

# 3. 编辑模式安装全套
python -m pip install -r requirements/full.txt
python -m pip install -e . --no-deps
python scripts/install_extras.py dev
(cd web && npm ci --legacy-peer-deps)

# 4. 配置 pre-commit（每台机器一次）
pip install pre-commit
pre-commit install

# 5. 改完跑一遍校验
pre-commit run --all-files

# 6. 把 PR 提到 dev，并附相关测试证据
```

可以从 [`good first issue`](https://github.com/HKUDS/DeepTutor/issues?q=is%3Aissue+is%3Aopen+label%3A%22good+first+issue%22) 标签找入手点。开工前先在 issue 下留言，避免重复劳动。

## 编码规范

CI 会强制检查；`pre-commit run --all-files` 在本地能查出大部分问题。

| 范畴 | 规则 |
|------|------|
| Python | 所有函数签名加 type hint；遵循 PEP 8（Ruff 强制）；用 f-string；保持函数小而专一 |
| Docstring | 新模块 / 类 / public 函数使用 Google 风格 docstring |
| Secrets | 严禁提交；每个 PR 上 `detect-secrets` 都会跑 |
| Subprocess | 永远用 `shell=False` |
| 路径 | `pathlib.Path` 优于字符串拼接 |

底层工具链：**Ruff**（lint + format）、**Prettier**（前端 / 配置）、**detect-secrets**、**pip-audit**、**Bandit**、**MyPy**、**Interrogate**。

## Commit message 格式

```
<type>: <short description>

[optional body]
```

| Type | 用法 |
|------|------|
| `feat` | 新增用户可见功能 |
| `fix` | 修复已有功能的问题 |
| `docs` | 仅文档 |
| `style` | 仅格式化 |
| `refactor` | 重构，无行为变化 |
| `test` | 增 / 改测试 |
| `chore` | 构建 / 工具链 / 依赖 |

## 评审会看什么

- **正确性** —— 是否真的解决了问题？是否引入回归？
- **范围** —— 小而聚焦的 PR 比庞大杂烩 PR 合得快；拿不准就拆。
- **测试** —— 新行为要有对应覆盖；bug 修复尽量带回归测试。
- **文档** —— 影响用户的改动要同步更新 `site/docs/src/content/docs/` 下的相关页面。

## 寻求帮助

- [Discord](https://discord.gg/eRsjPgMU4t) —— 提问最快的地方
- [GitHub Discussions](https://github.com/HKUDS/DeepTutor/discussions) —— 长篇问答
- [微信社区](https://github.com/HKUDS/DeepTutor/issues/78) —— 中文贡献者群
- [Issues](https://github.com/HKUDS/DeepTutor/issues) —— bug 反馈与功能建议

## 参考

- [`CONTRIBUTING.md`](https://github.com/HKUDS/DeepTutor/blob/main/CONTRIBUTING.md) —— 完整文档（分支策略、安全实践、维护者）
