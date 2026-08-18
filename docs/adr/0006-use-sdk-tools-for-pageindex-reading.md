---
status: accepted
---

# Use SDK tools for PageIndex reading

DeepTutor obtains both PageIndex Cloud and PageIndex OSS read-only tools and agent instructions from the PageIndex SDK. The tools remain turn-scoped and management operations stay outside the model-facing surface; using one SDK-owned contract avoids PageIndex-specific behavior in DeepTutor's generic MCP integration.
