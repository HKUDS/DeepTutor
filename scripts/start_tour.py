#!/usr/bin/env python
"""DeepTutor Setup Tour - simplified CLI configuration wizard."""

from __future__ import annotations

import json
import locale
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from _cli_kit import configure_text_streams

configure_text_streams()

ENV_PATH = PROJECT_ROOT / ".env"
ENV_EXAMPLE_PATH = PROJECT_ROOT / ".env.example"
INTERFACE_SETTINGS_PATH = PROJECT_ROOT / "data" / "user" / "settings" / "interface.json"
LEGACY_TOUR_CACHE_PATH = PROJECT_ROOT / "data" / "user" / "settings" / ".tour_cache.json"


def _resolve_python() -> str:
    """Return a validated path to the current Python interpreter."""
    exe = sys.executable
    if exe:
        if Path(exe).exists():
            return exe
        resolved = str(Path(exe).resolve())
        if Path(resolved).exists():
            return resolved
    for name in ("python3", "python"):
        found = shutil.which(name)
        if found:
            return found
    return exe or "python3"


_PYTHON: str = _resolve_python()


def _resolve_pip_cmd() -> tuple[list[str], list[str]]:
    """Return ``(prefix, python_args)`` for the best pip invocation.

    Prefer ``uv pip`` when uv is on PATH (uv-managed venvs may have pip
    disabled).  When using uv, also bind ``--python _PYTHON`` so packages land
    in the same interpreter that's running this script — without it ``uv pip``
    falls back to its own venv discovery (``$VIRTUAL_ENV`` / ``./.venv``) and
    may install into a different environment.

    Falls back to ``python -m pip`` (with no extra args) when uv is absent.
    """
    uv = shutil.which("uv")
    if uv:
        return [uv, "pip"], ["--python", _PYTHON]
    return [_PYTHON, "-m", "pip"], []


_PIP_CMD, _PIP_PYTHON_ARGS = _resolve_pip_cmd()

_BOOTSTRAP_PACKAGES = [
    ("yaml", "PyYAML>=6.0"),
]


def _can_import(name: str) -> bool:
    try:
        __import__(name)
        return True
    except ImportError:
        return False


def _bootstrap() -> None:
    missing = [pip for imp, pip in _BOOTSTRAP_PACKAGES if not _can_import(imp)]
    if not missing:
        return
    print(f"  Installing bootstrap dependencies: {', '.join(missing)} ...")
    cmd = [*_PIP_CMD, "install", *missing, *_PIP_PYTHON_ARGS, "-q"]
    result = subprocess.run(cmd, capture_output=True, text=True, errors="replace")
    if result.returncode != 0:
        # Surface the real pip error instead of silently exiting — without
        # this, users see only an opaque CalledProcessError traceback.
        if result.stdout:
            sys.stderr.write(result.stdout)
        if result.stderr:
            sys.stderr.write(result.stderr)
        sys.stderr.write(
            f"\n  Failed to install bootstrap dependencies: {', '.join(missing)}\n"
            f"  Try running it manually to inspect the full error:\n"
            f"    {' '.join(cmd[:-1])}\n"
        )
        raise SystemExit(1)


_bootstrap()


def _load_runtime_deps():
    from _cli_kit import (
        accent,
        banner,
        bold,
        confirm,
        countdown,
        dim,
        log_error,
        log_info,
        log_success,
        log_warn,
        select,
        spinner,
        step,
        text_input,
    )

    from deeptutor.services.config import get_env_store

    return (
        accent,
        banner,
        bold,
        confirm,
        countdown,
        dim,
        log_error,
        log_info,
        log_success,
        log_warn,
        select,
        spinner,
        step,
        text_input,
        get_env_store,
    )


(
    accent,
    banner,
    bold,
    confirm,
    countdown,
    dim,
    log_error,
    log_info,
    log_success,
    log_warn,
    select,
    spinner,
    step,
    text_input,
    get_env_store,
) = _load_runtime_deps()

# ---------------------------------------------------------------------------
# Legacy install helpers kept for compatibility and tests
# ---------------------------------------------------------------------------

PROFILE_COMMANDS: dict[str, list[str]] = {
    "cli-core": ["requirements/cli.txt"],
    "cli-rag": ["requirements/cli.txt"],
    "web-basic": ["requirements/server.txt"],
    "web-rag": ["requirements/server.txt"],
    "web-tutorbot": ["requirements/tutorbot.txt"],
    "web-matrix": ["requirements/matrix.txt"],
}

PROFILE_ALIASES: dict[str, str] = {
    "cli-rag-lite": "cli-rag",
    "cli-rag-full": "cli-rag",
    "web-rag-lite": "web-rag",
    "web-rag-full": "web-rag",
}

MATH_ANIMATOR_REQUIREMENTS = "requirements/math-animator.txt"
NODE_MIN_VERSION = (20, 9, 0)


