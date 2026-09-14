"""The owner's first-run wizard on the bundled Postgres (PRD M2).

The promise under test: a hotel the wizard creates is ready for its first
report — the report's header resolves to it, its rooms and fiscal calendar
satisfy upstream's own checklist and property-config reads — and it was
written through the RLS-bound serving role, as every request is.
"""

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from usali.adaptors.pdf import Word
from usali.db import make_engine, make_session_factory
from usali.desktop.accounts_api import SessionChecker
from usali.desktop.app import OWNER, build_app
from usali.desktop.bootstrap import DesktopKeys, app_url, prepare_database
from usali.desktop.identity import LocalIssuer
from usali.desktop.paths import DesktopPaths
from usali.desktop.pg_runtime import PgCluster, PostgresNotFound, find_bin_dir, free_port
from usali.desktop.session_api import LaunchCodes
from usali.desktop.welcome_api import new_property_id, pms_choices
from usali.detect import detect, load_registry, supported_pms_sources
from usali.models import Property
from usali.tenancy import FOUNDING_ORG_ID, OrgBoundSessionFactory

REPO = Path(__file__).resolve().parents[1]
try:
    BIN: Path | None = find_bin_dir(REPO)
except PostgresNotFound:
    BIN = None

pytestmark = pytest.mark.skipif(
    BIN is None, reason="bundled Postgres not fetched (scripts/desktop/fetch_postgres.py)"
)

HOTEL = {
    "name": "Redstone Test Inn",
    "report_name": "redstone   test inn",
    "pms_source": "skytouch",
    "total_rooms": 60,
    "timezone": "America/Chicago",
    "fiscal": {"calendar_type": "calendar_month", "fiscal_year_start_month": 1,
               "week_start_weekday": None},
}


class World:
    def __init__(self, client: TestClient, headers: dict[str, str], org_sessions: object):
        self.client = client
        self.headers = headers
        self.org_sessions = org_sessions

    def get(self, path: str) -> object:
        return self.client.get(path, headers=self.headers)

    def post(self, path: str, body: object = None) -> object:
        return self.client.post(path, json=body, headers=self.headers)


@pytest.fixture(scope="module")
def world(tmp_path_factory: pytest.TempPathFactory) -> Iterator[World]:
    assert BIN is not None
    root = tmp_path_factory.mktemp("welcome")
    keys = DesktopKeys.generate()
    cluster = PgCluster(bin_dir=BIN, data_dir=root / "database", log_file=root / "db.log")
    cluster.init(keys.db_owner_password)
    port = free_port(55436)
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
        headers = {"Authorization": f"Bearer {owner.json()['access_token']}"}
        yield World(client, headers, OrgBoundSessionFactory(sessions, FOUNDING_ORG_ID))
        engine.dispose()
    finally:
        mp.undo()
        cluster.stop()


def test_the_pms_choices_are_the_engines_own_registry_plus_other() -> None:
    choices = pms_choices()
    detectable = {c.id for c in choices} - {"OTHER"}
    # Every system we claim to READ comes from the engine's own registry, so
    # the wizard can never offer one whose reports would quarantine on ingest.
    assert detectable == {s.upper() for s in supported_pms_sources()}
    # The owner reads choiceADVANTAGE, never the engine's SKYTOUCH identifier.
    assert ("SKYTOUCH", "choiceADVANTAGE") in [(c.id, c.name) for c in choices]
    # OTHER is not a vendor and is last: it exists so a hotel we have no
    # parser for can still be set up, its reports read with the AI helper's
    # assistance instead (ADR-D7 phase 3).
    assert choices[-1].id == "OTHER"
    assert "AI helper" in choices[-1].name
    # choiceADVANTAGE prints the hotel's code on every report, so its hotels
    # are recognised by the code and the form does not ask for a printed name.
    by_id = {c.id: c for c in choices}
    assert by_id["SKYTOUCH"].prints_code and not by_id["OPERA"].prints_code


