"""Order MiniMax discovery without discarding account-provided model IDs."""

from __future__ import annotations


def prioritize_model_names(names: list[str], binding: str) -> list[str]:
    """Prefer current defaults and retain every model returned by discovery."""
    if binding not in {"minimax", "minimax_anthropic", "openrouter"}:
        return names
    prefix = "minimax/" if binding == "openrouter" else ""
    flash = prefix + "minimax-m3.1-flash" + (":free" if prefix else "")
    preferred = [flash, prefix + "minimax-m3"]
    return sorted(
        names, key=lambda name: preferred.index(name.lower()) if name.lower() in preferred else 2
    )
