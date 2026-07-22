"""Branded banner + localized labels for ``deeptutor start`` / ``deeptutor init``.

Both commands read the user's language preference from
``data/user/settings/interface.json`` (default ``en``) so their startup
output matches the UI language the user has chosen.
"""

from __future__ import annotations

from rich.align import Align
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from deeptutor.__version__ import __version__

_ASCII_LOGO = r""" ____                  _____      _
|  _ \  ___  ___ _ __ |_   _|   _| |_ ___  _ __
| | | |/ _ \/ _ \ '_ \  | || | | | __/ _ \| '__|
| |_| |  __/  __/ |_) | | || |_| | || (_) | |
|____/ \___|\___| .__/  |_| \__,_|\__\___/|_|
                |_|"""


LABELS: dict[str, dict[str, str]] = {
    "en": {
        "tagline": "Agent-Native Personalized Tutoring",
        "lab": "Data Intelligence Lab @ HKU",
        # init
        "init.mode": "Workspace initializer",
        "init.workspace": "Workspace",
        "init.note_settings_dir": "Settings will be written under data/user/settings.",
        "init.cancelled": "Setup cancelled. Nothing was saved.",
        "init.step_ports": "Step {n}/{total} · Ports",
        "init.step_llm": "Step {n}/{total} · LLM provider",
        "init.step_embedding": "Step {n}/{total} · Embedding (RAG / Knowledge Base)",
        "init.step_search": "Step {n}/{total} · Web search",
        "init.step_review": "Step {n}/{total} · Review & save",
        "init.backend_port": "Backend port",
        "init.frontend_port": "Frontend port",
        "init.llm_section": "LLM provider",
        "init.pick_provider": "Pick an LLM provider",
        "init.pick_embedding_provider": "Pick an embedding provider",
        "init.show_all": "Show all providers",
        "init.custom_provider": "Custom / Other",
        "init.skip_step": "Skip / configure later",
        "init.back": "Back",
        "init.skipped": "Skipped — you can configure this later in Web Settings.",
        "init.binding": "Binding",
        "init.base_url": "Base URL",
        "init.api_key": "API key",
        "init.api_key_env_detected": "Detected {env_var}={masked} in your environment. Use it?",
        "init.api_key_prompt": "API key (input hidden, Enter to skip)",
        "init.api_key_reuse_llm": "Reuse the LLM API key {masked}?",
        "init.edit_base_url": "Edit Base URL?",
        "init.new_base_url": "New Base URL",
        "init.model": "Model",
        "init.fetch_models": "Fetching available models from {url} ...",
        "init.fetch_models_ok": "Found {count} model(s).",
        "init.fetch_models_fail": "Could not list models ({error}). Using fallback list.",
        "init.pick_model": "Pick a model — or type {marker} to enter your own",
        "init.custom_model": "Custom model name",
        "init.embedding_section": "Embedding provider",
        "init.embedding_endpoint": "Embedding endpoint URL",
        "init.embedding_api_key": "Embedding API key",
        "init.embedding_model": "Embedding model",
        "init.embedding_dimension": "Embedding dimension (blank for auto)",
        "init.search_section": "Web search provider",
        "init.pick_search_provider": "Pick a web-search provider",
        "init.search_api_key_prompt": "API key (input hidden, Enter to skip)",
        "init.search_base_url_prompt": "Base URL",
        "init.search_no_key_note": "{label} does not need an API key.",
        "init.search_disabled_note": "Web search will be disabled. Agents will skip search tools.",
        "init.review_search": "Search",
        "init.review_search_disabled": "disabled",
        "init.probe_offer": "Test connection now?",
        "init.probe_running": "Testing {what} ...",
        "init.probe_ok": "{what} OK  ·  {ms}ms",
        "init.probe_fail": "{what} failed: {error}",
        "init.probe_retry": "Re-enter API key and retry?",
        "init.review_title": "Review",
        "init.review_llm": "LLM",
        "init.review_embedding": "Embedding",
        "init.review_ports": "Ports",
        "init.review_ports_value": "backend {backend}, frontend {frontend}",
        "init.confirm_save": "Save these settings?",
        "init.saved": "Settings saved. You can edit them later in the Web Settings page or data/user/settings/.",
        "init.next_step": "Run `deeptutor start` to launch DeepTutor.",
        "init.choice": "Choice",
        "init.choice_invalid": "Invalid choice. Try again.",
        # start (launcher)
        "start.mode": "Launching backend + frontend",
        "start.backend": "Backend",
        "start.browser_api": "Browser API",
        "start.frontend": "Frontend",
        "start.workspace": "Workspace",
        "start.frontend_runtime": "Frontend runtime",
        "start.press_ctrl_c": "Press Ctrl+C to stop.",
        "start.starting_backend": "Starting backend ...",
        "start.starting_frontend": "Starting frontend ...",
        "start.reusing_frontend": "Reusing existing frontend at {url} (PID {pid}).",
        "start.restarting_frontend": (
            "Existing frontend at {url} is not responding; restarting it (PID {pid})."
        ),
        "start.frontend_restart_failed": (
            "Existing frontend at {url} is not responding and could not be stopped automatically. "
            "Stop PID {pid} and run `deeptutor start` again."
        ),
        "start.waiting_for": "Waiting for {name} at {url} ...",
        "start.ready": "{name} is ready.",
        "start.open_in_browser": "Open {url} in your browser.",
        "start.received_signal": "Received {signal}; shutting down ...",
        "start.stopping": "Stopping {name} (PID {pid})",
        "start.exited": "{name} exited with code {code}",
        "start.not_ready": "{name} did not become ready within {timeout}s",
        "start.port_in_use": (
            "DeepTutor cannot start because port(s) already in use: {ports}. "
            "Stop the existing process or change data/user/settings/system.json."
        ),
        "start.port_conflict_title": "Port conflict detected:",
        "start.port_conflict_line": "  {role} port {port} is in use by:",
        "start.port_conflict_proc": "    PID {pid} · {command}",
        "start.port_conflict_unknown_proc": "    (process info unavailable)",
        "start.port_option_change": "Change ports (saved to data/user/settings/system.json)",
        "start.port_option_kill": "Stop the occupying process(es) and continue",
        "start.port_invalid": "Invalid port: {value}. Enter a free port between 1 and 65535.",
        "start.port_saved": "Ports saved to {path}.",
        "start.port_killing": "Stopping PID {pid} ({command}) ...",
        "start.port_kill_failed": "Could not free port {port} (PID {pid}).",
        "start.port_freed": "Port {port} released.",
    },
    "zh": {
        "tagline": "智能体原生的个性化辅导",
        "lab": "香港大学数据智能实验室",
        # init
        "init.mode": "工作目录初始化",
        "init.workspace": "工作目录",
        "init.note_settings_dir": "配置文件将写入 data/user/settings 目录。",
        "init.cancelled": "已取消,未保存任何更改。",
        "init.step_ports": "第 {n}/{total} 步 · 端口",
        "init.step_llm": "第 {n}/{total} 步 · 大模型服务",
        "init.step_embedding": "第 {n}/{total} 步 · 向量模型 (知识库 / RAG)",
        "init.step_search": "第 {n}/{total} 步 · 联网搜索",
        "init.step_review": "第 {n}/{total} 步 · 确认并保存",
        "init.backend_port": "后端端口",
        "init.frontend_port": "前端端口",
        "init.llm_section": "大模型服务",
        "init.pick_provider": "请选择大模型服务",
        "init.pick_embedding_provider": "请选择向量模型服务",
        "init.show_all": "查看全部服务商",
        "init.custom_provider": "其他 / 自定义",
        "init.skip_step": "跳过 / 稍后配置",
        "init.back": "返回上一步",
        "init.skipped": "已跳过 —— 后续可在 Web 设置页中配置。",
        "init.binding": "服务类型",
        "init.base_url": "Base URL",
        "init.api_key": "API Key",
        "init.api_key_env_detected": "已检测到环境变量 {env_var}={masked},是否使用?",
        "init.api_key_prompt": "API Key (输入不显示,直接回车跳过)",
        "init.api_key_reuse_llm": "复用大模型的 API Key ({masked})?",
        "init.edit_base_url": "需要修改 Base URL 吗?",
        "init.new_base_url": "新的 Base URL",
        "init.model": "模型",
        "init.fetch_models": "正在从 {url} 拉取可用模型列表 ...",
        "init.fetch_models_ok": "找到 {count} 个模型。",
        "init.fetch_models_fail": "无法获取模型列表 ({error}),将使用本地推荐列表。",
        "init.pick_model": "请选择模型 —— 或输入 {marker} 手动填写",
        "init.custom_model": "自定义模型名称",
        "init.embedding_section": "向量模型服务",
        "init.embedding_endpoint": "向量服务地址",
        "init.embedding_api_key": "向量服务 API Key",
        "init.embedding_model": "向量模型",
        "init.embedding_dimension": "向量维度 (留空自动检测)",
        "init.search_section": "联网搜索服务",
        "init.pick_search_provider": "请选择联网搜索服务",
        "init.search_api_key_prompt": "API Key (输入不显示,直接回车跳过)",
        "init.search_base_url_prompt": "Base URL",
        "init.search_no_key_note": "{label} 无需 API Key。",
        "init.search_disabled_note": "联网搜索将被禁用。Agent 将跳过搜索工具。",
        "init.review_search": "搜索",
        "init.review_search_disabled": "已禁用",
        "init.probe_offer": "立即测试连接?",
        "init.probe_running": "正在测试 {what} ...",
        "init.probe_ok": "{what} 连接成功  ·  {ms}ms",
        "init.probe_fail": "{what} 连接失败: {error}",
        "init.probe_retry": "重新输入 API Key 并重试?",
        "init.review_title": "配置确认",
        "init.review_llm": "大模型",
        "init.review_embedding": "向量",
        "init.review_ports": "端口",
        "init.review_ports_value": "后端 {backend},前端 {frontend}",
        "init.confirm_save": "确认保存以上配置?",
        "init.saved": "配置已保存。后续可在 Web 设置页或 data/user/settings/ 中修改。",
        "init.next_step": "运行 `deeptutor start` 启动 DeepTutor。",
        "init.choice": "请选择",
        "init.choice_invalid": "无效选项,请重新输入。",
        # start (launcher)
        "start.mode": "启动后端 + 前端",
        "start.backend": "后端",
        "start.browser_api": "前端 API",
        "start.frontend": "前端",
        "start.workspace": "工作目录",
        "start.frontend_runtime": "前端运行模式",
        "start.press_ctrl_c": "按 Ctrl+C 停止。",
        "start.starting_backend": "正在启动后端服务 ...",
        "start.starting_frontend": "正在启动前端服务 ...",
        "start.reusing_frontend": "复用已运行的前端 {url} (PID {pid})。",
        "start.restarting_frontend": "已运行的前端 {url} 无响应,正在重启 (PID {pid})。",
        "start.frontend_restart_failed": (
            "已运行的前端 {url} 无响应,且无法自动停止。"
            "请先停止 PID {pid},然后重新运行 `deeptutor start`。"
        ),
        "start.waiting_for": "正在等待 {name} ({url}) ...",
        "start.ready": "{name} 已就绪。",
        "start.open_in_browser": "请在浏览器中打开 {url}。",
        "start.received_signal": "收到 {signal} 信号,正在关闭 ...",
        "start.stopping": "正在停止 {name} (PID {pid})",
        "start.exited": "{name} 已退出 (退出码 {code})",
        "start.not_ready": "{name} 在 {timeout} 秒内未就绪",
        "start.port_in_use": (
            "无法启动 DeepTutor,端口已被占用: {ports}。"
            "请先停止占用进程,或修改 data/user/settings/system.json 中的端口设置。"
        ),
        "start.port_conflict_title": "检测到端口被占用:",
        "start.port_conflict_line": "  {role}端口 {port} 被以下进程占用:",
        "start.port_conflict_proc": "    PID {pid} · {command}",
        "start.port_conflict_unknown_proc": "    (无法获取进程信息)",
        "start.port_option_change": "更改端口设置 (写入 data/user/settings/system.json)",
        "start.port_option_kill": "停止占用进程并继续启动",
        "start.port_invalid": "无效端口: {value}。请输入 1-65535 之间且未被占用的端口。",
        "start.port_saved": "端口设置已保存到 {path}。",
        "start.port_killing": "正在停止 PID {pid} ({command}) ...",
        "start.port_kill_failed": "无法释放端口 {port} (PID {pid})。",
        "start.port_freed": "端口 {port} 已释放。",
    },
}


