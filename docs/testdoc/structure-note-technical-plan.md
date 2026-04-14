# Structure Note 详细技术计划

## 1. 背景与决策

### 1.1 目标

在 DeepTutor 中新增一个独立的 `Structure Note` 工作区，将用户上传的课件或教材转成可阅读、可回溯的结构化 PDF 讲义。

### 1.2 已锁定决策

- 工作区独立存在，不挂在 `Knowledge Hub` 或 `Guided Learning` 下
- 首发真实支持 `PDF + PPT/PPTX`
- `PPT/PPTX -> PDF` 由服务端通过 `headless LibreOffice` 实现
- 结构底座为新增的 `PageIndex`，不接入现有 `llamaindex` provider
- 最终用户产物是 PDF
- 引用只在前端结果页侧栏展示，不强行内嵌到 PDF 中
- 中间状态保留采用环境可配策略
- 难度固定为 `simple / medium / detailed`，默认 `medium`

### 1.3 与现有能力的关系

- 复用 `knowledge` 路由中的任务流、SSE 日志和后台任务模式
- 参考 `guide` 工作区的 session / manager 组织方式
- 不复用 Notebook 作为主产物容器
- 不影响现有 RAG 搜索、聊天和 Guided Learning

## 2. 端到端数据流

### 2.1 主流程

1. 前端上传文件并提交难度参数
2. 后端创建 `job_id`，生成 artifact 目录结构
3. 后端执行素材归一化：
   - PDF：直接进入下一阶段
   - PPT/PPTX：使用 `soffice --headless --convert-to pdf` 转为 PDF
4. 后端执行 `PageIndex`：
   - 逐页抽文本
   - 渲染页图缩略信息
   - 识别标题候选
   - 记录图像候选区域
5. 后端构建章节树：
   - 规则层抽标题候选
   - LLM 将候选标准化为 2-5 级结构
   - 输出节点与页码范围映射
6. 后端分段生成正文：
   - 按章节树与页范围切块
   - 每块调用 LLM 生成 Markdown 讲义正文
   - 同步输出页码范围与图片占位符
7. 后端执行图片流水线：
   - 识别占位符
   - 生成页号映射
   - 通过定位 Agent 选择象限
   - 通过切图执行器生成图片资源
   - 回填 Markdown / render model
8. 后端渲染最终 PDF 与 `citation_manifest.json`
9. 前端结果页读取任务详情、PDF 地址与 citation 清单

### 2.2 阶段与状态

统一任务状态：

- `queued`
- `normalizing`
- `indexing`
- `planning`
- `generating`
- `processing_images`
- `rendering`
- `ready`
- `failed`

### 2.3 失败与续跑原则

- 若素材归一化失败，任务直接失败，不进入后续阶段
- 若 `PageIndex` 失败，任务失败；后续重试从 `normalize` 后的 PDF 继续
- 若章节树生成失败，可回退到按页段生成
- 若图片定位或切图失败，不阻塞整份文档，可对该占位符降级为整页截图或文本标注
- `retry` 优先复用已存在中间态，而不是重新上传文件

## 3. 后端模块拆分

### 3.1 新增目录

建议新增：

- `deeptutor/api/routers/structure_note.py`
- `deeptutor/services/structure_note/`

### 3.2 服务子模块

建议按以下模块拆分：

#### `models.py`

定义内部类型：

- `DifficultyLevel`
- `JobStatus`
- `StructureNoteArtifact`
- `PageIndexPage`
- `SectionTreeNode`
- `GenerationChunk`
- `CitationEntry`
- `ImagePlaceholder`

#### `storage.py`

负责：

- 生成 artifact 目录
- 读写 `artifact.json`
- 路径组装
- 环境化保留策略清理

#### `normalizer.py`

负责：

- 判断输入格式
- 调用 LibreOffice 完成 PPT/PPTX -> PDF 转换
- 输出标准 PDF 路径
- 提供依赖缺失时的明确错误消息

#### `page_index.py`

负责：

- 使用 PyMuPDF 逐页抽文本
- 记录页码、页尺寸、文本块信息
- 渲染页面基础图像信息
- 提取标题候选与图像候选区域

#### `tree_builder.py`

负责：

- 规则层标题候选提取
- 调用 LLM 将候选标准化为 2-5 级章节树
- 建立 `section -> page range` 映射
- 失败时回退到按页段生成

#### `difficulty.py`

负责三档难度 preset：

- 输出长度预算
- 输出风格约束
- 页窗口大小
- 术语解释深度
- 推理展开深度

#### `generator.py`

负责：

