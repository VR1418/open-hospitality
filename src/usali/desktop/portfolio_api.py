"""All hotels at a glance — the desktop Overview.

    GET /api/desktop/portfolio?date=YYYY-MM-DD

One call for the owner's home screen: every hotel the caller may see, for one
business day (by default the latest day any of them has reports for), with
totals across them. When Payroll & People is on it adds who is on the clock
now, staff, timecards waiting for approval, and labour cost against revenue
for the month so far.

Every figure comes from upstream's own functions. The day and the month are
`reporting.summary_operating_statement_from_journal` — the call the Profit
and loss page makes — so the Overview can never show a number the statement
doesn't. Upstream has no portfolio query; building one here keeps upstream's
files untouched (the fork's rule: changes at the edges).

Which hotels a caller sees is upstream's rule too (`workforce.resolve_scope`),
so a hotel manager's Overview holds their hotels and nobody else's.
"""

from collections.abc import Iterable
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, FastAPI, Query, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from usali import reporting
from usali.assignments import (
    AmbiguousPrimaryError,
    employee_ids_serving_property,
    primary_assignment_on,
)
from usali.auth import Principal, request_session_factory, require_active_org, require_operator
from usali.inventory import InventoryInconsistent, InventoryNotConfigured, rooms_available
from usali.models import Employee, KioskDevice, Property, Punch, Timecard
from usali.timecards import punch_states
from usali.workforce import resolve_scope

# How far back a clock-in can still mean "on the clock" — the same window
# `timecards.punch_state` uses, so both answers agree.
_OPEN_SHIFT = timedelta(hours=18)
_CENT = Decimal("0.01")
_TENTH = Decimal("0.1")

NO_REPORTS_YET = "No reports read yet."
MISSING_DAY = "No reports for this day yet."
NOT_IN_BOOKS = (
    "Reports are in but haven't reached the books. Check this hotel's financial year "
    "on Your hotels."
)


class StaffOut(BaseModel):
    staff: int
    on_clock: int
    timecards_to_approve: int


class HotelOut(BaseModel):
    property_id: str
    name: str
    pms_source: str
    status: Literal["in", "missing", "error"]
    note: str | None
    revenue: str | None
    occupancy_pct: str | None
    adr: str | None
    revpar: str | None
    rooms_occupied: str | None
    rooms_total: str | None
    month_revenue: str | None
    month_labour_cost: str | None
    staff: StaffOut | None


class TotalsOut(BaseModel):
    hotels: int
    hotels_in: int
    revenue: str | None
    occupancy_pct: str | None
    adr: str | None
    revpar: str | None
    month_revenue: str | None
    month_labour_cost: str | None
    month_labour_pct: str | None
    staff: StaffOut | None


class PortfolioOut(BaseModel):
    business_date: date | None
    month_start: date | None
    staff_shown: bool
    hotels: list[HotelOut]
    totals: TotalsOut


def _money(v: Decimal | None) -> str | None:
    return None if v is None else str(v.quantize(_CENT))


def _pct(v: Decimal | None) -> str | None:
    return None if v is None else str(v.quantize(_TENTH))


def _ratio(num: Decimal, den: Decimal) -> Decimal | None:
    return None if den == 0 else num / den


class _Day:
    """One hotel's figures for the day, kept as Decimals until the totals."""

    def __init__(self) -> None:
        self.status: Literal["in", "missing", "error"] = "missing"
        self.note: str | None = None
        self.revenue: Decimal | None = None
        self.occupancy: Decimal | None = None
        self.adr: Decimal | None = None
        self.revpar: Decimal | None = None
        self.rooms_occupied: Decimal | None = None
        self.rooms_total: Decimal | None = None
        self.room_revenue: Decimal | None = None
        self.month_revenue: Decimal | None = None
        self.month_labour: Decimal | None = None


