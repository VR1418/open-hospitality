"""Backup and restore (PRD I-6 and G6, ADR-D4).

A backup is the database files copied while the database is STOPPED, sealed
into one file in a folder the owner names — one their cloud drive already
syncs. The launcher takes it at start-up, before `PgCluster.start`, which is
the one moment the cluster is quiescent by construction. Copying a running
cluster is how books get corrupted (see paths.py), and the bundle ships no
`pg_dump` to take a logical copy with: `vendor/postgres/<tag>/bin` holds
`initdb`, `pg_ctl` and `postgres`, and nothing else.

What the file holds: the cluster directory, `keys.sealed.json`, `state.json`
and a manifest (install id, app version, both migration heads, the Postgres
major version). Not the owner's report folders — those already live in the
owner's own folder, which is what the cloud drive syncs.

How it is sealed, and why a backup can be opened on a NEW computer:

* a random 32-byte **backup key** per install, kept in the OS keychain
  (`backup-key:<install id>`);
* the archive is encrypted with a per-file key derived from it (HKDF over a
  random salt), in chunks, so no two files ever share a key and counter;
* the archive carries the **master key** (ADR-D5's, which unseals
  `keys.sealed.json`) wrapped under the backup key;
* and it carries the **backup key** itself wrapped under a key derived from
  the owner's RECOVERY CODE (Argon2id, the parameters passwords.py uses).

So: backup file + recovery code = the books, on any computer. The wrap is
written when the recovery code is known in the clear — owner setup, recovery,
or the owner typing it on the Backups page — never at backup time, when only
its hash exists. Each backup carries the wrap that was current when it was
taken, so replacing the recovery code never orphans older files.
"""

import base64
import json
import logging
import os
import shutil
import zipfile
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import Any

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from usali.desktop.keystore import KeyStore, entry_name, read_master
from usali.desktop.passwords import normalise_recovery_code
from usali.desktop.paths import DesktopPaths

_LOG = logging.getLogger(__name__)

MAGIC = b"OHBACKUP1\n"
FORMAT = 1
# 4 MiB plaintext per sealed chunk: big enough that a 40 MB cluster is a
# handful of blocks, small enough never to hold the file in memory.
CHUNK = 4 * 1024 * 1024
KEEP_DEFAULT = 7
# A backup a day, taken on the first launch of the day (ADR-D4).
STALE_AFTER = timedelta(hours=20)
# The bundled server's major version (scripts/desktop/fetch_postgres.py's
# VERSION). A file-level copy restores onto the same major only.
PG_MAJOR = "16"

SUFFIX = ".ohbackup"


class BackupError(RuntimeError):
    """Refused, with a sentence the owner can act on."""


class BackupUnreadable(BackupError):
    """Wrong recovery code, or the file has been damaged."""


@dataclass(frozen=True)
class BackupConfig:
    """Where backups go and when the last one was taken.

    A file, not a `desktop.setting` row: the backup runs before the database
    is started, so its own settings cannot live inside it.
    """

    folder: Path | None = None
    last_backup_at: datetime | None = None
    last_file: str | None = None
    # Set by "Back up now": the next launch takes one whatever the clock says.
    requested: bool = False
    keep: int = KEEP_DEFAULT

    @classmethod
    def load(cls, path: Path) -> "BackupConfig":
        if not path.is_file():
            return cls()
        try:
            raw: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            _LOG.warning("%s isn't readable; treating backups as not set up", path)
            return cls()
        when = raw.get("last_backup_at")
        folder = raw.get("folder")
        return cls(
            folder=Path(folder) if isinstance(folder, str) and folder else None,
            last_backup_at=datetime.fromisoformat(when) if isinstance(when, str) else None,
            last_file=raw.get("last_file"),
            requested=bool(raw.get("requested", False)),
            keep=int(raw.get("keep", KEEP_DEFAULT)),
        )

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps({
            "folder": str(self.folder) if self.folder is not None else None,
            "last_backup_at": (
                self.last_backup_at.isoformat() if self.last_backup_at is not None else None
            ),
            "last_file": self.last_file,
            "requested": self.requested,
            "keep": self.keep,
        }, indent=2), encoding="utf-8")
        os.replace(tmp, path)

    def due(self, now: datetime) -> bool:
        if self.folder is None:
            return False
        if self.requested or self.last_backup_at is None:
            return True
        return now - self.last_backup_at >= STALE_AFTER


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


