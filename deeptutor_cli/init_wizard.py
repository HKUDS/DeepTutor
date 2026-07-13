"""Interactive setup helpers used by ``deeptutor init``.

Drives the multi-step wizard: provider menu, API-key capture (with env-var
auto-detect), live model-list fetch from ``GET {base_url}/models`` with a
curated fallback list, and an optional connectivity probe before save.

Everything that touches I/O (HTTP, env, stdin) goes through small helpers so
the orchestrator in ``init_cmd.py`` stays a thin sequence of steps.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
import time
from typing import Any

import httpx
from rich.console import Console
from rich.markup import escape as rich_escape
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
import typer

from deeptutor.services.llm.config import get_token_limit_kwargs
from deeptutor.services.provider_registry import PROVIDERS, ProviderSpec, find_by_name

# --- Featured selection ------------------------------------------------------
# Hand-picked, in display order, for the LLM step. Everything else is reachable
# via the "Show all" option. Names match ProviderSpec.name in provider_registry.

FEATURED_LLM_PROVIDERS: tuple[str, ...] = (
    "openai",
    "anthropic",
    "deepseek",
    "dashscope",
    "zhipu",
    "moonshot",
    "gemini",
    "siliconflow",
    "openrouter",
    "ollama",
)

# Fallback model lists used only when ``GET {base_url}/models`` fails or the
# provider is "custom". Live fetch is preferred — keep these short, just enough
# to unblock common cases.
LLM_FALLBACK_MODELS: dict[str, tuple[str, ...]] = {
    "openai": ("gpt-4o-mini", "gpt-4o", "o4-mini", "gpt-4.1", "gpt-4.1-mini"),
    "anthropic": (
        "claude-sonnet-4-6",
        "claude-opus-4-7",
        "claude-haiku-4-5-20251001",
    ),
    "deepseek": ("deepseek-chat", "deepseek-reasoner"),
    "dashscope": ("qwen-plus", "qwen-turbo", "qwen-max", "qwen3-coder-plus"),
    "zhipu": ("glm-4.6", "glm-4.5", "glm-4-flash"),
    "moonshot": ("kimi-k2.6", "kimi-k2.5", "kimi-latest"),
    "gemini": ("gemini-2.5-pro", "gemini-2.5-flash", "gemini-2.5-flash-lite"),
    "siliconflow": (
        "Qwen/Qwen3-Coder-480B-A35B-Instruct",
        "deepseek-ai/DeepSeek-V3",
    ),
    "openrouter": (
        "openai/gpt-4o-mini",
        "anthropic/claude-sonnet-4-6",
        "deepseek/deepseek-chat",
    ),
    "ollama": ("llama3.2", "qwen2.5", "mistral"),
}

# Featured embedding providers — display order. Source of truth for label /
# default URL / default model is ``EMBEDDING_PROVIDERS`` in
# ``deeptutor.services.config.provider_runtime``. Adding a new featured entry
# just means appending its key here.
FEATURED_EMBEDDING_PROVIDERS: tuple[str, ...] = (
    "openai",
    "gemini",
    "aliyun",  # DashScope / Qwen multimodal embeddings
    "siliconflow",
    "jina",
    "cohere",
    "openrouter",
    "azure_openai",
    "vllm",  # also covers LM Studio, llama.cpp via the same OpenAI-compatible adapter
    "ollama",
)

# Fallback model lists used only when live ``/models`` fetch fails. For
# providers where ``EmbeddingProviderSpec.default_model`` is set, that's
# preferred and these are extras.
EMBEDDING_FALLBACK_MODELS: dict[str, tuple[str, ...]] = {
    "openai": ("text-embedding-3-large", "text-embedding-3-small"),
    "gemini": ("gemini-embedding-001", "text-embedding-004"),
    "aliyun": ("qwen3-vl-embedding", "text-embedding-v3", "text-embedding-v2"),
    "siliconflow": (
        "Qwen/Qwen3-Embedding-8B",
        "BAAI/bge-m3",
        "BAAI/bge-large-en-v1.5",
    ),
    "jina": ("jina-embeddings-v3", "jina-embeddings-v2-base-en"),
    "cohere": ("embed-v4.0", "embed-multilingual-v3.0", "embed-english-v3.0"),
    "openrouter": ("openai/text-embedding-3-large",),
    "vllm": ("BAAI/bge-m3",),
    "ollama": ("nomic-embed-text", "mxbai-embed-large", "snowflake-arctic-embed"),
}


# --- Search providers ----------------------------------------------------------
# Source of truth: ``SUPPORTED_SEARCH_PROVIDERS`` in
# ``deeptutor.services.config.provider_runtime``. Each entry below describes
# how the wizard captures the credentials/config for that provider.


@dataclass(frozen=True)
class SearchProviderSpec:
    """How the init wizard handles one search provider."""

    name: str  # canonical key written into catalog.services.search.profiles[].provider
    label: str
    requires_api_key: bool
    env_keys: tuple[str, ...] = ()  # checked in order — first non-empty wins
    requires_base_url: bool = False
    default_base_url: str = ""
    hint: str = ""


SEARCH_PROVIDERS: tuple[SearchProviderSpec, ...] = (
    SearchProviderSpec(
        name="brave",
        label="Brave Search",
        requires_api_key=True,
        env_keys=("BRAVE_API_KEY", "SEARCH_API_KEY"),
        hint="independent index · paid tier",
    ),
    SearchProviderSpec(
        name="tavily",
        label="Tavily",
        requires_api_key=True,
        env_keys=("TAVILY_API_KEY", "SEARCH_API_KEY"),
        hint="LLM-friendly · free tier",
    ),
    SearchProviderSpec(
        name="jina",
        label="Jina Reader Search",
        requires_api_key=True,
        env_keys=("JINA_API_KEY", "SEARCH_API_KEY"),
        hint="returns full page content",
    ),
    SearchProviderSpec(
        name="serper",
        label="Serper",
        requires_api_key=True,
        env_keys=("SERPER_API_KEY", "SEARCH_API_KEY"),
        hint="Google results · paid",
    ),
    SearchProviderSpec(
        name="perplexity",
        label="Perplexity",
        requires_api_key=True,
        env_keys=("PERPLEXITY_API_KEY", "SEARCH_API_KEY"),
        hint="answer-style search",
    ),
    SearchProviderSpec(
        name="duckduckgo",
        label="DuckDuckGo",
        requires_api_key=False,
        hint="no API key needed",
    ),
    SearchProviderSpec(
        name="searxng",
        label="SearXNG",
        requires_api_key=False,
        requires_base_url=True,
        default_base_url="http://localhost:8888",
        hint="self-hosted · provide your instance URL",
    ),
    SearchProviderSpec(
        name="none",
        label="Disable web search",
        requires_api_key=False,
        hint="agents will skip all search tools",
    ),
)


# --- Data ----------------------------------------------------------------------


@dataclass
class LLMChoice:
    """User-confirmed LLM step result, ready to write into the catalog."""

    binding: str
    base_url: str
    api_key: str
    model: str
    display_provider: str  # human-friendly label for the review panel
    probed: bool = False
    probe_ok: bool = False
    probe_ms: int = 0


@dataclass
class EmbeddingChoice:
    binding: str
    base_url: str  # full /embeddings URL (already normalised)
    api_key: str
    model: str
    dimension: str
    display_provider: str
    probed: bool = False
    probe_ok: bool = False
    probe_ms: int = 0


@dataclass
class SearchChoice:
    """User-confirmed Search step result. ``provider == 'none'`` means
    disable web search entirely."""

    provider: str
    label: str
    api_key: str = ""
    base_url: str = ""


# --- Rendering helpers ---------------------------------------------------------


def step_header(console: Console, label: str) -> None:
    console.print()
    bar = "─" * 8
    console.print(
        f"[bright_cyan]{bar}[/bright_cyan]  [bold]{label}[/bold]  [bright_cyan]{bar}[/bright_cyan]"
    )
    console.print()


def info(console: Console, message: str) -> None:
    console.print(f"[dim]{message}[/dim]")


def ok(console: Console, message: str) -> None:
    console.print(f"[green]✓[/green] {message}")


def warn(console: Console, message: str) -> None:
    console.print(f"[yellow]![/yellow] {message}")


def fail(console: Console, message: str) -> None:
    console.print(f"[red]✗[/red] {message}")


def _mask_secret(value: str) -> str:
    """Show first 4 + last 4 chars of an API key. Empty / short → fully masked."""
    if not value:
        return "(empty)"
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:4]}...{value[-4:]}"


# --- Numbered-list picker ------------------------------------------------------


def select_from_options(
    console: Console,
    *,
    title: str,
    options: list[tuple[str, str, str]],  # [(key, label, hint), ...]
    default_key: str | None = None,
    extra_keys: dict[str, str] | None = None,
    prompt_label: str = "Choice",
    invalid_label: str = "Invalid choice. Try again.",
) -> str:
    """Render a numbered/keyed menu, return the selected key.

    ``options`` is the visible numbered list. ``extra_keys`` adds letter
    shortcuts (e.g. ``{"s": "Show all providers", "c": "Custom"}``) — these
    show up after the numbered rows and are accepted as input.
    """

    # Titles come from i18n and may contain `[c]`-style brackets that Rich
    # would otherwise interpret as markup tags.
    console.print(f"[bold]{rich_escape(title)}[/bold]")
    console.print()
    table = Table.grid(padding=(0, 1))
    table.add_column(style="bright_cyan", justify="right")
    table.add_column(style="bold")
    table.add_column(style="dim")

    # Rich Table cells parse markup, so e.g. `[s]` would be eaten as a
    # nonexistent tag. Wrap markers in Text so they render verbatim.
    def _marker(text: str) -> Text:
        return Text(text, style="bright_cyan", justify="right")

    for idx, (_key, label, hint) in enumerate(options, start=1):
        table.add_row(_marker(f"[{idx}]"), label, hint or "")
    if extra_keys:
        for short, label in extra_keys.items():
            table.add_row(_marker(f"[{short}]"), label, "")
    console.print(table)
    console.print()

    valid_numbers = {str(i): options[i - 1][0] for i in range(1, len(options) + 1)}
    valid_letters = {k.lower(): k.lower() for k in (extra_keys or {})}
    default_input: str | None = None
    if default_key is not None:
        for idx, (key, _label, _hint) in enumerate(options, start=1):
            if key == default_key:
                default_input = str(idx)
                break
        if default_input is None and default_key.lower() in valid_letters:
            default_input = default_key.lower()

    while True:
        raw = typer.prompt(prompt_label, default=default_input or "")
        choice = str(raw).strip().lower()
        if choice in valid_numbers:
            return valid_numbers[choice]
        if choice in valid_letters:
            return valid_letters[choice]
        fail(console, invalid_label)


# --- Provider selection --------------------------------------------------------


def _ordered_providers(featured: tuple[str, ...]) -> list[ProviderSpec]:
    """Return featured provider specs in the given order, dropping unknowns."""
    out: list[ProviderSpec] = []
    seen: set[str] = set()
    for name in featured:
        spec = find_by_name(name)
        if spec and spec.name not in seen:
            out.append(spec)
            seen.add(spec.name)
    return out


def _all_providers_except(featured: set[str]) -> list[ProviderSpec]:
    """All providers from the registry that aren't already in the featured list."""
    return [
        spec
        for spec in PROVIDERS
        if spec.name not in featured and not spec.is_oauth  # OAuth flows use `deeptutor login`
    ]