MESSAGES: dict[str, dict[str, str]] = {
    "en": {
        "banner_line_1": "Configure DeepTutor from the terminal.",
        "banner_line_2": "We will write ports and provider settings directly into .env.",
        "env_created": "Created `.env` from `.env.example`.",
        "env_exists": "Using existing `.env` file.",
        "env_missing_template": "`.env.example` was not found. Creating an empty `.env` instead.",
        "platform": "Platform",
        "python": "Python",
        "node": "Node",
        "env_path": ".env",
        "language_step": "Choose language",
        "language_prompt": "Choose your language",
        "language_en_desc": "Run the setup wizard in English",
        "language_zh_desc": "Run the setup wizard in Chinese",
        "language_saved": "Saved interface language to `{path}`.",
        "ports_step": "Configure ports",
        "backend_port": "Backend port",
        "frontend_port": "Frontend port",
        "llm_step": "Configure LLM",
        "embedding_step": "Configure embedding",
        "search_step": "Configure search",
        "review_step": "Write configuration",
        "provider_prompt": "Choose a provider",
        "search_provider_prompt": "Choose a search provider",
        "profile_binding": "Provider / binding",
        "base_url": "Base URL",
        "api_key": "API key",
        "api_version": "API version",
        "model_id": "Model ID",
        "dimension": "Dimension",
        "send_dimensions": "Send `dimensions` parameter",
        "send_dimensions_auto": "auto",
        "send_dimensions_yes": "yes",
        "send_dimensions_no": "no",
        "search_enable": "Configure web search?",
        "search_base_url": "Search base URL",
        "search_proxy": "Search proxy",
        "keep_secret": "Press Enter to keep the existing secret value.",
        "optional": "Optional",
        "none": "None",
        "write_confirm": "Write these settings into `.env` now?",
        "write_success": "Updated `.env` successfully.",
        "no_changes": "No files changed.",
        "next_steps": "Setup complete. You can now start DeepTutor with:",
        "next_command": "python scripts/start_web.py",
        "summary_ports": "Ports",
        "summary_llm": "LLM",
        "summary_embedding": "Embedding",
        "summary_search": "Search",
        "search_disabled": "disabled",
        "tour_cache_removed": "Removed legacy setup-tour cache.",
        "interrupt": "Setup interrupted.",
        "manual_desc": "Enter a custom provider name",
        "custom_desc": "Any OpenAI-compatible endpoint",
        "local_desc": "Local model endpoint",
        "search_none_desc": "Disable web search integration",
        "search_proxy_placeholder": "http://127.0.0.1:7890",
        "searxng_default": "http://localhost:8080",
        "api_version_hint_azure": "Optional — required only for Azure OpenAI (e.g. 2024-02-15-preview)",
        "api_version_hint_generic": "Optional — leave blank unless your provider requires it",
        "search_proxy_hint": "Optional — only set if you need an HTTP/SOCKS proxy to reach the search provider",
        # -- install step --
        "install_step": "Install dependencies",
        "install_desc": "We will install Python (via uv) and Node.js dependencies for you.",
        "install_checking": "Checking environment ...",
        "install_uv_via_pip": "uv not found — installing via pip ...",
        "install_uv_pip_failed": "Failed to install uv via pip. The underlying error was:",
        "install_uv_hint": (
            "Possible fixes:\n"
            "  - Python 3.14+ may not yet have a prebuilt uv wheel; try Python 3.12 or 3.13.\n"
            "  - If you already installed uv manually, open a NEW terminal so PATH is refreshed.\n"
            "  - Slow / blocked PyPI? Try a mirror, e.g.\n"
            "      pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple\n"
            "  - Or install uv directly: https://docs.astral.sh/uv/getting-started/installation/"
        ),
        "install_uv_not_on_path": (
            "uv was installed but is not on PATH. Open a new terminal and re-run this script."
        ),
        "install_uv_ok": "uv: {version}",
        "install_python_ok": "Python: {version}",
        "install_node_ok": "Node.js: {version}",
        "install_npm_ok": "npm: {version}",
        "install_node_missing": "Node.js / npm not found.",
        "install_node_hint_brew": "Install with: brew install node",
        "install_node_hint_apt": "Install with: sudo apt install nodejs npm",
        "install_node_hint_dnf": "Install with: sudo dnf install nodejs npm",
        "install_node_hint_yum": "Install with: sudo yum install nodejs npm",
        "install_node_hint_winget": "Install with: winget install OpenJS.NodeJS",
        "install_node_hint_manual": "Download from https://nodejs.org",
        "install_node_abort": "Node.js is required for the frontend. Please install it and re-run this script.",
        "install_node_too_old": "Node.js {version} is too old. DeepTutor web requires Node.js >=20.9.0.",
        "install_profile_prompt": "Choose installation profile",
        "install_profile_web_label": "Web app (recommended)",
        "install_profile_web_desc": "CLI + API server + RAG/document parsing",
        "install_profile_tutorbot_label": "Web + TutorBot",
        "install_profile_tutorbot_desc": "Adds TutorBot engine and common channel SDKs",
        "install_profile_matrix_label": "Web + TutorBot + Matrix",
        "install_profile_matrix_desc": "Adds Matrix support without E2EE/libolm; install matrix-e2e for encrypted rooms",
        "install_math_animator": "Install Math Animator add-on?",
        "install_math_animator_hint": (
            "Optional: Manim can require LaTeX, Cairo, pkg-config, CMake, and ffmpeg."
        ),
        "install_selected": "Selected install profile: {profile}",
        "install_confirm": "Install dependencies now?",
        "install_backend": "Installing Python dependencies ...",
        "install_requirement": "Installing {requirement} ...",
        "install_backend_done": "Python dependencies installed.",
        "install_frontend": "Installing frontend dependencies (npm install) ...",
        "install_frontend_done": "Frontend dependencies installed.",
        "install_editable": "Installing DeepTutor package ...",
        "install_editable_done": "DeepTutor package installed.",
        "install_failed": "Installation failed: {error}",
        "install_skipped": "Skipped dependency installation.",
        "install_all_done": "All dependencies installed successfully.",
        "install_retry_node": "Press Enter after installing Node.js to continue, or Ctrl-C to exit.",
    },
    "zh": {
        "banner_line_1": "在命令行中完成 DeepTutor 配置。",
        "banner_line_2": "我们会把端口和提供商配置直接写入 .env。",
        "env_created": "已根据 `.env.example` 创建 `.env`。",
        "env_exists": "检测到现有 `.env` 文件。",
        "env_missing_template": "未找到 `.env.example`，将创建一个空的 `.env`。",
        "platform": "平台",
        "python": "Python",
        "node": "Node",
        "env_path": ".env",
        "language_step": "选择语言",
        "language_prompt": "选择界面语言",
        "language_en_desc": "使用英文完成配置",
        "language_zh_desc": "使用中文完成配置",
        "language_saved": "已将界面语言写入 `{path}`。",
        "ports_step": "配置端口",
        "backend_port": "后端端口",
        "frontend_port": "前端端口",
        "llm_step": "配置 LLM",
        "embedding_step": "配置 Embedding",
        "search_step": "配置 Search",
        "review_step": "写入配置",
        "provider_prompt": "选择提供商",
        "search_provider_prompt": "选择搜索提供商",
        "profile_binding": "提供商 / 绑定",
        "base_url": "Base URL",
        "api_key": "API Key",
        "api_version": "API 版本",
        "model_id": "模型 ID",
        "dimension": "维度",
        "send_dimensions": "是否发送 `dimensions` 参数",
        "send_dimensions_auto": "自动",
        "send_dimensions_yes": "是",
        "send_dimensions_no": "否",
        "search_enable": "是否配置联网搜索？",
        "search_base_url": "搜索服务 Base URL",
        "search_proxy": "搜索代理",
        "keep_secret": "直接回车即可保留当前密钥。",
        "optional": "可选",
        "none": "不配置",
        "write_confirm": "现在将这些设置写入 `.env` 吗？",
        "write_success": "已成功更新 `.env`。",
        "no_changes": "未修改任何文件。",
        "next_steps": "配置完成。你现在可以用下面的命令启动 DeepTutor：",
        "next_command": "python scripts/start_web.py",
        "summary_ports": "端口",
        "summary_llm": "LLM",
        "summary_embedding": "Embedding",
        "summary_search": "Search",
        "search_disabled": "未启用",
        "tour_cache_removed": "已移除旧版 setup-tour 缓存。",
        "interrupt": "配置已中断。",
        "manual_desc": "手动输入自定义提供商名称",
        "custom_desc": "任意兼容 OpenAI 的接口",
        "local_desc": "本地模型服务",
        "search_none_desc": "关闭联网搜索集成",
        "search_proxy_placeholder": "http://127.0.0.1:7890",
        "searxng_default": "http://localhost:8080",
        "api_version_hint_azure": "选填 — 仅 Azure OpenAI 需要（例如 2024-02-15-preview）",
        "api_version_hint_generic": "选填 — 一般留空，除非你的提供商明确要求",
        "search_proxy_hint": "选填 — 仅当你需要通过 HTTP/SOCKS 代理访问搜索服务时填写",
        # -- install step --
        "install_step": "安装依赖",
        "install_desc": "我们将通过 uv 安装 Python 依赖，并安装 Node.js 依赖。",
        "install_checking": "正在检测环境 ...",
        "install_uv_via_pip": "未检测到 uv，正在通过 pip 安装 ...",
        "install_uv_pip_failed": "通过 pip 安装 uv 失败，下方是 pip 输出的真实错误：",
        "install_uv_hint": (
            "可能的解决办法：\n"
            "  - Python 3.14+ 可能还没有预编译的 uv wheel，建议改用 Python 3.12 或 3.13。\n"
            "  - 如果你已经手动安装了 uv，请关闭并重新打开终端以刷新 PATH 后重试。\n"
            "  - PyPI 下载缓慢或被拦截？可以切换镜像源，例如：\n"
            "      pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple\n"
            "  - 也可参考官方安装方式：https://docs.astral.sh/uv/getting-started/installation/"
        ),
        "install_uv_not_on_path": (
            "uv 已安装但没有出现在 PATH 中，请新开一个终端窗口后重新运行本脚本。"
        ),
        "install_uv_ok": "uv: {version}",
        "install_python_ok": "Python: {version}",
        "install_node_ok": "Node.js: {version}",
        "install_npm_ok": "npm: {version}",
        "install_node_missing": "未检测到 Node.js / npm。",
        "install_node_hint_brew": "请运行: brew install node",
        "install_node_hint_apt": "请运行: sudo apt install nodejs npm",
        "install_node_hint_dnf": "请运行: sudo dnf install nodejs npm",
        "install_node_hint_yum": "请运行: sudo yum install nodejs npm",
        "install_node_hint_winget": "请运行: winget install OpenJS.NodeJS",
        "install_node_hint_manual": "请前往 https://nodejs.org 下载安装",
        "install_node_abort": "前端运行需要 Node.js，请安装后重新运行本脚本。",
        "install_node_too_old": "当前 Node.js {version} 版本过低。DeepTutor Web 需要 Node.js >=20.9.0。",
        "install_profile_prompt": "选择安装配置",
        "install_profile_web_label": "Web 应用（推荐）",
        "install_profile_web_desc": "CLI + API 服务 + RAG/文档解析",
        "install_profile_tutorbot_label": "Web + TutorBot",
        "install_profile_tutorbot_desc": "增加 TutorBot 引擎和常用渠道 SDK",
        "install_profile_matrix_label": "Web + TutorBot + Matrix",
        "install_profile_matrix_desc": "增加非 E2EE Matrix 支持；加密房间请另装 matrix-e2e/libolm",
        "install_math_animator": "是否安装 Math Animator 附加能力？",
        "install_math_animator_hint": "选填：Manim 可能需要 LaTeX、Cairo、pkg-config、CMake 和 ffmpeg。",
        "install_selected": "已选择安装配置：{profile}",
        "install_confirm": "现在安装依赖？",
        "install_backend": "正在安装 Python 依赖 ...",
        "install_requirement": "正在安装 {requirement} ...",
        "install_backend_done": "Python 依赖安装完成。",
        "install_frontend": "正在安装前端依赖（npm install）...",
        "install_frontend_done": "前端依赖安装完成。",
        "install_editable": "正在安装 DeepTutor 包 ...",
        "install_editable_done": "DeepTutor 包安装完成。",
        "install_failed": "安装失败：{error}",
        "install_skipped": "已跳过依赖安装。",
        "install_all_done": "所有依赖安装成功。",
        "install_retry_node": "安装好 Node.js 后按回车继续，或按 Ctrl-C 退出。",
    },
}

