---
title: 快速入门
description: 了解 DeepTutor 是什么，安装 Open DeepTutor 桌面端，接上第一个语言模型，并完成你的第一次学习对话。
quadrant: tutorial
---

## DeepTutor 是什么？

DeepTutor 是安装在你电脑上的 **AI 学习工作台**。

如果把普通网页版 AI（如 ChatGPT、DeepSeek 网页版）比作“随时问答的聊天窗口”，DeepTutor 则更像你的 **私人学习书房**：

- **带着你的材料学**：上传讲义、PDF、论文或网页，回答会标注出处，点一下就能回到原文核对。
- **按学科分工作区**：高数、英语、科研项目各用独立工作区，对话、笔记、错题和知识库互不混杂。
- **不止能聊天**：除了对话，还内置拍照解题、出题练习、精通之路（拆解学习目标）、沉浸式阅读与学习笔记。
- **数据留在你自己手里**：笔记、对话和设置保存在本地电脑，换模型不会丢记录。

:::note[为什么安装后不能直接回复？]
DeepTutor 提供的是学习界面与工具，回答问题需要接上一个 **AI 模型**（可以理解为给工作台装上“大脑”）。你不需要一次配齐所有模型——**先接上 1 个语言模型，就能开始聊天和学习**。
:::

## 1. 下载并安装 Open DeepTutor

**Open DeepTutor** 是桌面应用，自带 Python 和 Node.js 运行环境，不需要你手动配置开发环境或敲命令行。

