"""CLI entry point for the standalone ``deeptutor-cli`` package."""

from __future__ import annotations
import typer

from deeptutor.runtime.mode import RunMode, set_mode
from deeptutor.services.setup import get_backend_port

from .bot import register as register_bot
from .chat import register as register_chat
from .common import build_turn_request, console, maybe_run
from .config_cmd import register as register_config
from .kb import register as register_kb
from .memory import register as register_memory
from .notebook import register as register_notebook
from .plugin import register as register_plugin
from .provider_cmd import register as register_provider
from .session_cmd import register as register_session

set_mode(RunMode.CLI)

app = typer.Typer(
    name="deeptutor",
    help="DeepTutor CLI - 面向智能体的能力、工具与知识统一入口。",
    no_args_is_help=True,
    add_completion=False,
)

bot_app = typer.Typer(help="管理 TutorBot 实例。")
chat_app = typer.Typer(help="交互式聊天 REPL。")
kb_app = typer.Typer(help="管理知识库。")
memory_app = typer.Typer(help="查看和管理轻量记忆。")
plugin_app = typer.Typer(help="查看插件。")
config_app = typer.Typer(help="查看配置。")
session_app = typer.Typer(help="管理共享会话。")
notebook_app = typer.Typer(help="管理笔记本与导入的 Markdown 记录。")
provider_app = typer.Typer(help="管理 Provider OAuth 登录。")

app.add_typer(bot_app, name="bot")
app.add_typer(chat_app, name="chat")
app.add_typer(kb_app, name="kb")
app.add_typer(memory_app, name="memory")
app.add_typer(plugin_app, name="plugin")
app.add_typer(config_app, name="config")
app.add_typer(session_app, name="session")
app.add_typer(notebook_app, name="notebook")
app.add_typer(provider_app, name="provider")

register_bot(bot_app)
register_chat(chat_app)
register_kb(kb_app)
register_memory(memory_app)
register_plugin(plugin_app)
register_config(config_app)
register_session(session_app)
register_notebook(notebook_app)
register_provider(provider_app)


@app.command("run")
def run_capability(
    capability: str = typer.Argument(..., help="能力名称（如 chat、deep_solve、deep_question、deep_research、math_animator）。"),
    message: str = typer.Argument(..., help="要发送的消息。"),
    session: str | None = typer.Option(None, "--session", help="已有会话 ID。"),
    tool: list[str] = typer.Option([], "--tool", "-t", help="启用的工具。"),
    kb: list[str] = typer.Option([], "--kb", help="知识库名称。"),
    notebook_ref: list[str] = typer.Option([], "--notebook-ref", help="笔记本引用。"),
    history_ref: list[str] = typer.Option([], "--history-ref", help="引用的会话 ID。"),
    language: str = typer.Option("zh", "--language", "-l", help="响应语言。"),
    config: list[str] = typer.Option([], "--config", help="能力配置 key=value。"),
    config_json: str | None = typer.Option(None, "--config-json", help="JSON 格式能力配置。"),
    fmt: str = typer.Option("rich", "--format", "-f", help="输出格式：rich | json。"),
) -> None:
    """单轮执行任意能力（智能体优先入口）。"""
    from deeptutor.app import DeepTutorApp
    from .common import run_turn_and_render

    request = build_turn_request(
        content=message,
        capability=capability,
        session_id=session,
        tools=tool,
        knowledge_bases=kb,
        language=language,
        config_items=config,
        config_json=config_json,
        notebook_refs=notebook_ref,
        history_refs=history_ref,
    )
    maybe_run(run_turn_and_render(app=DeepTutorApp(), request=request, fmt=fmt))


@app.command()
def serve(
    host: str = typer.Option("0.0.0.0", help="绑定地址。"),
    port: int = typer.Option(get_backend_port(), help="端口号。"),
    reload: bool = typer.Option(False, help="开发模式启用自动重载。"),
) -> None:
    """启动 DeepTutor API 服务。"""
    set_mode(RunMode.SERVER)
    try:
        import uvicorn
    except ImportError:
        console.print(
            "[bold red]Error:[/] API server dependencies not installed.\n"
            "请运行：pip install -r requirements/server.txt"
        )
        raise typer.Exit(code=1)

    uvicorn.run(
        "deeptutor.api.main:app",
        host=host,
        port=port,
        reload=reload,
        reload_excludes=["web/*", "data/*"] if reload else None,
    )


def main() -> None:
    app()


if __name__ == "__main__":
    main()