def test_property_codes_are_short_and_never_clash() -> None:
    assert new_property_id("Holiday Inn & Suites San Jose", set()) == "HISSJ"
    assert new_property_id("Marriott", set()) == "MARRIOTT"
    assert new_property_id("Redstone Inn", {"RI", "RI2"}) == "RI3"
    assert new_property_id("!!!", set()) == "HOTEL"


def test_a_new_install_starts_the_wizard(world: World) -> None:
    r = world.get("/api/desktop/welcome")
    assert r.status_code == 200, r.text  # type: ignore[attr-defined]
    body = r.json()  # type: ignore[attr-defined]
    assert body["finished"] is False
    assert body["group_named"] is False
    assert body["properties"] == []
    # PRD I-6: the wizard asks where backups go, so it has to know.
    assert body["backup_folder_set"] is False


def test_nobody_signed_out_can_read_or_change_it(world: World) -> None:
    assert world.client.get("/api/desktop/welcome").status_code == 401
    assert world.client.post("/api/desktop/welcome/property", json=HOTEL).status_code == 401


def test_finishing_needs_a_hotel_first(world: World) -> None:
    r = world.post("/api/desktop/welcome/finish")
    assert r.status_code == 409 and "first hotel" in r.json()["detail"]  # type: ignore[attr-defined]


def test_the_owner_names_their_hotel_group(world: World) -> None:
    r = world.client.put("/api/desktop/welcome/group", json={"name": "  Redstone   Hotels "},
                         headers=world.headers)
    assert r.status_code == 204, r.text
    body = world.get("/api/desktop/welcome").json()  # type: ignore[attr-defined]
    assert body["group_name"] == "Redstone Hotels" and body["group_named"] is True


def test_a_new_hotel_is_ready_for_its_first_report(world: World) -> None:
    r = world.post("/api/desktop/welcome/property", HOTEL)
    assert r.status_code == 201, r.text  # type: ignore[attr-defined]
    assert r.json() == {"property_id": "RTI", "name": "Redstone Test Inn"}  # type: ignore[attr-defined]

    [hotel] = world.get("/api/desktop/welcome").json()["properties"]  # type: ignore[attr-defined]
    assert hotel == {"property_id": "RTI", "name": "Redstone Test Inn", "pms_source": "SKYTOUCH",
                     "ownership_entity": None, "has_fiscal_calendar": True, "has_rooms": True}

    # Upstream's own reads agree: the checklist's required set-up items...
    items = {i["key"]: i["status"] for i in world.get("/api/checklist").json()["items"]}  # type: ignore[attr-defined]
    assert items["fiscal_calendar"] == "done" and items["room_inventory"] == "done"
    # ...and property config.
    config = world.get("/api/properties/RTI/config").json()  # type: ignore[attr-defined]
    assert config["fiscal_calendar"]["calendar_type"] == "calendar_month"
    assert config["inventory"][0]["total_rooms"] == 60

    # The point of the alias: a choiceADVANTAGE header naming the hotel as
    # its PMS prints it resolves to this property.
    with world.org_sessions() as s:  # type: ignore[operator]
        registry = load_registry(s)
        tz = s.scalar(select(Property.timezone).where(Property.property_id == "RTI"))
    header = "REDSTONE TEST INN Hotel Journal Summary Business Date 07/07/2026".split()
    found = detect([Word(text=t, x0=0.0, top=0.0) for t in header], registry)
    assert (found.property_id, found.pms_source) == ("RTI", "SKYTOUCH")
    assert tz == "America/Chicago"


def test_a_report_name_that_could_be_mixed_up_is_refused(world: World) -> None:
    for report_name in ("Redstone Test Inn West", "TEST INN"):
        r = world.post("/api/desktop/welcome/property",
                       {**HOTEL, "name": "Redstone West", "report_name": report_name})
        assert r.status_code == 409, report_name  # type: ignore[attr-defined]
        assert "RTI" in r.json()["detail"]  # type: ignore[attr-defined]


