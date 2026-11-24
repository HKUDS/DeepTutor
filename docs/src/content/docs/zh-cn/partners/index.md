---
title: 伙伴与渠道
description: DeepTutor Partners 的运维文档：渠道配置、工作区布局和 IM 投递行为。
quadrant: how-to
---

Partners 是可以存在于 Web UI 和外部 IM 应用里的持久 DeepTutor 伙伴。它不是第二套 bot engine。每条入站消息都会变成一个作用域在该 Partner 下的普通 chat-agent turn：

```text
IM / Web message -> PartnerRunner -> ChatOrchestrator -> AgenticChatPipeline -> tools -> reply
```

![伙伴列表](/screenshots/dev/partners.png)

本页是运维指南。想了解伙伴*是什么*（它的灵魂、资料库、记忆与网页 Chat 视图），见[探索 → 伙伴](/zh-cn/explore/partners/)。伙伴也可以在一轮普通聊天里通过[我的智能体](/zh-cn/explore/subagents/)被咨询。

## 账号范围与资料模式

伙伴及伙伴群组属于账号，切换工作区不会改变列表。创建时或在 **Configure → Workspace** 中，可以选择**伙伴私有工作区**，复制获准的知识库、技能和笔记本；也可以绑定所有者的现有工作区，实时共用它的文件、知识库、技能、笔记本，生成文件进入该工作区 outputs 文件夹。绑定后请在工作区的资源入口维护材料，而不是继续复制私有 Library。下方目录树描述的是私有资料模式；灵魂、渠道状态和关系会话在两种模式下都由伙伴保存。详见[伙伴资料模式](/zh-cn/explore/partners/#账号伙伴与工作区资源)。

## 和旧 TutorBot 的区别

| 旧 TutorBot | 新 Partner |
| --- | --- |
| 独立 bot engine，工作区在 `data/tutorbot/<id>/` | 复用 Chat loop，作用域在 `data/partners/<id>/workspace/` |
| `deeptutor bot ...` 命令 | `deeptutor partner list/create/start/stop` |
| 手写 bot YAML 里的 channels | Partners UI 中按 schema 渲染的 channel cards |
| bot skills / memory 独立处理 | 分配的 KB、skills、notebooks、tools、memory 像普通 chat context 一样挂载 |

旧 `/tutorbot/*` 文档地址会重定向到对应的 `/partners/*` 页面，已有外链和书签仍可继续使用。

## 所有权、分配与私有会话

任何已认证用户都可以创建 Partner，并自动成为其所有者。所有者和管理员可以管理它的 soul、资料库、渠道、模型、生命周期与删除操作。管理员还可以把 Partner 分配给其他用户；被分配的用户可以与它对话，但只能看到身份卡片，看不到配置和凭据。

Partner 的配置与复制进来的资料库是共享的，关系状态则彼此隔离。每个已认证的非管理员用户都在 `users/<user_id>/` 下拥有自己的会话文件和关系记忆。与该用户互动时，Partner 还可以读取这个用户自己的共享记忆；新学到的偏好只写入这段私有的 Partner—用户关系记忆。因此，两个人使用同一个 Partner 时不会看到彼此的会话或已学习偏好。管理员会话和未归属到账号的渠道消息则兼容性地使用 Partner 顶层的会话与记忆作用域。

## 推荐配置流程

1. 在 **Partners -> New partner** 创建 Partner。
2. 启用任何 channel 前，先填好 **Identity** 和 **Soul**。第一条 IM 回复就会使用这个 soul。
3. 在 **Mind** 里选择模型；测试阶段先少开可选工具。
4. 在 **Library** 中选择私有复制资料库或绑定所有者的现有工作区，先用一份小资料测试。
5. 在 **Channels** 里先只启用一个 channel，并从本地/私有测试开始。
6. 调试时保留 `send_progress` 和 `send_tool_hints`，生产环境再按需要关闭。
7. 对真实用户开放前，把 `allow_from: ["*"]` 换成明确 sender ids。

![伙伴渠道配置](/screenshots/dev/partners-channels.png)

## Partner Groups

Partners 页面还支持一等公民的 **Partner Groups（伙伴群组）**。从两个或更多 Partner 组建群组，选择成员、讨论模式和共享记忆模式，就能在同一场讨论中保留每个 Partner 各自的角色与推理方式。

每个群组都有独立的会话与持久历史。一轮消息可以发给全部成员，也可以只指定部分成员；每个成员的回复占据独立 seat。某个 seat 失败时，可以只重试这一席，而不用让已经答完的 Partner 全部重跑。

## Channel 入口

| Channel | 适用场景 | 页面 |
| --- | --- | --- |
| <img src="/channel-icons/weixin.svg" alt="" width="16" height="16" /> WeChat (`weixin`) | 个人微信，扫码登录，HTTP long-poll | [WeChat](/zh-cn/partners/weixin/) |
| <img src="/channel-icons/wecom.svg" alt="" width="16" height="16" /> WeCom (`wecom`) | 企业微信 / WeChat Work AI Bot 平台 | [WeCom](/zh-cn/partners/wecom/) |
| <img src="/channel-icons/qq.svg" alt="" width="16" height="16" /> QQ (`qq`) | 腾讯官方 QQ Bot，botpy SDK | [QQ / NapCat](/zh-cn/partners/qq/) |
| <img src="/channel-icons/napcat.svg" alt="" width="16" height="16" /> NapCat (`napcat`) | 个人 QQ，通过 OneBot v11 / NapCat 接入 | [QQ / NapCat](/zh-cn/partners/qq/) |
| <img src="/channel-icons/telegram.svg" alt="" width="16" height="16" /> Telegram (`telegram`) | 上手最快——BotFather 拿 token，无需公网 IP | [Telegram](/zh-cn/partners/telegram/) |
| <img src="/channel-icons/discord.svg" alt="" width="16" height="16" /> Discord (`discord`) | Discord server 和 DM，Gateway WebSocket | [Discord](/zh-cn/partners/discord/) |
| <img src="/channel-icons/slack.svg" alt="" width="16" height="16" /> Slack (`slack`) | Slack team，Socket Mode，线程回复 | [Slack](/zh-cn/partners/slack/) |
| <img src="/channel-icons/feishu.svg" alt="" width="16" height="16" /> Feishu (`feishu`) | 飞书 / Lark，CardKit 流式卡片 | [Feishu](/zh-cn/partners/feishu/) |
| <img src="/channel-icons/dingtalk.svg" alt="" width="16" height="16" /> DingTalk (`dingtalk`) | 钉钉企业机器人，Stream Mode | [DingTalk](/zh-cn/partners/dingtalk/) |
| <img src="/channel-icons/matrix.svg" alt="" width="16" height="16" /> Matrix (`matrix`) | 去中心化房间，可选 E2EE | [Matrix](/zh-cn/partners/matrix/) |
| <img src="/channel-icons/zulip.svg" alt="" width="16" height="16" /> Zulip (`zulip`) | stream + topic 结构化团队聊天 | [Zulip](/zh-cn/partners/zulip/) |
| <img src="/channel-icons/mattermost.svg" alt="" width="16" height="16" /> Mattermost (`mattermost`) | 自托管 Mattermost，原生 v4 WebSocket | [Mattermost](/zh-cn/partners/mattermost/) |
| <img src="/channel-icons/whatsapp.svg" alt="" width="16" height="16" /> WhatsApp (`whatsapp`) | 通过 bridge 运行时接 WhatsApp | [WhatsApp](/zh-cn/partners/whatsapp/) |
| <img src="/channel-icons/email.svg" alt="" width="16" height="16" /> Email (`email`) | IMAP/SMTP 异步收发件箱工作流 | [Email](/zh-cn/partners/email/) |
| <img src="/channel-icons/mochat.svg" alt="" width="16" height="16" /> Mochat (`mochat`) | 客服式聊天面板 | [Mochat](/zh-cn/partners/mochat/) |
| <img src="/channel-icons/msteams.svg" alt="" width="16" height="16" /> Microsoft Teams (`msteams`) | Teams，Bot Framework webhook 监听 | [Microsoft Teams](/zh-cn/partners/msteams/) |

各渠道的连接模型、必填字段和投递开关对照，请看 [渠道矩阵](/zh-cn/partners/channels/)。

## 运行时状态

```text
data/partners/<partner_id>/
├── config.yaml                  # Partner identity, model, channels, tools
├── sessions/                    # 共享/未归属账号的会话
│   ├── <session_key>.jsonl      # 每个会话一个 append-only 文件
│   └── _index.json              # 需要时创建的归档元数据
├── channels/
│   └── <channel>/...            # QR token、cursor、conversation ref
├── users/<user_id>/             # 已认证用户的私有关系状态
│   ├── sessions/<session_key>.jsonl
│   └── workspace/memory/
└── workspace/
    ├── knowledge_bases/         # 复制过来的 assigned KBs
    └── user/
        ├── workspace/SOUL.md
        ├── workspace/skills/<name>/SKILL.md
        ├── workspace/notebook/
        └── workspace/memory/
```

私有资料模式会复制分配资源，便于保留独立演进的资料库。绑定工作区时则共用其实时资源；伙伴的灵魂、渠道状态、会话及关系记忆仍独立保存。

## 对话命令

所有 Partner 对话共用这组 slash commands：

- `/help` —— 查看可用命令。
- `/new` —— 归档当前会话并新开一段；`/branch` 会归档当前会话，再从其副本继续；`/stop` 停止生成中的回复。
- `/sessions` —— 列出会话 id；`/resume <session-id>` 恢复已归档会话，`/delete <session-id>` 永久删除会话。
- `/status` —— 查看 Partner、会话、模型与工具状态；`/history [n]` 查看最近消息。
- `/tool [on|off <name>|reset]` —— 查看或调整 Partner 已启用的工具。
- `/model [number|model name]` —— 所有者或管理员在私聊里列出或切换模型。
- `/link <code>` —— 在外部 IM 私聊里，把该账号关联到生成此 code 的 DeepTutor 用户。

## Web UI vs CLI

配置 channel 推荐用 Web UI，因为它会从 `/api/partners/channels/schema` 渲染实时 schema，并自动 mask secret 字段。CLI 更适合 lifecycle 检查：

```bash
deeptutor partner list
deeptutor partner start math-tutor
deeptutor partner stop math-tutor
```
