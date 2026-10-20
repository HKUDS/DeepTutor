"""Current MiniMax text choices in live discovery; saved model IDs remain untouched."""

from __future__ import annotations


def active_model_names(names: list[str], binding: str) -> list[str]:
    """Prefer Flash, retain M3, and preserve unrelated/custom discovery entries.

    Only filter known MiniMax text IDs for MiniMax and OpenRouter. Do not invent
    account access by adding models missing from the endpoint's response.
    """
    if binding not in {"minimax", "minimax_anthropic", "openrouter"}:
        return names
    prefix = "minimax/" if binding == "openrouter" else ""
    flash = prefix + "minimax-m3.1-flash" + (":free" if prefix else "")
    active = [flash, prefix + "minimax-m3"]

    def keep(name: str) -> bool:
        lowered = name.lower()
        if prefix and not lowered.startswith(prefix):
            return True
        model = lowered.removeprefix(prefix)
        known_text = model == "minimax-01" or model.startswith(
            ("minimax-m", "minimax-text", "minimax-vl", "abab")
        )
        return not known_text or lowered in active

    filtered = [name for name in names if keep(name)]
    return sorted(
        filtered, key=lambda name: active.index(name.lower()) if name.lower() in active else 2
    )
