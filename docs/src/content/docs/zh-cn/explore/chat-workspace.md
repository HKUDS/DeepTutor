---
title: 对话
description: "DeepTutor 的默认智能体循环——能力、会话上下文、可复用引用、工具、活动面板，以及驱动这一切的模型。"
quadrant: how-to
---

主页是 DeepTutor 的核心。它不是一个普通的输入框，而是**默认的智能体循环**（agent loop）：它能调用工具、阅读你的资料、检索知识库、记笔记、生成图片、咨询其他智能体、在需要时反问你，并切换到更深的能力——这一切都在同一个对话里完成。

## 它在哪里

先选择[工作区](/zh-cn/explore/workspaces/)，再打开**主页 → 聊天**（`/chat`）。主页还包含[任务看板](/zh-cn/explore/task-board/)、[学习笔记本](/zh-cn/explore/co-writer/)和[日历](/zh-cn/explore/calendar/)。聊天、任务与笔记页面随工作区变化；日历事件属于账号级，并叠加工作区学习信息。

![主页与对话输入框](/screenshots/dev/overview.png)

界面分为三个区域：

| 区域 | 作用 |
| --- | --- |
| **左侧栏** | 顶部为工作区菜单，下方是**主页、学习、资料**。**伙伴**与**个性化**属于账号级。对话会恢复所属学习上下文；工作区菜单可进入设置与工作区管理。经典布局的导航排列有所不同。 |
| **输入框** | 消息框。**左下角**决定这一轮是哪种「能力」，并用 `+` 加入引用；**右下角**提供连接智能体、知识库、人设与模型选择器。麦克风只转写当前消息。 |
| **活动面板**（右上角切换） | 当前会话用到的工具调用、引用、生成的文件、附件与预览，并能快速打开一个 URL 或本地文件。 |

启用身份认证后，已登录用户还会在侧栏看到 **My profile**。这里显示不可编辑的用户名、角色与加入日期；你可以上传头像，或选择图标和颜色，也可以退出登录。

对话上方的右上角图标分别用于：**把有用内容存到收藏夹**、**把整段会话导出为 Markdown**、**展开/收起活动面板**。

## 完成第一段有用的对话

1. 选中项目工作区，新建聊天。
2. 用资料控件加入 PDF 或某条保存记录；需要跨资料库检索时挂载知识库。
3. 说明结果与限制，例如：“基于这份讲义解释采样定理，再给我两道题。先让我尝试，不要直接展示答案。”
4. 在活动面板查看工具进度，打开引用来源或生成文件核对依据。
5. 将有用结果存到[收藏夹](/zh-cn/explore/favorites/)，或到[学习笔记本](/zh-cn/explore/co-writer/)写自己的理解。之后可从资料 → 聊天历史重开会话。

选择连接的智能体默认会作为会话偏好保留；导入旧智能体记录则是在引用材料。同样，附件默认提供当前轮次资料，工作区指令与会话偏好影响后续轮次。回答似乎引用了错误来源或人设时，发送前检查可见的选择标签。

## 起始建议

空白输入框下方提供解释、解题、练习、规划和研究等起始提示。独立的一条个性化建议取自记忆与近期活动；**换一批**会替换它。选择提示或建议后，内容先进入输入框，供你检查再发送。通过**自定义页面 → 起始提示**可修改常用标题与请求。

**Settings → Conversation** 决定喂给它们多少历史：把活动条数调高，建议的取材面更广；调低，则更贴近你刚才在做的事。


## 智能体循环（它是怎么「想」的）

DeepTutor 聊天运行的是单一智能体循环，因此一条消息在你看到答复前，内部可能要走好几轮：

1. 模型读取你的消息与已挂载的上下文，然后直接作答，或规划一次工具调用。
2. 若需要工具，DeepTutor 派发工具并把观测结果追加进来（可在活动面板里实时看到）。
3. 模型带着更充分的证据继续——阅读资料、检索知识库、运行代码、抓取网页。
4. 一条不再调用工具的最终消息，结束这一轮。

`ask_user` 很特殊：与其瞎猜，智能体可以**暂停这一轮**，向你提出结构化的澄清问题，待你回答后再继续。

## 选择一种能力

输入框左下角的选择器（现代布局默认显示 **Auto**，经典布局显示 **Chat**）决定由哪种 capability 处理这一轮。各能力共享编排与会话上下文；有些复用 Chat 循环，有些运行专用 pipeline。