- 根据树结构切分 generation chunks
- 生成 Markdown 正文
- 注入页码范围标签
- 生成图片占位符

#### `image_pipeline.py`

负责：

- 占位符扫描
- 页号映射
- 调用定位 Agent 得到页与象限
- 将象限转换为 PyMuPDF crop box
- 切图并写入 `images/`
- 回填到 Markdown / render model

#### `renderer.py`

负责：

- Markdown -> HTML
- HTML -> PDF（WeasyPrint）
- citation manifest 输出

#### `manager.py`

负责：

- 任务编排
- 状态流转
- 后台续跑
- 对 router 提供统一接口

### 3.3 PathService 扩展

在 `deeptutor/services/path_service.py` 中增加 `structure_note` 工作区路径支持，最终目录落到：

`data/user/workspace/structure_note/<job_id>/`

固定目录结构：

- `source/`
- `normalized/`
- `index/`
- `chunks/`
- `images/`
- `final/`
- `artifact.json`

## 4. API 与类型

### 4.1 对外接口

#### `POST /api/v1/structure-note/jobs`

用途：创建任务  
请求：`multipart/form-data`

- `file`: 上传文件
- `difficulty_level`: `simple | medium | detailed`

行为：

- 验证格式
- 创建 `job_id`
- 写入源文件
- 启动后台任务
- 返回任务基础信息与 task stream 标识

#### `GET /api/v1/structure-note/jobs`

用途：获取工作区历史列表  
返回最少字段：

- `job_id`
- `file_name`
- `difficulty_level`
- `status`
- `created_at`
- `updated_at`

#### `GET /api/v1/structure-note/jobs/{job_id}`

用途：获取任务详情  
返回最少字段：

- `job_id`
- `status`
- `source_format`
- `difficulty_level`
- `final_pdf_path`
- `citation_manifest_summary`
- `retry_available`

#### `POST /api/v1/structure-note/jobs/{job_id}/retry`

用途：失败任务续跑  
行为：

- 读取 `artifact.json`
- 检查上次成功阶段
- 从最近可复用阶段继续执行

#### `GET /api/v1/structure-note/tasks/{task_id}/stream`

用途：SSE 任务流  
复用 `knowledge` 的日志和状态推送模式

### 4.2 内部 artifact 结构

`artifact.json` 至少包含：

- `job_id`
- `source_format`
- `difficulty_level`
- `source_path`
- `normalized_pdf_path`
- `page_index_path`
- `section_tree_path`
- `generation_chunks_path`
- `citation_manifest_path`
- `final_pdf_path`
- `status`
- `retry_state`
- `created_at`
- `updated_at`

### 4.3 Citation 类型

每条 citation 至少包含：

- `citation_id`
- `section_path`
- `page_start`
- `page_end`
- `source_file`
- `source_kind`
- `image_page`
- `image_region`

其中：

- `source_kind` 仅允许 `text` 或 `image`
- `image_page` / `image_region` 仅在图像引用时填写

## 5. 前端工作区设计

### 5.1 页面结构

新页面建议为：

`web/app/(workspace)/structure-note/page.tsx`

### 5.2 三个核心面板

#### 上传与配置

- 文件选择
- 难度切换：
  - 简单
  - 中等（默认）
  - 复杂
- `detailed` 旁边增加一条轻量提示：生成时间更长

#### 处理中

- 阶段文本
- 进度条
- 错误提示
- 重试按钮

#### 结果页

- PDF 预览
- 下载按钮
- citation 侧栏
- 历史任务入口

### 5.3 非目标展示

前端明确不展示：

- 章节树调试信息
- 图片占位符
- 四象限判断
- crop box
- 中间 Markdown
- 中间 JSON

### 5.4 历史列表字段

至少显示：

- 文件名
- 难度
- 状态
- 创建时间
- 重新打开结果

## 6. 生成与渲染策略

### 6.1 难度预设

#### simple

- 目标：关键词、定义、核心知识、结论
- 风格：科普型
- 输出：最短
- 推理：尽量压缩
- 页窗口：默认 10 页

#### medium

- 目标：正常课堂讲解
- 风格：重点解释 + 基础逻辑链
- 输出：中等
- 推理：保留基础过程
- 页窗口：默认 10 页

#### detailed

- 目标：覆盖细节、推理、过程与隐含逻辑
- 风格：最详细
- 输出：最长
- 推理：尽量完整
- 页窗口：自动缩到 5-8 页

### 6.2 章节树生成规则

- 优先依据字体大小、位置、编号样式和文本模式抽取标题候选
- 交给 LLM 做结构归一化，但输出必须约束为 2-5 级节点
- 若 LLM 输出不可用，回退到按页段分组，而不是阻塞整个流程

