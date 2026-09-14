"""Reports by email, through the app on the real bundled cluster, with a
stand-in mailbox so no test touches a network."""

from collections.abc import Iterable, Iterator
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from usali.db import make_engine, make_session_factory
from usali.desktop import mail
from usali.desktop.accounts_api import SessionChecker
from usali.desktop.app import OWNER, build_app
from usali.desktop.bootstrap import DesktopKeys, app_url, prepare_database
from usali.desktop.identity import LocalIssuer
from usali.desktop.keystore import MemoryKeyStore
from usali.desktop.paths import DesktopPaths
from usali.desktop.pg_runtime import PgCluster, PostgresNotFound, find_bin_dir, free_port
from usali.desktop.session_api import LaunchCodes
from usali.tenancy import FOUNDING_ORG_ID, OrgBoundSessionFactory

REPO = Path(__file__).resolve().parents[1]
try:
    BIN: Path | None = find_bin_dir(REPO)
except PostgresNotFound:
    BIN = None

pytestmark = pytest.mark.skipif(
    BIN is None, reason="bundled Postgres not fetched (scripts/desktop/fetch_postgres.py)"
)
PDF = b"%PDF-1.4\n%mock\n"


class MockMailbox:
    def __init__(self, password: str | None) -> None:
        self.password = password
        self.all = [
            mail.Message(5, "audit@pms.example.com", "Night audit", None,
                         (mail.Attachment("audit-2026-09-13.pdf", PDF),)),
            mail.Message(6, "spam@example.com", "Great offer", None,
                         (mail.Attachment("offer.pdf", PDF),)),
        ]

    def _check(self) -> None:
        if self.password != "app-password-123":
            raise mail.MailboxError("The mail service refused the sign-in.")

    def messages(self, *, after_uid: int, since: date) -> list[mail.Message]:
        self._check()
        return [m for m in self.all if m.uid > after_uid]

    def messages_by_uid(self, uids: Iterable[int]) -> list[mail.Message]:
        self._check()
        wanted = set(uids)
        return [m for m in self.all if m.uid in wanted]

    def probe(self, *, since: date) -> int:
        self._check()
        return len(self.all)


class World:
    def __init__(self, client: TestClient, headers: dict[str, str], drop: Path,
                 store: MemoryKeyStore) -> None:
        self.client, self.headers, self.drop, self.store = client, headers, drop, store

    def get(self, path: str) -> object:
        return self.client.get(path, headers=self.headers)

    def post(self, path: str, body: object = None) -> object:
        return self.client.post(path, json=body, headers=self.headers)

    def put(self, path: str, body: object) -> object:
        return self.client.put(path, json=body, headers=self.headers)


@pytest.fixture(scope="module")
def world(tmp_path_factory: pytest.TempPathFactory) -> Iterator[World]:
    assert BIN is not None
    root = tmp_path_factory.mktemp("mail")
    keys = DesktopKeys.generate()
    cluster = PgCluster(bin_dir=BIN, data_dir=root / "database", log_file=root / "db.log")
    cluster.init(keys.db_owner_password)
    port = free_port(55445)
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
        store = MemoryKeyStore()
        paths.sealed_keys_file.write_text('{"install_id": "mailtest"}', encoding="utf-8")
        intake = mail.MailIntake(
            OrgBoundSessionFactory(sessions, FOUNDING_ORG_ID), paths.drop_folder,
            store=store, sealed=paths.sealed_keys_file,
            mailbox_for=lambda settings, password: MockMailbox(password),
        )
        app = build_app(
            paths, LocalIssuer.from_pem(keys.issuer_private_key_pem), codes, root / "no-portal",
            enabled=frozenset({"accounting"}), reload=lambda: None,
            sessions=sessions, checker=SessionChecker(sessions, ttl_seconds=0),
            store=store, mail_intake=intake,
        )
        client = TestClient(app, base_url="http://127.0.0.1")
        owner = client.post("/api/desktop/setup/owner", json={
            "code": codes.issue(), "full_name": "Priya Owner", "email": "priya@example.com",
            "password": "harbour lights at dusk",
        })
        assert owner.status_code == 201, owner.text
        yield World(client, {"Authorization": f"Bearer {owner.json()['access_token']}"},
                    paths.drop_folder, store)
        engine.dispose()
    finally:
        mp.undo()
        cluster.stop()


