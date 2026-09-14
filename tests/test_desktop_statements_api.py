"""Bank and card statements through the app, on the real bundled cluster, against
facts read from the sample choiceADVANTAGE pack."""

import shutil
from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from usali.db import make_engine, make_session_factory
from usali.desktop.accounts_api import SessionChecker
from usali.desktop.app import OWNER, build_app
from usali.desktop.bootstrap import DesktopKeys, app_url, prepare_database
from usali.desktop.identity import LocalIssuer
from usali.desktop.paths import DesktopPaths
from usali.desktop.pg_runtime import PgCluster, PostgresNotFound, find_bin_dir, free_port
from usali.desktop.session_api import LaunchCodes
from usali.ingestion import process_upload
from usali.models import UsaliFinancialFact
from usali.reporting import SETTLEMENTS_MAJOR
from usali.tenancy import FOUNDING_ORG_ID, OrgBoundSessionFactory

REPO = Path(__file__).resolve().parents[1]
SAMPLE = REPO / "docs/reference/samples/SkyTouch - Standard Audit Pack (mock).pdf"
try:
    BIN: Path | None = find_bin_dir(REPO)
except PostgresNotFound:
    BIN = None

pytestmark = pytest.mark.skipif(
    BIN is None, reason="bundled Postgres not fetched (scripts/desktop/fetch_postgres.py)"
)


class World:
    def __init__(self, client: TestClient, headers: dict[str, str], sessions: object) -> None:
        self.client, self.headers, self.sessions = client, headers, sessions
        self.hotel = ""
        self.settled: dict[str, Decimal] = {}

    def get(self, path: str) -> object:
        return self.client.get(path, headers=self.headers)

    def put(self, path: str, body: object) -> object:
        return self.client.put(path, json=body, headers=self.headers)

    def upload(self, kind: str, csv_text: str, label: str = "") -> object:
        return self.client.post(
            "/api/desktop/statements", headers=self.headers,
            files={"file": ("statement.csv", csv_text.encode(), "text/csv")},
            data={"property": self.hotel, "kind": kind, "account_label": label},
        )


@pytest.fixture(scope="module")
def world(tmp_path_factory: pytest.TempPathFactory) -> Iterator[World]:
    assert BIN is not None
    root = tmp_path_factory.mktemp("statements")
    keys = DesktopKeys.generate()
    cluster = PgCluster(bin_dir=BIN, data_dir=root / "database", log_file=root / "db.log")
    cluster.init(keys.db_owner_password)
    port = free_port(55446)
    cluster.start(port)
    mp = pytest.MonkeyPatch()
    try:
        prepare_database(port=port, keys=keys, resources=REPO, state_file=root / "state.json",
                         user=OWNER, allow_upgrade=False)
        mp.setenv("USALI_DB_URL", app_url(port, keys))
        engine = make_engine(app_url(port, keys))
        sessions = make_session_factory(engine)
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
        org_sessions = OrgBoundSessionFactory(sessions, FOUNDING_ORG_ID)
        w = World(client, {"Authorization": f"Bearer {owner.json()['access_token']}"}, org_sessions)
        # The sample pack's hotel, by the code its pages print.
        made = client.post("/api/desktop/welcome/property", headers=w.headers, json={
            "ownership_entity": "Redstone Hospitality LLC", "name": "Redstone Test Inn",
            "code": "TEST1", "pms_source": "SKYTOUCH", "timezone": "America/Chicago",
            "fiscal": {"calendar_type": "calendar_month", "fiscal_year_start_month": 1,
                       "week_start_weekday": None},
        })
        assert made.status_code == 201, made.text
        w.hotel = made.json()["property_id"]
        drop = root / "drop" / SAMPLE.name
        drop.parent.mkdir()
        shutil.copy(SAMPLE, drop)
        with org_sessions() as s:
            process_upload(s, drop, processed_dir=root / "read", failed_dir=root / "failed")
            rows = s.execute(
                select(UsaliFinancialFact.usali_line_item, func.sum(UsaliFinancialFact.amount))
                .where(UsaliFinancialFact.property_id == w.hotel,
                       UsaliFinancialFact.usali_major_category == SETTLEMENTS_MAJOR)
                .group_by(UsaliFinancialFact.usali_line_item)
            ).all()
        w.settled = {line: abs(Decimal(total)) for line, total in rows}
        assert {"Visa", "Cash"} <= set(w.settled), w.settled
        yield w
        engine.dispose()
    finally:
        mp.undo()
        cluster.stop()