def select_llm_provider(
    console: Console,
    strings: dict[str, str],
    *,
    current_binding: str | None = None,
) -> ProviderSpec | None:
    """Walk the user through provider selection. ``None`` means custom/manual."""

    featured = _ordered_providers(FEATURED_LLM_PROVIDERS)
    featured_names = {spec.name for spec in featured}

    options: list[tuple[str, str, str]] = []
    for spec in featured:
        hint = spec.default_api_base or ("local" if spec.is_local else "")
        options.append((spec.name, spec.label, hint))

    # ``[s]`` is reserved for the "Skip" shortcut in optional steps
    # (embedding / search). LLM is mandatory, so we use ``[a]`` for "show all".
    extra = {
        "a": strings["init.show_all"],
        "c": strings["init.custom_provider"],
    }

    default_key = current_binding if current_binding in featured_names else "openai"
    pick = select_from_options(
        console,
        title=strings["init.pick_provider"],
        options=options,
        default_key=default_key,
        extra_keys=extra,
        prompt_label=strings["init.choice"],
        invalid_label=strings["init.choice_invalid"],
    )

    if pick == "c":
        return None
    if pick == "a":
        return _select_provider_full_list(console, strings, exclude=featured_names)
    return find_by_name(pick)


def _select_provider_full_list(
    console: Console,
    strings: dict[str, str],
    *,
    exclude: set[str],
) -> ProviderSpec | None:
    rest = _all_providers_except(exclude)
    options: list[tuple[str, str, str]] = [
        (spec.name, spec.label, spec.default_api_base or ("local" if spec.is_local else ""))
        for spec in rest
    ]
    extra = {"b": strings["init.back"], "c": strings["init.custom_provider"]}
    pick = select_from_options(
        console,
        title=strings["init.pick_provider"],
        options=options,
        extra_keys=extra,
        prompt_label=strings["init.choice"],
        invalid_label=strings["init.choice_invalid"],
    )
    if pick == "b":
        return select_llm_provider(console, strings, current_binding=None)
    if pick == "c":
        return None
    return find_by_name(pick)


