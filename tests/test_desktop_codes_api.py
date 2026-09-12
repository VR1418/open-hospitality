"""Codes to confirm (PRD M4, Phase 1).

The promise under test: a code nobody has explained is shown WITH the money
it is holding out of the books — the money `transform` banks as a mapping
exception and `build_pms_daily_plan` sweeps into the clearing account, where
`sos_journal_parity` excludes it and reports parity over a profit and loss
that is missing revenue. Confirming the code puts that money in the books,
and a day inside a closed month is refused by name rather than restated
quietly.
"""

from collections.abc import Iterator
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from usali import gl_posting
from usali.db import make_engine, make_session_factory
from usali.desktop.accounts_api import SessionChecker
from usali.desktop.app import OWNER, build_app
from usali.desktop.bootstrap import DesktopKeys, app_url, prepare_database
from usali.desktop.identity import LocalIssuer
from usali.desktop.mapping_decisions import DecidingSessionFactory
from usali.desktop.paths import DesktopPaths
from usali.desktop.pg_runtime import PgCluster, PostgresNotFound, find_bin_dir, free_port
from usali.desktop.session_api import LaunchCodes
from usali.models import IngestBatch, PmsDailyFinancialStage, UsaliFinancialFact
from usali.tenancy import FOUNDING_ORG_ID, OrgBoundSessionFactory

REPO = Path(__file__).resolve().parents[1]
try:
    BIN: Path | None = find_bin_dir(REPO)
except PostgresNotFound:
    BIN = None

pytestmark = pytest.mark.skipif(
    BIN is None, reason="bundled Postgres not fetched (scripts/desktop/fetch_postgres.py)"
)

SOURCE = "SKYTOUCH"
HOTEL = {
    "name": "Cedar Point Inn", "report_name": "CEDAR POINT INN", "pms_source": "skytouch",
    "total_rooms": 40, "timezone": "America/Chicago",
    "fiscal": {"calendar_type": "calendar_month", "fiscal_year_start_month": 1,
               "week_start_weekday": None},
}


class World:
    def __init__(self, client: TestClient, headers: dict[str, str], sessions: object) -> None:
        self.client = client
        self.headers = headers
        self.sessions = sessions
        self.property_id = ""

    def get(self, path: str) -> object:
        return self.client.get(path, headers=self.headers)

    def put(self, path: str, body: object) -> object:
        return self.client.put(path, json=body, headers=self.headers)

    def stage(self, *, day: date, code: str, desc: str, amount: str) -> None:
        with self.sessions() as s:  # type: ignore[operator]
            batch = IngestBatch(
                pms_source=SOURCE, report_type="hotel_journal", source_file=f"{day}-{code}.pdf",
                file_hash=f"h-{day}-{code}", status="started", row_count=1,
            )
            s.add(batch)
            s.flush()
            s.add(PmsDailyFinancialStage(
                property_id=self.property_id, pms_source=SOURCE, report_type="hotel_journal",
                business_date=day, pms_trx_code=code, pms_trx_desc=desc, raw_amount=amount,
                room_count=1, source_file=f"{day}-{code}.pdf", ingest_batch_id=batch.batch_id,
                row_hash=f"{day}-{code}",
            ))
            s.commit()

    def facts_for(self, code: str) -> list[UsaliFinancialFact]:
        from sqlalchemy import select
        with self.sessions() as s:  # type: ignore[operator]
            ids = list(s.scalars(select(PmsDailyFinancialStage.stage_id).where(
                PmsDailyFinancialStage.pms_trx_code == code
            )))
            if not ids:
                return []
            return list(s.scalars(
                select(UsaliFinancialFact).where(UsaliFinancialFact.stage_id.in_(ids))
            ))


