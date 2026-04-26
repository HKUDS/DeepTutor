"""CLI commands for notebook record management."""

from __future__ import annotations

import json
from pathlib import Path

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
        name: str = typer.Argument(..., help="Notebook name."),
        description: str = typer.Option("", "--description", help="Notebook description."),
    ) -> None:
        """Create a notebook."""
        client = DeepTutorApp()
        notebook = client.create_notebook(name=name, description=description)
        console.print(json.dumps(notebook, ensure_ascii=False, indent=2, default=str))

    @app.command("show")
    def show_notebook(
        notebook_id: str = typer.Argument(..., help="Notebook id."),
        fmt: str = typer.Option("rich", "--format", help="Output format: rich | json."),
    ) -> None:
        """Show a notebook and its records."""
        client = DeepTutorApp()
        notebook = client.get_notebook(notebook_id)
        if notebook is None:
            console.print(f"[red]Notebook not found:[/] {notebook_id}")
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

    @app.command("remove-record")
    def remove_record(
        notebook_id: str = typer.Argument(..., help="Notebook id."),
        record_id: str = typer.Argument(..., help="Record id."),
    ) -> None:
        """Delete a notebook record."""
        client = DeepTutorApp()
        success = client.remove_record(notebook_id, record_id)
        if not success:
            console.print(f"[red]Record not found:[/] {record_id}")
            raise typer.Exit(code=1)
        console.print(f"Removed record {record_id} from notebook {notebook_id}")

    @app.command("add-md")
    def add_md(
        notebook_id: str = typer.Argument(..., help="Notebook id."),
        file_path: str = typer.Argument(..., help="Path to the markdown file."),
        title: str = typer.Option("", "--title", help="Record title (defaults to filename)."),
        record_type: str = typer.Option(
            "chat",
            "--type",
            help="Record type: chat, question, research, solve.",
        ),
    ) -> None:
        """Add a markdown file as a record to a notebook."""
        path = Path(file_path)
        if not path.exists():
            console.print(f"[red]File not found:[/] {file_path}")
            raise typer.Exit(code=1)

        content = path.read_text(encoding="utf-8")
        record_title = title or path.stem

        client = DeepTutorApp()
        result = client.add_record(
            notebook_ids=[notebook_id],
            record_type=record_type,
            title=record_title,
            user_query="",
            output=content,
        )
        record = result.get("record", {})
        console.print(
            f"[green]Added record[/] {record.get('id', '')} "
            f"to notebook {notebook_id}: {record_title}"
        )

    @app.command("replace-md")
    def replace_md(
        notebook_id: str = typer.Argument(..., help="Notebook id."),
        record_id: str = typer.Argument(..., help="Record id."),
        file_path: str = typer.Argument(..., help="Path to the markdown file."),
    ) -> None:
        """Replace a notebook record's output with content from a markdown file."""
        path = Path(file_path)
        if not path.exists():
            console.print(f"[red]File not found:[/] {file_path}")
            raise typer.Exit(code=1)

        content = path.read_text(encoding="utf-8")

        client = DeepTutorApp()
        updated = client.update_record(notebook_id, record_id, output=content)
        if updated is None:
            console.print(f"[red]Record not found:[/] {record_id}")
            raise typer.Exit(code=1)
        console.print(f"[green]Updated record[/] {record_id} in notebook {notebook_id}")
