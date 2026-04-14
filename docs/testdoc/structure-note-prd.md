# Structure Note 产品需求文档（PRD）

## Title

Structure Note: 基于 PageIndex 的课件/教材结构化讲义工作区

## Summary

新增一个独立的 `Structure Note` 工作区。用户上传 `PDF` 或 `PPT/PPTX` 后，系统先统一归一化为 PDF，再基于新增的 `PageIndex` 构建页级结构树，按章节与页范围分段生成详细讲义，并通过图片占位、定位、切图和回填补全图文内容，最终输出一份带引用来源的可读 PDF。用户可在生成前选择三档讲解难度：简单、中等（默认）、复杂。

## Existing Requirements And Current State

DeepTutor 当前已具备相邻能力，但缺少本功能所需的页级结构层：

- 知识库主干已统一到 `llamaindex`，`lightrag` 只是兼容别名
- 当前文档导入以整文抽取和向量检索为主，没有稳定的页级索引或章节树
- `Guided Learning` 已有独立工作区、session、分页状态和后台生成机制，可作为工作区组织方式参考
- `Notebook` 适合保存文本记录，不适合作为 PDF 最终产物主模型
- 上传校验允许 `ppt/pptx`，但 RAG 文件路由当前并不真正支持它们进入主流程

## Problem Statement

DeepTutor 目前没有一个面向课件和教材的“逐页、详细、可回溯”的结构化讲义产物。

这带来两个明显缺口：

1. 学生无法获得接近逐字稿的图文讲义，用于跟课、补漏和课后复习
2. 教师无法将现有 PPT 快速转换为可直接讲授的 Script，仍需自行整理讲稿

现有知识库能力偏向检索，不足以支撑页级结构、章节树、图片回填和最终 PDF 产出。

## Repo Context

- 该功能应是独立工作区，而不是 `Knowledge Hub` 的附属按钮，也不是 `Guided Learning` 的变种
- 该功能不应建立在 LightRAG 上，而应新增 `PageIndex` 结构层
- 当前 repo 没有现成 `PageIndex` 实现，需要新增核心服务
- 该功能会跨后端 router、任务流、路径管理、前端工作区和 PDF 导出，更适合进入 core，并以实验性工作区首发

## Target Users

- 学生：跟课、补漏、课后复习
- 教师：PPT 转 Script，减轻备课负担
- 研发与测试：验证引用、图片回填和恢复流程

## Goals

- 提供独立的 `Structure Note` 工作区
- 支持 `PDF + PPT/PPTX` 上传
- 将 PPT/PPTX 先归一化为 PDF
- 基于 `PageIndex` 生成页级结构树，而非整文向量块
- 采用章节树加分段生成策略，降低 lost-in-the-middle 风险
- 支持简单 / 中等 / 复杂三档讲解难度，其中中等为默认
- 输出最终可读 PDF，并附带引用来源
- 在后端保留中间状态、图片回填和续跑能力，用于测试和恢复

## Non-Goals

- 不替换现有 `Knowledge Hub` 主流程
- 不把最终产物首发建模为 Notebook 主记录类型
- 不在首发覆盖 DOCX、图片 OCR、音频转录等更多素材
- 不向前端暴露占位符、象限定位、切图调试细节
- 不要求 CLI / SDK 首发同步支持

## Proposed Solution

新增 `Structure Note` 工作区，采用独立 router、manager、artifact 存储与前端页面。

### 主流程

1. 用户上传 `PDF` 或 `PPT/PPTX`
2. 若为 PPT/PPTX，先通过转换适配器归一化为 PDF
3. 对 PDF 执行 `PageIndex`，输出逐页文本、页码、标题候选、图像候选区域
4. 构建多级章节树，优先覆盖二级到五级结构
5. 以章节树为主线，按约 10 页窗口分段生成讲义；`复杂讲解` 可自动缩小为 5-8 页窗口
6. 首轮文本生成时插入图片占位符，并记录对应页码范围
7. 图像流水线识别占位符，执行“页定位 -> 象限定位 -> 切图 -> 回填”
8. 将最终内容渲染为 PDF，并生成 `citation_manifest.json`
9. 前端展示最终 PDF、下载入口和引用来源列表

### Difficulty Model

#### simple

- 定位：科普型、入门型
- 目标：讲清关键词、定义、核心知识和结论
- 风格：少推理、少展开、少旁支
- 篇幅：最短

#### medium

- 定位：默认档，接近正常课堂讲解密度
- 目标：概念、重点、基础逻辑链讲清楚
- 风格：细致但不过度展开
- 篇幅：中等

#### detailed

- 定位：最完整档
- 目标：尽量展开所有内容，包括推理、过程、细节和隐含连接
- 风格：最详细
- 篇幅：最长
- 特殊策略：自动缩小页窗口，以换取生成稳定性

## Scope In

- 独立工作区
- PDF 与 PPT/PPTX 上传
- PPT/PPTX -> PDF 归一化
- `PageIndex` 服务层
- 章节树生成
- 按页范围分段生成
- 三档难度控制
- 图片占位、定位、切图、回填
- 最终 PDF 导出
- 引用来源展示
- 后端中间状态持久化与续跑

## Scope Out

- 与知识库检索结果的双向联动
- Notebook 一键保存 PDF
- 用户手动编辑章节树
- 多文档自动合并成一本总讲义
- CLI / SDK 首发接口
- 高级版式编辑器

## UX Or Interaction Notes

