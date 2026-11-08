"""Offline-safe ``cl100k_base`` acquisition for chat token counting (#2522).

``tiktoken.get_encoding`` fetches its BPE ranks from a CDN with no timeout on
any cache miss (including a vanished cache file), so an ``except`` around
counting cannot save the event loop. These pin the guardrails instead,
deterministically and without any network:

* the downloader is never invoked — no ``get_encoding``, no
  ``read_file_cached`` — including when the cache file is deleted, replaced
  or swapped for a FIFO after verification began; the deletion and
  replacement races run against the real tiktoken with a synthetic,
  hash-verified ranks blob, so they never skip on clean CI;
* imports, filesystem reads and parsing never block the synchronous caller
  or the event loop: acquisition runs on a background worker, and callers
  get the heuristic while it is pending;
* concurrent callers share one acquisition attempt and one encoding;
* a real verified warm cache produces the exact ``cl100k_base`` counts —
  optional parity only, compared against tiktoken itself via a local
  fixture when one exists (never a download).
"""

from __future__ import annotations

import asyncio
import base64
from concurrent.futures import ThreadPoolExecutor
import hashlib
import os
from pathlib import Path
import threading
import time
from types import SimpleNamespace
from typing import Any

import pytest

from deeptutor.services.session.context_builder import count_tokens
import deeptutor.services.session.token_encoding as token_encoding

_FIXTURE_CANDIDATES = (
    Path("/tmp/data-gym-cache") / token_encoding._CACHE_KEY,
    Path(os.environ.get("DEEPTUTOR_CL100K_FIXTURE", "")),
)


class _StubEncoding:
    """Minimal stand-in for ``tiktoken.Encoding``: one word, one token."""

    def encode(self, text: str) -> list[str]:
        return text.split()


class _ExplodingEncoding:
    def encode(self, text: str) -> list[str]:
        raise RuntimeError("encode failed")


def _fixture_ranks() -> bytes | None:
    """The published ranks from a known local fixture, or ``None``."""
    for path in _FIXTURE_CANDIDATES:
        try:
            data = path.read_bytes()
        except OSError:
            continue
        if hashlib.sha256(data).hexdigest() == token_encoding._EXPECTED_SHA256:
            return data
    return None


def _synthetic_ranks() -> bytes:
    """A small, deterministic, valid ``.tiktoken`` ranks blob.

    Every byte value 0..255 gets a rank equal to its value, so any text
    round-trips and one-character pieces encode to their own byte; two
    merged tokens beyond the byte alphabet exercise the merge path while
    keeping the blob trivially valid for the real ``tiktoken.Encoding``.
    """
    lines = [base64.b64encode(bytes([value])) + b" " + str(value).encode() for value in range(256)]
    lines.append(base64.b64encode(b"He") + b" 256")
    lines.append(base64.b64encode(b"llo") + b" 257")
    return b"\n".join(lines) + b"\n"


