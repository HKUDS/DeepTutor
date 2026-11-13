"""Model-facing description of the user Content Workspace."""

from __future__ import annotations

from deeptutor.core.context import UnifiedContext


def workspace_system_note(
    context: UnifiedContext,
    *,
    language: str,
    allow_export: bool = False,
) -> str:
    """Keep workspace guidance stable across turns; never expose host paths."""
    workspace = context.runtime.workspace
    if workspace is None:
        return ""
    if language.lower().startswith("zh"):
        export = (
            "若用户明确要求把产物写到 outputs/ 之外，使用 workspace_export 请求一次性授权；"
            "不要尝试绕过授权。"
            if allow_export
            else "不要写入 outputs/ 之外的位置。"
        )
        return (
            "[用户 Workspace]\n"
            "你可以用 workspace_list、workspace_search 和 workspace_read 查看用户允许读取的文件。"
            "在声称本地文件不可用前，必须先使用这些工具确认。\n"
            "本轮默认只能写入 `outputs/` 下分配给本轮的输出目录；所有新建、下载、解压、代码和"
            "生成素材都必须保存在其中。exec 在此目录内运行；创建文件时使用相对路径。"
            "不要暴露或猜测宿主机绝对路径。\n"
            "exec 代码需读取 workspace 中已有的二进制文件时，用环境变量 "
            "DEEPTUTOR_WORKSPACE_ROOT 与 workspace 工具返回的精确相对路径拼接；"
            "不要输出该环境变量的值。\n"
            "要让用户打开文件，先调用 workspace_present，再在 Markdown 中使用它返回的精确相对"
            f"路径。不要直接粘贴内部下载 URL。{export}"
        )
    export = (
        "If the user explicitly asks to write a result outside outputs/, request one-time "
        "authorization with workspace_export; never try to bypass it."
        if allow_export
        else "Do not write outside outputs/."
    )
    return (
        "[User workspace]\n"
        "Use workspace_list, workspace_search, and workspace_read to inspect files the user "
        "made available. Before saying a local file is unavailable, check with these tools.\n"
        "The only default writable directory is this turn's assigned output directory under "
        "`outputs/`. Save every new, downloaded, extracted, coded, or generated file there. "
        "Exec runs inside that directory; use relative paths when creating files. "
        "Never expose or guess host absolute paths.\n"
        "When exec code must open an existing binary workspace file, join the "
        "DEEPTUTOR_WORKSPACE_ROOT environment variable with the exact relative path returned "
        "by a workspace tool; never print the variable's value.\n"
        "To let the user open a file, call workspace_present first, then use the exact relative "
        f"path it returns in Markdown. Never paste an internal download URL. {export}"
    )


__all__ = ["workspace_system_note"]
