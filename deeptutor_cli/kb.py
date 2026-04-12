"""
CLI Knowledge Base Command
===========================

Manage llamaindex knowledge bases from the command line.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from deeptutor.knowledge.manager import KnowledgeBaseManager
from deeptutor.services.path_service import get_path_service
from deeptutor.services.rag.components.routing import FileTypeRouter
from deeptutor.services.rag.factory import DEFAULT_PROVIDER

console = Console()


def _get_kb_manager() -> KnowledgeBaseManager:
    """Return a KnowledgeBaseManager rooted at the canonical project-level KB directory."""
    base_dir = get_path_service().project_root / "data" / "knowledge_bases"
    return KnowledgeBaseManager(base_dir=str(base_dir))


def _collect_documents(docs: list[str], docs_dir: Optional[str]) -> list[str]:
    """Collect and de-duplicate document files from explicit paths and a directory."""
    candidates: list[Path] = []

    for doc in docs:
        path = Path(doc).expanduser().resolve()
        if path.exists() and path.is_file():
            candidates.append(path)

    if docs_dir:
        base = Path(docs_dir).expanduser().resolve()
        if not base.exists() or not base.is_dir():
            raise typer.BadParameter(f"文档目录不存在：{base}")
        for pattern in FileTypeRouter.get_glob_patterns_for_provider(DEFAULT_PROVIDER):
            candidates.extend(path for path in base.rglob(pattern) if path.is_file())

    unique: list[str] = []
    seen: set[str] = set()
    for path in candidates:
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        unique.append(key)

    return unique


def register(app: typer.Typer) -> None:
    @app.command("list")
    def kb_list(
        fmt: str = typer.Option("rich", "--format", "-f", help="输出格式：rich | json。"),
    ) -> None:
        """List all knowledge bases."""
        mgr = _get_kb_manager()
        kb_names = mgr.list_knowledge_bases()
        if not kb_names:
            if fmt == "json":
                console.print_json("[]")
            else:
                console.print("[dim]未找到知识库。[/]")
            return

        if fmt == "json":
            items = []
            for name in kb_names:
                info = mgr.get_info(name)
                stats = info.get("statistics", {})
                metadata = info.get("metadata", {})
                items.append({
                    "name": name,
                    "status": info.get("status", "unknown"),
                    "documents": stats.get("raw_documents", 0),
                    "rag_provider": metadata.get("rag_provider", stats.get("rag_provider", DEFAULT_PROVIDER)),
                    "is_default": bool(info.get("is_default")),
                })
            console.print_json(json.dumps(items, ensure_ascii=False, default=str))
            return

        table = Table(title="知识库")
        table.add_column("名称", style="bold")
        table.add_column("状态")
        table.add_column("文档数", justify="right")
        table.add_column("RAG 提供商")
        table.add_column("默认")

        for name in kb_names:
            info = mgr.get_info(name)
            stats = info.get("statistics", {})
            metadata = info.get("metadata", {})
            table.add_row(
                name,
                str(info.get("status", "unknown")),
                str(stats.get("raw_documents", 0)),
                str(metadata.get("rag_provider", stats.get("rag_provider", DEFAULT_PROVIDER))),
                "是" if info.get("is_default") else "",
            )

        console.print(table)

    @app.command("info")
    def kb_info(name: str = typer.Argument(..., help="知识库名称。")) -> None:
        """Show details of a knowledge base."""
        mgr = _get_kb_manager()
        try:
            info = mgr.get_info(name)
        except Exception as exc:
            console.print(f"[red]未找到知识库 '{name}'：{exc}[/]")
            raise typer.Exit(code=1) from exc
        console.print_json(json.dumps(info, indent=2, ensure_ascii=False, default=str))

    @app.command("set-default")
    def kb_set_default(name: str = typer.Argument(..., help="知识库名称。")) -> None:
        """Set the default knowledge base."""
        mgr = _get_kb_manager()
        try:
            mgr.set_default(name)
        except Exception as exc:
            console.print(f"[red]设置默认知识库 '{name}' 失败：{exc}[/]")
            raise typer.Exit(code=1) from exc
        console.print(f"[green]已将 '{name}' 设为默认知识库。[/]")

    @app.command("create")
    def kb_create(
        name: str = typer.Argument(..., help="新知识库名称。"),
        docs: list[str] = typer.Option([], "--doc", "-d", help="文档路径。"),
        docs_dir: Optional[str] = typer.Option(None, "--docs-dir", help="文档目录。"),
    ) -> None:
        """Initialize a new knowledge base from documents."""
        mgr = _get_kb_manager()
        if name in mgr.list_knowledge_bases():
            console.print(f"[red]知识库 '{name}' 已存在。[/]")
            raise typer.Exit(code=1)

        try:
            doc_paths = _collect_documents(docs, docs_dir)
        except typer.BadParameter as exc:
            console.print(f"[red]{exc}[/]")
            raise typer.Exit(code=1) from exc

        if not doc_paths:
            console.print("[red]请至少提供一个支持的文档（--doc 或 --docs-dir）。[/]")
            raise typer.Exit(code=1)

        console.print(
            f"正在通过 [bold]LlamaIndex[/] 创建知识库 [bold]{name}[/]，共 {len(doc_paths)} 个文档..."
        )
        from deeptutor.knowledge.initializer import initialize_knowledge_base

        try:
            asyncio.run(
                initialize_knowledge_base(
                    kb_name=name,
                    source_files=doc_paths,
                    base_dir=str(mgr.base_dir),
                    skip_extract=True,
                )
            )
        except Exception as exc:
            console.print(f"[red]知识库创建失败：{exc}[/]")
            raise typer.Exit(code=1) from exc
        console.print("[green]知识库创建成功。[/]")

    @app.command("add")
    def kb_add(
        name: str = typer.Argument(..., help="知识库名称。"),
        docs: list[str] = typer.Option([], "--doc", "-d", help="要添加的文档路径。"),
        docs_dir: Optional[str] = typer.Option(None, "--docs-dir", help="文档目录。"),
    ) -> None:
        """Add documents to an existing knowledge base."""
        mgr = _get_kb_manager()
        if name not in mgr.list_knowledge_bases():
            console.print(f"[red]未找到知识库 '{name}'。[/]")
            raise typer.Exit(code=1)

        try:
            doc_paths = _collect_documents(docs, docs_dir)
        except typer.BadParameter as exc:
            console.print(f"[red]{exc}[/]")
            raise typer.Exit(code=1) from exc

        if not doc_paths:
            console.print("[red]请至少提供一个支持的文档。[/]")
            raise typer.Exit(code=1)

        console.print(f"正在向 [bold]{name}[/] 添加 {len(doc_paths)} 个文档...")
        from deeptutor.knowledge.add_documents import add_documents

        try:
            processed_count = asyncio.run(
                add_documents(
                    kb_name=name,
                    source_files=doc_paths,
                    base_dir=str(mgr.base_dir),
                    allow_duplicates=False,
                )
            )
        except Exception as exc:
            console.print(f"[red]文档上传失败：{exc}[/]")
            raise typer.Exit(code=1) from exc

        if processed_count:
            console.print(f"[green]完成，已索引 {processed_count} 个文档。[/]")
        else:
            console.print("[yellow]没有新的唯一文档被索引。[/]")

    @app.command("delete")
    def kb_delete(
        name: str = typer.Argument(..., help="知识库名称。"),
        force: bool = typer.Option(False, "--force", "-f", help="跳过确认。"),
    ) -> None:
        """Delete a knowledge base."""
        if not force:
            confirm = typer.confirm(f"确认删除知识库 '{name}' 吗？")
            if not confirm:
                raise typer.Abort()

        mgr = _get_kb_manager()
        try:
            deleted = mgr.delete_knowledge_base(name, confirm=True)
        except Exception as exc:
            console.print(f"[red]删除 '{name}' 失败：{exc}[/]")
            raise typer.Exit(code=1) from exc

        if deleted:
            console.print(f"[green]已删除 '{name}'。[/]")
        else:
            console.print(f"[yellow]知识库 '{name}' 未被删除。[/]")

    @app.command("search")
    def kb_search(
        name: str = typer.Argument(..., help="知识库名称。"),
        query: str = typer.Argument(..., help="搜索查询。"),
        mode: str = typer.Option("hybrid", help="搜索模式。"),
        fmt: str = typer.Option("rich", "--format", "-f", help="输出格式：rich | json。"),
    ) -> None:
        """Search a knowledge base."""
        from deeptutor.tools.rag_tool import rag_search

        mgr = _get_kb_manager()
        if name not in mgr.list_knowledge_bases():
            console.print(f"[red]未找到知识库 '{name}'。[/]")
            raise typer.Exit(code=1)

        try:
            result = asyncio.run(
                rag_search(
                    query=query,
                    kb_name=name,
                    mode=mode,
                    kb_base_dir=str(mgr.base_dir),
                )
            )
        except Exception as exc:
            console.print(f"[red]搜索失败：{exc}[/]")
            raise typer.Exit(code=1) from exc

        if fmt == "json":
            console.print_json(json.dumps(result, indent=2, ensure_ascii=False, default=str))
            return

        answer = result.get("answer") or result.get("content", "")
        provider = result.get("provider", DEFAULT_PROVIDER)
        console.print(f"[bold]提供商：[/] {provider}")
        console.print(f"[bold]答案：[/]\n{answer}")
