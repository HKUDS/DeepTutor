---
layout: home

hero:
  name: "DeepTutor"
  text: "Your AI Learning Companion"
  tagline: Transform any document into an interactive learning experience with multi-agent intelligence
  image:
    src: /logo.png
    alt: DeepTutor
  actions:
    - theme: brand
      text: Get Started →
      link: /guide/pre-config
    - theme: alt
      text: GitHub
      link: https://github.com/HKUDS/DeepTutor

features:
  - icon: 📚
    title: Massive Document Q&A
    details: Upload textbooks, papers, and manuals. Build AI-powered knowledge repositories with RAG and knowledge graph integration.
  - icon: 🧠
    title: Smart Problem Solving
    details: Dual-loop reasoning architecture with multi-agent collaboration, delivering step-by-step solutions with precise citations.
  - icon: 🎯
    title: Practice Generator
    details: Generate custom quizzes based on your knowledge base, or mimic real exam styles for authentic practice.
  - icon: 🎓
    title: Guided Learning
    details: Personalized learning paths with interactive visualizations and adaptive explanations.
  - icon: 🔬
    title: Deep Research
    details: Systematic topic exploration with web search, paper retrieval, and literature synthesis.
  - icon: 💡
    title: Idea Generation
    details: AI-assisted brainstorming with knowledge extraction and multi-stage filtering.
---

## Why DeepTutor?

- **Deep Understanding** — Not just answers, but guided learning journeys with visual explanations
- **Multi-Modal Support** — PDF, LaTeX, images, code execution, and more
- **Knowledge Graph** — Semantic connections powered by LightRAG for better comprehension
- **All-in-One Platform** — Problem solving, question generation, research, and idea generation in one place

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
