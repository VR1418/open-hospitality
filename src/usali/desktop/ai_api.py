"""The owner's own AI helper (PRD §6.3, ADR-D7).

    GET    /api/desktop/ai          what's set up, and what this month has cost
    PUT    /api/desktop/ai          choose a provider, a model, and the limits
    DELETE /api/desktop/ai/key      forget the key
    POST   /api/desktop/ai/suggest  ask where one charge code belongs

**No secret is ever returned.** The GET says whether a key is saved and
nothing else; `test_the_key_is_never_on_the_wire` greps the whole body, the
`integrations_api` guard applied here.

**Nothing here writes to the books.** A suggestion is a proposal. Accepting one
goes through `PUT /api/desktop/codes/{code}` — the same endpoint the owner's
own choice goes through — with `origin="ai-accepted"` and their subject in
`decided_by` (AI-6). There is deliberately no "apply" endpoint on this router.
"""

from decimal import Decimal

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from usali.auth import (
    ORG_ADMIN,
    Principal,
    request_session_factory,
    require_active_org,
    require_grants,
    require_operator,
)
from usali.desktop.ai import client, config, spend
from usali.desktop.ai.allowlist import CodeQuestion, LineChoice
from usali.desktop.ai.port import AiError, NotConfigured, SpendCapReached
from usali.desktop.ai.spend import Prices
from usali.desktop.codes_api import DEFAULT_EDITION, Line, known_lines, require_property
from usali.desktop.keystore import KeyStore
from usali.desktop.paths import DesktopPaths
from usali.models import PmsDailyFinancialStage

_owner = require_grants(ORG_ADMIN)
router = APIRouter(dependencies=[Depends(require_operator), Depends(require_active_org)])

#: How many individual amounts the model is shown. Enough to tell a fixed fee
#: from a per-night charge; not a transaction list.
SAMPLE_AMOUNTS = 5


class ProviderChoice(BaseModel):
    id: str
    name: str
    needs_address: bool
    needs_key: bool


class SpendOut(BaseModel):
    month_start: str
    calls: int
    #: None when some of the month's calls could not be priced — an honest
    #: "we don't know", never a total that quietly omits them.
    estimated_cost: str | None
    unpriced_calls: int
    cap: str
    max_calls: int
    stopped: bool


class AiOut(BaseModel):
    provider: str | None
    model: str
    base_url: str | None
    cap: str
    max_calls: int
    price_in: str | None
    price_out: str | None
    #: Whether a key is saved on this computer. Never the key itself.
    key_saved: bool
    local: bool
    spend: SpendOut
    providers: list[ProviderChoice]


class AiIn(BaseModel):
    provider: str
    model: str = Field(min_length=1, max_length=120)
    base_url: str | None = Field(default=None, max_length=300)
    cap: str = "10.00"
    max_calls: int = Field(default=spend.DEFAULT_MAX_CALLS, ge=1, le=100000)
    price_in: str | None = None
    price_out: str | None = None
    #: Write-only, and only when it is being set or replaced. It goes to the
    #: OS keychain and never to the database (AI-1).
    key: str | None = Field(default=None, max_length=500)


class SuggestIn(BaseModel):
    property_id: str = Field(min_length=1, max_length=50)
    pms_source: str = Field(min_length=1, max_length=20)
    code: str = Field(min_length=1, max_length=50)
    edition: int = DEFAULT_EDITION


class SuggestOut(BaseModel):
    code: str
    #: None when the model declined, which it is required to be able to do
    #: on tax and capitalisation questions (AI-7).
    line: Line | None
    confidence: str
    reason: str
    decline_reason: str | None
    estimated_cost: str | None
    model: str
    spend: SpendOut


def _paths(request: Request) -> DesktopPaths:
    return request.app.state.desktop_ai_paths  # type: ignore[no-any-return]


def _store(request: Request) -> KeyStore:
    return request.app.state.desktop_ai_store  # type: ignore[no-any-return]


