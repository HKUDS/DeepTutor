---
title: 我的智能体
description: "我的智能体——在一轮聊天里咨询本地 agent harness、已配置的 ACP 智能体、远程 Hermes 网关或某个伙伴，并把 Claude Code / Codex / ChatGPT 对话导入为有名字、可续聊的智能体。"
quadrant: how-to
---

**My Agents**（我的智能体）把其他智能体变成 DeepTutor 的上下文。它做两件不同的事：让你在一轮聊天里**实时咨询一个活的智能体**（本机受支持的 harness 或已配置的 ACP 智能体、远程 Hermes 网关，或你的某个伙伴），以及把 **Claude Code / Codex / ChatGPT 历史对话导入**为有名字、可搜索、可续聊的智能体。

## 它在哪里

点击左侧栏的 **My Agents**（我的智能体）。在聊天里你也有两条捷径触达活的智能体：输入框工具栏上的 **Agent 胶囊**（机器人图标），或在消息框里输入 **`@`**。

![我的智能体](/screenshots/dev/agents.png)

页面分为两节，正好对应这两个概念。

## 账号连接与工作区使用

从**个性化 → 子智能体**打开这个资源库。连接属于账号，切换工作区后仍然存在；在工作区**主页**选择连接进行实时请教，导入的历史则是按任务选择的参考材料。

建立连接不等于获得当前工作区全部文件的访问权。本机 agent 在服务端机器上，使用自己的工作目录和主机凭据执行；切换 DeepTutor 工作区不会自动重设该目录。连接项目 agent 时应确认路径。Partner 则使用自己配置的资料模式与私有会话连续性，即使从其他工作区的主页请教也一样。

例如，课程项目可以把讲义放在资源中，在主页请教编程 agent，再回到学习进行练习。请提供具体问题和所需依据。导入旧历史有助于找回过去的决定；运行已连接 agent 则获得新的回答。

## 连接的智能体——咨询一个活的智能体

**连接的智能体**（connected agent）是 DeepTutor 能实时对话的真实智能体。点击 **Connect agent**，从下面三种里选一个：

- 本机的一个 agent harness——**Claude Code**、**Codex**、**Grok CLI**、**Antigravity CLI**、**Kimi CLI**、**opencode**、**MiMo Code**、**Hermes Agent**、**OpenClaw**、**DeepSeek Harness** 或已配置的 **ACP** 智能体，
- 一个已配置的**远程 Hermes 网关**（Hermes Agent (remote)），或
- 你的某个**伙伴**（Partner）。

咨询一个连接的智能体时，DeepTutor 不是把对话记录粘进来——它真的*运行*那个智能体并把它的工作流式回传。在底层，连接的智能体是第三类上下文来源，拥有一项独有能力：聊天循环里的 `consult_subagent` 工具会多轮驱动该智能体，并在活动面板里实时展示它的完整运行过程。

### 在聊天里咨询

用 **Agent 胶囊**选中智能体，然后设置 **Max rounds DeepTutor may ask**（DeepTutor 最多可追问的轮数）——也就是这次咨询里来回轮次的上限。


输入 **`@`** 可筛选同一列表；选择会持续到清除或替换。


### 一次实时咨询长什么样

咨询一个 **Claude Code** 智能体时，它会在自己的工作目录里运行——读取文件、grep、对着真实仓库推理。它的工具调用会流式进入活动面板，同时 DeepTutor 把结论收拢进你的答复。

咨询一个**伙伴**时，DeepTutor 把问题送进那个伙伴自己的会话——于是伙伴会用它的灵魂（soul）、它的资料库、它私有的记忆工具（`partner_search`、`partner_read`）以及技能（`read_skill`）来作答。一个聊天线程会绑定到一个伙伴会话，因此追问会延续同一段对话。

## 导入的对话——来自你历史记录的智能体

页面的下半部分会导入你已有的 **Claude Code、Codex 与 ChatGPT 对话**，并把每个来源呈现为一个**有名字的智能体**，可搜索、可打开、可继续聊，或在聊天里引用。

点击 **Import conversations** 导入历史。本地文件夹要先起名字，再选择范围：**Claude Code 按项目 / 工作目录**，**Codex 按日历日期**；刷新会重新同步同一范围。ChatGPT 的 `conversations.json` 导出是一次性快照，重复导入不会产生重复对话。你能精确决定哪些历史成为 DeepTutor 上下文。


导入的智能体会显示来源、对话数量与上次同步时间。在这里你可以：

- **打开一段对话**，在 DeepTutor 里继续聊。
- **刷新**某个智能体，拉进所选日期或项目范围内的新对话。
- 在任意一轮聊天里，通过 **`+` → My Agents** **引用**一段导入的对话——DeepTutor 会把它当作第三方对话记录来读（它仍是「他们的」对话，DeepTutor 不会以第一人称代入）。

## 两者的区别

| | 连接的智能体 | 导入的对话 |
| --- | --- | --- |
| **是什么** | DeepTutor 实时运行并对话的活智能体 | 作为命名智能体引入的只读历史 |
| **来源** | 十种具名本地 harness（Claude Code / Codex / Grok / Antigravity / Kimi / opencode / MiMo / Hermes / OpenClaw / DeepSeek Harness）、已配置的 ACP 智能体、远程 Hermes 或伙伴 | 过去的 Claude Code / Codex 会话，或 ChatGPT 导出 |
| **在聊天里** | 用 Agent 胶囊或 `@` 选择；运行实时流式，选择会持续 | 用 `+` → My Agents 引用，或打开续聊 |
| **新鲜度** | 实时，每次咨询都是 | 快照；用 **Refresh** 重新同步所选日期或项目 |

## 另见

- [主页](/zh-cn/learning-workspace/chat/)——在这里咨询与引用智能体
- [伙伴](/zh-cn/channels/)——把一个伙伴连接成可咨询的智能体
- [记忆](/zh-cn/learning-workspace/memory/)——导入的上下文如何与 DeepTutor 自己的声音保持区隔
