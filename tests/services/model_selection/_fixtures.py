"""Shared offline fixtures for the MOD-03 model-selection/audit tests.

No real endpoint is ever touched: selections resolve against this in-memory
catalog and invocation records are persisted to a tmp LearningStore.
"""

from __future__ import annotations

from deeptutor.learning.models import LearningProgress
from deeptutor.learning.storage import LearningStore


def catalog() -> dict:
    """A two-profile LLM catalog: OpenAI Responses (active) + Anthropic."""
    return {
        "version": 1,
        "services": {
            "llm": {
                "active_profile_id": "p1",
                "active_model_id": "m1",
                "profiles": [
                    {
                        "id": "p1",
                        "name": "OpenAI Evaluator",
                        "binding": "openai",
                        "base_url": "https://api.example.com/v1",
                        "api_key": "sk-secret",
                        "api_version": "",
                        "api_protocol": "openai_responses",
                        "strict_protocol": True,
                        "extra_headers": {},
                        "models": [
                            {"id": "m1", "name": "Eval", "model": "gpt-4o-mini"},
                            {"id": "m2", "name": "Cross", "model": "gpt-5.6"},
                        ],
                    },
                    {
                        "id": "p2",
                        "name": "Anthropic Evaluator",
                        "binding": "anthropic",
                        "base_url": "https://api.anthropic.com/v1",
                        "api_key": "sk-ant-xxx",
                        "api_version": "",
                        "api_protocol": "anthropic_messages",
                        "strict_protocol": True,
                        "extra_headers": {},
                        "models": [
                            {"id": "m3", "name": "Claude", "model": "claude-3-7-sonnet"},
                        ],
                    },
                ],
            },
            "embedding": {"active_profile_id": None, "active_model_id": None, "profiles": []},
            "search": {"active_profile_id": None, "profiles": []},
        },
    }


def auto_catalog() -> dict:
    """A legacy-style catalog using ``api_protocol=auto`` (Anthropic binding)."""
    data = catalog()
    for profile in data["services"]["llm"]["profiles"]:
        profile["api_protocol"] = "auto"
        profile["strict_protocol"] = False
    return data


def progress(book_id: str = "b1") -> LearningProgress:
    return LearningProgress(book_id=book_id)


def store(tmp_path) -> LearningStore:
    return LearningStore(root=tmp_path)