def _spend_out(s: spend.Spend) -> SpendOut:
    return SpendOut(
        month_start=s.month_start.isoformat(), calls=s.calls,
        estimated_cost=None if s.estimated_cost is None else str(s.estimated_cost),
        unpriced_calls=s.unpriced_calls, cap=str(s.cap), max_calls=s.max_calls,
        stopped=s.stopped,
    )


def _providers() -> list[ProviderChoice]:
    return [
        ProviderChoice(
            id=pid, name=config.PROVIDER_NAMES[pid],
            needs_address=pid == "openai_compatible", needs_key=pid != "mock",
        )
        for pid in config.PROVIDERS
    ]


def _decimal_or_422(value: str | None, what: str) -> Decimal | None:
    if value is None or value.strip() == "":
        return None
    try:
        got = Decimal(value)
    except (ArithmeticError, ValueError):
        raise HTTPException(status_code=422, detail=f"{what} isn't a number.") from None
    if got < 0:
        raise HTTPException(status_code=422, detail=f"{what} can't be negative.")
    return got


@router.get("/api/desktop/ai")
def settings(request: Request, _: Principal = Depends(_owner)) -> AiOut:
    with request_session_factory(request)() as session:
        got = config.read(session)
        return AiOut(
            provider=got.provider, model=got.model, base_url=got.base_url,
            cap=str(got.cap), max_calls=got.max_calls,
            price_in=(None if got.prices.per_million_input is None
                      else str(got.prices.per_million_input)),
            price_out=(None if got.prices.per_million_output is None
                       else str(got.prices.per_million_output)),
            key_saved=config.read_key(_store(request), _paths(request).sealed_keys_file)
            is not None,
            local=got.prices.local,
            spend=_spend_out(
                spend.this_month(session, cap=got.cap, max_calls=got.max_calls)
            ),
            providers=_providers(),
        )


@router.put("/api/desktop/ai")
def save(body: AiIn, request: Request, _: Principal = Depends(_owner)) -> AiOut:
    if body.provider not in config.PROVIDERS:
        raise HTTPException(status_code=422, detail="That isn't a helper we can talk to.")
    if body.provider == "openai_compatible" and not (body.base_url or "").strip():
        raise HTTPException(
            status_code=422,
            detail="That helper needs the web address its service answers on.",
        )
    cap = _decimal_or_422(body.cap, "The monthly limit")
    if cap is None or cap <= 0:
        raise HTTPException(status_code=422, detail="The monthly limit has to be more than 0.")

    with request_session_factory(request)() as session:
        base_url = (body.base_url or "").strip() or None
        config.write(session, config.AiSettings(
            provider=body.provider, model=body.model.strip(), base_url=base_url,
            cap=cap, max_calls=body.max_calls,
            prices=Prices(
                per_million_input=_decimal_or_422(body.price_in, "The cost per million words in"),
                per_million_output=_decimal_or_422(
                    body.price_out, "The cost per million words out"
                ),
                local=config.is_local(base_url),
            ),
        ))
        # The key goes to the keychain, never through the session. Written
        # last so a refused settings write leaves no orphaned key.
        if body.key is not None and body.key.strip():
            try:
                config.write_key(
                    _store(request), _paths(request).sealed_keys_file, body.key.strip()
                )
            except RuntimeError as exc:
                raise HTTPException(status_code=503, detail=str(exc)) from None
        session.commit()
    return settings(request)


@router.delete("/api/desktop/ai/key", status_code=204)
def forget_key(request: Request, _: Principal = Depends(_owner)) -> None:
    config.clear_key(_store(request), _paths(request).sealed_keys_file)


