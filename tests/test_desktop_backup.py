"""Backup and restore (PRD I-6, ADR-D4).

The promise: one file in the owner's synced folder, plus the recovery code
they already keep, reopens their books on a computer that has never seen this
install's keychain. Most of this needs no database — the last test needs a
real one, because "the books open afterwards" is the only claim that matters.
"""

import json
import zipfile
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from usali.desktop import backup
from usali.desktop.app import OWNER
from usali.desktop.backup import BackupConfig, BackupError, BackupUnreadable
from usali.desktop.bootstrap import app_url, prepare_database
from usali.desktop.keystore import MemoryKeyStore, entry_name, open_keys
from usali.desktop.paths import DesktopPaths
from usali.desktop.pg_runtime import PgCluster, PostgresNotFound, find_bin_dir, free_port

REPO = Path(__file__).resolve().parents[1]
try:
    BIN: Path | None = find_bin_dir(REPO)
except PostgresNotFound:
    BIN = None

CODE = "Z177D-WHZ9P-4DPSD-V37AJ-9BGQ7"


def _install(root: Path, store: MemoryKeyStore) -> DesktopPaths:
    """A desktop install with sealed keys and a database folder."""
    paths = DesktopPaths(owner_root=root / "owner", system_root=root / "system")
    paths.ensure()
    open_keys(sealed=paths.sealed_keys_file, legacy=paths.keys_file, store=store,
              database_exists=False)
    paths.database.mkdir(parents=True, exist_ok=True)
    (paths.database / "PG_VERSION").write_text("16")
    (paths.database / "base").mkdir(exist_ok=True)
    (paths.database / "base" / "1").write_bytes(b"pretend pages" * 1000)
    # Postgres keeps several directories that are EMPTY after a clean stop
    # and refuses to start without them.
    (paths.database / "pg_notify").mkdir(exist_ok=True)
    # ...and one file that belongs to the computer it was running on.
    (paths.database / "postmaster.pid").write_text("4242")
    paths.state_file.write_text(json.dumps({"seeded_at": "2026-09-11T00:00:00+00:00"}))
    return paths


def _configured(paths: DesktopPaths, folder: Path) -> None:
    BackupConfig(folder=folder).save(paths.backup_config_file)


@pytest.fixture
def armed(tmp_path: Path) -> Iterator[tuple[DesktopPaths, MemoryKeyStore, Path]]:
    store = MemoryKeyStore()
    paths = _install(tmp_path / "a", store)
    folder = tmp_path / "synced"
    _configured(paths, folder)
    backup.write_wrap(paths, recovery_code=CODE, store=store)
    yield paths, store, folder


def test_a_backup_reopens_on_a_computer_that_never_saw_this_install(
    armed: tuple[DesktopPaths, MemoryKeyStore, Path], tmp_path: Path,
) -> None:
    paths, store, folder = armed
    archive = backup.make_backup(paths, store=store, now=datetime(2026, 9, 11, 4, tzinfo=UTC))
    assert archive.parent == folder and archive.suffix == ".ohbackup"

    # Nothing readable leaks: the file names no secret and no plain zip header.
    blob = archive.read_bytes()
    assert blob.startswith(b"OHBACKUP1\n")
    assert b"PK\x03\x04" not in blob
    assert b"pretend pages" not in blob

    # A new computer: new folders, and a keychain that holds nothing at all.
    fresh_store = MemoryKeyStore()
    other = DesktopPaths(owner_root=tmp_path / "b" / "owner",
                         system_root=tmp_path / "b" / "system")
    manifest = backup.restore(other, archive, recovery_code=CODE, store=fresh_store)

    assert manifest["install_id"] == json.loads(paths.sealed_keys_file.read_text())["install_id"]
    assert (other.database / "base" / "1").read_bytes() == (
        paths.database / "base" / "1"
    ).read_bytes()
    assert other.state_file.read_text() == paths.state_file.read_text()
    # The empty directories Postgres needs come back...
    assert (other.database / "pg_notify").is_dir()
    # ...and the last computer's pid file does not.
    assert not (other.database / "postmaster.pid").exists()
    # ...and the keys open, which is the whole point.
    assert open_keys(sealed=other.sealed_keys_file, legacy=other.keys_file, store=fresh_store,
                     database_exists=True) == open_keys(
        sealed=paths.sealed_keys_file, legacy=paths.keys_file, store=store, database_exists=True)
    assert fresh_store.get(entry_name(str(manifest["install_id"]))) is not None
    # The restored install can take its own backups straight away.
    assert other.backup_wrap_file.is_file()


