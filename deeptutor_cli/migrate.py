from __future__ import annotations

import json
from pathlib import Path

import typer

from deeptutor.multi_user.kids_migration import KidsToLearningMigration


def register(app: typer.Typer) -> None:
    @app.command("kids-to-learning")
    def kids_to_learning(
        apply: bool = typer.Option(False, "--apply", help="Perform the copy migration."),
        activation_report: Path | None = typer.Option(
            None,
            "--activation-report",
            help="Required with --apply; plaintext one-time codes are written here with mode 0600.",
        ),
    ) -> None:
        """Copy legacy Kids profiles into restricted Learning Accounts."""
        migration = KidsToLearningMigration()
        if apply:
            if activation_report is None:
                raise typer.BadParameter("--activation-report is required with --apply")
            result = migration.apply(activation_report=activation_report)
        else:
            result = migration.plan()
        typer.echo(json.dumps(result, ensure_ascii=False, indent=2))
