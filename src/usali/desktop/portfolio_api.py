"""All hotels at a glance — the desktop Overview.

    GET /api/desktop/portfolio?date=YYYY-MM-DD[&property=RTI22]
    PUT /api/desktop/hotels/{property_id}/targets   the owner's breakeven and last year

One call for the owner's home screen: every hotel the caller may see (or the
one asked for), for one business day (by default the latest day any of them
has reports for), with totals across them. When Payroll & People is on it
adds who is on the clock now, staff, timecards waiting for approval, and
labour cost against revenue for the month so far.

The multi-hotel owner's picture (docs/desktop/PLAN-multi-hotel.md): rooms
across the portfolio as well as money; and, per hotel, the owner's own
ANNUAL breakeven — divided by the days in the year and compared with last
night, the month and the year to date — with a projection for the year that
is shaped by last year's revenue where the report prints it (choiceADVANTAGE
carries last year's YTD beside this year's), by a figure the owner typed
otherwise, and by a plain run rate as the last resort. The card always says
which. None of this is a book entry: the targets are an install setting.

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

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, Request
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
from usali.auth import ORG_ADMIN, require_grants
from usali.desktop.settings import read_setting, write_setting
from usali.inventory import InventoryInconsistent, InventoryNotConfigured, rooms_available
from usali.models import (
    Employee,
    KioskDevice,
    MappingException,
    PmsDailyFinancialStage,
    Property,
    Punch,
    Timecard,
    UsaliStatisticFact,
)
from usali.night_audit import ledger_checks, slot_status
from usali.timecards import punch_states
from usali.workforce import resolve_scope

#: Where each hotel's owner-typed figures live — the same setting the wizard
#: keeps the ownership entity in (welcome_api.PROFILES_KEY), so a hotel has
#: one profile: entity, breakeven, last year's revenue.
PROFILES_KEY = "hotel_profiles"
#: A night whose occupancy is this many points under the hotel's own last
#: seven is worth a look.
OCCUPANCY_DROP_POINTS = Decimal(15)
#: How many of last year's days the books must hold before the app trusts its
#: own figure for last year's total (a year with a gap is not a year).
_FULL_YEAR_DAYS = 360

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


class TargetsOut(BaseModel):
    """The owner's own figures for a hotel. Both optional, both theirs to change."""
    #: Total revenue the hotel needs in a year to cover its costs.
    breakeven_annual: str | None
    #: Last year's total revenue, typed until a report or the books supply it.
    last_year_revenue: str | None
    changed_at: str | None


class OutlookOut(BaseModel):
    """Where the hotel stands against its breakeven, and where the year is heading."""
    breakeven_per_day: str
    #: The first night this year the books have for the hotel — Jan 1 when
    #: they go back that far. The year-to-date comparison starts here, so a
    #: hotel whose books began in August is not judged on January.
    since: date
    #: Nights from `since` to the day shown, inclusive.
    days_elapsed: int
    days_in_year: int
    #: Last night's revenue minus the daily breakeven; None when no report.
    night_gap: str | None
    #: Year-to-date revenue, and what it should be by today (per day × days elapsed).
    year_revenue: str | None
    expected_year_to_date: str
    year_gap: str | None
    #: The year's projected total, and what shaped it.
    projected_year: str | None
    projection_basis: Literal["last_year", "run_rate"] | None
    #: Last year's total and where it came from; growth = this YTD ÷ last YTD.
    last_year_total: str | None
    last_year_source: Literal["owner", "books"] | None
    growth: str | None


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
    #: Room-nights sold and available so far this month.
    rooms_sold_month: str | None
    rooms_available_month: str | None
    month_revenue: str | None
    month_labour_cost: str | None
    month_labour_pct: str | None
    year_revenue: str | None
    staff: StaffOut | None
    targets: TargetsOut
    #: None until the owner has typed an annual breakeven.
    outlook: OutlookOut | None


class BreakevenSummary(BaseModel):
    above: int
    behind: int
    unset: int
    #: Sum of the year gaps over the hotels with a breakeven.
    year_gap: str | None


class TotalsOut(BaseModel):
    hotels: int
    hotels_in: int
    revenue: str | None
    occupancy_pct: str | None
    adr: str | None
    revpar: str | None
    rooms_total: str | None
    rooms_sold: str | None
    rooms_sold_month: str | None
    rooms_available_month: str | None
    month_revenue: str | None
    month_labour_cost: str | None
    month_labour_pct: str | None
    year_revenue: str | None
    breakeven: BreakevenSummary
    staff: StaffOut | None