@pytest.fixture()
def acquisition(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Reset the process-wide acquisition state around each test."""
    with token_encoding._state_lock:
        token_encoding._encoding = None
        token_encoding._latched_unusable = False
        token_encoding._acquiring = False
        token_encoding._next_retry_monotonic = 0.0
        token_encoding._generation += 1
        token_encoding._worker_thread = None
        token_encoding._warned_untrusted = False
    # Tests that verify backoff set their own interval.
    monkeypatch.setattr(token_encoding, "_RETRY_INTERVAL_SECONDS", 0.0)
    yield token_encoding
    with token_encoding._state_lock:
        token_encoding._generation += 1  # stale workers must not publish
        token_encoding._acquiring = False
        token_encoding._worker_thread = None


@pytest.fixture()
def no_network(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Fail loudly if tiktoken's downloader (``read_file``) is ever reached.

    ``read_file`` is the only network path in tiktoken's loader; blocking it
    proves no test — not even the warm parity reference — could fetch, while
    still allowing the reference's legitimate local cache read.
    """
    tiktoken_load = pytest.importorskip("tiktoken.load")
    attempts: list[str] = []

    def _blocked(*args: Any, **_kwargs: Any) -> None:
        attempts.append(str(args))
        raise AssertionError(f"tiktoken downloader invoked: {args}")

    monkeypatch.setattr(tiktoken_load, "read_file", _blocked)
    return attempts


@pytest.fixture()
def registry_free_tiktoken(monkeypatch: pytest.MonkeyPatch) -> None:
    """The real tiktoken with every download-capable entry point exploding.

    ``get_encoding`` and the cached loaders must never be reached, and the
    in-process registry is emptied so its resident-encoding shortcut cannot
    bypass the verified-file path the race tests exercise.
    """
    tiktoken = pytest.importorskip("tiktoken")
    tiktoken_load = pytest.importorskip("tiktoken.load")

    def _forbidden(callee: str) -> Any:
        def _raise(*args: Any, **kwargs: Any) -> None:
            raise AssertionError(f"{callee} must never be called: it can download")

        return _raise

    monkeypatch.setattr(tiktoken, "get_encoding", _forbidden("tiktoken.get_encoding"))
    monkeypatch.setattr(
        tiktoken_load, "read_file_cached", _forbidden("tiktoken.load.read_file_cached")
    )
    monkeypatch.setattr(
        tiktoken_load, "load_tiktoken_bpe", _forbidden("tiktoken.load.load_tiktoken_bpe")
    )
    monkeypatch.setattr(tiktoken.registry, "ENCODINGS", {})


def _settle(timeout: float = 5.0) -> None:
    """Wait until no background attempt is in flight; join it if possible."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with token_encoding._state_lock:
            acquiring = token_encoding._acquiring
            worker = token_encoding._worker_thread
        if not acquiring:
            return
        if worker is not None:
            worker.join(timeout)
            return
        time.sleep(0.005)
    pytest.fail("background acquisition did not settle")


def _wait_ready(timeout: float = 10.0) -> Any:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if token_encoding._encoding is not None:
            return token_encoding._encoding
        time.sleep(0.005)
    pytest.fail("background acquisition never published an encoding")


def _stub_tiktoken(encoding: Any = None) -> Any:
    """Stub tiktoken module whose real loader must never be reached."""
    built: list[dict[str, Any]] = []

    def _encoding_ctor(**kwargs: Any) -> Any:
        built.append(kwargs)
        return encoding if encoding is not None else _StubEncoding()

    def _get_encoding(name: str) -> Any:
        raise AssertionError(f"get_encoding({name!r}) must never be called: it can download")

    return SimpleNamespace(
        Encoding=_encoding_ctor,
        registry=SimpleNamespace(ENCODINGS={}),
        get_encoding=_get_encoding,
        built=built,
    )


def _fabricated_cache(
    acquisition: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Any, payload: bytes
) -> Path:
    """Make the cache-presence gate pass with a fabricated ranks file."""
    cache_dir = tmp_path / "ranks"
    cache_dir.mkdir(exist_ok=True)
    (cache_dir / acquisition._CACHE_KEY).write_bytes(payload)
    monkeypatch.setattr(acquisition, "_EXPECTED_SHA256", hashlib.sha256(payload).hexdigest())
    monkeypatch.setenv("TIKTOKEN_CACHE_DIR", str(cache_dir))
    return cache_dir


def _warm_synthetic_cache(acquisition: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> Path:
    """Warm the cache with the synthetic blob, verified as if published.

    Unlike ``_warm_real_cache`` this never skips: the hash gate simply
    trusts the blob we just wrote, so the race tests below always run.
    """
    ranks = _synthetic_ranks()
    cache_dir = tmp_path / "ranks"
    cache_dir.mkdir()
    (cache_dir / acquisition._CACHE_KEY).write_bytes(ranks)
    monkeypatch.setattr(acquisition, "_EXPECTED_SHA256", hashlib.sha256(ranks).hexdigest())
    monkeypatch.setenv("TIKTOKEN_CACHE_DIR", str(cache_dir))
    return cache_dir


def _warm_real_cache(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> Path:
    """Warm the cache from a verified local fixture; skip when absent.

    Used only by the optional ``test_real_warm_cache_parity`` — every test
    that must always run builds from ``_warm_synthetic_cache`` instead.
    """
    ranks = _fixture_ranks()
    if ranks is None:
        pytest.skip(
            "optional parity test: no verified local cl100k_base fixture "
            "(set DEEPTUTOR_CL100K_FIXTURE to provide one)"
        )
    cache_dir = tmp_path / "ranks"
    cache_dir.mkdir()
    (cache_dir / token_encoding._CACHE_KEY).write_bytes(ranks)
    monkeypatch.setenv("TIKTOKEN_CACHE_DIR", str(cache_dir))
    return cache_dir


# ---- the downloader can never be reached -----------------------------------


def test_cold_cache_is_a_transient_miss(
    acquisition: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    """First chat with an empty cache: heuristic now, exact later if warmed."""
    stub = _stub_tiktoken()
    monkeypatch.setattr(acquisition, "_import_tiktoken", lambda: stub)
    monkeypatch.setenv("TIKTOKEN_CACHE_DIR", str(tmp_path / "cold"))

    began = time.monotonic()
    assert acquisition.get_local_encoding() is None
    assert time.monotonic() - began < 1.0  # no wait for import/fs/parse
    _settle()
    assert acquisition._latched_unusable is False  # retryable, not latched
    assert stub.built == []  # nothing was built from an unverified cache


def test_disabled_cache_is_a_transient_miss(
    acquisition: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Empty-string cache env makes every tiktoken load a download: refuse it."""
    stub = _stub_tiktoken()
    monkeypatch.setattr(acquisition, "_import_tiktoken", lambda: stub)
    monkeypatch.setenv("TIKTOKEN_CACHE_DIR", "")

    assert acquisition.get_local_encoding() is None
    _settle()
    assert acquisition._encoding is None
    assert acquisition._latched_unusable is False
    assert stub.built == []


def test_untrusted_ranks_are_never_parsed_or_built(
    acquisition: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    """A hash-mismatched cache file is ignored, not fed to tiktoken."""
    stub = _stub_tiktoken()
    monkeypatch.setattr(acquisition, "_import_tiktoken", lambda: stub)
    _fabricated_cache(acquisition, monkeypatch, tmp_path, b"not the published ranks\n")
    (tmp_path / "ranks" / acquisition._CACHE_KEY).write_bytes(b"tampered payload\n")

    assert acquisition.get_local_encoding() is None
    _settle()
    assert acquisition._encoding is None
    assert acquisition._latched_unusable is False  # repairable, so retryable
    assert stub.built == []


def test_file_deleted_after_read_still_builds_and_never_downloads(
    acquisition: Any,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Any,
    no_network: list[str],
    registry_free_tiktoken: None,
) -> None:
    """The old verify-then-load race: deletion must not reach a downloader.

    The ranks are synthetic, but the hash gate and the build run the real
    code paths against the real tiktoken, with every download-capable
    entry point rigged to fail loudly.
    """
    cache_dir = _warm_synthetic_cache(acquisition, monkeypatch, tmp_path)
    original_build = acquisition._build_encoding

    def _unlink_then_build(module: Any, ranks: bytes) -> Any:
        (cache_dir / acquisition._CACHE_KEY).unlink()
        return original_build(module, ranks)

    monkeypatch.setattr(acquisition, "_build_encoding", _unlink_then_build)

    assert acquisition.get_local_encoding() is None  # pending, not blocking
    encoding = _wait_ready()
    assert encoding.name == "cl100k_base"  # built by the verified-bytes path
    assert encoding.decode(encoding.encode("Hello, world!")) == "Hello, world!"
    assert encoding.encode("A") == [ord("A")]  # byte-level ranks equal byte values
    assert not (cache_dir / acquisition._CACHE_KEY).exists()
    assert no_network == []


def test_file_replaced_after_read_uses_the_verified_bytes(
    acquisition: Any,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Any,
    no_network: list[str],
    registry_free_tiktoken: None,
) -> None:
    """Replacement mid-acquisition: the verified bytes already in hand win.

    Same synthetic-blob setup as the deletion race: real tiktoken, real
    hash gate, and any download-capable loader call fails loudly.
    """
    cache_dir = _warm_synthetic_cache(acquisition, monkeypatch, tmp_path)
    original_build = acquisition._build_encoding

    def _swap_then_build(module: Any, ranks: bytes) -> Any:
        (cache_dir / acquisition._CACHE_KEY).write_bytes(b"swapped in a race\n")
        return original_build(module, ranks)

    monkeypatch.setattr(acquisition, "_build_encoding", _swap_then_build)

    acquisition.get_local_encoding()
    encoding = _wait_ready()
    assert encoding.name == "cl100k_base"  # built by the verified-bytes path
    assert encoding.decode(encoding.encode("Hello, world!")) == "Hello, world!"
    assert encoding.encode("A") == [ord("A")]  # byte-level ranks equal byte values
    assert (cache_dir / acquisition._CACHE_KEY).read_bytes() == b"swapped in a race\n"
    assert no_network == []


def test_fifo_ranks_file_never_blocks_the_caller_or_downloads(
    acquisition: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Any, no_network: list[str]
) -> None:
    """A FIFO swapped into the cache slot hangs only the daemon worker."""
    pytest.importorskip("tiktoken")
    if os.name != "posix":
        pytest.skip("requires os.mkfifo")
    cache_dir = tmp_path / "ranks"
    cache_dir.mkdir()
    fifo = cache_dir / acquisition._CACHE_KEY
    os.mkfifo(fifo)
    monkeypatch.setenv("TIKTOKEN_CACHE_DIR", str(cache_dir))

    began = time.monotonic()
    assert acquisition.get_local_encoding() is None  # returns despite the FIFO
    assert time.monotonic() - began < 1.0

    deadline = time.monotonic() + 2.0
    worker = None
    while time.monotonic() < deadline:
        with acquisition._state_lock:
            worker = acquisition._worker_thread
        if worker is not None and worker.is_alive():
            break
        time.sleep(0.005)
    assert worker is not None and worker.is_alive()
    worker.join(0.2)
    assert worker.is_alive()  # stuck in the FIFO open, deadline-free by design

    with open(fifo, "wb") as writer:  # release the worker with junk
        writer.write(b"garbage, not ranks")
    worker.join(5.0)
    assert not worker.is_alive()
    assert acquisition._encoding is None  # junk never verified: heuristic
    assert acquisition._latched_unusable is False
    assert no_network == []


# ---- latching policy --------------------------------------------------------


def test_missing_tiktoken_latches_heuristic(
    acquisition: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    imports: list[str] = []

    def _raise() -> Any:
        imports.append("tiktoken")
        raise ImportError("tiktoken")

    monkeypatch.setattr(acquisition, "_import_tiktoken", _raise)
    monkeypatch.setenv("TIKTOKEN_CACHE_DIR", "/nonexistent")

    assert acquisition.get_local_encoding() is None
    _settle()
    assert acquisition._latched_unusable is True
    began = time.monotonic()
    assert acquisition.get_local_encoding() is None
    assert time.monotonic() - began < 0.5  # latched: no second attempt
    assert imports == ["tiktoken"]


def test_unparseable_verified_ranks_latch_heuristic(
    acquisition: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    """Bytes that pass the hash but cannot parse cannot self-heal: latch."""
    stub = _stub_tiktoken()
    monkeypatch.setattr(acquisition, "_import_tiktoken", lambda: stub)
    _fabricated_cache(acquisition, monkeypatch, tmp_path, b"@@@ not a tiktoken line @@@")

    assert acquisition.get_local_encoding() is None
    _settle()
    assert acquisition._latched_unusable is True
    assert stub.built == []


# ---- a usable local encoding is acquired once and reused --------------------


def test_verified_ranks_build_once_and_are_reused(
    acquisition: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    stub = _stub_tiktoken()
    monkeypatch.setattr(acquisition, "_import_tiktoken", lambda: stub)
    _fabricated_cache(acquisition, monkeypatch, tmp_path, b"AAAA 0\n")

    assert acquisition.get_local_encoding() is None  # pending on first call
    encoding = _wait_ready()
    assert acquisition.get_local_encoding() is encoding  # exact from now on
    assert acquisition.get_local_encoding() is encoding
    assert len(stub.built) == 1  # one build for the whole process
    (kwargs,) = stub.built
    assert kwargs["name"] == "cl100k_base"
    assert kwargs["mergeable_ranks"] == {base64.b64decode("AAAA"): 0}
    assert kwargs["special_tokens"]["<|endoftext|>"] == 100257


def test_registry_resident_encoding_wins_without_filesystem(
    acquisition: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    """An encoding tiktoken already built in-process is adopted as-is."""
    stub = _stub_tiktoken()
    resident = _StubEncoding()
    stub.registry.ENCODINGS["cl100k_base"] = resident
    monkeypatch.setattr(acquisition, "_import_tiktoken", lambda: stub)
    monkeypatch.setenv("TIKTOKEN_CACHE_DIR", str(tmp_path / "no-such-dir"))

    acquisition.get_local_encoding()
    encoding = _wait_ready()
    assert encoding is resident
    assert stub.built == []


def test_ready_encoding_is_returned_without_any_work(
    acquisition: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    stub_encoding = _StubEncoding()
    monkeypatch.setattr(
        acquisition, "_import_tiktoken", lambda: pytest.fail("must not import when ready")
    )
    with acquisition._state_lock:
        acquisition._encoding = stub_encoding

    began = time.monotonic()
    assert acquisition.get_local_encoding() is stub_encoding
    assert time.monotonic() - began < 0.05
    with acquisition._state_lock:
        assert acquisition._worker_thread is None


def test_cold_cache_recovers_once_verified_ranks_appear(
    acquisition: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    """Cold-to-warm: the retry picks up ranks that appear later."""
    stub = _stub_tiktoken()
    monkeypatch.setattr(acquisition, "_import_tiktoken", lambda: stub)
    cache_dir = tmp_path / "ranks"
    cache_dir.mkdir()
    monkeypatch.setenv("TIKTOKEN_CACHE_DIR", str(cache_dir))

    assert acquisition.get_local_encoding() is None
    _settle()
    assert acquisition._encoding is None  # cold

    (cache_dir / acquisition._CACHE_KEY).write_bytes(b"AAAA 0\n")
    monkeypatch.setattr(acquisition, "_EXPECTED_SHA256", hashlib.sha256(b"AAAA 0\n").hexdigest())
    assert acquisition.get_local_encoding() is None  # next attempt is async
    assert _wait_ready() is not None
    assert len(stub.built) == 1


def test_backoff_limits_attempt_rate(
    acquisition: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    imports: list[str] = []

    def _slow_import() -> Any:
        imports.append("tiktoken")
        return _stub_tiktoken()

    monkeypatch.setattr(acquisition, "_import_tiktoken", _slow_import)
    monkeypatch.setenv("TIKTOKEN_CACHE_DIR", str(tmp_path / "cold"))
    monkeypatch.setattr(acquisition, "_RETRY_INTERVAL_SECONDS", 30.0)

    assert acquisition.get_local_encoding() is None
    _settle()
    time.sleep(0.05)
    assert acquisition.get_local_encoding() is None
    assert acquisition.get_local_encoding() is None
    assert imports == ["tiktoken"]  # backoff suppressed the re-attempts


# ---- the caller and the event loop never block ------------------------------


def test_slow_import_and_verification_never_block_the_event_loop(
    acquisition: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    """Every blocking stage lives on the worker; the loop keeps beating.

    The seams each sleep 0.2 s, so an inline implementation would stall the
    loop for at least 0.6 s and starve the heartbeat; the background design
    keeps both the synchronous call and the heartbeat gaps far below that.
    """
    stub = _stub_tiktoken()
    cache_dir = _fabricated_cache(acquisition, monkeypatch, tmp_path, b"AAAA 0\n")

    def _slow_import() -> Any:
        time.sleep(0.2)
        return stub

    original_read = acquisition._verified_ranks_bytes
    original_build = acquisition._build_encoding

    def _slow_read(directory: str) -> bytes | None:
        time.sleep(0.2)
        return original_read(directory)

    def _slow_build(module: Any, ranks: bytes) -> Any:
        time.sleep(0.2)
        return original_build(module, ranks)

    monkeypatch.setattr(acquisition, "_import_tiktoken", _slow_import)
    monkeypatch.setattr(acquisition, "_verified_ranks_bytes", _slow_read)
    monkeypatch.setattr(acquisition, "_build_encoding", _slow_build)

    async def scenario() -> tuple[float, list[float]]:
        ticks: list[float] = []

        async def heartbeat() -> None:
            for _ in range(40):
                await asyncio.sleep(0.01)
                ticks.append(time.monotonic())

        beating = asyncio.create_task(heartbeat())
        await asyncio.sleep(0)
        began = time.monotonic()
        pending = token_encoding.get_local_encoding()  # synchronous, on the loop
        elapsed = time.monotonic() - began
        await beating
        assert pending is None
        return elapsed, ticks

    elapsed, ticks = asyncio.run(scenario())
    assert elapsed < 0.15  # the 0.6 s of seam sleeps happened elsewhere
    assert len(ticks) == 40
    gaps = [later - earlier for earlier, later in zip(ticks, ticks[1:])]
    assert max(gaps) < 0.15  # the loop was never frozen by acquisition

    assert _wait_ready() is not None  # accuracy arrives once ranks are ready
    assert count_tokens("alpha beta") == 2  # exact stub counts, not chars/4
    assert (cache_dir / acquisition._CACHE_KEY).exists()


# ---- concurrent callers share one acquisition -------------------------------


def test_concurrent_calls_share_one_attempt(
    acquisition: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    attempts: list[float] = []
    gate = threading.Event()
    stub = _stub_tiktoken()
    monkeypatch.setattr(acquisition, "_import_tiktoken", lambda: stub)

    def _gated_acquire(module: Any) -> Any:
        attempts.append(time.monotonic())
        assert gate.wait(10), "test gate never opened"
        return _StubEncoding()

    monkeypatch.setattr(acquisition, "_acquire_encoding", _gated_acquire)
    monkeypatch.setenv("TIKTOKEN_CACHE_DIR", str(tmp_path / "cold"))

    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(token_encoding.get_local_encoding) for _ in range(8)]
        results = [future.result(10) for future in futures]
    assert all(result is None for result in results)  # pending, not blocking
    assert len(attempts) == 1  # eight concurrent callers, one attempt
    gate.set()
    assert _wait_ready() is not None
    assert len(attempts) == 1  # the latch-free retry never duplicated work


def test_concurrent_warm_calls_yield_one_encoding(
    acquisition: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    stub = _stub_tiktoken()
    monkeypatch.setattr(acquisition, "_import_tiktoken", lambda: stub)
    _fabricated_cache(acquisition, monkeypatch, tmp_path, b"AAAA 0\n")
    stop_at = time.monotonic() + 0.5

    def churn() -> set[int]:
        seen: set[int] = set()
        while time.monotonic() < stop_at:
            encoding = token_encoding.get_local_encoding()
            if encoding is not None:
                seen.add(id(encoding))
        return seen

    with ThreadPoolExecutor(max_workers=8) as pool:
        seen_per_thread = list(pool.map(lambda _: churn(), range(8)))
    every_seen = set().union(*seen_per_thread)
    assert len(every_seen) == 1  # one shared encoding instance, ever
    assert len(stub.built) == 1  # built exactly once


# ---- cache-directory resolution matches tiktoken -----------------------------


def test_cache_dir_resolves_like_tiktoken(
    acquisition: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    import tempfile

    monkeypatch.delenv("TIKTOKEN_CACHE_DIR", raising=False)
    monkeypatch.delenv("DATA_GYM_CACHE_DIR", raising=False)
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    expected_default = os.path.join(str(tmp_path), "data-gym-cache")
    assert acquisition._cache_dir() == expected_default
    monkeypatch.setenv("DATA_GYM_CACHE_DIR", str(tmp_path / "gym"))
    assert acquisition._cache_dir() == str(tmp_path / "gym")
    monkeypatch.setenv("TIKTOKEN_CACHE_DIR", str(tmp_path / "tik"))
    assert acquisition._cache_dir() == str(tmp_path / "tik")
    monkeypatch.setenv("TIKTOKEN_CACHE_DIR", "")
    assert acquisition._cache_dir() is None  # empty env disables the cache


# ---- the counting call sites follow the acquisition --------------------------


def test_count_tokens_prefers_local_encoding_and_falls_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import deeptutor.services.session.context_builder as context_builder

    text = "alpha beta gamma"
    monkeypatch.setattr(context_builder, "get_local_encoding", lambda: _StubEncoding())
    assert count_tokens(text) == 3
    monkeypatch.setattr(context_builder, "get_local_encoding", lambda: None)
    assert count_tokens(text) == max(1, len(text) // 4)


def test_count_tokens_edge_cases_without_local_encoding(monkeypatch: pytest.MonkeyPatch) -> None:
    import deeptutor.services.session.context_builder as context_builder

    monkeypatch.setattr(context_builder, "get_local_encoding", lambda: None)
    assert count_tokens("") == 0
    assert count_tokens("x") == 1  # heuristic floors at one token
    assert count_tokens(None) == 0  # type: ignore[arg-type]


def test_count_tokens_survives_encoding_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    import deeptutor.services.session.context_builder as context_builder

    monkeypatch.setattr(context_builder, "get_local_encoding", lambda: _ExplodingEncoding())
    assert count_tokens("four four four four ") == 5  # 20 chars -> chars/4


def test_detect_counter_name_tracks_encoding_availability(monkeypatch: pytest.MonkeyPatch) -> None:
    from deeptutor.agents.loop.context_budget import detect_counter_name

    monkeypatch.setattr(token_encoding, "get_local_encoding", lambda: None)
    assert detect_counter_name() == "heuristic"
    monkeypatch.setattr(token_encoding, "get_local_encoding", lambda: _StubEncoding())
    assert detect_counter_name() == "cl100k_base"


# ---- real tiktoken, offline: cold and warm -----------------------------------


def test_real_tiktoken_cold_cache_stays_local_and_quick(
    acquisition: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Any, no_network: list[str]
) -> None:
    """End to end with the real tiktoken import: a cold cache yields the
    heuristic without entering tiktoken's loader (which would download)."""
    pytest.importorskip("tiktoken")
    monkeypatch.setenv("TIKTOKEN_CACHE_DIR", str(tmp_path / "cold"))

    began = time.monotonic()
    encoding = acquisition.get_local_encoding()
    assert time.monotonic() - began < 1.0
    assert encoding is None
    _settle()
    assert acquisition._encoding is None
    assert no_network == []
    assert count_tokens("some chat text") == max(1, len("some chat text") // 4)


def test_real_warm_cache_parity(
    acquisition: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Any, no_network: list[str]
) -> None:
    """Optional parity only: exact ``cl100k_base`` counts against tiktoken.

    Requires a verified local fixture of the published ranks and skips
    without one; the always-run race tests above already cover the
    no-download guarantees using the synthetic verified blob.
    """
    tiktoken = pytest.importorskip("tiktoken")
    _warm_real_cache(monkeypatch, tmp_path)

    acquisition.get_local_encoding()
    encoding = _wait_ready()
    reference = tiktoken.get_encoding("cl100k_base")  # warm verified cache: local read

    assert encoding.encode("Hello, world!") == [9906, 11, 1917, 0]
    for sample in (
        "Hello, world!",
        "def f(x):\n    return x ** 2\n",
        "中文 token 计数测试 🙂",
        "<|endoftext|>",
        "  trailing whitespace\tand\nnewlines  ",
    ):
        assert encoding.encode(sample, allowed_special="all") == reference.encode(
            sample, allowed_special="all"
        )
    assert encoding.n_vocab == reference.n_vocab
    assert count_tokens("Hello, world!") == 4
    assert no_network == []