SKIP_SENTINEL = "__skip__"


def select_embedding_provider(
    console: Console,
    strings: dict[str, str],
    *,
    current: str | None = None,
) -> str | None:
    """Pick an embedding provider key. Returns one of:

    - canonical provider name (e.g. ``"openai"``, ``"aliyun"``)
    - ``None`` → user wants to type their own (custom)
    - :data:`SKIP_SENTINEL` → user wants to skip this step entirely

    The featured list is driven by :data:`FEATURED_EMBEDDING_PROVIDERS`; labels
    and default endpoints come from ``EMBEDDING_PROVIDERS`` in
    ``provider_runtime`` so we don't duplicate the source of truth.
    """

    from deeptutor.services.config.provider_runtime import EMBEDDING_PROVIDERS

    options: list[tuple[str, str, str]] = []
    for name in FEATURED_EMBEDDING_PROVIDERS:
        spec = EMBEDDING_PROVIDERS.get(name)
        if not spec:
            continue
        hint = spec.default_api_base or ("local" if spec.is_local else "")
        options.append((name, spec.label, hint))

    extra = {
        "s": strings["init.skip_step"],
        "c": strings["init.custom_provider"],
    }
    default_key = current if current in {n for n, _, _ in options} else "openai"
    pick = select_from_options(
        console,
        title=strings["init.pick_embedding_provider"],
        options=options,
        default_key=default_key,
        extra_keys=extra,
        prompt_label=strings["init.choice"],
        invalid_label=strings["init.choice_invalid"],
    )
    if pick == "s":
        return SKIP_SENTINEL
    if pick == "c":
        return None
    return pick