_LANG = "en"

LLM_MODEL_SUGGESTIONS = {
    "openai": "gpt-4o-mini",
    "anthropic": "claude-3-5-sonnet-latest",
    "deepseek": "deepseek-chat",
    "dashscope": "qwen-max",
    "gemini": "gemini-2.5-flash",
    "groq": "llama-3.3-70b-versatile",
    "zhipu": "glm-4.5",
    "moonshot": "kimi-k2-0905",
    "minimax": "MiniMax-M1",
    "minimax_anthropic": "MiniMax-M1",
    "mistral": "mistral-large-latest",
    "stepfun": "step-1-8k",
    "xiaomi_mimo": "MiMo-7B-RL",
    "qianfan": "ernie-4.0-8k",
    "openrouter": "openai/gpt-4o-mini",
    "aihubmix": "gpt-4o-mini",
    "siliconflow": "Qwen/Qwen2.5-72B-Instruct",
    "volcengine": "doubao-1-5-pro-32k-250115",
    "volcengine_coding_plan": "doubao-seed-code-1-6",
    "byteplus": "seed-1-5-pro-250115",
    "byteplus_coding_plan": "seed-coding-1-6",
    "github_copilot": "gpt-4o",
    "openai_codex": "gpt-5",
    "ollama": "qwen3:8b",
    "vllm": "Qwen/Qwen3-8B",
    "lm_studio": "qwen2.5-7b-instruct",
    "llama_cpp": "qwen2.5-7b-instruct",
    "ovms": "qwen2.5-7b-instruct",
}