@pytest.fixture(scope="module")
def world(tmp_path_factory: pytest.TempPathFactory) -> Iterator[World]:
    assert BIN is not None
    root = tmp_path_factory.mktemp("codes")
    keys = DesktopKeys.generate()
    cluster = PgCluster(bin_dir=BIN, data_dir=root / "database", log_file=root / "db.log")
    cluster.init(keys.db_owner_password)
    port = free_port(55440)
    cluster.start(port)
    mp = pytest.MonkeyPatch()
    try:
        prepare_database(port=port, keys=keys, resources=REPO, state_file=root / "state.json",
                         user=OWNER, allow_upgrade=False)
        mp.setenv("USALI_DB_URL", app_url(port, keys))
        engine = make_engine(app_url(port, keys))
        sessions = DecidingSessionFactory(make_session_factory(engine))
        codes = LaunchCodes()
        paths = DesktopPaths(owner_root=root / "owner", system_root=root / "system")
        paths.ensure()
        app = build_app(
            paths, LocalIssuer.from_pem(keys.issuer_private_key_pem), codes, root / "no-portal",
            enabled=frozenset({"accounting"}), reload=lambda: None,
            sessions=sessions, checker=SessionChecker(sessions, ttl_seconds=0),
        )
        client = TestClient(app, base_url="http://127.0.0.1")
        owner = client.post("/api/desktop/setup/owner", json={
            "code": codes.issue(), "full_name": "Priya Owner", "email": "priya@example.com",
            "password": "harbour lights at dusk",
        })
        assert owner.status_code == 201, owner.text
        headers = {"Authorization": f"Bearer {owner.json()['access_token']}"}
        w = World(client, headers, OrgBoundSessionFactory(sessions, FOUNDING_ORG_ID))
        made = client.post("/api/desktop/welcome/property", json=HOTEL, headers=headers)
        assert made.status_code == 201, made.text
        w.property_id = made.json()["property_id"]
        yield w
        engine.dispose()
    finally:
        mp.undo()
        cluster.stop()


def _items(body: dict[str, object]) -> dict[str, dict[str, object]]:
    return {i["code"]: i for i in body["items"]}  # type: ignore[index,union-attr]


def test_nobody_signed_out_can_read_or_change_it(world: World) -> None:
    assert world.client.get(f"/api/desktop/codes?property={world.property_id}").status_code == 401
    assert world.client.put("/api/desktop/codes/RM", json={}).status_code == 401


def test_an_unknown_hotel_is_a_404(world: World) -> None:
    r = world.get("/api/desktop/codes?property=NOPE")
    assert r.status_code == 404  # type: ignore[attr-defined]


def test_a_code_nobody_knows_is_shown_with_the_money_it_holds(world: World) -> None:
    world.stage(day=date(2026, 4, 1), code="ZZQ", desc="Cabana Rental", amount="250.0000")
    body = world.get(f"/api/desktop/codes?property={world.property_id}").json()  # type: ignore[attr-defined]
    item = _items(body)["ZZQ"]
    assert item["status"] == "unknown"
    assert item["current"] is None
    assert item["description"] == "Cabana Rental"
    assert Decimal(item["amount"]) == Decimal("250")  # type: ignore[arg-type]
    # The headline figure: money the profit and loss does not have.
    assert Decimal(body["money_not_in_the_books"]) == Decimal("250")  # type: ignore[arg-type]


def test_a_shipped_guess_is_shown_as_a_guess(world: World) -> None:
    """Every choiceADVANTAGE row ships LOW / needs-review, and `transform`
    reads neither field — so it posts like a confirmed one."""
    world.stage(day=date(2026, 4, 1), code="RM", desc="Room Charge", amount="900.0000")
    item = _items(world.get(f"/api/desktop/codes?property={world.property_id}").json())["RM"]  # type: ignore[attr-defined]
    assert item["status"] == "unconfirmed"
    assert item["current"]["line_item"] == "Room Revenue"  # type: ignore[index]
    assert item["decided_by"] is None


def test_the_lines_on_offer_are_ones_the_product_knows(world: World) -> None:
    lines = world.get("/api/desktop/codes/choices").json()["lines"]  # type: ignore[attr-defined]
    assert {"Room Revenue", "Other Rooms Revenue"} <= {ln["line_item"] for ln in lines}
    # No duplicates: the picker is a list of distinct classifications.
    seen = [tuple(sorted(ln.items())) for ln in lines]
    assert len(seen) == len(set(seen))


def test_a_line_the_product_does_not_know_is_refused(world: World) -> None:
    r = world.put("/api/desktop/codes/ZZQ", {
        "property_id": world.property_id, "pms_source": SOURCE,
        "line": {"schedule_id": 1, "major": "Invented", "sub": "Nonsense",
                 "line_item": "Made Up", "gl_account_code": "4000"},
    })
    assert r.status_code == 422  # type: ignore[attr-defined]
    assert "knows about" in r.json()["detail"]  # type: ignore[attr-defined]