def _day_for(session: Session, property_id: str, day: date | None, has_reports: bool) -> _Day:
    out = _Day()
    if day is None or not has_reports:
        out.note = NO_REPORTS_YET
        return out
    try:
        report = reporting.summary_operating_statement_from_journal(
            session, property_id=property_id, business_date=day,
        )
    except reporting.NoPostedEntriesError:
        out.status, out.note = "error", NOT_IN_BOOKS
        return out
    except reporting.NoFactsError:
        out.note = MISSING_DAY
        return out
    except ValueError as exc:
        out.status, out.note = "error", f"This day's statement couldn't be built: {exc}"
        return out

    stats = {m.metric_code: m.day for m in report.statistics}
    out.status = "in"
    out.revenue = report.total_operating_revenue
    out.occupancy = stats.get("OCCUPANCY_PCT")
    out.adr = stats.get("ADR")
    out.revpar = stats.get("REVPAR")
    out.rooms_occupied = stats.get("ROOMS_OCCUPIED")
    # TOTAL_ROOMS is the house size (the dashboard's denominator too). Not
    # every PMS prints it (AutoClerk's pack doesn't); then the rooms the
    # owner gave for this hotel stand in — upstream's own room inventory.
    out.rooms_total = stats.get("TOTAL_ROOMS")
    if out.rooms_total is None:
        try:
            out.rooms_total = Decimal(rooms_available(session, property_id, day, day))
        except (InventoryNotConfigured, InventoryInconsistent):
            pass
    out.room_revenue = stats.get("ROOM_REVENUE")
    if out.room_revenue is None and out.adr is not None and out.rooms_occupied is not None:
        out.room_revenue = out.adr * out.rooms_occupied  # ADR's own definition
    if out.occupancy is None and out.rooms_occupied is not None and out.rooms_total:
        out.occupancy = out.rooms_occupied * 100 / out.rooms_total

    try:
        month = reporting.summary_operating_statement_from_journal(
            session, property_id=property_id, date_from=day.replace(day=1), date_to=day,
        )
    except ValueError:
        return out  # the day stands on its own; the month simply isn't shown
    out.month_revenue = month.total_operating_revenue
    # Estimated, from approved timecards (Schedule 14) — the statement's own figure.
    out.month_labour = month.payroll_expense_total
    return out


def _staff(
    session: Session, property_ids: list[str], today: date, now: datetime,
) -> dict[str, StaffOut]:
    serving = {pid: employee_ids_serving_property(session, pid, today) for pid in property_ids}
    everyone: set[int] = set().union(*serving.values()) if serving else set()
    active = set(session.scalars(
        select(Employee.employee_id).where(
            Employee.employee_id.in_(everyone), Employee.employment_status == "active",
        )
    )) if everyone else set()

    # On the clock: counted at the hotel whose time clock they last used, so a
    # person who works at two hotels is on shift at one of them, not both.
    states = punch_states(session, sorted(everyone), now=now)
    clocked = [e for e, s in states.items() if s != "out"]
    where: dict[int, str] = {}
    if clocked:
        for employee_id, property_id in session.execute(
            select(Punch.employee_id, KioskDevice.property_id)
            .join(KioskDevice, KioskDevice.device_id == Punch.kiosk_device_id)
            .where(Punch.employee_id.in_(clocked), Punch.punched_at >= now - _OPEN_SHIFT)
            .order_by(Punch.punched_at.asc())
        ).all():
            where[employee_id] = property_id  # ascending: the last one wins

    # Waiting for approval: open cards whose pay period has ENDED — the
    # current fortnight's card is still filling up and waits on nobody. A card
    # belongs to the hotel that pays the person (their primary assignment).
    waiting: dict[str, int] = dict.fromkeys(property_ids, 0)
    for card in session.scalars(
        select(Timecard).where(Timecard.status == "open", Timecard.period_end < today)
    ):
        try:
            primary = primary_assignment_on(session, card.employee_id, card.period_end)
        except AmbiguousPrimaryError:
            continue
        if primary is not None and primary.property_id in waiting:
            waiting[primary.property_id] += 1

    return {
        pid: StaffOut(
            staff=len(serving[pid] & active),
            on_clock=sum(1 for e in clocked if where.get(e) == pid),
            timecards_to_approve=waiting[pid],
        )
        for pid in property_ids
    }


def _sum(values: Iterable[Decimal | None]) -> Decimal | None:
    present = [v for v in values if v is not None]
    return sum(present, Decimal(0)) if present else None