EMBEDDING_MODEL_SUGGESTIONS = {
    "openai": "text-embedding-3-large",
    "gemini": "gemini-embedding-001",
    "cohere": "embed-v4.0",
    "jina": "jina-embeddings-v3",
    "ollama": "nomic-embed-text",
}

SEARCH_PROVIDERS = (
    ("none", "None", "Disable web search integration"),
    ("brave", "Brave", "API key required"),
    ("tavily", "Tavily", "API key required"),
    ("jina", "Jina", "API key required"),
    ("searxng", "SearXNG", "Self-hosted or public instance"),
    ("duckduckgo", "DuckDuckGo", "No API key required"),
    ("perplexity", "Perplexity", "API key required"),
    ("serper", "Serper", "API key required"),
)


# ---------------------------------------------------------------------------
# Compatibility helpers
# ---------------------------------------------------------------------------


def _node_strategy() -> str:
    if shutil.which("node") and shutil.which("npm"):
        return "installed"
    system = platform.system().lower()
    if system == "darwin":
        return "brew"
    if system == "windows":
        return "winget"
    for pm in ("apt", "dnf", "yum"):
        if shutil.which(pm):
            return pm
    return "manual"


def _get_npm_command() -> str:
    if platform.system().lower() == "windows":
        return "npm.cmd"
    npm = shutil.which("npm")
    if npm:
        return npm
    return "npm"


def _install_commands(
    profile: str,
    catalog: dict[str, Any],
    *,
    include_math_animator: bool = False,
) -> list[tuple[list[str], Path]]:
    del catalog
    profile = PROFILE_ALIASES.get(profile, profile)
    if profile not in PROFILE_COMMANDS:
        raise ValueError(f"Unknown install profile: {profile}")

    cmds: list[tuple[list[str], Path]] = []
    for req in PROFILE_COMMANDS[profile]:
        cmds.append(([*_PIP_CMD, "install", "-r", req, *_PIP_PYTHON_ARGS], PROJECT_ROOT))
    if include_math_animator:
        cmds.append(
            (
                [*_PIP_CMD, "install", "-r", MATH_ANIMATOR_REQUIREMENTS, *_PIP_PYTHON_ARGS],
                PROJECT_ROOT,
            )
        )
    cmds.append(([*_PIP_CMD, "install", "-e", ".", "--no-deps", *_PIP_PYTHON_ARGS], PROJECT_ROOT))
    if profile.startswith("web"):
        cmds.append(([_get_npm_command(), "install"], PROJECT_ROOT / "web"))
    return cmds


def _requirements_for_install(profile: str, *, include_math_animator: bool = False) -> list[str]:
    profile = PROFILE_ALIASES.get(profile, profile)
    if profile not in PROFILE_COMMANDS:
        raise ValueError(f"Unknown install profile: {profile}")
    requirements = list(PROFILE_COMMANDS[profile])
    if include_math_animator:
        requirements.append(MATH_ANIMATOR_REQUIREMENTS)
    return requirements


def _run_cmd(cmd: list[str], cwd: Path) -> None:
    log_info(f"{dim(str(cwd))}  {' '.join(cmd)}")
    use_shell = platform.system().lower() == "windows"
    result = subprocess.run(cmd, cwd=str(cwd), check=False, shell=use_shell)
    if result.returncode != 0:
        raise RuntimeError(f"Command failed (exit {result.returncode}): {' '.join(cmd)}")


def _stream_text_kwargs() -> dict[str, object]:
    """Best-effort text decoding for subprocess output."""
    encoding = locale.getpreferredencoding(False) or "utf-8"
    return {
        "stdout": subprocess.PIPE,
        "stderr": subprocess.STDOUT,
        "text": True,
        "encoding": encoding,
        "errors": "replace",
        "bufsize": 1,
    }


# ---------------------------------------------------------------------------
# Localized prompt helpers
# ---------------------------------------------------------------------------


def _set_language(language: str) -> None:
    global _LANG
    _LANG = "zh" if str(language).strip().lower().startswith("zh") else "en"


def _t(key: str, **kwargs: Any) -> str:
    template = MESSAGES[_LANG].get(key, MESSAGES["en"].get(key, key))
    return template.format(**kwargs)


def _secret_mask(value: str) -> str:
    if not value:
        return "-"
    if len(value) <= 8:
        return "****"
    return f"{value[:4]}...{value[-4:]}"


