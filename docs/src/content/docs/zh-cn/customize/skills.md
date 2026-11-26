---
title: Skill 扩展
description: 使用内置 Skill、本地创作、ClawHub 或 EduHub 社区目录，为 DeepTutor 加入可复用的 SKILL.md 工作手册。
quadrant: how-to
---

Skill 是模型按需读取的 **`SKILL.md` 工作手册**。它不用增加新的可执行服务，就能教给 DeepTutor 一套流程、风格或领域行为。

## 浏览与管理 Skill

打开**个性化 → Skills**。Skill 支持标签与搜索；内置 office skill（`docx`、`pdf`、`pptx`、`xlsx`）和预设为只读，你自己的 Skill 则可以随着工作流持续演进。

![技能库](/screenshots/dev/skills.png)

一个实用的 Skill 应说明**什么时候使用**、需要哪些输入、哪些步骤或约束不可忽略，以及成功输出是什么样子。内置的 `skill-creator` 会帮助你写出这套结构，不必从空文件开始。

## 从 EduHub 导入

选择 **Import from EduHub**，可以直接浏览社区 Skill 并下载到自己的库里。导入内容通过安全闸门后才会可用。发现、审阅、安全检查、发布与版本管理详见 [EduHub](/zh-cn/customize/eduhub/)。

## 从 CLI 安装与发布

CLI 还支持其他目录，并能发布 Skill：

```bash
deeptutor skill install clawhub:<slug>
deeptutor skill login
deeptutor skill publish <directory>
deeptutor skill update
```

`login` 会在浏览器中完成 Hub 授权；`publish` 上传一个 Skill 目录，`update` 列出你发布过的包，方便发布新版本或回滚。

## 创建、测试与维护技能

1. 打开**个性化 → 技能**，在 **Skill library（技能库）**选择账号共享技能或某个工作区。这里的选择决定写入位置，不取决于打开个性化之前正在查看哪个工作区。
2. 创建技能，填写明确的名字与说明，编写 `SKILL.md`。写清输入、重要约束与输出形式；需要的配套文件放在指令旁边。
3. 在**设置 → 工作区**中允许目标工作区使用该技能；回到主页，再用输入框的技能选择缩小当前对话的范围，以真实小任务测试。
4. 根据结果修改指令。删除前检查使用提示列出的工作区，替换或移除相应选择，以免后续流程缺少技能。

运行时的同名技能优先级是：工作区本地、账号自有、管理员分配、内置。工作区允许列表仍然生效，因此本地版本能定制一个已启用技能，而不改变其他课程的共享版本。

## 技能如何连接学习

评分表技能可以指导资源中文档的反馈，复习技能可以指导主页围绕同一课程的对话。引导式学习的学习输入框也使用工作区允许的技能。技能提供流程，不保存学习进度，也不替代课程来源材料。

把通用流程放在账号库，把课程变体放在工作区库。复制到 Partner 私有库的技能是快照；绑定工作区的 Partner 则读取该工作区的实时资源。

## 另见

- [个性化](/zh-cn/customize/)——账号资源架与工作区选择
- [EduHub](/zh-cn/customize/eduhub/)——发现并发布社区 Skill
- [MCP 扩展](/zh-cn/customize/mcp/)——连接运行在 DeepTutor 之外的工具
- [CLI 命令](/zh-cn/developers/reference/cli/)——完整命令参考
