"""Bring the bundled database to the state the engine expects.

The same order every upstream environment follows (ARCHITECTURE, "Ordering
invariant"): cluster roles → migrations as the owner → reference data → the
founding org and its owner grant. Only then does anything serve, and serving
connects as `usali_app` — the RLS-bound role — never as the owner.

Keys live in one file in the system folder. PRD A-4/AI-1 put the signing
key and provider keys in the OS keychain; that move is M2's (ADR-D1). The
file is written owner-only on POSIX and sits in the per-user app-data
folder on Windows, and the M3 backup must carry it — a database whose keys
are lost cannot be opened, by design.
"""

import base64
import json
import os
import re
import secrets
import shutil
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from sqlalchemy import create_engine, delete, select, text

from usali.config import get_settings
from usali.db import make_engine, make_session_factory
from usali.desktop.identity import DesktopUser, LocalIssuer
from usali.desktop.pg_runtime import DATABASE, SUPERUSER, db_url
from usali.tenancy import APP_DB_ROLE

# The PMS dictionaries a fresh install knows: PRD 5.2's three systems.
_PMS_MAPPINGS = ("opera.yaml", "autoclerk.yaml", "skytouch.yaml")
# Only generated secrets are ever inlined into role DDL (Postgres takes no
# bind parameters there); anything else is refused rather than quoted.
_SAFE_SECRET = re.compile(r"^[A-Za-z0-9_-]{20,}$")
# The `connected_by` that `property_registry._seed_integration_credentials`
# stamps on the env-bridged rows it plants in a newly created org 1.
_ENV_SEED_SUBJECT = "seed:env"


class KeysMissing(RuntimeError):
    """A database exists but the keys that open it do not."""


class NeedsUpgradeConsent(RuntimeError):
    """A newer engine wants to migrate an existing database (PRD I-5)."""


def _secret() -> str:
    return secrets.token_urlsafe(32)


@dataclass(frozen=True)
class DesktopKeys:
    db_owner_password: str
    db_app_password: str
    db_provisioner_password: str
    field_encryption_key: str  # base64(32 bytes): Settings.field_encryption_key
    pii_hpke_private_key: str  # base64(PKCS8 DER, P-256): SoftwareOpener
    issuer_private_key_pem: str  # RSA: identity.LocalIssuer

    @classmethod
    def generate(cls) -> "DesktopKeys":
        hpke = ec.generate_private_key(ec.SECP256R1()).private_bytes(
            serialization.Encoding.DER,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
        return cls(
            db_owner_password=_secret(),
            db_app_password=_secret(),
            db_provisioner_password=_secret(),
            field_encryption_key=base64.b64encode(secrets.token_bytes(32)).decode(),
            pii_hpke_private_key=base64.b64encode(hpke).decode(),
            issuer_private_key_pem=LocalIssuer.generate_pem(),
        )

    @classmethod
    def load_or_create(cls, path: Path, *, database_exists: bool) -> "DesktopKeys":
        if path.is_file():
            return cls(**json.loads(path.read_text(encoding="utf-8")))
        if database_exists:
            # Generating fresh keys here would lock the owner out of their own
            # books AND make every encrypted field unreadable. Stop and say so.
            raise KeysMissing(
                f"The key file that unlocks your books is missing ({path}). Without it the "
                "database cannot be opened. Put keys.json back in that folder from your "
                "backup, then start Open Hospitality again."
            )
        keys = cls.generate()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(asdict(keys), f, indent=2)
        os.replace(tmp, path)
        return keys


def owner_url(port: int, keys: DesktopKeys) -> str:
    return db_url(port=port, user=SUPERUSER, password=keys.db_owner_password)


def app_url(port: int, keys: DesktopKeys) -> str:
    return db_url(port=port, user=APP_DB_ROLE, password=keys.db_app_password)


@contextmanager
def _db_url_env(url: str) -> Iterator[None]:
    """migrations/env.py takes its URL from Settings (USALI_DB_URL), not from
    the Config handed to alembic — so the owner URL must be in env while the
    chain runs, and the serving URL must be back the moment it finishes."""
    previous = os.environ.get("USALI_DB_URL")
    os.environ["USALI_DB_URL"] = url
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("USALI_DB_URL", None)
        else:
            os.environ["USALI_DB_URL"] = previous


def ensure_database(port: int, keys: DesktopKeys) -> None:
    admin = create_engine(
        db_url(port=port, user=SUPERUSER, password=keys.db_owner_password, database="postgres"),
        isolation_level="AUTOCOMMIT",
    )
    try:
        with admin.connect() as conn:
            found = conn.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :d"), {"d": DATABASE}
            ).scalar()
            if found is None:
                conn.execute(text(f'CREATE DATABASE "{DATABASE}"'))
    finally:
        admin.dispose()


