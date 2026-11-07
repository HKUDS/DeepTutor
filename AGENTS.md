# DeepTutor LLM System (Current Behavior)

This file describes what the current LLM system does at runtime.

## What it does

- Loads active LLM configuration (API key, base URL, model, provider binding).
- Routes requests to the correct provider (cloud or local) via a unified factory.
- Supports both single-shot completion and streaming responses.
- Applies token limits and optional response formats when the provider supports them.
- Centralizes temperature and max token limits using `config/agents.yaml`.
- Logs LLM inputs/outputs and tracks token usage and timing per module.
- Maps provider errors into consistent exceptions for callers.
- Allows runtime config refresh so agents can pick up new settings without restart.
- Picks the final model by priority: agent override → global config → env defaults.
- Injects provider-specific kwargs (e.g., token limit fields) safely per model.
- Keeps a shared stats tracker per module for aggregated usage reporting.

## Scope

This repository is the **paper evaluation** variant of DeepTutor, containing only:
- Question Generation
- Question Solving
- RAG (Retrieval-Augmented Generation)
- Memory / Personalization
- Evaluation framework (`benchmark` + simulator tools)

All features are CLI-driven. There is no web frontend or HTTP API.