class TrendPoint(BaseModel):
    business_date: date
    # Total across the hotels, from the reports read; null on a day none of
    # them reported, so the chart can leave a gap rather than draw a zero.
    revenue: str | None


class FindingOut(BaseModel):
    property_id: str
    hotel: str
    kind: Literal[
        "behind_breakeven", "occupancy_drop",
        "no_reports", "missing_report", "check_failed", "not_in_books", "codes_to_confirm"
    ]
    label: str
    detail: str
    delta: str | None


class PortfolioOut(BaseModel):
    business_date: date | None
    month_start: date | None
    staff_shown: bool
    hotels: list[HotelOut]
    totals: TotalsOut
    # The last 14 days ending on `business_date`, oldest first.
    trend: list[TrendPoint]
    # What the night's audit turned up, across the hotels.
    findings: list[FindingOut]


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
        self.rooms_sold_month: Decimal | None = None
        self.rooms_available_month: Decimal | None = None
        self.year_revenue: Decimal | None = None
        #: This year's and last year's revenue to date as the REPORT prints
        #: them (choiceADVANTAGE's YTD and Last YTD), for the growth ratio.
        self.ytd_printed: Decimal | None = None
        self.ytd_prior_printed: Decimal | None = None


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
    for m in report.statistics:
        if m.metric_code == "ROOM_REVENUE":
            out.ytd_printed, out.ytd_prior_printed = m.ytd, m.ytd_prior
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
    sold = _rooms_sold(session, property_id, day.replace(day=1), day)
    out.rooms_sold_month = sold if sold else None
    if out.rooms_total is not None:
        out.rooms_available_month = out.rooms_total * day.day
    try:
        year = reporting.summary_operating_statement_from_journal(
            session, property_id=property_id, date_from=day.replace(month=1, day=1), date_to=day,
        )
        out.year_revenue = year.total_operating_revenue
    except ValueError:
        pass
    return out


def _rooms_sold(session: Session, property_id: str, start: date, end: date) -> Decimal:
    """Room-nights sold over the window, from the promoted nightly statistic."""
    rows = session.execute(
        select(UsaliStatisticFact.business_date, UsaliStatisticFact.value).where(
            UsaliStatisticFact.property_id == property_id,
            UsaliStatisticFact.business_date >= start,
            UsaliStatisticFact.business_date <= end,
            UsaliStatisticFact.metric_code == "ROOMS_OCCUPIED",
            UsaliStatisticFact.period == "DAY",
            UsaliStatisticFact.is_prior_year.is_(False),
        )
    ).all()
    by_day = {d: Decimal(str(v)) for d, v in rows}  # last write wins, as the statement pivots
    return sum(by_day.values(), Decimal(0))


# --- The owner's targets, and the outlook they make ---------------------------

def _profiles(session: Session) -> dict[str, dict[str, object]]:
    raw = read_setting(session, PROFILES_KEY)
    return raw if isinstance(raw, dict) else {}


def _targets(profile: dict[str, object]) -> TargetsOut:
    def money(key: str) -> str | None:
        value = profile.get(key)
        return None if value is None else str(Decimal(str(value)).quantize(_CENT))
    changed = profile.get("targets_changed_at")
    return TargetsOut(breakeven_annual=money("breakeven_annual"),
                      last_year_revenue=money("last_year_revenue"),
                      changed_at=str(changed) if changed else None)


def _days_in_year(year: int) -> int:
    return 366 if (year % 4 == 0 and year % 100 != 0) or year % 400 == 0 else 365


def _last_year_from_books(session: Session, property_id: str, year: int) -> Decimal | None:
    """Last year's total revenue from the app's own books — only when they
    hold nearly every day of it. A year with a gap is not a year."""
    by_day = reporting.revenue_by_day(session, property_id, date(year, 1, 1), date(year, 12, 31))
    if len(by_day) < _FULL_YEAR_DAYS:
        return None
    return sum(by_day.values(), Decimal(0))