def _un64(text: str) -> bytes:
    return base64.b64decode(text)


def _recovery_key(recovery_code: str, salt: bytes) -> bytes:
    """Argon2id over the recovery code — the same cost passwords.py hashes
    with (m=19 MiB, t=2, p=1)."""
    from argon2.low_level import Type, hash_secret_raw

    return hash_secret_raw(
        secret=normalise_recovery_code(recovery_code).encode(),
        salt=salt, time_cost=2, memory_cost=19456, parallelism=1, hash_len=32, type=Type.ID,
    )


def _file_key(key: bytes, salt: bytes) -> bytes:
    """A key for THIS archive: chunk nonces are a counter, so two files must
    never share a key."""
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=salt,
                info=b"open-hospitality-backup").derive(key)


def backup_key(store: KeyStore, install_id: str) -> bytes:
    """This install's backup key, from the OS keychain; made on first use."""
    name = f"backup-key:{install_id}"
    kept = store.get(name)
    if kept is not None:
        return _un64(kept)
    key = os.urandom(32)
    store.set(name, _b64(key))
    return key


def install_id_of(sealed: Path) -> str:
    doc: dict[str, Any] = json.loads(sealed.read_text(encoding="utf-8"))
    return str(doc["install_id"])


def write_wrap(paths: DesktopPaths, *, recovery_code: str, store: KeyStore) -> None:
    """Wrap the backup key under the owner's recovery code, so a backup can be
    opened on a computer this install's keychain has never seen. Called where
    the code is known in the clear: owner setup, recovery, and the Backups
    page."""
    install_id = install_id_of(paths.sealed_keys_file)
    salt = os.urandom(16)
    nonce = os.urandom(12)
    wrapped = AESGCM(_recovery_key(recovery_code, salt)).encrypt(
        nonce, backup_key(store, install_id), install_id.encode(),
    )
    paths.backup_wrap_file.write_text(json.dumps({
        "format": FORMAT, "install_id": install_id, "salt": _b64(salt),
        "nonce": _b64(nonce), "wrapped": _b64(wrapped),
    }, indent=2), encoding="utf-8")


def _read_wrap(paths: DesktopPaths) -> dict[str, Any] | None:
    if not paths.backup_wrap_file.is_file():
        return None
    try:
        doc: dict[str, Any] = json.loads(paths.backup_wrap_file.read_text(encoding="utf-8"))
    except ValueError:
        return None
    return doc


def _heads() -> dict[str, str | None]:
    """The migration heads THIS build knows — read from the scripts, so no
    database is needed (there isn't one running when a backup is taken)."""
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    def head(script_location: Path) -> str | None:
        if not script_location.is_dir():
            return None
        cfg = Config()
        cfg.set_main_option("script_location", str(script_location))
        cfg.set_main_option("sqlalchemy.url", "sqlite://")  # never connected to
        return ScriptDirectory.from_config(cfg).get_current_head()

    # src/usali/desktop/backup.py -> the repo (or bundle) root.
    resources = Path(__file__).resolve().parents[3]
    return {
        "engine": head(resources / "migrations"),
        "desktop": head(Path(__file__).with_name("migrations")),
    }


# A pid file from another computer makes a restored copy look like it is
# already running; the postmaster writes both of these afresh on start.
_SKIP = frozenset({"postmaster.pid", "postmaster.opts"})


def _zip_install(paths: DesktopPaths, manifest: dict[str, Any], into: Path) -> None:
    with zipfile.ZipFile(into, "w", zipfile.ZIP_DEFLATED, compresslevel=1) as zf:
        zf.writestr("manifest.json", json.dumps(manifest, indent=2))
        zf.write(paths.sealed_keys_file, "keys.sealed.json")
        if paths.state_file.is_file():
            zf.write(paths.state_file, "state.json")
        for path in sorted(paths.database.rglob("*")):
            # Forward slashes always: a backup written on Windows has to
            # restore on a Mac as a tree, not as one flat filename.
            rel = "database/" + path.relative_to(paths.database).as_posix()
            if path.is_dir():
                # Directories, INCLUDING EMPTY ONES. Postgres refuses to start
                # without pg_notify, pg_serial, pg_twophase and the rest, and
                # those are empty on a clean shutdown — a files-only copy
                # restores a cluster that dies with "could not open directory".
                zf.writestr(rel + "/", "")
            elif path.is_file() and path.name not in _SKIP:
                zf.write(path, rel)


