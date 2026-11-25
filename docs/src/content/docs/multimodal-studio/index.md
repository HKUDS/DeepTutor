---
title: Which generator to use
description: How Visualize, Math Animator, and Video Lesson divide the work of making something you can watch.
quadrant: explanation
---

Make one figure in [Make a figure](/learn/make-a-figure/). Math Animator and Video Lesson stay on this page.

DeepTutor has three generators. They share the chat thread and a model, and they answer different jobs.

| Generator | You want | What comes back |
| --- | --- | --- |
| [Visualize](/multimodal-studio/visualize/) | A figure you can read: a plot, a diagram, a small interactive page | SVG, Mermaid, Chart.js, or HTML in the thread |
| [Math Animator](/multimodal-studio/math-animator/) | A derivation or geometric construction that has to move | A Manim video or a storyboard |
| [Video Lesson](/multimodal-studio/video-lesson/) | A short lesson someone can play, with captions | A browser lesson, optionally narrated |

Visualize can also hand a math animation to the Manim renderer. Math Animator is the path when the subject is the mathematics itself. Video Lesson is a lesson, not a single figure: it writes a sequence, checks the render, and plays it in the browser.

All three are capabilities on top of the same [agent loop](/learning-workspace/agent-loop/). A missing system tool (LaTeX, ffmpeg, or Node for a source install) stops the render. It does not change which generator you should have chosen.
