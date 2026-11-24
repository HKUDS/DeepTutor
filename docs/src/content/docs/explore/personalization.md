---
title: Personalization
description: Manage the agents, personas, skills, connected services, CLI apps, and memory that accompany your account across workspaces.
quadrant: how-to
---

**Personalization** is your account's shelf of reusable behavior and connections. Open it from the sidebar to reach **My Agents**, **Personas**, **Skills**, **MCP Services**, **CLI Apps**, and **Memory**. Switching from a course workspace to a research workspace keeps this shelf available; each workspace decides which resources its turns may use.

![Personalization](/screenshots/dev/personalization.png)

## Account shelf and workspace context

A workspace groups the work itself: **Home** for conversations, **Learning** for study and practice, and **Resources** for materials. Personalization supplies ways of working with those materials. For example, a patient teaching persona can serve both a calculus course and a language course, while each course keeps its own files, reading progress, and learning topics.

| Keep here | Use it for | Scope to remember |
| --- | --- | --- |
| **My Agents** | Consult a connected harness or Partner; import earlier agent conversations | The connection belongs to the account; a local harness uses its configured working directory |
| **Personas** | Reuse a voice, teaching style, or response policy | Account behavior preset selected for a turn |
| **Skills** | Reuse a workflow and its supporting instructions | Account shared library or an explicitly selected workspace library |
| **MCP Services** | Authorize an external service and discover its tools | Account connection, plus any administrator-managed services you may use |
| **CLI Apps** | Run an installed command-line application through tools | Administrator installs; account grants govern use |
| **Memory** | Review retained preferences and learning experiences | Personal memory accompanies the learner; Partner relationship memory is separate |

A library entry is not automatic permission to use it everywhere. In **Settings → Workspace**, configure the workspace's allowed skills, MCP services, and knowledge bases. A conversation may narrow skills and MCP services further in its composer. These selections intersect with the signed-in user's grants; they never grant access to another account's resources. An unselected composer inherits its workspace selection. See [Settings](/explore/settings/) for configuration and [Resources](/explore/space/) for materials.

## Create and use a persona

Open **Personalization → Personas**, create a preset, and give it a name, a short description, and Markdown instructions. Describe behavior concretely: “ask for the learner's next step before revealing a solution” is more useful than “be helpful.” Save it, select it in the chat composer's persona control, and test it on a short question.

Personas change how DeepTutor responds; the selected capability still determines the task and stages. A teacher persona can guide an explanation, and a research-assistant persona can guide a literature discussion, without replacing those workflows. Edit your own preset when its style needs adjustment; delete it when it is no longer useful. Deployment presets are read-only to ordinary users. Your own persona with the same name takes precedence over the deployment preset.

A persona is also a starting point for a Partner's soul: the creation wizard can clone its content. That produces the Partner's own identity; later edits to the original persona do not silently rewrite the Partner. Use [Partners](/explore/partners/) for a persistent companion with channels and relationship memory.

## Build a reusable skill library

Open **Personalization → Skills** and check **Skill library** before creating or importing anything. **Account shared skills** can be assigned to several workspaces. Selecting a workspace creates and edits its local skills instead. An enabled workspace skill overrides a shared skill of the same name; the scope picker prevents a course-specific workflow from accidentally becoming your account-wide version.

Create a skill for a repeatable procedure, such as reviewing an essay against a rubric or turning lab notes into a report. Include its trigger, expected inputs, steps, and output requirements. Import community skills through EduHub, inspect their instructions, and test against a small real example. Keep the account version general; use a local override when a course has a different rubric. See [Skills](/ecosystem/skills/) for authoring and lifecycle details.

## Connect services and applications

Use **MCP Services** when the work depends on a remote service. Connect from the store or add a server URL, finish its API-key or OAuth flow, and confirm it is connected. Allow the service in the intended workspace and select it for the conversation when needed. If a service changes to **needs auth**, reconnect from Installed. Removing a connection makes its tools unavailable; update workspaces that reference it. Credentials stay with the account connection rather than the workspace's files.

Use **CLI Apps** for installed programs that operate on files. An administrator installs the app and grants access; the agent runs it in the sandbox. A skill may explain when and how to use that app, but importing the skill does not install the program or grant permission. See [MCP Services](/ecosystem/mcp/) and [CLI Apps](/ecosystem/cli-apps/).

## Put the pieces together

For a literature project, keep PDFs and reading notes in the project's **Resources**, read and annotate them in **Learning**, then open **Home** with the research persona and an allowed citation skill. Add a connected service for live reference lookup only when the task needs it. Outputs and conversation context remain associated with the working workspace.

For exam preparation, use a course workspace's materials and learning topics with a teaching persona. Keep a general study-planning skill in the account shelf and a course-specific marking rubric in the workspace skill library. Review remembered preferences in **Memory** if the tutoring style stops matching your needs.

For a companion available in IM, create an account-level Partner and choose whether it uses a private copied library or a live workspace binding. A connected Partner can also be consulted from Home through My Agents. Those choices control different things: where you reach the companion, which resources it sees, and which conversation it continues.

## When something is missing

Check the account library first, then the workspace selection, then the conversation selection. For a shared deployment, also check your per-user grants. A skill may be present but filtered out by the workspace; an MCP service may be selected but awaiting authorization; a CLI App may be listed but not installed, enabled, or granted. **Settings → Runtime status** helps distinguish a missing module or provider from a resource selection problem.
