---
title: 运行目录
description: 自部署的 DeepTutor 把设置、工作区和账户数据放在哪里。
quadrant: explanation
---

每条安装路径最后都落到同一个运行目录。设置在启动目录下的 `data/user/settings/`，也可以用 `DEEPTUTOR_HOME` 或 `deeptutor start --home` 指定。知识库、记忆、伙伴运行状态、多用户账户和审计日志都在同一棵 `data/` 里。把这棵目录，以及单独配置的内容工作区目录，一起持久化。

运行目录是部署的存储根，和应用里选中的工作区不是一回事。主页、学习和资料跟随当前工作区；伙伴和个性化属于账户。

进程环境变量只覆盖启动时的少量项，例如传给 `deeptutor start` 的端口。Podman 的宿主机端口映射写在 `.env.example`，不写进应用设置文件。

## 安装路径

| 路径 | 适合 | 页面 |
| --- | --- | --- |
| PyPI | 已发布的包，1.7.0 之后的完整应用 | [PyPI](/zh-cn/self-hosting/pypi/) |
| 源码 | 当前 dev 检出 | [从源码运行](/zh-cn/self-hosting/source/) |
| Docker | 一个已发布容器 | [Docker 教程](/zh-cn/get-started/docker/) 和 [运维](/zh-cn/self-hosting/docker/) |
| 纯 CLI | 不要 Web 前端 | [纯 CLI](/zh-cn/self-hosting/cli-only/) |
| 桌面端 | macOS 或 Windows 上双击打开 | [桌面版本](/zh-cn/self-hosting/desktop/) |

桌面端和 Docker 的快速上手仍在[从这里开始](/zh-cn/get-started/)。本页是部署地图。
