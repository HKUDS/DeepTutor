---
title: CLI Apps
description: Install reviewed command-line applications once per deployment and expose each permitted app as a sandboxed tool.
quadrant: how-to
---

CLI Apps give the agent a real command-line program without giving it a general host shell. DeepTutor installs each app into its own environment, mounts it read-only into the sandbox runner, and exposes one fixed program with a model-authored argument vector.

## Browse the catalog

Open **Personalization → CLI Apps**. The store catalogs 101 tools snapshotted from the two CLI-Anything registries, including media, document, geospatial, and 3D applications.

![CLI Apps catalog](/screenshots/dev/cli-apps.png)

The catalog ships inside the package, so browsing works offline and the deployment has a stable answer to what it can install. **Include unavailable** reveals entries whose installer needs a package manager the current runtime does not provide.

| Trust label | Meaning |
|---|---|
| **Pinned** | First-party code from the reviewed CLI-Anything revision in this build. |
| **Third-party** | Another upstream at the revision recorded by the registry. |
| **Third-party, unpinned** | Another upstream at the current head of its default branch. |

## Installation is administrator-only

Installing a package runs third-party build code as the application user, so it is never a self-service account action. The registry's install string is parsed into an installation plan rather than executed as a shell command, npm install scripts are disabled, and a failed update restores the prior working environment.

Installation and assignment are separate decisions: an administrator can install an app without granting every account permission to run it.

## Running stays sandboxed

Each installed app becomes one tool named `cli_<app id>`. The model supplies an argument vector such as `['scene', 'list']`; the executable itself is fixed, so no downstream shell has to parse a command string.

Usage guides are loaded through progressive disclosure. The initial manifest carries one line per app, and the full guide reaches the model only after `load_tools` selects that app. Multi-user grants whitelist CLI Apps by app id and remain deny-by-default for non-admin accounts.

## From installation to a useful task

1. Open **Personalization → CLI Apps**, search by the task or application, and inspect availability and the upstream trust label.
2. Ask the deployment administrator to install the app when it is missing and grant your account access. A visible catalog entry alone is not a runnable tool.
3. Put the input files in the working workspace, then ask Home for a concrete transformation and output. The agent can discover the app's tool and load its guide when needed.
4. Inspect the generated files and retain the useful results with the workspace's other work. If a workflow needs a repeatable sequence, describe it in a skill rather than repeatedly pasting command recipes.

Personalization shows the reusable app catalog across workspaces. Each run still works with the current turn's sandbox and files; it does not make every host directory readable. Program availability, account grants, and a valid input file are separate requirements.

## Updates and removal

Administrators manage the installed environment and enabled state. If an update fails, DeepTutor restores the prior environment; check the install result before retrying a user task. Removing or disabling an application also affects skills that expect its tool. Keep their instructions and the installed app version aligned, and verify the resulting file with the program that will consume it.

## See also

- [MCP Services](/customize/mcp/) — connect remote tools without installing host code
- [Home](/learning-workspace/chat/) — where permitted CLI Apps become callable tools
- [Multi-User Deployment](/self-hosting/multi-user/) — grant apps to accounts