def select_search_provider(
    console: Console,
    strings: dict[str, str],
    *,
    current: str | None = None,
) -> SearchProviderSpec | None:
    """Pick a search provider. Returns the :class:`SearchProviderSpec` for the
    chosen entry, or ``None`` when the user picks ``[s] Skip``."""

    options = [(spec.name, spec.label, spec.hint) for spec in SEARCH_PROVIDERS]
    extra = {"s": strings["init.skip_step"]}
    default_key = current if current in {s.name for s in SEARCH_PROVIDERS} else "tavily"
    pick = select_from_options(
        console,
        title=strings["init.pick_search_provider"],
        options=options,
        default_key=default_key,
        extra_keys=extra,
        prompt_label=strings["init.choice"],
        invalid_label=strings["init.choice_invalid"],
    )
    if pick == "s":
        return None
    return next((spec for spec in SEARCH_PROVIDERS if spec.name == pick), None)


def search_api_key_from_env(env_keys: tuple[str, ...]) -> tuple[str, str]:
    """Return ``(key, env_name)`` of the first non-empty env var, else ``("", "")``."""
    for env_name in env_keys:
        value = os.environ.get(env_name, "")
        if value:
            return value, env_name
    return "", ""


# --- API key capture -----------------------------------------------------------


def capture_api_key(
    console: Console,
    strings: dict[str, str],
    *,
    env_key: str,
    current: str = "",
) -> str:
    """Prompt for an API key, with env-var auto-detect + saved-value fallback.

    Preference order:
      1. Existing saved key — confirm with masked display.
      2. ``env_key`` environment variable — confirm with masked display.
      3. Plain hidden prompt.
    """
    if current:
        masked = _mask_secret(current)
        if typer.confirm(
            strings["init.api_key_reuse_llm"].format(masked=masked),
            default=True,
        ):
            return current

    if env_key:
        from_env = os.environ.get(env_key, "")
        if from_env:
            masked = _mask_secret(from_env)
            offer = strings["init.api_key_env_detected"].format(env_var=env_key, masked=masked)
            if typer.confirm(offer, default=True):
                return from_env

    return typer.prompt(
        strings["init.api_key_prompt"], default="", hide_input=True, show_default=False
    )


