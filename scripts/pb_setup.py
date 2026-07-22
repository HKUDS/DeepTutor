#!/usr/bin/env python3
"""
PocketBase collection bootstrap script.

Run this once after starting PocketBase for the first time:

    python scripts/pb_setup.py

Requires integrations.pocketbase_url, integrations.pocketbase_admin_email, and
integrations.pocketbase_admin_password in data/user/settings/integrations.json.

Safe to re-run — existing collections are left untouched.
"""

from __future__ import annotations

from pathlib import Path
import sys

# Allow running from project root without installing the package.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from deeptutor.services.config import load_integrations_settings

_INTEGRATIONS = load_integrations_settings()
POCKETBASE_BASE_URL = str(_INTEGRATIONS["pocketbase_url"]).rstrip("/")
ADMIN_EMAIL = str(_INTEGRATIONS["pocketbase_admin_email"])
ADMIN_PASSWORD = str(_INTEGRATIONS["pocketbase_admin_password"])


def _require_env():
    missing = []
    if not POCKETBASE_BASE_URL:
        missing.append("integrations.pocketbase_url")
    if not ADMIN_EMAIL:
        missing.append("integrations.pocketbase_admin_email")
    if not ADMIN_PASSWORD:
        missing.append("integrations.pocketbase_admin_password")
    if missing:
        print(f"ERROR: Missing required integration settings: {', '.join(missing)}")
        print("Set them in data/user/settings/integrations.json before running this script.")
        sys.exit(1)


def _get_client():
    try:
        from pocketbase import PocketBase  # type: ignore[import]
    except ImportError:
        print("ERROR: pocketbase package not installed.")
        print("Run: pip install pocketbase")
        sys.exit(1)

    pb = PocketBase(POCKETBASE_BASE_URL)
    pb.admins.auth_with_password(ADMIN_EMAIL, ADMIN_PASSWORD)
    return pb


def _existing_collections(pb) -> set[str]:
    try:
        collections = pb.collections.get_full_list()
        return {c.name for c in collections}
    except Exception:
        return set()


def _create_if_missing(pb, name: str, schema: dict, existing: set[str]):
    if name in existing:
        print(f"  skip  {name} (already exists)")
        return
    try:
        pb.collections.create(schema)
        print(f"  create {name}")
    except Exception as exc:
        print(f"  ERROR creating {name}: {exc}")


def main():
    _require_env()
    print(f"Connecting to PocketBase at {POCKETBASE_BASE_URL} ...")
    pb = _get_client()
    print("Authenticated as admin.")

    existing = _existing_collections(pb)
    print(f"Found {len(existing)} existing collection(s): {sorted(existing) or '(none)'}\n")

    # Access control is enforced in the application layer, not by PocketBase
    # collection rules: the backend connects with a single admin-authenticated
    # client (see services/pocketbase_client.py), which bypasses collection
    # RBAC entirely, so the rules below stay empty by design. Per-user session
    # isolation is implemented in PocketBaseSessionStore by stamping every
    # session row with ``user_id`` and filtering every query by the current
    # user. Do NOT rely on these listRule/viewRule strings for isolation.
    collections = [
        # ----------------------------------------------------------------
        # sessions  (``user_id`` populated + filtered by PocketBaseSessionStore)
        # ----------------------------------------------------------------
        {
            "name": "sessions",
            "type": "base",
            "schema": [
                {"name": "session_id", "type": "text", "required": True},
                {"name": "user_id", "type": "text", "required": False},
                {"name": "title", "type": "text", "required": False},
                {"name": "compressed_summary", "type": "text", "required": False},
                {"name": "summary_up_to_msg_id", "type": "number", "required": False},
                {"name": "preferences_json", "type": "json", "required": False},
                {"name": "capability", "type": "text", "required": False},
                {"name": "status", "type": "text", "required": False},
            ],
            "listRule": "",
            "viewRule": "",
            "createRule": "",
            "updateRule": "",
            "deleteRule": "",
        },
        # ----------------------------------------------------------------
        # messages
        # ----------------------------------------------------------------
        {
            "name": "messages",
            "type": "base",
            "schema": [
                {"name": "session_id", "type": "text", "required": True},
                {"name": "role", "type": "text", "required": True},
                {"name": "content", "type": "text", "required": False},
                {"name": "capability", "type": "text", "required": False},
                {"name": "events_json", "type": "json", "required": False},
                {"name": "attachments_json", "type": "json", "required": False},
                {"name": "msg_created_at", "type": "number", "required": False},
            ],
            "listRule": "",
            "viewRule": "",
            "createRule": "",
            "updateRule": "",
            "deleteRule": "",
        },
        # ----------------------------------------------------------------
        # turns
        # ----------------------------------------------------------------
        {
            "name": "turns",
            "type": "base",
            "schema": [
                {"name": "turn_id", "type": "text", "required": True},
                {"name": "session_id", "type": "text", "required": True},
                {"name": "capability", "type": "text", "required": False},
                {"name": "status", "type": "text", "required": False},
                {"name": "error", "type": "text", "required": False},
                {"name": "turn_created_at", "type": "number", "required": False},
                {"name": "turn_updated_at", "type": "number", "required": False},
                {"name": "finished_at", "type": "number", "required": False},
            ],
            "listRule": "",
            "viewRule": "",
            "createRule": "",
            "updateRule": "",
            "deleteRule": "",
        },
        # ----------------------------------------------------------------
        # turn_events
        # ----------------------------------------------------------------
        {
            "name": "turn_events",
            "type": "base",
            "schema": [
                {"name": "turn_id", "type": "text", "required": True},
                {"name": "session_id", "type": "text", "required": False},
                {"name": "seq", "type": "number", "required": True},
                {"name": "type", "type": "text", "required": False},
                {"name": "source", "type": "text", "required": False},
                {"name": "stage", "type": "text", "required": False},
                {"name": "content", "type": "text", "required": False},
                {"name": "metadata_json", "type": "json", "required": False},
                {"name": "event_timestamp", "type": "number", "required": False},
            ],
            "listRule": "",
            "viewRule": "",
            "createRule": "",
            "updateRule": "",
            "deleteRule": "",
        },
        # ----------------------------------------------------------------
        # knowledge_bases
        # ----------------------------------------------------------------
        {
            "name": "knowledge_bases",
            "type": "base",
            "schema": [
                {"name": "kb_name", "type": "text", "required": True},
                {"name": "user_id", "type": "text", "required": False},
                {"name": "description", "type": "text", "required": False},
                {"name": "rag_provider", "type": "text", "required": False},
                {"name": "needs_reindex", "type": "bool", "required": False},
                {"name": "status", "type": "text", "required": False},
                {"name": "kb_created_at", "type": "text", "required": False},
                {
                    "name": "raw_files",
                    "type": "file",
                    "required": False,
                    "options": {"maxSelect": 99, "maxSize": 52428800},
                },
            ],
            "listRule": "",
            "viewRule": "",
            "createRule": "",
            "updateRule": "",
            "deleteRule": "",
        },
    ]

    print("Creating collections:")
    for col in collections:
        _create_if_missing(pb, col["name"], col, existing)

    print("\nDone. PocketBase collections are ready.")
    print(f"Open the admin panel at {POCKETBASE_BASE_URL}/_/ to view and configure collections.")


if __name__ == "__main__":
    main()
