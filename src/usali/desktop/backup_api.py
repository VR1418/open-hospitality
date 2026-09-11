"""The Backups page's API (PRD I-6, ADR-D4).

    GET  /api/desktop/backup        where they go, when the last one was taken,
                                    what is in the folder, and whether a backup
                                    could be opened on another computer
    PUT  /api/desktop/backup        choose the folder
    POST /api/desktop/backup/arm    confirm the recovery code once, so backups
                                    carry a copy of their key wrapped under it
    POST /api/desktop/backup/now    take one at the next start

Why "at the next start": a backup is a copy of the database files taken while
the database is STOPPED (ADR-D4), and the database is running whenever this
API can answer. The launcher takes it before it starts the cluster.

Arming verifies the recovery code against the owner's stored hash before
wrapping anything. Wrapping with a mistyped code would write backups nobody
could ever open — the failure would surface years later, on the day it
mattered.
"""

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request
from pydantic import BaseModel, Field

from usali.auth import ORG_ADMIN, Principal, require_active_org, require_grants, require_operator
from usali.desktop import accounts as acct
from usali.desktop import backup
from usali.desktop.keystore import KeyStore
from usali.desktop.passwords import normalise_recovery_code, verify_secret
from usali.desktop.paths import DesktopPaths

_LOG = logging.getLogger(__name__)

_owner = require_grants(ORG_ADMIN)

# How many files the page lists. A folder holds seven by default; more than
# this and something else is writing there.
_LIST_LIMIT = 20


@dataclass(frozen=True)
class _Context:
    paths: DesktopPaths
    store: KeyStore
    sessions: acct.SessionFactory


def _ctx(request: Request) -> _Context:
    ctx: _Context = request.app.state.desktop_backup
    return ctx


class BackupFile(BaseModel):
    name: str
    size_mb: float
    taken_at: datetime | None
    app_version: str | None
    readable: bool


class BackupOut(BaseModel):
    folder: str | None
    suggested_folder: str
    last_backup_at: datetime | None
    last_file: str | None
    # True once the owner has confirmed their recovery code: only then can a
    # backup be opened on another computer.
    armed: bool
    # True when the next start will take one.
    due: bool
    keep: int
    files: list[BackupFile]


def _describe(path: Path) -> BackupFile:
    size_mb = round(path.stat().st_size / 1_000_000, 1)
    try:
        header = backup.describe(path)
    except (OSError, ValueError, backup.BackupError):
        return BackupFile(name=path.name, size_mb=size_mb, taken_at=None,
                          app_version=None, readable=False)
    taken = header.get("created_at")
    return BackupFile(
        name=path.name, size_mb=size_mb,
        taken_at=datetime.fromisoformat(str(taken)) if isinstance(taken, str) else None,
        app_version=str(header.get("app_version")) if header.get("app_version") else None,
        readable=True,
    )


def _files(folder: Path | None) -> list[BackupFile]:
    if folder is None or not folder.is_dir():
        return []
    newest = sorted(folder.glob(f"*{backup.SUFFIX}"),
                    key=lambda p: p.stat().st_mtime, reverse=True)
    return [_describe(p) for p in newest[:_LIST_LIMIT]]


router = APIRouter(dependencies=[Depends(require_operator), Depends(require_active_org)])


@router.get("/api/desktop/backup")
def get_backup(request: Request, _: Principal = Depends(_owner)) -> BackupOut:
    ctx = _ctx(request)
    config = backup.BackupConfig.load(ctx.paths.backup_config_file)
    return BackupOut(
        folder=str(config.folder) if config.folder is not None else None,
        suggested_folder=str(ctx.paths.owner_root / "Backups"),
        last_backup_at=config.last_backup_at,
        last_file=config.last_file,
        armed=ctx.paths.backup_wrap_file.is_file(),
        due=config.due(datetime.now(UTC)),
        keep=config.keep,
        files=_files(config.folder),
    )


