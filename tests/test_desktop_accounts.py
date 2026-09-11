"""Local accounts end to end on the bundled Postgres (PRD A-1 to A-7).

Built with the launcher's own `build_app`, so the wiring under test is the
wiring that ships: upstream's create_app, the session-checked verifier, the
Keycloak seam over local accounts, and every desktop router.
"""

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from usali.db import make_engine, make_session_factory
from usali.desktop import accounts as acct
from usali.desktop.accounts_api import OWNER_SUBJECT, SessionChecker
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

PASSWORD = "harbour lights at dusk"


class World:
    def __init__(self, client: TestClient, codes: LaunchCodes, sessions: acct.SessionFactory):
        self.client = client
        self.codes = codes
        self.sessions = sessions

    def setup_owner(self, password: str = PASSWORD) -> dict[str, object]:
        r = self.client.post("/api/desktop/setup/owner", json={
            "code": self.codes.issue(), "full_name": "Priya Owner",
            "email": "priya@example.com", "password": password, "device_label": "Laptop",
        })
        assert r.status_code == 201, r.text
        body: dict[str, object] = r.json()
        return body

    def sign_in(self, login: str, password: str, device: str = "Laptop") -> object:
        return self.client.post("/api/desktop/signin", json={
            "login": login, "password": password, "device_label": device,
        })


def bearer(token: object) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="module")
def world(tmp_path_factory: pytest.TempPathFactory) -> Iterator[World]:
    assert BIN is not None
    root = tmp_path_factory.mktemp("accounts")
    keys = DesktopKeys.generate()
    cluster = PgCluster(bin_dir=BIN, data_dir=root / "database", log_file=root / "db.log")
    cluster.init(keys.db_owner_password)
    port = free_port(55434)
    cluster.start(port)
    mp = pytest.MonkeyPatch()
    try:
        prepare_database(port=port, keys=keys, resources=REPO, state_file=root / "state.json",
                         user=OWNER, allow_upgrade=False)
        # create_app's default session factory reads the serving URL from env,
        # exactly as it does under the launcher.
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
        yield World(TestClient(app, base_url="http://127.0.0.1"), codes, sessions)
        engine.dispose()
    finally:
        mp.undo()
        cluster.stop()


def test_a_new_install_asks_for_an_owner(world: World) -> None:
    assert world.client.get("/api/desktop/status").json() == {"setup_required": True}


def test_owner_setup_refuses_a_breached_password_without_spending_the_code(world: World) -> None:
    code = world.codes.issue()
    r = world.client.post("/api/desktop/setup/owner", json={
        "code": code, "full_name": "Priya Owner", "email": "priya@example.com",
        "password": "password123",
    })
    assert r.status_code == 422 and "stolen" in r.json()["detail"]
    assert world.codes.redeem(code) is True  # still good for the real attempt


def test_owner_setup_needs_the_trays_launch_code(world: World) -> None:
    r = world.client.post("/api/desktop/setup/owner", json={
        "code": "not-from-the-tray", "full_name": "Mallory", "email": "m@example.com",
        "password": PASSWORD,
    })
    assert r.status_code == 401 and "icon" in r.json()["detail"]


def test_the_owner_is_created_once_signed_in_and_given_a_recovery_code(world: World) -> None:
    body = world.setup_owner()
    assert isinstance(body["recovery_code"], str) and len(str(body["recovery_code"])) == 29
    me = world.client.get("/api/me", headers=bearer(body["access_token"]))
    assert me.status_code == 200 and me.json()["subject"] == OWNER_SUBJECT
    assert world.client.get("/api/desktop/status").json() == {"setup_required": False}
    again = world.client.post("/api/desktop/setup/owner", json={
        "code": world.codes.issue(), "full_name": "Second", "email": "s@example.com",
        "password": PASSWORD,
    })
    assert again.status_code == 409


def test_sign_in_never_says_which_half_was_wrong(world: World) -> None:
    wrong_password = world.sign_in("priya@example.com", "not the password at all")
    no_such_person = world.sign_in("nobody@example.com", PASSWORD)
    assert wrong_password.status_code == no_such_person.status_code == 401  # type: ignore[attr-defined]
    assert wrong_password.json() == no_such_person.json()  # type: ignore[attr-defined]