def _outlook(
    session: Session, property_id: str, entry: _Day, targets: TargetsOut, day: date,
    first_night: date | None,
) -> OutlookOut | None:
    if targets.breakeven_annual is None:
        return None
    days_in_year = _days_in_year(day.year)
    since = max(date(day.year, 1, 1), first_night or date(day.year, 1, 1))
    elapsed = (day - since).days + 1
    per_day = Decimal(targets.breakeven_annual) / days_in_year
    expected = per_day * elapsed

    last_year_total: Decimal | None = None
    source: Literal["owner", "books"] | None = None
    if targets.last_year_revenue is not None:
        last_year_total, source = Decimal(targets.last_year_revenue), "owner"
    else:
        from_books = _last_year_from_books(session, property_id, day.year - 1)
        if from_books is not None:
            last_year_total, source = from_books, "books"

    growth: Decimal | None = None
    if entry.ytd_printed and entry.ytd_prior_printed:
        growth = entry.ytd_printed / entry.ytd_prior_printed

    projected: Decimal | None = None
    basis: Literal["last_year", "run_rate"] | None = None
    if entry.year_revenue is not None:
        if last_year_total is not None and growth is not None:
            projected, basis = last_year_total * growth, "last_year"
        elif elapsed > 0:
            projected, basis = entry.year_revenue / elapsed * days_in_year, "run_rate"

    return OutlookOut(
        breakeven_per_day=_money(per_day) or "0.00", since=since, days_elapsed=elapsed,
        days_in_year=days_in_year,
        night_gap=_money(entry.revenue - per_day) if entry.revenue is not None else None,
        year_revenue=_money(entry.year_revenue), expected_year_to_date=_money(expected) or "0.00",
        year_gap=_money(entry.year_revenue - expected) if entry.year_revenue is not None else None,
        projected_year=_money(projected), projection_basis=basis,
        last_year_total=_money(last_year_total), last_year_source=source,
        growth=None if growth is None else str(growth.quantize(Decimal("0.001"))),
    )


class TargetsIn(BaseModel):
    breakeven_annual: Decimal | None = None
    last_year_revenue: Decimal | None = None


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


TREND_DAYS = 14


def _trend(session: Session, property_ids: list[str], day: date | None) -> list[TrendPoint]:
    """Revenue per day across the hotels, for the fortnight ending on `day`.

    `reporting.revenue_by_day` is FACT-derived — what the reports said —
    where a hotel's headline revenue above is the posted journal's. They
    agree once a day is posted, and the page says which is which. The
    statement is not rebuilt per day per hotel: that is 14 x N statements
    for a shape."""
    if day is None:
        return []
    start = day - timedelta(days=TREND_DAYS - 1)
    totals: dict[date, Decimal] = {}
    for property_id in property_ids:
        for on, amount in reporting.revenue_by_day(session, property_id, start, day).items():
            totals[on] = totals.get(on, Decimal(0)) + amount
    days = [start + timedelta(days=i) for i in range(TREND_DAYS)]
    return [TrendPoint(business_date=d, revenue=_money(totals.get(d))) for d in days]


def _unknown_codes(session: Session, property_id: str) -> tuple[int, Decimal]:
    """How many transaction codes this hotel uses that nothing can classify,
    and what they add up to.

    Standing, not nightly: the money accumulates until somebody says what the
    codes mean. Nothing else in the product mentions it — the journal balances
    by sweeping the difference into the clearing account, which
    `reporting._journal_nets` excludes, so `sos_journal_parity` reports parity
    over a profit and loss that is short.
    """
    rows = session.execute(
        select(MappingException.pms_trx_code, MappingException.raw_amount)
        .join(PmsDailyFinancialStage,
              PmsDailyFinancialStage.stage_id == MappingException.stage_id)
        .where(PmsDailyFinancialStage.property_id == property_id)
    ).all()
    codes = {r[0] for r in rows}
    # Absolute, not net: a night audit nets to zero by construction, so
    # summing signed amounts would report nothing missing for a hotel where
    # nothing at all is classified.
    return len(codes), sum((abs(Decimal(r[1])) for r in rows), Decimal("0"))


def _occupancy_drop(session: Session, property_id: str, entry: _Day, day: date) -> Decimal | None:
    """Points of occupancy last night fell under the hotel's own previous
    seven nights, when that is more than OCCUPANCY_DROP_POINTS; else None."""
    if entry.rooms_occupied is None or not entry.rooms_total:
        return None
    rows = session.execute(
        select(UsaliStatisticFact.business_date, UsaliStatisticFact.value).where(
            UsaliStatisticFact.property_id == property_id,
            UsaliStatisticFact.business_date >= day - timedelta(days=7),
            UsaliStatisticFact.business_date < day,
            UsaliStatisticFact.metric_code == "ROOMS_OCCUPIED",
            UsaliStatisticFact.period == "DAY",
            UsaliStatisticFact.is_prior_year.is_(False),
        )
    ).all()
    nights = {d: Decimal(str(v)) for d, v in rows}
    if len(nights) < 4:
        return None
    usual = sum(nights.values(), Decimal(0)) / len(nights) * 100 / entry.rooms_total
    tonight = entry.rooms_occupied * 100 / entry.rooms_total
    drop = usual - tonight
    return drop if drop > OCCUPANCY_DROP_POINTS else None


