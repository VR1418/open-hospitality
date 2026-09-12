"""The owner's own AI helper, end to end (PRD §6.3, ADR-D7).

Runs against the real bundled cluster and the real keychain seam (a
`MemoryKeyStore`), through the offline mock provider — so no test needs a key
or a network, which is the point of having a mock adapter at all.

The promises under test: the key is never on the wire; the cap stops the
feature before the call, not after; every call is recorded whatever happened;
the model may decline; and nothing the model says reaches the books without a
person's click, which goes through the same endpoint their own choice does.
"""

from collections.abc import Iterator
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from usali.db import make_engine, make_session_factory
from usali.desktop.accounts_api import SessionChecker
from usali.desktop.app import OWNER, build_app
from usali.desktop.bootstrap import app_url, prepare_database
from usali.desktop.identity import LocalIssuer
from usali.desktop.keystore import MemoryKeyStore, open_keys
from usali.desktop.mapping_decisions import DecidingSessionFactory, decisions_for
from usali.desktop.paths import DesktopPaths
from usali.desktop.pg_runtime import PgCluster, PostgresNotFound, find_bin_dir, free_port
from usali.desktop.session_api import LaunchCodes
from usali.models import AuditEvent, IngestBatch, PmsDailyFinancialStage
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
SECRET = "sk-test-do-not-leak-9f3a2b"
HOTEL = {
    "name": "Willow Creek Inn", "report_name": "WILLOW CREEK INN", "pms_source": "skytouch",
    "total_rooms": 30, "timezone": "America/Chicago",
    "fiscal": {"calendar_type": "calendar_month", "fiscal_year_start_month": 1,
               "week_start_weekday": None},
}


class World:
    def __init__(self, client: TestClient, headers: dict[str, str], sessions: object,
                 store: MemoryKeyStore, without_ai: TestClient) -> None:
        self.client = client
        self.headers = headers
        self.sessions = sessions
        self.store = store
        #: The same install with the AI module off, which is what AI-8 is
        #: actually about: the routes are not mounted at all.
        self.without_ai = without_ai
        self.property_id = ""

    def get(self, path: str) -> object:
        return self.client.get(path, headers=self.headers)

    def put(self, path: str, body: object) -> object:
        return self.client.put(path, json=body, headers=self.headers)

    def post(self, path: str, body: object) -> object:
        return self.client.post(path, json=body, headers=self.headers)

    def stage(self, *, code: str, desc: str, amount: str = "120.0000",
              day: date = date(2026, 6, 1)) -> None:
        with self.sessions() as s:  # type: ignore[operator]
            batch = IngestBatch(
                pms_source=SOURCE, report_type="hotel_journal", source_file=f"{code}.pdf",
                file_hash=f"h-{code}", status="transformed", row_count=1,
            )
            s.add(batch)
            s.flush()
            s.add(PmsDailyFinancialStage(
                property_id=self.property_id, pms_source=SOURCE,
                report_type="hotel_journal", business_date=day, pms_trx_code=code,
                pms_trx_desc=desc, raw_amount=amount, room_count=1,
                source_file=f"{code}.pdf", ingest_batch_id=batch.batch_id,
                row_hash=f"{code}-{day}",
            ))
            s.commit()

    def calls(self) -> list[tuple[str, str, int]]:
        with self.sessions() as s:  # type: ignore[operator]
            return [
                (r.outcome, r.model, r.calls_seen)
                for r in s.execute(text(
                    "SELECT outcome, model, 1 AS calls_seen FROM desktop.ai_call"
                    " ORDER BY call_id"
                )).all()
            ]

    def use_mock(self, **over: object) -> object:
        body = {"provider": "mock", "model": "practice", "cap": "10.00", "max_calls": 500}
        body.update(over)
        return self.put("/api/desktop/ai", body)