def _save_ui_language(language: str, path: Path = INTERFACE_SETTINGS_PATH) -> None:
    payload: dict[str, Any] = {"theme": "light", "language": language}
    if path.exists():
        try:
            payload.update(json.loads(path.read_text(encoding="utf-8")) or {})
        except Exception:
            pass
    payload["language"] = "zh" if language == "zh" else "en"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _ensure_env_file(env_path: Path = ENV_PATH, template_path: Path = ENV_EXAMPLE_PATH) -> bool:
    if env_path.exists():
        return False
    env_path.parent.mkdir(parents=True, exist_ok=True)
    if template_path.exists():
        shutil.copyfile(template_path, env_path)
        return True
    env_path.write_text("", encoding="utf-8")
    return True


def _cleanup_legacy_tour_cache(path: Path = LEGACY_TOUR_CACHE_PATH) -> bool:
    if not path.exists():
        return False
    path.unlink(missing_ok=True)
    return True


def _prompt_int(prompt: str, default: int) -> int:
    while True:
        value = text_input(prompt, str(default)).strip()
        try:
            return int(value)
        except ValueError:
            log_warn(f"{prompt}: {value!r} is not a valid integer.")


def _prompt_secret(prompt: str, default: str) -> str:
    if default:
        log_info(dim(_t("keep_secret")))
    return text_input(prompt, default, secret=True)


def _enum_options(
    options: list[tuple[str, str, str]], current: str | None = None
) -> list[tuple[str, str, str]]:
    normalized_current = str(current or "").strip()
    if not normalized_current:
        return options
    seen = {value for value, _, _ in options}
    if normalized_current in seen:
        return options
    current_label = normalized_current
    current_desc = "current value" if _LANG == "en" else "当前值"
    return [(normalized_current, current_label, current_desc)] + options


def _load_provider_metadata():
    from deeptutor.services.config.provider_runtime import EMBEDDING_PROVIDERS
    from deeptutor.services.provider_registry import PROVIDERS, find_by_name

    return EMBEDDING_PROVIDERS, find_by_name, PROVIDERS


# Order in which provider modes are listed in the wizard.
_LLM_MODE_ORDER = {
    "standard": 0,
    "gateway": 1,
    "local": 2,
    "oauth": 3,
    "direct": 4,
}

# Featured providers appear first within their mode group.
_LLM_FEATURED_ORDER = (
    "openai",
    "anthropic",
    "deepseek",
    "gemini",
    "dashscope",
    "zhipu",
    "moonshot",
    "minimax",
    "groq",
    "openrouter",
    "siliconflow",
    "volcengine",
    "byteplus",
    "ollama",
    "lm_studio",
    "vllm",
    "llama_cpp",
    "azure_openai",
    "custom",
    "custom_anthropic",
)


def _llm_provider_options(current: str | None) -> list[tuple[str, str, str]]:
    _, _, providers = _load_provider_metadata()
    featured_index = {name: i for i, name in enumerate(_LLM_FEATURED_ORDER)}

    def sort_key(spec) -> tuple[int, int, str]:
        return (
            _LLM_MODE_ORDER.get(spec.mode, 99),
            featured_index.get(spec.name, 1000),
            spec.label.lower(),
        )

    options: list[tuple[str, str, str]] = []
    for spec in sorted(providers, key=sort_key):
        if spec.name == "custom":
            desc = _t("custom_desc")
        elif spec.name == "custom_anthropic":
            desc = "Anthropic-compatible custom endpoint"
        elif spec.is_local:
            desc = _t("local_desc")
        elif spec.is_oauth:
            desc = "OAuth login required"
        else:
            desc = spec.default_api_base or ""
        options.append((spec.name, spec.label, desc))
    return _enum_options(options, current)


def _embedding_provider_options(current: str | None) -> list[tuple[str, str, str]]:
    embedding_providers, _, _ = _load_provider_metadata()
    common = ["openai", "gemini", "jina", "cohere", "ollama", "vllm", "azure_openai", "custom"]
    options: list[tuple[str, str, str]] = []
    for name in common:
        spec = embedding_providers.get(name)
        label = spec.label if spec else name
        if name == "custom":
            desc = _t("custom_desc")
        elif spec and spec.is_local:
            desc = _t("local_desc")
        else:
            desc = spec.default_api_base if spec and spec.default_api_base else ""
        options.append((name, label, desc))
    return _enum_options(options, current)


def _search_provider_options(current: str | None) -> list[tuple[str, str, str]]:
    options = [
        (value, label, _t("search_none_desc") if value == "none" else desc)
        for value, label, desc in SEARCH_PROVIDERS
    ]
    return _enum_options(options, current)


def _default_base_url(
    binding: str, current_binding: str, current_value: str, fallback: str = ""
) -> str:
    if current_value and binding == current_binding:
        return current_value
    embedding_providers, find_by_name, _ = _load_provider_metadata()
    if binding in embedding_providers:
        return embedding_providers[binding].default_api_base or fallback
    spec = find_by_name(binding)
    if spec and spec.default_api_base:
        return spec.default_api_base
    return fallback


def _default_llm_model(binding: str, current_binding: str, current_model: str) -> str:
    if current_model and binding == current_binding:
        return current_model
    return LLM_MODEL_SUGGESTIONS.get(binding, current_model)


def _default_embedding_model(binding: str, current_binding: str, current_model: str) -> str:
    if current_model and binding == current_binding:
        return current_model
    embedding_providers, _, _ = _load_provider_metadata()
    spec = embedding_providers.get(binding)
    if spec and spec.default_model:
        return spec.default_model
    return EMBEDDING_MODEL_SUGGESTIONS.get(binding, current_model)


def _default_embedding_dimension(binding: str, current_binding: str, current_value: str) -> str:
    if current_value and binding == current_binding:
        return current_value
    embedding_providers, _, _ = _load_provider_metadata()
    spec = embedding_providers.get(binding)
    if spec and spec.default_dim:
        return str(spec.default_dim)
    return current_value or "3072"


