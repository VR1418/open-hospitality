"""The schedule made easy: starter shifts, "until done", editing, copying a week.

On the real bundled cluster, through the desktop app with Payroll & People on.
"""

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from usali.db import make_engine, make_session_factory
from usali.desktop.accounts_api import SessionChecker
from usali.desktop.app import OWNER, build_app
from usali.desktop.bootstrap import DesktopKeys, app_url, prepare_database
from usali.desktop.identity import LocalIssuer
from usali.desktop.paths import DesktopPaths
from usali.desktop.pg_runtime import PgCluster, PostgresNotFound, find_bin_dir, free_port
from usali.desktop.session_api import LaunchCodes

REPO = Path(__file__).resolve().parents[1]
try:
    BIN: Path | None = find_bin_dir(REPO)
except PostgresNotFound:
    BIN = None

pytestmark = pytest.mark.skipif(
    BIN is None, reason="bundled Postgres not fetched (scripts/desktop/fetch_postgres.py)"
)

# Mondays on the payroll grid (anchor 2026-01-05).
WEEK, NEXT = "2026-09-14", "2026-09-21"


class World:
    def __init__(self, client: TestClient, headers: dict[str, str]) -> None:
        self.client, self.headers = client, headers
        self.hotel = ""
        self.people: dict[str, int] = {}

    def get(self, path: str) -> object:
        return self.client.get(path, headers=self.headers)

    def post(self, path: str, body: object = None) -> object:
        return self.client.post(path, json=body, headers=self.headers)

    def put(self, path: str, body: object) -> object:
        return self.client.put(path, json=body, headers=self.headers)


@pytest.fixture(scope="module")
def world(tmp_path_factory: pytest.TempPathFactory) -> Iterator[World]:
    assert BIN is not None
    root = tmp_path_factory.mktemp("rota")
    keys = DesktopKeys.generate()
    cluster = PgCluster(bin_dir=BIN, data_dir=root / "database", log_file=root / "db.log")
    cluster.init(keys.db_owner_password)
    port = free_port(55444)
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
            enabled=frozenset({"accounting", "payroll"}), reload=lambda: None,
            sessions=sessions, checker=SessionChecker(sessions, ttl_seconds=0),
        )
        client = TestClient(app, base_url="http://127.0.0.1")
        owner = client.post("/api/desktop/setup/owner", json={
            "code": codes.issue(), "full_name": "Priya Owner", "email": "priya@example.com",
            "password": "harbour lights at dusk",
        })
        assert owner.status_code == 201, owner.text
        w = World(client, {"Authorization": f"Bearer {owner.json()['access_token']}"})
        made = w.post("/api/desktop/welcome/property", {
            "ownership_entity": "Redstone Hospitality LLC", "name": "Redstone Lodge",
            "code": "TX901", "pms_source": "SKYTOUCH", "timezone": "America/Chicago",
            "fiscal": {"calendar_type": "calendar_month", "fiscal_year_start_month": 1,
                       "week_start_weekday": None},
        })
        assert made.status_code == 201, made.text
        w.hotel = made.json()["property_id"]
        for name in ("Ana Desk", "Ben Desk", "Cora Rooms"):
            r = w.post("/api/employees", {"full_name": name, "property": w.hotel,
                                          "pay_type": "hourly"})
            assert r.status_code == 201, r.text
            w.people[name] = r.json()["employee_id"]
        yield w
        engine.dispose()
    finally:
        mp.undo()
        cluster.stop()


def test_a_new_hotel_comes_with_the_standard_shifts(world: World) -> None:
    shifts = world.get(f"/api/desktop/rota/templates?property={world.hotel}").json()  # type: ignore[attr-defined]
    names = {s["name"]: s for s in shifts}
    assert {"Morning desk", "Evening desk", "Night audit", "Housekeeping", "Breakfast",
            "Maintenance", "Laundry"} <= set(names)
    assert names["Night audit"]["crosses_midnight"] is True
    assert names["Housekeeping"]["until_done"] is True and names["Morning desk"]["until_done"] is False
    depts = {d["name"] for d in world.get(f"/api/departments?property={world.hotel}").json()}  # type: ignore[attr-defined]
    assert {"Front desk", "Housekeeping", "Breakfast", "Maintenance"} <= depts
    # Asking for them again adds nothing.
    again = world.post(f"/api/desktop/rota/starter?property={world.hotel}").json()  # type: ignore[attr-defined]
    assert again == {"departments_added": 0, "shifts_added": 0}


def test_the_owner_makes_and_changes_their_own_shift(world: World) -> None:
    depts = {d["name"]: d["department_id"]
             for d in world.get(f"/api/departments?property={world.hotel}").json()}  # type: ignore[attr-defined]
    made = world.post("/api/desktop/rota/templates", {
        "property": world.hotel, "department_id": depts["Front desk"], "name": "Mid shift",
        "start_time": "11:00", "end_time": "19:00",
    })
    assert made.status_code == 201, made.text  # type: ignore[attr-defined]
    tid = made.json()["template_id"]  # type: ignore[attr-defined]

    twice = world.post("/api/desktop/rota/templates", {
        "property": world.hotel, "department_id": depts["Front desk"], "name": "mid   shift",
        "start_time": "11:00", "end_time": "19:00",
    })
    assert twice.status_code == 409  # type: ignore[attr-defined]
    backwards = world.post("/api/desktop/rota/templates", {
        "property": world.hotel, "department_id": depts["Front desk"], "name": "Backwards",
        "start_time": "15:00", "end_time": "07:00",
    })
    assert backwards.status_code == 422 and "past midnight" in backwards.json()["detail"]  # type: ignore[attr-defined]

    changed = world.put(f"/api/desktop/rota/templates/{tid}", {
        "department_id": depts["Housekeeping"], "name": "Deep clean",
        "start_time": "10:00", "end_time": "14:00", "until_done": True,
    })
    assert changed.status_code == 200, changed.text  # type: ignore[attr-defined]
    assert changed.json()["until_done"] is True and changed.json()["name"] == "Deep clean"  # type: ignore[attr-defined]
    listed = {s["template_id"]: s
              for s in world.get(f"/api/desktop/rota/templates?property={world.hotel}").json()}  # type: ignore[attr-defined]
    assert listed[tid]["start_time"] == "10:00" and listed[tid]["until_done"] is True


