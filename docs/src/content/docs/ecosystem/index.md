---
title: DeepTutor Ecosystem
description: Extend DeepTutor through RAG integrations, reusable Skills, remote MCP services, sandboxed CLI Apps, and EduHub.
quadrant: explanation
---

DeepTutor's built-in learning surfaces cover the everyday product. The **ecosystem** is how you add behavior and tools without changing that core: connect a retrieval engine, teach the model a workflow, connect an external service, install a command-line application, or discover community Skills.

![Personalization and reusable account resources](/screenshots/dev/personalization.png)

## Five extension paths

| Extension | What it adds | Ownership |
|---|---|---|
| [**Skills**](/ecosystem/skills/) | `SKILL.md` playbooks the model reads when a workflow calls for them | Built-in, local, ClawHub, or EduHub |
| [**MCP Services**](/ecosystem/mcp/) | Tools exposed by hosted or deployment-managed MCP servers | Per account for remote services; admin for deployment registry |
| [**CLI Apps**](/ecosystem/cli-apps/) | Installed command-line programs exposed to turns as sandboxed tools | Admin installs and grants; permitted accounts run |
| [**RAG Integration**](/ecosystem/rag-integration/) | Local, agentic, remote, or live-library retrieval behind a Knowledge Base | Deployment configuration plus per-KB choice |
| [**EduHub**](/ecosystem/eduhub/) | Community discovery, versioning, import, and publishing for Skills | Community authors publish; users review and import |

The trust boundary is different for each path. RAG integrations own retrieval, a Skill is instructions, an MCP service is a remote tool boundary, and a CLI App is code installed on the host. EduHub distributes Skills without becoming their runtime. DeepTutor therefore gives each path a different configuration, installation, credential, sandbox, and grant model.

## Where they appear in the product

Knowledge engines are selected through the **Knowledge Center**. Skills, MCP Services, and CLI Apps are managed from **Personalization**, with EduHub embedded in the Skills importer. Once enabled, tools appear to the Home agent through the same discovery flow as built-ins.

## Start with a workspace task

Keep course or project files in that workspace's **Resources**, study them through **Learning**, and use **Home** to ask for an explanation or create an output. [Personalization](/explore/personalization/) is the account shelf from which you supply personas, skills, agents, and connections. The same shelf remains available across workspace switches.

For skills and MCP services, configure the workspace's **Assigned resources** in Settings, then narrow the current conversation if needed. Workspace assignments reference the account catalog; they do not copy credentials or bypass user grants. CLI Apps have their own administrator installation and grant controls. RAG remains associated with a Knowledge Base and the materials it retrieves.

## Next

Start with [RAG Integration](/ecosystem/rag-integration/) when retrieval is the extension point. Use [Skills](/ecosystem/skills/) for repeatable workflows, [MCP Services](/ecosystem/mcp/) for account-connected online services, and [CLI Apps](/ecosystem/cli-apps/) when the job needs a real command-line program. Visit [EduHub](/ecosystem/eduhub/) to discover or publish community Skills.
