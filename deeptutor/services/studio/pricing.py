"""What a render costs in money, not only in tokens.

Why this module exists
----------------------
The cost ledger could say "a mind map costs 600 tokens". That is a measurement
of length, not of money. Gate 8's cost column asks what a lesson costs, and the
only honest way to answer is to multiply the token count by the price the
provider actually charges — and to keep that price with the row so the answer
can be re-derived when the price changes.

Where the numbers come from
---------------------------
Prices are not guessed and not typed from memory. They are read from the
provider's public model catalogue, which lists every endpoint for a model with
its per-token prompt and completion rates. :data:`CATALOGUE` holds one such
reading, with the date it was taken. A price list is a fact about a moment, so
it carries its timestamp.

The free tier is free, and that is a constraint
-----------------------------------------------
``nvidia/nemotron-3.5-super-vl:free`` resolves to a single endpoint priced at
exactly zero. Zero is a real price, and it is why
:data:`FREE_TIER_LIMITS` matters: a free model is rate-limited to 20 requests
per minute and 50 per day on an account that has not purchased credits. A
pipeline measured at 86 jobs/second is therefore not limited by this host at
all — it is limited to 50 lessons per day. Recording the price without
recording the limit would turn "we can afford it" into a false conclusion.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

#: Micro-USD per US dollar. The ledger stores integers in this unit.
MICRO = 1_000_000


@dataclass(frozen=True)
class Price:
    """One endpoint's published rate, in USD per token."""

    endpoint: str
    prompt_usd_per_token: float
    completion_usd_per_token: float
    #: Reported uptime over the last day, where the catalogue provides it.
    uptime_1d: float | None = None

    def cost_microusd(self, prompt_tokens: int, completion_tokens: int) -> int:
        """Total cost in integer micro-USD, rounded half-up.

        Uses Decimal rather than float for the multiplication: at 6e-8 USD per
        token, a float product of a few hundred tokens lands near the edge of
        the representable cents, and rounding it twice gives a number that
        disagrees with itself between runs.
        """
        total = (
            Decimal(str(prompt_tokens)) * Decimal(str(self.prompt_usd_per_token))
            + Decimal(str(completion_tokens)) * Decimal(str(self.completion_usd_per_token))
        )
        scaled = (total * MICRO).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        return int(scaled)

    def as_dict(self) -> dict[str, Any]:
        return {
            "endpoint": self.endpoint,
            "in": self.prompt_usd_per_token,
            "out": self.completion_usd_per_token,
            "unit": "USD/token",
        }


#: Readings from the provider catalogue. Each entry records when it was taken:
#: a price list without a date is a rumour.
CATALOGUE: dict[str, dict[str, Any]] = {
    "nvidia/nemotron-3.5-super-vl": {
        "read_at": "2026-11-18",
        "source": "https://openrouter.ai/api/v1/models/nvidia/nemotron-3.5-super-vl/endpoints",
        "context_length": 1_048_576,
        "endpoints": (
            Price("Darkbloom nvfp4", 6e-8, 3.5e-7, 44.3),
            Price("Crusoe bf16", 1e-7, 4e-7, 99.2),
            Price("CoreWeave nvfp4", 1.5e-7, 4.7e-7, 99.9),
            Price("Together", 1.5e-7, 5e-7, 100.0),
            Price("DeepInfra fp4", 1.5e-7, 5e-7, 99.9),
            Price("BaseTen fp4", 2e-7, 5e-7, 100.0),
            Price("Nebius fp4", 3e-7, 9e-7, 99.8),
            Price("Io Net nvfp4", 5.9e-7, 1.83e-6, 99.3),
        ),
    },
    "nvidia/nemotron-3.5-super-vl:free": {
        "read_at": "2026-11-18",
        "source": "https://openrouter.ai/api/v1/models/nvidia/nemotron-3.5-super-vl:free/endpoints",
        "context_length": 1_000_000,
        "endpoints": (Price("Nvidia", 0.0, 0.0, 100.0),),
    },
}