def _seal(plain: Path, dest: Path, key: bytes, header: dict[str, Any]) -> None:
    aes = AESGCM(key)
    head = json.dumps(header).encode()
    tmp = dest.with_name(dest.name + ".part")
    with plain.open("rb") as src, tmp.open("wb") as out:
        out.write(MAGIC)
        out.write(len(head).to_bytes(4, "big"))
        out.write(head)
        index = 0
        while True:
            chunk = src.read(CHUNK)
            if not chunk:
                break
            # Counter nonce, safe because the key is this file's alone.
            blob = aes.encrypt(index.to_bytes(12, "big"), chunk, head)
            out.write(len(blob).to_bytes(4, "big"))
            out.write(blob)
            index += 1
    os.replace(tmp, dest)


def _open_header(archive: Path) -> dict[str, Any]:
    with archive.open("rb") as src:
        if src.read(len(MAGIC)) != MAGIC:
            raise BackupUnreadable(
                f"{archive.name} isn't an Open Hospitality backup."
            )
        size = int.from_bytes(src.read(4), "big")
        doc: dict[str, Any] = json.loads(src.read(size))
        return doc


def _unseal(archive: Path, dest: Path, key: bytes) -> None:
    aes = AESGCM(key)
    with archive.open("rb") as src, dest.open("wb") as out:
        src.read(len(MAGIC))
        size = int.from_bytes(src.read(4), "big")
        head = src.read(size)
        index = 0
        while True:
            length = src.read(4)
            if not length:
                break
            blob = src.read(int.from_bytes(length, "big"))
            try:
                out.write(aes.decrypt(index.to_bytes(12, "big"), blob, head))
            except InvalidTag as exc:
                raise BackupUnreadable(
                    f"{archive.name} has been changed or damaged and can't be opened."
                ) from exc
            index += 1


def _prune(folder: Path, keep: int) -> None:
    files = sorted(folder.glob(f"*{SUFFIX}"), key=lambda p: p.stat().st_mtime, reverse=True)
    for old in files[keep:]:
        old.unlink(missing_ok=True)


def make_backup(
    paths: DesktopPaths, *, store: KeyStore, now: datetime | None = None,
) -> Path:
    """One backup, taken with the cluster STOPPED. Returns the file written."""
    now = now or datetime.now(UTC)
    config = BackupConfig.load(paths.backup_config_file)
    if config.folder is None:
        raise BackupError("No backup folder has been chosen yet.")
    if not paths.database.is_dir():
        raise BackupError("There are no books to back up yet.")
    wrap = _read_wrap(paths)
    if wrap is None:
        raise BackupError(
            "Open Hospitality needs your recovery code once before it can make a backup "
            "you could open on another computer. Enter it on the Backups page."
        )
    install_id = install_id_of(paths.sealed_keys_file)
    key = backup_key(store, install_id)
    master = read_master(paths.sealed_keys_file, store)
    salt = os.urandom(16)
    nonce = os.urandom(12)

    from usali import __version__

    manifest: dict[str, Any] = {
        "format": FORMAT,
        "install_id": install_id,
        "created_at": now.isoformat(),
        "app_version": __version__,
        "postgres_major": PG_MAJOR,
        "heads": _heads(),
    }
    header: dict[str, Any] = {
        **manifest,
        "salt": _b64(salt),
        # The master key (ADR-D5) under the backup key, so a restore can put
        # it back in the new computer's keychain.
        "master_nonce": _b64(nonce),
        "master_key": _b64(AESGCM(key).encrypt(nonce, master, install_id.encode())),
        # ...and the backup key under the owner's recovery code.
        "backup_key_wrap": wrap,
    }

    config.folder.mkdir(parents=True, exist_ok=True)
    dest = config.folder / f"Open Hospitality {now.strftime('%Y-%m-%d %H%M')}{SUFFIX}"
    staging = paths.system_root / "backup.staging.zip"
    try:
        _zip_install(paths, manifest, staging)
        _seal(staging, dest, _file_key(key, salt), header)
    finally:
        staging.unlink(missing_ok=True)
    _prune(config.folder, config.keep)
    replace(config, last_backup_at=now, last_file=dest.name, requested=False).save(
        paths.backup_config_file
    )
    _LOG.info("backup written: %s (%.1f MB)", dest, dest.stat().st_size / 1_000_000)
    return dest