@pytest.fixture(scope="module")
def world(tmp_path_factory: pytest.TempPathFactory) -> Iterator[World]:
    assert BIN is not None
    root = tmp_path_factory.mktemp("ai")
    paths = DesktopPaths(owner_root=root / "owner", system_root=root / "system")
    paths.ensure()
    store = MemoryKeyStore()
    # The real first-run path: keys generated, sealed, and the master key put
    # in the store — which is also what gives this install the id that names
    # the AI key's own keychain entry.
    keys = open_keys(
        sealed=paths.sealed_keys_file, legacy=paths.keys_file,
        store=store, database_exists=False,
    )
    cluster = PgCluster(bin_dir=BIN, data_dir=root / "database", log_file=root / "db.log")
    cluster.init(keys.db_owner_password)
    port = free_port(55442)
    cluster.start(port)
    mp = pytest.MonkeyPatch()
    try:
        prepare_database(port=port, keys=keys, resources=REPO, state_file=paths.state_file,
                         user=OWNER, allow_upgrade=False)
        mp.setenv("USALI_DB_URL", app_url(port, keys))
        engine = make_engine(app_url(port, keys))
        sessions = DecidingSessionFactory(make_session_factory(engine))
        codes = LaunchCodes()
        app = build_app(
            paths, LocalIssuer.from_pem(keys.issuer_private_key_pem), codes,
            root / "no-portal", enabled=frozenset({"accounting", "ai"}),
            reload=lambda: None, sessions=sessions,
            checker=SessionChecker(sessions, ttl_seconds=0), store=store,
        )
        off = build_app(
            paths, LocalIssuer.from_pem(keys.issuer_private_key_pem), codes,
            root / "no-portal", enabled=frozenset({"accounting"}),
            reload=lambda: None, sessions=sessions,
            checker=SessionChecker(sessions, ttl_seconds=0), store=store,
        )
        client = TestClient(app, base_url="http://127.0.0.1")
        owner = client.post("/api/desktop/setup/owner", json={
            "code": codes.issue(), "full_name": "Priya Owner", "email": "priya@example.com",
            "password": "harbour lights at dusk",
        })
        assert owner.status_code == 201, owner.text
        headers = {"Authorization": f"Bearer {owner.json()['access_token']}"}
        w = World(
            client, headers, OrgBoundSessionFactory(sessions, FOUNDING_ORG_ID), store,
            TestClient(off, base_url="http://127.0.0.1"),
        )
        made = client.post("/api/desktop/welcome/property", json=HOTEL, headers=headers)
        assert made.status_code == 201, made.text
        w.property_id = made.json()["property_id"]
        yield w
        engine.dispose()
    finally:
        mp.undo()
        cluster.stop()


def test_nobody_signed_out_can_read_or_change_it(world: World) -> None:
    assert world.client.get("/api/desktop/ai").status_code == 401
    assert world.client.put("/api/desktop/ai", json={}).status_code == 401
    assert world.client.post("/api/desktop/ai/suggest", json={}).status_code == 401


def test_before_it_is_set_up_it_says_so_and_has_spent_nothing(world: World) -> None:
    body = world.get("/api/desktop/ai").json()  # type: ignore[attr-defined]
    assert body["provider"] is None and body["key_saved"] is False
    assert body["spend"]["calls"] == 0 and body["spend"]["stopped"] is False
    # PRD AI-2's default, before anyone has chosen anything.
    assert body["cap"] == "10.00"
    assert {p["id"] for p in body["providers"]} == {"openai_compatible", "anthropic", "mock"}


def test_asking_before_it_is_set_up_is_refused_in_words(world: World) -> None:
    r = world.post("/api/desktop/ai/suggest", {
        "property_id": world.property_id, "pms_source": SOURCE, "code": "ZZQ",
    })
    assert r.status_code == 409  # type: ignore[attr-defined]
    assert "AI settings" in r.json()["detail"]  # type: ignore[attr-defined]


def test_a_helper_we_cannot_talk_to_is_refused(world: World) -> None:
    r = world.put("/api/desktop/ai", {"provider": "some-startup", "model": "x"})
    assert r.status_code == 422  # type: ignore[attr-defined]


def test_an_openai_shaped_helper_needs_its_address(world: World) -> None:
    """The base URL IS the configuration for that adapter — without it there
    is nothing to distinguish OpenRouter from a local Ollama."""
    r = world.put("/api/desktop/ai", {"provider": "openai_compatible", "model": "x"})
    assert r.status_code == 422 and "web address" in r.json()["detail"]  # type: ignore[attr-defined]


def test_a_limit_of_nothing_is_refused(world: World) -> None:
    r = world.put("/api/desktop/ai", {"provider": "mock", "model": "practice", "cap": "0"})
    assert r.status_code == 422  # type: ignore[attr-defined]


def test_the_key_is_never_on_the_wire(world: World) -> None:
    """The `integrations_api` guard, applied here: grep the WHOLE body."""
    saved = world.put("/api/desktop/ai", {
        "provider": "anthropic", "model": "claude-test", "cap": "10.00", "key": SECRET,
    })
    assert saved.status_code == 200, saved.text  # type: ignore[attr-defined]
    assert saved.json()["key_saved"] is True  # type: ignore[attr-defined]
    for body in (saved.text, world.client.get(  # type: ignore[attr-defined]
        "/api/desktop/ai", headers=world.headers
    ).text):
        assert SECRET not in body

    # It is in the keychain, under this install's own entry — and nowhere in
    # the database (AI-1).
    assert SECRET in world.store.entries.values()
    with world.sessions() as s:  # type: ignore[operator]
        stored = s.execute(
            text("SELECT value::text FROM desktop.setting WHERE key = 'ai'")
        ).scalar_one()
    assert SECRET not in stored


