"""Offline-safe acquisition of the encoding behind chat token counting.

``tiktoken.get_encoding("cl100k_base")`` reads its BPE ranks from a CDN —
with no request timeout — whenever its cache misses, and re-reads (and
possibly re-downloads) the file on *every* cold construction. Chat history
budgeting counts tokens synchronously, so a download or a pathological
filesystem could freeze the turn, and the ``except Exception`` heuristic
fallback around counting can never fire: the call simply never returns
(#2522). This module guarantees both properties by construction:

* **No download can ever start.** ``tiktoken.get_encoding`` /
  ``read_file_cached`` are never called. The ranks file is read once here
  with a size cap and accepted only if it hashes to the published
  ``cl100k_base`` SHA-256, and the :class:`tiktoken.Encoding` is built
  directly from those bytes. Races that delete or swap the file after the
  read therefore cannot send tiktoken down its delete-and-refetch path —
  there is no second read. An encoding already resident in tiktoken's
  in-process registry is adopted without touching the filesystem.
* **The caller never waits.** ``get_local_encoding`` performs no import,
  filesystem access or parsing; it only checks published flags and, at
  most, starts one background worker. Importing tiktoken, reading and
  verifying the ranks, and parsing them all run on that daemon worker.
  While acquisition is pending the caller gets ``None`` and keeps its
  chars/4 heuristic estimate; once the verified encoding is published,
  later calls return it and counting becomes exact.

A cold, disabled, untrusted or unreadable cache is re-attempted in the
background at most once per :data:`_RETRY_INTERVAL_SECONDS`, so ranks that
appear later in the process's life are picked up. Only misses that cannot
self-heal — tiktoken not importable, or verified bytes that fail to build —
latch for the process lifetime.
"""

from __future__ import annotations

import base64
import hashlib
import logging
import os
import tempfile
import threading
import time
from typing import Any

logger = logging.getLogger(__name__)

#: The tokenizer ``count_tokens`` uses when a verified local copy is usable.
ENCODING_NAME = "cl100k_base"

#: tiktoken caches each encoding's ranks at ``<cache dir>/<sha1(url)>`` and
#: downloads them over HTTPS on any cache miss — see tiktoken's
#: ``read_file_cached``. The URL has been stable since tiktoken first shipped
#: ``cl100k_base``; if it ever changes, this probe stops matching and counting
#: stays on the heuristic — a different file is never fetched or trusted.
_BLOB_URL = "https://openaipublic.blob.core.windows.net/encodings/cl100k_base.tiktoken"
_CACHE_KEY = hashlib.sha1(_BLOB_URL.encode(), usedforsecurity=False).hexdigest()
#: Published by tiktoken's own ``cl100k_base`` constructor. Anything else in
#: the cache slot is ignored (tiktoken itself would delete it and re-download).
_EXPECTED_SHA256 = "223921b76ee99bde995b7ff738513eef100fb51d18c93597a113bcffe865b2a7"
#: tiktoken's default cache directory when no environment override is set.
_DEFAULT_CACHE_DIRNAME = "data-gym-cache"
#: The published ranks file is ~1.7 MB; anything larger cannot be it, and the
#: cap bounds memory if the cache slot is swapped for something huge.
_MAX_RANKS_BYTES = 4 * 1024 * 1024
#: How often a transient miss (cold, disabled, untrusted or unreadable cache)
#: may be re-attempted in the background.
_RETRY_INTERVAL_SECONDS = 30.0

#: Constructor constants mirroring tiktoken's own ``cl100k_base`` plugin
#: (``tiktoken_ext.openai_public``, tiktoken 0.14.0). They define the
#: encoding's splitter and special tokens; only the ranks come from the
#: verified file. ``test_real_warm_cache_parity`` pins them against the
#: installed tiktoken, so drift fails CI instead of miscounting.
_PAT_STR = (
    r"""'(?i:[sdmt]|ll|ve|re)|[^\r\n\p{L}\p{N}]?+\p{L}++|\p{N}{1,3}+"""
    r"""| ?[^\s\p{L}\p{N}]++[\r\n]*+|\s++$|\s*[\r\n]|\s+(?!\S)|\s"""
)
_SPECIAL_TOKENS = {
    "<|endoftext|>": 100257,
    "<|fim_prefix|>": 100258,
    "<|fim_middle|>": 100259,
    "<|fim_suffix|>": 100260,
    "<|endofprompt|>": 100276,
}

#: Guards all flag transitions below; never held across I/O.
_state_lock = threading.Lock()
_encoding: Any | None = None
#: Latched when no locally verifiable path to the encoding exists (tiktoken
#: missing, or verified bytes that fail to build) so repeated counting never
#: pays for the attempt again this process.
_latched_unusable = False
#: True while the one-and-only background attempt is in flight.
_acquiring = False
#: Earliest background re-attempt after a transient miss (monotonic).
_next_retry_monotonic = 0.0
#: Bumped by test resets; a worker from an older generation must not publish.
_generation = 0
#: The in-flight worker, so tests can join it deterministically.
_worker_thread: threading.Thread | None = None
_warned_untrusted = False


def _import_tiktoken() -> Any:
    """Import seam: raising means "not installed", which callers treat as a miss."""
    import tiktoken

    return tiktoken


def _cache_dir() -> str | None:
    """Resolve the cache directory exactly as tiktoken will at load time.

    ``None`` means tiktoken's cache is disabled (``TIKTOKEN_CACHE_DIR`` or
    ``DATA_GYM_CACHE_DIR`` set to the empty string) — a configuration under
    which every ``get_encoding`` call downloads, so it must read as "no local
    copy" here.
    """
    for variable in ("TIKTOKEN_CACHE_DIR", "DATA_GYM_CACHE_DIR"):
        value = os.environ.get(variable)
        if value is not None:
            return value or None
    return os.path.join(tempfile.gettempdir(), _DEFAULT_CACHE_DIRNAME)


