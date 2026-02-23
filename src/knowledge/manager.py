#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Knowledge Base Manager

Manages multiple knowledge bases and provides utilities for accessing them.
"""

from datetime import datetime
import json
from pathlib import Path
import shutil


class KnowledgeBaseManager:
    """Manager for knowledge bases"""

    def __init__(self, base_dir="./data/knowledge_bases"):
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

        # Config file to track knowledge bases
        self.config_file = self.base_dir / "kb_config.json"
        self.config = self._load_config()

    def _load_config(self) -> dict:
        """Load knowledge base configuration"""
        if self.config_file.exists():
            with open(self.config_file, encoding="utf-8") as f:
                return json.load(f)
        return {"knowledge_bases": {}, "default": None}

    def _save_config(self):
        """Save knowledge base configuration"""
        with open(self.config_file, "w", encoding="utf-8") as f:
            json.dump(self.config, f, indent=2, ensure_ascii=False)

    def _metadata_path(self, name: str) -> Path:
        kb_dir = self.get_knowledge_base_path(name)
        return kb_dir / "metadata.json"

    def list_knowledge_bases(self) -> list[str]:
        """List all available knowledge bases from kb_config.json"""
        kb_list = []

        # Read knowledge base list from config file (this is the authoritative source)
        config_kbs = self.config.get("knowledge_bases", {})

        for kb_name in config_kbs.keys():
            # Verify knowledge base directory exists
            kb_dir = self.base_dir / kb_name
            if kb_dir.exists() and kb_dir.is_dir():
                kb_list.append(kb_name)
            else:
                # If in config but directory doesn't exist, log warning but don't add
                print(
                    f"Warning: Knowledge base '{kb_name}' is in config but directory does not exist: {kb_dir}"
                )

        # Always scan the directory for valid knowledge base directories as a fallback
        # and merge them with those from the config file
        if self.base_dir.exists():
            for item in self.base_dir.iterdir():
                if item.is_dir() and item.name != "__pycache__":
                    if item.name not in kb_list:
                        metadata_file = item / "metadata.json"
                        if metadata_file.exists():
                            kb_list.append(item.name)

        return sorted(kb_list)

    def create_knowledge_base(self, name: str, description: str = "", set_default: bool = False):
        """Create a new knowledge base"""
        kb_dir = self.base_dir / name
        if kb_dir.exists():
            # If it exists, just register it
            pass
        else:
            kb_dir.mkdir(parents=True, exist_ok=True)
            # Create subdirectories
            (kb_dir / "raw").mkdir(exist_ok=True)
            (kb_dir / "images").mkdir(exist_ok=True)
            (kb_dir / "rag_storage").mkdir(exist_ok=True)
            (kb_dir / "content_list").mkdir(exist_ok=True)

            # Create metadata file
            metadata = {
                "name": name,
                "display_name": name,
                "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "description": description,
                "version": "1.0",
                "system_managed": False,
            }
            with open(kb_dir / "metadata.json", "w", encoding="utf-8") as f:
                json.dump(metadata, f, indent=2, ensure_ascii=False)

        self.register_knowledge_base(name, description, set_default)
        return str(kb_dir)

    def register_knowledge_base(self, name: str, description: str = "", set_default: bool = False):
        """Register a knowledge base"""
        kb_dir = self.base_dir / name
        if not kb_dir.exists():
            raise ValueError(f"Knowledge base directory does not exist: {kb_dir}")

        if "knowledge_bases" not in self.config:
            self.config["knowledge_bases"] = {}

        self.config["knowledge_bases"][name] = {"path": name, "description": description}

        if set_default or not self.config.get("default"):
            self.config["default"] = name

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
        """Set default knowledge base"""
        if name not in self.list_knowledge_bases():
            raise ValueError(f"Knowledge base not found: {name}")

        self.config["default"] = name
        self._save_config()

    def get_default(self) -> str | None:
        """Get default knowledge base name"""
        return self.config.get("default")

    def get_metadata(self, name: str | None = None) -> dict:
        """Get knowledge base metadata"""
        kb_dir = self.get_knowledge_base_path(name)
        metadata_file = kb_dir / "metadata.json"

        if metadata_file.exists():
            with open(metadata_file, encoding="utf-8") as f:
                return json.load(f)

        return {}

    def update_metadata_fields(self, name: str, updates: dict) -> dict:
        """Update metadata.json fields for a knowledge base."""
        if not isinstance(updates, dict):
            raise ValueError("updates must be a dict")

        metadata = self.get_metadata(name)
        metadata.update(updates)
        metadata.setdefault("name", name)

        metadata_path = self._metadata_path(name)
        with open(metadata_path, "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2, ensure_ascii=False)

        return metadata

    def update_display_name(self, name: str, display_name: str) -> dict:
        """Update only the display name of a knowledge base."""
        cleaned = (display_name or "").strip()
        if not cleaned:
            raise ValueError("display_name cannot be empty")
        return self.update_metadata_fields(name, {"display_name": cleaned})

    def get_info(self, name: str | None = None) -> dict:
        """Get detailed information about a knowledge base.

        This method:
        1. Gets the KB name (from parameter or default)
        2. Reads metadata.json from the KB directory
        3. Collects statistics about files and RAG status
        """
        kb_name = name or self.get_default()
        if kb_name is None:
            raise ValueError("No knowledge base name provided and no default set")

        # Get knowledge base path
        kb_dir = self.base_dir / kb_name
        if not kb_dir.exists():
            raise ValueError(f"Knowledge base directory does not exist: {kb_dir}")

        # Verify knowledge base is in config (if not, give warning but don't block)
        if kb_name not in self.config.get("knowledge_bases", {}):
            print(
                f"Warning: Knowledge base '{kb_name}' is not in kb_config.json, but directory exists"
            )

        info = {
            "name": kb_name,
            "path": str(kb_dir),
            "is_default": kb_name == self.get_default(),
            "metadata": {},
        }

        # Read metadata.json (if exists)
        metadata_file = kb_dir / "metadata.json"
        if metadata_file.exists():
            try:
                with open(metadata_file, encoding="utf-8") as f:
                    info["metadata"] = json.load(f)
            except Exception as e:
                print(f"Warning: Failed to read metadata.json for KB '{kb_name}': {e}")
                info["metadata"] = {}
        else:
            # metadata.json doesn't exist, use empty dict
            info["metadata"] = {}

        metadata = info["metadata"] if isinstance(info["metadata"], dict) else {}
        owner = metadata.get("owner") if isinstance(metadata.get("owner"), dict) else None
        info["display_name"] = metadata.get("display_name") or kb_name
        info["system_managed"] = bool(metadata.get("system_managed", False))
        info["owner"] = owner

        # Count files - handle errors gracefully
        raw_dir = kb_dir / "raw"
        images_dir = kb_dir / "images"
        content_list_dir = kb_dir / "content_list"
        rag_storage_dir = kb_dir / "rag_storage"

        try:
            raw_count = (
                len([f for f in raw_dir.iterdir() if f.is_file()]) if raw_dir.exists() else 0
            )
        except Exception:
            raw_count = 0

        try:
            images_count = (
                len([f for f in images_dir.iterdir() if f.is_file()]) if images_dir.exists() else 0
            )
        except Exception:
            images_count = 0

        try:
            content_lists_count = (
                len(list(content_list_dir.glob("*.json"))) if content_list_dir.exists() else 0
            )
        except Exception:
            content_lists_count = 0

        info["statistics"] = {
            "raw_documents": raw_count,
            "images": images_count,
            "content_lists": content_lists_count,
            "rag_initialized": rag_storage_dir.exists() and rag_storage_dir.is_dir(),
        }

        # Try to get RAG statistics
        if rag_storage_dir.exists() and rag_storage_dir.is_dir():
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
                    info["statistics"]["rag"] = rag_stats
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
