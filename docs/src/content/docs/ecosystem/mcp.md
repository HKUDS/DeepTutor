---
title: MCP Services
description: Connect hosted Model Context Protocol services per account, or manage deployment-wide servers through the administrator registry.
quadrant: how-to
---

MCP Services bring tools from outside DeepTutor into the same agent loop as built-in tools. Remote services connect to an individual account; deployment-managed servers are owned by an administrator.

## Browse the store

Open **Personalization → MCP Services**. **Installed** shows what your account has connected. **Store** exposes 39 hosted servers; the full 46-entry catalog also includes seven administrator-only `stdio` definitions, which are deliberately filtered out of the self-service store.

![MCP Services catalog](/screenshots/dev/mcp.png)

Cards show the category, whether a credential is required, and whether the entry is curated for this build or came from a public registry. Once connected, a service's tools become available through normal tool discovery; pickers group them under one service row instead of listing hundreds of schemas up front.

## Connect a hosted service

The flow depends on what the server requires:

| Server requires | Connection flow |
|---|---|
| **Nothing** | Connect immediately with one click. |
| **API key** | Paste it once. The server configuration stores a `${secret:…}` reference, not the token itself. |
| **OAuth** | DeepTutor runs OAuth 2.1 with PKCE and dynamic client registration, then stores the account-scoped authorization. |

Background reconnects never wait on a consent screen. When authorization expires, the service changes to **needs auth** and the UI offers a new Connect action.

## Add a service outside the store

On **Installed**, **Add a server by URL** accepts public endpoints or an administrator-approved private origin with the exact scheme, host, and port. Loopback and metadata addresses remain blocked. **Deployment registry** manages shared `mcp.json` entries.

Self-service `stdio` is refused: commands run as the application user. Administrators add these servers through the registry. The legacy `/settings/mcp` route redirects here.

## Credentials and grants

Account-scoped MCP credentials live under `data/system`, which the code sandbox never mounts. In multi-user deployments, non-admin grants whitelist individual MCP tools by name and are deny-by-default. Authorization is checked again when the tool executes, not only when its schema is advertised.

## Allow a connection in a workspace

After connecting a service, open **Settings → Workspace** and include it in the intended workspace's MCP resource selection. Return to that workspace's Home and select the service in the composer if only this conversation needs it. A conversation can narrow the workspace selection, but cannot widen it or override the user's tool grants.

This lets one account connect a reference service once and make it available in both a literature workspace and a thesis workspace, while keeping it out of an unrelated course. Files and learning materials remain workspace resources; the service's authorization remains account-level.

## Maintain and troubleshoot

Check **Installed** for connection state before debugging a chat prompt. Reconnect **needs auth** services, correct an endpoint or API-key configuration at its source, and test again. If tools are connected but absent from a turn, check the workspace selection and per-user grants before reconnecting repeatedly.

Disabling or removing a server makes its tools unavailable. Review its referenced workspaces before removing it; selecting a stale entry does not recreate a connection or supply a missing credential. For Partner use, configure the Partner's MCP tools and workspace binding explicitly rather than assuming the active Home conversation's selection carries over.

## See also

- [Skills](/ecosystem/skills/) — instruction-only workflow extensions
- [CLI Apps](/ecosystem/cli-apps/) — sandboxed command-line tools installed on the deployment
- [Multi-User Deployment](/get-started/multi-user/) — edit per-account grants

