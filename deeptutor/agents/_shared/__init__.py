"""Helpers shared by capability pipelines (chat, solve, quiz, ...).

Cross-pipeline policy that doesn't belong on the generic ``core.agentic``
engine (which stays capability-agnostic) and doesn't belong on a single
pipeline either. Each module here documents the contract its consumers
must hold to.
"""
