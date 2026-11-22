"""Vault path shared by bundled Desktop sessions, outside workspace backups."""

from pathlib import Path


def desktop_vault_path(workspace: Path) -> Path:
    return workspace.parent / "chatgpt-plan-vault.enc"
