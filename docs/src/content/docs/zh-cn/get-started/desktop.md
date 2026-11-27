---
title: 桌面端快速上手
description: 安装 Open DeepTutor，接上一个语言模型，发出第一条消息。
quadrant: tutorial
---

Open DeepTutor 是桌面应用。第一次打开时，它会解开自带的 Python 和 Node 运行时，在这台电脑上启动服务，然后显示工作区。你不用自己再装 Python、Node 或源码。

## 1. 下载这台电脑对应的应用

| 这台电脑 | 下载 |
| --- | --- |
| Apple 芯片的 Mac | [macOS（Apple 芯片）版 Open DeepTutor](https://github.com/HKUDS/DeepTutor/releases/latest/download/Open-DeepTutor-MacOS-Apple-Silicon.dmg) |
| Intel 芯片的 Mac | [macOS（Intel）版 Open DeepTutor](https://github.com/HKUDS/DeepTutor/releases/latest/download/Open-DeepTutor-MacOS-Intel.dmg) |
| Windows | [Windows 版 Open DeepTutor](https://github.com/HKUDS/DeepTutor/releases/latest/download/Open-DeepTutor-Windows-Setup.exe) |

打开刚下载的文件。在 Mac 上，把应用拖进“应用程序”。在 Windows 上，把安装向导走完。安装包没有签名，SmartScreen 会让你确认；选择继续运行。完成后，应用程序列表里能看到 **Open DeepTutor**。

Windows 便携 ZIP 在[同一个 Release](https://github.com/HKUDS/DeepTutor/releases/latest) 上。这篇教程用的是上面的安装包。

## 2. 等到工作区打开

启动 **Open DeepTutor**。第一次启动会先解开自带运行时，再打开 DeepTutor 窗口。侧栏里能看到主页时，就可以继续。如果过了几分钟还停在启动画面，退出再打开一次。

## 3. 连接你的 AI 账号，或填写 API Key

DeepTutor 提供学习界面和工具，回答问题还需要连接 AI 模型。你可以连接自己已有使用权限的 AI 模型平台账号，也可以使用从相关 AI 平台获得的 **API Key（访问密钥）**。

如果还没有配置，发送问题时可能看到：

> No active LLM model is configured. Please set it in Settings > Language models.

意思是：尚未配置正在使用的 AI 模型，请前往“设置 → 语言模型”进行配置。

点击左上角的工作区名称，例如 **General workspace**，选择 **Settings（设置）**。在 **General** 页面找到 **Set up chat first**，点击 **1. Connect a provider**。进入 **Providers** 后，点击 **Add provider**。

**Provider** 可以理解为“你从哪里获得 AI”，本文称它为“服务提供商”。我们主要通过对话框与 AI 互动，因此先配置聊天功能，请查看标有 **Language models（语言模型）** 的选项。

### 方式 A：填写 API Key

| API Key 来源 | 选择的选项 |
| --- | --- |
| OpenAI 平台 | **OpenAI** |
| DeepSeek 平台 | **DeepSeek** |
| 其他支持的平台 | 对应提供商 |

如果没有 API Key，需要到对应平台的 API 开放平台，在密钥管理页面创建。普通聊天账号或会员订阅，不一定包含 API 使用权限或额度。API Key 是程序使用的访问密钥，不是账号密码。

选择签发密钥的提供商，点击 **Continue**，填写：

| 字段 | 如何填写 |
| --- | --- |
| **Provider URL** | 使用官方默认地址时，按页面提示留空；使用网关或私有部署时，填写对应服务的 API 地址 |
| **API key** | 粘贴所选提供商签发的密钥 |
| **Language-model API protocol** | 如果出现，先保留 **Auto** |
| **Available service types** | 确认支持 **Language models** |
| **Advanced connection settings** | 先保留默认值，除非提供商明确要求修改 |

`https://api.example.com/v1` 是格式示例，不能照填。API 地址不是官网首页，应以平台接入说明为准。不要在截图、群聊或问题反馈中公开密钥。

向下滚动，在 **Provider connection** 区域点击 **Test provider**。如果显示 **Model list retrieved**，表示已经取得模型列表，尚未证明具体模型可以回答问题。点击页面底部的 **Language models →**，继续添加、选择并测试模型。

如果密钥被拒绝，检查提供商、密钥和账号权限；如果超时，检查地址和网络。连接成功但没有列表时，按照提供商说明填写准确的模型 ID。

### 方式 B：使用已有账号登录

| 你已有的账号 | 选择的选项 |
| --- | --- |
| 有相应 Codex 使用权限的 ChatGPT 账号 | **OpenAI Codex** |
| CodeBuddy 账号 | **CodeBuddy/WorkBuddy** |
| 有相应 Copilot 使用权限的 GitHub 账号 | **GitHub Copilot** |

下面以 ChatGPT 账号登录为例。其他账号的登录要求见[提供方配置](/zh-cn/get-started/providers/)。

1. 在 **Add provider** 中选择 **OpenAI Codex**，点击 **Continue**。
2. 点击 **Sign in with Codex**。
3. 在浏览器中选择 ChatGPT 账号，完成登录和授权。
4. 看到 **Authentication received. You can return to DeepTutor.** 后返回应用，确认页面显示已连接，并出现可用模型。

不需要事先安装或使用过 Codex，也不需要另注册账号；但账号需要相应权限和可用额度。**OpenAI Codex** 用于账号登录，**OpenAI** 用于 API Key 连接。

如果一直等待授权，检查浏览器步骤是否完成；失败或超时后取消当前登录，再重新发起。

## 4. 选择具体模型并保存

同一账号或平台可能提供多个型号。打开设置中的 **Language models**，或返回 **General**，点击 **2. Choose a chat model**。

1. 选择准备使用的具体型号，比如 **GPT-5.6-Sol、GPT-6-Astra**。可选型号以实际列表为准。
2. API Key 连接尚未添加模型时，从已连接提供商添加；手动输入时使用平台给出的准确 **Model ID**。Codex 登录则选择账号提供的型号。
3. 点击 **Test model**，确认这个型号可用。连接成功不代表账号有所有型号的使用权限。
4. 如果出现 **Reasoning effort（推理强度）**，首次体验可选 **low（轻度）**，也可以保留默认值。
5. 点击 **Set as default**，再点击 **Apply changes**。

所选模型应显示 **Default model**，应用后页面显示 **Applied**。**Save draft** 只保存草稿，暂不启用；**Apply changes** 才让配置生效。

## 5. 开始第一次学习

返回 **Home → Chat**，检查输入框附近的模型名称。已有对话可能保留之前的选择，需要时点击模型选择按钮切换。

发送：

> 我想练习英语写作，请用中文讲解。给我一个日常话题，让我用英文写四到六句话。等我回答后，指出最影响理解的两个问题，给我提示，让我自己修改。

收到题目后，自己作答并发送。根据反馈修改，再问：

> 这是我修改后的答案。刚才那两个问题解决了吗？

当 DeepTutor 能针对你的答案正常回复，就完成了第一次学习对话：**收到任务 → 自己作答 → 获得反馈 → 修改答案**。

如果仍提示未配置模型，检查账号连接、默认模型、**Apply changes** 和当前对话的模型选择，再点击 **Retry**。请求失败时，检查网络、授权、额度和模型测试结果。更多排查见[故障排查](/zh-cn/self-hosting/troubleshooting/)。

基本聊天不需要先配齐嵌入、语音、图片或视频服务；之后需要时再添加。

## 数据放在哪里

笔记、对话和设置都留在应用自己的工作区目录里。换一个新版本的应用，不会换掉这个目录。

| 系统 | 工作区数据 |
| --- | --- |
| macOS | `~/Library/Application Support/Open DeepTutor/workspace/data` |
| Windows | `%LOCALAPPDATA%\Open DeepTutor\workspace\data` |

## 下一步

- [串起一次完整学习](/zh-cn/learning-workspace/) — 一个主题、一份材料、一个问题。
- [更新日志](/zh-cn/get-started/changelog/) — 替换旧版桌面应用前先看这里。v1.7.4 更换了运行时签名密钥，需要安装这个版本的应用本身，而不是把更新导入旧版本。