def _send_dimensions_choice(current_value: str) -> str:
    normalized = str(current_value or "").strip().lower()
    if normalized in {"true", "1", "yes", "on"}:
        default = "true"
    elif normalized in {"false", "0", "no", "off"}:
        default = "false"
    else:
        default = "auto"
    return (
        select(
            _t("send_dimensions"),
            [
                ("auto", _t("send_dimensions_auto"), ""),
                ("true", _t("send_dimensions_yes"), ""),
                ("false", _t("send_dimensions_no"), ""),
            ],
        )
        or default
    )


def _install_profile_options() -> list[tuple[str, str, str]]:
    return [
        (
            "web-basic",
            _t("install_profile_web_label"),
            _t("install_profile_web_desc"),
        ),
        (
            "web-tutorbot",
            _t("install_profile_tutorbot_label"),
            _t("install_profile_tutorbot_desc"),
        ),
        (
            "web-matrix",
            _t("install_profile_matrix_label"),
            _t("install_profile_matrix_desc"),
        ),
    ]


def _install_profile_label(profile: str) -> str:
    for value, label, _desc in _install_profile_options():
        if value == profile:
            return label
    return profile


def _select_install_profile() -> str:
    profile = select(_t("install_profile_prompt"), _install_profile_options())
    log_info(_t("install_selected", profile=_install_profile_label(profile)))
    return profile


def _select_math_animator() -> bool:
    log_info(dim(_t("install_math_animator_hint")))
    return confirm(_t("install_math_animator"), default=False)


def _parse_version_tuple(version: str | None) -> tuple[int, int, int] | None:
    if not version:
        return None
    token = version.strip().split()[0].lstrip("v")
    parts: list[int] = []
    for raw_part in token.split(".")[:3]:
        digits = ""
        for char in raw_part:
            if char.isdigit():
                digits += char
            else:
                break
        if not digits:
            return None
        parts.append(int(digits))
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts[:3])


def _node_version_supported(version: str | None) -> bool:
    parsed = _parse_version_tuple(version)
    return parsed is None or parsed >= NODE_MIN_VERSION


# ---------------------------------------------------------------------------
# Wizard steps
# ---------------------------------------------------------------------------

_TOTAL_STEPS = 7


def _get_version(cmd: list[str]) -> str | None:
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=10,
            errors="replace",
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return None


def _detect_command_version(name: str) -> str | None:
    """Resolve ``name`` via ``shutil.which`` then probe ``--version``.

    Why: on Windows, ``node`` resolves to ``node.exe`` and ``npm`` to
    ``npm.cmd``. ``subprocess.run`` with a bare name (no ``shell=True``)
    handles the former unevenly across Python versions and outright rejects
    ``.cmd``/``.bat`` files since the CVE-2024-4030 hardening in 3.12. Using
    the absolute path returned by ``shutil.which`` (which already respects
    ``PATHEXT``) sidesteps both pitfalls and matches how ``_node_strategy``
    detects the same tools.
    """
    exe = shutil.which(name)
    if not exe:
        return None
    return _get_version([exe, "--version"])


def _find_uv_in_known_locations() -> str | None:
    """Look for uv in well-known install locations even if not on PATH.

    Helps when the user just ran the standalone installer (or ``pip install
    --user uv``) and hasn't reopened their shell to refresh PATH — without
    this, we'd needlessly try to install uv again.
    """
    home = Path.home()
    if platform.system().lower() == "windows":
        candidates = [
            home / ".local" / "bin" / "uv.exe",
            home / ".cargo" / "bin" / "uv.exe",
        ]
    else:
        candidates = [
            home / ".local" / "bin" / "uv",
            home / ".cargo" / "bin" / "uv",
            Path("/opt/homebrew/bin/uv"),
            Path("/usr/local/bin/uv"),
        ]
    for path in candidates:
        if path.is_file():
            return str(path)
    return None


def _resolve_uv() -> str:
    """Return path to uv, installing it via pip if necessary.

    NOTE: kept on ``python -m pip`` intentionally — if ``shutil.which("uv")``
    returned None we cannot bootstrap uv with itself, and a pip-less venv
    would have already failed in ``_bootstrap()`` above.
    """
    found = shutil.which("uv") or _find_uv_in_known_locations()
    if found:
        return found
    log_info(dim(_t("install_uv_via_pip")))
    cmd = [_PYTHON, "-m", "pip", "install", "uv", "--disable-pip-version-check"]
    result = subprocess.run(cmd, capture_output=True, text=True, errors="replace")
    if result.returncode != 0:
        log_error(_t("install_uv_pip_failed"))
        # Replay pip's real output so the user can see *why* it failed
        # (no wheel for this Python, network/proxy, SSL, etc.).
        if result.stdout:
            sys.stderr.write(result.stdout)
            if not result.stdout.endswith("\n"):
                sys.stderr.write("\n")
        if result.stderr:
            sys.stderr.write(result.stderr)
            if not result.stderr.endswith("\n"):
                sys.stderr.write("\n")
        log_warn(_t("install_uv_hint"))
        raise SystemExit(1)
    found = shutil.which("uv") or _find_uv_in_known_locations()
    if found:
        return found
    # pip reported success but uv is nowhere we recognize — its Scripts/bin
    # dir is not on PATH. Reopening the shell almost always fixes this.
    log_error(_t("install_uv_not_on_path"))
    raise SystemExit(1)


_UV: str | None = None


def _uv() -> str:
    global _UV
    if _UV is None:
        _UV = _resolve_uv()
    return _UV


def _run_live(cmd: list[str], cwd: Path, label: str) -> None:
    """Run a command, inheriting the parent's TTY so progress bars display
    correctly (uv / npm / pip all detect TTY via stdout)."""
    log_info(label)
    log_info(dim(f"  {' '.join(cmd)}"))
    print()
    use_shell = platform.system().lower() == "windows"

    env = os.environ.copy()
    env.setdefault("FORCE_COLOR", "1")
    env.setdefault("CLICOLOR_FORCE", "1")
    env.setdefault("PY_COLORS", "1")
    env["PYTHONIOENCODING"] = "utf-8:replace"

    sys.stdout.flush()
    sys.stderr.flush()

    result = subprocess.run(
        cmd,
        cwd=str(cwd),
        check=False,
        shell=use_shell,
        env=env,
    )
    print()
    if result.returncode != 0:
        raise RuntimeError(f"Command failed (exit {result.returncode}): {' '.join(cmd)}")


