# Source Ingest 使用指南

## 功能概述

笔记本的 Source 功能现在支持三种方式添加参考来源，所有内容都会被自动向量化并用于 Grounded QA：

1. **HTML 网页 URL** - 自动爬取网页内容
2. **PDF 文档 URL** - 自动下载 PDF 文件
3. **本地 PDF 上传** - 上传本地 PDF 文件

## 使用方法

### 方式一：添加 URL（前端）

1. 打开笔记本页面
2. 点击"添加来源"按钮
3. 输入 URL：
   - HTML 网页：`https://example.com/article`
   - PDF 文档：`https://arxiv.org/pdf/2301.00001.pdf`
4. 点击确认
5. 等待几秒，系统会自动：
   - 爬取/下载内容
   - 向量化存入知识库
6. 在聊天时选中该 source
7. 提问时模型会基于完整内容回答

### 方式二：上传 PDF（API）

使用 curl 或其他 HTTP 客户端：

```bash
curl -X POST "http://localhost:8000/api/notebook/{notebook_id}/upload_source_pdf" \
  -F "file=@/path/to/your/paper.pdf"
```

响应示例：
```json
{
  "success": true,
  "filename": "paper.pdf",
  "file_path": "/data/knowledge_base/notebook_xxx_sources/raw/paper.pdf",
  "kb_name": "notebook_xxx_sources"
}
```

**注意事项：**
- PDF 文件最大 50MB
- 只支持 .pdf 格式
- 上传后需要等待几秒让向量化完成

### 方式三：前端集成 PDF 上传（待实现）

前端可以添加一个文件上传按钮，调用上述 API：

```typescript
const handleUploadPDF = async (file: File) => {
  const formData = new FormData();
  formData.append('file', file);

  const response = await fetch(
    `/api/notebook/${notebookId}/upload_source_pdf`,
    {
      method: 'POST',
      body: formData,
    }
  );

  const result = await response.json();
  console.log('PDF uploaded:', result);

  // 刷新 sources 列表或添加到本地状态
  // ...
};
```

## 支持的 URL 类型

### HTML 网页
- 博客文章
- 技术文档
- 新闻报道
- 任何包含文本内容的网页

系统会自动：
- 提取主要内容（去除导航、广告等）
- 转换为 Markdown 格式
- 保留标题、段落结构

### PDF 文档
- 学术论文（如 arXiv）
- 技术报告
- 书籍章节
- 任何 PDF 格式文档

系统会自动：
- 下载完整 PDF 文件
- 使用 RAGAnything 解析（支持图片、表格、公式）
- 提取文本和结构化信息

## 查看处理状态

### 检查知识库文件

```bash
# 查看 sources KB 的原始文件
ls -la data/knowledge_base/notebook_{id}_sources/raw/

# HTML sources 会生成 .md 文件
# PDF sources 会保存为 .pdf 文件
```

### 检查向量化状态

```bash
# 查看 RAG 存储目录
ls -la data/knowledge_base/notebook_{id}_sources/rag_storage/
```

如果看到 `graph_chunk_entity_relation.graphml` 等文件，说明向量化已完成。

## 常见问题

### Q: 添加 URL 后多久可以使用？

A: 通常几秒到几十秒，取决于：
- HTML 网页：1-5 秒（爬取 + 向量化）
- 小 PDF（<5MB）：5-15 秒
- 大 PDF（>10MB）：15-60 秒

### Q: 支持哪些网站？

A: 理论上支持所有公开访问的网站，但：
- 需要登录的网站不支持
- 有反爬虫机制的网站可能失败
- 纯 JavaScript 渲染的网站可能内容不完整

### Q: PDF 解析效果如何？

A: 使用 RAGAnything + MinerU 解析，支持：
- ✓ 文本提取
- ✓ 表格识别
- ✓ 图片处理
- ✓ 公式识别
- ✓ 多栏布局

### Q: 如何删除已添加的 source？

A: 目前需要在前端 session 中删除 source，然后保存 session。系统会自动重建知识库。

### Q: 可以添加多少个 sources？

A: 没有硬性限制，但建议：
- 每个笔记本 < 50 个 sources
- 总内容 < 100MB
- 过多 sources 会影响检索速度

## 技术细节

### 爬取限制

- 超时：30 秒
- HTML 内容：最大 50,000 字符
- PDF 文件：最大 50MB
- 并发数：5 个 URL 同时爬取

### 错误处理

如果爬取失败，source 会被标记 `fetch_error` 字段，但不会阻塞其他 sources。

查看日志：
```bash
# 后端日志会显示爬取状态
tail -f logs/app.log | grep WebCrawler
```

### 知识库结构

```
data/knowledge_base/notebook_{id}_sources/
├── raw/                    # 原始文件
│   ├── source_abc123.md   # HTML 转换的 markdown
│   └── paper.pdf          # 下载的 PDF
├── rag_storage/           # 向量化数据
│   ├── graph_chunk_entity_relation.graphml
│   ├── kv_store_full_docs.json
│   └── ...
└── sources_manifest.json  # 元数据
```

## 示例场景

### 场景一：研究论文

1. 添加 arXiv 论文 URL：`https://arxiv.org/pdf/2301.00001.pdf`
2. 等待下载和向量化
3. 在聊天中选中该 source
4. 提问："这篇论文的主要贡献是什么？"
5. 模型会基于完整论文内容回答

### 场景二：技术博客

1. 添加博客 URL：`https://blog.example.com/how-to-use-react`
2. 系统自动提取文章内容
3. 在聊天中选中该 source
4. 提问："文章中提到的最佳实践有哪些？"
5. 模型会引用文章中的具体段落

### 场景三：混合来源

1. 添加多个 sources：
   - 论文 PDF
   - 官方文档网页
   - 技术博客
2. 在聊天时全部选中
3. 提问综合性问题
4. 模型会综合所有来源的信息回答

## 下一步优化

- [ ] 前端添加 PDF 上传按钮
- [ ] 显示爬取/上传进度
- [ ] 支持更多文件格式（Word, PPT）
- [ ] 定期更新过期内容
- [ ] 智能去重（相同 URL 不重复爬取）
