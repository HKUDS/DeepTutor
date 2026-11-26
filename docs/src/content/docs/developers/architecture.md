---
title: Architecture
description: How a turn enters DeepTutor and reaches a tool or a capability.
quadrant: explanation
---

DeepTutor has three entry points: the CLI, the WebSocket API, and the Python SDK. All three enter the turn application service. That service persists the turn, then the turn engine routes one normalized context to the selected capability. The default capability is `chat`.

```text
CLI  |  WebSocket /ws  |  Python SDK
              |
     Turn application service
              |
         Turn engine
          /        \
   Tool registry   Capability registry
```

Tools are single functions the model calls during a turn. Capabilities are multi-stage pipelines that own the turn, such as `deep_solve`, `deep_research`, and `visualize`. The registered names, stages, and CLI aliases are in the [capability reference](/developers/reference/capabilities/).

A running turn speaks the [turn protocol](/developers/reference/turn-protocol/) on `WS /ws`. HTTP routes outside that socket are indexed in the [HTTP API](/developers/reference/http-api/).

Implementation layout, tests, and module ownership stay in the repository's [architecture notes](https://github.com/HKUDS/DeepTutor/blob/dev/docs-for-dev/ARCHITECTURE.md). This site does not publish that tree.