能力菜单可选择 **Ask Questions**、**Quiz**、**Visualize** 与 **Video Lesson** 等专用模式；**Research** 和 **Solve** 收在 *More Capabilities* 弹出层里。**Mastery Path** 与 **Immersive Reading** 位于**学习**下，与书籍和练习并列，不属于 Home 模式。这个分组只关乎呈现，并不代表各模式如何运行。

| 能力 | 适用于 |
| --- | --- |
| **Chat** | 可用任意工具的灵活对话——开放式问答、轻量工具使用，日常默认。 |
| **Ask Questions** | 先用一张结合上下文的提问卡补齐信息，再依据你的回答完成原请求。 |
| **Quiz** | 自动校验的出题：练习题、仿真题、从你的资料出题。 |
| **Visualize** | 图表、示意图、可交互 HTML、SVG、Mermaid 与 Manim，由可扩展的 visualizer 目录选择。 |
| **Video Lesson** | 生成在浏览器播放的课程，含字幕与可选旁白（使用设置的 TTS 提供方或 Edge）；后端需要 Node.js 22+ 和 npm。 |
| **Immersive Reading**（学习活动） | 在文档、音频和视频旁依据来源学习；媒体转录使用时间戳引用。 |
| **Research**（在 *More Capabilities* 下） | 全面的多智能体研究：子话题分解、RAG / 网络 / arXiv 检索、带引用的报告。 |
| **Solve**（在 *More Capabilities* 下） | 多步推理与解题，带验证和完整解答过程。 |


视频学习现与文档、音频一起进入**沉浸式阅读**合集。YouTube 使用原生播放器；设置负责字幕来源与可选的 Invidious 浏览。助手按转录时间戳引用，无法看到视频画面；没有转录仍可播放。重新打开旧 Watching 会话时，会把保留的素材和笔记迁到 Reading；素材缺失时，对话仍作为 Chat 保留。


Visualize 的渲染模式现在来自目录。SVG、Mermaid、Mermaid 思维导图、Chart.js、可交互 HTML、Manim 动画与分镜是核心类型；GeoGebra 是可选的内置安装项。你也能导入包含 `visualizer.json` 与浏览器资产的 ZIP；导入的 renderer 在沙箱 iframe 中运行，不含后端 Python，并可按用户启用、停用或移除。


### Little Tutor——追问一段选区

选中对话中的文字并打开 **Little Tutor**，即可启动一条独立、以来源内容为依据的侧栏线程。它嵌套在来源对话下，并使用自己的聚焦上下文而不加载全局记忆或通用工具，因此精读追问不会打断主线程。

## 黏性上下文 vs. 一次性引用

DeepTutor 把上下文分成两类，输入框也把它们放在两个不同的位置——这是这一页最关键的一个概念。

**黏性会话上下文**会跨轮持续生效，直到你手动更改：能力、工作区或课程绑定、工具、**知识库**、**人设**、**模型**以及 Reading / Mastery 状态。右侧提供相关选择器；通过 Agent 胶囊或 `@` 选中的智能体默认会留在本会话里，而麦克风只填入当前草稿。

**引用**位于左侧的 **`+` 按钮**后面，默认只用于*当前这一轮*；可通过复用控件让支持的引用在后续每一轮继续使用。


| `+` 引用 | 拉进什么 |
| --- | --- |
| **Attach files** | 一份 PDF、图片、Office 文档、Markdown 或数据文件，交给智能体阅读。 |
| **Chat History** | 把过去的某段会话作为背景资料。 |
| **My Agents** | 一份导入的 Claude Code / Codex / ChatGPT 对话记录供探查——见[我的智能体](/zh-cn/explore/subagents/)。 |
| **Books / Reading / Notebooks / Question Bank** | 一本已编译的书、一个阅读片段、一个已保存的笔记本，或[资料](/zh-cn/explore/space/)里的练习题。题目可按材料或分类筛选，**Select all** 会保留先前选择。 |
| **Memory** | 某一份具体的记忆文档——当你希望智能体依据一条你指得出来的事实工作，而不是依据召回碰巧捞上来的东西。 |

在主 Chat 输入框里键入 **`@`**，会筛选与 Agent 胶囊相同的连接智能体列表，并默认把选中项保留在本会话中。没有实时智能体选择器的跟进界面，则继续用 `@` 打开 Space 引用菜单。

