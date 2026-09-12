"""The monthly cap (PRD AI-2, AI-3, ADR-D7).

Offline: the arithmetic and the refusal, without a database.

The design being tested: we never invent a price, so the cap has two halves —
dollars when the calls can be priced, and a plain count of calls always. A cap
that quietly stopped counting because a price was missing would be the
surprise bill AI-2 exists to prevent.
"""

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from usali.desktop.ai.port import SpendCapReached, Usage
from usali.desktop.ai.spend import (
    DEFAULT_CAP,
    Prices,
    Spend,
    check,
    estimate,
    month_start,
    payload_hash,
)

PRICED = Prices(per_million_input=Decimal("3.00"), per_million_output=Decimal("15.00"))
USED = Usage(prompt_tokens=1000, completion_tokens=500)


def _spend(**over: object) -> Spend:
    base = {
        "month_start": date(2026, 6, 1), "calls": 1, "estimated_cost": Decimal("0.01"),
        "unpriced_calls": 0, "cap": DEFAULT_CAP, "max_calls": 500,
    }
    base.update(over)
    return Spend(**base)  # type: ignore[arg-type]


def test_the_default_cap_is_the_one_the_prd_names() -> None:
    assert DEFAULT_CAP == Decimal("10.00")


def test_a_priced_call_costs_what_the_owners_rates_say() -> None:
    # 1000 in at $3/M plus 500 out at $15/M = 0.003 + 0.0075.
    assert estimate(USED, PRICED) == Decimal("0.010500")


def test_a_model_we_have_no_price_for_is_not_guessed_at() -> None:
    assert estimate(USED, Prices()) is None
    # Half a price is no price: a total built on one rate would be wrong in a
    # direction nobody could see.
    assert estimate(USED, Prices(per_million_input=Decimal("3.00"))) is None


def test_a_provider_that_reported_no_tokens_cannot_be_priced() -> None:
    assert estimate(Usage(None, None), PRICED) is None


def test_a_model_on_this_machine_costs_nothing_and_says_so() -> None:
    """The one price we can assert without being told."""
    assert estimate(USED, Prices(local=True)) == Decimal("0")
    assert estimate(Usage(None, None), Prices(local=True)) == Decimal("0")


def test_a_month_with_an_unpriced_call_reports_no_total() -> None:
    """An honest "we don't know" rather than a total that quietly omits
    the calls it could not price."""
    unknown = _spend(estimated_cost=None, unpriced_calls=3)
    assert unknown.estimated_cost is None
    # ...and it is not treated as zero: the call count still stops it.
    assert unknown.stopped is False
    assert _spend(estimated_cost=None, unpriced_calls=3, calls=500).stopped is True


def test_the_dollar_half_stops_at_the_cap() -> None:
    assert _spend(estimated_cost=Decimal("9.99")).stopped is False
    assert _spend(estimated_cost=Decimal("10.00")).stopped is True


def test_each_half_says_which_one_stopped_it() -> None:
    """They have different answers — wait for next month, or raise the
    limit — so the message has to distinguish them."""
    with pytest.raises(SpendCapReached, match="all 500 AI checks"):
        check(_spend(calls=500))
    with pytest.raises(SpendCapReached, match=r"\$10.00 monthly limit"):
        check(_spend(estimated_cost=Decimal("12.00")))
    check(_spend())  # under both: no refusal


def test_the_month_starts_on_the_first() -> None:
    assert month_start(datetime(2026, 6, 17, 23, 30, tzinfo=UTC)) == date(2026, 6, 1)


def test_what_left_is_recorded_as_a_hash_not_as_itself() -> None:
    """AI-5 asks for a hash of the payload. Keeping the prompt would put
    transaction data in a second place for no added assurance."""
    prompt = "Printed on the report as: Cabana Rental"
    digest = payload_hash(prompt)
    assert len(digest) == 64 and digest == payload_hash(prompt)
    assert "Cabana" not in digest
    assert payload_hash("something else") != digest