def test_before_setup_it_says_so_and_offers_the_services(world: World) -> None:
    body = world.get("/api/desktop/mail").json()  # type: ignore[attr-defined]
    assert body["enabled"] is False and body["password_saved"] is False
    assert [p["id"] for p in body["presets"]][0] == "gmail"
    assert body["status"]["last_run_at"] is None
    assert world.client.get("/api/desktop/mail").status_code == 401


def test_saving_picks_the_servers_address_and_keeps_the_password_off_the_wire(world: World) -> None:
    r = world.put("/api/desktop/mail", {
        "enabled": True, "preset": "gmail", "username": "reports@example.com",
        "mode": "daily", "at": "6:30", "password": "app-password-123",
    })
    assert r.status_code == 200, r.text  # type: ignore[attr-defined]
    body = r.json()  # type: ignore[attr-defined]
    assert body["host"] == "imap.gmail.com" and body["port"] == 993
    assert body["at"] == "06:30" and body["password_saved"] is True
    assert body["status"]["next_run_at"] is not None
    assert "app-password-123" not in r.text  # type: ignore[attr-defined]
    assert world.store.get("mail-password:mailtest") == "app-password-123"

    bad = world.put("/api/desktop/mail", {"enabled": True, "preset": "gmail", "username": ""})
    assert bad.status_code == 422  # type: ignore[attr-defined]
    odd = world.put("/api/desktop/mail", {"preset": "gmail", "username": "x@y.com", "at": "25:00"})
    assert odd.status_code == 422  # type: ignore[attr-defined]


def test_the_connection_check_takes_nothing(world: World) -> None:
    r = world.post("/api/desktop/mail/test")
    assert r.status_code == 200 and r.json()["messages_seen"] == 2  # type: ignore[attr-defined]
    assert not any(world.drop.glob("*.pdf"))


def test_the_first_look_holds_unknown_senders_and_allowing_one_brings_it_in(world: World) -> None:
    first = world.post("/api/desktop/mail/fetch").json()  # type: ignore[attr-defined]
    assert first["fetched"] == 0 and first["held_senders"] == 2
    status = world.get("/api/desktop/mail").json()["status"]  # type: ignore[attr-defined]
    assert {h["sender"] for h in status["held"]} == {"audit@pms.example.com", "spam@example.com"}
    assert not any(world.drop.glob("*.pdf"))

    allowed = world.post("/api/desktop/mail/allow", {"sender": "Audit@PMS.example.com"}).json()  # type: ignore[attr-defined]
    assert allowed["fetched"] == 1 and allowed["files"] == ["audit-2026-09-13.pdf"]
    assert (world.drop / "audit-2026-09-13.pdf").read_bytes() == PDF
    after = world.get("/api/desktop/mail").json()  # type: ignore[attr-defined]
    assert after["senders"] == ["audit@pms.example.com"]
    assert [h["sender"] for h in after["status"]["held"]] == ["spam@example.com"]
    assert after["status"]["fetched"] == ["audit-2026-09-13.pdf"]

    # Looking again takes nothing twice.
    again = world.post("/api/desktop/mail/fetch").json()  # type: ignore[attr-defined]
    assert again["fetched"] == 0


def test_a_wrong_password_is_said_plainly_and_recorded(world: World) -> None:
    world.put("/api/desktop/mail", {
        "enabled": True, "preset": "gmail", "username": "reports@example.com",
        "senders": ["audit@pms.example.com"], "password": "wrong",
    })
    r = world.post("/api/desktop/mail/fetch")
    assert r.status_code == 502 and "refused the sign-in" in r.json()["detail"]  # type: ignore[attr-defined]
    assert "wrong" not in r.text  # type: ignore[attr-defined]
    assert "refused" in world.get("/api/desktop/mail").json()["status"]["last_error"]  # type: ignore[attr-defined]
    assert world.client.delete("/api/desktop/mail/password", headers=world.headers).status_code == 204
    assert world.get("/api/desktop/mail").json()["password_saved"] is False  # type: ignore[attr-defined]