def _pick_language(language: str | None) -> str:
    if not language:
        return "en"
    code = str(language).lower().strip()
    if code in {"zh", "zh-cn", "zh-hans", "chinese", "cn"}:
        return "zh"
    return "en"


def resolve_language(default: str = "en") -> str:
    """Read the saved UI language, falling back to ``default``.

    Safe to call before the runtime is fully initialized; any failure
    silently falls back to the default.
    """
    try:
        from deeptutor.services.settings.interface_settings import get_ui_language

        return _pick_language(get_ui_language(default))
    except Exception:
        return _pick_language(default)


def labels_for(language: str | None) -> dict[str, str]:
    return LABELS[_pick_language(language)]


def render_banner(language: str | None, *, mode_key: str | None = None) -> Panel:
    """Build the branded banner panel.

    Parameters
    ----------
    language:
        Language code (``"en"``/``"zh"``). Unknown values fall back to English.
    mode_key:
        Optional key into ``LABELS[lang]`` to display under the tagline
        (e.g. ``"start.mode"``, ``"init.mode"``).
    """

    lang = _pick_language(language)
    strings = LABELS[lang]

    logo = Text(_ASCII_LOGO, style="bold bright_cyan")
    tagline_line = f"{strings['tagline']}  ·  v{__version__}"

    body = Text()
    body.append(logo)
    body.append("\n\n")
    body.append(tagline_line, style="bold white")
    body.append("\n")
    body.append(strings["lab"], style="dim")
    if mode_key and mode_key in strings:
        body.append("\n")
        body.append(strings[mode_key], style="italic bright_magenta")

    return Panel(
        Align.left(body),
        title="[bold bright_cyan]DeepTutor[/]",
        border_style="bright_cyan",
        padding=(1, 2),
    )


def print_banner(
    console: Console | None = None,
    *,
    language: str | None = None,
    mode_key: str | None = None,
) -> None:
    """Print the branded banner to ``console`` (creates one if omitted)."""

    target = console or Console()
    target.print(render_banner(language, mode_key=mode_key))


__all__: tuple[str, ...] = (
    "LABELS",
    "labels_for",
    "print_banner",
    "render_banner",
    "resolve_language",
)
