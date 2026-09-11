"""The bundled Postgres, end to end: create, start, migrate, seed, serve-role walls.

Runs only where the binaries have been fetched
(`uv run python scripts/desktop/fetch_postgres.py`); no Docker involved.
"""

import time
from collections.abc import Iterator
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.exc import OperationalError

from usali.db import make_engine, make_session_factory
from usali.desktop.bootstrap import (
    DesktopKeys,
    KeysMissing,
    NeedsUpgradeConsent,
    app_url,
    load_sample_data,
    migrate,
    owner_url,
    prepare_database,
)
from fastapi.testclient import TestClient

from usali.desktop import modules_api
from usali.desktop.identity import DesktopUser, LocalIssuer
from usali.desktop.intake import ReportIntake
from usali.desktop.modules import mount_predicate
from usali.desktop.settings import MODULES_KEY, read_modules, write_setting
from usali.keycloak_admin import InMemoryKeycloakAdmin
from usali.photo_store import InMemoryPhotoStore
from usali.server import create_app
from usali.desktop.pg_runtime import (
    SUPERUSER,
    PgCluster,
    PostgresNotFound,
    db_url,
    find_bin_dir,
    free_port,
)
from usali.models import OrgIntegrationCredential, Organization, RoleAssignment
from usali.reporting import summary_operating_statement_from_journal
from usali.tenancy import FOUNDING_ORG_ID, OrgBoundSessionFactory

REPO = Path(__file__).resolve().parents[1]
try:
    BIN: Path | None = find_bin_dir(REPO)
except PostgresNotFound:
    BIN = None

pytestmark = pytest.mark.skipif(
    BIN is None, reason="bundled Postgres not fetched (scripts/desktop/fetch_postgres.py)"
)

OWNER = DesktopUser(
    subject="desktop-owner", username="owner", roles=("org_admin",), org_alias="pilot-hotel-group"
)


@pytest.fixture(scope="module")
def running(tmp_path_factory: pytest.TempPathFactory) -> Iterator[tuple[PgCluster, int, DesktopKeys, Path]]:
    assert BIN is not None
    root = tmp_path_factory.mktemp("desktop")
    keys = DesktopKeys.load_or_create(root / "keys.json", database_exists=False)
    cluster = PgCluster(bin_dir=BIN, data_dir=root / "database", log_file=root / "database.log")
    cluster.init(keys.db_owner_password)
    port = free_port(55433)
    cluster.start(port)
    try:
        yield cluster, port, keys, root
    finally:
        cluster.stop()


def test_the_cluster_listens_on_loopback_only_with_passwords(running: tuple[PgCluster, int, DesktopKeys, Path]) -> None:
    cluster, port, keys, _ = running
    assert cluster.is_running()
    admin = create_engine(db_url(port=port, user=SUPERUSER, password=keys.db_owner_password, database="postgres"))
    try:
        with admin.connect() as conn:
            assert conn.execute(text("SHOW listen_addresses")).scalar() == "127.0.0.1"
    finally:
        admin.dispose()
    wrong = create_engine(db_url(port=port, user=SUPERUSER, password="not-the-password", database="postgres"))
    with pytest.raises(OperationalError):
        with wrong.connect():
            pass
    wrong.dispose()


def test_first_run_prepares_a_walled_database_with_nothing_connected(
    running: tuple[PgCluster, int, DesktopKeys, Path],
) -> None:
    _, port, keys, root = running
    outcome = prepare_database(
        port=port, keys=keys, resources=REPO, state_file=root / "state.json",
        user=OWNER, allow_upgrade=False,
    )
    assert outcome == "created"

    serving = make_engine(app_url(port, keys))
    try:
        bound = OrgBoundSessionFactory(make_session_factory(serving), FOUNDING_ORG_ID)
        with bound() as session:
            org = session.execute(select(Organization)).scalar_one()
            assert org.kc_org_alias == "pilot-hotel-group"
            grants = session.execute(
                select(RoleAssignment.role).where(RoleAssignment.keycloak_subject == "desktop-owner")
            ).scalars().all()
            assert grants == ["org_admin"]
            # PRD 5.3: every connection starts Off — none of upstream's mock
            # Gusto/QBO rows survive into a real owner's books.
            assert session.execute(
                select(func.count()).select_from(OrgIntegrationCredential)
            ).scalar_one() == 0
        # The DB wall, fail-closed: the serving role with NO org bound sees
        # zero rows, not all of them.
        with serving.connect() as conn:
            assert conn.execute(text("SELECT count(*) FROM organization")).scalar() == 0
    finally:
        serving.dispose()


def test_the_desktop_chain_keeps_its_own_history(
    running: tuple[PgCluster, int, DesktopKeys, Path],
) -> None:
    _, port, keys, _ = running
    owner = create_engine(owner_url(port, keys))
    try:
        with owner.connect() as conn:
            assert conn.execute(
                text("SELECT count(*) FROM desktop.alembic_version_desktop")
            ).scalar() == 1
            # Upstream's ledger holds upstream's head only — never ours.
            assert conn.execute(text("SELECT count(*) FROM public.alembic_version")).scalar() == 1
    finally:
        owner.dispose()
    serving = make_engine(app_url(port, keys))
    try:
        with make_session_factory(serving)() as session:
            assert read_modules(session) is None
            write_setting(session, MODULES_KEY, ["accounting"])
            session.commit()
            assert read_modules(session) == ["accounting"]
    finally:
        serving.dispose()


