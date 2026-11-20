"""The licence catalogue and the cost method, over the API.

Both exist because a refusal needs an explanation and a cost figure needs an
error bar. Neither is a control by itself; they are what makes the two controls
in Gate 8 usable.
"""

from __future__ import annotations

import asyncio

from fastapi import HTTPException
import pytest

from deeptutor.api.routers import studio as api
from deeptutor.db.config import DatabaseSettings, reset_database_settings
from deeptutor.db.repositories.identity import IdentityRepository
from deeptutor.db.repositories.wallets import WalletRepository
from deeptutor.services.studio import jobs as S
from deeptutor.services.studio import licences


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture
def live(db, monkeypatch):
    settings = DatabaseSettings(app_url=db.settings.app_url, backend=db.settings.backend)
    monkeypatch.setattr("deeptutor.db.config.get_database_settings", lambda: settings)
    reset_database_settings()
    IdentityRepository(db).save("u1", {"id": "u1", "hash": "x", "role": "user"})
    WalletRepository(db).grant("u1", tokens=5000)
    return db


# ---------------------------------------------------------------------------
# Catalogue
# ---------------------------------------------------------------------------


def test_the_catalogue_lists_every_registered_licence(live):
    body = _run(api.licence_catalogue())
    assert {entry["code"] for entry in body["licences"]} == set(licences.REGISTRY)


def test_the_catalogue_explains_what_each_licence_permits(live):
    body = _run(api.licence_catalogue())
    citation = next(e for e in body["licences"] if e["code"] == "citation-only")
    assert "reproduce" in citation["grants"]
    assert "render_visual" not in citation["grants"]


def test_the_catalogue_says_what_each_kind_needs(live):
    body = _run(api.licence_catalogue())
    for kind in S.MEDIA_KINDS:
        assert body["requirements"][kind], f"{kind} declares no requirement"


def test_the_catalogue_is_reachable_without_a_wallet(live):
    """Knowing which licences exist is not a paid operation."""
    body = _run(api.licence_catalogue())
    assert body["licences"]


def test_the_catalogue_matches_the_enforcement_point(live):
    """If the catalogue and the check disagree, the catalogue is a lie."""
    body = _run(api.licence_catalogue())
    for entry in body["licences"]:
        granted = set(entry["grants"])
        for kind, needed in body["requirements"].items():
            satisfiable = set(needed) <= granted and set(
                entry.get("requires", [])
            ) <= set(licences.SATISFIABLE_REQUIREMENTS)
            # A refusal costs nothing, but an acceptance commits tokens, so the
            # wallet is topped up per attempt: otherwise the loop measures the
            # balance instead of the licence.
            WalletRepository(live).grant("u1", tokens=5000)
            if satisfiable:
                assert _run(
                    api.submit_job(
                        api.SubmitPayload(
                            kind=kind,
                            script=f"متن {entry['code']} {kind}",
                            source_id="s1",
                            licence_code=entry["code"],
                        ),
                        user_id="u1",
                    )
                )["job_id"]
            else:
                with pytest.raises(HTTPException) as exc:
                    _run(
                        api.submit_job(
                            api.SubmitPayload(
                                kind=kind,
                                script=f"متن {entry['code']} {kind}",
                                source_id="s1",
                                licence_code=entry["code"],
                            ),
                            user_id="u1",
                        )
                    )
                assert exc.value.status_code in (403, 422)


# ---------------------------------------------------------------------------
# Cost method
# ---------------------------------------------------------------------------


def test_the_cost_endpoint_states_the_method_and_the_error(live):
    body = _run(api.cost_method())
    assert body["tokenizer"]
    assert body["uncertainty"] is not None
    assert "calibration" in body


def test_an_inexact_counter_never_claims_zero_uncertainty(live):
    body = _run(api.cost_method())
    if body["exact"]:
        assert body["uncertainty"] == 0.0
    else:
        assert body["uncertainty"] > 0


def test_the_calibration_shipped_to_clients_carries_the_measurement(live):
    body = _run(api.cost_method())
    calibration = body["calibration"]
    assert calibration["reference"] == "cl100k_base"
    assert calibration["sample_size"] >= 10
    assert calibration["reference_tokens"] > 0


def test_the_known_limits_are_published_not_hidden(live):
    body = _run(api.cost_method())
    assert body["known_limits"], "a cost figure without its limits is a claim"
