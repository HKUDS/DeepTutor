"""Chat's binding of the agent loop.

The loop engine and its host live in :mod:`deeptutor.agents.loop`; this
package holds what makes a turn a *chat* turn — the prompt pack under
``prompts/`` and the capability that starts it.
"""

from .agentic_pipeline import AgenticChatPipeline

__all__ = ["AgenticChatPipeline"]