def maybe_backup(
    paths: DesktopPaths, *, store: KeyStore, now: datetime | None = None, force: bool = False,
) -> Path | None:
    """The launcher's call, before the cluster starts. A backup that fails
    must never stop the owner opening their books — it is logged, loudly, and
    the app carries on."""
    now = now or datetime.now(UTC)
    config = BackupConfig.load(paths.backup_config_file)
    if not (force or config.due(now)):
        return None
    try:
        return make_backup(paths, store=store, now=now)
    except (BackupError, OSError) as exc:
        _LOG.warning("no backup taken: %s", exc)
        return None


def describe(archive: Path) -> dict[str, Any]:
    """What a backup says about itself, without opening it."""
    return _open_header(archive)


def restore(
    paths: DesktopPaths, archive: Path, *, recovery_code: str, store: KeyStore,
) -> dict[str, Any]:
    """Put a backup back on a computer with no books. Refuses to overwrite an
    existing install: a restore that replaced live books is the one mistake
    nobody could undo."""
    if paths.database.exists():
        raise BackupError(
            f"This computer already has books ({paths.database}). Restoring would replace "
            "them. If those books are empty and you want this backup instead, uninstall "
            "Open Hospitality first (Windows Settings › Apps), say Yes to deleting the "
            "books, then open the backup again."
        )
    if not archive.is_file():
        raise BackupError(f"There is no backup file at {archive}.")
    header = _open_header(archive)
    if str(header.get("postgres_major")) != PG_MAJOR:
        raise BackupError(
            f"That backup was made by a version of Open Hospitality storing its books in "
            f"PostgreSQL {header.get('postgres_major')}; this one uses {PG_MAJOR}."
        )
    wrap = header.get("backup_key_wrap") or {}
    try:
        key = AESGCM(_recovery_key(recovery_code, _un64(str(wrap["salt"])))).decrypt(
            _un64(str(wrap["nonce"])), _un64(str(wrap["wrapped"])), str(wrap["install_id"]).encode(),
        )
    except (InvalidTag, KeyError, ValueError) as exc:
        raise BackupUnreadable(
            "That recovery code doesn't open this backup. Check it against the copy you "
            "saved — dashes and capital letters don't matter — and that it is the code you "
            "had when this backup was made."
        ) from exc

    install_id = str(header["install_id"])
    paths.ensure()
    staging = paths.system_root / "restore.staging.zip"
    try:
        _unseal(archive, staging, _file_key(key, _un64(str(header["salt"]))))
        with zipfile.ZipFile(staging) as zf:
            manifest: dict[str, Any] = json.loads(zf.read("manifest.json"))
            paths.sealed_keys_file.write_bytes(zf.read("keys.sealed.json"))
            if "state.json" in zf.namelist():
                paths.state_file.write_bytes(zf.read("state.json"))
            paths.database.mkdir(parents=True, exist_ok=True)
            root = paths.database.resolve()
            for info in zf.infolist():
                if not info.filename.startswith("database/"):
                    continue
                rel = PurePosixPath(info.filename).relative_to("database")
                target = (paths.database / Path(*rel.parts)).resolve()
                # Zip entries are ours, but a path that climbs out of the
                # folder is refused rather than trusted.
                if not target.is_relative_to(root):
                    raise BackupUnreadable(f"{archive.name} holds a file path it shouldn't.")
                if info.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(info) as src, target.open("wb") as out:
                    shutil.copyfileobj(src, out)
    finally:
        staging.unlink(missing_ok=True)

    # The keychain of THIS computer now holds what the archive carried.
    master = AESGCM(key).decrypt(
        _un64(str(header["master_nonce"])), _un64(str(header["master_key"])), install_id.encode(),
    )
    store.set(entry_name(install_id), _b64(master))
    store.set(f"backup-key:{install_id}", _b64(key))
    paths.backup_wrap_file.write_text(json.dumps(wrap, indent=2), encoding="utf-8")
    _LOG.info("restored the books from %s (taken %s)", archive.name, manifest.get("created_at"))
    return manifest