# --- Live /models fetch --------------------------------------------------------


def fetch_models(
    console: Console,
    strings: dict[str, str],
    *,
    base_url: str,
    api_key: str,
    binding: str,
) -> list[str]:
    """Query the provider for an available-model list.

    Returns ``[]`` on any failure — callers should fall back to the curated
    list in ``LLM_FALLBACK_MODELS`` / ``EMBEDDING_FALLBACK_MODELS``.
    """
    if not base_url:
        return []

    url = base_url.rstrip("/") + "/models"
    headers: dict[str, str] = {}

    if binding == "anthropic":
        # Anthropic uses different auth headers.
        if api_key:
            headers["x-api-key"] = api_key
        headers["anthropic-version"] = "2023-06-01"
    else:
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

    info(console, strings["init.fetch_models"].format(url=url))
    try:
        with httpx.Client(timeout=5.0) as client:
            response = client.get(url, headers=headers)
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:
        warn(console, strings["init.fetch_models_fail"].format(error=str(exc)[:160]))
        return []

    raw_items: list[Any]
    if isinstance(payload, dict) and isinstance(payload.get("data"), list):
        raw_items = payload["data"]
    elif isinstance(payload, dict) and isinstance(payload.get("models"), list):
        # Ollama: GET /api/tags returns {"models": [{"name": "...", ...}]}
        raw_items = payload["models"]
    elif isinstance(payload, list):
        raw_items = payload
    else:
        warn(console, strings["init.fetch_models_fail"].format(error="unexpected response shape"))
        return []

    names: list[str] = []
    for item in raw_items:
        if isinstance(item, str):
            names.append(item)
        elif isinstance(item, dict):
            # OpenAI: {"id": "..."}. Ollama: {"name": "..."}. Anthropic: {"id": "..."}.
            name = item.get("id") or item.get("name") or item.get("model")
            if isinstance(name, str) and name:
                names.append(name)
    # Dedupe preserving order
    seen: set[str] = set()
    deduped: list[str] = []
    for n in names:
        if n in seen:
            continue
        seen.add(n)
        deduped.append(n)
    if deduped:
        ok(console, strings["init.fetch_models_ok"].format(count=len(deduped)))
    return deduped


def _derive_embedding_models_url(endpoint: str, provider: str) -> str:
    """Convert a (full) embedding endpoint URL into its sibling ``/models`` URL.

    Embedding endpoints are stored as the *exact* URL adapters POST to
    (e.g. ``https://api.openai.com/v1/embeddings``), not a base. To list
    available models we have to strip the embedding-specific path segment.

    Ollama is special-cased: it exposes installed models at ``/api/tags``,
    not ``/models``.
    """
    url = endpoint.rstrip("/")

    if provider == "ollama" or url.endswith("/api/embed"):
        base = url
        for suffix in ("/api/embed", "/api/embeddings"):
            if base.endswith(suffix):
                base = base[: -len(suffix)]
                break
        return f"{base.rstrip('/')}/api/tags"

    for suffix in ("/embeddings", "/embed"):
        if url.endswith(suffix):
            return f"{url[: -len(suffix)]}/models"

    return f"{url}/models"


# Strict "embed" substring match. Broader heuristics (``e5-``, ``nomic``,
# ``voyage``...) drag too many LLMs in. Embedding models that don't follow
# the naming convention (``bge-m3``, ``qwen3-embedding-8b``) are picked up
# from the curated EMBEDDING_FALLBACK_MODELS list instead.
def _looks_like_embedding_model(name: str) -> bool:
    return "embed" in name.lower()


