# Source URL Ingest Implementation (with PDF Support)

## 概述

实现了自动爬取和向量化 source URL 的功能，支持 HTML 网页和 PDF 文件（URL 下载 + 本地上传），解决了 Grounded QA 效果差的问题。

## 问题背景

之前的实现中，笔记本的 source URL 只存储了 URL 和摘要等元数据，原始网页内容并没有被爬取和向量化。这导致：
- Grounded QA 无法访问原始内容
- 回答质量严重依赖有限的元数据
- 无法进行段落级的精确检索
- 不支持 PDF 文档作为来源

## 解决方案

采用**方案二：异步爬取 + 专属知识库**，并扩展支持 PDF

### 支持的来源类型

1. **HTML 网页 URL**：自动爬取网页内容，提取主要文本，转换为 Markdown
2. **PDF URL**：自动下载 PDF 文件，保存到知识库，由 RAGAnything 处理
3. **本地 PDF 上传**：通过 API endpoint 上传 PDF 文件到知识库

### 工作流程

当用户添加 source 时：
1. 前端调用 `handleAddSourceUrl` 添加 source（只有 URL，无 content）
2. 前端保存 session 时触发 `POST /{notebook_id}/sessions`
3. 后端的 `_sync_sources_kb` 检测到 source 缺少 content
4. 自动调用 `web_crawler.fetch_urls` 并发爬取/下载所有 URL
   - HTML URL：提取内容并转换为 Markdown
   - PDF URL：下载 PDF 文件到 raw 目录
5. 写入 `notebook_{id}_sources` 知识库的 raw 目录
6. 后台任务异步处理：chunk + embedding + 存储
7. 聊天时通过 `sources_kb_name` 参数检索相关内容

## 实现细节

### 1. Web Crawler (`src/tools/web_crawler.py`)

核心功能：
- 使用 `httpx` 异步获取网页和 PDF
- 使用 `readability-lxml` 提取 HTML 主要内容
- 使用 `markdownify` 转换为 Markdown
- **支持 PDF 下载**：检测 PDF URL，下载到指定目录
- 支持并发爬取（默认 5 个并发）
- 自动跳过非内容资源（图片、视频等，但不跳过 PDF）
- 内容长度限制（HTML: 50,000 字符，PDF: 50MB）
- 超时控制（30 秒）

关键函数：
```python
async def fetch_url(url: str, pdf_save_dir: Optional[Path] = None) -> dict:
    """
    返回 {url, title, content/file_path, error, filename, is_pdf}
    - 如果是 HTML：返回 content 字段
    - 如果是 PDF：返回 file_path 字段
    """

async def fetch_pdf(url: str, save_dir: Path) -> dict:
    """下载 PDF 文件到指定目录"""

async def fetch_urls(urls: list[str], concurrency: int = 5, pdf_save_dir: Optional[Path] = None) -> list[dict]:
    """并发爬取多个 URL（支持混合 HTML 和 PDF）"""
```

### 2. Source Enrichment (`src/api/routers/notebook.py`)

新增/修改函数：

**`_enrich_sources_with_content(sources, raw_dir)`**：
- 检测哪些 source 需要爬取（type=web, 有 url, 无 content/file_path）
- 并发爬取所有缺失内容的 URL
- 对于 HTML：将内容填充到 source 的 content 字段
- 对于 PDF：将文件路径填充到 source 的 file_path 字段，标记 is_pdf=True
- 记录爬取错误到 fetch_error 字段

**`_write_source_files(raw_dir, sources)`**：
- 对于 HTML sources：创建 markdown 文件
- 对于 PDF sources：PDF 已下载，直接返回文件路径

**`_sync_sources_kb(notebook_id, background_tasks)`**：
- 改为 async 函数
- 先创建 KB 和 raw_dir
- 调用 `_enrich_sources_with_content` 爬取内容（传入 raw_dir 用于保存 PDF）
- 写入文件并触发后台向量化

### 3. PDF 上传 API

新增 endpoint：`POST /{notebook_id}/upload_source_pdf`

功能：
- 接收用户上传的 PDF 文件
- 验证文件类型和大小（最大 50MB）
- 保存到 notebook 的 sources KB 的 raw 目录
- 触发后台向量化任务

请求示例：
```bash
curl -X POST "http://localhost:8000/api/notebook/{notebook_id}/upload_source_pdf" \
  -F "file=@paper.pdf"
```

响应：
```json
{
  "success": true,
  "filename": "paper.pdf",
  "file_path": "/path/to/kb/raw/paper.pdf",
  "kb_name": "notebook_xxx_sources"
}
```

### 4. 依赖更新

在 `requirements.txt` 中添加：
```
readability-lxml>=0.8.1
markdownify>=0.11.6
```

`httpx` 已存在，无需添加。

## 使用流程

### 用户视角

#### 方式一：添加 URL（HTML 或 PDF）

