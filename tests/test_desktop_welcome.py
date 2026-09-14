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
    "wage_jurisdiction": "US",
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

    welcome = world.get("/api/desktop/welcome").json()  # type: ignore[attr-defined]
    [hotel] = [h for h in welcome["properties"] if h["property_id"] == "TX901"]
    assert hotel["ownership_entity"] == "Redstone Hospitality LLC"
    assert hotel["has_rooms"] is False
    # Whose overtime rules apply: the engine's own list, federal last, and
    # the hotel carries the choice so schedules can be costed from day one.
    assert welcome["jurisdictions"][-1]["id"] == "US"
    assert {"id": "US-CA", "name": "California"} in welcome["jurisdictions"]
    with world.org_sessions() as s:  # type: ignore[operator]
        assert s.scalar(select(Property.wage_jurisdiction).where(Property.property_id == "TX901")) == "US"

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
    elsewhere = world.post("/api/desktop/welcome/property",
                           {**SIGNUP, "code": "TX902", "wage_jurisdiction": "FR"})
    assert elsewhere.status_code == 422 and "state" in elsewhere.json()["detail"]  # type: ignore[attr-defined]


def test_the_folders_holding_the_reports_are_listed_and_can_be_opened(world: World) -> None:
    """Asked for by the owner: "show which folder has all reports"."""
    opened: list[object] = []
    app = world.client.app
    original = app.state.desktop_folders_reveal  # type: ignore[attr-defined]
    app.state.desktop_folders_reveal = opened.append  # type: ignore[attr-defined]
    try:
        body = world.get("/api/desktop/folders").json()  # type: ignore[attr-defined]
        ids = [f["id"] for f in body["folders"]]
        # The app's own saved reports come first; then the report folders.
        assert ids[:5] == ["saved", "drop", "read", "unreadable", "memory"]
        saved = body["folders"][0]
        assert saved["name"] == "Saved reports" and saved["path"].startswith(body["root"])
        assert "accountant pack" in saved["what"]

        assert world.post("/api/desktop/folders/saved/open").status_code == 204  # type: ignore[attr-defined]
        assert [str(p) for p in opened] == [saved["path"]]
        # Only the fixed folders, by name — never a path from the request.
        assert world.post("/api/desktop/folders/..%2F..%2FWindows/open").status_code == 404  # type: ignore[attr-defined]
    finally:
        app.state.desktop_folders_reveal = original  # type: ignore[attr-defined]
    assert world.client.get("/api/desktop/folders").status_code == 401


def test_what_is_connected_and_what_is_not_in_one_place(world: World) -> None:
    """Asked for by the owner: "show what is connected and what is not"."""
    body = world.get("/api/desktop/connections").json()  # type: ignore[attr-defined]
    rows = {c["id"]: c for c in body["connections"]}
    assert list(rows) == ["hotels", "ai", "email", "bank", "backups", "clocks", "startup"]
    # A hotel with no reports yet is something to look at, and says which.
    assert rows["hotels"]["state"] == "attention" and "no reports yet" in rows["hotels"]["detail"]
    # The optional pieces say they are optional; the one that isn't nags.
    assert rows["ai"]["state"] == "not_set_up" and "Optional" in rows["ai"]["detail"]
    assert rows["email"]["state"] == "not_set_up" and rows["email"]["page"] == "/email"
    assert rows["backups"]["state"] == "attention" and "No backup folder" in rows["backups"]["detail"]
    # The time clock runs on this computer's screen: nothing to enroll elsewhere.
    assert rows["clocks"]["state"] == "not_set_up" and "this computer" in rows["clocks"]["detail"]
    assert all(c["page"].startswith("/") for c in body["connections"])
    # Not an installed copy here: starting with Windows can't be offered.
    startup = world.get("/api/desktop/startup").json()  # type: ignore[attr-defined]
    assert startup == {"enabled": False, "available": False}
    assert world.client.get("/api/desktop/connections").status_code == 401


def test_a_backup_folder_is_not_connected_until_a_backup_has_been_taken(tmp_path: Path) -> None:
    """The Overview said "Backups — Connected" beside "No backup has been
    taken yet". A folder chosen and armed is still something to look at
    until the first copy exists, and the line says when that happens."""
    from datetime import UTC, datetime

    from usali.desktop.backup import BackupConfig
    from usali.desktop.connections_api import _backups

    paths = DesktopPaths(owner_root=tmp_path / "owner", system_root=tmp_path / "system")
    paths.ensure()
    BackupConfig(folder=tmp_path / "synced").save(paths.backup_config_file)
    paths.backup_wrap_file.write_text("{}", encoding="utf-8")
    row = _backups(paths)
    assert row.state == "attention" and "next time you start" in row.detail
    BackupConfig(folder=tmp_path / "synced", last_backup_at=datetime(2026, 9, 13, 6, 0, tzinfo=UTC),
                 last_file="x.ohbackup").save(paths.backup_config_file)
    row = _backups(paths)
    assert row.state == "connected" and "last backup 13 Sep" in row.detail


def test_the_folder_dialog_answers_with_a_folder_or_nothing(world: World) -> None:
    """A text box for a folder path is the thing an owner gets wrong; the
    page asks Windows' own dialog instead, and hears back the folder chosen,
    nothing when cancelled, or that there is no dialog here."""
    app = world.client.app
    original = app.state.desktop_folders_pick  # type: ignore[attr-defined]
    asked: list[tuple[object, str]] = []

    def chosen(start: object, title: str) -> Path:
        asked.append((start, title))
        return Path("D:/Hotel backups")

    try:
        app.state.desktop_folders_pick = chosen  # type: ignore[attr-defined]
        r = world.post("/api/desktop/folders/pick", {"start": "C:/somewhere", "title": "Where?"})
        assert r.status_code == 200 and r.json()["folder"] == str(Path("D:/Hotel backups"))  # type: ignore[attr-defined]
        assert asked == [(Path("C:/somewhere"), "Where?")]

        app.state.desktop_folders_pick = lambda start, title: None  # type: ignore[attr-defined]
        assert world.post("/api/desktop/folders/pick", {}).json() == {"folder": None}  # type: ignore[attr-defined]

        def nowhere(start: object, title: str) -> Path:
            raise OSError("no dialog")

        app.state.desktop_folders_pick = nowhere  # type: ignore[attr-defined]
        r = world.post("/api/desktop/folders/pick", {})
        assert r.status_code == 501 and "Type the folder" in r.json()["detail"]  # type: ignore[attr-defined]
    finally:
        app.state.desktop_folders_pick = original  # type: ignore[attr-defined]
    assert world.client.post("/api/desktop/folders/pick", json={}).status_code == 401


def test_the_morning_is_four_lines_and_what_just_came_in(world: World) -> None:
    """The owner's morning: reports in? codes to confirm? bank checked? backed
    up? — each done or not, with where to go — and the last files read."""
    body = world.get("/api/desktop/morning").json()  # type: ignore[attr-defined]
    items = {i["id"]: i for i in body["items"]}
    assert list(items) == ["reports", "codes", "bank", "backup"]
    assert all(i["page"].startswith("/") for i in items.values())
    assert items["reports"]["state"] in ("attention", "todo")
    assert items["codes"]["state"] in ("done", "todo")
    assert items["bank"]["state"] == "todo" and "no statement" in items["bank"]["text"] or \
        items["bank"]["text"] == "No hotel set up yet."
    assert items["backup"]["state"] == "attention"
    assert isinstance(body["recent"], list)
    assert world.client.get("/api/desktop/morning").status_code == 401
