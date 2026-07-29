# MathTutor 学生使用指南

竞赛数学 AI 导师 — 在浏览器里用 AI 学数学，覆盖 13,000+ 道竞赛题（数论、组合、几何、代数），每道题拆解为 20+ 步详解，每题绑定知识点。

## 你需要什么

| 要求 | 说明 |
|------|------|
| 电脑 | macOS 或 Linux（Windows 用户请用 WSL） |
| Python | 3.11 或以上 |
| Node.js | 22 或以上 |
| DeepSeek API Key | 用于 AI 对话（LLM），[注册获取](https://platform.deepseek.com) |
| SiliconFlow API Key | 用于题库索引（Embedding），[注册获取](https://siliconflow.cn) |
| 网络 | 能访问 api.deepseek.com 和 8.138.199.23:8080 |
| 磁盘空间 | 约 3-5 GB（依赖 + KB 索引） |

> **费用说明**：DeepSeek API 按量计费（约 ¥1/百万 token），普通学习使用一个月几块钱。SiliconFlow Embedding 首次建索引消耗约几毛钱。

## 安装（3 步）

### 1. 下载代码

```bash
git clone https://github.com/xiongjnu/DeepTutor.git
cd DeepTutor
```

### 2. 一键安装

```bash
bash scripts/setup.sh
```

脚本自动完成：检查 Python/Node → 创建虚拟环境 → 安装 Python 包 → 构建前端。

### 3. 配置 API Key

编辑项目根目录的 `.env` 文件（setup.sh 已从 `.env.student` 自动复制）：

```
LLM_API_KEY=sk-你的DeepSeekKey
EMBEDDING_API_KEY=sk-你的SiliconFlowKey
```

安装完成后，把 `MathTutor.app` 拖到 `/Applications` 即可双击启动。

## 启动

**macOS 用户**（推荐）：Finder 里双击 `MathTutor.app`，等待进度条走完，浏览器自动打开。

**命令行用户**：
```bash
bash scripts/start.sh
```

浏览器打开 **http://localhost:3782**，看到聊天界面即成功。

## 同步 MathNet 题库

```bash
bash scripts/sync-mathnet.sh
```

首次同步约需 **30-60 分钟**（13,000+ 题 → 向量索引）。同步完成后，在 Chat 界面左侧 Knowledge Base 面板勾选 **MathNet** 即可。

## 怎么用

### Chat 问答（最常用）

在聊天框直接问数学题。勾选 MathNet KB 后，AI 会从题库中检索相关题目和知识点辅助回答。

试试这些问题：
- "鸽巢原理有哪些经典应用？给我讲一道 L1 难度的题"
- "线性代数中矩阵对角化的核心思想是什么？"
- "给我讲一道用数学归纳法的组合题"
- "请用 Deep Solve 帮我拆解这道题：证明 √2 是无理数"

### 6 种学习模式

| 模式 | 用途 |
|------|------|
| **Chat** | 日常问答，挂在 MathNet KB 上问数学 |
| **Deep Solve** | 多 Agent 协作，分步骤深入解一道题 |
| **Quiz** | 基于题库自动出题自测 |
| **Math Animator** | 生成 Manim 数学动画（可视化） |
| **Deep Research** | 多轮调研一个数学主题 |
| **Notebook** | 保存学习笔记和题目 |

### 难度参照 (L1-L4)

| 难度 | 对标 | 大一学生 |
|:---:|------|:---:|
| L1 | 高中竞赛入门 / 高等数学(上) | ✅ |
| L2 | 省赛难度 / 高等数学(下)+线性代数 | ✅ |
| L3 | 全国赛难度 / 离散数学 | 🔜 大二 |
| L4 | IMO 级别 / 高级方法 | 🔜 大二下+ |

## 更新题库

云端题库持续更新中。当有新题加入时：

```bash
bash scripts/sync-mathnet.sh
```

增量同步只更新变化部分，比首次快很多。

## 常见问题

### Q: 启动报错 "端口被占用"

编辑 `.env`：
```
BACKEND_PORT=8003
FRONTEND_PORT=3783
```
重新运行 `bash scripts/start.sh`。

### Q: DeepSeek API 返回 401

检查 `.env` 中 `LLM_API_KEY` 是否正确，以及 DeepSeek 账户余额是否充足。

### Q: 同步题库很慢

13k 题建立 RAG 索引需要向 SiliconFlow 发送 embedding 请求。这是正常的，只需做一次。后续更新只处理增量。

### Q: 想卸载

删除整个项目目录即可。所有数据都在项目目录内（`data/`、`.venv/`），不会在系统其他地方残留。

### Q: 题库只有竞赛题，没有课堂练习题？

竞赛题代表经典题型和思维方式，与大学课程有对应关系（见上表）。如果确实需要特定教材的题，可以用 Chat 的 Deep Solve 功能输入你的题让 AI 解答。

## 帮助

有问题联系 xj。