1. 在笔记本中点击"添加来源"
2. 输入 URL
   - HTML 网页：如 `https://example.com/article`
   - PDF 文档：如 `https://arxiv.org/pdf/2301.00001.pdf`
3. 点击确认
4. 系统自动：
   - HTML：爬取网页内容，提取主要文本，转换为 Markdown
   - PDF：下载 PDF 文件到知识库
   - 向量化并存入知识库
5. 在聊天时选中该 source
6. 模型可以基于完整内容回答问题

#### 方式二：上传本地 PDF

1. 调用 API：`POST /api/notebook/{notebook_id}/upload_source_pdf`
2. 上传 PDF 文件（最大 50MB）
3. 系统自动保存并向量化
4. 在前端刷新 sources 列表（需要前端集成）

### 技术流程

#### URL 添加流程（HTML + PDF）

```
用户添加 URL
    ↓
前端 handleAddSourceUrl (web/app/notebooks/[id]/page.tsx:1833)
    ↓
保存 session → POST /{notebook_id}/sessions
    ↓
后端 upsert_session (src/api/routers/notebook.py:674)
    ↓
await _sync_sources_kb
    ↓
await _enrich_sources_with_content (传入 raw_dir)
    ↓
fetch_urls (并发爬取，HTML 提取内容，PDF 下载文件)
    ↓
_write_source_files (HTML 写 markdown，PDF 使用已下载文件)
    ↓
后台任务: run_upload_processing_task
    ↓
DocumentAdder.process_new_documents
    ↓
RAGAnything 处理 → Chunking → Embedding → 存储
    ↓
聊天时通过 sources_kb_name 检索
```

#### PDF 上传流程

```
用户上传 PDF
    ↓
POST /{notebook_id}/upload_source_pdf
    ↓
验证文件类型和大小
    ↓
保存到 sources KB 的 raw 目录
    ↓
后台任务: run_upload_processing_task
    ↓
RAGAnything 处理 PDF → Chunking → Embedding → 存储
    ↓
聊天时通过 sources_kb_name 检索
```

## 测试验证

### 1. 运行自动化测试

```bash
cd /Users/bytedance/DeepTutor-1-source-ingest
python manual_tests/source_ingest_check.py
```

测试内容：
- HTML URL 爬取
- PDF URL 下载
- 并发爬取混合类型
- Source enrichment 逻辑

spec = importlib.util.spec_from_file_location('web_crawler', 'src/tools/web_crawler.py')
web_crawler = importlib.util.module_from_spec(spec)

class MockLogger:
    def info(self, msg): print(f'INFO: {msg}')
    def warning(self, msg): print(f'WARN: {msg}')

web_crawler.logger = MockLogger()
spec.loader.exec_module(web_crawler)

async def test():
    result = await web_crawler.fetch_url('https://example.com')
    print(f'Title: {result[\"title\"]}')
    print(f'Content: {result[\"content\"][:200]}...')

asyncio.run(test())
"
```

### 2. 端到端测试

1. 启动后端服务
2. 打开笔记本页面
3. 添加一个 source URL（如技术博客文章）
4. 等待几秒让爬取和向量化完成
5. 在聊天中选中该 source
6. 提问关于文章内容的问题
7. 验证回答是否基于完整内容

### 3. 检查知识库

```bash
# 查看生成的 markdown 文件
ls -la data/knowledge_base/notebook_<id>_sources/raw/

# 查看文件内容
cat data/knowledge_base/notebook_<id>_sources/raw/source_*.md
```

## 性能考虑

1. **并发控制**：默认 5 个并发请求，避免过载
2. **超时设置**：30 秒超时，防止卡住
3. **内容限制**：单页最多 50,000 字符，避免内存问题
4. **异步处理**：爬取在 API 请求中完成，向量化在后台任务中完成
5. **缓存机制**：通过 signature 检测内容变化，避免重复处理

## 错误处理

- 爬取失败：记录到 `fetch_error` 字段，不阻塞其他 source
- 非 HTML 资源：自动跳过（PDF、图片等）
- 超时：记录错误，继续处理其他 URL
- HTTP 错误：记录状态码，不影响整体流程

## 后续优化建议

1. **增量更新**：支持定期重新爬取，更新过期内容
2. **爬取队列**：对于大量 source，使用任务队列异步处理
3. **内容预览**：前端显示爬取状态和内容摘要
4. **智能提取**：针对特定网站（如 arXiv、GitHub）使用专门的提取器
5. **PDF 支持**：扩展支持 PDF 文档的爬取和解析
6. **去重机制**：检测重复 URL，避免重复爬取

## 文件清单

### 新增文件
- `src/tools/web_crawler.py` - Web 爬虫工具

### 修改文件
- `src/api/routers/notebook.py` - 添加 source enrichment 逻辑
- `requirements.txt` - 添加爬虫依赖

### 未修改（前端无需改动）
- `web/app/notebooks/[id]/page.tsx` - 前端逻辑保持不变