### 知识库——把答案锚定到你的资料

**数据库图标**打开知识库选择器。未手动选择的对话继承工作区已就绪的指定知识库或默认库；显式选择（包括不选）会持续保留，直到修改。问题需要依据时，智能体从这些库检索。

具体怎么检索，取决于这个库绑定的引擎——回答让你意外的时候，这个区别很值得知道。大多数库——LlamaIndex、GraphRAG、LightRAG、链接的现成索引、远端 LightRAG Server、腾讯 IMA 库——由 `rag` 工具服务。**PageIndex OSS** 与 **PageIndex Cloud** 不是：它们的检索本身是 agentic 的，阅读循环会遍历本地或托管文档树，因此这些库被有意排除在 `rag` 列表之外。**Obsidian** 库压根没有索引，会被路由给 Obsidian 能力，由它直接浏览实时文件；**MarginNote 4** 库是同一种形态，由它自己的一组工具来走。


### 人设——设定语气与立场

**人物图标**用于选择人设。`Default` 是朴素的助手；内置的 **peer**（同伴）、**research-assistant**（研究助理）、**teacher**（老师）等会改变语气与教学风格。人设在**个性化 → 人设**中管理，并可被伙伴复用。


### 模型——逐轮切换

**模型胶囊**决定这一轮用哪个模型。你在设置里配好的每个模型都会列在这里，并标注提供商与上下文窗口，默认模型有标记。处理大文档时切到长上下文模型，闲聊时切到更便宜更快的模型——会话中途即可切换，不丢上下文。


## 活动面板

右上角的面板切换按钮会打开 **Activity**（活动）——当前会话用过的工具、引用与文件的实时记录，生成的文件排在你上传的之上，外加一个 **Open** 框，可把 URL 或本地文件拉进应用内的查看器。

![对话与活动控制](/screenshots/dev/chat.png)

一轮进行时，每次工具调用都会折叠成一个紧凑的标题（例如 `Done · 21s`），展开即可查看输入与输出——对话保持清爽，完整轨迹依然可审计。

## 知道窗口有多满

输入框上有一个胶囊，报告这一轮实际占用了模型上下文窗口的多少、以及是什么在占——提示词块、工具 schema、消息列表。它是从已经拼装好的提示词上量出来的，不是事后重新推算的，所以这个读数不可能和真正发出去的内容对不上。点开看明细，再决定要不要换一个长上下文模型，或者干脆开一段新会话。

长对话还会在正文左侧空白处长出一条刻度轨，你每问一次就多一格，用来在历史里跳来跳去而不必滚动。

## 工具——也包括生成

工具分三类，区别在于由谁来决定。

**由你决定**的是 **Settings → Tools** 里那些体验增强工具：`brainstorm`、`web_search`、`paper_search`、`zotero_search`、`reason` 与 `geogebra_analysis`——配好相应的生成模型后，还会有 `imagegen` 与 `videogen`。

**由上下文决定**的是其余那些：它们在有用时自动挂载，从输入框的角度看是常开的——`rag`、`kb_files`、`knowledge_frontier`、`read_source`、`read_memory`、`write_memory`、`read_skill`、`list_favorites`、`save_favorite`、`question_bank`、`web_fetch`、`github`、`preprint`、`research_audit`、`research_lit`、`learning_status`、`learning_update`、`ask_user`、`load_tools`、`cron`、`mastery_topics`、`mastery_sessions`、`mastery_open_session`、`mastery_new_session`，以及唯一的代码路径 `exec`（python、c、cpp 或 shell）。能力还会在此之上追加自己的：八个阅读工具、精通之路的教学工具、`consult_subagent` 等等。还有一类谁也管不着：工作区基础工具包含文件工具及 `write_note`、`search_notes`；`workspace_export` 要经你批准才能把文件移出 `outputs/`。（伙伴是例外：可以逐个禁用受上下文门控的工具——见[伙伴](/zh-cn/explore/partners/)。）

### 把事情排到以后做

`cron` 让一个回合可以把活儿排期而不是当场干完：**在**某个时刻、**每隔** N 秒，或者按一条带时区的 **cron 表达式**。任务到点时，它的消息会作为一条新指令**在同一段对话里**执行，回复也落在这里——所以「工作日每天早上九点就这一章考我」是一句话，而不是一个设置页面。同一个工具还能列出本对话的任务、取消其中一个。对伙伴而言，到点的任务会顺着它所连接的 IM 渠道发回去。