def fetch_embedding_models(
    console: Console,
    strings: dict[str, str],
    *,
    endpoint: str,
    api_key: str,
    provider: str,
) -> list[str]:
    """Live-list embedding models from the provider's ``/models`` endpoint.

    Returns ``[]`` on any failure so callers can fall back to the curated
    list. When the provider's ``/models`` includes non-embedding models
    (typical for OpenAI-compatible endpoints), the result is filtered down
    to entries whose name looks like an embedding model. If filtering
    leaves nothing, the unfiltered list is returned as a safety net.
    """
    if not endpoint:
        return []

    models_url = _derive_embedding_models_url(endpoint, provider)
    headers: dict[str, str] = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    info(console, strings["init.fetch_models"].format(url=models_url))
    try:
        with httpx.Client(timeout=5.0) as client:
            response = client.get(models_url, headers=headers)
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:
        warn(console, strings["init.fetch_models_fail"].format(error=str(exc)[:160]))
        return []

    raw_items: list[Any] = []
    if isinstance(payload, dict):
        for key in ("data", "models"):
            value = payload.get(key)
            if isinstance(value, list):
                raw_items = value
                break
    elif isinstance(payload, list):
        raw_items = payload

    names: list[str] = []
    for item in raw_items:
        if isinstance(item, str):
            names.append(item)
        elif isinstance(item, dict):
            name = item.get("id") or item.get("name") or item.get("model")
            if isinstance(name, str) and name:
                names.append(name)
    if not names:
        warn(console, strings["init.fetch_models_fail"].format(error="empty model list"))
        return []

    # Mixed lists (OpenAI returns gpt-4o, dall-e, etc. alongside embeddings).
    # Strict ``embed`` filter; if it matches nothing, return empty so the
    # caller falls through to the curated EMBEDDING_FALLBACK_MODELS list.
    filtered = [n for n in names if _looks_like_embedding_model(n)]
    if not filtered:
        return []

    seen: set[str] = set()
    deduped: list[str] = []
    for n in filtered:
        if n in seen:
            continue
        seen.add(n)
        deduped.append(n)
    ok(console, strings["init.fetch_models_ok"].format(count=len(deduped)))
    return deduped


def select_model(
    console: Console,
    strings: dict[str, str],
    *,
    models: list[str],
    current: str = "",
    custom_prompt_label: str | None = None,
) -> str:
    """Numbered-list model picker with ``[c] Custom`` escape."""
    if not models:
        return typer.prompt(
            custom_prompt_label or strings["init.custom_model"],
            default=current or "",
        )

    options = [(m, m, "") for m in models]
    extra = {"c": strings["init.custom_model"]}
    default_key = current if current in models else models[0]
    pick = select_from_options(
        console,
        title=strings["init.pick_model"].format(marker="[c]"),
        options=options,
        default_key=default_key,
        extra_keys=extra,
        prompt_label=strings["init.choice"],
        invalid_label=strings["init.choice_invalid"],
    )
    if pick == "c":
        return typer.prompt(
            custom_prompt_label or strings["init.custom_model"],
            default=current or "",
        )
    return pick


# --- Connectivity probe --------------------------------------------------------


def probe_llm(*, base_url: str, api_key: str, binding: str, model: str) -> tuple[bool, int, str]:
    """Send a single-token completion to verify credentials.

    Returns ``(ok, elapsed_ms, error_or_empty)``. Network failures, auth
    failures, 4xx, 5xx all surface as ``ok=False`` with a short error string.
    """
    if not base_url or not model:
        return False, 0, "missing base_url or model"

    started = time.monotonic()
    try:
        if binding == "anthropic":
            url = base_url.rstrip("/") + "/messages"
            headers = {
                "x-api-key": api_key or "",
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
            }
            body = {
                "model": model,
                "max_tokens": 1,
                "messages": [{"role": "user", "content": "ping"}],
            }
        else:
            url = base_url.rstrip("/") + "/chat/completions"
            headers = {
                "Authorization": f"Bearer {api_key or 'sk-no-key-required'}",
                "Content-Type": "application/json",
            }
            body = {
                "model": model,
                **get_token_limit_kwargs(model, 1),
                "messages": [{"role": "user", "content": "ping"}],
            }

        with httpx.Client(timeout=15.0) as client:
            response = client.post(url, headers=headers, json=body)
        elapsed = int((time.monotonic() - started) * 1000)
        if response.status_code >= 400:
            snippet = response.text[:200]
            return False, elapsed, f"HTTP {response.status_code} · {snippet}"
        return True, elapsed, ""
    except Exception as exc:
        elapsed = int((time.monotonic() - started) * 1000)
        return False, elapsed, str(exc)[:200]


