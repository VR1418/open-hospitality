"""The Backups page's API (PRD I-6, ADR-D4).

The promises: the owner chooses a folder their cloud drive syncs, the app
says when it last backed up and whether a backup could be opened anywhere
else, and the recovery code is CHECKED before it is used to wrap anything —
arming with a mistyped code would write backups nobody could open.
"""

import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from usali.db import make_engine, make_session_factory
from usali.desktop.accounts_api import SessionChecker
from usali.desktop.app import OWNER, build_app
from usali.desktop.backup import BackupConfig
from usali.desktop.bootstrap import DesktopKeys, app_url, prepare_database
from usali.desktop.identity import LocalIssuer
from usali.desktop.keystore import MemoryKeyStore, open_keys
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

PASSWORD = "harbour lights at dusk"


class World:
    def __init__(self, client: TestClient, paths: DesktopPaths, store: MemoryKeyStore,
                 headers: dict[str, str], recovery_code: str, root: Path) -> None:
        self.client = client
        self.paths = paths
        self.store = store
        self.headers = headers
        self.recovery_code = recovery_code
        self.root = root

    def status(self) -> dict:  # type: ignore[type-arg]
        r = self.client.get("/api/desktop/backup", headers=self.headers)
        assert r.status_code == 200, r.text
        return r.json()  # type: ignore[no-any-return]


@pytest.fixture(scope="module")
def world(tmp_path_factory: pytest.TempPathFactory) -> Iterator[World]:
    assert BIN is not None
    root = tmp_path_factory.mktemp("backupapi")
    paths = DesktopPaths(owner_root=root / "owner", system_root=root / "system")
    paths.ensure()
    store = MemoryKeyStore()
    # Sealed keys, as a real install has: arming wraps the key they hide.
    open_keys(sealed=paths.sealed_keys_file, legacy=paths.keys_file, store=store,
              database_exists=False)
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
        sessions = make_session_factory(engine)
        codes = LaunchCodes()
        app = build_app(
            paths, LocalIssuer.from_pem(keys.issuer_private_key_pem), codes, root / "no-portal",
            enabled=frozenset({"accounting"}), reload=lambda: None, sessions=sessions,
            checker=SessionChecker(sessions, ttl_seconds=0), store=store,
        )
        client = TestClient(app, base_url="http://127.0.0.1")
        owner = client.post("/api/desktop/setup/owner", json={
            "code": codes.issue(), "full_name": "Priya Owner", "email": "priya@example.com",
            "password": PASSWORD,
        })
        assert owner.status_code == 201, owner.text
        body = owner.json()
        yield World(client, paths, store, {"Authorization": f"Bearer {body['access_token']}"},
                    str(body["recovery_code"]), root)
        engine.dispose()
    finally:
        mp.undo()
        cluster.stop()


def test_creating_the_owner_arms_backups_without_being_asked(world: World) -> None:
    """The recovery code exists in the clear exactly once — at setup. That is
    when the backup key is wrapped under it (ADR-D4)."""
    assert world.paths.backup_wrap_file.is_file()
    status = world.status()
    assert status["armed"] is True
    # Nothing to back up TO yet, though.
    assert status["folder"] is None and status["files"] == []
    assert status["suggested_folder"].endswith("Backups")


def test_the_owner_chooses_a_folder_their_cloud_drive_syncs(world: World) -> None:
    folder = world.root / "OneDrive" / "Open Hospitality backups"
    r = world.client.put("/api/desktop/backup", json={"folder": str(folder)},
                         headers=world.headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert Path(body["folder"]) == folder.resolve()
    # Choosing one means a backup at the next start, without being asked.
    assert body["due"] is True
    assert folder.is_dir()  # made for them, and proven writable
    assert BackupConfig.load(world.paths.backup_config_file).folder == folder.resolve()


def test_the_books_own_folder_is_refused_with_a_reason(world: World) -> None:
    r = world.client.put("/api/desktop/backup",
                         json={"folder": str(world.paths.system_root / "copies")},
                         headers=world.headers)
    assert r.status_code == 422
    assert "somewhere else" in r.json()["detail"]
    # A relative path is refused too — "backups" could mean anywhere.
    assert world.client.put("/api/desktop/backup", json={"folder": "backups"},
                            headers=world.headers).status_code == 422


def test_a_mistyped_recovery_code_never_arms_a_backup(world: World) -> None:
    before = world.paths.backup_wrap_file.read_text()
    r = world.client.post("/api/desktop/backup/arm",
                          json={"recovery_code": "AAAAA-BBBBB-CCCCC-DDDDD-EEEEE"},
                          headers=world.headers)
    assert r.status_code == 401 and "doesn't match" in r.json()["detail"]
    # The wrap is untouched: a backup wrapped under a wrong code opens for
    # nobody, and the owner would not find out until they needed it.
    assert world.paths.backup_wrap_file.read_text() == before


def test_the_real_recovery_code_arms_it(world: World) -> None:
    r = world.client.post("/api/desktop/backup/arm",
                          json={"recovery_code": world.recovery_code.lower()},
                          headers=world.headers)
    assert r.status_code == 200 and r.json() == {"armed": True}
    wrap = json.loads(world.paths.backup_wrap_file.read_text())
    assert wrap["install_id"] and wrap["wrapped"] and wrap["salt"]


def test_back_up_now_says_plainly_when_it_will_happen(world: World) -> None:
    r = world.client.post("/api/desktop/backup/now", headers=world.headers)
    assert r.status_code == 200, r.text
    assert r.json()["requested"] is True
    assert "next time you start" in r.json()["detail"]
    assert BackupConfig.load(world.paths.backup_config_file).requested is True


def test_using_the_recovery_code_arms_the_new_one(world: World) -> None:
    """Recovery replaces the code; future backups must be wrapped under the
    new one, while files already written keep the wrap they were taken with."""
    before = json.loads(world.paths.backup_wrap_file.read_text())
    r = world.client.post("/api/desktop/recover", json={
        "login": "priya@example.com", "recovery_code": world.recovery_code,
        "new_password": "a different passphrase entirely",
    })
    assert r.status_code == 200, r.text
    after = json.loads(world.paths.backup_wrap_file.read_text())
    assert after["salt"] != before["salt"] and after["wrapped"] != before["wrapped"]
    world.recovery_code = str(r.json()["recovery_code"])
    world.headers = {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_nobody_signed_out_can_read_or_change_where_the_books_are_copied(world: World) -> None:
    assert world.client.get("/api/desktop/backup").status_code == 401
    assert world.client.put("/api/desktop/backup", json={"folder": "C:/anywhere"}).status_code == 401
    assert world.client.post("/api/desktop/backup/now").status_code == 401
