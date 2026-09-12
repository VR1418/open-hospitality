"""Transform staged PMS rows into USALI facts, with mapping exceptions and reconciliation."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Protocol

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from usali.models import (
    MappingException,
    PmsDailyFinancialStage,
    UsaliFinancialFact,
    UsaliMappingDictionary,
)


class ReconciliationError(RuntimeError):
    pass


#: Session key a caller may bind a :class:`MappingResolver` under (desktop
#: edition). `transform` is reached through eight ingestion handlers and four
#: entry points — folder watch, /ingest, the night-audit upload, the CLI — so a
#: SESSION-scoped policy, the shape tenancy already binds with, reaches every
#: one of them without threading an argument through all eight handlers. Leave
#: it unbound and nothing changes: the shipped dictionary decides, as before.
RESOLVER_KEY = "usali_mapping_resolver"


@dataclass(frozen=True)
class Classification:
    """What a transaction code means: the five fields a fact copies from
    whatever decided it. One shape, so the fact-building code below does not
    care whether the dictionary or a resolver answered."""

    usali_schedule_id: int | None
    usali_major_category: str
    usali_sub_category: str
    usali_line_item: str
    gl_account_code: str | None


class MappingResolver(Protocol):
    """Consulted BEFORE the shipped dictionary, and free to decline by
    returning None.

    The dictionary's rows are keyed (pms_source, pms_trx_code, usali_edition)
    with no property, so it cannot hold a per-hotel answer — and the one PMS
    whose codes are documented as franchise-configurable (choiceADVANTAGE,
    see mapping/skytouch.yaml) is the one that most needs one. The desktop
    edition binds a resolver holding each hotel's own confirmed meanings.
    """

    def __call__(
        self, *, property_id: str, pms_source: str, trx_code: str, edition: int
    ) -> Classification | None: ...


def _from_dictionary(d: UsaliMappingDictionary) -> Classification:
    return Classification(
        usali_schedule_id=d.usali_schedule_id,
        usali_major_category=d.usali_major_category,
        usali_sub_category=d.usali_sub_category,
        usali_line_item=d.usali_line_item,
        gl_account_code=d.gl_account_code,
    )


@dataclass
class TransformResult:
    mapped: int
    unmapped: int
    skipped: int
    reconciled: bool


def transform(
    session: Session, *, source: str, business_date: date, edition: int
) -> TransformResult:
    """Map staged rows for (source, business_date) to USALI facts using the edition's dictionary.

    A resolver bound under `RESOLVER_KEY` on the session is asked first and may
    decline; the dictionary answers whatever it leaves. Unmapped rows are
    recorded as MappingException rows (nothing is silently dropped).
    Reruns are idempotent: stage rows whose stage_id already has a persisted fact or
    exception are skipped rather than re-inserted. Reconciliation verifies persisted
    totals (facts + exceptions, across all runs) still equal the full staged total.
    """
    stage_rows = (
        session.execute(
            select(PmsDailyFinancialStage).where(
                PmsDailyFinancialStage.pms_source == source,
                PmsDailyFinancialStage.business_date == business_date,
            )
        )
        .scalars()
        .all()
    )

    mappings = {
        m.pms_trx_code: m
        for m in session.execute(
            select(UsaliMappingDictionary).where(
                UsaliMappingDictionary.pms_source == source,
                UsaliMappingDictionary.usali_edition == edition,
            )
        ).scalars()
    }

    # A stage row is "processed" if a prior run produced either a fact or an
    # exception for it — hence the union across both output tables.
    processed_stage_ids: set[int] = set(
        session.execute(
            select(UsaliFinancialFact.stage_id).where(
                UsaliFinancialFact.pms_source == source,
                UsaliFinancialFact.business_date == business_date,
            )
        ).scalars()
    ) | set(
        session.execute(
            select(MappingException.stage_id).where(
                MappingException.pms_source == source,
                MappingException.business_date == business_date,
            )
        ).scalars()
    )

    resolver: MappingResolver | None = session.info.get(RESOLVER_KEY)

    mapped = unmapped = skipped = 0
    stage_total = Decimal("0")

    for row in stage_rows:
        stage_total += Decimal(row.raw_amount)
        if row.stage_id in processed_stage_ids:
            skipped += 1
            continue
        m = (
            resolver(
                property_id=row.property_id,
                pms_source=source,
                trx_code=row.pms_trx_code,
                edition=edition,
            )
            if resolver is not None
            else None
        )
        if m is None:
            d = mappings.get(row.pms_trx_code)
            m = _from_dictionary(d) if d is not None else None
        if m is None:
            session.add(
                MappingException(
                    pms_source=source,
                    pms_trx_code=row.pms_trx_code,
                    pms_trx_desc=row.pms_trx_desc,
                    raw_amount=row.raw_amount,
                    business_date=business_date,
                    ingest_batch_id=row.ingest_batch_id,
                    stage_id=row.stage_id,
                )
            )
            unmapped += 1
            continue
        session.add(
            UsaliFinancialFact(
                property_id=row.property_id,
                pms_source=source,
                business_date=business_date,
                usali_edition=edition,
                usali_schedule_id=m.usali_schedule_id,
                usali_major_category=m.usali_major_category,
                usali_sub_category=m.usali_sub_category,
                usali_line_item=m.usali_line_item,
                amount=row.raw_amount,
                room_count=row.room_count,
                gl_account_code=m.gl_account_code,
                ingest_batch_id=row.ingest_batch_id,
                stage_id=row.stage_id,
            )
        )
        mapped += 1

    # Flush so the facts/exceptions just added are visible to the aggregate queries below.
    session.flush()

    fact_total_raw = session.scalar(
        select(func.coalesce(func.sum(UsaliFinancialFact.amount), Decimal("0"))).where(
            UsaliFinancialFact.pms_source == source,
            UsaliFinancialFact.business_date == business_date,
        )
    )
    assert fact_total_raw is not None
    fact_total = Decimal(fact_total_raw)

    exc_total_raw = session.scalar(
        select(func.coalesce(func.sum(MappingException.raw_amount), Decimal("0"))).where(
            MappingException.pms_source == source,
            MappingException.business_date == business_date,
        )
    )
    assert exc_total_raw is not None
    exc_total = Decimal(exc_total_raw)

    # Exact Decimal equality is safe here: all amounts are fixed-precision Numeric(15,4)/Decimal
    # end-to-end (no floats enter this comparison), so there is no rounding drift to tolerate.
    # Do not switch this to a tolerance-based comparison.
    reconciled = stage_total == (fact_total + exc_total)
    if not reconciled:
        raise ReconciliationError(
            f"stage {stage_total} != fact {fact_total} + exceptions {exc_total}"
        )
    return TransformResult(mapped=mapped, unmapped=unmapped, skipped=skipped, reconciled=reconciled)
