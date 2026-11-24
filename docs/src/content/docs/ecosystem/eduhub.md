---
title: EduHub
description: Discover community Skills, inspect them before installation, import them through DeepTutor's safety gate, and publish your own versions.
quadrant: how-to
---

[EduHub](https://eduhub.deeptutor.info) is DeepTutor's community distribution layer for Skills. It sits between a local `SKILL.md` library and a shared catalog: learners discover reusable workflows, authors publish versioned packages, and DeepTutor keeps installation behind an explicit review and security boundary.

## Discover from the Web UI

Open **Personalization → Skills → Import from EduHub**. The in-app catalog lets you search community Skills, inspect their description and version, open the corresponding EduHub page, and install into the library selected in Skills: account shared skills or a specific workspace. Check that scope before importing.

![Open the Skills library to import community playbooks](/screenshots/dev/skills.png)

The catalog is intentionally an import flow rather than a second runtime. Once installed, an EduHub Skill behaves like any other local Skill and is read on demand by the model.

## The installation safety gate

Before an imported package becomes available, DeepTutor:

1. checks the Hub's verdict and package metadata;
2. extracts into a controlled destination with path traversal protection;
3. rejects binaries and unsafe archive content;
4. scans for prompt self-injection patterns;
5. records the installed source and version for later updates.

This does not make every community instruction trustworthy. Read the Skill before enabling it in a sensitive workflow, just as you would review a script or dependency.

## Publish from the CLI

Authors use the CLI for authentication, publishing, updates, and rollback:

```bash
deeptutor skill login
deeptutor skill publish <directory>
deeptutor skill update
```

`login` completes authorization in the browser. `publish` uploads a Skill directory and its metadata. `update` lists packages you own so you can publish a new version or roll back to an earlier one.

## EduHub and other catalogs

EduHub is the community experience integrated into the Web UI. DeepTutor can also install from other supported Skill catalogs, such as ClawHub, through an explicit catalog prefix:

```bash
deeptutor skill install clawhub:<slug>
```

## See also

- [Skills](/ecosystem/skills/) — how Skills work after they enter DeepTutor
- [CLI commands](/cli/commands/) — full Skill command reference
- [DeepTutor Ecosystem](/ecosystem/) — compare Skills with MCP Services and CLI Apps

