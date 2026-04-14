---
layout: home

hero:
  name: "DeepTutor"
  text: "你的 AI 学习伙伴"
  tagline: 将任何文档转化为多智能体驱动的互动学习体验
  image:
    src: /logo.png
    alt: DeepTutor
  actions:
    - theme: brand
      text: 快速开始 →
      link: /zh/guide/pre-config
    - theme: alt
      text: GitHub
      link: https://github.com/HKUDS/DeepTutor

features:
  - icon: 📚
    title: 海量文档问答
    details: 上传教材、论文和手册，构建基于 RAG 和知识图谱的 AI 知识库。
  - icon: 🧠
    title: 智能解题
    details: 双循环推理架构配合多智能体协作，提供带有精准文档引用的逐步解答。
  - icon: 🎯
    title: 题目生成
    details: 基于知识库生成自定义测验，或模拟真实考试风格进行练习。
  - icon: 🎓
    title: 引导学习
    details: 个性化学习路径，配合交互式可视化和自适应讲解。
  - icon: 🔬
    title: 深度研究
    details: 系统化主题探索，整合网络搜索、论文检索和文献综合。
  - icon: 💡
    title: 灵感生成
    details: AI 辅助头脑风暴，知识提取与多阶段筛选。
---

## 为什么选择 DeepTutor？

- **深度理解** — 不只是答案，而是带有可视化讲解的引导式学习之旅
- **多模态支持** — PDF、LaTeX、图片、代码执行等全面支持
- **知识图谱** — 基于 LightRAG 的语义连接，实现更好的理解
- **一站式平台** — 解题、题目生成、研究、灵感生成集于一体

<style>
:root {
  --vp-home-hero-name-color: transparent;
  --vp-home-hero-name-background: linear-gradient(135deg, #667eea 0%, #764ba2 50%, #f093fb 100%);
  --vp-home-hero-image-background-image: linear-gradient(135deg, rgba(102, 126, 234, 0.2) 0%, rgba(118, 75, 162, 0.2) 50%, rgba(240, 147, 251, 0.15) 100%);
  --vp-home-hero-image-filter: blur(72px);
}

.dark {
  --vp-home-hero-image-background-image: linear-gradient(135deg, rgba(102, 126, 234, 0.15) 0%, rgba(118, 75, 162, 0.15) 50%, rgba(240, 147, 251, 0.1) 100%);
}

.VPHero .name {
  font-size: 4.5rem !important;
  line-height: 1.1 !important;
}

.VPHero .text {
  font-size: 2.4rem !important;
  font-weight: 600 !important;
}

@media (max-width: 768px) {
  .VPHero .name {
    font-size: 3rem !important;
  }
  .VPHero .text {
    font-size: 1.8rem !important;
  }
}
</style>