def ensure_roles(owner: str, keys: DesktopKeys) -> None:
    """The two cluster roles the migration chain refuses to run without
    (l2a0rlswall, b1a0provrole) — LOGIN and nothing else, as
    scripts/dev_pg_init.sql creates them. Re-applied every start so the
    passwords always match keys.json."""
    provisioner = get_settings().provisioner_db_role
    engine = create_engine(owner, isolation_level="AUTOCOMMIT")
    try:
        with engine.connect() as conn:
            for role, password in (
                (APP_DB_ROLE, keys.db_app_password),
                (provisioner, keys.db_provisioner_password),
            ):
                if not _SAFE_SECRET.match(password):
                    raise ValueError(f"refusing to inline an unexpected password shape ({role})")
                exists = conn.execute(
                    text("SELECT 1 FROM pg_roles WHERE rolname = :r"), {"r": role}
                ).scalar() is not None
                verb = "ALTER" if exists else "CREATE"
                conn.execute(text(f"{verb} ROLE \"{role}\" LOGIN PASSWORD '{password}'"))
    finally:
        engine.dispose()


def _alembic_config(resources: Path, url: str) -> Config:
    # No ini file, on purpose: alembic.ini's logging sections make env.py run
    # fileConfig(), which DISABLES every logger configured before it — the
    # launcher's own log would go silent for the rest of the session.
    cfg = Config()
    cfg.set_main_option("script_location", str(resources / "migrations"))
    cfg.set_main_option("sqlalchemy.url", url)
    return cfg


def migration_revisions(resources: Path, url: str) -> tuple[str | None, str]:
    head = ScriptDirectory.from_config(_alembic_config(resources, url)).get_current_head()
    if head is None:
        raise RuntimeError(f"no migrations found under {resources / 'migrations'}")
    engine = create_engine(url)
    try:
        with engine.connect() as conn:
            current = MigrationContext.configure(conn).get_current_revision()
    finally:
        engine.dispose()
    return current, head


def _consent(current: str | None, head: str, *, allow_upgrade: bool) -> None:
    """A fresh database is migrated without asking — that IS the install. An
    existing one is only upgraded with the owner's say-so (PRD I-5): until M3
    gives that a dialog and a pre-upgrade backup, the say-so is a flag."""
    if current is not None and current != head and not allow_upgrade:
        raise NeedsUpgradeConsent(
            "This version of Open Hospitality needs to update how your books are stored. "
            "Make sure you have a recent copy of your data, then start it with "
            f"--upgrade-database to go ahead. (Your data: {current}; this version: {head}.)"
        )


def migrate(owner: str, resources: Path, *, allow_upgrade: bool) -> str:
    """Upstream's chain: 'created' (a fresh install), 'current', or 'upgraded'."""
    current, head = migration_revisions(resources, owner)
    if current == head:
        return "current"
    _consent(current, head, allow_upgrade=allow_upgrade)
    with _db_url_env(owner):
        command.upgrade(_alembic_config(resources, owner), "head")
    return "created" if current is None else "upgraded"


_DESKTOP_MIGRATIONS = Path(__file__).with_name("migrations")


def _desktop_config(url: str) -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(_DESKTOP_MIGRATIONS))
    cfg.set_main_option("sqlalchemy.url", url)
    return cfg


def migrate_desktop(owner: str, *, allow_upgrade: bool) -> str:
    """The desktop chain (schema `desktop`, its own version table), under the
    same consent rule as upstream's."""
    from usali.desktop.migrations.env_names import SCHEMA, VERSION_TABLE

    head = ScriptDirectory.from_config(_desktop_config(owner)).get_current_head()
    if head is None:
        raise RuntimeError(f"no desktop migrations under {_DESKTOP_MIGRATIONS}")
    engine = create_engine(owner)
    try:
        with engine.connect() as conn:
            current = MigrationContext.configure(
                conn, opts={"version_table": VERSION_TABLE, "version_table_schema": SCHEMA}
            ).get_current_revision()
    finally:
        engine.dispose()
    if current == head:
        return "current"
    _consent(current, head, allow_upgrade=allow_upgrade)
    command.upgrade(_desktop_config(owner), "head")
    return "created" if current is None else "upgraded"


def seed_first_run(owner: str, resources: Path, user: DesktopUser) -> None:
    """Reference data, the founding org, and the owner's grant."""
    from usali.mapping.loader import load_mappings
    from usali.mapping.property_registry import ensure_default_org
    from usali.mapping.schedules import seed_schedules
    from usali.models import OrgIntegrationCredential, RoleAssignment

    engine = make_engine(owner)
    try:
        with make_session_factory(engine)() as session:
            seed_schedules(session, str(resources / "mapping" / "usali_schedules.yaml"))
            for name in _PMS_MAPPINGS:
                load_mappings(session, str(resources / "mapping" / name))
            org_id = ensure_default_org(session)
            # PRD 5.3: every connection starts OFF. On a newly created org 1,
            # ensure_default_org bridges the process env into credential rows —
            # and upstream's env defaults are its local MOCK Gusto and QBO, so a
            # real owner would open the app "connected" to services that do not
            # exist. Remove exactly the rows that bridge planted: nothing a
            # person connected carries this subject.
            session.execute(
                delete(OrgIntegrationCredential).where(
                    OrgIntegrationCredential.org_id == org_id,
                    OrgIntegrationCredential.connected_by == _ENV_SEED_SUBJECT,
                )
            )
            held = set(
                session.execute(
                    select(RoleAssignment.role).where(
                        RoleAssignment.keycloak_subject == user.subject
                    )
                ).scalars()
            )
            for role in user.roles:
                if role not in held:
                    # Org-wide grant (property_id NULL): the l4a0orggrant shape
                    # the seeds and provision_tenant write for org_admin.
                    session.add(
                        RoleAssignment(
                            org_id=org_id, keycloak_subject=user.subject,
                            role=role, property_id=None,
                        )
                    )
            session.commit()
    finally:
        engine.dispose()


