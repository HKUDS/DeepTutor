"""CLI commands for notebook record management."""

from __future__ import annotations

import json

import typer

from deeptutor.app import DeepTutorApp

from .common import console, print_notebook_table


def register(app: typer.Typer) -> None:
    @app.command("list")
    def list_notebooks() -> None:
        """List notebooks."""
        client = DeepTutorApp()
        print_notebook_table(client.list_notebooks())

    @app.command("create")
    def create_notebook(
        name: str = typer.Argument(..., help="笔记本名称。"),
        description: str = typer.Option("", "--description", help="笔记本描述。"),
    ) -> None:
        """Create a notebook."""
        client = DeepTutorApp()
        notebook = client.create_notebook(name=name, description=description)
        console.print(json.dumps(notebook, ensure_ascii=False, indent=2, default=str))

    @app.command("show")
    def show_notebook(
        notebook_id: str = typer.Argument(..., help="笔记本 ID。"),
        fmt: str = typer.Option("rich", "--format", help="输出格式：rich | json。"),
    ) -> None:
        """Show a notebook and its records."""
        client = DeepTutorApp()
        notebook = client.get_notebook(notebook_id)
        if notebook is None:
            console.print(f"[red]未找到笔记本：[/] {notebook_id}")
            raise typer.Exit(code=1)
        if fmt == "json":
            console.print(json.dumps(notebook, ensure_ascii=False, indent=2, default=str))
            return
        console.print(f"[bold]{notebook.get('name', '')}[/] ({notebook.get('id', '')})")
        console.print(str(notebook.get("description", "") or ""))
        for record in notebook.get("records", []):
            console.print(
                f"\n[cyan]{record.get('id', '')}[/] "
                f"{record.get('type', '')} "
                f"{record.get('title', '')}"
            )

    @app.command("add-md")
    def add_md(
        notebook_id: str = typer.Argument(..., help="笔记本 ID。"),
        path: str = typer.Argument(..., help="Markdown 文件路径。"),
    ) -> None:
        """Import a markdown file as a co-writer notebook record."""
        client = DeepTutorApp()
        result = client.import_markdown_into_notebook(notebook_id, path)
        console.print(json.dumps(result, ensure_ascii=False, indent=2, default=str))

    @app.command("replace-md")
    def replace_md(
        notebook_id: str = typer.Argument(..., help="笔记本 ID。"),
        record_id: str = typer.Argument(..., help="已有记录 ID。"),
        path: str = typer.Argument(..., help="Markdown 文件路径。"),
    ) -> None:
        """Replace an existing co-writer notebook record in-place."""
        client = DeepTutorApp()
        record = client.replace_markdown_record(notebook_id, record_id, path)
        console.print(json.dumps(record, ensure_ascii=False, indent=2, default=str))

    @app.command("remove-record")
    def remove_record(
        notebook_id: str = typer.Argument(..., help="笔记本 ID。"),
        record_id: str = typer.Argument(..., help="记录 ID。"),
    ) -> None:
        """Delete a notebook record."""
        client = DeepTutorApp()
        success = client.remove_record(notebook_id, record_id)
        if not success:
            console.print(f"[red]未找到记录：[/] {record_id}")
            raise typer.Exit(code=1)
        console.print(f"已从笔记本 {notebook_id} 删除记录 {record_id}")