def _install_dependencies() -> None:
    step(2, _TOTAL_STEPS, _t("install_step"))
    log_info(_t("install_desc"))
    print()

    # --- detect Python ---
    py_version = _get_version([_PYTHON, "--version"])
    log_success(_t("install_python_ok", version=py_version or "unknown"))

    # --- detect / install uv ---
    uv = _uv()
    uv_version = _get_version([uv, "--version"])
    log_success(_t("install_uv_ok", version=uv_version or "unknown"))

    # --- detect Node.js / npm ---
    node_version = _detect_command_version("node")
    npm_version = _detect_command_version("npm")

    if node_version and npm_version and _node_version_supported(node_version):
        log_success(_t("install_node_ok", version=node_version))
        log_success(_t("install_npm_ok", version=npm_version))
    else:
        if node_version and not _node_version_supported(node_version):
            log_warn(_t("install_node_too_old", version=node_version))
        else:
            log_warn(_t("install_node_missing"))
        strategy = _node_strategy()
        hint_key = f"install_node_hint_{strategy}"
        if hint_key in MESSAGES[_LANG]:
            log_info(_t(hint_key))
        else:
            log_info(_t("install_node_hint_manual"))
        print()
        try:
            input(f"  {_t('install_retry_node')}")
        except EOFError:
            pass
        node_version = _detect_command_version("node")
        npm_version = _detect_command_version("npm")
        if not (node_version and npm_version):
            log_error(_t("install_node_abort"))
            raise SystemExit(1)
        if not _node_version_supported(node_version):
            log_error(_t("install_node_too_old", version=node_version))
            raise SystemExit(1)
        log_success(_t("install_node_ok", version=node_version))
        log_success(_t("install_npm_ok", version=npm_version))

    print()

    profile = _select_install_profile()
    include_math_animator = _select_math_animator()
    print()

    if not confirm(_t("install_confirm"), default=True):
        log_warn(_t("install_skipped"))
        print()
        return

    print()

    uv = _uv()

    # --- uv pip install -r requirements/*.txt ---
    try:
        for requirement in _requirements_for_install(
            profile,
            include_math_animator=include_math_animator,
        ):
            _run_live(
                [uv, "pip", "install", "-r", requirement, "--python", _PYTHON],
                PROJECT_ROOT,
                _t("install_requirement", requirement=requirement),
            )
        log_success(_t("install_backend_done"))
    except RuntimeError as exc:
        log_error(_t("install_failed", error=str(exc)))
        raise SystemExit(1)

    # --- uv pip install -e . --no-deps ---
    try:
        _run_live(
            [uv, "pip", "install", "-e", ".", "--no-deps", "--python", _PYTHON],
            PROJECT_ROOT,
            _t("install_editable"),
        )
        log_success(_t("install_editable_done"))
    except RuntimeError as exc:
        log_error(_t("install_failed", error=str(exc)))
        raise SystemExit(1)

    # --- npm install ---
    try:
        npm_cmd = _get_npm_command()
        _run_live(
            [npm_cmd, "install"],
            PROJECT_ROOT / "web",
            _t("install_frontend"),
        )
        log_success(_t("install_frontend_done"))
    except RuntimeError as exc:
        log_error(_t("install_failed", error=str(exc)))
        raise SystemExit(1)

    print()
    log_success(_t("install_all_done"))
    print()


def _choose_language() -> str:
    step(1, _TOTAL_STEPS, "Language")
    language = select(
        "Choose language / 选择语言",
        [
            ("en", "English", "Run the setup wizard in English"),
            ("zh", "中文", "使用中文完成配置"),
        ],
    )
    _set_language(language)
    _save_ui_language(language)
    log_success(_t("language_saved", path=INTERFACE_SETTINGS_PATH.relative_to(PROJECT_ROOT)))
    print()
    return language


def _configure_ports() -> dict[str, str]:
    step(3, _TOTAL_STEPS, _t("ports_step"))
    summary = get_env_store().as_summary()
    backend_port = _prompt_int(_t("backend_port"), summary.backend_port)
    frontend_port = _prompt_int(_t("frontend_port"), summary.frontend_port)
    print()
    return {
        "BACKEND_PORT": str(backend_port),
        "FRONTEND_PORT": str(frontend_port),
    }


def _configure_llm() -> dict[str, str]:
    step(4, _TOTAL_STEPS, _t("llm_step"))
    summary = get_env_store().as_summary()
    current_binding = summary.llm["binding"] or "openai"
    binding = select(_t("provider_prompt"), _llm_provider_options(current_binding))
    base_url = text_input(
        _t("base_url"),
        _default_base_url(binding, current_binding, summary.llm["host"]),
    )
    api_key = _prompt_secret(_t("api_key"), summary.llm["api_key"])
    model_id = text_input(
        _t("model_id"),
        _default_llm_model(binding, current_binding, summary.llm["model"]),
    )
    api_version_default = summary.llm["api_version"] if binding == current_binding else ""
    if binding == "azure_openai":
        log_info(dim(_t("api_version_hint_azure")))
    else:
        log_info(dim(_t("api_version_hint_generic")))
    api_version = text_input(_t("api_version"), api_version_default)
    print()
    return {
        "LLM_BINDING": binding,
        "LLM_HOST": base_url,
        "LLM_API_KEY": api_key,
        "LLM_MODEL": model_id,
        "LLM_API_VERSION": api_version,
    }


