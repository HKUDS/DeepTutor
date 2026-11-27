"""Coordinate in-process knowledge base catalog updates and deletions."""

from contextlib import contextmanager
from functools import wraps
from os.path import normcase
from pathlib import Path
from threading import Lock, RLock
from weakref import WeakValueDictionary

# Resolve and reserve the name before another deletion can release it.
KB_DELETION_LOCK = RLock()


class KnowledgeBaseDeletionInProgress(ValueError):
    def __init__(self, name: str):
        super().__init__(f"Knowledge base '{name}' is already being deleted")


class KnowledgeBaseCatalog:
    def __init__(self):
        self.lock = RLock()
        self._deleting: dict[str, str] = {}

    def is_deleting(self, name: str) -> bool:
        with self.lock:
            return normcase(name) in self._deleting

    def deleting_names(self) -> set[str]:
        with self.lock:
            return set(self._deleting.values())

    @contextmanager
    def reserve_deletion(self, name: str):
        key = normcase(name)
        with KB_DELETION_LOCK, self.lock:
            if key in self._deleting:
                raise KnowledgeBaseDeletionInProgress(name)
            self._deleting[key] = name
        try:
            yield
        finally:
            with KB_DELETION_LOCK, self.lock:
                del self._deleting[key]


_catalogs = WeakValueDictionary()
_catalogs_lock = Lock()


def kb_catalog(base_dir: Path) -> KnowledgeBaseCatalog:
    key = base_dir.resolve()
    with _catalogs_lock:
        catalog = _catalogs.get(key)
        if catalog is None:
            catalog = KnowledgeBaseCatalog()
            _catalogs[key] = catalog
        return catalog


def serialize_catalog(method):
    """Keep one catalog read-modify-write together across manager instances."""

    @wraps(method)
    def locked(self, *args, **kwargs):
        with self._catalog.lock:
            return method(self, *args, **kwargs)

    return locked