def _shift(world: World, schedule_id: int, day: str, template: dict[str, object],
           who: int | None) -> dict[str, object]:
    r = world.post(f"/api/schedule/weeks/{schedule_id}/shifts", {
        "business_date": day, "department_id": template["department_id"],
        "start_time": template["start_time"], "end_time": template["end_time"],
        "crosses_midnight": template["crosses_midnight"], "employee_id": who,
        "template_id": template["template_id"],
    })
    assert r.status_code == 201, r.text  # type: ignore[attr-defined]
    return r.json()  # type: ignore[no-any-return]


def test_a_week_is_copied_to_the_next_with_the_same_people(world: World) -> None:
    by_name = {s["name"]: s
               for s in world.get(f"/api/desktop/rota/templates?property={world.hotel}").json()}  # type: ignore[attr-defined]
    week = world.post("/api/schedule/weeks", {"property": world.hotel, "week_start": WEEK})
    assert week.status_code == 201, week.text  # type: ignore[attr-defined]
    sid = week.json()["schedule_id"]  # type: ignore[attr-defined]
    ana, ben, cora = (world.people[n] for n in ("Ana Desk", "Ben Desk", "Cora Rooms"))
    _shift(world, sid, "2026-09-14", by_name["Morning desk"], ana)
    _shift(world, sid, "2026-09-14", by_name["Evening desk"], ben)
    _shift(world, sid, "2026-09-14", by_name["Housekeeping"], cora)
    _shift(world, sid, "2026-09-15", by_name["Night audit"], None)  # open

    # Ben is already booked on the target week's Monday evening.
    target = world.post("/api/schedule/weeks", {"property": world.hotel, "week_start": NEXT})
    assert target.status_code == 201  # type: ignore[attr-defined]
    _shift(world, target.json()["schedule_id"], "2026-09-21", by_name["Evening desk"], ben)  # type: ignore[attr-defined]

    copied = world.post("/api/desktop/rota/copy", {
        "property": world.hotel, "from_week_start": WEEK, "to_week_start": NEXT,
    })
    assert copied.status_code == 201, copied.text  # type: ignore[attr-defined]
    out = copied.json()  # type: ignore[attr-defined]
    # Four shifts copied; Ben's landed OPEN rather than double-booking him.
    assert (out["copied"], out["left_open"], out["skipped"]) == (4, 1, 0)

    shifts = world.get(f"/api/schedule/weeks?property={world.hotel}&week_start={NEXT}").json()["shifts"]  # type: ignore[attr-defined]
    assert len(shifts) == 5  # the one already there, plus four
    monday = sorted(((s["start_time"], s["employee_id"]) for s in shifts
                     if s["business_date"] == "2026-09-21"),
                    key=lambda t: (t[0], t[1] or -1))
    assert monday == [("07:00", ana), ("09:00", cora), ("15:00", None), ("15:00", ben)]
    [night] = [s for s in shifts if s["business_date"] == "2026-09-22"]
    assert night["employee_id"] is None and night["crosses_midnight"] is True
    assert night["template_id"] == by_name["Night audit"]["template_id"]  # provenance kept


def test_copying_without_people_gives_the_same_coverage_with_nobody_on_it(world: World) -> None:
    later = "2026-09-28"
    out = world.post("/api/desktop/rota/copy", {
        "property": world.hotel, "from_week_start": WEEK, "to_week_start": later,
        "keep_people": False,
    }).json()  # type: ignore[attr-defined]
    assert out["copied"] == 4 and out["left_open"] == 0
    shifts = world.get(f"/api/schedule/weeks?property={world.hotel}&week_start={later}").json()["shifts"]  # type: ignore[attr-defined]
    assert all(s["employee_id"] is None for s in shifts)


def test_someone_who_has_left_is_left_open_on_the_copy(world: World) -> None:
    gone = world.post(f"/api/employees/{world.people['Cora Rooms']}/terminate")
    assert gone.status_code == 200, gone.text  # type: ignore[attr-defined]
    out = world.post("/api/desktop/rota/copy", {
        "property": world.hotel, "from_week_start": WEEK, "to_week_start": "2026-10-05",
    }).json()  # type: ignore[attr-defined]
    assert out["copied"] == 4 and out["left_open"] == 1


def test_copying_refuses_what_makes_no_sense(world: World) -> None:
    same = world.post("/api/desktop/rota/copy", {
        "property": world.hotel, "from_week_start": WEEK, "to_week_start": WEEK,
    })
    assert same.status_code == 422  # type: ignore[attr-defined]
    off_grid = world.post("/api/desktop/rota/copy", {
        "property": world.hotel, "from_week_start": WEEK, "to_week_start": "2026-09-23",
    })
    assert off_grid.status_code == 422  # type: ignore[attr-defined]
    empty = world.post("/api/desktop/rota/copy", {
        "property": world.hotel, "from_week_start": "2026-01-05", "to_week_start": NEXT,
    })
    assert empty.status_code == 404  # type: ignore[attr-defined]
    assert world.client.get(f"/api/desktop/rota/templates?property={world.hotel}").status_code == 401
