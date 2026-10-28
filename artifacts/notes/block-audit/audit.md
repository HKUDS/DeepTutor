# 笔记块预览与实际插入验收

日期：2026-10-17。代码位置：`/Users/frank/HKUDS/DeepTutor`。验收通过 CUA 操作真实浏览器，使用隔离测试服务（3796 / 8016）；没有向用户正在编辑的正文插入测试内容。

## 结果

- 50 / 50 个菜单入口拥有专属预览，桌面逐项检查并保存完整截图；没有通用占位预览、横向溢出或示例裁切。
- 32 / 32 类文本、结构及任务视图通过真实菜单插入、输入、保存、重新打开与布局核查。标题 1–4 为 28 / 23 / 19 / 16 px。
- 390 × 844 下检查全部 50 种预览，未发现示例裁切；2–5 列按顺序堆叠，页面无横向溢出。
- 320 × 568 下菜单保留完整的键盘选中行；空间不足时预览独立滚动，内容不会永久隐藏。
- 新建公式无需再次点击即可直接输入；折叠标题先聚焦标题，分栏先聚焦第一列。
- 浏览器最终控制台没有 error。

## 修复的具体问题

1. 页面链接、媒体、目录、分栏、日期、学习内容等缺少格式预览，回退成统一“文件图标＋一句话”。增加有类型约束的 50 项预览清单和穷尽渲染，页面选择器也显示对应页面标题。
2. 任务表格、看板和列表共用表格预览。改为对应的独立布局。
3. 行内公式被 Markdown 归一化成独立公式，破坏字号和基线。预览与正文共用显式区分行内 / 独立模式的 KaTeX 渲染器，保留无效公式回显并禁用可信 HTML 命令。
4. 新公式刚插入就失去焦点并收起输入框。避免编辑器抢焦点，并在菜单事务结束后把焦点交给表单；空公式保持可编辑。
5. 折叠标题插入后聚焦到空正文，留下空标题。修正插入光标位置。
6. 窄屏完全不显示预览，固定高度还会裁切闪卡、时间线等内容。提供菜单内部预览、自适应高度与短屏滚动；列表尺寸变化时重新显露选中行。
7. 鼠标悬停预览与选中项语义不一致，筛选后可能沿用旧索引。统一选中状态，按结果集判定悬停有效性，Enter 执行当前悬停项。
8. 正文中的中文顿号会误开菜单。中文快捷入口只在空块生效；代码块、表格单元格不再误开块插入菜单。
9. 缺少下划线按钮、格式按钮没有选中反馈、颜色选择不能反映当前格式。补上对应交互和状态。
10. 编辑器重新挂载可能读取旧初始内容。页面状态同步最新块快照，补充回归测试，实测热更新与重新加载后保留内容。
11. 页面链接实际样式与预览不一致、代码预览背景不一致。统一链接图标与代码背景；书签输入归一化首尾空白。

## 实际交互记录

- 正文：粗体、斜体、下划线、行内代码；选中格式按钮返回正确的 aria-pressed。
- 待办：勾选后显示完成样式。标注：切换 tip / info 样式。
- 表格：连续 Tab 编辑六个单元格，文本落入正确单元格。
- 普通折叠列表：展开、添加子块、收起，子内容高度为 0；折叠标题同样验证收起。
- 目录：包含四级标题与三级折叠标题，点击跳转到对应标题并更新锚点。
- 公式：新建后直接输入积分，Enter 渲染；行内公式改成 E=mc² 并保存。
- 日期：原生键盘将日期改为 2026-10-20，确认保存后的块数据与显示一致。
- 页面链接：选择目标页面，插入后 href 指向目标笔记；预览显示页面名称。
- 网页书签 / 嵌入 / HTML：输入与保存成功；HTML 在独立沙盒中实际渲染标题、段落和粗体。
- 任务视图：在表格创建任务，在列表勾选完成，表格状态与看板 Done 列同步。
- 分栏：2、3、4、5 列均填写内容；桌面并排，手机依次堆叠。

## 预览逐项清单

每张链接都是该菜单项选中时的完整浏览器截图。