def _findings(
    session: Session, hotels: list[Property], days: dict[str, "_Day"], day: date | None,
    outlooks: dict[str, OutlookOut | None],
) -> list[FindingOut]:
    """What last night's audit turned up, in the owner's words: a hotel that
    sent nothing, a report still to come, a balance check that failed, or a
    day the books haven't taken. Read-only on purpose — upstream's
    `GET /night-audit` creates and commits a state row as a side effect of
    reading, which is right for one hotel's page and wrong for a home screen
    that touches every hotel."""
    out: list[FindingOut] = []
    # Before the day guard: this one is true whatever day is on screen.
    for prop in hotels:
        count, money = _unknown_codes(session, prop.property_id)
        if count:
            out.append(FindingOut(
                property_id=prop.property_id, hotel=prop.name, kind="codes_to_confirm",
                label="Codes to confirm",
                detail=f"{count} code{'' if count == 1 else 's'} on your reports "
                       f"{'is' if count == 1 else 'are'} holding ${money:,.2f} out of your "
                       f"books. Nothing here knows what they are.",
                delta=None,
            ))
    if day is None:
        return out
    for prop in hotels:
        entry = days[prop.property_id]
        common = {"property_id": prop.property_id, "hotel": prop.name}
        outlook = outlooks.get(prop.property_id)
        if outlook is not None and outlook.year_gap is not None and Decimal(outlook.year_gap) < 0:
            out.append(FindingOut(
                **common, kind="behind_breakeven", label="Behind breakeven",
                detail=f"${-Decimal(outlook.year_gap):,.0f} under where it should be since "
                       f"{outlook.since.day} {outlook.since:%b}, at "
                       f"${Decimal(outlook.breakeven_per_day):,.0f} a day.",
                delta=None,
            ))
        drop = _occupancy_drop(session, prop.property_id, entry, day)
        if drop is not None:
            out.append(FindingOut(
                **common, kind="occupancy_drop", label="Occupancy fell",
                detail=f"{drop:.0f} points under this hotel's last seven nights.", delta=None,
            ))
        if entry.status == "missing":
            out.append(FindingOut(**common, kind="no_reports", label="No reports yet",
                                  detail=entry.note or MISSING_DAY, delta=None))
            continue
        if entry.status == "error":
            out.append(FindingOut(**common, kind="not_in_books", label="Not in the books",
                                  detail=entry.note or NOT_IN_BOOKS, delta=None))
            continue
        for slot in slot_status(session, prop.property_id, day, prop.pms_source):
            if not slot["landed"]:
                out.append(FindingOut(
                    **common, kind="missing_report", label=str(slot["label"]),
                    detail="This report hasn't arrived for the day.", delta=None,
                ))
        for check in ledger_checks(session, prop.property_id, day, prop.pms_source):
            if check.status == "fail":
                out.append(FindingOut(**common, kind="check_failed", label=check.name,
                                      detail=check.detail, delta=check.delta))
    return out


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
    only: str | None = Query(default=None, alias="property"),
) -> PortfolioOut:
    now = datetime.now(UTC)
    staff_shown = "payroll" in getattr(request.app.state, "desktop_enabled_modules", frozenset())
    with request_session_factory(request)() as session:
        scope = resolve_scope(principal, session)
        hotels = [
            p for p in session.scalars(select(Property).order_by(Property.property_id))
            if scope.allows_property(p.property_id) and (only is None or p.property_id == only)
        ]
        profiles = _profiles(session)
        visible = {p.property_id for p in hotels}
        # The latest day each hotel has reports for (a hotel on two PMS
        # sources has two rows; its latest is the later of them).
        latest: dict[str, date] = {}
        first: dict[str, date] = {}
        for info in reporting.list_properties(session):
            if info.property_id in visible:
                latest[info.property_id] = max(latest.get(info.property_id, info.last_date),
                                               info.last_date)
                first[info.property_id] = min(first.get(info.property_id, info.first_date),
                                              info.first_date)
        day = on if on is not None else max(latest.values(), default=None)

        days = {p.property_id: _day_for(session, p.property_id, day, p.property_id in latest)
                for p in hotels}
        targets = {p.property_id: _targets(profiles.get(p.property_id, {})) for p in hotels}
        outlooks: dict[str, OutlookOut | None] = {
            p.property_id: (
                _outlook(session, p.property_id, days[p.property_id], targets[p.property_id], day,
                         first.get(p.property_id))
                if day is not None else None
            )
            for p in hotels
        }
        trend = _trend(session, sorted(visible), day)
        findings = _findings(session, hotels, days, day, outlooks)
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
    with_target = [o for o in outlooks.values() if o is not None]
    gaps = [Decimal(o.year_gap) for o in with_target if o.year_gap is not None]
    totals = TotalsOut(
        hotels=len(hotels),
        hotels_in=len(counted),
        revenue=_money(_sum(d.revenue for d in counted)),
        occupancy_pct=_pct(_pooled(counted, "rooms_occupied", "rooms_total", scale=100)),
        adr=_money(_pooled(counted, "room_revenue", "rooms_occupied")),
        revpar=_money(_pooled(counted, "room_revenue", "rooms_total")),
        # Rooms across the portfolio: every hotel that says how many it has,
        # whether or not last night's report is in.
        rooms_total=_money(_sum(d.rooms_total for d in days.values())),
        rooms_sold=_money(_sum(d.rooms_occupied for d in counted)),
        rooms_sold_month=_money(_sum(d.rooms_sold_month for d in days.values())),
        rooms_available_month=_money(_sum(d.rooms_available_month for d in days.values())),
        month_revenue=_money(month_rev),
        month_labour_cost=_money(month_lab) if staff_shown else None,
        month_labour_pct=_pct(None if month_lab is None or month_rev is None
                              else _ratio(month_lab * 100, month_rev)) if staff_shown else None,
        year_revenue=_money(_sum(d.year_revenue for d in days.values())),
        breakeven=BreakevenSummary(
            above=sum(1 for g in gaps if g >= 0), behind=sum(1 for g in gaps if g < 0),
            unset=len(hotels) - len(with_target),
            year_gap=_money(sum(gaps, Decimal(0))) if gaps else None,
        ),
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
                rooms_sold_month=_money(days[p.property_id].rooms_sold_month),
                rooms_available_month=_money(days[p.property_id].rooms_available_month),
                month_revenue=_money(days[p.property_id].month_revenue),
                month_labour_cost=(_money(days[p.property_id].month_labour)
                                   if staff_shown else None),
                month_labour_pct=_labour_pct(days[p.property_id]) if staff_shown else None,
                year_revenue=_money(days[p.property_id].year_revenue),
                staff=staff.get(p.property_id),
                targets=targets[p.property_id],
                outlook=outlooks[p.property_id],
            )
            for p in hotels
        ],
        totals=totals,
        trend=trend,
        findings=findings,
    )


