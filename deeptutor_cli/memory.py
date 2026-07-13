"""CLI memory commands for the three-layer memory subsystem (v2)."""

from __future__ import annotations

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
import typer

from deeptutor.services.memory import (
    L3_SLOTS,
    SURFACES,
    get_memory_store,
    paths,
)

console = Console()


def register(app: typer.Typer) -> None:
    @app.command("show")
    def memory_show(
        target: str = typer.Argument(
            "L3",
            help="What to show: 'L3' (all four global docs), 'L2' (all seven surface docs), or a single doc name (e.g. 'profile', 'chat').",
        ),
    ) -> None:
        """Display memory document content."""
        store = get_memory_store()

        if target == "L3":
            text = store.read_l3_concat()
            console.print(Panel(Markdown(text), title="[bold]L3 (concatenated)[/]"))
            return

        if target == "L2":
            for surface in SURFACES:
                content = store.read_raw("L2", surface)
                if content.strip():
                    console.print(Panel(Markdown(content), title=f"[bold]L2/{surface}.md[/]"))
                else:
                    console.print(f"[dim]L2/{surface}.md: (empty)[/]")
            return

        # Single doc name — resolve to L2 or L3.
        if target in L3_SLOTS:
            content = store.read_raw("L3", target)
            label = f"L3/{target}.md"
        elif target in SURFACES:
            content = store.read_raw("L2", target)
            label = f"L2/{target}.md"
        else:
            console.print(
                f"[red]Unknown doc: {target}. Use 'L2', 'L3', a surface ({', '.join(SURFACES)}), or a slot ({', '.join(L3_SLOTS)}).[/]"
            )
            raise typer.Exit(1)

        if content.strip():
            console.print(Panel(Markdown(content), title=f"[bold]{label}[/]"))
        else:
            console.print(f"[dim]{label}: (empty)[/]")

    @app.command("clear")
    def memory_clear(
        target: str = typer.Argument(
            "all",
            help="What to clear: 'all' (entire memory), 'trace' (all L1 trace), or a surface name to clear that surface's L1.",
        ),
        force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation."),
    ) -> None:
        """Clear memory (use 'all' for a full reset, or a surface name for L1 only)."""
        if target != "all" and target != "trace" and target not in SURFACES:
            console.print(f"[red]Unknown target: {target}[/]")
            raise typer.Exit(1)

        if not force:
            label = "all memory" if target == "all" else f"L1 trace for {target}"
            if not typer.confirm(f"Clear {label}?"):
                raise typer.Abort()

        if target == "all":
            root = paths.memory_root()
            for entry in root.iterdir() if root.exists() else []:
                if entry.is_file():
                    entry.unlink()
                elif entry.is_dir() and entry.name in {"trace", "L2", "L3"}:
                    for child in entry.rglob("*"):
                        if child.is_file():
                            child.unlink()
            console.print("[green]Cleared all memory.[/]")
        elif target == "trace":
            for surface in SURFACES:
                for f in paths.trace_dir(surface).glob("*.jsonl"):
                    f.unlink()
            console.print("[green]Cleared all L1 trace.[/]")
        else:
            for f in paths.trace_dir(target).glob("*.jsonl"):  # type: ignore[arg-type]
                f.unlink()
            console.print(f"[green]Cleared L1 trace for {target}.[/]")
