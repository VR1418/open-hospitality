"""The spend cap, and the record of what left (PRD AI-2, AI-3, AI-5).

AI-2 asks for "a hard monthly spend cap, defaulting to $10, enforced locally.
At the cap the feature stops and says so. There is no path to a surprise bill."

Two things follow from taking that literally.

**We do not invent prices.** Model prices change, and a figure this app made up
would be wrong in a way the owner could not see. So the price is something the
owner can tell us — two numbers, per million tokens, from their provider's own
page — and when they have not, spend is not estimated at all. A local model on
localhost is zero, and says so.

**So the cap has two halves.** Dollars, when we can price the calls; and a
plain count of calls, always, which is the half that still holds when we
cannot. A cap that quietly stopped counting because a price was missing would
be the surprise bill AI-2 exists to prevent.
"""

import hashlib
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import text
from sqlalchemy.orm import Session

from usali.desktop.ai.port import SpendCapReached, Usage

#: PRD AI-2's default. Dollars.
DEFAULT_CAP = Decimal("10.00")
#: The other half of the cap, in calls. It applies whether or not the calls
#: can be priced, so the feature always stops somewhere.
DEFAULT_MAX_CALLS = 500

_MILLION = Decimal("1000000")
_CENTS = Decimal("0.000001")


@dataclass(frozen=True)
class Prices:
    """What the owner's provider charges, as the owner entered it.

    Both None means "not priced" — not "free". `local` is the one case we can
    assert for ourselves: a model served from this machine costs nothing.
    """

    per_million_input: Decimal | None = None
    per_million_output: Decimal | None = None
    local: bool = False


@dataclass(frozen=True)
class Spend:
    """Where the month stands. Shown in the app at all times (AI-3)."""

    month_start: date
    calls: int
    #: None when some of the month's calls could not be priced — an honest
    #: "we don't know" rather than a total that quietly omits them.
    estimated_cost: Decimal | None
    unpriced_calls: int
    cap: Decimal
    max_calls: int

    @property
    def stopped(self) -> bool:
        if self.calls >= self.max_calls:
            return True
        return self.estimated_cost is not None and self.estimated_cost >= self.cap


def month_start(now: datetime | None = None) -> date:
    at = now or datetime.now(UTC)
    return date(at.year, at.month, 1)


def estimate(usage: Usage, prices: Prices) -> Decimal | None:
    """What one call cost, or None when we cannot say.

    A provider that reported no token counts cannot be priced even when the
    rates are known — another reason the call count is the half that always
    holds.
    """
    if prices.local:
        return Decimal("0")
    if prices.per_million_input is None or prices.per_million_output is None:
        return None
    if usage.prompt_tokens is None or usage.completion_tokens is None:
        return None
    total = (
        Decimal(usage.prompt_tokens) * prices.per_million_input
        + Decimal(usage.completion_tokens) * prices.per_million_output
    ) / _MILLION
    return total.quantize(_CENTS, rounding=ROUND_HALF_UP)


def payload_hash(prompt: str) -> str:
    """A hash of what left, for the audit row (AI-5). The prompt itself is
    never stored: keeping it would put transaction data in a second place for
    no added assurance."""
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()


def this_month(
    session: Session, *, cap: Decimal = DEFAULT_CAP, max_calls: int = DEFAULT_MAX_CALLS,
    now: datetime | None = None,
) -> Spend:
    """The month's calls and cost so far.

    Failed and blocked calls are counted: a provider that errored after
    reading the prompt may still have billed for it, and a request the
    allow-list refused is a bug worth rate-limiting either way.
    """
    start = month_start(now)
    row = session.execute(
        text(
            "SELECT count(*) AS calls,"
            " count(*) FILTER (WHERE estimated_cost IS NULL) AS unpriced,"
            " coalesce(sum(estimated_cost), 0) AS spent"
            " FROM desktop.ai_call WHERE called_at >= :start"
        ),
        {"start": start},
    ).one()
    unpriced = int(row.unpriced)
    return Spend(
        month_start=start,
        calls=int(row.calls),
        estimated_cost=None if unpriced else Decimal(row.spent),
        unpriced_calls=unpriced,
        cap=cap,
        max_calls=max_calls,
    )


def check(spend: Spend) -> None:
    """Refuse before the call, not after (AI-2). The message says which half
    of the cap stopped it, because the two have different answers: wait for
    next month, or raise the limit."""
    if spend.calls >= spend.max_calls:
        raise SpendCapReached(
            f"You've used all {spend.max_calls} AI checks for this month. "
            "They start again on the 1st, or you can raise the limit in AI settings."
        )
    if spend.estimated_cost is not None and spend.estimated_cost >= spend.cap:
        raise SpendCapReached(
            f"You've reached your ${spend.cap} monthly limit for AI. "
            "It starts again on the 1st, or you can raise the limit in AI settings."
        )


def record(
    session: Session,
    *,
    actor_subject: str,
    provider: str,
    model: str,
    purpose: str,
    property_id: str | None,
    usage: Usage,
    prices: Prices,
    prompt: str,
    outcome: str,
    message: str | None = None,
) -> Decimal | None:
    """Write the call's row and return what it was estimated to cost.

    Does not commit: the caller owns the transaction, so the ledger row, the
    audit event and the suggestion land together or not at all — the house
    rule `integrations_api` and `crm_api` already follow.
    """
    cost = estimate(usage, prices)
    session.execute(
        text(
            "INSERT INTO desktop.ai_call (actor_subject, provider, model, purpose,"
            " property_id, prompt_tokens, completion_tokens, estimated_cost,"
            " payload_sha256, outcome, message)"
            " VALUES (:actor, :provider, :model, :purpose, :property_id, :prompt_tokens,"
            " :completion_tokens, :cost, :hash, :outcome, :message)"
        ),
        {
            "actor": actor_subject,
            "provider": provider,
            "model": model,
            "purpose": purpose,
            "property_id": property_id,
            "prompt_tokens": usage.prompt_tokens,
            "completion_tokens": usage.completion_tokens,
            "cost": cost,
            "hash": payload_hash(prompt),
            "outcome": outcome,
            "message": (message or None) and message[:300],
        },
    )
    return cost
