"""Codes to confirm: what this hotel's transaction codes mean, and what
happens to the money while nobody has said.

    GET /api/desktop/codes?property=RTI   every code this hotel's reports use
    GET /api/desktop/codes/choices        the USALI lines a code may be put on
    PUT /api/desktop/codes/{code}         confirm one, and restate its days

Why this page exists. A code the shipped dictionary has never heard of is not
dropped and does not quarantine the report: `transform` banks it as a
`MappingException` and carries on, so no fact is created and the journal
never sees that money. The entry still balances, because `build_pms_daily_plan`
sweeps the difference into `guest_ledger_clearing` — and `_journal_nets`
excludes that account by design, so `sos_journal_parity` reports parity over
a profit and loss that is missing revenue. Nothing else in the product will
ever mention it: the intake log prints `unmapped=0` on a re-run, and the
individual exception rows, with their amounts, are shown nowhere.

A code the dictionary DOES have can be just as wrong. `transform` reads
neither `review_status` nor `confidence`, so a row shipped LOW /
needs-review posts exactly like a confirmed one — and every choiceADVANTAGE
row ships that way, because those codes are franchise-configurable.

Confirming a code writes a `desktop.mapping_decision` (mapping_decisions),
then RESTATES it: the facts and exceptions that came from that code at that
hotel are deleted, its days are transformed again, and the ledger is posted
again — upstream's own correction path, a reversal plus a fresh entry, never
an edit. Days inside a closed period are refused by name rather than
restated behind the owner's back.
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select, update

from usali import fiscal, gl_posting
from usali.auth import (
    ORG_ADMIN,
    Principal,
    request_session_factory,
    require_active_org,
    require_grants,
    require_operator,
)
from usali.desktop.mapping_decisions import decisions_for, record
from usali.models import (
    AuditEvent,
    MappingException,
    PmsDailyFinancialStage,
    Property,
    UsaliFinancialFact,
    UsaliMappingDictionary,
)
from usali.transform import Classification, transform

#: `ingestion.process_file`'s own default (ingestion.py:254). One edition is
#: in play on a desktop install; the parameter exists so this never guesses.
DEFAULT_EDITION = 12

_owner = require_grants(ORG_ADMIN)
router = APIRouter(dependencies=[Depends(require_operator), Depends(require_active_org)])


class Line(BaseModel):
    """One USALI line a code can be put on."""

    # Null is meaningful, not missing: it is what puts a code in taxes,
    # settlements or non-operating rather than in a revenue schedule.
    schedule_id: int | None
    major: str
    sub: str
    line_item: str
    gl_account_code: str | None

    def classification(self) -> Classification:
        return Classification(
            usali_schedule_id=self.schedule_id,
            usali_major_category=self.major,
            usali_sub_category=self.sub,
            usali_line_item=self.line_item,
            gl_account_code=self.gl_account_code,
        )

    @classmethod
    def of(cls, c: Classification) -> "Line":
        return cls(
            schedule_id=c.usali_schedule_id,
            major=c.usali_major_category,
            sub=c.usali_sub_category,
            line_item=c.usali_line_item,
            gl_account_code=c.gl_account_code,
        )


class CodeItem(BaseModel):
    code: str
    description: str | None
    pms_source: str
    #: unknown — nothing decides it, so its money is not in the books.
    #: unconfirmed — the shipped dictionary guesses, nobody has agreed.
    #: confirmed — somebody here said what it means.
    status: Literal["unknown", "unconfirmed", "confirmed"]
    times_seen: int
    amount: str
    first_seen: date
    last_seen: date
    #: What decides this code today; None when nothing does.
    current: Line | None
    decided_by: str | None
    decided_at: datetime | None


class CodesOut(BaseModel):
    property_id: str
    edition: int
    #: What the unknown codes add up to, counting every charge and every
    #: payment as money — NOT their net. A night audit nets to zero by
    #: construction, so summing signed amounts would report "$0.00 missing"
    #: for a hotel where nothing at all is classified, which is the case this
    #: page exists for.
    money_not_in_the_books: str
    #: Codes the shipped dictionary already had confirmed. Nothing to do.
    settled_count: int
    items: list[CodeItem]


class ChoicesOut(BaseModel):
    lines: list[Line]


class ConfirmIn(BaseModel):
    property_id: str = Field(min_length=1, max_length=50)
    pms_source: str = Field(min_length=1, max_length=20)
    line: Line
    note: str | None = Field(default=None, max_length=500)
    #: 'owner' chose it; 'ai-accepted' means they accepted a suggestion.
    origin: Literal["owner", "ai-accepted"] = "owner"
    edition: int = DEFAULT_EDITION


class ConfirmOut(BaseModel):
    code: str
    days_restated: list[date]
    facts_written: int
    #: Days whose ledger would not take the restatement, and why.
    ledger_refused: dict[str, str]


def known_lines(session: object, edition: int) -> list[Line]:
    """The classifications this product already knows about.

    A code may be moved to any of these and to nothing else. Free text would
    let one schedule's facts span two sub-categories, which
    `summary_operating_statement_from_journal` refuses outright — the owner
    would find out when the profit and loss stopped building.
    """
    rows = session.execute(  # type: ignore[attr-defined]
        select(
            UsaliMappingDictionary.usali_schedule_id,
            UsaliMappingDictionary.usali_major_category,
            UsaliMappingDictionary.usali_sub_category,
            UsaliMappingDictionary.usali_line_item,
            UsaliMappingDictionary.gl_account_code,
        )
        .where(UsaliMappingDictionary.usali_edition == edition)
        .distinct()
        .order_by(
            UsaliMappingDictionary.usali_major_category,
            UsaliMappingDictionary.usali_sub_category,
            UsaliMappingDictionary.usali_line_item,
        )
    ).all()
    return [
        Line(schedule_id=r[0], major=r[1], sub=r[2], line_item=r[3], gl_account_code=r[4])
        for r in rows
    ]


def require_property(session: object, property_id: str) -> None:
    found = session.scalar(  # type: ignore[attr-defined]
        select(Property.property_id).where(Property.property_id == property_id)
    )
    if found is None:
        raise HTTPException(status_code=404, detail=f"No hotel called {property_id}.")


@router.get("/api/desktop/codes")
def codes(
    request: Request,
    property_id: str = Query(alias="property"),
    edition: int = Query(default=DEFAULT_EDITION),
    _: Principal = Depends(_owner),
) -> CodesOut:
    """Every transaction code this hotel's reports have used, and who — if
    anyone — has said what it means."""
    with request_session_factory(request)() as session:
        require_property(session, property_id)

        seen = session.execute(
            select(
                PmsDailyFinancialStage.pms_source,
                PmsDailyFinancialStage.pms_trx_code,
                func.max(PmsDailyFinancialStage.pms_trx_desc),
                func.count(),
                func.coalesce(func.sum(PmsDailyFinancialStage.raw_amount), Decimal("0")),
                func.min(PmsDailyFinancialStage.business_date),
                func.max(PmsDailyFinancialStage.business_date),
            )
            .where(PmsDailyFinancialStage.property_id == property_id)
            .group_by(PmsDailyFinancialStage.pms_source, PmsDailyFinancialStage.pms_trx_code)
        ).all()

        shipped = {
            (m.pms_source, m.pms_trx_code): m
            for m in session.execute(
                select(UsaliMappingDictionary).where(
                    UsaliMappingDictionary.usali_edition == edition
                )
            ).scalars()
        }
        decided = {
            (d.pms_source, d.pms_trx_code): d
            for d in decisions_for(session, property_id=property_id)
            if d.usali_edition == edition
        }

        items: list[CodeItem] = []
        settled = 0
        not_in_books = Decimal("0")
        for source, code, desc, times, amount, first, last in seen:
            decision = decided.get((source, code))
            row = shipped.get((source, code))
            if decision is not None:
                status: Literal["unknown", "unconfirmed", "confirmed"] = "confirmed"
                current = Line.of(decision.classification)
            elif row is None:
                status = "unknown"
                current = None
                not_in_books += abs(Decimal(amount))
            elif row.review_status != "reviewed" or row.confidence == "LOW":
                status = "unconfirmed"
                current = Line(
                    schedule_id=row.usali_schedule_id, major=row.usali_major_category,
                    sub=row.usali_sub_category, line_item=row.usali_line_item,
                    gl_account_code=row.gl_account_code,
                )
            else:
                settled += 1
                continue
            items.append(CodeItem(
                code=code, description=desc, pms_source=source, status=status,
                times_seen=times, amount=str(Decimal(amount)),
                first_seen=first, last_seen=last, current=current,
                decided_by=decision.decided_by if decision else None,
                decided_at=decision.decided_at if decision else None,
            ))

        order = {"unknown": 0, "unconfirmed": 1, "confirmed": 2}
        items.sort(key=lambda i: (order[i.status], -abs(Decimal(i.amount)), i.code))
        return CodesOut(
            property_id=property_id, edition=edition,
            money_not_in_the_books=str(not_in_books), settled_count=settled, items=items,
        )


@router.get("/api/desktop/codes/choices")
def choices(
    request: Request,
    edition: int = Query(default=DEFAULT_EDITION),
    _: Principal = Depends(_owner),
) -> ChoicesOut:
    with request_session_factory(request)() as session:
        return ChoicesOut(lines=known_lines(session, edition))


@router.put("/api/desktop/codes/{code}")
def confirm(
    code: str, body: ConfirmIn, request: Request, principal: Principal = Depends(_owner)
) -> ConfirmOut:
    """Say what a code means here, and restate every day it appears on."""
    with request_session_factory(request)() as session:
        require_property(session, body.property_id)
        if body.line not in known_lines(session, body.edition):
            raise HTTPException(
                status_code=422,
                detail="That isn't a line this product knows about. Pick one from the list.",
            )

        stage_ids = list(session.scalars(
            select(PmsDailyFinancialStage.stage_id).where(
                PmsDailyFinancialStage.property_id == body.property_id,
                PmsDailyFinancialStage.pms_source == body.pms_source,
                PmsDailyFinancialStage.pms_trx_code == code,
            )
        ))
        days = sorted(set(session.scalars(
            select(PmsDailyFinancialStage.business_date).where(
                PmsDailyFinancialStage.stage_id.in_(stage_ids)
            )
        ))) if stage_ids else []

        # Refuse BEFORE writing anything: a restatement the ledger cannot
        # take would leave the facts changed and the journal stale, which is
        # the one state nothing in the product detects.
        closed = [d for d in days if _is_closed(session, body.property_id, d)]
        if closed:
            raise HTTPException(
                status_code=409,
                detail="These days are in a closed month, so they can't be restated: "
                       + ", ".join(d.isoformat() for d in closed)
                       + ". Reopen the month first.",
            )

        record(
            session, property_id=body.property_id, pms_source=body.pms_source,
            trx_code=code, edition=body.edition, classification=body.line.classification(),
            origin=body.origin, decided_by=principal.subject, note=body.note,
        )

        before = _fact_count(session, stage_ids)
        if stage_ids:
            # A fact that has been posted is referenced by its journal lines
            # (fk_journal_line_fact) and cannot be deleted — nor should it be:
            # the line is how a posted amount traces back to the report. So a
            # fact that exists is RE-CLASSIFIED in place; its id, amount and
            # provenance stay, and the ledger sees a changed day and reposts
            # (a reversal plus a fresh entry). Only rows that never became a
            # fact — the unmapped ones, held as exceptions — are transformed
            # afresh, once their exception row (what marks a stage row
            # "already processed") is gone.
            c = body.line.classification()
            session.execute(
                update(UsaliFinancialFact)
                .where(UsaliFinancialFact.stage_id.in_(stage_ids))
                .values(
                    usali_schedule_id=c.usali_schedule_id,
                    usali_major_category=c.usali_major_category,
                    usali_sub_category=c.usali_sub_category,
                    usali_line_item=c.usali_line_item,
                    gl_account_code=c.gl_account_code,
                )
            )
            session.execute(
                delete(MappingException).where(MappingException.stage_id.in_(stage_ids))
            )
            session.flush()

        refused: dict[str, str] = {}
        for day in days:
            transform(session, source=body.pms_source, business_date=day, edition=body.edition)
            outcome = gl_posting.post_and_record(
                session, property_id=body.property_id, business_date=day,
                source_type="pms_daily", actor=principal.subject,
            )
            if outcome.status == "failed" and outcome.message:
                refused[day.isoformat()] = outcome.message

        session.add(AuditEvent(
            actor_subject=principal.subject, action=f"mapping_decision_{body.origin}",
            resource_type="pms_trx_code", resource_id=f"{body.property_id}:{code}"[:64],
        ))
        written = _fact_count(session, stage_ids) - before
        session.commit()
        return ConfirmOut(
            code=code, days_restated=days, facts_written=written, ledger_refused=refused,
        )


def _fact_count(session: object, stage_ids: list[int]) -> int:
    if not stage_ids:
        return 0
    return int(session.scalar(  # type: ignore[attr-defined]
        select(func.count()).select_from(UsaliFinancialFact).where(
            UsaliFinancialFact.stage_id.in_(stage_ids)
        )
    ) or 0)


def _is_closed(session: object, property_id: str, day: date) -> bool:
    """A day in a closed month. A hotel with no fiscal calendar has no
    months to close, and its ledger is off anyway."""
    try:
        key = gl_posting.period_key_for(session, property_id, day)  # type: ignore[arg-type]
    except fiscal.FiscalCalendarNotConfigured:
        return False
    return gl_posting.period_state(session, property_id, key) == "closed"  # type: ignore[arg-type]


def install(app: FastAPI) -> None:
    app.include_router(router)