def test_signing_out_a_device_ends_that_token_at_once(world: World) -> None:
    laptop = world.sign_in("PRIYA@example.com", PASSWORD, "Laptop").json()  # type: ignore[attr-defined]
    phone = world.sign_in("priya@example.com", PASSWORD, "Front-desk PC").json()  # type: ignore[attr-defined]
    listed = world.client.get("/api/desktop/sessions", headers=bearer(laptop["access_token"])).json()
    other = next(s for s in listed if s["device_label"] == "Front-desk PC")
    assert next(s for s in listed if s["current"])["device_label"] == "Laptop"

    gone = world.client.delete(f"/api/desktop/sessions/{other['session_id']}",
                               headers=bearer(laptop["access_token"]))
    assert gone.status_code == 204
    assert world.client.get("/api/me", headers=bearer(phone["access_token"])).status_code == 401
    assert world.client.get("/api/me", headers=bearer(laptop["access_token"])).status_code == 200


def test_ten_wrong_passwords_lock_the_account_but_the_recovery_code_still_works(
    world: World,
) -> None:
    with world.sessions() as s:
        acct.clear_failures(s, OWNER_SUBJECT)
        recovery = "ABCDE-FGHJK-MNPQR-STVWX-YZ012"
        acct.set_recovery_code(s, OWNER_SUBJECT, recovery)
        s.commit()
    for _ in range(acct.MAX_FAILURES):
        world.sign_in("priya@example.com", "definitely wrong password")
    locked = world.sign_in("priya@example.com", PASSWORD)
    assert locked.status_code == 429 and "15 minutes" in locked.json()["detail"]  # type: ignore[attr-defined]

    old_token = world.sign_in  # noqa: F841 — nothing signed in survives recovery (below)
    recovered = world.client.post("/api/desktop/recover", json={
        "login": "priya@example.com", "recovery_code": recovery.lower().replace("-", " "),
        "new_password": "new tide over the pier",
    })
    assert recovered.status_code == 200, recovered.text
    fresh = recovered.json()
    assert fresh["recovery_code"] and fresh["recovery_code"] != recovery  # spent, replaced
    assert world.sign_in("priya@example.com", "new tide over the pier").status_code == 200  # type: ignore[attr-defined]
    reused = world.client.post("/api/desktop/recover", json={
        "login": "priya@example.com", "recovery_code": recovery, "new_password": PASSWORD,
    })
    assert reused.status_code == 401


def test_a_new_person_sets_their_password_with_the_owners_setup_code(world: World) -> None:
    owner = world.sign_in("priya@example.com", "new tide over the pier").json()  # type: ignore[attr-defined]
    admin = LocalAdminFor(world)
    subject = admin.create_user(
        username="sam", email="sam@example.com", full_name="Sam Bookkeeper",
        realm_roles=["accountant"],
    )
    people = world.client.get("/api/desktop/accounts", headers=bearer(owner["access_token"])).json()
    sam = next(p for p in people if p["subject"] == subject)
    assert sam["has_password"] is False

    # A person with no password cannot sign in, whatever they type.
    assert world.sign_in("sam", "anything they like here").status_code == 401  # type: ignore[attr-defined]

    code = world.client.post(f"/api/desktop/accounts/{subject}/setup-code",
                             headers=bearer(owner["access_token"])).json()["setup_code"]
    redeemed = world.client.post("/api/desktop/setup-code", json={
        "login": "sam@example.com", "code": code.lower(), "new_password": "ledger by lamplight",
    })
    assert redeemed.status_code == 200, redeemed.text
    assert world.sign_in("sam", "ledger by lamplight").status_code == 200  # type: ignore[attr-defined]
    # Spent: the same code can't set a second password.
    assert world.client.post("/api/desktop/setup-code", json={
        "login": "sam", "code": code, "new_password": "another good phrase",
    }).status_code == 401

    # Upstream's termination path disables the login through the same seam.
    token = world.sign_in("sam", "ledger by lamplight").json()["access_token"]  # type: ignore[attr-defined]
    admin.disable_user(subject)
    assert world.client.get("/api/desktop/sessions", headers=bearer(token)).status_code == 401
    assert world.sign_in("sam", "ledger by lamplight").status_code == 401  # type: ignore[attr-defined]


def test_the_owner_cannot_hand_themselves_a_setup_code(world: World) -> None:
    owner = world.sign_in("priya@example.com", "new tide over the pier").json()  # type: ignore[attr-defined]
    r = world.client.post(f"/api/desktop/accounts/{OWNER_SUBJECT}/setup-code",
                          headers=bearer(owner["access_token"]))
    assert r.status_code == 409 and "recovery code" in r.json()["detail"]


def LocalAdminFor(world: World) -> acct.LocalAccountAdmin:  # noqa: N802 — reads as a type
    return acct.LocalAccountAdmin(world.sessions, org_alias=OWNER.org_alias)
