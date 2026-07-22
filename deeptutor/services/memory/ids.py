"""Stable, time-ordered identifiers for trace events and document entries.

Format: 26-character Crockford-base32 (ULID-style).

- Trace ids:  ``<surface>:<ULID>`` — e.g. ``chat:01HZK4ABCDEFGHJKMNPQRSTVWX``
- Entry ids:  ``m_<ULID>``        — used in MD footnote labels

The ULID's leading 10 characters encode a millisecond timestamp, giving
natural chronological sort across files and within a file.
"""

from __future__ import annotations

import re
import secrets
import time

_BASE32 = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"  # Crockford
_ULID_TS_LEN = 10
_ULID_RAND_LEN = 16
_ULID_LEN = _ULID_TS_LEN + _ULID_RAND_LEN

_ENTRY_RE = re.compile(r"^m_[0-9A-HJKMNP-TV-Z]{26}$")
_TRACE_RE = re.compile(r"^[a-z][a-z0-9_-]*:[0-9A-HJKMNP-TV-Z]{26}$")
# Snapshot ref points to a current workspace entity. The id portion is
# whatever the per-surface adapter chose (doc_id / record_id / kb_name /
# bot name / session_id / "session:question" composites). Permissive
# enough to allow embedded ``:``; restrictive enough to keep refs safe
# to embed in the comma-separated footnote serialization.
_SNAPSHOT_RE = re.compile(r"^[a-z][a-z0-9_-]*:[A-Za-z0-9_.:\-]+$")
# L3 surface ref — bare surface name like ``chat``, ``notebook``. L3 is
# a synthesis layer that points at L2 *files*, not L2 entries, so its
# refs need no id portion. Whitelist (not a loose regex) so a malformed
# ref like ``not-an-id`` doesn't accidentally validate. Mirrors
# :data:`paths.SURFACES`; if you add a surface, add it here too.
_SHORTNAME_REFS = frozenset({"chat", "notebook", "quiz", "kb", "book", "partner", "cowriter"})


def _encode(n: int, length: int) -> str:
    chars: list[str] = []
    for _ in range(length):
        chars.append(_BASE32[n & 0x1F])
        n >>= 5
    return "".join(reversed(chars))


def new_ulid() -> str:
    ts = int(time.time() * 1000) & ((1 << (_ULID_TS_LEN * 5)) - 1)
    rand = secrets.randbits(_ULID_RAND_LEN * 5)
    return _encode(ts, _ULID_TS_LEN) + _encode(rand, _ULID_RAND_LEN)


def new_entry_id() -> str:
    return f"m_{new_ulid()}"


def new_trace_id(surface: str) -> str:
    return f"{surface}:{new_ulid()}"


def is_entry_id(s: str) -> bool:
    return bool(_ENTRY_RE.match(s))


def is_trace_id(s: str) -> bool:
    return bool(_TRACE_RE.match(s))


def is_snapshot_ref(s: str) -> bool:
    return bool(_SNAPSHOT_RE.match(s))


def is_shortname_ref(s: str) -> bool:
    """Bare surface name — the form used by L3 refs (whitelist)."""
    return s in _SHORTNAME_REFS


def is_valid_ref(s: str) -> bool:
    """Any form of ref the ops validator accepts."""
    return is_entry_id(s) or is_trace_id(s) or is_snapshot_ref(s) or is_shortname_ref(s)
