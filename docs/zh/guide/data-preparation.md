# 数据准备

DeepTutor 提供示例知识库和样例问题，帮助您快速上手。

## 示例知识库

我们在 [Google Drive](https://drive.google.com/drive/folders/1iWwfZXiTuQKQqUYb5fGDZjLCeTUP6DA6?usp=sharing) 上提供两个预构建的知识库：

### 1. 研究论文合集

<div class="info-card">
  <div class="info-header">
    <span class="info-icon">📄</span>
    <span class="info-title">5 篇研究论文（每篇 20-50 页）</span>
  </div>
  <div class="info-content">
    <p>来自我们实验室的前沿研究论文精选集，涵盖 RAG 和 Agent 领域。</p>
    <p><strong>包含论文：</strong></p>
    <ul>
      <li><a href="https://github.com/HKUDS/AI-Researcher">AI-Researcher</a> - 自动化研究论文生成</li>
      <li><a href="https://github.com/HKUDS/AutoAgent">AutoAgent</a> - 自主智能体框架</li>
      <li><a href="https://github.com/HKUDS/RAG-Anything">RAG-Anything</a> - 多模态 RAG 系统</li>
      <li><a href="https://github.com/HKUDS/LightRAG">LightRAG</a> - 简洁快速的 RAG</li>
      <li><a href="https://github.com/HKUDS/VideoRAG">VideoRAG</a> - 基于 RAG 的视频理解</li>
    </ul>
    <p><strong>适用场景：</strong> 研究场景，广泛知识覆盖</p>
  </div>
</div>

### 2. 数据科学教材

<div class="info-card">
  <div class="info-header">
    <span class="info-icon">📚</span>
    <span class="info-title">8 章，296 页</span>
  </div>
  <div class="info-content">
    <p>来自加州大学伯克利分校的综合深度学习教材。</p>
    <p><strong>来源：</strong> <a href="https://ma-lab-berkeley.github.io/deep-representation-learning-book/">Deep Representation Learning Book</a></p>
    <p><strong>涵盖主题：</strong></p>
    <ul>
      <li>神经网络基础</li>
      <li>表示学习</li>
      <li>深度学习架构</li>
      <li>高级主题</li>
    </ul>
    <p><strong>适用场景：</strong> 学习场景，深度知识挖掘</p>
  </div>
</div>

## 下载与设置

### 步骤 1：下载

访问我们的 [Google Drive 文件夹](https://drive.google.com/drive/folders/1iWwfZXiTuQKQqUYb5fGDZjLCeTUP6DA6?usp=sharing) 并下载：

- `knowledge_bases.zip` - 包含嵌入的预构建知识库
- `questions.zip` - 样例问题和使用示例（可选）

### 步骤 2：解压

将下载的文件解压到 `data/` 目录：

```
DeepTutor/
├── data/
│   └── knowledge_bases/
│       ├── research_papers/      # 研究论文知识库
│       ├── data_science_book/    # 教材知识库
│       └── kb_config.json        # 知识库配置
└── user/                         # 用户数据（自动创建）
```

### 步骤 3：验证

解压后，启动 DeepTutor 时您的知识库将自动可用。

::: warning 嵌入兼容性
我们的示例知识库使用 `text-embedding-3-large`，`dimensions = 3072`。

如果您的嵌入模型具有不同的维度，您需要创建自己的知识库。
:::

## 创建自定义知识库

### 支持的文件格式

| 格式 | 扩展名 | 说明 |
|:-------|:----------|:------|
| PDF | `.pdf` | 支持文本提取和版面分析 |
| 文本 | `.txt` | 纯文本文件 |
| Markdown | `.md` | 支持格式化的 Markdown |

### 通过 Web 界面

1. 导航到 `http://localhost:3782/knowledge`
2. 点击 **"New Knowledge Base"**
3. 为您的知识库输入唯一名称
4. 上传您的文档（单个或批量上传）
5. 等待处理完成

::: tip 处理时间
- 小文档（< 10 页）：约 1 分钟
- 中等文档（10-100 页）：约 5-10 分钟
- 大文档（100+ 页）：可能需要更长时间
:::

### 通过命令行

```bash
# 使用文档初始化新知识库
python -m src.knowledge.start_kb init <kb_name> --docs <pdf_path>

# 向现有知识库添加文档
python -m src.knowledge.add_documents <kb_name> --docs <new_document.pdf>
```

## 数据存储结构

所有用户数据存储在 `data/` 目录中：

```
data/
├── knowledge_bases/              # 知识库存储
│   ├── <kb_name>/
│   │   ├── documents/            # 原始文档
│   │   ├── chunks/               # 分块内容
│   │   ├── embeddings/           # 向量嵌入
│   │   └── graph/                # 知识图谱数据
└── user/                         # 用户活动数据
    ├── solve/                    # 解题结果
    ├── question/                 # 生成的题目
    ├── research/                 # 研究报告
    ├── notebook/                 # 笔记本记录
    └── logs/                     # 系统日志
```

---

**下一步：** [本地安装 →](/zh/guide/local-start)

<style>
.info-card {
  background: var(--vp-c-bg-soft);
  border: 1px solid var(--vp-c-border);
  border-radius: 12px;
  padding: 20px;
  margin: 16px 0;
}

.info-header {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 16px;
}

.info-icon {
  font-size: 1.5rem;
}

.info-title {
  font-size: 1.1rem;
  font-weight: 600;
  color: var(--vp-c-text-1);
}

.info-content {
  color: var(--vp-c-text-2);
  line-height: 1.7;
}

.info-content ul {
  margin: 12px 0;
  padding-left: 20px;
}

.info-content li {
  margin: 6px 0;
}

.info-content a {
  color: var(--vp-c-brand-1);
}
</style>
