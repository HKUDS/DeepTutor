---
title: Workspaces
description: Organize conversations, learning records, resources, files, and instructions by subject or project.
quadrant: how-to
---

A workspace is the container for a subject or project. Choose it **before** opening Home, Learning, or Resources: those areas show the selected workspace's work. A workspace is larger than a single conversation or a reading collection.

![Switch workspaces from the sidebar](/screenshots/dev/workspace-switcher.png)

## Understand the hierarchy

| Level | What belongs here | Example |
| --- | --- | --- |
| Workspace | Conversations, learning activities, saved materials, working files, instructions and assigned resources | Probability exam preparation |
| Home | Chat, Task Board, Learning notebook; Calendar is an account-level exception | Ask a question, plan revision, write notes |
| Learning | Books, Mastery Path, Practice and Immersive Reading | Read chapter 3 and review conditional probability |
| Resources | Chat History, Favorites, Learning journal, Question Bank and Knowledge Center | Reuse an explanation or find a source |
| Account | Partners and Personalization, plus shared settings | Reuse your persona, connected agent or model configuration |

Switching workspaces changes the first three areas. Partners and Personalization travel with your account. A persona can be reused in several workspaces; a book belongs to the workspace in which it was created. Resource assignments control which Skills, MCP services and knowledge bases a workspace can use.

## Create your first workspace

1. Open the workspace name at the top of the sidebar and choose **Manage workspaces**, or open **Settings → Workspaces**.
2. Select **New workspace** and enter a meaningful name, such as `Probability — autumn exam`.
3. Optionally enter an existing folder path. Leave it empty to create storage under the configured workspace root. On a server, the path is a server folder.
4. Add **Workspace instructions** and choose **Assigned resources**. For example: “Explain in Chinese, keep mathematical notation, ask me to attempt a problem before showing the solution.”
5. Create the workspace, select it from the workspace menu, and start a chat or learning activity.

Instructions and resource changes apply to subsequent supported turns. They guide the assistant within the capability's own rules; they do not enable unavailable tools or bypass access permissions.

## Switch and resume

Use the workspace menu to select another workspace. A top-level page stays on the equivalent page in the destination. A record detail page returns to its feature's index because that record belongs to the previous workspace. Account-level pages stay available. Your browser remembers the workspace, and workspace links can explicitly name it.

If a list looks empty after switching, check the workspace name first. Creating another workspace does not copy your books, conversations or study progress into it.

## Files and generated work

Place source files in the workspace folder for the assistant to read. Generated files go into turn-specific directories beneath `outputs/`. The assistant presents files for opening or download; exporting one into another location in the content folder requires approval for that source and destination. This lets a report be generated without silently replacing your original materials.

**General** is the default content workspace for work without a custom selection. **System** contains shared Skills and sanitized configuration snapshots; private keys and tokens remain in private configuration.

## Manage an existing workspace

Settings lets you rename a custom workspace, edit its instructions and resource assignments, archive it, or restore it. **Archive** keeps existing conversations and files. **Move folder** copies and verifies the content before switching storage, keeps the workspace identity and conversation bindings, and retains the old folder as a backup. Finish running conversations before changing the storage root.

## A practical study setup

Create `Signals and systems`, add lecture files, and assign the relevant knowledge base. Ask in [Home](/learning-workspace/chat/) for a short explanation, open the source in [Immersive Reading](/learning-workspace/reading/), and create a [Mastery Path](/learning-workspace/mastery/) for the skills you need. Save useful answers to [Favorites](/learning-workspace/favorites/) and build your own synthesis in the [Learning notebook](/learning-workspace/notebook/). Return to [Practice](/learning-workspace/questions/) for daily recall. All of these remain organized under that workspace.