def _question(
    session: object, body: SuggestIn, choices: tuple[LineChoice, ...]
) -> CodeQuestion:
    """Everything the model may see about this code, and nothing else.

    Read from the staging rows only — the report as printed. No fact, no
    journal line, no employee, no labour figure is in reach of this query,
    which is how ADR-006's outbound clause is satisfied by construction.
    """
    summary = session.execute(  # type: ignore[attr-defined]
        select(
            func.max(PmsDailyFinancialStage.pms_trx_desc),
            func.count(),
            func.coalesce(func.sum(PmsDailyFinancialStage.raw_amount), Decimal("0")),
            func.min(PmsDailyFinancialStage.business_date),
            func.max(PmsDailyFinancialStage.business_date),
        ).where(
            PmsDailyFinancialStage.property_id == body.property_id,
            PmsDailyFinancialStage.pms_source == body.pms_source,
            PmsDailyFinancialStage.pms_trx_code == body.code,
        )
    ).one()
    if summary[1] == 0:
        raise HTTPException(
            status_code=404,
            detail=f"{body.code} hasn't appeared on any of this hotel's reports.",
        )
    samples = session.scalars(  # type: ignore[attr-defined]
        select(PmsDailyFinancialStage.raw_amount)
        .where(
            PmsDailyFinancialStage.property_id == body.property_id,
            PmsDailyFinancialStage.pms_source == body.pms_source,
            PmsDailyFinancialStage.pms_trx_code == body.code,
        )
        .order_by(PmsDailyFinancialStage.business_date.desc())
        .limit(SAMPLE_AMOUNTS)
    ).all()
    return CodeQuestion(
        pms_source=body.pms_source, code=body.code, description=summary[0],
        times_seen=int(summary[1]), total_amount=Decimal(summary[2]),
        first_seen=summary[3], last_seen=summary[4],
        sample_amounts=tuple(Decimal(a) for a in samples), choices=choices,
    )


@router.post("/api/desktop/ai/suggest")
def suggest(
    body: SuggestIn, request: Request, principal: Principal = Depends(_owner)
) -> SuggestOut:
    """Ask where one charge code belongs. Writes nothing to the books."""
    with request_session_factory(request)() as session:
        require_property(session, body.property_id)
        # Asked BEFORE any of the work below: "you haven't set this up" is
        # something the owner can act on, and it should not be hidden behind
        # a 404 about a code they were only asking about.
        if not config.read(session).ready:
            raise HTTPException(
                status_code=409,
                detail="No AI helper is set up yet. Choose one in AI settings first.",
            )
        # The model is offered the LINE only — never the GL account number,
        # which is both useless to it and a category the allow-list forbids.
        offered: list[LineChoice] = []
        full: list[Line] = []
        seen: set[tuple[str, str, str]] = set()
        for line in known_lines(session, body.edition):
            key = (line.major, line.sub, line.line_item)
            if key in seen:
                continue
            seen.add(key)
            offered.append(LineChoice(*key))
            full.append(line)
        if not offered:
            raise HTTPException(
                status_code=409, detail="There are no lines to choose from yet."
            )

        question = _question(session, body, tuple(offered))
        try:
            got = client.suggest_line_for_code(
                session, store=_store(request), sealed=_paths(request).sealed_keys_file,
                question=question, property_id=body.property_id,
                actor_subject=principal.subject,
            )
        except NotConfigured as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from None
        except SpendCapReached as exc:
            raise HTTPException(status_code=429, detail=str(exc)) from None
        except AiError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from None

        chosen: Line | None = None
        if got.line is not None:
            picked = (got.line.major, got.line.sub, got.line.line_item)
            chosen = next(
                f for f in full if (f.major, f.sub, f.line_item) == picked
            )
        settings_now = config.read(session)
        out = SuggestOut(
            code=got.code, line=chosen, confidence=got.confidence, reason=got.reason,
            decline_reason=got.decline_reason,
            estimated_cost=None if got.estimated_cost is None else str(got.estimated_cost),
            model=got.model,
            spend=_spend_out(spend.this_month(
                session, cap=settings_now.cap, max_calls=settings_now.max_calls
            )),
        )
        session.commit()
        return out


def install(app: FastAPI, *, paths: DesktopPaths, store: KeyStore) -> None:
    app.state.desktop_ai_paths = paths
    app.state.desktop_ai_store = store
    app.include_router(router)
