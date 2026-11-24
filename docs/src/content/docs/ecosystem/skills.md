---
title: Skills
description: Add reusable SKILL.md playbooks from built-ins, local authoring, ClawHub, or the EduHub community catalog.
quadrant: how-to
---

Skills are **`SKILL.md` playbooks** the model reads on demand. They teach DeepTutor a workflow, style, or domain behavior without adding a new executable service.

## Browse and manage Skills

Open **Personalization → Skills**. Skills are tagged and searchable; built-in office skills (`docx`, `pdf`, `pptx`, `xlsx`) and presets are read-only, while your own skills can evolve with the workflow they describe.

![Skill library](/screenshots/dev/skills.png)

A useful skill says **when** to use it, what inputs it expects, the steps or constraints that matter, and what a successful output looks like. The built-in `skill-creator` helps you author that structure rather than starting from an empty file.

## Import from EduHub

Choose **Import from EduHub** to browse and download community Skills directly into your library. Imports cross a security gate before they become available. See [EduHub](/ecosystem/eduhub/) for discovery, review, safety checks, publishing, and version management.

## Install and publish from the CLI

The CLI supports other catalogs and also publishes:

```bash
deeptutor skill install clawhub:<slug>
deeptutor skill login
deeptutor skill publish <directory>
deeptutor skill update
```

`login` authorizes against a hub in the browser. `publish` uploads a skill directory, while `update` lists your published packages so you can ship a new version or roll one back.

## Create, test, and maintain a skill

1. Open **Personalization → Skills** and choose **Account shared skills** or a workspace in **Skill library**. The selected library is the write destination, independent of whichever workspace you were viewing before opening Personalization.
2. Create a skill with a specific name and description, then write the `SKILL.md` procedure. Include the inputs it needs, important constraints, and the shape of the result. Supporting files belong beside the instructions when the workflow needs them.
3. In **Settings → Workspace**, allow the skill for the workspace that should use it. In Home, use the composer's skill selection to narrow the current conversation, then test with a realistic small task.
4. Review the result and revise the instructions. Before deleting a skill, check the workspaces listed in its usage warning; remove or replace their selection so future turns can still follow the workflow.

The runtime resolves same-name skills in this order: workspace-local, account-owned, assigned administrator skill, then built-in. The workspace's allowed skill list still applies. A local override therefore specializes an enabled skill without changing every course that uses the shared version.

## How skills connect to learning

A rubric skill can guide feedback on a document held in Resources, while a revision skill guides a Home conversation about the same course. Guided Learning's study composer uses the workspace's permitted skills too. The skill supplies procedure; it does not contain the learner's progress or replace the course's source materials.

Keep reusable procedures in the account library and course-specific variations in a workspace library. When copying a skill into a Partner's private library, treat it as a snapshot; a Partner bound to that workspace reads the live workspace resources instead.

## See also

- [Personalization](/explore/personalization/) — the account shelf and workspace selection
- [EduHub](/ecosystem/eduhub/) — discover and publish community Skills
- [MCP Services](/ecosystem/mcp/) — connect tools that run outside DeepTutor
- [CLI commands](/cli/commands/) — full command reference