def test_the_recovery_code_is_what_opens_it(
    armed: tuple[DesktopPaths, MemoryKeyStore, Path], tmp_path: Path,
) -> None:
    paths, store, _ = armed
    archive = backup.make_backup(paths, store=store)
    other = DesktopPaths(owner_root=tmp_path / "c" / "owner",
                         system_root=tmp_path / "c" / "system")
    with pytest.raises(BackupUnreadable, match="recovery code"):
        backup.restore(other, archive, recovery_code="AAAAA-BBBBB-CCCCC-DDDDD-EEEEE",
                       store=MemoryKeyStore())
    # Dashes and case don't matter, as the recovery screen promises.
    backup.restore(other, archive, recovery_code=CODE.lower().replace("-", " "),
                   store=MemoryKeyStore())


def test_a_damaged_file_is_refused_not_half_restored(
    armed: tuple[DesktopPaths, MemoryKeyStore, Path], tmp_path: Path,
) -> None:
    paths, store, _ = armed
    archive = backup.make_backup(paths, store=store)
    blob = bytearray(archive.read_bytes())
    blob[-40] ^= 0xFF
    archive.write_bytes(blob)
    other = DesktopPaths(owner_root=tmp_path / "d" / "owner",
                         system_root=tmp_path / "d" / "system")
    with pytest.raises(BackupUnreadable, match="changed or damaged"):
        backup.restore(other, archive, recovery_code=CODE, store=MemoryKeyStore())


def test_restoring_never_writes_over_books_that_are_already_here(
    armed: tuple[DesktopPaths, MemoryKeyStore, Path],
) -> None:
    paths, store, _ = armed
    archive = backup.make_backup(paths, store=store)
    with pytest.raises(BackupError, match="already has books"):
        backup.restore(paths, archive, recovery_code=CODE, store=store)


def test_without_the_recovery_code_once_there_is_no_backup(tmp_path: Path) -> None:
    store = MemoryKeyStore()
    paths = _install(tmp_path / "e", store)
    _configured(paths, tmp_path / "synced-e")
    # Never armed: refusing beats writing a file only this computer can open.
    with pytest.raises(BackupError, match="recovery code"):
        backup.make_backup(paths, store=store)


def test_a_backup_a_day_and_the_owner_can_ask_for_one(
    armed: tuple[DesktopPaths, MemoryKeyStore, Path],
) -> None:
    paths, store, folder = armed
    monday = datetime(2026, 9, 7, 6, tzinfo=UTC)
    assert backup.maybe_backup(paths, store=store, now=monday) is not None
    # Same day, hours later: the copy already exists.
    assert backup.maybe_backup(paths, store=store, now=monday + timedelta(hours=6)) is None
    # Next morning: another.
    assert backup.maybe_backup(paths, store=store, now=monday + timedelta(hours=21)) is not None
    # "Back up now" doesn't wait for the clock.
    config = BackupConfig.load(paths.backup_config_file)
    assert config.last_file is not None
    assert backup.maybe_backup(paths, store=store, now=monday + timedelta(hours=22),
                               force=True) is not None
    assert len(list(folder.glob("*.ohbackup"))) == 3


def test_only_the_last_seven_are_kept(
    armed: tuple[DesktopPaths, MemoryKeyStore, Path],
) -> None:
    paths, store, folder = armed
    start = datetime(2026, 8, 1, 5, tzinfo=UTC)
    for day in range(9):
        backup.make_backup(paths, store=store, now=start + timedelta(days=day))
    kept = sorted(p.name for p in folder.glob("*.ohbackup"))
    assert len(kept) == 7
    assert kept[0].startswith("Open Hospitality 2026-08-03")


def test_a_backup_says_what_it_is_without_being_opened(
    armed: tuple[DesktopPaths, MemoryKeyStore, Path],
) -> None:
    paths, store, _ = armed
    archive = backup.make_backup(paths, store=store)
    header = backup.describe(archive)
    assert header["postgres_major"] == "16"
    assert header["heads"]["desktop"] and header["heads"]["engine"]
    assert "app_version" in header and "created_at" in header
    # The manifest is readable; the books are not.
    assert "master_key" in header and "backup_key_wrap" in header


