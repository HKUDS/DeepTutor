---
title: 能力
description: 已注册能力的名称、阶段、所属模块和 CLI 别名。
quadrant: reference
---

名称、阶段和 CLI 别名来自 `deeptutor/modules/manifests/*.json` 里每个能力的 `manifest`。描述保持清单中的英文原文。

| 能力 | 模块 | 阶段 | CLI | 说明 |
| --- | --- | --- | --- | --- |
| `audio_overview` | `audio-overview` | `retrieving`, `script_writing`, `voice_generation`, `publishing` | `audio-overview`, `overview` | Create a grounded two-voice audio overview and transcript from a knowledge base. |
| `chat` | `core` | `exploring`, `responding` | `chat` | Agentic chat: an exploring agent loop with tools, followed by a respond stage that streams the answer. |
| `ask_questions` | `core` | `responding` | `ask` | Ask the user high-value questions to fill in missing context, then complete the original request with their answers. |
| `mastery_path` | `mastery` | `responding` | `mastery` | Mastery-based tutoring: a dedicated agent loop drives an adaptive mastery path with a hard, per-type mastery gate and spaced review. |
| `deep_question` | `questions` | `ideation`, `generation` | `quiz` | Fast question generation (Template batches -> Generate). |
| `immersive_reading` | `reading` | `responding` | `reading`, `read` | Read a document alongside the assistant, which cites the exact page or section behind every claim. |
| `math_animator` | `renderer-manim` | `concept_analysis`, `concept_design`, `code_generation`, `code_retry`, `summary`, `render_output` | `animate` | Generate math animations or storyboard images with Manim. |
| `deep_research` | `research` | `rephrasing`, `decomposing`, `researching`, `reporting` | `research` | Agentic-loop deep research with iterative report generation. |
| `deep_solve` | `solve` | `responding` | `solve` | Multi-step problem solving driven by the chat agent loop. |
| `video_lesson` | `video-lesson` | `code_generation`, `render_check`, `render_output` | `lesson` | Generate an animated video lesson (Remotion) that plays in the browser. |
| `visualize` | `visualize` | `analyzing`, `generating`, `reviewing`, `concept_analysis`, `concept_design`, `code_generation`, `code_retry`, `summary`, `render_output` | `visualize`, `viz` | Generate a validated visualization with any installed visualizer type, or render a Manim animation/storyboard artifact. |
