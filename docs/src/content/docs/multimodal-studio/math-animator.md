---
title: Math Animator
description: Render one Manim math animation from Chat.
quadrant: how-to
---

**Math Animator** (`math_animator`) writes a Manim scene for one derivation or construction and renders a video or a storyboard. The machine that renders needs LaTeX and ffmpeg. A desktop install does not bundle those tools.

On a source or PyPI install, the renderer comes from the `math-animator` extra. See [Install from source](/self-hosting/source/#optional-install-extras).

## Render one animation

1. Confirm `latex` and `ffmpeg` run in a terminal on this computer.
2. Open [Chat](/learning-workspace/chat/) and choose **Math Animator**.
3. Describe one transformation. Example: “Animate the derivative of sin(x²) as the chain rule, one step at a time, then hold the final expression.”
4. Wait for the video or storyboard in the thread. Play it once and check that each step matches the algebra.

If the render fails on a missing binary, install that binary and send the same request again. Do not switch generators to hide a missing tool.

## See also

- [Visualize](/multimodal-studio/visualize/) — a still figure
- [Which generator to use](/multimodal-studio/)