def _cached_ranks_path(cache_dir: str) -> str:
    return os.path.join(cache_dir, _CACHE_KEY)


def _verified_ranks_bytes(cache_dir: str) -> bytes | None:
    """Read the cache slot once and return it only if it is the published ranks.

    ``None`` (absent, unreadable, oversized or hash-mismatched) always means
    "no verified local copy" — the caller must not ask tiktoken for anything,
    because tiktoken's own cache path can delete the slot and re-download it.
    """
    global _warned_untrusted
    try:
        with open(_cached_ranks_path(cache_dir), "rb") as ranks:
            data = ranks.read(_MAX_RANKS_BYTES + 1)
    except OSError:
        return None
    if len(data) > _MAX_RANKS_BYTES:
        return None
    if hashlib.sha256(data).hexdigest() != _EXPECTED_SHA256:
        if not _warned_untrusted:
            _warned_untrusted = True
            logger.warning(
                "Cached %s ranks failed verification; token counting keeps the chars/4 estimate",
                ENCODING_NAME,
            )
        return None
    return data


def _build_encoding(tiktoken_module: Any, ranks: bytes) -> Any:
    """Build the encoding from already-verified bytes; parse errors propagate.

    This is tiktoken's own ``load_tiktoken_bpe`` body (the ``.tiktoken``
    line format) fed with our bytes instead of its cache/network reader, so
    no second read of the file — and no downloader — is involved.
    """
    mergeable_ranks: dict[bytes, int] = {}
    for line in ranks.splitlines():
        if not line:
            continue
        token, rank = line.split()
        mergeable_ranks[base64.b64decode(token)] = int(rank)
    return tiktoken_module.Encoding(
        name=ENCODING_NAME,
        pat_str=_PAT_STR,
        mergeable_ranks=mergeable_ranks,
        special_tokens=_SPECIAL_TOKENS,
    )


def _acquire_encoding(tiktoken_module: Any) -> Any | None:
    """Find a trustworthy ``cl100k_base`` without any network-capable call."""
    resident = getattr(getattr(tiktoken_module, "registry", None), "ENCODINGS", None)
    if isinstance(resident, dict):
        encoding = resident.get(ENCODING_NAME)
        if encoding is not None:
            return encoding  # already built by tiktoken in this process
    cache_dir = _cache_dir()
    if cache_dir is None:
        return None  # cache explicitly disabled: a load would download
    ranks = _verified_ranks_bytes(cache_dir)
    if ranks is None:
        return None
    return _build_encoding(tiktoken_module, ranks)


def _finish_attempt(generation: int, encoding: Any | None = None, *, latched: bool = False) -> None:
    """Publish an attempt's outcome, unless a newer generation superseded it."""
    global _encoding, _latched_unusable, _acquiring, _next_retry_monotonic, _worker_thread
    with _state_lock:
        if generation != _generation:
            return
        _acquiring = False
        _worker_thread = None
        if encoding is not None:
            _encoding = encoding
        elif latched:
            _latched_unusable = True
        else:
            _next_retry_monotonic = time.monotonic() + _RETRY_INTERVAL_SECONDS


def _acquisition_worker(generation: int) -> None:
    """Background body: import, verify and parse; never raises, never downloads."""
    try:
        try:
            tiktoken_module = _import_tiktoken()
        except Exception:
            logger.info("tiktoken is not importable; token counting keeps the chars/4 estimate")
            _finish_attempt(generation, latched=True)
            return
        try:
            encoding = _acquire_encoding(tiktoken_module)
        except Exception as exc:
            logger.warning(
                "Verified local %s ranks could not be built (%s); token counting keeps the chars/4 estimate",
                ENCODING_NAME,
                type(exc).__name__,
            )
            _finish_attempt(generation, latched=True)
            return
        _finish_attempt(generation, encoding)
    except BaseException:
        logger.debug("Background %s acquisition aborted; will retry", ENCODING_NAME, exc_info=True)
        _finish_attempt(generation)


def get_local_encoding() -> Any | None:
    """Return the process-wide ``cl100k_base`` encoding, or ``None`.

    ``None`` — never an exception, never a download, never a wait — means the
    caller should use its heuristic estimate: tiktoken missing, the cache
    cold, disabled or untrusted, or the background acquisition still pending
    or failed. This function only reads published flags and starts the worker
    at most once per retry interval; it performs no import, filesystem access
    or parsing of its own.
    """
    global _acquiring, _worker_thread
    if _encoding is not None:
        return _encoding
    if _latched_unusable or _acquiring:
        return None
    if time.monotonic() < _next_retry_monotonic:
        return None
    with _state_lock:
        if _encoding is not None:
            return _encoding
        if _latched_unusable or _acquiring:
            return None
        if time.monotonic() < _next_retry_monotonic:
            return None
        _acquiring = True
        generation = _generation
    try:
        worker = threading.Thread(
            target=_acquisition_worker,
            args=(generation,),
            daemon=True,
            name="deeptutor-tiktoken-local-acquire",
        )
        with _state_lock:
            _worker_thread = worker
        worker.start()
    except Exception:
        logger.debug("Could not start %s acquisition worker; will retry", ENCODING_NAME)
        _finish_attempt(generation)
    return None


__all__ = ["ENCODING_NAME", "get_local_encoding"]
