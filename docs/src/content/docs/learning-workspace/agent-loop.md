---
title: How the agent loop works
description: How one chat turn plans, calls tools, reads observations, and stops.
quadrant: explanation
---

A chat turn is not one completion. The model can call a tool, read the observation, and decide whether to continue or answer. The steps to send a turn are in [Chat](/learning-workspace/chat/).

### Little Tutor — follow up on a selection

Select text in a conversation and open **Little Tutor** to start an independent, source-grounded sidebar thread. It stays nested under the source conversation and keeps its own focused context without global memory or general-purpose tools, so a close reading does not derail the main thread.


## The agent loop (how it thinks)

DeepTutor Chat runs a single agent loop, so one message can take several internal rounds before you see an answer:

1. The model reads your message and the mounted context, then either answers directly or plans a tool call.
2. If tools are needed, DeepTutor dispatches them and appends the observations (you can watch this in the Activity panel).
3. The model continues with better evidence — reading a source, querying a KB, running code, fetching a URL.
4. A final, tool-free message ends the turn.

`ask_user` is special: instead of guessing, the agent can **pause the turn**, ask you a structured clarifying question, and resume once you answer.

## Knowing how full the window is

A chip in the composer reports how much of the model's context window this turn actually used and what is filling it — prompt blocks, tool schemas, the message list. It is measured from the assembled prompt rather than re-derived afterwards, so the readout cannot drift from what was sent. Open it to see the breakdown before deciding whether to switch to a longer-context model or start a fresh session.

Long conversations also grow a rail of ticks in the transcript's left gutter, one per question you asked, for jumping back without scrolling.

## Tools — including generation

Tools come in three kinds, and the split is about who decides.

**You decide** for the experience-enhancement tools in **Settings → Tools**: `brainstorm`, `web_search`, `paper_search`, `zotero_search`, `reason`, and `geogebra_analysis` — plus `imagegen` and `videogen` once you configure the matching generation model.

**Context decides** for the rest, which mount automatically when they are useful and are locked on from the composer's point of view: `rag`, `kb_files`, `knowledge_frontier`, `read_source`, `read_memory`, `write_memory`, `read_skill`, `list_favorites`, `save_favorite`, `question_bank`, `web_fetch`, `github`, `preprint`, `research_audit`, `research_lit`, `learning_status`, `learning_update`, `ask_user`, `load_tools`, `cron`, `mastery_topics`, `mastery_sessions`, `mastery_open_session`, `mastery_new_session`, and the single code path `exec` (python, c, cpp, or shell). A capability adds its own on top: the eight reading tools, the mastery tutoring tools, `consult_subagent`, and so on. A third group answers to neither: the workspace baseline includes file tools plus `write_note` and `search_notes`, while `workspace_export` needs your approval to move a file out of `outputs/`. (Partners are the exception: a companion can be denied context-gated tools individually — see [Partners](/channels/).)

### Scheduling something for later

`cron` lets a turn schedule work instead of doing it now: **at** a time, **every** N seconds, or on a **cron expression** with a timezone. When the job is due, its message runs as a new instruction **in this same conversation** and the reply lands here — so "quiz me on this chapter every weekday at 9" is a sentence, not a setup screen. The same tool lists this conversation's jobs and cancels one. For a Partner, a due job rides back out through the IM channel the partner is connected to.

Configure an **Image Generation** (or Video Generation) model in Settings and it becomes a chat tool too — ask in plain language and the agent calls it, then previews the result inline with a downloadable file.

