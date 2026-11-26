---
title: Video Lesson
description: Generate one captioned lesson that plays in the browser.
quadrant: how-to
---

**Video Lesson** (`video_lesson`) writes a short lesson, checks the render, and plays it in the browser with captions. Narration uses the Text-to-Speech provider in Settings, or Edge when that provider is not set.

A source install needs Node.js 22 or newer and npm on the machine that renders. The desktop app already includes Node.

## Generate one lesson

1. Open [Chat](/learning-workspace/chat/) and choose **Video Lesson**.
2. Ask for one idea and a length. Example: “A three-minute lesson on the sampling theorem for a first-year class. Captions on. One worked numeric example.”
3. Wait until the player appears in the thread. Play it through once.
4. If you wanted a voice and the lesson is silent, set a TTS provider under **Settings → Models & services** and generate the lesson again.

The lesson is done when you can watch it in the thread with captions that match the pictures.

## See also

- [Which generator to use](/multimodal-studio/)
- [Providers and models](/get-started/providers/) — TTS lives with the other model profiles
