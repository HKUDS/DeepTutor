---
title: 智能体循环是怎么工作的
description: 一轮对话如何规划、调用工具、观察结果并结束。
quadrant: explanation
---

对话的一轮不是一次补全。模型可以先调用工具、读到观察，再决定是继续还是回答。操作步骤在[对话](/zh-cn/learning-workspace/chat/)。

### Little Tutor——追问一段选区

选中对话中的文字并打开 **Little Tutor**，即可启动一条独立、以来源内容为依据的侧栏线程。它嵌套在来源对话下，并使用自己的聚焦上下文而不加载全局记忆或通用工具，因此精读追问不会打断主线程。


## 智能体循环（它是怎么「想」的）

DeepTutor 聊天运行的是单一智能体循环，因此一条消息在你看到答复前，内部可能要走好几轮：

1. 模型读取你的消息与已挂载的上下文，然后直接作答，或规划一次工具调用。
2. 若需要工具，DeepTutor 派发工具并把观测结果追加进来（可在活动面板里实时看到）。
3. 模型带着更充分的证据继续——阅读资料、检索知识库、运行代码、抓取网页。
4. 一条不再调用工具的最终消息，结束这一轮。

`ask_user` 很特殊：与其瞎猜，智能体可以**暂停这一轮**，向你提出结构化的澄清问题，待你回答后再继续。

## 知道窗口有多满

输入框上有一个胶囊，报告这一轮实际占用了模型上下文窗口的多少、以及是什么在占——提示词块、工具 schema、消息列表。它是从已经拼装好的提示词上量出来的，不是事后重新推算的，所以这个读数不可能和真正发出去的内容对不上。点开看明细，再决定要不要换一个长上下文模型，或者干脆开一段新会话。

长对话还会在正文左侧空白处长出一条刻度轨，你每问一次就多一格，用来在历史里跳来跳去而不必滚动。

## 工具——也包括生成

工具分三类，区别在于由谁来决定。

**由你决定**的是 **Settings → Tools** 里那些体验增强工具：`brainstorm`、`web_search`、`paper_search`、`zotero_search`、`reason` 与 `geogebra_analysis`——配好相应的生成模型后，还会有 `imagegen` 与 `videogen`。

**由上下文决定**的是其余那些：它们在有用时自动挂载，从输入框的角度看是常开的——`rag`、`kb_files`、`knowledge_frontier`、`read_source`、`read_memory`、`write_memory`、`read_skill`、`list_favorites`、`save_favorite`、`question_bank`、`web_fetch`、`github`、`preprint`、`research_audit`、`research_lit`、`learning_status`、`learning_update`、`ask_user`、`load_tools`、`cron`、`mastery_topics`、`mastery_sessions`、`mastery_open_session`、`mastery_new_session`，以及唯一的代码路径 `exec`（python、c、cpp 或 shell）。能力还会在此之上追加自己的：八个阅读工具、精通之路的教学工具、`consult_subagent` 等等。还有一类谁也管不着：工作区基础工具包含文件工具及 `write_note`、`search_notes`；`workspace_export` 要经你批准才能把文件移出 `outputs/`。（伙伴是例外：可以逐个禁用受上下文门控的工具——见[伙伴](/zh-cn/channels/)。）

### 把事情排到以后做

`cron` 让一个回合可以把活儿排期而不是当场干完：**在**某个时刻、**每隔** N 秒，或者按一条带时区的 **cron 表达式**。任务到点时，它的消息会作为一条新指令**在同一段对话里**执行，回复也落在这里——所以「工作日每天早上九点就这一章考我」是一句话，而不是一个设置页面。同一个工具还能列出本对话的任务、取消其中一个。对伙伴而言，到点的任务会顺着它所连接的 IM 渠道发回去。

在设置里配好一个**图像生成**（或视频生成）模型，它也会变成聊天工具——用自然语言提出需求，智能体便会调用它，并把结果内联预览、附上可下载的文件。

