# 参与贡献 DeepTutor

[English](CONTRIBUTING.md) | **简体中文**

感谢你参与 DeepTutor 的建设！写代码、改文档、做翻译、报告 bug、回答别人的问题，都是贡献。

社区：[Discord](https://discord.gg/eRsjPgMU4t) ·
[飞书](./Communication.md) · [微信](https://github.com/HKUDS/DeepTutor/issues/78) ·
[Discussions](https://github.com/HKUDS/DeepTutor/discussions) ·
[Roadmap](https://github.com/HKUDS/DeepTutor/issues/498)

- [加入我们](#加入我们)
- [从哪里开始](#从哪里开始)
- [Pull Request](#pull-request)
- [开发环境](#开发环境)

---

## 加入我们

**我们正在积极招募 Triager 和 Maintainer。** 每个参与贡献的人都是贡献者（Contributor）；参与项目日常维护的人，会担任下面两种角色之一：

| | Triager | Maintainer |
| --- | --- | --- |
| **GitHub 权限** | Triage | Write |
| **职责** | 给新 issue 打标签并分派，复现 bug，追问缺失信息，关闭重复和过期的条目，给 PR 第一轮回复，邀请合适的人 review | Triager 的全部职责，另外负责审核、批准并合并自己熟悉模块中进入 `dev` 的 PR，跟进这些模块的 bug |
| **时间投入** | 每周几小时 | 每周几小时，并在负责的模块里保持稳定回复 |

发版、`main` 分支、仓库设置和密钥由项目负责人管理。

### Maintainer 规则

- 只在 CI 通过且 PR 有人批准（approve）后合并。
- 自己的 PR 需要另一位 Maintainer 批准，错别字和小的文档修改除外。
- 涉及鉴权、代码执行、发版流程或签名的改动，需要项目负责人审核。
- review 时友善、具体，并遵守[行为准则](CODE_OF_CONDUCT.md)。

### 如何加入

- **Triager：** 已经参与了一段时间，比如回答 issue、复现 bug，或者有几个 PR 被合并。
- **Maintainer：** 做过 Triager，或者在某个模块合并过几个有分量的 PR。

如果你符合条件，请发邮件到 [bingxizhao39@gmail.com](mailto:bingxizhao39@gmail.com)，并附上：

- 你在 DeepTutor 开过的 PR 链接
- 你维护过的其他开源项目
- 你能为 DeepTutor 投入的时间

Maintainer 也可能主动邀请表现出色的贡献者。

连续三个月不活跃的成员会转为荣誉成员（emeritus），相应权限会被收回。他们的名字仍保留在下面的名单里，随时欢迎回来。

### 当前团队

- **项目负责人：** [@pancacake](https://github.com/pancacake)
- **Maintainer：** 招募中
- **Triager：** 招募中

---

## 从哪里开始

| 你遇到的情况 | 怎么做 |
| --- | --- |
| 发现 bug | 提交 [bug report](https://github.com/HKUDS/DeepTutor/issues/new?template=bug_report.yml)，写清复现步骤、版本和操作系统。小而明显的修复可以直接提 PR。 |
| 想加功能或改变行为 | 先提交 [feature request](https://github.com/HKUDS/DeepTutor/issues/new?template=feature_request.yml)，等 Maintainer 认可方向后再写代码。 |
| 文档或翻译有问题 | 提交 [docs issue](https://github.com/HKUDS/DeepTutor/issues/new?template=docs.yml) 或直接提 PR。 |
| 有疑问或安装遇到问题 | 到 [Discussions](https://github.com/HKUDS/DeepTutor/discussions) 或 [Discord](https://discord.gg/eRsjPgMU4t) 提问。 |
| 发现安全漏洞 | 通过 [GitHub security advisories](https://github.com/HKUDS/DeepTutor/security/advisories/new) 私下报告，不要公开提 issue。 |

想找点事做？可以看看带
[`good first issue`](https://github.com/HKUDS/DeepTutor/issues?q=is%3Aissue+is%3Aopen+label%3A%22good+first+issue%22)
或 [`help wanted`](https://github.com/HKUDS/DeepTutor/issues?q=is%3Aissue+is%3Aopen+label%3A%22help+wanted%22)
标签的 issue，并留言告诉大家你在做。

---

## Pull Request

**目标分支选 `dev`。** `main` 只在发版时更新，提到 `main` 的 PR 会先被改到 `dev` 再审核。

- **一个 PR 只做一件事。** 不要混入无关的修复、格式调整或重构。
- **关联 issue**，写上 `Closes #123` 或 `Related to #123`。
- **说明问题并给出证据。** 说清楚原来哪里有问题、改了什么，再证明它有效：测试输出、UI 改动的截图或录屏，或者日志。
- **运行与改动相关的检查**（见 [Testing](docs-for-dev/TESTING.md)），以及 `pre-commit run --all-files`。CI 会跑完整测试。
- **保持勾选 "Allow edits by maintainers"**，方便我们推送小修改，让你的 PR 更快合并。
- **欢迎用 AI 辅助写的 PR。** 不需要额外标注，但你必须理解自己提交的代码，并和其他 PR 一样附上证据。

我们一般不接受：

- 纯重构的 PR，除非是 Maintainer 要求的。
- 没有先在 issue 里讨论过的大功能。
- 同一作者同时开超过 20 个 PR。请先完成一些再开新的。

### Commit 信息

```
<type>: <short description>
```

`feat` 新功能 · `fix` 修复 bug · `docs` 文档 · `refactor` 不改变行为的重构 · `test` 测试 · `chore` 构建、工具或依赖

---

## 开发环境

以[开发者手册](docs-for-dev/README.md)为准：安装和配置看 [Agent setup](docs-for-dev/AGENT_SETUP.md)，源码开发流程看 [Development](docs-for-dev/DEVELOPMENT.md)，代码结构看 [Architecture](docs-for-dev/ARCHITECTURE.md)。简要步骤如下（Python 3.11–3.14，Node.js 22 LTS）：

```bash
git clone https://github.com/<you>/DeepTutor.git && cd DeepTutor
git checkout dev

python -m pip install -r requirements/full.txt
python -m pip install -e . --no-deps
python scripts/install_extras.py dev
(cd web && npm ci --legacy-peer-deps)

pre-commit install
```

然后从 `dev` 拉分支（`git checkout -b fix/short-name`）。不要把构建产物、运行时数据和 `node_modules` 提交到 Git。
