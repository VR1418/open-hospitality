"""The desktop Overview (portfolio) on the bundled Postgres.

The promise under test: every hotel the caller may see, for one day, with
the statement's own figures (never a second calculation of them), totals
built from summed parts, a plain note for a hotel without that day's
reports — and, when Payroll & People is on, a staff picture that counts a
person at the hotel whose time clock they used.

The world is the pilot's sample hotels with their sample reports read in,
as the drop folder reads them.
"""

import time
import uuid
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from usali.db import make_engine, make_session_factory
from usali.desktop import accounts as acct
from usali.desktop.accounts_api import SessionChecker
from usali.desktop.app import OWNER, build_app
from usali.desktop.bootstrap import (
    DesktopKeys,
    app_url,
    load_sample_data,
    owner_url,
    prepare_database,
)
from usali.desktop.identity import LocalIssuer
from usali.desktop.intake import ReportIntake
from usali.desktop.passwords import hash_secret
from usali.desktop.paths import DesktopPaths
from usali.desktop.pg_runtime import PgCluster, PostgresNotFound, find_bin_dir, free_port
from usali.desktop.portfolio_api import MISSING_DAY
from usali.desktop.session_api import LaunchCodes
from usali.models import (
    Employee,
    EmployeeAssignment,
    IngestBatch,
    KioskDevice,
    MappingException,
    NightAuditState,
    PmsDailyFinancialStage,
    Punch,
    RoleAssignment,
    Timecard,
)
from usali.reporting import revenue_by_day, summary_operating_statement_from_journal
from usali.tenancy import FOUNDING_ORG_ID, OrgBoundSessionFactory

REPO = Path(__file__).resolve().parents[1]
try:
    BIN: Path | None = find_bin_dir(REPO)
except PostgresNotFound:
    BIN = None

pytestmark = pytest.mark.skipif(
    BIN is None, reason="bundled Postgres not fetched (scripts/desktop/fetch_postgres.py)"
)

PASSWORD = "harbour lights at dusk"
DAY = date(2026, 7, 7)  # the OPERA and AutoClerk samples' business date


class World:
    def __init__(self, payroll: TestClient, accounting: TestClient,
                 org_sessions: OrgBoundSessionFactory, owner: dict[str, str],
                 gm: dict[str, str]) -> None:
        self.payroll = payroll          # Payroll & People on
        self.accounting = accounting    # accounting only
        self.org_sessions = org_sessions
        self.owner = owner
        self.gm = gm

    def portfolio(self, headers: dict[str, str], *, client: TestClient | None = None,
                  day: str | None = None) -> dict:  # type: ignore[type-arg]
        c = client or self.payroll
        r = c.get("/api/desktop/portfolio", params={"date": day} if day else None,
                  headers=headers)
        assert r.status_code == 200, r.text
        return r.json()  # type: ignore[no-any-return]


def _sign_in(client: TestClient, login: str) -> dict[str, str]:
    r = client.post("/api/desktop/signin", json={"login": login, "password": PASSWORD})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _seed_staff(org: OrgBoundSessionFactory) -> None:
    """Two people: Ana is paid by HISJ and is clocked in on SSSJ's tablet;
    Ben is paid by SSSJ and is off. Ana has one timecard from a period that
    has ended (waiting) and one for the period still running (not waiting)."""
    now = datetime.now(UTC)
    today = now.date()
    with org() as s:
        ana = Employee(full_name="Ana Test", pay_type="hourly")
        ben = Employee(full_name="Ben Test", pay_type="hourly")
        s.add_all([ana, ben])
        s.flush()
        s.add_all([
            EmployeeAssignment(employee_id=ana.employee_id, property_id="HISJ", is_primary=True,
                               status="active", effective_from=date(2020, 1, 1)),
            EmployeeAssignment(employee_id=ana.employee_id, property_id="SSSJ", is_primary=False,
                               status="active", effective_from=date(2020, 1, 1)),
            EmployeeAssignment(employee_id=ben.employee_id, property_id="SSSJ", is_primary=True,
                               status="active", effective_from=date(2020, 1, 1)),
        ])
        tablet = KioskDevice(property_id="SSSJ", name="Front desk",
                             token_hash=uuid.uuid4().hex + uuid.uuid4().hex, enrolled_by="test")
        s.add(tablet)
        s.flush()
        s.add(Punch(employee_id=ana.employee_id, kiosk_device_id=tablet.device_id,
                    punch_type="clock_in", punched_at=now - timedelta(hours=1),
                    business_date=today))
        s.add_all([
            Timecard(employee_id=ana.employee_id, period_start=today - timedelta(days=30),
                     period_end=today - timedelta(days=17), status="open"),
            Timecard(employee_id=ana.employee_id, period_start=today - timedelta(days=3),
                     period_end=today + timedelta(days=10), status="open"),
        ])
        s.commit()