def _labour_pct(d: _Day) -> str | None:
    if d.month_labour is None or not d.month_revenue:
        return None
    return _pct(d.month_labour * 100 / d.month_revenue)


@router.put("/api/desktop/hotels/{property_id}/targets")
def put_targets(
    property_id: str, body: TargetsIn, request: Request,
    _: Principal = Depends(require_grants(ORG_ADMIN)),
) -> TargetsOut:
    """The owner's annual breakeven and last year's revenue for one hotel.
    Null clears a figure; the rest of the profile (ownership entity) is kept."""
    for name, value in (("breakeven_annual", body.breakeven_annual),
                        ("last_year_revenue", body.last_year_revenue)):
        if value is not None and (value < 0 or value > Decimal("1000000000")):
            raise HTTPException(status_code=422, detail=f"{name.replace('_', ' ')} should be a "
                                                        "yearly dollar figure, zero or more.")
    with request_session_factory(request)() as session:
        if session.get(Property, property_id) is None:
            raise HTTPException(status_code=404, detail=f"No hotel called {property_id}.")
        profiles = _profiles(session)
        profile = dict(profiles.get(property_id, {}))
        profile["breakeven_annual"] = (
            None if body.breakeven_annual is None else str(body.breakeven_annual.quantize(_CENT))
        )
        profile["last_year_revenue"] = (
            None if body.last_year_revenue is None else str(body.last_year_revenue.quantize(_CENT))
        )
        profile["targets_changed_at"] = datetime.now(UTC).isoformat(timespec="seconds")
        write_setting(session, PROFILES_KEY, {**profiles, property_id: profile})
        session.commit()
        return _targets(profile)


def install(app: FastAPI) -> None:
    app.include_router(router)