def test_confirming_a_code_puts_its_money_in_the_books(world: World) -> None:
    lines = world.get("/api/desktop/codes/choices").json()["lines"]  # type: ignore[attr-defined]
    other = next(ln for ln in lines if ln["line_item"] == "Other Rooms Revenue")

    assert world.facts_for("ZZQ") == []
    r = world.put("/api/desktop/codes/ZZQ", {
        "property_id": world.property_id, "pms_source": SOURCE, "line": other,
        "note": "Cabanas are a rooms extra here.",
    })
    assert r.status_code == 200, r.text  # type: ignore[attr-defined]
    out = r.json()  # type: ignore[attr-defined]
    assert out["days_restated"] == ["2026-04-01"]
    assert out["facts_written"] == 1
    assert out["ledger_refused"] == {}

    [fact] = world.facts_for("ZZQ")
    assert fact.usali_line_item == "Other Rooms Revenue"
    assert Decimal(fact.amount) == Decimal("250")

    body = world.get(f"/api/desktop/codes?property={world.property_id}").json()  # type: ignore[attr-defined]
    item = _items(body)["ZZQ"]
    assert item["status"] == "confirmed"
    assert item["decided_by"] is not None and item["decided_at"] is not None
    # And the headline figure is back to nothing.
    assert Decimal(body["money_not_in_the_books"]) == Decimal("0")  # type: ignore[arg-type]


def test_a_confirmed_code_can_be_moved_and_its_days_restated(world: World) -> None:
    lines = world.get("/api/desktop/codes/choices").json()["lines"]  # type: ignore[attr-defined]
    room = next(ln for ln in lines if ln["line_item"] == "Room Revenue")
    r = world.put("/api/desktop/codes/ZZQ", {
        "property_id": world.property_id, "pms_source": SOURCE, "line": room,
    })
    assert r.status_code == 200, r.text  # type: ignore[attr-defined]
    # Restated, not duplicated: still one fact, on the new line.
    [fact] = world.facts_for("ZZQ")
    assert fact.usali_line_item == "Room Revenue"


def test_a_day_in_a_closed_month_is_refused_by_name(world: World) -> None:
    """A restatement the ledger cannot take would leave the facts changed and
    the journal stale — the one state nothing in the product detects."""
    day = date(2026, 5, 4)
    world.stage(day=day, code="QQZ", desc="Kayak Hire", amount="75.0000")
    with world.sessions() as s:  # type: ignore[operator]
        key = gl_posting.period_key_for(s, world.property_id, day)
        gl_posting.close_period(s, property_id=world.property_id, period_key=key, actor="owner")
        s.commit()

    lines = world.get("/api/desktop/codes/choices").json()["lines"]  # type: ignore[attr-defined]
    r = world.put("/api/desktop/codes/QQZ", {
        "property_id": world.property_id, "pms_source": SOURCE, "line": lines[0],
    })
    assert r.status_code == 409  # type: ignore[attr-defined]
    assert "2026-05-04" in r.json()["detail"]  # type: ignore[attr-defined]
    # Nothing was written: the refusal comes before the decision.
    assert world.facts_for("QQZ") == []
    item = _items(world.get(f"/api/desktop/codes?property={world.property_id}").json())["QQZ"]  # type: ignore[attr-defined]
    assert item["status"] == "unknown"


def test_charges_and_payments_both_count_towards_the_figure(world: World) -> None:
    """A night audit nets to zero by construction — charges in, settlements
    out. Summing signed amounts would tell a hotel whose codes are ALL
    unknown that nothing was missing, which is the case this page exists for."""
    day = date(2026, 7, 9)
    world.stage(day=day, code="WXY", desc="Spa Charge", amount="400.0000")
    world.stage(day=day, code="WXZ", desc="Card Settlement", amount="-400.0000")
    body = world.get(f"/api/desktop/codes?property={world.property_id}").json()  # type: ignore[attr-defined]
    figure = Decimal(body["money_not_in_the_books"])
    assert figure >= Decimal("800"), "both sides count as money, they do not cancel"