@pytest.fixture(scope="module")
def world(tmp_path_factory: pytest.TempPathFactory) -> Iterator[World]:
    assert BIN is not None
    root = tmp_path_factory.mktemp("portfolio")
    keys = DesktopKeys.generate()
    cluster = PgCluster(bin_dir=BIN, data_dir=root / "database", log_file=root / "db.log")
    cluster.init(keys.db_owner_password)
    port = free_port(55437)
    cluster.start(port)
    mp = pytest.MonkeyPatch()
    try:
        prepare_database(port=port, keys=keys, resources=REPO, state_file=root / "state.json",
                         user=OWNER, allow_upgrade=False)
        mp.setenv("USALI_DB_URL", app_url(port, keys))
        engine = make_engine(app_url(port, keys))
        sessions = make_session_factory(engine)
        org = OrgBoundSessionFactory(sessions, FOUNDING_ORG_ID)

        # The sample hotels and their reports, read the way the folder reads them.
        drop, read = root / "drop", root / "read"
        load_sample_data(owner_url(port, keys), REPO, drop)
        intake = ReportIntake(org, drop_folder=drop, read_folder=read,
                              unreadable_folder=root / "unreadable")
        intake.start()
        try:
            deadline = time.monotonic() + 240
            while any(drop.glob("*.pdf")) and time.monotonic() < deadline:
                time.sleep(0.5)
        finally:
            intake.stop()
        _seed_staff(org)

        codes = LaunchCodes()
        paths = DesktopPaths(owner_root=root / "owner", system_root=root / "system")
        paths.ensure()
        issuer = LocalIssuer.from_pem(keys.issuer_private_key_pem)

        def app(enabled: frozenset[str]) -> TestClient:
            return TestClient(build_app(
                paths, issuer, codes, root / "no-portal", enabled=enabled, reload=lambda: None,
                sessions=sessions, checker=SessionChecker(sessions, ttl_seconds=0),
            ), base_url="http://127.0.0.1")

        payroll = app(frozenset({"accounting", "payroll"}))
        accounting = app(frozenset({"accounting"}))
        r = payroll.post("/api/desktop/setup/owner", json={
            "code": codes.issue(), "full_name": "Priya Owner", "email": "priya@example.com",
            "password": PASSWORD,
        })
        assert r.status_code == 201, r.text
        owner = {"Authorization": f"Bearer {r.json()['access_token']}"}

        # A hotel manager for HISJ alone.
        with sessions() as s:
            acct.create_account(s, subject="gm-hisj", username="gm@example.com",
                                email="gm@example.com", full_name="Gina Manager",
                                roles=["property_gm"], password_hash=hash_secret(PASSWORD))
            s.commit()
        with org() as s:
            s.add(RoleAssignment(org_id=FOUNDING_ORG_ID, keycloak_subject="gm-hisj",
                                 role="property_gm", property_id="HISJ"))
            s.commit()
        gm = _sign_in(payroll, "gm@example.com")

        yield World(payroll, accounting, org, owner, gm)
        engine.dispose()
    finally:
        mp.undo()
        cluster.stop()


def _hotel(body: dict, property_id: str) -> dict:  # type: ignore[type-arg]
    return next(h for h in body["hotels"] if h["property_id"] == property_id)