def test_the_modules_api_saves_the_owners_choice_and_asks_for_a_reload(
    running: tuple[PgCluster, int, DesktopKeys, Path], tmp_path: Path,
) -> None:
    _, port, keys, _ = running
    issuer = LocalIssuer.from_pem(keys.issuer_private_key_pem)
    serving = make_engine(app_url(port, keys))
    reloads: list[bool] = []
    try:
        app = create_app(
            inbox_dir=tmp_path / "i", processed_dir=tmp_path / "r", failed_dir=tmp_path / "f",
            dist_dir=tmp_path / "no-portal", session_factory=make_session_factory(serving),
            token_verifier=issuer.verifier(), keycloak_admin=InMemoryKeycloakAdmin(),
            photo_store=InMemoryPhotoStore(), mount=mount_predicate({"accounting"}),
        )
        modules_api.install(app, enabled=frozenset({"accounting"}),
                            reload=lambda: reloads.append(True))
        client = TestClient(app)
        owner = {"Authorization": f"Bearer {issuer.mint(OWNER)}"}

        listed = client.get("/api/me/modules", headers=owner)
        assert listed.status_code == 200
        state = {m["id"]: m["enabled"] for m in listed.json()["modules"]}
        assert state == {"accounting": True, "payroll": False, "utilities": False}

        saved = client.put("/api/desktop/modules", headers=owner,
                           json={"enabled": ["accounting", "payroll"]})
        assert saved.status_code == 200
        assert saved.json()["reloading"] is True
        assert reloads == [True]
        with make_session_factory(serving)() as session:
            assert read_modules(session) == ["accounting", "payroll"]

        # Choosing is the owner's call: an operator with no org_admin grant is refused.
        stranger = DesktopUser(subject="someone-else", username="x",
                               roles=("org_admin",), org_alias="pilot-hotel-group")
        refused = client.put("/api/desktop/modules",
                             headers={"Authorization": f"Bearer {issuer.mint(stranger)}"},
                             json={"enabled": ["accounting"]})
        assert refused.status_code == 403
    finally:
        serving.dispose()


def test_a_second_launch_is_a_no_op(running: tuple[PgCluster, int, DesktopKeys, Path]) -> None:
    _, port, keys, root = running
    outcome = prepare_database(
        port=port, keys=keys, resources=REPO, state_file=root / "state.json",
        user=OWNER, allow_upgrade=False,
    )
    assert outcome == "current"


def test_an_existing_database_is_not_upgraded_without_consent(
    running: tuple[PgCluster, int, DesktopKeys, Path],
) -> None:
    _, port, keys, _ = running
    owner = owner_url(port, keys)
    engine = create_engine(owner)
    try:
        with engine.begin() as conn:
            head = conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
            conn.execute(text("UPDATE alembic_version SET version_num = 'pretend-older'"))
        with pytest.raises(NeedsUpgradeConsent):
            migrate(owner, REPO, allow_upgrade=False)
    finally:
        with engine.begin() as conn:
            conn.execute(text("UPDATE alembic_version SET version_num = :h"), {"h": head})
        engine.dispose()


def test_the_intake_reads_every_sample_report_including_packs(
    running: tuple[PgCluster, int, DesktopKeys, Path], tmp_path: Path,
) -> None:
    _, port, keys, _ = running
    drop, read, unreadable = tmp_path / "drop", tmp_path / "read", tmp_path / "unreadable"
    n = load_sample_data(owner_url(port, keys), REPO, drop)
    assert n >= 7  # six single reports + the choiceADVANTAGE (SKYTOUCH) audit pack

    serving = make_engine(app_url(port, keys))
    intake = ReportIntake(
        OrgBoundSessionFactory(make_session_factory(serving), FOUNDING_ORG_ID),
        drop_folder=drop, read_folder=read, unreadable_folder=unreadable,
    )
    intake.start()
    try:
        deadline = time.monotonic() + 240
        while any(drop.glob("*.pdf")) and time.monotonic() < deadline:
            time.sleep(0.5)
    finally:
        intake.stop()
        serving.dispose()

    assert [p.name for p in unreadable.glob("*.pdf")] == []
    assert len(list(read.glob("*.pdf"))) == n

    # G1, engine side: the owner reaches a real number. Upstream's statement
    # reads the POSTED JOURNAL, so this fails if the chart was never seeded
    # (ingestion then posts nothing) even though every fact landed.
    serving = make_engine(app_url(port, keys))
    try:
        with OrgBoundSessionFactory(make_session_factory(serving), FOUNDING_ORG_ID)() as session:
            sos = summary_operating_statement_from_journal(
                session, property_id="HISJ", business_date=date(2026, 7, 7),
                date_from=None, date_to=None,
            )
        assert sos.total_operating_revenue > 0
    finally:
        serving.dispose()


def test_missing_keys_for_an_existing_database_refuse_loudly(tmp_path: Path) -> None:
    with pytest.raises(KeysMissing):
        DesktopKeys.load_or_create(tmp_path / "keys.json", database_exists=True)
    assert not (tmp_path / "keys.json").exists()