def test_a_bank_statement_is_checked_against_the_night_audits(world: World) -> None:
    cards = world.settled["Visa"] + world.settled.get("MasterCard", Decimal("0"))
    net = (cards * Decimal("0.975")).quantize(Decimal("0.01"))  # the processor's fee
    csv_text = (
        "Date,Description,Amount,Balance\n"
        f"06/23/2026,BANKCARD MERCH DEP 0421,{net},50000.00\n"
        f"06/22/2026,DEPOSIT,{world.settled['Cash']},49000.00\n"
        "06/24/2026,GUSTO PAYROLL 260624,-4210.55,44789.45\n"
        "06/25/2026,SBA LOAN PMT,-1800.00,42989.45\n"
        "06/25/2026,BANKCARD MERCH DEP 0421,77.77,43067.22\n"
    )
    r = world.upload("bank", csv_text, "Operating account")
    assert r.status_code == 201, r.text  # type: ignore[attr-defined]
    body = r.json()  # type: ignore[attr-defined]
    assert body["kind"] == "bank" and body["account_label"] == "Operating account"
    assert body["lines"] == 5 and body["unmatched"] == 2
    by_desc = {row["description"]: row for row in body["rows"]}
    cards_row = next(row for row in body["rows"] if row["amount"] == str(net))
    assert cards_row["match_kind"] == "settlement"
    assert "Visa/MasterCard settled 6/21, less $" in cards_row["match_note"]
    assert Decimal(cards_row["matched_amount"]) == cards
    assert by_desc["DEPOSIT"]["match_kind"] == "cash"
    assert by_desc["GUSTO PAYROLL 260624"]["match_kind"] == "payroll"
    assert by_desc["SBA LOAN PMT"]["match_kind"] == "unmatched"
    stray = next(row for row in body["rows"] if row["amount"] == "77.77")
    assert stray["match_kind"] == "unmatched" and "No Visa/MasterCard settlement" in stray["match_note"]

    # The owner marks the loan as not the hotel's business.
    marked = world.put(f"/api/desktop/statements/lines/{by_desc['SBA LOAN PMT']['line_id']}", {
        "match_kind": "ignored", "match_note": "Owner's loan, paid from here",
    })
    assert marked.status_code == 200 and marked.json()["match_kind"] == "ignored"  # type: ignore[attr-defined]
    listed = world.get(f"/api/desktop/statements?property={world.hotel}").json()  # type: ignore[attr-defined]
    assert listed[0]["unmatched"] == 1 and listed[0]["money_out"] == "6010.55"


def test_a_card_statement_is_sorted_and_the_merchant_remembered(world: World) -> None:
    first = world.upload("card", (
        "Transaction Date,Description,Amount\n"
        "06/02/2026,HOME DEPOT #6512 CARLSBAD NM,-142.18\n"
        "06/03/2026,AMAZON MKTPL*2K4J1 SEATTLE WA,-58.40\n"
        "06/05/2026,PAYMENT - THANK YOU,900.00\n"
    ), "Visa ending 4411")
    assert first.status_code == 201, first.text  # type: ignore[attr-defined]
    body = first.json()  # type: ignore[attr-defined]
    assert body["kind"] == "card" and body["unmatched"] == 3
    assert body["by_category"] == [["Not sorted yet", "200.58"]]
    depot = next(row for row in body["rows"] if row["description"].startswith("HOME DEPOT"))
    sorted_row = world.put(f"/api/desktop/statements/lines/{depot['line_id']}",
                           {"category": "Repairs & maintenance"})
    assert sorted_row.status_code == 200, sorted_row.text  # type: ignore[attr-defined]
    nonsense = world.put(f"/api/desktop/statements/lines/{depot['line_id']}", {"category": "Fun"})
    assert nonsense.status_code == 422  # type: ignore[attr-defined]

    # Next month, a different store number: sorted on the way in.
    second = world.upload("card", (
        "Transaction Date,Description,Amount\n"
        "07/02/2026,HOME DEPOT #9901 ROSWELL NM,-31.00\n"
        "07/09/2026,HOME DEPOT #6512 CARLSBAD NM,-12.50\n"
    )).json()  # type: ignore[attr-defined]
    categories = {row["description"]: row["category"] for row in second["rows"]}
    assert categories["HOME DEPOT #6512 CARLSBAD NM"] == "Repairs & maintenance"
    assert categories["HOME DEPOT #9901 ROSWELL NM"] is None  # a different town is a different key
    assert second["by_category"] == [["Not sorted yet", "31.00"], ["Repairs & maintenance", "12.50"]]
    assert world.get("/api/desktop/statements/categories").json()[0] == "Rooms — Cleaning supplies"  # type: ignore[attr-defined]


def test_a_file_that_is_not_a_statement_and_a_missing_hotel_are_refused(world: World) -> None:
    r = world.upload("bank", "hello,world\n1,2\n")
    assert r.status_code == 422 and "name the columns" in r.json()["detail"]  # type: ignore[attr-defined]
    r = world.client.post(
        "/api/desktop/statements", headers=world.headers,
        files={"file": ("s.csv", b"Date,Description,Amount\n06/01/2026,x,1\n", "text/csv")},
        data={"property": "NOPE", "kind": "bank"},
    )
    assert r.status_code == 404
    assert world.client.get(f"/api/desktop/statements?property={world.hotel}").status_code == 401


def test_a_statement_can_be_removed(world: World) -> None:
    listed = world.get(f"/api/desktop/statements?property={world.hotel}").json()  # type: ignore[attr-defined]
    sid = listed[-1]["statement_id"]
    gone = world.client.delete(f"/api/desktop/statements/{sid}", headers=world.headers)
    assert gone.status_code == 204
    assert world.get(f"/api/desktop/statements/{sid}").status_code == 404  # type: ignore[attr-defined]
