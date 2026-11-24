---
title: DeepTutor 生态
description: 通过 RAG 集成、可复用 Skill、远程 MCP 服务、沙箱化 CLI App 与 EduHub 扩展 DeepTutor。
quadrant: explanation
---

DeepTutor 的内置学习界面覆盖日常使用；**生态**则让你在不修改核心代码的前提下增加行为与工具：连接检索引擎、教模型一套工作流、连接外部服务、安装命令行应用，或发现社区 Skill。

![个性化与可复用的账户资源](/screenshots/dev/personalization.png)

## 五条扩展路径

| 扩展 | 增加什么 | 由谁管理 |
|---|---|---|
| [**Skill**](/zh-cn/ecosystem/skills/) | 模型在需要某套流程时读取的 `SKILL.md` 手册 | 内置、本地、ClawHub 或 EduHub |
| [**MCP 服务**](/zh-cn/ecosystem/mcp/) | 托管或部署级 MCP 服务器暴露的工具 | 远程服务按账号；部署注册表由管理员管理 |
| [**CLI App**](/zh-cn/ecosystem/cli-apps/) | 安装在服务器、以沙箱工具形式进入对话的命令行程序 | 管理员安装和授权；获准账号运行 |
| [**RAG 集成**](/zh-cn/ecosystem/rag-integration/) | 知识库背后的本地、智能体式、远程或实时资料库检索 | 部署配置 + 每个 KB 的选择 |
| [**EduHub**](/zh-cn/ecosystem/eduhub/) | 面向 Skill 的社区发现、版本、导入与发布 | 社区作者发布；用户审阅并导入 |

每条路径的信任边界不同。RAG 集成负责检索，Skill 是指令，MCP 服务是远程工具边界，CLI App 则是在主机安装的代码；EduHub 分发 Skill，但不成为它的运行时。因此 DeepTutor 为各条路径分别设计配置、安装、凭据、沙箱与授权模型。

## 它们在产品里的位置

知识引擎从**知识中心**选择；Skill、MCP 服务和 CLI App 从**个性化**管理，EduHub 则嵌在 Skill 导入器里。启用后，工具通过与内置工具相同的发现流程进入主页智能体。

## 从工作区任务出发

在当前工作区的**资源**中保留课程或项目文件，在**学习**中学习材料，在**主页**提出问题或生成成果。[个性化](/zh-cn/explore/personalization/)则是账号的人格、技能、智能体和连接资源架，切换工作区后仍然存在。

技能和 MCP 服务先在设置的工作区 **Assigned resources（分配资源）**中配置，再按需缩小当前对话范围。分配引用账号资源库，不复制凭据，也不绕过用户授权。CLI 应用另有管理员安装与授权规则。RAG 则关联知识库及其检索材料。

## 下一步

检索本身是扩展点时，先看 [RAG 集成](/zh-cn/ecosystem/rag-integration/)；要教模型一套可复用流程时看 [Skill 扩展](/zh-cn/ecosystem/skills/)，连接账号型在线服务时看 [MCP 扩展](/zh-cn/ecosystem/mcp/)，需要真实命令行程序时看 [CLI-App 扩展](/zh-cn/ecosystem/cli-apps/)。发现或发布社区 Skill 则进入 [EduHub](/zh-cn/ecosystem/eduhub/)。
