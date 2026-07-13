"""rag_search no longer accepts an implicit/default KB.

The chat composer always sends an explicit ``kb_name`` selected from the
user's attached knowledge bases, so the tool fails fast when called without
one. Multi-user routing is verified separately in
``test_grants_and_settings.py``.
"""

from __future__ import annotations

import asyncio
import importlib


def _rag_search():
    # Bypass parent-attribute pollution from earlier tests' fake modules:
    # ``importlib.import_module`` reads ``sys.modules`` directly, which is
    # properly reverted by ``monkeypatch``.
    return importlib.import_module("deeptutor.tools.rag_tool").rag_search


def test_rag_search_no_kb_raises_value_error(mu_isolated_root, as_user):
    import pytest

    rag_search = _rag_search()
    with as_user("u_alice", role="user"):
        with pytest.raises(ValueError, match="kb_name"):
            asyncio.run(rag_search(query="hi", kb_name=""))


def test_rag_search_admin_also_requires_kb_name(mu_isolated_root, as_user):
    import pytest

    rag_search = _rag_search()
    with as_user("u_admin", role="admin"):
        with pytest.raises(ValueError, match="kb_name"):
            asyncio.run(rag_search(query="hi", kb_name=""))
