"""Pricing: what a lesson costs in money, from a real published rate.

The cost column had a token count and no price. Multiplying by a guessed rate
would repeat the `len // 4` mistake in a different unit, so these tests pin two
things: that the arithmetic is exact at the scale real prices are quoted in, and
that "free" and "unpriced" never collapse into one another.
"""

from __future__ import annotations

import pytest

from deeptutor.services.studio import pricing as P

MODEL = "nvidia/nemotron-3.5-super-vl"
FREE = "nvidia/nemotron-3.5-super-vl:free"


# ---------------------------------------------------------------------------
# Arithmetic
# ---------------------------------------------------------------------------


def test_a_known_rate_gives_a_known_cost():
    """6e-8 in, 3.5e-7 out: 100 tokens each is 0.000041 USD."""
    price = P.Price("test", 6e-8, 3.5e-7)
    assert price.cost_microusd(100, 100) == 41


def test_micro_usd_is_an_integer_so_a_ledger_can_sum_it():
    for prompt, completion in [(1, 1), (79, 106), (5000, 2048), (0, 0)]:
        value = P.Price("t", 6e-8, 3.5e-7).cost_microusd(prompt, completion)
        assert isinstance(value, int)


def test_the_arithmetic_is_exact_rather_than_float_rounded():
    """A specific case where naive float arithmetic gives the wrong integer.

    25 tokens at the cheapest catalogue rate is 1.5 micro-USD. Rounded half-up
    from an exact decimal that is 2; computed as a float and nudged by 0.5 it
    lands on 1, because 25 * 6e-8 * 1e6 is 1.4999999999999998 in binary
    floating point. This is not a hypothetical -- 396 such cases exist across
    the catalogue's rates and plausible token counts. The test would have
    passed against a float implementation if it only checked determinism, which
    is why it checks the number instead.
    """
    price = P.Price("test", 6e-8, 3.5e-7)
    assert price.cost_microusd(25, 0) == 2
    assert price.cost_microusd(75, 0) == 5
    assert price.cost_microusd(135, 1024) == 367


def test_cost_is_monotonic_in_tokens():
    price = P.Price("t", 1e-7, 4e-7)
    previous = -1
    for n in (0, 1, 10, 100, 1000, 10000):
        current = price.cost_microusd(n, n)
        assert current >= previous
        previous = current


def test_completion_tokens_cost_more_than_prompt_tokens():
    """True for every endpoint in the catalogue, and the whole margin model."""
    for endpoint in P.endpoints_for(MODEL):
        assert endpoint.completion_usd_per_token > endpoint.prompt_usd_per_token


# ---------------------------------------------------------------------------
# Free is zero, unpriced is unknown
# ---------------------------------------------------------------------------


def test_a_free_endpoint_costs_exactly_zero():
    quote = P.quote(FREE, prompt_tokens=1000, completion_tokens=1000)
    assert quote["cost_usd"] == 0.0
    assert quote["cost_microusd"] == 0


def test_zero_and_unknown_are_different_answers():
    """The type carries the difference: None means nobody priced it."""
    quote = P.quote(FREE, prompt_tokens=10, completion_tokens=10)
    assert quote["cost_microusd"] == 0
    assert None is not quote["cost_microusd"]


def test_the_free_model_is_not_silently_chosen_from_the_paid_catalogue():
    """Price a paid model and you get a paid endpoint, not the free one."""
    quote = P.quote(MODEL, prompt_tokens=100, completion_tokens=100)
    assert quote["cost_microusd"] > 0
    assert quote["endpoint"] != "Nvidia"


def test_an_unrecorded_model_raises_rather_than_inventing_a_price():
    with pytest.raises(KeyError) as exc:
        P.endpoints_for("some/model/we/never-read")
    assert "guessing a rate" in str(exc.value)


def test_an_unknown_endpoint_name_lists_the_known_ones():
    with pytest.raises(KeyError) as exc:
        P.quote(MODEL, prompt_tokens=1, completion_tokens=1, endpoint="nope")
    assert "known" in str(exc.value)


# ---------------------------------------------------------------------------
# Provenance
# ---------------------------------------------------------------------------


def test_every_catalogue_entry_records_when_it_was_read():
    for model, entry in P.CATALOGUE.items():
        assert entry["read_at"], f"{model} has no read date"
        assert entry["source"].startswith("https://openrouter.ai/"), model


def test_every_quote_carries_the_price_and_its_date():
    quote = P.quote(MODEL, prompt_tokens=79, completion_tokens=106)
    assert quote["price"]["in"] > 0
    assert quote["price"]["unit"] == "USD/token"
    assert quote["price_read_at"]