def ensure_gl_chart(owner: str, resources: Path) -> int:
    """The founding org's USALI chart of accounts, as `usali gl-seed-chart`
    seeds it — same call, same founding-bound session.

    Load-bearing, not optional: upstream's Summary Operating Statement reads
    the posted journal (OH-27 cutover), and ingestion posts nothing while no
    chart exists — facts land, the statement refuses. Insert-only upstream
    (an owner's edits survive), so it runs on EVERY launch: that is also what
    repairs an install first seeded before this step existed. Tracking
    upstream's ledger rather than building a second one is PRD open
    decision 6.

    The template path is passed explicitly: gl_chart's default finds it
    relative to its own __file__, which inside a PyInstaller bundle points
    outside the bundle."""
    from usali import gl_chart
    from usali.tenancy import FOUNDING_ORG_ID, OrgBoundSessionFactory

    engine = make_engine(owner)
    try:
        with OrgBoundSessionFactory(make_session_factory(engine), FOUNDING_ORG_ID)() as session:
            added = gl_chart.seed_chart(
                session, org_id=FOUNDING_ORG_ID,
                path=resources / "mapping" / "gl_accounts_usali.yaml",
            )
            session.commit()
    finally:
        engine.dispose()
    return added


def load_sample_data(owner: str, resources: Path, drop_folder: Path) -> int:
    """Developer-only in M1: the pilot's sample properties, and the sample
    PDFs copied into the drop folder so the intake reads them the way it
    reads an owner's reports. M2's first-run wizard replaces this with a
    separate practice copy (PRD appendix A) — sample rows never belong in
    real books.

    Each sample property ALSO gets a fiscal calendar (calendar months, year
    from January — upstream's own GL test choice). The statement reads the
    posted journal, and posting refuses a property with no calendar
    (ADR-010), so without one the samples would land as facts and the
    statement would still say nothing. For a real owner the calendar is
    their answer to give: M2's wizard asks it before the first report.
    Only properties this call CREATES get one, so running it against an
    install with real properties never touches theirs."""
    from usali.mapping.property_registry import seed_properties
    from usali.models import FiscalCalendar, Property
    from usali.tenancy import FOUNDING_ORG_ID, OrgBoundSessionFactory

    engine = make_engine(owner)
    try:
        with make_session_factory(engine)() as session:
            before = set(session.scalars(select(Property.property_id)))
            seed_properties(session, str(resources / "mapping" / "properties.yaml"))
            session.commit()
            created = set(session.scalars(select(Property.property_id))) - before
        # ORM adds on a founding-bound session, as property_config_api writes
        # calendars: the before_flush org stamp applies to them.
        with OrgBoundSessionFactory(make_session_factory(engine), FOUNDING_ORG_ID)() as session:
            for property_id in sorted(created):
                if session.get(FiscalCalendar, property_id) is None:
                    session.add(FiscalCalendar(
                        property_id=property_id, calendar_type="calendar_month",
                        fiscal_year_start_month=1, week_start_weekday=None,
                    ))
            session.commit()
    finally:
        engine.dispose()
    samples = sorted((resources / "docs" / "reference" / "samples").glob("*.pdf"))
    drop_folder.mkdir(parents=True, exist_ok=True)
    for pdf in samples:
        shutil.copy2(pdf, drop_folder / pdf.name)
    return len(samples)


def _read_state(path: Path) -> dict[str, object]:
    if not path.is_file():
        return {}
    loaded: dict[str, object] = json.loads(path.read_text(encoding="utf-8"))
    return loaded


def _write_state(path: Path, state: dict[str, object]) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def prepare_database(
    *,
    port: int,
    keys: DesktopKeys,
    resources: Path,
    state_file: Path,
    user: DesktopUser,
    allow_upgrade: bool,
) -> str:
    """Idempotent: safe on every launch, and safe to re-run after a launch
    that died half-way through its first run."""
    ensure_database(port, keys)
    owner = owner_url(port, keys)
    ensure_roles(owner, keys)
    outcome = migrate(owner, resources, allow_upgrade=allow_upgrade)
    migrate_desktop(owner, allow_upgrade=allow_upgrade)
    state = _read_state(state_file)
    if not state.get("seeded_at"):
        seed_first_run(owner, resources, user)
        state["seeded_at"] = datetime.now(UTC).isoformat()
        _write_state(state_file, state)
    ensure_gl_chart(owner, resources)
    return outcome