def test_the_overview_opens_on_the_latest_day_any_hotel_reported(world: World) -> None:
    body = world.portfolio(world.owner)
    assert body["business_date"] == DAY.isoformat()
    assert body["month_start"] == DAY.replace(day=1).isoformat()
    assert {h["property_id"] for h in body["hotels"]} == {"HISJ", "SSSJ", "STDEMO"}


def test_a_hotels_figures_are_the_statements_own(world: World) -> None:
    body = world.portfolio(world.owner)
    hisj = _hotel(body, "HISJ")
    assert hisj["status"] == "in"
    with world.org_sessions() as s:
        sos = summary_operating_statement_from_journal(s, property_id="HISJ", business_date=DAY)
        month = summary_operating_statement_from_journal(
            s, property_id="HISJ", date_from=DAY.replace(day=1), date_to=DAY,
        )
    assert Decimal(hisj["revenue"]) == sos.total_operating_revenue.quantize(Decimal("0.01"))
    assert Decimal(hisj["month_revenue"]) == month.total_operating_revenue.quantize(Decimal("0.01"))
    occ = next(m.day for m in sos.statistics if m.metric_code == "OCCUPANCY_PCT")
    assert occ is not None and Decimal(hisj["occupancy_pct"]) == occ.quantize(Decimal("0.1"))


def test_a_hotel_without_the_days_reports_says_so_in_words(world: World) -> None:
    stdemo = _hotel(world.portfolio(world.owner), "STDEMO")  # its pack is for 2026-06-21
    assert stdemo["status"] == "missing"
    assert stdemo["note"] == MISSING_DAY
    assert stdemo["revenue"] is None
    # ...and on its own day, it's in.
    assert _hotel(world.portfolio(world.owner, day="2026-06-21"), "STDEMO")["status"] == "in"


def test_totals_are_built_from_summed_parts(world: World) -> None:
    body = world.portfolio(world.owner)
    counted = [h for h in body["hotels"] if h["status"] == "in"]
    t = body["totals"]
    assert t["hotels"] == 3 and t["hotels_in"] == len(counted)
    assert Decimal(t["revenue"]) == sum((Decimal(h["revenue"]) for h in counted), Decimal(0))
    # Occupancy across hotels is rooms sold over rooms — pooled over ONLY the
    # hotels that report both. Not every PMS prints its room count, and a
    # hotel's rooms sold without its rooms would overstate the total.
    paired = [h for h in counted
              if h["rooms_occupied"] is not None and h["rooms_total"] is not None]
    assert paired, "no sample hotel reported both rooms sold and rooms"
    occupied = sum((Decimal(h["rooms_occupied"]) for h in paired), Decimal(0))
    rooms = sum((Decimal(h["rooms_total"]) for h in paired), Decimal(0))
    assert Decimal(t["occupancy_pct"]) == (occupied * 100 / rooms).quantize(Decimal("0.1"))


def test_the_trend_is_a_fortnight_of_daily_revenue_across_the_hotels(world: World) -> None:
    body = world.portfolio(world.owner)
    trend = body["trend"]
    assert len(trend) == 14
    assert trend[-1]["business_date"] == DAY.isoformat()
    assert trend[0]["business_date"] == (DAY - timedelta(days=13)).isoformat()
    # The day itself has revenue; a day nobody reported is a gap, not a zero.
    assert Decimal(trend[-1]["revenue"]) > 0
    assert any(p["revenue"] is None for p in trend)
    # It sums the hotels: the last day is more than any one of them alone.
    with world.org_sessions() as s:
        hisj = revenue_by_day(s, "HISJ", DAY, DAY)[DAY]
    assert Decimal(trend[-1]["revenue"]) > hisj