def _configure_embedding() -> dict[str, str]:
    step(5, _TOTAL_STEPS, _t("embedding_step"))
    summary = get_env_store().as_summary()
    current_binding = summary.embedding["binding"] or "openai"
    binding = select(_t("provider_prompt"), _embedding_provider_options(current_binding))
    base_url = text_input(
        _t("base_url"),
        _default_base_url(binding, current_binding, summary.embedding["host"]),
    )
    api_key = _prompt_secret(_t("api_key"), summary.embedding["api_key"])
    model_id = text_input(
        _t("model_id"),
        _default_embedding_model(binding, current_binding, summary.embedding["model"]),
    )
    dimension = text_input(
        _t("dimension"),
        _default_embedding_dimension(binding, current_binding, summary.embedding["dimension"]),
    )
    send_dimensions = _send_dimensions_choice(summary.embedding["send_dimensions"])
    api_version_default = summary.embedding["api_version"] if binding == current_binding else ""
    if binding == "azure_openai":
        log_info(dim(_t("api_version_hint_azure")))
    else:
        log_info(dim(_t("api_version_hint_generic")))
    api_version = text_input(_t("api_version"), api_version_default)
    print()
    return {
        "EMBEDDING_BINDING": binding,
        "EMBEDDING_HOST": base_url,
        "EMBEDDING_API_KEY": api_key,
        "EMBEDDING_MODEL": model_id,
        "EMBEDDING_DIMENSION": dimension,
        "EMBEDDING_SEND_DIMENSIONS": "" if send_dimensions == "auto" else send_dimensions,
        "EMBEDDING_API_VERSION": api_version,
    }


def _configure_search() -> dict[str, str]:
    step(6, _TOTAL_STEPS, _t("search_step"))
    summary = get_env_store().as_summary()
    current_provider = summary.search["provider"] or "none"
    provider = select(_t("search_provider_prompt"), _search_provider_options(current_provider))

    if provider == "none":
        print()
        return {
            "SEARCH_PROVIDER": "",
            "SEARCH_API_KEY": "",
            "SEARCH_BASE_URL": "",
            "SEARCH_PROXY": "",
        }

    base_url_default = summary.search["base_url"] if provider == current_provider else ""
    if provider == "searxng" and not base_url_default:
        base_url_default = _t("searxng_default")
    api_key_default = summary.search["api_key"] if provider == current_provider else ""
    proxy_default = summary.search["proxy"] if provider == current_provider else ""

    base_url = base_url_default
    if provider == "searxng" or base_url_default:
        base_url = text_input(_t("search_base_url"), base_url_default)

    api_key = ""
    if provider in {"brave", "tavily", "jina", "perplexity", "serper"} or api_key_default:
        api_key = _prompt_secret(_t("api_key"), api_key_default)

    log_info(dim(_t("search_proxy_hint")))
    proxy = text_input(_t("search_proxy"), proxy_default or _t("search_proxy_placeholder"))
    if proxy == _t("search_proxy_placeholder") and not proxy_default:
        proxy = ""

    print()
    return {
        "SEARCH_PROVIDER": provider,
        "SEARCH_API_KEY": api_key,
        "SEARCH_BASE_URL": base_url,
        "SEARCH_PROXY": proxy,
    }


def _print_review(values: dict[str, str]) -> None:
    step(7, _TOTAL_STEPS, _t("review_step"))
    log_info(
        f"{_t('summary_ports')}  {bold(values['BACKEND_PORT'])} / {bold(values['FRONTEND_PORT'])}"
    )
    log_info(
        "{}  {}  {}  {}".format(
            _t("summary_llm"),
            bold(values["LLM_BINDING"] or "-"),
            dim(values["LLM_MODEL"] or "-"),
            dim(values["LLM_HOST"] or "-"),
        )
    )
    log_info(
        "{}  {}  {}  {}".format(
            _t("summary_embedding"),
            bold(values["EMBEDDING_BINDING"] or "-"),
            dim(values["EMBEDDING_MODEL"] or "-"),
            dim(values["EMBEDDING_HOST"] or "-"),
        )
    )
    search_summary = values["SEARCH_PROVIDER"] or _t("search_disabled")
    log_info(f"{_t('summary_search')}  {bold(search_summary)}")
    log_info(f"LLM key  {dim(_secret_mask(values['LLM_API_KEY']))}")
    log_info(f"Emb key  {dim(_secret_mask(values['EMBEDDING_API_KEY']))}")
    if values["SEARCH_PROVIDER"]:
        log_info(f"Search key  {dim(_secret_mask(values['SEARCH_API_KEY']))}")
    print()


def _write_env(values: dict[str, str]) -> None:
    get_env_store().write(values)


def _tour_banner() -> None:
    banner(
        "DeepTutor Setup Tour / DeepTutor 配置向导",
        [
            "CLI-first setup wizard.",
            "命令行配置向导。",
        ],
    )


def run_tour() -> None:
    _tour_banner()

    created_env = _ensure_env_file()
    removed_cache = _cleanup_legacy_tour_cache()

    _choose_language()

    if created_env:
        if ENV_EXAMPLE_PATH.exists():
            log_success(_t("env_created"))
        else:
            log_warn(_t("env_missing_template"))
    else:
        log_info(_t("env_exists"))
    if removed_cache:
        log_info(_t("tour_cache_removed"))

    log_info(f"{_t('env_path')}       {dim(str(ENV_PATH.relative_to(PROJECT_ROOT)))}")
    print()

    _install_dependencies()

    values: dict[str, str] = {}
    values.update(_configure_ports())
    values.update(_configure_llm())
    values.update(_configure_embedding())
    values.update(_configure_search())

    _print_review(values)
    if not confirm(_t("write_confirm"), default=True):
        log_warn(_t("no_changes"))
        return

    _write_env(values)
    log_success(_t("write_success"))
    print()
    log_success(_t("next_steps"))
    print()
    print(f"  {dim('$')} {_t('next_command')}")
    print()


def main() -> None:
    try:
        run_tour()
    except KeyboardInterrupt:
        print()
        log_warn(_t("interrupt"))
        raise SystemExit(130)


if __name__ == "__main__":
    main()
