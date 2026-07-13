"""Partners — IM-connected companions driven by the DeepTutor chat agent loop.

This package hosts the channel (IM) layer: the chat-platform integrations,
the message bus that decouples them from the agent runtime, and their
configuration schema. The agent runtime itself lives in
``deeptutor.services.partners`` and reuses the chat capability's agent loop
(``ChatOrchestrator`` → ``AgenticChatPipeline``) — there is no separate
partner engine.
"""

__version__ = "2.0.0"