def test_the_findings_are_what_last_nights_audit_turned_up(world: World) -> None:
    body = world.portfolio(world.owner)
    findings = body["findings"]
    # The hotel that sent nothing for the day says so once — not once per
    # report it didn't send.
    stdemo = [f for f in findings if f["property_id"] == "STDEMO"]
    assert [f["kind"] for f in stdemo] == ["no_reports"]
    assert stdemo[0]["hotel"] and stdemo[0]["detail"] == MISSING_DAY
    # Every finding names its hotel and says something in plain words.
    assert all(f["hotel"] and f["detail"] for f in findings)
    assert {f["kind"] for f in findings} <= {
        "no_reports", "missing_report", "check_failed", "not_in_books", "codes_to_confirm",
    }
    # Reading them changed nothing: upstream's own GET creates a state row,
    # and the Overview must not.
    with world.org_sessions() as s:
        assert s.get(NightAuditState, "STDEMO") is None


def test_a_hotel_manager_sees_their_hotel_and_no_other(world: World) -> None:
    body = world.portfolio(world.gm)
    assert [h["property_id"] for h in body["hotels"]] == ["HISJ"]
    assert body["totals"]["hotels"] == 1


def test_the_staff_picture_counts_people_where_they_clocked_in(world: World) -> None:
    body = world.portfolio(world.owner)
    assert body["staff_shown"] is True
    hisj, sssj = _hotel(body, "HISJ")["staff"], _hotel(body, "SSSJ")["staff"]
    # Ana works at both and is paid by HISJ, but she clocked in on SSSJ's tablet.
    assert (hisj["on_clock"], sssj["on_clock"]) == (0, 1)
    assert (hisj["staff"], sssj["staff"]) == (1, 2)
    # Only the card whose period has ended is waiting; it belongs to the hotel that pays her.
    assert (hisj["timecards_to_approve"], sssj["timecards_to_approve"]) == (1, 0)
    # Across hotels a person counts once.
    assert body["totals"]["staff"] == {"staff": 2, "on_clock": 1, "timecards_to_approve": 1}


def test_with_payroll_off_no_staff_figures_are_given(world: World) -> None:
    body = world.portfolio(world.owner, client=world.accounting)
    assert body["staff_shown"] is False
    assert body["totals"]["staff"] is None and body["totals"]["month_labour_pct"] is None
    assert all(h["staff"] is None and h["month_labour_cost"] is None for h in body["hotels"])


def test_nobody_signed_out_gets_the_overview(world: World) -> None:
    assert world.payroll.get("/api/desktop/portfolio").status_code == 401


def test_the_overview_says_when_codes_are_holding_money_out_of_the_books(world: World) -> None:
    """The one place this ever reaches the owner unprompted. The journal
    balances by sweeping an unrecognised code's money into the clearing
    account, which `_journal_nets` excludes — so parity is clean, every other
    check is quiet, and the profit and loss is short by exactly this."""
    day = date(2026, 4, 1)
    with world.org_sessions() as s:
        batch = IngestBatch(
            pms_source="SKYTOUCH", report_type="hotel_journal", source_file="cabana.pdf",
            file_hash="hash-cabana", status="transformed", row_count=1,
        )
        s.add(batch)
        s.flush()
        stage = PmsDailyFinancialStage(
            property_id="STDEMO", pms_source="SKYTOUCH", report_type="hotel_journal",
            business_date=day, pms_trx_code="ZZQ", pms_trx_desc="Cabana Rental",
            raw_amount="250.0000", room_count=0, source_file="cabana.pdf",
            ingest_batch_id=batch.batch_id, row_hash="cabana-1",
        )
        s.add(stage)
        s.flush()
        s.add(MappingException(
            pms_source="SKYTOUCH", pms_trx_code="ZZQ", pms_trx_desc="Cabana Rental",
            stage_id=stage.stage_id, raw_amount="250.0000", business_date=day,
            ingest_batch_id=batch.batch_id,
        ))
        s.commit()

    [found] = [f for f in world.portfolio(world.owner)["findings"]
               if f["kind"] == "codes_to_confirm"]
    assert found["property_id"] == "STDEMO"
    assert "1 code" in found["detail"] and "$250.00" in found["detail"]
    # Standing, not nightly: it is true whichever day is on screen.
    assert any(f["kind"] == "codes_to_confirm"
               for f in world.portfolio(world.owner, day="2026-01-02")["findings"])