class FolderIn(BaseModel):
    folder: str = Field(min_length=1, max_length=1000)


def _usable_folder(paths: DesktopPaths, raw: str) -> Path:
    folder = Path(raw.strip()).expanduser()
    if not folder.is_absolute():
        raise HTTPException(
            status_code=422,
            detail="Give the whole path to the folder, starting from the drive.",
        )
    resolved = folder.resolve()
    system = paths.system_root.resolve()
    if resolved == system or resolved.is_relative_to(system):
        raise HTTPException(
            status_code=422,
            detail="That's where Open Hospitality keeps your books. A backup has to go "
                   "somewhere else — a folder your cloud drive syncs is the point.",
        )
    try:
        resolved.mkdir(parents=True, exist_ok=True)
        probe = resolved / ".open-hospitality-write-test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
    except OSError as exc:
        raise HTTPException(
            status_code=422,
            detail=f"Open Hospitality can't write to that folder: {exc.strerror or exc}.",
        ) from exc
    return resolved


@router.put("/api/desktop/backup")
def put_backup(body: FolderIn, request: Request, _: Principal = Depends(_owner)) -> BackupOut:
    ctx = _ctx(request)
    folder = _usable_folder(ctx.paths, body.folder)
    config = backup.BackupConfig.load(ctx.paths.backup_config_file)
    # A folder chosen for the first time means a backup at the next start.
    backup.BackupConfig(
        folder=folder, last_backup_at=config.last_backup_at, last_file=config.last_file,
        requested=config.requested or config.folder != folder, keep=config.keep,
    ).save(ctx.paths.backup_config_file)
    return get_backup(request)


class ArmIn(BaseModel):
    recovery_code: str = Field(min_length=1, max_length=80)


class ArmOut(BaseModel):
    armed: bool


@router.post("/api/desktop/backup/arm")
def arm_backup(
    body: ArmIn, request: Request, principal: Principal = Depends(_owner),
) -> ArmOut:
    """Confirm the recovery code, then wrap the backup key with it."""
    ctx = _ctx(request)
    with ctx.sessions() as session:
        account = acct.get_account(session, principal.subject)
    if account is None or not verify_secret(
        account.recovery_code_hash, normalise_recovery_code(body.recovery_code)
    ):
        raise HTTPException(
            status_code=401,
            detail="That recovery code doesn't match the one for this account. Check it "
                   "against the copy you saved — dashes and capital letters don't matter.",
        )
    try:
        backup.write_wrap(ctx.paths, recovery_code=body.recovery_code, store=ctx.store)
    except Exception as exc:  # keychain trouble, and nothing the owner mistyped
        _LOG.warning("could not arm backups: %s", exc)
        raise HTTPException(
            status_code=503,
            detail="Open Hospitality couldn't reach this computer's password store, so "
                   "backups aren't ready yet. Try again in a moment.",
        ) from exc
    return ArmOut(armed=True)


class RequestedOut(BaseModel):
    requested: bool
    detail: str


@router.post("/api/desktop/backup/now")
def backup_now(request: Request, _: Principal = Depends(_owner)) -> RequestedOut:
    ctx = _ctx(request)
    config = backup.BackupConfig.load(ctx.paths.backup_config_file)
    if config.folder is None:
        raise HTTPException(status_code=409, detail="Choose a backup folder first.")
    backup.BackupConfig(
        folder=config.folder, last_backup_at=config.last_backup_at,
        last_file=config.last_file, requested=True, keep=config.keep,
    ).save(ctx.paths.backup_config_file)
    return RequestedOut(
        requested=True,
        # Not a delay for its own sake: the copy is taken while the database
        # is stopped, which is only true before it starts (ADR-D4).
        detail="Open Hospitality will back up the next time you start it.",
    )


def install(app: FastAPI, *, paths: DesktopPaths, store: KeyStore,
            sessions: acct.SessionFactory) -> None:
    app.state.desktop_backup = _Context(paths=paths, store=store, sessions=sessions)
    app.include_router(router)
