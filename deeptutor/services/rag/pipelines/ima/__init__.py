"""Tencent IMA integration — retrieval, inventory and authoring over a live library.

A KB bound to the ``ima`` provider is a connection pointer to a library the user
keeps in IMA (https://ima.qq.com) and curates there. DeepTutor never indexes or
stores anything locally; everything is an OpenAPI call:

* :mod:`.pipeline` — the ``rag`` engine: ``search_knowledge`` plus a bounded
  full-text top-up for matches whose snippet is too thin to reason from.
* :mod:`.inventory` — what the library *contains* (``get_knowledge_list``), which
  is what makes "list the documents in this knowledge base" answerable; read from
  the synchronous manifest layer, so it is blocking and cached.
* :mod:`.notes` — the notes module, including the sort orders that answer "my
  most recent items" (knowledge items carry no timestamps; notes do).
* :mod:`.client` — the knowledge-base method table, with :mod:`.transport`,
  :mod:`.envelope`, :mod:`.models` and :mod:`.media` underneath it.
* :mod:`.probe` — the connect-time health check.

The IMA credentials are configured once for the account on the engine page (a KB
may override them to reach another account); the knowledge base id is always
per-KB. The agentic surface over these calls is
:mod:`deeptutor.capabilities.ima`.
"""

from __future__ import annotations

from .pipeline import ImaPipeline

__all__ = ["ImaPipeline"]
