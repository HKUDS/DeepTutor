---
title: EduHub
description: 发现社区 Skill，安装前检查内容，通过 DeepTutor 的安全闸门导入，并发布自己的版本。
quadrant: how-to
---

[EduHub](https://eduhub.deeptutor.info) 是 DeepTutor 面向 Skill 的社区分发层。它连接本地 `SKILL.md` 资料库与共享目录：学习者发现可复用工作流，作者发布带版本的软件包，而 DeepTutor 把安装放在显式审阅与安全边界之后。

## 从 Web UI 发现 Skill

打开**个性化 → Skills → Import from EduHub**。应用内目录可以搜索社区 Skill，查看说明和版本，打开对应 EduHub 页面，并安装到技能页面当前选择的库：账号共享技能或指定工作区。导入前先确认范围。

![从技能库导入社区技能](/screenshots/dev/skills.png)

这个目录刻意只是导入流程，而不是第二套运行时。安装后，EduHub Skill 与其他本地 Skill 完全一样，由模型按需读取。

## 安装安全闸门

导入包可用之前，DeepTutor 会：

1. 检查 Hub 判定结果与软件包元数据；
2. 以防路径穿越的方式解压到受控目标；
3. 拒绝二进制文件和不安全归档内容；
4. 扫描提示词自注入模式；
5. 记录安装来源与版本，供后续更新。

这不代表所有社区指令都天然可信。在敏感工作流中启用 Skill 前，仍应像审阅脚本或依赖一样先读一遍。

## 从 CLI 发布

作者通过 CLI 完成授权、发布、更新与回滚：

```bash
deeptutor skill login
deeptutor skill publish <directory>
deeptutor skill update
```

`login` 在浏览器中完成授权；`publish` 上传 Skill 目录与元数据；`update` 列出你拥有的软件包，方便发布新版本或回退旧版本。

## EduHub 与其他目录

EduHub 是 Web UI 内集成的社区体验。DeepTutor 也能通过显式目录前缀从其他受支持的 Skill 目录安装，例如 ClawHub：

```bash
deeptutor skill install clawhub:<slug>
```

## 另见

- [Skill 扩展](/zh-cn/customize/skills/)——Skill 进入 DeepTutor 后如何工作
- [CLI 命令](/zh-cn/developers/reference/cli/)——完整 Skill 命令参考
- [DeepTutor 生态](/zh-cn/customize/)——比较 Skill、MCP 服务与 CLI App