#: Free-model rate limits, which are the real ceiling on a zero-cost plan.
#: The tier is chosen by all-time credits purchased, not by whether the account
#: has paid before.
FREE_TIER_LIMITS: dict[str, dict[str, int]] = {
    "under_10_credits": {"requests_per_minute": 20, "requests_per_day": 50},
    "at_least_10_credits": {"requests_per_minute": 20, "requests_per_day": 1000},
}


def endpoints_for(model: str) -> tuple[Price, ...]:
    try:
        return CATALOGUE[model]["endpoints"]
    except KeyError as exc:
        raise KeyError(
            f"{model!r} has no recorded prices; read them from the provider "
            f"catalogue and add an entry to pricing.CATALOGUE rather than "
            f"guessing a rate"
        ) from exc


def cheapest_paid(model: str) -> Price:
    """The cheapest endpoint that actually charges. Free endpoints are excluded:
    a free endpoint is not a budget, it is a promotion with a daily cap."""
    paid = [p for p in endpoints_for(model) if p.prompt_usd_per_token > 0]
    if not paid:
        raise ValueError(f"{model!r} has no paid endpoint; nothing to price")
    return min(paid, key=lambda p: p.prompt_usd_per_token + p.completion_usd_per_token)


def quote(
    model: str,
    *,
    prompt_tokens: int,
    completion_tokens: int,
    endpoint: str | None = None,
) -> dict[str, Any]:
    """Price one render on one endpoint, and say which endpoint was used."""
    options = endpoints_for(model)
    if endpoint is None:
        # Only one endpoint: no choice to make. With several, default to the
        # cheapest that charges, because "" should not silently mean "the free
        # one" -- free is a promotion with a daily cap, and picking it by
        # accident is how a pipeline discovers the cap in production.
        if len(options) == 1:
            chosen = options[0]
        else:
            chosen = cheapest_paid(model)
    else:
        matches = [p for p in options if p.endpoint == endpoint]
        if not matches:
            known = sorted(p.endpoint for p in options)
            raise KeyError(f"{endpoint!r} not found for {model!r}; known: {known}")
        chosen = matches[0]

    micro = chosen.cost_microusd(prompt_tokens, completion_tokens)
    return {
        "model": model,
        "endpoint": chosen.endpoint,
        "cost_microusd": micro,
        "cost_usd": micro / MICRO,
        "tokens": {"prompt": prompt_tokens, "completion": completion_tokens},
        "price": chosen.as_dict(),
        "price_read_at": CATALOGUE[model]["read_at"],
    }


def daily_ceiling(model: str, usd_per_day: float | None = None) -> dict[str, Any]:
    """How many lessons a day this plan supports, and what binds it.

    For a free model the binding constraint is the request cap, not money.
    Saying "the free model costs nothing" and stopping there is the kind of
    half-truth this phase keeps finding: it costs nothing and it serves fifty
    lessons a day.
    """
    options = endpoints_for(model)
    is_free = all(p.prompt_usd_per_token == 0 for p in options)
    if is_free:
        tier = FREE_TIER_LIMITS["under_10_credits"]
        return {
            "model": model,
            "free": True,
            "binding_constraint": "requests_per_day",
            "lessons_per_day": tier["requests_per_day"],
            "requests_per_minute": tier["requests_per_minute"],
            "note": (
                "a free endpoint is capped by request count, not by spend; "
                "buying 10 credits raises the daily cap to "
                f"{FREE_TIER_LIMITS['at_least_10_credits']['requests_per_day']}"
            ),
        }
    if usd_per_day is None:
        raise ValueError("a paid model needs a daily budget to compute a ceiling")
    cheapest = cheapest_paid(model)
    per_lesson = cheapest.cost_microusd(1, 1) or 1
    return {
        "model": model,
        "free": False,
        "binding_constraint": "budget",
        "lessons_per_day": int(usd_per_day * MICRO // per_lesson),
        "budget_usd_per_day": usd_per_day,
    }
