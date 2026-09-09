"""Provider registry for DeepTutor LLM routing.

Single source of truth for provider metadata. Adding a new provider:
  1. Add a ProviderSpec to PROVIDERS below.
  Done. Env vars, config matching, status display all derive from here.

Order matters — it controls match priority and fallback. Gateways first.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from pydantic.alias_generators import to_snake


@dataclass(frozen=True)
class ProviderSpec:
    """Single provider metadata entry.

    Placeholders in env_extras values:
      {api_key}  — the user's API key
      {api_base} — api_base from config, or this spec's default_api_base
    """

    name: str
    keywords: tuple[str, ...]
    env_key: str
    display_name: str = ""

    # Which provider implementation to use:
    # "openai_compat" | "anthropic" | "azure_openai" | "openai_codex" | "github_copilot" | "codebuddy"
    backend: str = "openai_compat"

    env_extras: tuple[tuple[str, str], ...] = ()
    is_gateway: bool = False
    is_local: bool = False
    detect_by_key_prefix: str = ""
    detect_by_base_keyword: str = ""
    default_api_base: str = ""
    strip_model_prefix: bool = False
    supports_max_completion_tokens: bool = False
    supports_prompt_caching: bool = False
    supports_stream_options: bool = True
    model_overrides: tuple[tuple[str, dict[str, Any]], ...] = ()
    # Bare model-id families too short or generic for substring-based vendor
    # detection. See ``_matches_model_family`` for what a family covers.
    model_id_families: tuple[str, ...] = ()
    is_oauth: bool = False
    is_direct: bool = False
    thinking_style: str = ""
    # Substring patterns (case-insensitive) marking models whose native
    # reasoning trace should be surfaced. When the caller does not pass an
    # explicit reasoning_effort, the provider auto-injects "high" so the
    # thinking_style flag (e.g. extra_body.thinking.type=enabled) is sent.
    reasoning_model_patterns: tuple[str, ...] = ()
    # Exact model ids whose Responses API executes `web_search` server-side.
    # Exact matching is intentional: providers often expose Responses only on
    # one model even when sibling models share the same family prefix.
    native_web_search_models: tuple[str, ...] = ()
    # Endpoints a vendor exposes for a *non-default* API format, e.g. MiniMax
    # serving Anthropic Messages at ``/anthropic`` next to its OpenAI-style
    # ``/v1``. ``default_api_base`` stays the default format's endpoint.
    api_base_by_format: tuple[tuple[str, str], ...] = ()
    # Set on entries kept only so stored catalogs keep resolving: the pair is
    # the (provider, api_format) that expresses the same thing today. Pickers
    # hide these; ``binding`` values in existing files are never rewritten.
    legacy_of: tuple[str, ...] = ()

    @property
    def mode(self) -> str:
        if self.is_oauth:
            return "oauth"
        if self.is_direct:
            return "direct"
        if self.is_gateway:
            return "gateway"
        if self.is_local:
            return "local"
        return "standard"

    @property
    def auth_mode(self) -> str:
        return "oauth" if self.is_oauth else "api_key"

    @property
    def supports_wire_api_selection(self) -> bool:
        """Whether profiles may select an OpenAI wire protocol explicitly."""
        return self.backend == "openai_compat" and not self.is_oauth

    @property
    def is_legacy(self) -> bool:
        return bool(self.legacy_of)

    @property
    def api_formats(self) -> tuple[str, ...]:
        """API formats a profile on this provider may choose between.

        Empty means the format is fixed by the backend (OAuth vendors, Azure)
        and the UI has nothing to offer. Anthropic-backed vendors speak only
        Anthropic Messages. OpenAI-compatible vendors get the OpenAI pair, plus
        Anthropic Messages when the vendor is known to serve it too or when
        the endpoint is user-supplied and could be anything.
        """
        if self.is_oauth or self.backend in {"azure_openai", "openai_codex", "github_copilot"}:
            return ()
        if self.backend == "anthropic":
            return ("anthropic",)
        if self.backend != "openai_compat":
            return ()
        formats: tuple[str, ...] = OPENAI_API_FORMATS
        if self.name == "custom" or "anthropic" in dict(self.api_base_by_format):
            formats = (*formats, "anthropic")
        return formats

    @property
    def default_api_format(self) -> str:
        return "anthropic" if self.backend == "anthropic" else "auto"

    def default_api_base_for(self, api_format: str | None) -> str:
        """The vendor endpoint for *api_format*, falling back to the default one."""
        return dict(self.api_base_by_format).get(api_format or "", self.default_api_base)

    @property
    def label(self) -> str:
        return self.display_name or self.name.title()


PROVIDER_ALIASES = {
    "azure": "azure_openai",
    "azure-openai": "azure_openai",
    "azureopenai": "azure_openai",
    "google": "gemini",
    "google_genai": "gemini",
    "claude": "anthropic",
    "openai_compatible": "custom",
    "openai-compatible": "custom",
    "anthropic_compatible": "custom_anthropic",
    "anthropic-compatible": "custom_anthropic",
    "volcenginecodingplan": "volcengine_coding_plan",
    "volcengineCodingPlan": "volcengine_coding_plan",
    "bytepluscodingplan": "byteplus_coding_plan",
    "byteplusCodingPlan": "byteplus_coding_plan",
    "github-copilot": "github_copilot",
    "openai-codex": "openai_codex",
    "codebuddy-code": "codebuddy",
    "codebuddy_code": "codebuddy",
    "workbuddy": "codebuddy",
    "lm-studio": "lm_studio",
    "atlas": "atlascloud",
    "atlas_cloud": "atlascloud",
    "atlas-cloud": "atlascloud",
    "eden_ai": "edenai",
    "novita_ai": "novita",
    "orca_router": "orcarouter",
    "orca-router": "orcarouter",
}


def canonical_provider_name(name: str | None) -> str | None:
    """Normalize incoming provider names and legacy aliases."""
    if not name:
        return None
    key = name.strip()
    if not key:
        return None
    key = to_snake(key.replace("-", "_"))
    return PROVIDER_ALIASES.get(key, key)


# ---------------------------------------------------------------------------
# PROVIDERS — the registry.  Order = priority.
# ---------------------------------------------------------------------------

PROVIDERS: tuple[ProviderSpec, ...] = (
    # === Direct (user supplies everything, no auto-detection) ===============
    ProviderSpec(
        name="custom",
        keywords=(),
        env_key="",
        display_name="Custom",
        backend="openai_compat",
        is_direct=True,
    ),
    ProviderSpec(
        name="custom_anthropic",
        keywords=(),
        env_key="",
        display_name="Custom (Anthropic API)",
        backend="anthropic",
        is_direct=True,
        legacy_of=("custom", "anthropic"),
    ),
    ProviderSpec(
        name="azure_openai",
        keywords=("azure", "azure_openai"),
        env_key="",
        display_name="Azure OpenAI",
        backend="azure_openai",
        is_direct=True,
    ),
    # === Gateways (detected by api_key / api_base, route any model) ========
    ProviderSpec(
        name="openrouter",
        keywords=("openrouter",),
        env_key="OPENROUTER_API_KEY",
        display_name="OpenRouter",
        backend="openai_compat",
        is_gateway=True,
        detect_by_key_prefix="sk-or-",
        detect_by_base_keyword="openrouter",
        default_api_base="https://openrouter.ai/api/v1",
        supports_prompt_caching=True,
    ),
    ProviderSpec(
        name="orcarouter",
        keywords=("orcarouter", "orca_router", "orca router"),
        env_key="ORCAROUTER_API_KEY",
        display_name="OrcaRouter",
        backend="openai_compat",
        is_gateway=True,
        detect_by_key_prefix="sk-orca-",
        detect_by_base_keyword="orcarouter",
        default_api_base="https://api.orcarouter.ai/v1",
    ),
    ProviderSpec(
        name="edenai",
        keywords=("edenai",),
        env_key="EDENAI_API_KEY",
        display_name="Eden AI",
        backend="openai_compat",
        is_gateway=True,
        detect_by_base_keyword="edenai",
        default_api_base="https://api.edenai.run/v3",
    ),
    ProviderSpec(
        name="aihubmix",
        keywords=("aihubmix",),
        env_key="OPENAI_API_KEY",
        display_name="AiHubMix",
        backend="openai_compat",
        is_gateway=True,
        detect_by_base_keyword="aihubmix",
        default_api_base="https://aihubmix.com/v1",
        strip_model_prefix=True,
    ),
    ProviderSpec(
        name="siliconflow",
        keywords=("siliconflow",),
        env_key="OPENAI_API_KEY",
        display_name="SiliconFlow",
        backend="openai_compat",
        is_gateway=True,
        detect_by_base_keyword="siliconflow",
        default_api_base="https://api.siliconflow.cn/v1",
    ),
    ProviderSpec(
        name="novita",
        keywords=("novita", "novita-ai", "novita ai"),
        env_key="NOVITA_API_KEY",
        display_name="Novita AI",
        backend="openai_compat",
        is_gateway=True,
        detect_by_base_keyword="novita",
        default_api_base="https://api.novita.ai/openai",
    ),
    ProviderSpec(
        name="atlascloud",
        keywords=("atlascloud", "atlas-cloud", "atlas cloud"),
        env_key="ATLASCLOUD_API_KEY",
        display_name="Atlas Cloud",
        backend="openai_compat",
        is_gateway=True,
        detect_by_base_keyword="atlascloud",
        default_api_base="https://api.atlascloud.ai/v1",
    ),
    ProviderSpec(
        name="volcengine",
        keywords=("volcengine", "volces", "ark"),
        env_key="OPENAI_API_KEY",
        display_name="VolcEngine",
        backend="openai_compat",
        is_gateway=True,
        detect_by_base_keyword="volces",
        default_api_base="https://ark.cn-beijing.volces.com/api/v3",
        thinking_style="thinking_type",
    ),
    ProviderSpec(
        name="volcengine_coding_plan",
        keywords=("volcengine-plan",),
        env_key="OPENAI_API_KEY",
        display_name="VolcEngine Coding Plan",
        backend="openai_compat",
        is_gateway=True,
        default_api_base="https://ark.cn-beijing.volces.com/api/coding/v3",
        strip_model_prefix=True,
        thinking_style="thinking_type",
    ),
    ProviderSpec(
        name="byteplus",
        keywords=("byteplus",),
        env_key="OPENAI_API_KEY",
        display_name="BytePlus",
        backend="openai_compat",
        is_gateway=True,
        detect_by_base_keyword="bytepluses",
        default_api_base="https://ark.ap-southeast.bytepluses.com/api/v3",
        strip_model_prefix=True,
        thinking_style="thinking_type",
    ),
    ProviderSpec(
        name="byteplus_coding_plan",
        keywords=("byteplus-plan",),
        env_key="OPENAI_API_KEY",
        display_name="BytePlus Coding Plan",
        backend="openai_compat",
        is_gateway=True,
        default_api_base="https://ark.ap-southeast.bytepluses.com/api/coding/v3",
        strip_model_prefix=True,
        thinking_style="thinking_type",
    ),
    # === Standard providers (matched by model-name keywords) ===============
    ProviderSpec(
        name="anthropic",
        keywords=("anthropic", "claude"),
        env_key="ANTHROPIC_API_KEY",
        display_name="Anthropic",
        backend="anthropic",
        default_api_base="https://api.anthropic.com/v1",
        supports_prompt_caching=True,
    ),
    ProviderSpec(
        name="openai",
        keywords=("openai", "gpt"),
        env_key="OPENAI_API_KEY",
        display_name="OpenAI",
        backend="openai_compat",
        default_api_base="https://api.openai.com/v1",
        supports_max_completion_tokens=True,
    ),
    ProviderSpec(
        name="openai_codex",
        keywords=("openai-codex",),
        env_key="",
        display_name="OpenAI Codex",
        backend="openai_codex",
        is_oauth=True,
        default_api_base="https://chatgpt.com/backend-api",
    ),
    ProviderSpec(
        name="github_copilot",
        keywords=("github_copilot", "copilot"),
        env_key="",
        display_name="GitHub Copilot",
        backend="github_copilot",
        is_oauth=True,
        default_api_base="https://api.githubcopilot.com",
        strip_model_prefix=True,
        supports_max_completion_tokens=True,
    ),
    ProviderSpec(
        name="codebuddy",
        keywords=("codebuddy", "workbuddy"),
        env_key="CODEBUDDY_API_KEY",
        display_name="CodeBuddy/WorkBuddy",
        backend="codebuddy",
        is_oauth=True,
        strip_model_prefix=True,
        supports_stream_options=False,
    ),
    ProviderSpec(
        name="deepseek",
        keywords=("deepseek",),
        env_key="DEEPSEEK_API_KEY",
        display_name="DeepSeek",
        backend="openai_compat",
        default_api_base="https://api.deepseek.com",
        thinking_style="thinking_type",
        reasoning_model_patterns=("deepseek-v4-pro", "deepseek-reasoner"),
        native_web_search_models=("deepseek-v4-flash", "deepseek-v4-pro"),
    ),
    ProviderSpec(
        name="gemini",
        keywords=("gemini",),
        env_key="GEMINI_API_KEY",
        display_name="Gemini",
        backend="openai_compat",
        default_api_base="https://generativelanguage.googleapis.com/v1beta/openai/",
    ),
    ProviderSpec(
        name="zhipu",
        keywords=("zhipu", "glm", "zai"),
        env_key="ZAI_API_KEY",
        display_name="Zhipu AI",
        backend="openai_compat",
        env_extras=(("ZHIPUAI_API_KEY", "{api_key}"),),
        default_api_base="https://open.bigmodel.cn/api/paas/v4",
    ),
    ProviderSpec(
        name="dashscope",
        keywords=("qwen", "dashscope"),
        env_key="DASHSCOPE_API_KEY",
        display_name="DashScope",
        backend="openai_compat",
        default_api_base="https://dashscope.aliyuncs.com/compatible-mode/v1",
        thinking_style="enable_thinking",
    ),
    ProviderSpec(
        name="moonshot",
        keywords=("moonshot", "kimi"),
        env_key="MOONSHOT_API_KEY",
        display_name="Moonshot",
        backend="openai_compat",
        default_api_base="https://api.moonshot.cn/v1",
        # Kimi-branded models (k2.5, k2.6, k2.7-code, k3, …) lock temperature
        # server-side: any value other than the model's fixed default is
        # rejected with HTTP 400 ("invalid temperature: only 1 is allowed for
        # this model"). Dropping the parameter (value None) lets the API apply
        # the correct fixed value per model and per thinking/non-thinking mode —
        # Moonshot's own recommendation. The tunable moonshot-v1-* series does
        # not contain "kimi" and keeps the caller's temperature. The Kimi
        # coding endpoint (api.kimi.com/coding/v1) addresses these models by
        # bare ids ("k3", "k3-256k", ...) without the "kimi-" prefix, so
        # match the whole family too.
        model_overrides=(
            ("kimi", {"temperature": None}),
            ("^k3", {"temperature": None}),
        ),
        model_id_families=("k3",),
    ),
    # MiniMax runs two separate platforms: global (platform.minimax.io /
    # api.minimax.io) and mainland China (platform.minimaxi.com /
    # api.minimaxi.com). Keys are issued per platform and are NOT
    # interchangeable. The global endpoint is the default here; China-platform
    # users must override base_url to https://api.minimaxi.com/v1 (or
    # https://api.minimaxi.com/anthropic) *and* use a China-platform key.
    ProviderSpec(
        name="minimax",
        keywords=("minimax",),
        env_key="MINIMAX_API_KEY",
        display_name="MiniMax",
        backend="openai_compat",
        default_api_base="https://api.minimax.io/v1",
        api_base_by_format=(("anthropic", "https://api.minimax.io/anthropic"),),
        thinking_style="reasoning_split",
    ),
    ProviderSpec(
        name="minimax_anthropic",
        keywords=("minimax_anthropic",),
        env_key="MINIMAX_API_KEY",
        display_name="MiniMax (Anthropic)",
        backend="anthropic",
        default_api_base="https://api.minimax.io/anthropic",
        legacy_of=("minimax", "anthropic"),
    ),
    ProviderSpec(
        name="mistral",
        keywords=("mistral",),
        env_key="MISTRAL_API_KEY",
        display_name="Mistral",
        backend="openai_compat",
        default_api_base="https://api.mistral.ai/v1",
    ),
    ProviderSpec(
        name="stepfun",
        keywords=("stepfun", "step"),
        env_key="STEPFUN_API_KEY",
        display_name="Step Fun",
        backend="openai_compat",
        default_api_base="https://api.stepfun.com/v1",
    ),
    ProviderSpec(
        name="xiaomi_mimo",
        keywords=("xiaomi_mimo", "mimo"),
        env_key="XIAOMIMIMO_API_KEY",
        display_name="Xiaomi MIMO",
        backend="openai_compat",
        default_api_base="https://api.xiaomimimo.com/v1",
    ),
    # === Local deployment ==================================================
    ProviderSpec(
        name="vllm",
        keywords=("vllm",),
        env_key="HOSTED_VLLM_API_KEY",
        display_name="vLLM/Local",
        backend="openai_compat",
        is_local=True,
    ),
    ProviderSpec(
        name="ollama",
        keywords=("ollama", "nemotron"),
        env_key="OLLAMA_API_KEY",
        display_name="Ollama",
        backend="openai_compat",
        is_local=True,
        detect_by_base_keyword="11434",
        default_api_base="http://localhost:11434/v1",
    ),
    ProviderSpec(
        name="lm_studio",
        keywords=("lm-studio", "lmstudio", "lm_studio"),
        env_key="LM_STUDIO_API_KEY",
        display_name="LM Studio",
        backend="openai_compat",
        is_local=True,
        detect_by_base_keyword="1234",
        default_api_base="http://localhost:1234/v1",
    ),
    ProviderSpec(
        name="llama_cpp",
        keywords=("llama_cpp", "llama.cpp"),
        env_key="",
        display_name="llama.cpp",
        backend="openai_compat",
        is_local=True,
        detect_by_base_keyword="8080",
        default_api_base="http://localhost:8080/v1",
    ),
    ProviderSpec(
        name="lemonade",
        keywords=("lemonade",),
        env_key="LEMONADE_API_KEY",
        display_name="Lemonade",
        backend="openai_compat",
        is_local=True,
        detect_by_base_keyword="13305",
        default_api_base="http://localhost:13305/api/v1",
    ),
    ProviderSpec(
        name="ovms",
        keywords=("openvino", "ovms"),
        env_key="",
        display_name="OpenVINO Model Server",
        backend="openai_compat",
        is_direct=True,
        is_local=True,
        default_api_base="http://localhost:8000/v3",
    ),
    # === Auxiliary ==========================================================
    ProviderSpec(
        name="nvidia_nim",
        keywords=("nvidia_nim", "nvidia-nim", "nim"),
        env_key="NVIDIA_NIM_API_KEY",
        display_name="NVIDIA NIM",
        backend="openai_compat",
        is_gateway=True,
        detect_by_key_prefix="nvapi-",
        detect_by_base_keyword="api.nvidia.com",
        default_api_base="https://integrate.api.nvidia.com/v1",
        supports_stream_options=False,
    ),
    ProviderSpec(
        name="groq",
        keywords=("groq",),
        env_key="GROQ_API_KEY",
        display_name="Groq",
        backend="openai_compat",
        default_api_base="https://api.groq.com/openai/v1",
    ),
    ProviderSpec(
        name="qianfan",
        keywords=("qianfan", "ernie"),
        env_key="QIANFAN_API_KEY",
        display_name="Qianfan",
        backend="openai_compat",
        default_api_base="https://qianfan.baidubce.com/v2",
    ),
)


NANOBOT_LLM_PROVIDERS: tuple[str, ...] = tuple(spec.name for spec in PROVIDERS)

WireAPI = Literal["auto", "responses", "chat_completions"]
WIRE_API_VALUES: frozenset[str] = frozenset({"auto", "responses", "chat_completions"})

# The protocol a profile's endpoint speaks. This is the user-facing concept;
# ``backend`` (which SDK class talks) and ``wire_api`` (which OpenAI endpoint)
# are derived from it. ``auto`` keeps the historical heuristics: Chat
# Completions everywhere except reasoning models on api.openai.com.
ApiFormat = Literal["auto", "openai_chat", "openai_responses", "anthropic"]
API_FORMAT_VALUES: frozenset[str] = frozenset(
    {"auto", "openai_chat", "openai_responses", "anthropic"}
)
OPENAI_API_FORMATS: tuple[str, ...] = ("auto", "openai_chat", "openai_responses")
_WIRE_API_BY_FORMAT: dict[str, WireAPI] = {
    "openai_responses": "responses",
    "openai_chat": "chat_completions",
}
_FORMAT_BY_WIRE_API: dict[str, ApiFormat] = {
    "responses": "openai_responses",
    "chat_completions": "openai_chat",
}


def find_by_name(name: str | None) -> ProviderSpec | None:
    canonical = canonical_provider_name(name)
    if not canonical:
        return None
    for spec in PROVIDERS:
        if spec.name == canonical:
            return spec
    return None


def normalize_wire_api(value: Any) -> WireAPI:
    """Normalize untrusted catalog values to a supported wire protocol."""
    normalized = str(value or "auto").strip().lower()
    return normalized if normalized in WIRE_API_VALUES else "auto"  # type: ignore[return-value]


def wire_api_for_provider(
    value: Any,
    provider: ProviderSpec | str | None,
) -> WireAPI:
    """Return a protocol override only for OpenAI-compatible backends."""
    spec = find_by_name(provider) if isinstance(provider, str) else provider
    if spec is None or not spec.supports_wire_api_selection:
        return "auto"
    return normalize_wire_api(value)


def normalize_api_format(value: Any) -> ApiFormat:
    """Normalize untrusted catalog values to a known API format."""
    normalized = str(value or "auto").strip().lower()
    return normalized if normalized in API_FORMAT_VALUES else "auto"  # type: ignore[return-value]


def api_format_for_provider(
    value: Any,
    provider: ProviderSpec | str | None,
) -> ApiFormat:
    """Clamp a requested format to what *provider* can actually speak.

    A vendor with no choice (OAuth, Azure, Anthropic-only) always resolves to
    its own default, so a stray value in a hand-edited file cannot route an
    Anthropic key at an OpenAI SDK.
    """
    spec = find_by_name(provider) if isinstance(provider, str) else provider
    requested = normalize_api_format(value)
    if spec is None:
        return requested
    choices = spec.api_formats
    if not choices:
        return spec.default_api_format  # type: ignore[return-value]
    return requested if requested in choices else spec.default_api_format  # type: ignore[return-value]


def api_format_from_legacy(
    provider: ProviderSpec | str | None,
    wire_api: Any,
) -> ApiFormat:
    """Derive the format a pre-``api_format`` profile has been running with.

    Anthropic-backed bindings (including the legacy ``custom_anthropic`` /
    ``minimax_anthropic`` entries) were always Anthropic Messages; everything
    else expressed its protocol choice through ``wire_api``.
    """
    spec = find_by_name(provider) if isinstance(provider, str) else provider
    if spec is not None and spec.backend == "anthropic":
        return "anthropic"
    return _FORMAT_BY_WIRE_API.get(normalize_wire_api(wire_api), "auto")


def wire_api_from_api_format(api_format: Any) -> WireAPI:
    """The OpenAI endpoint choice an explicit format implies (``auto`` otherwise)."""
    return _WIRE_API_BY_FORMAT.get(normalize_api_format(api_format), "auto")


def effective_backend(spec: ProviderSpec | None, api_format: Any = "auto") -> str:
    """Which provider implementation serves *spec* under *api_format*.

    The only format that changes the backend is Anthropic Messages on an
    OpenAI-compatible vendor; the OpenAI formats differ in ``wire_api``, not
    in backend.
    """
    if spec is None:
        return "openai_compat"
    if api_format_for_provider(api_format, spec) == "anthropic" and spec.backend == "openai_compat":
        return "anthropic"
    return spec.backend


def find_by_model(model: str | None) -> ProviderSpec | None:
    if not model:
        return None
    model_lower = model.lower()
    model_normalized = model_lower.replace("-", "_")
    model_prefix = model_lower.split("/", 1)[0] if "/" in model_lower else ""
    normalized_prefix = model_prefix.replace("-", "_")
    standard_specs = [s for s in PROVIDERS if not s.is_gateway and not s.is_local]

    for spec in standard_specs:
        if model_prefix and normalized_prefix == spec.name:
            return spec
    for spec in standard_specs:
        if any(_matches_model_family(family, model_lower) for family in spec.model_id_families):
            return spec
    for spec in standard_specs:
        if any(
            kw in model_lower or kw.replace("-", "_") in model_normalized for kw in spec.keywords
        ):
            return spec
    return None


def _matches_model_family(family: str, model_lower: str) -> bool:
    """Whether *model_lower* is the bare id ``family`` or a variant of it.

    A vendor ships a family under one short id plus siblings distinguished by
    a dash suffix — ``k3`` alongside ``k3-256k``. Enumerating each sibling is
    how #1227 happened: ``k3`` had a rule, ``k3-256k`` shipped later, missed
    it, and got exactly the HTTP 400 the rule exists to prevent. Naming the
    family covers the siblings that do not exist yet, while a short id still
    cannot capture an unrelated one — ``sk3``, ``k30`` and ``k3x`` are all
    different models, and none of them is in this family.
    """
    return model_lower == family or model_lower.startswith(f"{family}-")


def _matching_overrides(spec: ProviderSpec, model_lower: str) -> dict[str, Any]:
    for pattern, overrides in spec.model_overrides:
        # ``^name`` is a bare model-id family; every other pattern is a
        # vendor-family substring.
        matched = (
            _matches_model_family(pattern[1:], model_lower)
            if pattern.startswith("^")
            else pattern in model_lower
        )
        if matched:
            return dict(overrides)
    return {}


def model_overrides_for(model: str | None, spec: ProviderSpec | None) -> dict[str, Any]:
    """Request-parameter overrides *model* needs, whatever route serves it.

    ``model_overrides`` are intrinsic to the model rather than to the route: a
    Kimi model rejects an explicit ``temperature`` whether the caller reached
    it through the ``moonshot`` binding, through an OpenAI-compatible router,
    or through a gateway. Resolving them from the configured binding alone
    loses them for everyone who picked a generic binding — which is the common
    case — so #938 still got HTTP 400 ``invalid temperature: only 1 is allowed
    for this model`` from ``kimi-k3`` under ``binding="openai"``, two months
    after the override itself landed.

    The configured spec is consulted first so an explicit binding always wins.
    When it says nothing about this model, the model's own vendor spec does;
    ``find_by_model`` skips gateway and local entries, so that lookup lands on
    the vendor whose API is the thing actually enforcing the limit.

    A value of ``None`` means "send this parameter as absent" — see the
    ``moonshot`` spec for why that differs from sending a fixed value.
    """
    model_lower = (model or "").strip().lower()
    if not model_lower:
        return {}

    if spec is not None:
        configured = _matching_overrides(spec, model_lower)
        if configured:
            return configured

    vendor = find_by_model(model_lower)
    if vendor is None or vendor is spec:
        return {}
    return _matching_overrides(vendor, model_lower)


def find_gateway(
    provider_name: str | None = None,
    api_key: str | None = None,
    api_base: str | None = None,
) -> ProviderSpec | None:
    spec = find_by_name(provider_name)
    if spec and (spec.is_gateway or spec.is_local):
        return spec

    for spec in PROVIDERS:
        if spec.detect_by_key_prefix and api_key and api_key.startswith(spec.detect_by_key_prefix):
            return spec
        if spec.detect_by_base_keyword and api_base and spec.detect_by_base_keyword in api_base:
            return spec
    return None


def strip_provider_prefix(model: str, spec: ProviderSpec | None) -> str:
    """Strip the provider/ prefix from a model name if applicable."""
    if not model or not spec:
        return model
    if spec.strip_model_prefix and "/" in model:
        return model.split("/", 1)[1]
    return model


__all__ = [
    "API_FORMAT_VALUES",
    "ApiFormat",
    "OPENAI_API_FORMATS",
    "ProviderSpec",
    "PROVIDERS",
    "NANOBOT_LLM_PROVIDERS",
    "PROVIDER_ALIASES",
    "WIRE_API_VALUES",
    "WireAPI",
    "api_format_for_provider",
    "api_format_from_legacy",
    "canonical_provider_name",
    "effective_backend",
    "find_by_name",
    "find_by_model",
    "find_gateway",
    "normalize_api_format",
    "normalize_wire_api",
    "strip_provider_prefix",
    "wire_api_for_provider",
    "wire_api_from_api_format",
]