def test_the_owner_can_make_it_forget_the_key(world: World) -> None:
    assert world.client.delete(
        "/api/desktop/ai/key", headers=world.headers
    ).status_code == 204
    assert world.get("/api/desktop/ai").json()["key_saved"] is False  # type: ignore[attr-defined]
    assert SECRET not in world.store.entries.values()


def test_a_suggestion_names_a_line_and_is_recorded(world: World) -> None:
    world.use_mock()
    world.stage(code="CBN", desc="Cabana Rental")
    r = world.post("/api/desktop/ai/suggest", {
        "property_id": world.property_id, "pms_source": SOURCE, "code": "CBN",
    })
    assert r.status_code == 200, r.text  # type: ignore[attr-defined]
    out = r.json()  # type: ignore[attr-defined]
    assert out["line"] is not None and out["line"]["line_item"]
    assert out["decline_reason"] is None
    assert out["spend"]["calls"] >= 1

    # AI-5: the detailed row, and the org trail, both written.
    assert ("answered", "practice", 1) in world.calls()
    with world.sessions() as s:  # type: ignore[operator]
        actions = [e.action for e in s.query(AuditEvent).all()]
    assert "ai_suggestion_answered" in actions


def test_it_refuses_to_guess_on_tax(world: World) -> None:
    """AI-7: on tax and capitalisation it must decline rather than guess, and
    a decline without a reason is not an answer (the port refuses one)."""
    world.use_mock()
    world.stage(code="OCTAX", desc="Occupancy tax collected")
    out = world.post("/api/desktop/ai/suggest", {
        "property_id": world.property_id, "pms_source": SOURCE, "code": "OCTAX",
    }).json()  # type: ignore[attr-defined]
    assert out["line"] is None
    assert "tax" in out["decline_reason"].lower()
    assert ("declined", "practice", 1) in world.calls()


def test_a_code_that_never_appeared_is_a_404(world: World) -> None:
    world.use_mock()
    r = world.post("/api/desktop/ai/suggest", {
        "property_id": world.property_id, "pms_source": SOURCE, "code": "NEVER",
    })
    assert r.status_code == 404  # type: ignore[attr-defined]


def test_the_cap_stops_it_and_says_which_half(world: World) -> None:
    """AI-2: at the cap the feature stops and says so. Checked BEFORE the
    call, so there is no path to a surprise bill."""
    already = len(world.calls())
    world.use_mock(max_calls=already)
    world.stage(code="KAYAK", desc="Kayak hire")
    r = world.post("/api/desktop/ai/suggest", {
        "property_id": world.property_id, "pms_source": SOURCE, "code": "KAYAK",
    })
    assert r.status_code == 429  # type: ignore[attr-defined]
    assert "start again on the 1st" in r.json()["detail"]  # type: ignore[attr-defined]
    # Refused before the call: nothing new was recorded.
    assert len(world.calls()) == already
    world.use_mock()


def test_accepting_a_suggestion_is_the_owners_click_and_carries_their_name(
    world: World,
) -> None:
    """AI-6. There is no apply endpoint on the AI router: accepting goes
    through the same endpoint the owner's own choice goes through."""
    world.use_mock()
    world.stage(code="PADDLE", desc="Paddleboard hire")
    suggested = world.post("/api/desktop/ai/suggest", {
        "property_id": world.property_id, "pms_source": SOURCE, "code": "PADDLE",
    }).json()  # type: ignore[attr-defined]

    applied = world.put("/api/desktop/codes/PADDLE", {
        "property_id": world.property_id, "pms_source": SOURCE,
        "line": suggested["line"], "origin": "ai-accepted",
    })
    assert applied.status_code == 200, applied.text  # type: ignore[attr-defined]

    with world.sessions() as s:  # type: ignore[operator]
        [decision] = [
            d for d in decisions_for(s, property_id=world.property_id)
            if d.pms_trx_code == "PADDLE"
        ]
    assert decision.origin == "ai-accepted"
    # A person's subject, never the model's name.
    assert decision.decided_by and decision.decided_by != "practice"


def test_with_the_module_off_the_routes_do_not_exist(world: World) -> None:
    """AI-8, as ADR-D3 means it: a module that is off is not mounted, so
    "with AI disabled every feature still works" is true by construction
    rather than by a flag somewhere that could be read wrong."""
    for path, call in (
        ("/api/desktop/ai", world.without_ai.get),
        ("/api/desktop/ai/suggest", world.without_ai.post),
    ):
        assert call(path, headers=world.headers).status_code == 404, path
    # And the manual path is untouched: the codes queue still answers.
    still = world.without_ai.get(
        f"/api/desktop/codes?property={world.property_id}", headers=world.headers
    )
    assert still.status_code == 200
