#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Knowledge Base Manager

Manages multiple knowledge bases and provides utilities for accessing them.
"""

from contextlib import contextmanager
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys

from src.services.rag.components.routing import FileTypeRouter


# Cross-platform file locking
@contextmanager
def file_lock_shared(file_handle):
    """Acquire a shared (read) lock on a file - cross-platform."""
    if sys.platform == "win32":
        import msvcrt

        msvcrt.locking(file_handle.fileno(), msvcrt.LK_NBLCK, 1)
        try:
            yield
        finally:
            file_handle.seek(0)
            msvcrt.locking(file_handle.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        fcntl.flock(file_handle.fileno(), fcntl.LOCK_SH)
        try:
            yield
        finally:
            fcntl.flock(file_handle.fileno(), fcntl.LOCK_UN)


@contextmanager
def file_lock_exclusive(file_handle):
    """Acquire an exclusive (write) lock on a file - cross-platform."""
    if sys.platform == "win32":
        import msvcrt

        msvcrt.locking(file_handle.fileno(), msvcrt.LK_NBLCK, 1)
        try:
            yield
        finally:
            file_handle.seek(0)
            msvcrt.locking(file_handle.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        fcntl.flock(file_handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(file_handle.fileno(), fcntl.LOCK_UN)


class KnowledgeBaseManager:
    """Manager for knowledge bases"""

    def __init__(self, base_dir="./data/knowledge_bases"):
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

        # Config file to track knowledge bases
        self.config_file = self.base_dir / "kb_config.json"
        self.config = self._load_config()

    def _load_config(self) -> dict:
        """Load knowledge base configuration (kb_config.json only stores KB list)"""
        if self.config_file.exists():
            try:
                with open(self.config_file, encoding="utf-8") as f:
                    with file_lock_shared(f):
                        content = f.read()
                        if not content.strip():
                            # Empty file, return default
                            return {"knowledge_bases": {}}
                        config = json.loads(content)

                # Ensure knowledge_bases key exists
                if "knowledge_bases" not in config:
                    config["knowledge_bases"] = {}

                # Migration: remove old "default" field if present
                if "default" in config:
                    del config["default"]
                    # Note: Don't save during load to avoid recursion issues
                    # The next _save_config() call will persist this change

                return config
            except (json.JSONDecodeError, Exception) as e:
                print(f"[KnowledgeBaseManager] Error loading config: {e}")
                return {"knowledge_bases": {}}
        return {"knowledge_bases": {}}

    def _save_config(self):
        """Save knowledge base configuration (thread-safe with file locking)"""
        # Use exclusive lock for writing
        with open(self.config_file, "w", encoding="utf-8") as f:
            with file_lock_exclusive(f):
                json.dump(self.config, f, indent=2, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())  # Ensure data is written to disk

    def update_kb_status(
        self,
        name: str,
        status: str,
        progress: dict | None = None,
    ):
        """
        Update knowledge base status and progress in kb_config.json.

        Args:
            name: Knowledge base name
            status: Status string ("initializing", "processing", "ready", "error")
            progress: Optional progress dict with keys like:
                - stage: Current stage name
                - message: Human-readable message
                - percent: Progress percentage (0-100)
                - current: Current item number
                - total: Total items
                - file_name: Current file being processed
                - error: Error message (if status is "error")
        """
        # Reload config to get latest state
        self.config = self._load_config()

        if "knowledge_bases" not in self.config:
            self.config["knowledge_bases"] = {}

        if name not in self.config["knowledge_bases"]:
            # Auto-register if not exists
            self.config["knowledge_bases"][name] = {
                "path": name,
                "description": f"Knowledge base: {name}",
            }

        kb_config = self.config["knowledge_bases"][name]
        kb_config["status"] = status
        kb_config["updated_at"] = datetime.now().isoformat()

        if progress is not None:
            kb_config["progress"] = progress
        elif status == "ready":
            # Clear progress when ready
            kb_config["progress"] = {
                "stage": "completed",
                "message": "Ready",
                "percent": 100,
            }

        self._save_config()

    def get_kb_status(self, name: str) -> dict | None:
        """Get status and progress for a knowledge base."""
        self.config = self._load_config()
        kb_config = self.config.get("knowledge_bases", {}).get(name)
        if not kb_config:
            return None
        return {
            "status": kb_config.get("status", "unknown"),
            "progress": kb_config.get("progress"),
            "updated_at": kb_config.get("updated_at"),
        }

    def list_knowledge_bases(self) -> list[str]:
        """List all available knowledge bases from kb_config.json"""
        # Always reload config from file to ensure we have the latest data
        # This is important when new KBs are created by other processes/requests
        self.config = self._load_config()

        # Read knowledge base list from config file (this is the authoritative source)
        # Return all KBs in config, regardless of directory status
        # (status field indicates if KB is ready or still initializing)
        config_kbs = self.config.get("knowledge_bases", {})
        kb_list = list(config_kbs.keys())

        # If no config file or config is empty, fallback to scanning directory (backward compatibility)
        if not kb_list and self.base_dir.exists():
            for item in self.base_dir.iterdir():
                if item.is_dir() and item.name != "__pycache__":
                    metadata_file = item / "metadata.json"
                    if metadata_file.exists():
                        kb_list.append(item.name)

        return sorted(kb_list)

    def register_knowledge_base(self, name: str, description: str = "", set_default: bool = False):
        """Register a knowledge base"""
        kb_dir = self.base_dir / name
        if not kb_dir.exists():
            raise ValueError(f"Knowledge base directory does not exist: {kb_dir}")

        if "knowledge_bases" not in self.config:
            self.config["knowledge_bases"] = {}

        self.config["knowledge_bases"][name] = {"path": name, "description": description}

        # Only set default if explicitly requested
        if set_default:
            self.set_default(name)

        self._save_config()

    def get_knowledge_base_path(self, name: str | None = None) -> Path:
        """Get path to a knowledge base"""
        if name is None:
            name = self.config.get("default")
            if name is None:
                raise ValueError("No default knowledge base set")

        kb_dir = self.base_dir / name
        if not kb_dir.exists():
            raise ValueError(f"Knowledge base not found: {name}")

        return kb_dir

    def get_rag_storage_path(self, name: str | None = None) -> Path:
        """Get RAG storage path for a knowledge base"""
        kb_dir = self.get_knowledge_base_path(name)
        rag_storage = kb_dir / "rag_storage"
        if not rag_storage.exists():
            raise ValueError(f"RAG storage not found for knowledge base: {name or 'default'}")
        return rag_storage

    def get_images_path(self, name: str | None = None) -> Path:
        """Get images path for a knowledge base"""
        kb_dir = self.get_knowledge_base_path(name)
        return kb_dir / "images"

    def get_content_list_path(self, name: str | None = None) -> Path:
        """Get content list path for a knowledge base"""
        kb_dir = self.get_knowledge_base_path(name)
        return kb_dir / "content_list"

    def get_raw_path(self, name: str | None = None) -> Path:
        """Get raw documents path for a knowledge base"""
        kb_dir = self.get_knowledge_base_path(name)
        return kb_dir / "raw"

    def set_default(self, name: str):
        """Set default knowledge base using centralized config service."""
        if name not in self.list_knowledge_bases():
            raise ValueError(f"Knowledge base not found: {name}")

        # Use centralized config service only (no longer stored in kb_config.json)
        try:
            from src.services.config import get_kb_config_service

            kb_config_service = get_kb_config_service()
            kb_config_service.set_default_kb(name)
        except Exception as e:
            print(f"Warning: Failed to save default to centralized config: {e}")

    def get_default(self) -> str | None:
        """
        Get default knowledge base name.

        Priority:
        1. Centralized config service (knowledge_base_configs.json)
        2. First knowledge base in the list (auto-fallback)
        """
        # Try centralized config first
        try:
            from src.services.config import get_kb_config_service

            kb_config_service = get_kb_config_service()
            default_kb = kb_config_service.get_default_kb()
            if default_kb and default_kb in self.list_knowledge_bases():
                return default_kb
        except Exception:
            pass

        # Fallback to first knowledge base in sorted list
        kb_list = self.list_knowledge_bases()
        if kb_list:
            return kb_list[0]

        return None

    def get_metadata(self, name: str | None = None) -> dict:
        """Get knowledge base metadata"""
        kb_dir = self.get_knowledge_base_path(name)
        metadata_file = kb_dir / "metadata.json"

        if metadata_file.exists():
            with open(metadata_file, encoding="utf-8") as f:
                return json.load(f)

        return {}

    def get_info(self, name: str | None = None) -> dict:
        """Get detailed information about a knowledge base.

        This method:
        1. Gets the KB name (from parameter or default)
        2. Reads status and progress from kb_config.json
        3. Reads metadata.json from the KB directory (if exists)
        4. Collects statistics about files and RAG status
        """
        # Reload config to get latest status
        self.config = self._load_config()

        kb_name = name or self.get_default()
        if kb_name is None:
            raise ValueError("No knowledge base name provided and no default set")

        # Get knowledge base path
        kb_dir = self.base_dir / kb_name

        # Get status and progress from kb_config.json
        kb_config = self.config.get("knowledge_bases", {}).get(kb_name, {})
        status = kb_config.get("status")
        progress = kb_config.get("progress")

        # KB might not have a directory yet if still initializing
        dir_exists = kb_dir.exists()

        # For old KBs without status field, determine status from rag_storage
        if not status and dir_exists:
            rag_storage_dir = kb_dir / "rag_storage"
            if rag_storage_dir.exists() and any(rag_storage_dir.iterdir()):
                status = "ready"
            else:
                status = "unknown"
        elif not status:
            status = "unknown"

        info = {
            "name": kb_name,
            "path": str(kb_dir),
            "is_default": kb_name == self.get_default(),
            "metadata": {},
            "status": status,
            "progress": progress,
        }

        # Read metadata.json (if exists)
        if dir_exists:
            metadata_file = kb_dir / "metadata.json"
            if metadata_file.exists():
                try:
                    with open(metadata_file, encoding="utf-8") as f:
                        info["metadata"] = json.load(f)
                except Exception as e:
                    print(f"Warning: Failed to read metadata.json for KB '{kb_name}': {e}")
                    info["metadata"] = {}

        # Count files - handle errors gracefully
        raw_dir = kb_dir / "raw" if dir_exists else None
        images_dir = kb_dir / "images" if dir_exists else None
        content_list_dir = kb_dir / "content_list" if dir_exists else None
        rag_storage_dir = kb_dir / "rag_storage" if dir_exists else None

        raw_count = 0
        images_count = 0
        content_lists_count = 0

        if dir_exists:
            try:
                raw_count = (
                    len([f for f in raw_dir.iterdir() if f.is_file()]) if raw_dir.exists() else 0
                )
            except Exception:
                pass

            try:
                images_count = (
                    len([f for f in images_dir.iterdir() if f.is_file()])
                    if images_dir.exists()
                    else 0
                )
            except Exception:
                pass

            try:
                content_lists_count = (
                    len(list(content_list_dir.glob("*.json"))) if content_list_dir.exists() else 0
                )
            except Exception:
                pass

        metadata = info["metadata"]
        rag_provider = metadata.get("rag_provider") if isinstance(metadata, dict) else None
        # Also check kb_config for rag_provider (fallback)
        if not rag_provider:
            rag_provider = kb_config.get("rag_provider")

        rag_initialized = (
            dir_exists and rag_storage_dir and rag_storage_dir.exists() and rag_storage_dir.is_dir()
        )

        info["statistics"] = {
            "raw_documents": raw_count,
            "images": images_count,
            "content_lists": content_lists_count,
            "rag_initialized": rag_initialized,
            "rag_provider": rag_provider,
            # Include status and progress in statistics for backward compatibility
            "status": status,
            "progress": progress,
        }

        # Try to get RAG statistics
        if rag_initialized:
            try:
                entities_file = rag_storage_dir / "kv_store_full_entities.json"
                relations_file = rag_storage_dir / "kv_store_full_relations.json"
                chunks_file = rag_storage_dir / "kv_store_text_chunks.json"

                rag_stats = {}
                if entities_file.exists():
                    try:
                        with open(entities_file, encoding="utf-8") as f:
                            entities_data = json.load(f)
                            rag_stats["entities"] = (
                                len(entities_data) if isinstance(entities_data, (list, dict)) else 0
                            )
                    except Exception:
                        pass

                if relations_file.exists():
                    try:
                        with open(relations_file, encoding="utf-8") as f:
                            relations_data = json.load(f)
                            rag_stats["relations"] = (
                                len(relations_data)
                                if isinstance(relations_data, (list, dict))
                                else 0
                            )
                    except Exception:
                        pass

                if chunks_file.exists():
                    try:
                        with open(chunks_file, encoding="utf-8") as f:
                            chunks_data = json.load(f)
                            rag_stats["chunks"] = (
                                len(chunks_data) if isinstance(chunks_data, (list, dict)) else 0
                            )
                    except Exception:
                        pass

                if rag_stats:
                    statistics = info["statistics"]
                    if isinstance(statistics, dict):
                        statistics["rag"] = rag_stats
            except Exception:
                pass

        return info

    def delete_knowledge_base(self, name: str, confirm: bool = False) -> bool:
        """
        Delete a knowledge base

        Args:
            name: Knowledge base name
            confirm: If True, skip confirmation (use with caution!)

        Returns:
            True if deleted successfully
        """
        if name not in self.list_knowledge_bases():
            raise ValueError(f"Knowledge base not found: {name}")

        kb_dir = self.get_knowledge_base_path(name)

        if not confirm:
            # Ask for confirmation in CLI
            print(f"⚠️  Warning: This will permanently delete the knowledge base '{name}'")
            print(f"   Path: {kb_dir}")
            response = input("Are you sure? Type 'yes' to confirm: ")
            if response.lower() != "yes":
                print("Deletion cancelled.")
                return False

        # Delete the directory
        shutil.rmtree(kb_dir)

        # Remove from config
        if name in self.config.get("knowledge_bases", {}):
            del self.config["knowledge_bases"][name]

        # Update default if this was the default
        if self.config.get("default") == name:
            remaining = self.list_knowledge_bases()
            self.config["default"] = remaining[0] if remaining else None

        self._save_config()
        return True

    def clean_rag_storage(self, name: str | None = None, backup: bool = True) -> bool:
        """
        Clean (delete) RAG storage for a knowledge base
        Useful when RAG data is corrupted

        Args:
            name: Knowledge base name (default if not specified)
            backup: If True, backup the RAG storage before deleting

        Returns:
            True if cleaned successfully
        """
        kb_name = name or self.get_default()
        kb_dir = self.get_knowledge_base_path(kb_name)
        rag_storage_dir = kb_dir / "rag_storage"

        if not rag_storage_dir.exists():
            print(f"RAG storage does not exist for '{kb_name}'")
            return False

        # Backup if requested
        if backup:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_dir = kb_dir / f"rag_storage_backup_{timestamp}"
            shutil.copytree(rag_storage_dir, backup_dir)
            print(f"✓ Backed up to: {backup_dir}")

        # Delete RAG storage
        shutil.rmtree(rag_storage_dir)
        rag_storage_dir.mkdir(parents=True, exist_ok=True)

        print(f"✓ RAG storage cleaned for '{kb_name}'")
        return True

    def link_folder(self, kb_name: str, folder_path: str) -> dict:
        """
        Link a local folder to a knowledge base.

        Args:
            kb_name: Knowledge base name
            folder_path: Path to local folder (supports ~, relative paths)

        Returns:
            Dict with folder info including id, path, and file count

        Raises:
            ValueError: If KB not found or folder doesn't exist
        """
        if kb_name not in self.list_knowledge_bases():
            raise ValueError(f"Knowledge base not found: {kb_name}")

        # Normalize path (cross-platform: handles ~, relative paths, etc.)
        folder = Path(folder_path).expanduser().resolve()

        if not folder.exists():
            raise ValueError(f"Folder does not exist: {folder}")
        if not folder.is_dir():
            raise ValueError(f"Path is not a directory: {folder}")

        # Get RAG provider from KB metadata to determine supported extensions
        kb_dir = self.base_dir / kb_name
        metadata_file = kb_dir / "metadata.json"
        provider = "raganything"  # default to most comprehensive
        if metadata_file.exists():
            try:
                with open(metadata_file, encoding="utf-8") as f:
                    kb_meta = json.load(f)
                    provider = kb_meta.get("rag_provider") or "raganything"
            except Exception:
                pass

        # Get supported files in folder based on provider
        supported_extensions = FileTypeRouter.get_extensions_for_provider(provider)
        files: list[Path] = []
        for ext in supported_extensions:
            files.extend(folder.glob(f"**/*{ext}"))

        # Generate folder ID

        folder_id = hashlib.md5(  # noqa: S324
            str(folder).encode(), usedforsecurity=False
        ).hexdigest()[:8]

        # Load existing linked folders from metadata
        kb_dir = self.base_dir / kb_name
        metadata_file = kb_dir / "metadata.json"
        metadata: dict = {}

        if metadata_file.exists():
            try:
                with open(metadata_file, encoding="utf-8") as fp:
                    metadata = json.load(fp)
            except Exception:
                metadata = {}

        if "linked_folders" not in metadata:
            metadata["linked_folders"] = []

        # Check if already linked
        existing_ids = [item["id"] for item in metadata.get("linked_folders", [])]
        if folder_id in existing_ids:
            # If already linked, treat as success (idempotent)
            # Find and return existing info
            for item in metadata.get("linked_folders", []):
                if item["id"] == folder_id:
                    return item

        # Add folder info
        folder_info = {
            "id": folder_id,
            "path": str(folder),
            "added_at": datetime.now().isoformat(),
            "file_count": len(files),
        }
        metadata["linked_folders"].append(folder_info)

        # Save metadata
        with open(metadata_file, "w", encoding="utf-8") as fp:
            json.dump(metadata, fp, indent=2, ensure_ascii=False)

        return folder_info

    def get_linked_folders(self, kb_name: str) -> list[dict]:
        """
        Get list of linked folders for a knowledge base.

        Args:
            kb_name: Knowledge base name

        Returns:
            List of linked folder info dicts
        """
        if kb_name not in self.list_knowledge_bases():
            raise ValueError(f"Knowledge base not found: {kb_name}")

        kb_dir = self.base_dir / kb_name
        metadata_file = kb_dir / "metadata.json"

        if not metadata_file.exists():
            return []

        try:
            with open(metadata_file, encoding="utf-8") as f:
                metadata = json.load(f)
                return metadata.get("linked_folders", [])
        except Exception:
            return []

    def unlink_folder(self, kb_name: str, folder_id: str) -> bool:
        """
        Unlink a folder from a knowledge base.

        Args:
            kb_name: Knowledge base name
            folder_id: Folder ID to unlink

        Returns:
            True if unlinked successfully, False if not found
        """
        if kb_name not in self.list_knowledge_bases():
            raise ValueError(f"Knowledge base not found: {kb_name}")

        kb_dir = self.base_dir / kb_name
        metadata_file = kb_dir / "metadata.json"

        if not metadata_file.exists():
            return False

        try:
            with open(metadata_file, encoding="utf-8") as f:
                metadata = json.load(f)
        except Exception:
            return False

        linked = metadata.get("linked_folders", [])
        new_linked = [f for f in linked if f["id"] != folder_id]

        if len(new_linked) == len(linked):
            return False  # Not found

        metadata["linked_folders"] = new_linked

        with open(metadata_file, "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2, ensure_ascii=False)

        return True

    def scan_linked_folder(self, folder_path: str, provider: str = "raganything") -> list[str]:
        """
        Scan a linked folder and return list of supported file paths.

        Args:
            folder_path: Path to folder
            provider: RAG provider to determine supported extensions (default: raganything)

        Returns:
            List of file paths (as strings)
        """
        folder = Path(folder_path).expanduser().resolve()

        if not folder.exists() or not folder.is_dir():
            return []

        supported_extensions = FileTypeRouter.get_extensions_for_provider(provider)
        files = []

        for ext in supported_extensions:
            for file_path in folder.glob(f"**/*{ext}"):
                files.append(str(file_path))

        return sorted(files)

    def detect_folder_changes(self, kb_name: str, folder_id: str) -> dict:
        """
        Detect new and modified files in a linked folder since last sync.

        This enables automatic sync of changes from local folders that may
        be synced with cloud services like SharePoint, Google Drive, etc.

        Args:
            kb_name: Knowledge base name
            folder_id: Folder ID to check for changes

        Returns:
            Dict with 'new_files', 'modified_files', and 'has_changes' keys
        """
        if kb_name not in self.list_knowledge_bases():
            raise ValueError(f"Knowledge base not found: {kb_name}")

        # Get folder info
        folders = self.get_linked_folders(kb_name)
        folder_info = next((f for f in folders if f["id"] == folder_id), None)

        if not folder_info:
            raise ValueError(f"Linked folder not found: {folder_id}")

        folder_path = Path(folder_info["path"]).expanduser().resolve()
        last_sync = folder_info.get("last_sync")
        synced_files = folder_info.get("synced_files", {})

        # Parse last sync timestamp
        last_sync_time = None
        if last_sync:
            try:
                last_sync_time = datetime.fromisoformat(last_sync)
            except Exception:
                pass

        # Get RAG provider from KB metadata to determine supported extensions
        kb_dir = self.base_dir / kb_name
        metadata_file = kb_dir / "metadata.json"
        provider = "raganything"  # default to most comprehensive
        if metadata_file.exists():
            try:
                with open(metadata_file, encoding="utf-8") as f:
                    metadata = json.load(f)
                    provider = metadata.get("rag_provider") or "raganything"
            except Exception:
                pass

        # Scan current files based on provider's supported extensions
        supported_extensions = FileTypeRouter.get_extensions_for_provider(provider)
        new_files = []
        modified_files = []

        for ext in supported_extensions:
            for file_path in folder_path.glob(f"**/*{ext}"):
                file_str = str(file_path)
                file_mtime = datetime.fromtimestamp(file_path.stat().st_mtime)

                if file_str in synced_files:
                    # Check if modified since last sync
                    prev_mtime_str = synced_files[file_str]
                    try:
                        prev_mtime = datetime.fromisoformat(prev_mtime_str)
                        if file_mtime > prev_mtime:
                            modified_files.append(file_str)
                    except Exception:
                        modified_files.append(file_str)
                else:
                    # New file (not in synced files)
                    new_files.append(file_str)

        return {
            "new_files": sorted(new_files),
            "modified_files": sorted(modified_files),
            "has_changes": len(new_files) > 0 or len(modified_files) > 0,
            "new_count": len(new_files),
            "modified_count": len(modified_files),
        }

    def update_folder_sync_state(self, kb_name: str, folder_id: str, synced_files: list[str]):
        """
        Update the sync state for a linked folder after successful sync.

        Records which files were synced and their modification times,
        enabling future change detection.

        Args:
            kb_name: Knowledge base name
            folder_id: Folder ID
            synced_files: List of file paths that were successfully synced
        """
        if kb_name not in self.list_knowledge_bases():
            raise ValueError(f"Knowledge base not found: {kb_name}")

        kb_dir = self.base_dir / kb_name
        metadata_file = kb_dir / "metadata.json"

        if not metadata_file.exists():
            return

        try:
            with open(metadata_file, encoding="utf-8") as f:
                metadata = json.load(f)
        except Exception:
            return

        linked = metadata.get("linked_folders", [])

        for folder in linked:
            if folder["id"] == folder_id:
                # Record sync timestamp
                folder["last_sync"] = datetime.now().isoformat()

                # Record file modification times
                file_states = folder.get("synced_files", {})
                for file_path in synced_files:
                    try:
                        p = Path(file_path)
                        if p.exists():
                            mtime = datetime.fromtimestamp(p.stat().st_mtime)
                            file_states[file_path] = mtime.isoformat()
                    except Exception:
                        pass

                folder["synced_files"] = file_states
                folder["file_count"] = len(file_states)
                break


def main():
    """Command-line interface for knowledge base manager"""
    import argparse

    parser = argparse.ArgumentParser(description="Knowledge Base Manager")
    parser.add_argument(
        "--base-dir", default="./knowledge_bases", help="Base directory for knowledge bases"
    )

    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # List command
    subparsers.add_parser("list", help="List all knowledge bases")

    # Info command
    info_parser = subparsers.add_parser("info", help="Show knowledge base information")
    info_parser.add_argument(
        "name", nargs="?", help="Knowledge base name (default if not specified)"
    )

    # Set default command
    default_parser = subparsers.add_parser("set-default", help="Set default knowledge base")
    default_parser.add_argument("name", help="Knowledge base name")

    # Delete command
    delete_parser = subparsers.add_parser("delete", help="Delete a knowledge base")
    delete_parser.add_argument("name", help="Knowledge base name")
    delete_parser.add_argument("--force", action="store_true", help="Skip confirmation")

    # Clean RAG command
    clean_parser = subparsers.add_parser(
        "clean-rag", help="Clean RAG storage (useful for corrupted data)"
    )
    clean_parser.add_argument(
        "name", nargs="?", help="Knowledge base name (default if not specified)"
    )
    clean_parser.add_argument(
        "--no-backup", action="store_true", help="Don't backup before cleaning"
    )

    args = parser.parse_args()

    manager = KnowledgeBaseManager(args.base_dir)

    if args.command == "list":
        kb_list = manager.list_knowledge_bases()
        default_kb = manager.get_default()

        print("\nAvailable Knowledge Bases:")
        print("=" * 60)
        if not kb_list:
            print("No knowledge bases found")
        else:
            for kb_name in kb_list:
                default_marker = " (default)" if kb_name == default_kb else ""
                print(f"  • {kb_name}{default_marker}")
        print()

    elif args.command == "info":
        try:
            info = manager.get_info(args.name)

            print("\nKnowledge Base Information:")
            print("=" * 60)
            print(f"Name: {info['name']}")
            print(f"Path: {info['path']}")
            print(f"Default: {'Yes' if info['is_default'] else 'No'}")

            if info.get("metadata"):
                print("\nMetadata:")
                for key, value in info["metadata"].items():
                    print(f"  {key}: {value}")

            print("\nStatistics:")
            stats = info["statistics"]
            print(f"  Raw documents: {stats['raw_documents']}")
            print(f"  Images: {stats['images']}")
            print(f"  Content lists: {stats['content_lists']}")
            print(f"  RAG initialized: {'Yes' if stats['rag_initialized'] else 'No'}")

            if "rag" in stats:
                print("\n  RAG Statistics:")
                for key, value in stats["rag"].items():
                    print(f"    {key}: {value}")

            print()
        except Exception as e:
            print(f"Error: {e!s}")

    elif args.command == "set-default":
        try:
            manager.set_default(args.name)
            print(f"✓ Set '{args.name}' as default knowledge base")
        except Exception as e:
            print(f"Error: {e!s}")

    elif args.command == "delete":
        try:
            success = manager.delete_knowledge_base(args.name, confirm=args.force)
            if success:
                print(f"✓ Deleted knowledge base '{args.name}'")
        except Exception as e:
            print(f"Error: {e!s}")

    elif args.command == "clean-rag":
        try:
            manager.clean_rag_storage(args.name, backup=not args.no_backup)
        except Exception as e:
            print(f"Error: {e!s}")

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