def test_the_cheapest_paid_endpoint_is_the_one_used_by_default():
    quote = P.quote(MODEL, prompt_tokens=1000, completion_tokens=1000)
    cheapest = P.cheapest_paid(MODEL)
    assert quote["endpoint"] == cheapest.endpoint
    for other in P.endpoints_for(MODEL):
        if other.prompt_usd_per_token > 0:
            assert other.cost_microusd(1000, 1000) >= quote["cost_microusd"]


# ---------------------------------------------------------------------------
# The limit that makes a free plan not-free
# ---------------------------------------------------------------------------


def test_a_free_model_reports_its_daily_request_cap_not_zero_cost():
    ceiling = P.daily_ceiling(FREE)
    assert ceiling["free"] is True
    assert ceiling["binding_constraint"] == "requests_per_day"
    assert ceiling["lessons_per_day"] == 50
    assert ceiling["requests_per_minute"] == 20


def test_the_free_ceiling_names_the_upgrade():
    """A limit without the way past it is just a wall."""
    note = P.daily_ceiling(FREE)["note"]
    assert "1000" in note


def test_a_paid_model_reports_a_budget_ceiling_instead():
    ceiling = P.daily_ceiling(MODEL, usd_per_day=1.0)
    assert ceiling["free"] is False
    assert ceiling["binding_constraint"] == "budget"
    assert ceiling["lessons_per_day"] > 0


def test_asking_for_a_paid_ceiling_without_a_budget_raises():
    with pytest.raises(ValueError):
        P.daily_ceiling(MODEL)


def test_a_thousand_lessons_on_the_cheapest_endpoint_cost_cents():
    """The number Gate 8 could not state before: 4 cents for a thousand."""
    quote = P.quote(MODEL, prompt_tokens=79, completion_tokens=106)
    total = quote["cost_usd"] * 1000
    assert 0 < total < 1.0, f"${total} for 1000 lessons"


# ---------------------------------------------------------------------------
# The priced cost reaches the ledger
# ---------------------------------------------------------------------------


def _owner(db):
    from deeptutor.db.repositories.identity import IdentityRepository
    from deeptutor.db.repositories.wallets import WalletRepository

    IdentityRepository(db).save("u1", {"id": "u1", "hash": "x", "role": "user"})
    WalletRepository(db).grant("u1", tokens=500_000)


def _run_priced(db, *, microusd=42, price=None):
    from deeptutor.db.jobs.queue import JobQueue
    from deeptutor.services.studio import jobs as S

    queue = JobQueue(db, worker_id="t")
    submitted = S.submit(
        db,
        queue=queue,
        request=S.JobRequest(user_id="u1", kind="mind_map", script="مشتق چیست؟"),
    )

    def renderer(kind, payload):
        return S.RenderResult(
            storage_path="media/u1/x.png",
            mime_type="image/png",
            size_bytes=100,
            actual_tokens=185,
            provider="openrouter",
            actual_cost_microusd=microusd,
            price=price,
            content="مشتق نرخ تغییر است.",
        )

    while queue.run_once(
        {S.job_kind("mind_map"): lambda job: S.run_job(db, queue=queue, job=job, renderer=renderer)}
    ):
        pass
    return S.job_costs(db, submitted["job_id"])


def test_the_actual_cost_row_carries_money_not_only_tokens(db):
    _owner(db)
    rows = _run_priced(db)
    actual = [r for r in rows if r["phase"] == "actual"][0]
    assert actual["cost_microusd"] == 42
    assert actual["tokens"] == 185


def test_the_estimate_row_stays_unpriced_because_nothing_has_run(db):
    """None, not 0: an estimate is not a measured cost."""
    _owner(db)
    rows = _run_priced(db)
    estimate = [r for r in rows if r["phase"] == "estimate"][0]
    assert estimate["cost_microusd"] is None


def test_the_price_used_is_stored_with_the_cost(db):
    """Prices change; a cost whose rate is lost cannot be audited."""
    _owner(db)
    price = {"endpoint": "Darkbloom nvfp4", "in": 6e-8, "out": 3.5e-7, "unit": "USD/token"}
    rows = _run_priced(db, price=price)
    actual = [r for r in rows if r["phase"] == "actual"][0]
    import json

    stored = json.loads(actual["price_json"])
    assert stored["endpoint"] == "Darkbloom nvfp4"
    assert stored["unit"] == "USD/token"


def test_a_free_render_records_zero_and_stays_zero(db):
    _owner(db)
    rows = _run_priced(db, microusd=0)
    actual = [r for r in rows if r["phase"] == "actual"][0]
    assert actual["cost_microusd"] == 0


def test_an_unpriced_render_leaves_the_column_null_not_zero(db):
    _owner(db)
    rows = _run_priced(db, microusd=None)
    actual = [r for r in rows if r["phase"] == "actual"][0]
    assert actual["cost_microusd"] is None
