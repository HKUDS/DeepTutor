"""Model-facing description of the user Content Workspace."""

from __future__ import annotations

from deeptutor.core.context import UnifiedContext


def workspace_system_note(
    context: UnifiedContext,
    *,
    language: str,
    allow_export: bool = False,
) -> str:
    """Describe only logical workspace paths; never expose host paths."""
    workspace = context.runtime.workspace
    if workspace is None:
        return ""
    output = workspace.logical_output_dir
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
            f"本轮唯一默认可写目录是 `{output}/`；所有新建、下载、解压、代码和生成素材都必须"
            "保存在其中。不要暴露或猜测宿主机绝对路径。\n"
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
        f"The only default writable directory for this turn is `{output}/`. Save every new, "
        "downloaded, extracted, coded, or generated file there. Never expose or guess host "
        "absolute paths.\n"
        "When exec code must open an existing binary workspace file, join the "
        "DEEPTUTOR_WORKSPACE_ROOT environment variable with the exact relative path returned "
        "by a workspace tool; never print the variable's value.\n"
        "To let the user open a file, call workspace_present first, then use the exact relative "
        f"path it returns in Markdown. Never paste an internal download URL. {export}"
    )


__all__ = ["workspace_system_note"]