def probe_embedding(*, base_url: str, api_key: str, model: str) -> tuple[bool, int, str]:
    """POST a tiny embedding request. Returns ``(ok, elapsed_ms, error)``."""
    if not base_url or not model:
        return False, 0, "missing base_url or model"
    started = time.monotonic()
    try:
        headers = {
            "Authorization": f"Bearer {api_key or 'sk-no-key-required'}",
            "Content-Type": "application/json",
        }
        body = {"model": model, "input": "ping"}
        with httpx.Client(timeout=15.0) as client:
            response = client.post(base_url, headers=headers, json=body)
        elapsed = int((time.monotonic() - started) * 1000)
        if response.status_code >= 400:
            return False, elapsed, f"HTTP {response.status_code} · {response.text[:200]}"
        return True, elapsed, ""
    except Exception as exc:
        elapsed = int((time.monotonic() - started) * 1000)
        return False, elapsed, str(exc)[:200]


# --- Review panel --------------------------------------------------------------


def render_review_panel(
    console: Console,
    strings: dict[str, str],
    *,
    llm: LLMChoice | None,
    embedding: EmbeddingChoice | None,
    search: SearchChoice | None,
    backend_port: int | None,
    frontend_port: int | None,
) -> None:
    body = Text()

    def _row(label: str, value: str, probe: tuple[bool, bool] | None = None) -> None:
        body.append(f"{label:>12}  ", style="bold")
        body.append(value)
        if probe is not None:
            probed, ok_flag = probe
            if probed:
                if ok_flag:
                    body.append("  ✓ probed", style="green")
                else:
                    body.append("  ! probe failed", style="yellow")
        body.append("\n")

    if llm:
        _row(
            strings["init.review_llm"],
            f"{llm.display_provider} · {llm.model} · {llm.base_url}",
            probe=(llm.probed, llm.probe_ok),
        )
    if embedding:
        _row(
            strings["init.review_embedding"],
            f"{embedding.display_provider} · {embedding.model} · {embedding.base_url}",
            probe=(embedding.probed, embedding.probe_ok),
        )
    if search:
        if search.provider == "none":
            value = strings["init.review_search_disabled"]
        elif search.base_url:
            value = f"{search.label} · {search.base_url}"
        else:
            value = search.label
        _row(strings["init.review_search"], value)
    if backend_port is not None and frontend_port is not None:
        _row(
            strings["init.review_ports"],
            strings["init.review_ports_value"].format(backend=backend_port, frontend=frontend_port),
        )
    console.print(
        Panel(
            body,
            title=f"[bold]{rich_escape(strings['init.review_title'])}[/]",
            border_style="bright_cyan",
            padding=(1, 2),
        )
    )


__all__ = [
    "EMBEDDING_FALLBACK_MODELS",
    "EmbeddingChoice",
    "FEATURED_EMBEDDING_PROVIDERS",
    "FEATURED_LLM_PROVIDERS",
    "LLMChoice",
    "LLM_FALLBACK_MODELS",
    "SEARCH_PROVIDERS",
    "SKIP_SENTINEL",
    "SearchChoice",
    "SearchProviderSpec",
    "capture_api_key",
    "fail",
    "fetch_embedding_models",
    "fetch_models",
    "info",
    "ok",
    "probe_embedding",
    "probe_llm",
    "render_review_panel",
    "search_api_key_from_env",
    "select_embedding_provider",
    "select_from_options",
    "select_llm_provider",
    "select_model",
    "select_search_provider",
    "step_header",
    "warn",
]