在设置里配好一个**图像生成**（或视频生成）模型，它也会变成聊天工具——用自然语言提出需求，智能体便会调用它，并把结果内联预览、附上可下载的文件。

## 内容工作区

**内容工作区**是绑定到对话的文件夹。未绑定的会话使用通用工作区，也可为不同项目创建自建工作区。系统工作区保存共享技能和脱敏配置快照；私有运行设置、API key、数据库与记忆仍不属于对话的文件访问范围。

在 **Settings → Workspace** 管理根目录、工作区和 **Workspace instructions**。指令从下一轮起对支持的能力生效，但不包括 Deep Research、Quiz 和 Manim；能力规则与权限仍然适用。内置及托管的自建目录默认位于 `<runtime-home>/data/user/workspaces`。命令行仍可管理原有内容文件夹绑定：

```bash
deeptutor workspace show
deeptutor workspace set /absolute/path/to/my-folder
deeptutor workspace reset
```

读是自由的，写不是。一个回合产生的一切——下载、生成的文件、代码输出、渲染出的素材——都落在按回合隔离的 `outputs/<capability>/<session>/<turn>/` 目录下。文件夹的其余部分对执行是只读的；要把生成的文件从 `outputs/` 复制到你自己的材料里，必须经过一次点名了具体来源与去向的 **Allow once** 确认。

模型永远看不到绝对路径，只看得到 `outputs/report.docx` 这样的相对路径。它调用 `workspace_present` 时，界面会渲染一份带鉴权、可打开的快照；同一个相对路径也可以直接写进普通的 Markdown 链接或图片。之后再改源文件，不会改变已经呈现出去的快照。

在 Docker 与服务器部署下，托管工作区的存储范围由部署文件夹约束——见 [Docker](/zh-cn/get-started/docker/)。

## 配置聊天能用到的东西

输入框工具栏里的一切，最终都对应到 **Settings**（设置）里的配置。

**Settings → Models & services** 是模型所在之处：LLM、Task Models、Embedding、Search、文本转语音（TTS）、语音转文本（STT）、图像生成与视频生成。**Task Models** 负责标题、建议和阅读辅助，并可按任务单独选择模型；TTS 驱动朗读，STT 驱动麦克风，图像/视频模型则成为聊天工具。

![设置中的提供方连接](/screenshots/dev/providers.png)

独立的 **Settings** 页面提供五项控制：**Video Learning**（字幕来源与可选的 Invidious 浏览设置）、**Tools**、**Capabilities**（各能力的 LLM 参数与运行时旋钮）、**Starting points**，以及 **Attachments**（上传上限与文本提取预算）。MCP 服务不再在这里配置——它和 CLI App 一起归到账号级个性化，详见 [DeepTutor 生态](/zh-cn/ecosystem/)。


完整的控制面板见[设置](/zh-cn/explore/settings/)。

## 在手机上

窄于平板宽度时，工作区会收成单栏加一个抽屉式侧边栏，于是同一段对话在手机上是能用的，而不是把一个三栏桌面布局渲染到视口之外。

## 实用示例

```text
挂载一个知识库 + 提问：「讲讲第 4 章，并就我薄弱的点考我。」
```

```text
附加一份 PDF + 提问：「抽取其中的假设，并把最终摘要存进我的笔记本。」
```

```bash
deeptutor run chat "讲讲傅里叶变换" --kb signals
deeptutor chat --capability deep_research --kb papers
```

## 另见

- [沉浸式阅读](/zh-cn/explore/reading/)——同一个循环，旁边打开文档或媒体
- [DeepTutor 生态](/zh-cn/ecosystem/)——智能体可调用的 Skill、MCP 服务与 CLI App
- [伙伴](/zh-cn/explore/partners/)——同一个循环，运行在 IM 伙伴里
- [我的智能体](/zh-cn/explore/subagents/)——在一轮聊天里咨询 Claude Code、Codex 或某个伙伴
- [知识中心](/zh-cn/explore/knowledge/)——构建你在这里挂载的 RAG 库
- [记忆](/zh-cn/explore/memory/)——循环读写的个性化记忆
- [设置](/zh-cn/explore/settings/)——模型、工具、能力与运行时控制