def _pooled(
    days: list[_Day], num: str, den: str, scale: int = 1,
) -> Decimal | None:
    """A portfolio ratio from summed parts, over ONLY the hotels that report
    both parts. Summing rooms sold across every hotel but rooms across only
    those that print them would overstate occupancy; a mean of percentages
    would weigh a 20-room inn like a 300-room hotel."""
    pairs = [
        (getattr(d, num), getattr(d, den)) for d in days
        if getattr(d, num) is not None and getattr(d, den) is not None
    ]
    if not pairs:
        return None
    return _ratio(sum((n for n, _ in pairs), Decimal(0)) * scale,
                  sum((m for _, m in pairs), Decimal(0)))


router = APIRouter(dependencies=[Depends(require_operator), Depends(require_active_org)])


@router.get("/api/desktop/portfolio")
def portfolio(
    request: Request,
    principal: Principal = Depends(require_operator),
    on: date | None = Query(default=None, alias="date"),
) -> PortfolioOut:
    now = datetime.now(UTC)
    staff_shown = "payroll" in getattr(request.app.state, "desktop_enabled_modules", frozenset())
    with request_session_factory(request)() as session:
        scope = resolve_scope(principal, session)
        hotels = [
            p for p in session.scalars(select(Property).order_by(Property.property_id))
            if scope.allows_property(p.property_id)
        ]
        visible = {p.property_id for p in hotels}
        # The latest day each hotel has reports for (a hotel on two PMS
        # sources has two rows; its latest is the later of them).
        latest: dict[str, date] = {}
        for info in reporting.list_properties(session):
            if info.property_id in visible:
                latest[info.property_id] = max(latest.get(info.property_id, info.last_date),
                                               info.last_date)
        day = on if on is not None else max(latest.values(), default=None)

        days = {p.property_id: _day_for(session, p.property_id, day, p.property_id in latest)
                for p in hotels}
        staff = _staff(session, sorted(visible), now.date(), now) if staff_shown else {}
        staff_total: StaffOut | None = None
        if staff_shown:
            everyone: set[int] = set()
            for pid in visible:
                everyone |= employee_ids_serving_property(session, pid, now.date())
            active_total = session.scalars(
                select(Employee.employee_id).where(
                    Employee.employee_id.in_(everyone), Employee.employment_status == "active",
                )
            ).all() if everyone else []
            staff_total = StaffOut(
                staff=len(active_total),
                on_clock=sum(s.on_clock for s in staff.values()),
                timecards_to_approve=sum(s.timecards_to_approve for s in staff.values()),
            )

    counted = [d for d in days.values() if d.status == "in"]
    month_rev = _sum(d.month_revenue for d in days.values())
    month_lab = _sum(d.month_labour for d in days.values())
    totals = TotalsOut(
        hotels=len(hotels),
        hotels_in=len(counted),
        revenue=_money(_sum(d.revenue for d in counted)),
        occupancy_pct=_pct(_pooled(counted, "rooms_occupied", "rooms_total", scale=100)),
        adr=_money(_pooled(counted, "room_revenue", "rooms_occupied")),
        revpar=_money(_pooled(counted, "room_revenue", "rooms_total")),
        month_revenue=_money(month_rev),
        month_labour_cost=_money(month_lab) if staff_shown else None,
        month_labour_pct=_pct(None if month_lab is None or month_rev is None
                              else _ratio(month_lab * 100, month_rev)) if staff_shown else None,
        staff=staff_total,
    )
    return PortfolioOut(
        business_date=day,
        month_start=day.replace(day=1) if day is not None else None,
        staff_shown=staff_shown,
        hotels=[
            HotelOut(
                property_id=p.property_id, name=p.name, pms_source=p.pms_source,
                status=days[p.property_id].status, note=days[p.property_id].note,
                revenue=_money(days[p.property_id].revenue),
                occupancy_pct=_pct(days[p.property_id].occupancy),
                adr=_money(days[p.property_id].adr),
                revpar=_money(days[p.property_id].revpar),
                rooms_occupied=_pct(days[p.property_id].rooms_occupied),
                rooms_total=_pct(days[p.property_id].rooms_total),
                month_revenue=_money(days[p.property_id].month_revenue),
                month_labour_cost=(_money(days[p.property_id].month_labour)
                                   if staff_shown else None),
                staff=staff.get(p.property_id),
            )
            for p in hotels
        ],
        totals=totals,
    )


def install(app: FastAPI) -> None:
    app.include_router(router)
