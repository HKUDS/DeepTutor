"""
Notebook Manager - Manages user notebooks and records
All notebook data is stored in user/notebook/ directory
"""

from enum import Enum
import json
from pathlib import Path
import time
import uuid

from pydantic import BaseModel


class RecordType(str, Enum):
    """Record type"""

    SOLVE = "solve"
    QUESTION = "question"
    RESEARCH = "research"
    CO_WRITER = "co_writer"
    CHAT = "chat"
    NOTE = "note"


class NotebookRecord(BaseModel):
    """Single record in notebook"""

    id: str
    type: RecordType
    title: str
    user_query: str
    output: str
    metadata: dict = {}
    created_at: float
    kb_name: str | None = None


class Notebook(BaseModel):
    """Notebook model"""

    id: str
    name: str
    description: str = ""
    created_at: float
    updated_at: float
    records: list[NotebookRecord] = []
    color: str = "#3B82F6"  # Default blue
    icon: str = "book"  # Default icon


class NotebookManager:
    """Notebook manager"""

    def __init__(self, base_dir: str | None = None):
        """
        Initialize notebook manager

        Args:
            base_dir: Notebook storage directory, defaults to project root/user/notebook
        """
        if base_dir is None:
            # Current file: DeepTutor/src/api/utils/notebook_manager.py
            # Project root should be three levels up: DeepTutor/
            project_root = Path(__file__).resolve().parents[3]
            base_dir_path = project_root / "data" / "user" / "notebook"
        else:
            base_dir_path = Path(base_dir)

        self.base_dir = base_dir_path
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.sessions_dir = self.base_dir / "sessions"
        self.sessions_dir.mkdir(parents=True, exist_ok=True)

        # Notebook index file
        self.index_file = self.base_dir / "notebooks_index.json"
        self._ensure_index()

    def _ensure_index(self):
        """Ensure index file exists"""
        if not self.index_file.exists():
            with open(self.index_file, "w", encoding="utf-8") as f:
                json.dump({"notebooks": []}, f, indent=2, ensure_ascii=False)

    def _load_index(self) -> dict:
        """Load index"""
        try:
            with open(self.index_file, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {"notebooks": []}

    def _save_index(self, index: dict):
        """Save index"""
        with open(self.index_file, "w", encoding="utf-8") as f:
            json.dump(index, f, indent=2, ensure_ascii=False)

    def _get_notebook_file(self, notebook_id: str) -> Path:
        """Get notebook file path"""
        return self.base_dir / f"{notebook_id}.json"

    def _get_sessions_file(self, notebook_id: str) -> Path:
        """Get notebook sessions file path"""
        return self.sessions_dir / f"{notebook_id}.json"

    def _load_notebook(self, notebook_id: str) -> dict | None:
        """Load single notebook"""
        filepath = self._get_notebook_file(notebook_id)
        if not filepath.exists():
            return None
        try:
            with open(filepath, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None

    def _save_notebook(self, notebook: dict):
        """Save single notebook"""
        filepath = self._get_notebook_file(notebook["id"])
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(notebook, f, indent=2, ensure_ascii=False)

    def _load_sessions(self, notebook_id: str) -> dict:
        """Load sessions for a notebook"""
        filepath = self._get_sessions_file(notebook_id)
        if not filepath.exists():
            return {"sessions": []}
        try:
            with open(filepath, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {"sessions": []}

    def _save_sessions(self, notebook_id: str, data: dict):
        """Save sessions for a notebook"""
        filepath = self._get_sessions_file(notebook_id)
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    @staticmethod
    def _derive_session_title(session: dict) -> str:
        created_at = session.get("created_at") or time.time()
        time_label = time.strftime("%Y-%m-%d %H:%M", time.localtime(created_at))
        messages = session.get("messages", []) or []
        for msg in messages:
            if msg.get("role") == "user" and msg.get("content"):
                title = " ".join(msg["content"].split())
                short = title[:40] + "..." if len(title) > 40 else title
                return f"{time_label} · {short}"
        return time_label

    def list_sessions(self, notebook_id: str) -> list[dict]:
        """List all sessions for a notebook"""
        data = self._load_sessions(notebook_id)
        sessions = data.get("sessions", [])
        sessions.sort(key=lambda s: s.get("created_at", 0))
        return sessions

    def get_latest_session(self, notebook_id: str) -> dict | None:
        """Get latest session by updated_at"""
        sessions = self._load_sessions(notebook_id).get("sessions", [])
        if not sessions:
            return None
        return max(sessions, key=lambda s: s.get("updated_at", 0))

    def upsert_session(self, notebook_id: str, session: dict) -> dict:
        """Create or update a session for a notebook"""
        data = self._load_sessions(notebook_id)
        sessions = data.get("sessions", [])

        session_id = session.get("session_id") or session.get("id") or str(uuid.uuid4())[:8]
        now = time.time()

        existing_index = next(
            (idx for idx, s in enumerate(sessions) if s.get("session_id") == session_id), None
        )

        created_at = session.get("created_at")
        existing = sessions[existing_index] if existing_index is not None else {}
        if existing_index is not None:
            created_at = sessions[existing_index].get("created_at", created_at)

        incoming_title = session.get("title")
        if incoming_title == "未命名会话":
            incoming_title = None
        incoming_report = session.get("research_report")
        if existing and not incoming_report and existing.get("research_report"):
            incoming_report = existing.get("research_report")
        incoming_studio_state = session.get("studio_state")
        if "studio_state" not in session and existing:
            incoming_studio_state = existing.get("studio_state")
        incoming_messages = session.get("messages", [])
        if existing:
            existing_messages = existing.get("messages", [])
            existing_has_report = any(
                isinstance(msg.get("content"), str) and "📚 深度研究完成" in msg.get("content", "")
                for msg in existing_messages
            )
            incoming_has_report = any(
                isinstance(msg.get("content"), str) and "📚 深度研究完成" in msg.get("content", "")
                for msg in incoming_messages
            )
            if existing_has_report and not incoming_has_report:
                incoming_messages = existing_messages
        incoming_sources = session.get("sources", [])
        if existing:
            existing_report_sources = [
                source for source in existing.get("sources", []) if source.get("type") == "report"
            ]
            incoming_has_report = any(source.get("type") == "report" for source in incoming_sources)
            if existing_report_sources and not incoming_has_report:
                incoming_sources = [*incoming_sources, *existing_report_sources]
        merged = {
            "session_id": session_id,
            "title": incoming_title or self._derive_session_title(session),
            "messages": incoming_messages,
            "sources": incoming_sources,
            "research_report": incoming_report,
            "research_state": session.get("research_state"),
            "studio_state": incoming_studio_state,
            "created_at": created_at or now,
            "updated_at": session.get("updated_at") or now,
        }

        if existing_index is None:
            sessions.append(merged)
        else:
            sessions[existing_index] = merged

        data["sessions"] = sessions
        self._save_sessions(notebook_id, data)
        return merged

    # === Notebook Operations ===

    def create_notebook(
        self, name: str, description: str = "", color: str = "#3B82F6", icon: str = "book"
    ) -> dict:
        """
        Create new notebook

        Args:
            name: Notebook name
            description: Notebook description
            color: Color code
            icon: Icon name

        Returns:
            Created notebook information
        """
        notebook_id = str(uuid.uuid4())[:8]
        now = time.time()

        notebook = {
            "id": notebook_id,
            "name": name,
            "description": description,
            "created_at": now,
            "updated_at": now,
            "records": [],
            "color": color,
            "icon": icon,
        }

        # Save notebook file
        self._save_notebook(notebook)

        # Update index
        index = self._load_index()
        index["notebooks"].append(
            {
                "id": notebook_id,
                "name": name,
                "description": description,
                "created_at": now,
                "updated_at": now,
                "record_count": 0,
                "color": color,
                "icon": icon,
            }
        )
        self._save_index(index)

        return notebook

    def list_notebooks(self) -> list[dict]:
        """
        List all notebooks (summary information)

        Returns:
            Notebook list
        """
        index = self._load_index()
        notebooks = []

        for nb_info in index.get("notebooks", []):
            # Get latest information from actual file
            notebook = self._load_notebook(nb_info["id"])
            if notebook:
                notebooks.append(
                    {
                        "id": notebook["id"],
                        "name": notebook["name"],
                        "description": notebook.get("description", ""),
                        "created_at": notebook["created_at"],
                        "updated_at": notebook["updated_at"],
                        "record_count": len(notebook.get("records", [])),
                        "color": notebook.get("color", "#3B82F6"),
                        "icon": notebook.get("icon", "book"),
                    }
                )

        # Sort by update time
        notebooks.sort(key=lambda x: x["updated_at"], reverse=True)
        return notebooks

    def get_notebook(self, notebook_id: str) -> dict | None:
        """
        Get notebook details (includes all records)

        Args:
            notebook_id: Notebook ID

        Returns:
            Notebook details
        """
        return self._load_notebook(notebook_id)

    def update_notebook(
        self,
        notebook_id: str,
        name: str | None = None,
        description: str | None = None,
        color: str | None = None,
        icon: str | None = None,
    ) -> dict | None:
        """
        Update notebook information

        Args:
            notebook_id: Notebook ID
            name: New name
            description: New description
            color: New color
            icon: New icon

        Returns:
            Updated notebook information
        """
        notebook = self._load_notebook(notebook_id)
        if not notebook:
            return None

        if name is not None:
            notebook["name"] = name
        if description is not None:
            notebook["description"] = description
        if color is not None:
            notebook["color"] = color
        if icon is not None:
            notebook["icon"] = icon

        notebook["updated_at"] = time.time()
        self._save_notebook(notebook)

        # Update index
        index = self._load_index()
        for nb_info in index["notebooks"]:
            if nb_info["id"] == notebook_id:
                if name is not None:
                    nb_info["name"] = name
                if description is not None:
                    nb_info["description"] = description
                if color is not None:
                    nb_info["color"] = color
                if icon is not None:
                    nb_info["icon"] = icon
                nb_info["updated_at"] = notebook["updated_at"]
                break
        self._save_index(index)

        return notebook

    def delete_notebook(self, notebook_id: str) -> bool:
        """
        Delete notebook

        Args:
            notebook_id: Notebook ID

        Returns:
            Whether deletion was successful
        """
        filepath = self._get_notebook_file(notebook_id)
        if not filepath.exists():
            return False

        # Delete notebook file
        filepath.unlink()

        # Clean up associated session file
        sessions_file = self._get_sessions_file(notebook_id)
        if sessions_file.exists():
            sessions_file.unlink()

        # Clean up associated sources knowledge base
        try:
            from src.knowledge.manager import KnowledgeBaseManager

            # Get KB base dir (same logic as in notebook router)
            project_root = Path(__file__).resolve().parents[3]
            kb_base_dir = project_root / "data" / "knowledge_bases"
            kb_manager = KnowledgeBaseManager(base_dir=str(kb_base_dir))

            sources_kb_name = f"notebook_{notebook_id}_sources"
            if sources_kb_name in kb_manager.list_knowledge_bases():
                kb_manager.delete_knowledge_base(sources_kb_name, confirm=True)
        except Exception as e:
            # Log error but don't fail the deletion
            print(f"Warning: Failed to clean up sources KB for {notebook_id}: {e}")

        # Update index
        index = self._load_index()
        index["notebooks"] = [nb for nb in index["notebooks"] if nb["id"] != notebook_id]
        self._save_index(index)

        return True

    # === Record Operations ===

    def add_record(
        self,
        notebook_ids: list[str],
        record_type: RecordType,
        title: str,
        user_query: str,
        output: str,
        metadata: dict = None,
        kb_name: str = None,
    ) -> dict:
        """
        Add record to one or more notebooks

        Args:
            notebook_ids: Target notebook ID list
            record_type: Record type
            title: Title
            user_query: User input
            output: Output result
            metadata: Additional metadata
            kb_name: Knowledge base name

        Returns:
            Added record information
        """
        record_id = str(uuid.uuid4())[:8]
        now = time.time()

        record = {
            "id": record_id,
            "type": record_type,
            "title": title,
            "user_query": user_query,
            "output": output,
            "metadata": metadata or {},
            "created_at": now,
            "kb_name": kb_name,
        }

        kb_sync_info = None

        # Sync to User Notes KB if it's a note
        if record_type == RecordType.NOTE or record_type == "note":
            try:
                # Late import to avoid circular dependency
                from src.knowledge.manager import KnowledgeBaseManager
                
                # Get KB Manager
                # Use project root relative to this file
                project_root = Path(__file__).resolve().parents[3]
                kb_base_dir = project_root / "data" / "knowledge_bases"
                kb_manager = KnowledgeBaseManager(base_dir=str(kb_base_dir))
                
                kb_name = "User Notes"
                
                # Ensure KB exists
                if kb_name not in kb_manager.list_knowledge_bases():
                    kb_manager.create_knowledge_base(kb_name, description="Auto-generated from Notebook Notes")
                
                # Get raw directory
                kb_path = kb_manager.get_knowledge_base_path(kb_name)
                raw_dir = kb_path / "raw"
                raw_dir.mkdir(parents=True, exist_ok=True)
                
                # Create filename from title
                safe_title = "".join([c if c.isalnum() or c in "._- " else "_" for c in title])
                filename = f"{safe_title}_{int(now)}.md"
                file_path = raw_dir / filename
                
                # Save content
                content = f"# {title}\n\n{output}"
                with open(file_path, "w", encoding="utf-8") as f:
                    f.write(content)
                    
                kb_sync_info = {
                    "kb_name": kb_name,
                    "file_path": str(file_path),
                    "filename": filename
                }
            except Exception as e:
                print(f"Failed to sync note to KB: {e}")

        added_to = []
        for notebook_id in notebook_ids:
            notebook = self._load_notebook(notebook_id)
            if notebook:
                notebook["records"].append(record)
                notebook["updated_at"] = now
                self._save_notebook(notebook)
                added_to.append(notebook_id)

                # Update update time and record count in index
                index = self._load_index()
                for nb_info in index["notebooks"]:
                    if nb_info["id"] == notebook_id:
                        nb_info["updated_at"] = now
                        nb_info["record_count"] = len(notebook["records"])
                        break
                self._save_index(index)

        return {"record": record, "added_to_notebooks": added_to, "kb_sync_info": kb_sync_info}

    def remove_record(self, notebook_id: str, record_id: str) -> bool:
        """
        Remove record from notebook

        Args:
            notebook_id: Notebook ID
            record_id: Record ID

        Returns:
            Whether deletion was successful
        """
        notebook = self._load_notebook(notebook_id)
        if not notebook:
            return False

        original_count = len(notebook["records"])
        notebook["records"] = [r for r in notebook["records"] if r["id"] != record_id]

        if len(notebook["records"]) == original_count:
            return False

        notebook["updated_at"] = time.time()
        self._save_notebook(notebook)

        # Update index
        index = self._load_index()
        for nb_info in index["notebooks"]:
            if nb_info["id"] == notebook_id:
                nb_info["updated_at"] = notebook["updated_at"]
                nb_info["record_count"] = len(notebook["records"])
                break
        self._save_index(index)

        return True

    def get_statistics(self) -> dict:
        """
        Get notebook statistics

        Returns:
            Statistics information
        """
        notebooks = self.list_notebooks()

        total_records = 0
        type_counts = {"solve": 0, "question": 0, "research": 0, "co_writer": 0}

        for nb_info in notebooks:
            notebook = self._load_notebook(nb_info["id"])
            if notebook:
                for record in notebook.get("records", []):
                    total_records += 1
                    record_type = record.get("type", "")
                    if record_type in type_counts:
                        type_counts[record_type] += 1

        return {
            "total_notebooks": len(notebooks),
            "total_records": total_records,
            "records_by_type": type_counts,
            "recent_notebooks": notebooks[:5],
        }


# Global instance
notebook_manager = NotebookManager()