def test_what_it_cannot_do_is_refused_in_words(world: World) -> None:
    other = world.post("/api/desktop/welcome/property",
                       {**HOTEL, "report_name": "Somewhere Else Hotel", "pms_source": "CLOUDBEDS"})
    assert other.status_code == 422 and "can't read" in other.json()["detail"]  # type: ignore[attr-defined]
    unpaired = world.post("/api/desktop/welcome/property", {
        **HOTEL, "report_name": "Somewhere Else Hotel",
        "fiscal": {"calendar_type": "445", "fiscal_year_start_month": 1, "week_start_weekday": None},
    })
    assert unpaired.status_code == 422  # type: ignore[attr-defined]
    # Nothing half-made was left behind by either refusal.
    names = [p["name"] for p in world.get("/api/desktop/welcome").json()["properties"]]  # type: ignore[attr-defined]
    assert names == ["Redstone Test Inn"]


def test_a_second_hotel_on_a_4_4_5_year(world: World) -> None:
    r = world.post("/api/desktop/welcome/property", {
        **HOTEL, "name": "Harbour View", "report_name": "HARBOUR VIEW HOTEL", "pms_source": "OPERA",
        "fiscal": {"calendar_type": "445", "fiscal_year_start_month": 4, "week_start_weekday": 0},
    })
    assert r.status_code == 201, r.text  # type: ignore[attr-defined]
    config = world.get(f"/api/properties/{r.json()['property_id']}/config").json()  # type: ignore[attr-defined]
    assert config["fiscal_calendar"] == {"calendar_type": "445", "fiscal_year_start_month": 4,
                                         "week_start_weekday": 0}


def test_finishing_stops_the_wizard(world: World) -> None:
    r = world.post("/api/desktop/welcome/finish")
    assert r.status_code == 200 and r.json() == {"finished": True}  # type: ignore[attr-defined]
    assert world.get("/api/desktop/welcome").json()["finished"] is True  # type: ignore[attr-defined]


SIGNUP = {
    "ownership_entity": "Redstone Hospitality LLC",
    "name": "Redstone Lodge",
    "code": " tx901 ",
    "pms_source": "SKYTOUCH",
    "timezone": "America/Chicago",
    "fiscal": {"calendar_type": "calendar_month", "fiscal_year_start_month": 1,
               "week_start_weekday": None},
}


def test_signup_asks_for_the_owning_company_the_name_and_the_code(world: World) -> None:
    """No room count: the first statistics report carries it (ingestion), and
    the checklist says so until one has arrived."""
    r = world.post("/api/desktop/welcome/property", SIGNUP)
    assert r.status_code == 201, r.text  # type: ignore[attr-defined]
    # The code the owner typed is the hotel's code everywhere — not one made up.
    assert r.json() == {"property_id": "TX901", "name": "Redstone Lodge"}  # type: ignore[attr-defined]

    hotels = world.get("/api/desktop/welcome").json()["properties"]  # type: ignore[attr-defined]
    [hotel] = [h for h in hotels if h["property_id"] == "TX901"]
    assert hotel["ownership_entity"] == "Redstone Hospitality LLC"
    assert hotel["has_rooms"] is False

    # A choiceADVANTAGE report is matched by the code it prints, so a report
    # naming a different hotel of the same brand is not claimed.
    with world.org_sessions() as s:  # type: ignore[operator]
        registry = load_registry(s)
    header = "Hotel Journal Summary Property Name: Redstone Lodge Property Code: TX901".split()
    found = detect([Word(text=t, x0=0.0, top=0.0) for t in header], registry)
    assert found.property_id == "TX901"
    other = "Hotel Journal Summary Property Name: Redstone Lodge Property Code: TX902".split()
    with pytest.raises(ValueError):
        detect([Word(text=t, x0=0.0, top=0.0) for t in other], registry)


def test_a_code_is_set_up_once_and_looks_like_a_code(world: World) -> None:
    again = world.post("/api/desktop/welcome/property", {**SIGNUP, "name": "Another"})
    assert again.status_code == 409 and "TX901" in again.json()["detail"]  # type: ignore[attr-defined]
    bad = world.post("/api/desktop/welcome/property", {**SIGNUP, "code": "TX 9/01!"})
    assert bad.status_code == 422 and "letters and numbers" in bad.json()["detail"]  # type: ignore[attr-defined]
