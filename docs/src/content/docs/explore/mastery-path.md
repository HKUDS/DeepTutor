---
title: Mastery Path
description: Turn a learning goal and your own materials into a mastery map with recorded evidence, then study each waypoint with a dedicated tutor.
quadrant: how-to
---

Mastery Path turns a broad goal into a route you can actually finish. The route is divided into modules and typed knowledge points, and progress records assessed mastery or an explicit learner declaration, rather than time spent reading.

## Where it is

Open **Learning → Mastery Path** in the left sidebar (or visit `/learning/mastery`). The atlas shows this workspace’s topics, next waypoints and progress. Resources holds reusable materials; Personalization is account level.

![Mastery Path library](/screenshots/dev/mastery.png)

## Build a path

Create a **New mastery goal** in two steps:

1. **Goal** — describe the ability you want to build. The title is derived from the goal and can be renamed later.
2. **Materials** — choose Books, saved notebook/Favorites records or Knowledge Base files that should ground the learning.

Select the model for the opening conversation, then choose **Design the outline with the tutor**. Creation opens an Outline conversation: the tutor reads your materials, asks about prior knowledge and available time, and designs the map with you. Discuss changes before beginning Study. The outline is no longer a third wizard step.

Each knowledge point is typed as *memory*, *procedure*, *concept*, or *design*. That type changes what evidence counts as mastery and lets the tutor choose an appropriate learning activity.

## Study one waypoint at a time

The study surface keeps the current topic, waypoint, progress ring, outline, transcript, and composer together. Three **modes** sit above the transcript — *Outline*, *Study*, *Review* — and the live one gates the tutor's tools: only Outline may revise the map, with reviewed previews for reordering; only Study and Review may examine you. The Activity drawer and side viewer keep tools, references, and material visible. Questions arrive singly or in groups of two to four; the card ends the turn, and replies are graded independently, including partial submissions. Concept and design cards are practice; their mastery gate still requires your own explanation. The assessed **mastery gate** controls progression; a learner may explicitly mark a point mastered, with that source distinguished from assessment. Completed points return later through **spaced review** when they are due.

![Mastery Path topic and study workspace](/screenshots/dev/mastery-detail.png)

After a turn settles, the configured **Task Model** can write a suggested next question against the waypoint and recent transcript. With an empty composer, press **Tab** to accept the suggestion; it is not sent until you choose to send it.

## Conversations stay with the topic

A study session is an ordinary DeepTutor conversation bound to a Mastery Path. The sidebar files it under its topic; reopening restores the map and waypoint. In Chat, DeepTutor can offer a hand-off card to resume or start a session, and navigates only when you click.

## A concrete goal and its evidence

Instead of “Learn calculus,” try “Choose and apply substitution or integration by parts on first-year exam problems, and explain why the method works.” Add the relevant chapters or saved source records, then review the outline before studying. Ask the tutor to stay on one waypoint, attempt the exercise, and explain the result in your own words. Reading an answer alone does not demonstrate a concept or design skill.

Paths and their study conversations belong to the current workspace. Reopen the topic to resume its map and sessions; use the due-review entry to revisit older evidence. An explicit learner declaration is recorded differently from an assessed result. Keep this distinction in mind when interpreting the progress ring. Practice gives additional question-level recall; the Learning notebook preserves your own explanations.

## See also

- [Resources](/explore/space/) — the library for reusable materials and personalization
- [Immersive Reading](/explore/reading/) — turn an open collection into a new mastery path
- [Home](/explore/chat-workspace/) — the shared agent loop behind study conversations
