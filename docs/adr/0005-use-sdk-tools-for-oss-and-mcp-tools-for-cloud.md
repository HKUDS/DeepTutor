---
status: superseded by ADR-0006
---

# Use SDK tools for PageIndex OSS and MCP tools for PageIndex Cloud

DeepTutor uses the PageIndex SDK for both knowledge-base lifecycles, but keeps the existing MCP manager as the PageIndex Cloud tool transport while adapting the SDK's in-process tools for PageIndex OSS. This preserves the working Cloud tool contract and its `mcp_pageindex_*` names, limits the migration surface, and lets OSS use its backend-specific schemas without changing general MCP behavior.