| 序号 | 菜单入口 | 预览类型 | 结果 |
|---|---|---|---|
| 1 | Ask Dito | `ai` | [通过](preview-00-ai.jpg) |
| 2 | Reference a source | `source` | [通过](preview-01-source.jpg) |
| 3 | Insert favorite | `favorite` | [通过](preview-02-favorite.jpg) |
| 4 | Paragraph | `paragraph` | [通过](preview-03-paragraph.jpg) |
| 5 | Heading 1# | `heading` | [通过](preview-04-heading.jpg) |
| 6 | Heading 2## | `heading_2` | [通过](preview-05-heading_2.jpg) |
| 7 | Heading 3### | `heading_3` | [通过](preview-06-heading_3.jpg) |
| 8 | Heading 4#### | `heading_4` | [通过](preview-07-heading_4.jpg) |
| 9 | Bullet List- | `bullet_list` | [通过](preview-08-bullet_list.jpg) |
| 10 | Numbered List1. | `numbered_list` | [通过](preview-09-numbered_list.jpg) |
| 11 | Check List[] | `check_list` | [通过](preview-10-check_list.jpg) |
| 12 | Toggle List> | `toggle_list` | [通过](preview-11-toggle_list.jpg) |
| 13 | Quote" | `quote` | [通过](preview-12-quote.jpg) |
| 14 | Table | `table` | [通过](preview-13-table.jpg) |
| 15 | Divider--- | `divider` | [通过](preview-14-divider.jpg) |
| 16 | Code Block``` | `code_block` | [通过](preview-15-code_block.jpg) |
| 17 | Callout | `callout` | [通过](preview-16-callout.jpg) |
| 18 | Page link | `pageLink` | [通过](preview-17-pageLink.jpg) |
| 19 | Image | `image` | [通过](preview-18-image.jpg) |
| 20 | Video | `video` | [通过](preview-19-video.jpg) |
| 21 | Audio | `audio` | [通过](preview-20-audio.jpg) |
| 22 | File | `file` | [通过](preview-21-file.jpg) |
| 23 | Web bookmark | `bookmark` | [通过](preview-22-bookmark.jpg) |
| 24 | Embed | `embed` | [通过](preview-23-embed.jpg) |
| 25 | HTML | `htmlEmbed` | [通过](preview-24-htmlEmbed.jpg) |
| 26 | Task table | `task_table` | [通过](preview-25-task_table.jpg) |
| 27 | Task board | `task_board` | [通过](preview-26-task_board.jpg) |
| 28 | Task list | `task_list` | [通过](preview-27-task_list.jpg) |
| 29 | Table of contents | `toc` | [通过](preview-28-toc.jpg) |
| 30 | Math formula$$ | `math` | [通过](preview-29-math.jpg) |
| 31 | Toggle heading 1 | `toggle_heading_1` | [通过](preview-30-toggle_heading_1.jpg) |
| 32 | Toggle heading 2 | `toggle_heading_2` | [通过](preview-31-toggle_heading_2.jpg) |
| 33 | Toggle heading 3 | `toggle_heading_3` | [通过](preview-32-toggle_heading_3.jpg) |
| 34 | 2 columns | `columns_2` | [通过](preview-33-columns_2.jpg) |
| 35 | 3 columns | `columns_3` | [通过](preview-34-columns_3.jpg) |
| 36 | 4 columns | `columns_4` | [通过](preview-35-columns_4.jpg) |
| 37 | 5 columns | `columns_5` | [通过](preview-36-columns_5.jpg) |
| 38 | Date | `date` | [通过](preview-37-date.jpg) |
| 39 | Inline formula$…$ | `inlineMath` | [通过](preview-38-inlineMath.jpg) |
| 40 | Diagram | `mermaid` | [通过](preview-39-mermaid.jpg) |
| 41 | Quiz me | `quiz` | [通过](preview-40-quiz.jpg) |
| 42 | Flash Cards | `flashcards` | [通过](preview-41-flashcards.jpg) |
| 43 | Timeline | `timeline` | [通过](preview-42-timeline.jpg) |
| 44 | Research | `research` | [通过](preview-43-research.jpg) |
| 45 | Task | `task` | [通过](preview-44-task.jpg) |
| 46 | Animation | `animation` | [通过](preview-45-animation.jpg) |
| 47 | Concept map | `concept_map` | [通过](preview-46-concept_map.jpg) |
| 48 | Geometry | `geogebra` | [通过](preview-47-geogebra.jpg) |
| 49 | Generate image | `generated_image` | [通过](preview-48-generated_image.jpg) |
| 50 | Podcast | `podcast` | [通过](preview-49-podcast.jpg) |

## 实际插入逐项清单

| 测试项 | 检查结果 |
|---|---|
| paragraph | [显示与保存通过](actual-paragraph.jpg) |
| heading1 | [显示与保存通过](actual-heading1.jpg) |
| heading2 | [显示与保存通过](actual-heading2.jpg) |
| heading3 | [显示与保存通过](actual-heading3.jpg) |
| heading4 | [显示与保存通过](actual-heading4.jpg) |
| bullet | [显示与保存通过](actual-bullet.jpg) |
| numbered | [显示与保存通过](actual-numbered.jpg) |
| check | [显示与保存通过](actual-check.jpg) |
| toggle | [显示与保存通过](actual-toggle.jpg) |
| quote | [显示与保存通过](actual-quote.jpg) |
| table | [显示与保存通过](actual-table.jpg) |
| divider | [显示与保存通过](actual-divider.jpg) |
| code | [显示与保存通过](actual-code.jpg) |
| callout | [显示与保存通过](actual-callout.jpg) |
| pageLink | [显示与保存通过](actual-pageLink.jpg) |
| bookmark | [显示与保存通过](actual-bookmark.jpg) |
| embed | [显示与保存通过](actual-embed.jpg) |
| html | [显示与保存通过](actual-html.jpg) |
| toc | [显示与保存通过](actual-toc.jpg) |
| math | [显示与保存通过](actual-math.jpg) |
| toggle1 | [显示与保存通过](actual-toggle1.jpg) |
| toggle2 | [显示与保存通过](actual-toggle2.jpg) |
| toggle3 | [显示与保存通过](actual-toggle3.jpg) |
| columns2 | [显示与保存通过](actual-columns2.jpg) |
| columns3 | [显示与保存通过](actual-columns3.jpg) |
| columns4 | [显示与保存通过](actual-columns4.jpg) |
| columns5 | [显示与保存通过](actual-columns5.jpg) |
| date | [显示与保存通过](actual-date.jpg) |
| inlineMath | [显示与保存通过](actual-inlineMath.jpg) |
| taskTable | [显示与保存通过](actual-taskTable.jpg) |
| taskBoard | [显示与保存通过](actual-taskBoard.jpg) |
| taskList | [显示与保存通过](actual-taskList.jpg) |

## 验证命令

- `npm run typecheck`：通过。
- `npx vitest run tests/notes-previews.spec.tsx tests/notes-model.spec.ts tests/notes-autosave.spec.tsx`：60 / 60 通过。
- 修改范围 ESLint：0 errors；测试替身已有一条 useEffect 依赖 warning。
- `npm run architecture:check`：通过。
- `npm run i18n:parity`：六种语言键一致。
- `DEEPTUTOR_NEXT_DIST_DIR=.next-notes-preview-audit npm run build`：最终代码生产构建通过。
- `git diff --check`（本轮相关路径）：通过。

## 证据与范围

- 修复前：`01-before-body.jpg`、`02-before-page-link.jpg`。
- 修复后：`final-page-link-preview.jpg`、`previews-contact-1.jpg` 至 `previews-contact-5.jpg`、`actual-*.jpg`。
- 手机：`mobile-*.jpg`，包括 390 px 全菜单逐项检查和 320 px 选中行 / 可滚动预览检查。
- 机器可读记录：`preview-checks.json`、`narrow-checks.json`、`mobile-320-check.json`、`insertion-checks.json`。
- 本轮覆盖显示、输入、选择、折叠、保存和重开。媒体上传与远程 AI 生成没有重新发起；学习类菜单使用非交互示例，不会因悬停而调用模型或修改任务数据。没有宣称这些远程生成流程已经在本轮端到端复测。
- 保留仓库已有的其他工作；没有提交、推送或部署。