- 工作区形态采用“上传 -> 配置 -> 处理中 -> 查看结果”
- 上传页提供：
  - 文件选择
  - 难度选择器：简单 / 中等（默认） / 复杂
- 结果页仅展示：
  - 最终 PDF 预览或下载
  - 本次难度档位
  - 引用来源列表
  - 失败后的重试入口
- 不向用户展示内部中间态和 agent 细节

## Technical Considerations

- `PageIndex` 是新增结构服务，不是新的 RAG provider
- 用户可见主产物是 PDF；后端内部仍保留中间 JSON / Markdown / render state
- 内部 artifact 至少包含：
  - `source_file`
  - `normalized_pdf_path`
  - `difficulty_level`
  - `page_index`
  - `section_tree`
  - `generation_chunks`
  - `image_fill_state`
  - `final_pdf_path`
  - `citation_manifest`
- 引用来源至少应包含：
  - 章节路径
  - 页码范围
  - 原始 PDF 页
  - 图像来源页
- `detailed` 模式应允许更长耗时和更小页窗口，以换取稳定性

## Impacted Areas Of The Repo

- 新增 backend router：`deeptutor/api/routers/structure_note.py`
- 新增服务目录：`deeptutor/services/structure_note/`
- 扩展路径管理：`deeptutor/services/path_service.py`
- 复用任务流与日志广播模式：`deeptutor/api/routers/knowledge.py`
- 新增前端页面：`web/app/(workspace)/structure-note/page.tsx`
- 更新工作区导航与文档

## Acceptance Criteria

- 用户可在独立工作区上传 PDF 并生成最终 PDF 讲义
- 用户可上传 PPT/PPTX，系统会先转换为 PDF 再进入同一流程
- 系统基于页级结构和章节树分段生成，而不是整文一次性生成
- 用户可选择三档难度；未选择时默认为中等
- 三档难度的结果在覆盖密度和篇幅上有明显差异
- 最终结果可回溯到页码范围，并在前端展示引用来源
- 图片可通过占位符 -> 定位 -> 切图 -> 回填进入最终结果
- 生成中断后可在后端基于中间状态续跑
- 不影响现有 `Knowledge Hub`、`Notebook`、`Guided Learning`

## Success Metrics

- 任务成功率
- 平均生成时长
- 页码引用正确率
- 图片回填成功率
- 三档难度的用户使用分布
- 学生复习场景下的二次打开率
- 教师上传后导出率

## Rollout And Compatibility

- 以独立工作区、实验性功能首发
- 完全 opt-in，不替换现有知识库主行为
- 中间状态保留策略做成可配置项，测试环境默认开启，生产环境可裁剪
- 若 PPT 转 PDF 或 `PageIndex` 失败，应给出明确错误并允许重试

## Risks And Mitigations

### PageIndex 质量不稳定

- 风险：树生成失败或页级抽取噪声过大
- 缓解：树失败时回退为按页段生成，保证主流程可用

### PPT 转 PDF 兼容性不足

- 风险：不同模板、字体或复杂动画导致转换异常
- 缓解：转换器做成可替换 adapter；首发默认使用 LibreOffice

### simple 过度压缩

- 风险：为追求短篇幅丢失关键上下文
- 缓解：强制保留关键词、定义、结论和最小解释链

### detailed 成本和耗时过高

- 风险：长文档生成时间和成本显著上升
- 缓解：缩小页窗口并启用缓存和续跑

### 图片定位不准

- 风险：四象限粗定位与真实图像区域偏差较大
- 缓解：定位失败时允许整页截图回退

## Maintainer Fit

该功能适合进入 core，但建议以实验性工作区首发。它直接服务于 DeepTutor 的“材料 -> 学习产物”主线，需要复用上传、任务流、前端工作区和路径管理；若做成外置 plugin，会让产品入口、状态管理和文件处理都变得割裂。

## Alternatives Considered

- 挂在 `Knowledge Hub` 下：不选，因为它不是普通 KB 初始化副产物
- 复用 `Guided Learning`：不选，因为其主产物是交互页面，不是最终 PDF 讲义
- 只保存最终 PDF，不保留中间状态：不选，因为测试、恢复和图片回填都会变差
- 基于 LightRAG 扩展：不选，因为当前主干不走这条路径，且需求核心是页级结构

## Docs And Test Impact

- README 增加 `Structure Note` 工作区说明
- docs 增加支持格式、难度档位、生成流程、引用来源说明
- 后端测试覆盖：
  - PPT/PPTX 归一化
  - `PageIndex`
  - 章节树生成
  - 难度分层
  - 引用页码
  - 图片回填
  - 续跑恢复
- 前端测试覆盖：
  - 上传与难度选择
  - 处理中状态
  - 最终 PDF 展示
  - 引用来源展示

## Open Questions

- 最终 PDF 是否需要内嵌引用附录，还是只在前端展示完整 citation
- 生产环境中间状态保留多久
- 是否允许下载 `PDF + citation manifest` 打包结果

## Assumptions

- 首发是 web-first
- 最终用户产物是 PDF
- 后端保留中间状态仅用于测试、恢复和内部验证
- `medium` 为默认档位
- `detailed` 可接受更长生成时延和更高成本

## Decision Log

- 入口：独立工作区
- 素材：PDF + PPT/PPTX
- 归一化：PPT/PPTX 先转 PDF
- 结构底座：新增 `PageIndex`
- 用户可见产物：最终 PDF
- 前端：只展示结果与引用
- 后端：保留中间状态、图片回填和续跑
- 难度：简单 / 中等（默认） / 复杂