### 6.3 图片流水线

#### 第一步：占位符生成

正文生成时输出形如：

`[[IMAGE_PLACEHOLDER:section_id:page_hint:purpose]]`

#### 第二步：定位 Agent

Agent 输出固定格式：

- 第几页
- 象限：`left_top | right_top | left_bottom | right_bottom`

#### 第三步：切图执行

根据页面宽高将页面切成四象限：

- 左上
- 右上
- 左下
- 右下

切图执行器只做确定性 crop，不自行做语义判断。

#### 第四步：回填

回填模块将图片资源路径写回 Markdown 或 render model，再进入最终 PDF 渲染。

### 6.4 PDF 渲染

- 中间产物使用 Markdown 表达
- 渲染时先转 HTML，再交给 WeasyPrint 输出 PDF
- 引用不嵌入正文，只保留干净版 PDF
- citation manifest 单独生成 JSON，供前端侧栏展示

## 7. 存储与中间态策略

### 7.1 存储内容

在完整保留模式下，应保存：

- 原始上传文件
- 归一化 PDF
- 页级索引 JSON
- 章节树 JSON
- generation chunks JSON
- 图片资源
- 回填后 Markdown
- citation manifest
- 最终 PDF
- `artifact.json`

### 7.2 环境化保留策略

建议新增环境配置项，例如：

- `STRUCTURE_NOTE_RETENTION_MODE=full|minimal`

规则：

- 测试环境默认 `full`
- 生产环境默认 `minimal`

`minimal` 至少保留：

- `artifact.json`
- `final.pdf`
- `citation_manifest.json`

### 7.3 续跑策略

`retry_state` 记录最近成功阶段。续跑时遵循：

- 已完成 `normalize`：不重复转换
- 已完成 `page_index`：不重复抽页
- 已完成 `tree_build`：不重复建树
- 仅后续阶段失败：从失败阶段继续

## 8. 测试矩阵与实施里程碑

### 8.1 单元测试

- `PageIndex` 逐页文本提取
- 空页处理
- 页码顺序稳定
- 标题候选抽取规则
- 树标准化结果满足 2-5 级结构约束
- 难度 preset 对窗口大小和长度预算的影响
- 象限到 crop box 的换算
- 保留策略清理逻辑

### 8.2 集成测试

- PDF 上传全链路成功，生成 PDF 与 citation manifest
- PPT/PPTX 上传真实走 LibreOffice 转 PDF，再进入后续链路
- `simple / medium / detailed` 三档输出长度和内容密度有明显差异
- 图片占位符能被回填
- 图片失败时能降级或重试
- 任务中断后 `retry` 会复用中间态，而不是从头重跑

### 8.3 前端测试

- 上传页能提交文件和难度
- 处理中状态能接收 SSE 进度
- 结果页能加载 PDF 和 citation 侧栏
- 失败任务能触发重试

### 8.4 验收样本

- 学生教材 PDF：中等模式，结果可读、页码回溯清楚
- 教师 PPT：复杂模式，细节展开明显更多
- 简单模式：明显短于中等与复杂，不丢失关键词和核心知识

### 8.5 实施里程碑

#### M1：文档与骨架

- 在 `docs/testdoc/` 落 `PRD + 技术计划`
- 建立路由、artifact 模型、目录结构、SSE 任务流

#### M2：素材归一化与 PageIndex

- 接通 PDF 上传
- 接通 PPT/PPTX -> PDF 转换
- 产出页级索引与章节树

#### M3：内容生成与三档难度

- 接通 chunk 生成
- 接通难度 preset
- 产出 citation manifest

#### M4：图片流水线与 PDF 渲染

- 接通占位符识别、象限定位、切图回填
- 接通 Markdown -> HTML -> PDF

#### M5：前端结果工作区与完整测试

- 上传 / 进度 / 结果 / 重试闭环
- 完成集成测试与验收样本

## 9. 实施默认值

- 文档落盘格式使用中文 Markdown，不额外导出 PDF 版 PRD / 技术计划
- `docs/testdoc` 仅作归档，不在文档 sidebar 中额外挂载
- LibreOffice 是首发必需依赖；环境缺失时，PPT/PPTX 上传失败并返回安装指引
- 最终 PDF 不内嵌完整引用；完整引用只在前端侧栏和 `citation_manifest.json` 中展示
- 中间态保留走环境配置：测试环境保留完整中间态，生产环境默认保留 `artifact.json + final.pdf + citation_manifest.json`