| 你的电脑 | 下载安装包 | 安装方式 |
| --- | --- | --- |
| Apple 芯片 Mac（M1/M2/M3/M4） | [macOS（Apple 芯片）版 Open DeepTutor](https://github.com/HKUDS/DeepTutor/releases/latest/download/Open-DeepTutor-MacOS-Apple-Silicon.dmg) | 打开 DMG，将 **Open DeepTutor** 拖入“应用程序”。 |
| Intel 芯片 Mac | [macOS（Intel）版 Open DeepTutor](https://github.com/HKUDS/DeepTutor/releases/latest/download/Open-DeepTutor-MacOS-Intel.dmg) | 打开 DMG，将 **Open DeepTutor** 拖入“应用程序”。 |
| Windows（64 位） | [Windows 版 Open DeepTutor](https://github.com/HKUDS/DeepTutor/releases/latest/download/Open-DeepTutor-Windows-Setup.exe) | 双击完成安装向导。 |

:::caution[Windows 安全提示]
当前 Windows 安装包未签名，SmartScreen 可能会弹窗拦截。点击 **更多信息 → 仍要运行** 继续安装。Windows 便携 ZIP 在[同一个 Release](https://github.com/HKUDS/DeepTutor/releases/latest) 上。如果你使用 Docker、PyPI、源码或纯 CLI，请看[其他安装方式](/zh-cn/get-started/)。
:::

启动 **Open DeepTutor**。第一次打开会先解压自带运行时，稍等片刻后弹出工作区窗口。当侧栏里出现 **主页（Home）** 时，就可以继续。如果几分钟后仍停在启动画面，退出再重新打开一次。

<!-- TODO(screenshot): 补充首次打开桌面端工作区的截图，标出左上角工作区菜单 -> 设置（Settings）入口（建议保存到 docs/public/screenshots/dev/quickstart-workspace.png）。 -->

## 2. 接上你的第一个语言模型

还没有配置模型时，在对话框发消息会看到提示：

> No active LLM model is configured. Please set it in Settings > Language models.

意思是尚未配置正在使用的语言模型。接下来按应用内置的三步引导完成配置：

1. 点击左上角的工作区名称（例如 **General workspace**），选择 **Settings（设置）**。
2. 在 **常规（General）** 页面找到 **Set up chat first（先配置对话）**，按顺序完成三步。

<!-- TODO(screenshot): 补充“设置 -> 常规”页面中“Set up chat first”三步引导区的截图（建议保存到 docs/public/screenshots/dev/quickstart-setup-checklist.png）。 -->

### 第 1 步：连接提供方（Provider）

**提供方（Provider）** 是为你提供 AI 能力的平台或本地服务。点击 **1. Connect a provider** → **Add provider**，按你手头的条件二选一：

- **方式 A：使用已有账号登录（不用找密钥）**
  如果你有带 Codex 权限的 ChatGPT 账号、GitHub Copilot 账号或 CodeBuddy 账号，选择 **OpenAI Codex**、**GitHub Copilot** 或 **CodeBuddy/WorkBuddy**，按提示在浏览器完成登录授权。看到 **Authentication received. You can return to DeepTutor.** 后返回应用，确认页面显示已连接并列出可用模型。
- **方式 B：填写 API Key（最通用，支持 DeepSeek、通义千问、OpenAI 等）**
  1. 选择签发密钥的平台（例如 **DeepSeek**、**OpenAI**、**DashScope (Qwen)** 或 **SiliconFlow**），点击 **Continue**。
  2. **Provider URL** 使用官方默认地址时按提示留空；使用中转网关或私有部署时再填写平台给出的 API 地址。
  3. 粘贴 **API key**（这是给程序用的访问密钥，不是账号登录密码；不要在截图或群聊中泄露）。
  4. 如果出现 **Language-model API protocol**，先保留 **Auto**；确认可用服务类型包含 **Language models**。
  5. 向下滚动到 **Provider connection**，点击 **Test provider**。看到 **Model list retrieved** 后，点击页面底部的 **Language models →**。

:::tip[还没有 API Key，或者不确定选哪家平台？]
先看[模型配置指南](/zh-cn/get-started/models/)，里面对比了三种获取模型的方式，并整理了“网页会员 ≠ API 额度”等新手常见避坑点。
:::

<!-- TODO(screenshot): 补充“设置 -> 提供方 -> Add provider”页面截图，展示 API key 填写与“Test provider”按钮（使用脱敏示例数据，建议保存到 docs/public/screenshots/dev/quickstart-add-provider.png）。 -->

### 第 2 步：选择具体模型并测试

打开 **设置 → 模型与服务 → 语言模型（Language models）**（或返回 **General** 点击 **2. Choose a chat model**）：

1. 从已连接的提供方中选择一个具体型号（手动添加时，填写平台文档给出的准确 **Model ID**）。
2. 点击 **Test model**，确认账号能正常调用这个型号。
3. 如果出现 **Reasoning effort（推理强度）**，首次体验保留默认值或选择 **low（轻度）**。
4. 点击 **Set as default（设为默认）**。

### 第 3 步：应用更改

点击页面底部工具栏的 **Apply changes（应用更改）**。

确认所选模型显示 **Default model**，且页面状态变为 **Applied**。**Save draft** 只保存草稿、暂不启用；点击 **Apply changes** 才会正式生效。

<!-- TODO(screenshot): 补充“设置 -> 语言模型”页面截图，标出 Test model、Default model 标签以及底部 Apply changes 按钮（建议保存到 docs/public/screenshots/dev/quickstart-apply-model.png）。 -->

## 3. 完成你的第一次学习对话

返回 **主页 → 对话（Home → Chat）**，确认输入框旁已显示刚选好的模型名称。已有对话可能保留之前的选择，需要时点击模型选择按钮切换。

发送下面这段话：

> 我想练习英语写作，请用中文讲解。给我一个日常话题，让我用英文写四到六句话。等我回答后，指出最影响理解的两个问题，给我提示，让我自己修改。

收到题目后，自己作答并发送。根据反馈修改，再回复：

> 这是我修改后的答案。刚才那两个问题解决了吗？

当 DeepTutor 针对你的修改正常回复，你就完成了第一次学习循环：**收到任务 → 自己作答 → 获得反馈 → 修改巩固**。

如果仍提示未配置模型，检查提供方连接、**Default model** 标记、是否点了 **Apply changes** 以及当前对话的模型选择，然后点击 **Retry**。

## 数据放在哪里

笔记、对话和设置都保存在本机工作区目录里。安装新版本桌面应用不会清空这些数据：

| 系统 | 工作区数据 |
| --- | --- |
| macOS | `~/Library/Application Support/Open DeepTutor/workspace/data` |
| Windows | `%LOCALAPPDATA%\Open DeepTutor\workspace\data` |

## 下一步

日常聊天不需要先配齐嵌入、语音、图片或视频模型，以后用到对应功能时再添加。

- [模型配置指南](/zh-cn/get-started/models/) — 看懂七类模型的区别，按学习场景选出合适组合。
- [带着材料学习](/zh-cn/learn/ask-with-a-source/) — 附上一份 PDF 或笔记，让回复带上可点击核对的原文出处。
- [从照片解题](/zh-cn/learn/solve-a-photo/) — 拍下纸上的题目，一步步看懂解法。
- [串起一次完整学习](/zh-cn/learning-workspace/) — 用一个主题、一份材料、一个问题串起工作区。
- [更新日志](/zh-cn/get-started/changelog/) — 替换旧版桌面应用前先看这里。v1.7.4 更换了运行时签名密钥，需要安装这个版本的应用本身，而不是把更新导入旧版本。