def test_the_owners_reports_folder_is_not_copied_into_every_backup(
    armed: tuple[DesktopPaths, MemoryKeyStore, Path], tmp_path: Path,
) -> None:
    paths, store, _ = armed
    (paths.drop_folder / "last night.pdf").write_bytes(b"%PDF-1.4 pretend")
    archive = backup.make_backup(paths, store=store)
    other = DesktopPaths(owner_root=tmp_path / "f" / "owner",
                         system_root=tmp_path / "f" / "system")
    backup.restore(other, archive, recovery_code=CODE, store=MemoryKeyStore())
    staging = other.system_root / "restore.staging.zip"
    assert not staging.exists()
    assert not (other.drop_folder / "last night.pdf").exists()


@pytest.mark.skipif(BIN is None, reason="bundled Postgres not fetched")
def test_a_restored_install_starts_and_its_books_open(tmp_path: Path) -> None:
    """The claim that matters: back up a real cluster, restore it somewhere
    else, start Postgres there and find the books already migrated."""
    assert BIN is not None
    store = MemoryKeyStore()
    paths = DesktopPaths(owner_root=tmp_path / "live" / "owner",
                         system_root=tmp_path / "live" / "system")
    paths.ensure()
    keys = open_keys(sealed=paths.sealed_keys_file, legacy=paths.keys_file, store=store,
                     database_exists=False)
    cluster = PgCluster(bin_dir=BIN, data_dir=paths.database, log_file=tmp_path / "db.log")
    cluster.init(keys.db_owner_password)
    port = free_port(55438)
    cluster.start(port)
    try:
        assert prepare_database(port=port, keys=keys, resources=REPO,
                                state_file=paths.state_file, user=OWNER,
                                allow_upgrade=False) == "created"
    finally:
        cluster.stop()  # a backup is taken with the cluster STOPPED

    _configured(paths, tmp_path / "synced")
    backup.write_wrap(paths, recovery_code=CODE, store=store)
    archive = backup.make_backup(paths, store=store)

    fresh_store = MemoryKeyStore()
    other = DesktopPaths(owner_root=tmp_path / "new" / "owner",
                         system_root=tmp_path / "new" / "system")
    backup.restore(other, archive, recovery_code=CODE, store=fresh_store)
    restored_keys = open_keys(sealed=other.sealed_keys_file, legacy=other.keys_file,
                              store=fresh_store, database_exists=True)
    assert restored_keys == keys

    moved = PgCluster(bin_dir=BIN, data_dir=other.database, log_file=tmp_path / "db2.log")
    new_port = free_port(55439)
    moved.start(new_port)
    try:
        # Already migrated and seeded: nothing to do but open it.
        assert prepare_database(port=new_port, keys=restored_keys, resources=REPO,
                                state_file=other.state_file, user=OWNER,
                                allow_upgrade=False) == "current"
        from sqlalchemy import text

        from usali.db import make_engine

        engine = make_engine(app_url(new_port, restored_keys))
        try:
            with engine.connect() as conn:
                assert conn.execute(text("SELECT 1")).scalar() == 1
        finally:
            engine.dispose()
    finally:
        moved.stop()


def test_a_backup_carries_both_migration_heads_so_a_restore_knows_its_age(
    armed: tuple[DesktopPaths, MemoryKeyStore, Path],
) -> None:
    paths, store, _ = armed
    archive = backup.make_backup(paths, store=store)
    heads = backup.describe(archive)["heads"]
    # Both chains: upstream's and the desktop's own (ADR-D3).
    assert set(heads) == {"engine", "desktop"}
    assert all(isinstance(v, str) and v for v in heads.values())


def test_the_archive_holds_the_database_and_the_keys_and_nothing_surprising(
    armed: tuple[DesktopPaths, MemoryKeyStore, Path], tmp_path: Path,
) -> None:
    paths, store, _ = armed
    archive = backup.make_backup(paths, store=store)
    other = DesktopPaths(owner_root=tmp_path / "g" / "owner",
                         system_root=tmp_path / "g" / "system")
    backup.restore(other, archive, recovery_code=CODE, store=MemoryKeyStore())
    # Restore leaves the system folder holding exactly what an install needs.
    names = {p.name for p in other.system_root.iterdir()}
    assert {"database", "keys.sealed.json", "state.json", "backup-key.wrapped.json"} <= names


def test_the_staging_file_never_survives_a_backup(
    armed: tuple[DesktopPaths, MemoryKeyStore, Path],
) -> None:
    paths, store, _ = armed
    archive = backup.make_backup(paths, store=store)
    assert not (paths.system_root / "backup.staging.zip").exists()
    # And the archive is a sealed file, not a zip anyone can open.
    with pytest.raises(zipfile.BadZipFile):
        zipfile.ZipFile(archive)
