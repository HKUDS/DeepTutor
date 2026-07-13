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

from rich.console import Console
from rich.table import Table
import typer

from deeptutor.knowledge.manager import KnowledgeBaseManager
from deeptutor.knowledge.naming import validate_knowledge_base_name
from deeptutor.services.path_service import get_path_service
from deeptutor.services.rag.factory import DEFAULT_PROVIDER
from deeptutor.services.rag.file_routing import FileTypeRouter

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
            raise typer.BadParameter(f"docs directory does not exist: {base}")
        candidates.extend(FileTypeRouter.collect_supported_files(base, recursive=True))

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
        fmt: str = typer.Option("rich", "--format", "-f", help="Output format: rich | json."),
    ) -> None:
        """List all knowledge bases."""
        mgr = _get_kb_manager()
        kb_names = mgr.list_knowledge_bases()
        if not kb_names:
            if fmt == "json":
                console.print_json("[]")
            else:
                console.print("[dim]No knowledge bases found.[/]")
            return

        if fmt == "json":
            items = []
            for name in kb_names:
                info = mgr.get_info(name)
                stats = info.get("statistics", {})
                metadata = info.get("metadata", {})
                items.append(
                    {
                        "name": name,
                        "status": info.get("status", "unknown"),
                        "documents": stats.get("raw_documents", 0),
                        "rag_provider": metadata.get(
                            "rag_provider", stats.get("rag_provider", DEFAULT_PROVIDER)
                        ),
                        "is_default": bool(info.get("is_default")),
                    }
                )
            console.print_json(json.dumps(items, ensure_ascii=False, default=str))
            return

        table = Table(title="Knowledge Bases")
        table.add_column("Name", style="bold")
        table.add_column("Status")
        table.add_column("Documents", justify="right")
        table.add_column("RAG Provider")
        table.add_column("Default")

        for name in kb_names:
            info = mgr.get_info(name)
            stats = info.get("statistics", {})
            metadata = info.get("metadata", {})
            table.add_row(
                name,
                str(info.get("status", "unknown")),
                str(stats.get("raw_documents", 0)),
                str(metadata.get("rag_provider", stats.get("rag_provider", DEFAULT_PROVIDER))),
                "yes" if info.get("is_default") else "",
            )

        console.print(table)

    @app.command("info")
    def kb_info(name: str = typer.Argument(..., help="Knowledge base name.")) -> None:
        """Show details of a knowledge base."""
        mgr = _get_kb_manager()
        try:
            info = mgr.get_info(name)
        except Exception as exc:
            console.print(f"[red]Knowledge base '{name}' not found: {exc}[/]")
            raise typer.Exit(code=1) from exc
        console.print_json(json.dumps(info, indent=2, ensure_ascii=False, default=str))

    @app.command("set-default")
    def kb_set_default(name: str = typer.Argument(..., help="Knowledge base name.")) -> None:
        """Set the default knowledge base."""
        mgr = _get_kb_manager()
        try:
            mgr.set_default(name)
        except Exception as exc:
            console.print(f"[red]Failed to set default KB '{name}': {exc}[/]")
            raise typer.Exit(code=1) from exc
        console.print(f"[green]Set '{name}' as default knowledge base.[/]")

    @app.command("create")
    def kb_create(
        name: str = typer.Argument(..., help="New KB name."),
        docs: list[str] = typer.Option([], "--doc", "-d", help="Document paths."),
        docs_dir: Optional[str] = typer.Option(None, "--docs-dir", help="Directory of documents."),
    ) -> None:
        """Initialize a new knowledge base from documents."""
        mgr = _get_kb_manager()
        try:
            name = validate_knowledge_base_name(name)
        except ValueError as exc:
            console.print(f"[red]{exc}[/]")
            raise typer.Exit(code=1) from exc

        if name in mgr.list_knowledge_bases():
            console.print(f"[red]Knowledge base '{name}' already exists.[/]")
            raise typer.Exit(code=1)

        try:
            doc_paths = _collect_documents(docs, docs_dir)
        except typer.BadParameter as exc:
            console.print(f"[red]{exc}[/]")
            raise typer.Exit(code=1) from exc

        if not doc_paths:
            console.print("[red]Provide at least one supported document (--doc or --docs-dir).[/]")
            raise typer.Exit(code=1)

        console.print(
            f"Creating KB [bold]{name}[/] with {len(doc_paths)} document(s) via [bold]LlamaIndex[/]..."
        )
        from deeptutor.knowledge.initializer import initialize_knowledge_base

        try:
            asyncio.run(
                initialize_knowledge_base(
                    kb_name=name,
                    source_files=doc_paths,
                    base_dir=str(mgr.base_dir),
                )
            )
        except Exception as exc:
            console.print(f"[red]KB creation failed: {exc}[/]")
            raise typer.Exit(code=1) from exc
        console.print("[green]Knowledge base created successfully.[/]")

    @app.command("add")
    def kb_add(
        name: str = typer.Argument(..., help="KB name."),
        docs: list[str] = typer.Option([], "--doc", "-d", help="Document paths to add."),
        docs_dir: Optional[str] = typer.Option(None, "--docs-dir", help="Directory of documents."),
    ) -> None:
        """Add documents to an existing knowledge base."""
        mgr = _get_kb_manager()
        if name not in mgr.list_knowledge_bases():
            console.print(f"[red]Knowledge base '{name}' not found.[/]")
            raise typer.Exit(code=1)

        try:
            doc_paths = _collect_documents(docs, docs_dir)
        except typer.BadParameter as exc:
            console.print(f"[red]{exc}[/]")
            raise typer.Exit(code=1) from exc

        if not doc_paths:
            console.print("[red]Provide at least one supported document.[/]")
            raise typer.Exit(code=1)

        console.print(f"Adding {len(doc_paths)} document(s) to [bold]{name}[/]...")
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
            console.print(f"[red]Document upload failed: {exc}[/]")
            raise typer.Exit(code=1) from exc

        if processed_count:
            console.print(f"[green]Done. Indexed {processed_count} document(s).[/]")
        else:
            console.print("[yellow]No new unique documents were indexed.[/]")

    @app.command("delete")
    def kb_delete(
        name: str = typer.Argument(..., help="KB name."),
        force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation."),
    ) -> None:
        """Delete a knowledge base."""
        if not force:
            confirm = typer.confirm(f"Delete knowledge base '{name}'?")
            if not confirm:
                raise typer.Abort()

        mgr = _get_kb_manager()
        try:
            deleted = mgr.delete_knowledge_base(name, confirm=True)
        except Exception as exc:
            console.print(f"[red]Failed to delete '{name}': {exc}[/]")
            raise typer.Exit(code=1) from exc

        if deleted:
            console.print(f"[green]Deleted '{name}'.[/]")
        else:
            console.print(f"[yellow]Knowledge base '{name}' was not deleted.[/]")

    @app.command("search")
    def kb_search(
        name: str = typer.Argument(..., help="KB name."),
        query: str = typer.Argument(..., help="Search query."),
        mode: str = typer.Option("hybrid", help="Search mode."),
        fmt: str = typer.Option("rich", "--format", "-f", help="Output format: rich | json."),
    ) -> None:
        """Search a knowledge base."""
        from deeptutor.tools.rag_tool import rag_search

        mgr = _get_kb_manager()
        if name not in mgr.list_knowledge_bases():
            console.print(f"[red]Knowledge base '{name}' not found.[/]")
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
            console.print(f"[red]Search failed: {exc}[/]")
            raise typer.Exit(code=1) from exc

        if fmt == "json":
            console.print_json(json.dumps(result, indent=2, ensure_ascii=False, default=str))
            return

        answer = result.get("answer") or result.get("content", "")
        provider = result.get("provider", DEFAULT_PROVIDER)
        console.print(f"[bold]Provider:[/] {provider}")
        console.print(f"[bold]Answer:[/]\n{answer}")
