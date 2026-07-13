from __future__ import annotations

from deeptutor.services.parsing.signature import ParserSignature


def test_hash_is_order_independent() -> None:
    a = ParserSignature.build("mineru", "2.0", {"mode": "local", "lang": "en"})
    b = ParserSignature.build("mineru", "2.0", {"lang": "en", "mode": "local"})
    assert a.hash() == b.hash()


def test_hash_changes_with_params_version_and_engine() -> None:
    base = ParserSignature.build("mineru", "2.0", {"mode": "local"})
    assert base.hash() != ParserSignature.build("mineru", "2.0", {"mode": "cloud"}).hash()
    assert base.hash() != ParserSignature.build("mineru", "2.1", {"mode": "local"}).hash()
    assert base.hash() != ParserSignature.build("docling", "2.0", {"mode": "local"}).hash()


def test_hash_is_short_hex() -> None:
    h = ParserSignature.build("x", "1", {}).hash()
    assert len(h) == 16
    int(h, 16)  # hex-decodable
