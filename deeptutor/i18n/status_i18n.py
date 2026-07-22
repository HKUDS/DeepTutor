"""Shared i18n helper for capability status / UI strings.

Capability ``run()`` methods stream short status messages to the chat UI
(``stream.thinking``, ``stream.progress``, ``stream.error``). Those strings
must respect the user's locale. This helper wires them into the existing
``PromptManager`` so each capability keeps its UI copy alongside its LLM
prompts under that capability's own prompt module, e.g.
``deeptutor/agents/<module>/prompts/{en,zh}/<name>.yaml``.

Conventions:

* YAML files contain a single top-level ``status:`` mapping, key → string.
* Strings may use ``{name}`` placeholders rendered via ``str.format``.
* Missing keys / files fall back to the ``default`` argument so a new
  hardcoded string still works while its translation is being added.
"""

from __future__ import annotations

from typing import Any


class StatusI18n:
    """Per-capability localized status-string lookup.

    Construct once at the top of ``run()`` with the prompt ``module`` (the
    owning agent package, e.g. ``"question"``), the status file ``name``, and
    ``context.language``; then call ``t(key, default, **kwargs)`` wherever a
    hardcoded English string was previously emitted.
    """

    __slots__ = ("_strings",)

    def __init__(self, name: str, language: str, *, module: str) -> None:
        # Imported lazily: the prompt service pulls in services.config, which
        # would form an import cycle if loaded while the i18n package is being
        # imported during runtime bootstrap. StatusI18n is only constructed at
        # request time, so the deferral is free.
        from deeptutor.services.prompt import get_prompt_manager

        prompts = get_prompt_manager().load_prompts(
            module_name=module,
            agent_name=name,
            language=language,
        )
        raw = prompts.get("status") if isinstance(prompts, dict) else None
        self._strings: dict[str, Any] = raw if isinstance(raw, dict) else {}

    def t(self, key: str, default: str = "", /, **kwargs: Any) -> str:
        value = self._strings.get(key)
        text = value if isinstance(value, str) and value else default
        if kwargs and text:
            try:
                return text.format(**kwargs)
            except (KeyError, IndexError, ValueError):
                return text
        return text


__all__ = ["StatusI18n"]
