"""What's connected, and what isn't — one answer for the Overview.

    GET /api/desktop/connections   every connection's state, in the owner's words
    PUT /api/desktop/startup       start Open Hospitality when Windows starts

An owner asked to "see what is connected and what is not". The pieces each
had a page and a status of their own; this reads them all — the hotels'
reports, the AI helper, reports by email, bank statements, backups, time
clocks, starting with Windows — and says for each: connected, not set up, or
needs attention, with a line of detail and where to go.

Nothing here changes anything except the start-with-Windows switch, which
adds or removes a shortcut in the owner's Startup folder.
"""

from datetime import date, datetime
from typing import Literal

from fastapi import APIRouter, Depends, FastAPI, Request
from pydantic import BaseModel
from sqlalchemy import func, select, text

from usali.auth import ORG_ADMIN, Principal, request_session_factory, require_active_org, require_grants, require_operator
from usali.desktop import mail, window
from usali.desktop.ai import catalog, config
from usali.desktop.backup import BackupConfig
from usali.desktop.keystore import KeyStore
from usali.desktop.paths import DesktopPaths
from usali.desktop.settings import read_setting
from usali.models import IngestionCoverage, KioskDevice, Property

_owner = require_grants(ORG_ADMIN)
router = APIRouter(dependencies=[Depends(require_operator), Depends(require_active_org)])

AI_CHECKED_KEY = "ai_checked"

State = Literal["connected", "not_set_up", "attention"]


class ConnectionOut(BaseModel):
    id: str
    name: str
    state: State
    #: One line an owner reads: "Claude Sonnet 5 via OpenRouter · checked 13 Sep 9:02 PM".
    detail: str
    #: Where to set it up or fix it.
    page: str


class ConnectionsOut(BaseModel):
    connections: list[ConnectionOut]


class StartupIn(BaseModel):
    enabled: bool


class StartupOut(BaseModel):
    enabled: bool
    #: False when this copy isn't installed (a developer's run): nothing to point a shortcut at.
    available: bool


def _when(value: str | datetime | None) -> str:
    """13 Sep 9:02 PM — or "never"."""
    if value is None:
        return "never"
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            return value
    else:
        parsed = value
    hour = parsed.hour % 12 or 12
    return f"{parsed.day} {parsed:%b} {hour}:{parsed:%M} {'AM' if parsed.hour < 12 else 'PM'}"


def _hotels(session: object, today: date) -> ConnectionOut:
    rows = session.execute(  # type: ignore[attr-defined]
        select(Property.property_id, Property.name, func.max(IngestionCoverage.business_date))
        .outerjoin(IngestionCoverage, IngestionCoverage.property_id == Property.property_id)
        .group_by(Property.property_id, Property.name)
        .order_by(Property.property_id)
    ).all()
    if not rows:
        return ConnectionOut(id="hotels", name="Hotels and their reports", state="not_set_up",
                             detail="No hotel set up yet.", page="/welcome?add=hotel")
    parts, stale, none = [], 0, 0
    for code, _name, last in rows:
        if last is None:
            none += 1
            parts.append(f"{code}: no reports yet")
        else:
            behind = (today - last).days
            if behind > 2:
                stale += 1
            parts.append(f"{code}: last night read {last.isoformat()}" + (f" ({behind} days ago)" if behind > 2 else ""))
    state: State = "attention" if (stale or none) else "connected"
    return ConnectionOut(id="hotels", name="Hotels and their reports", state=state,
                         detail="; ".join(parts), page="/upload")


def _ai(session: object, store: KeyStore, paths: DesktopPaths) -> ConnectionOut:
    got = config.read(session)  # type: ignore[arg-type]
    if got.provider is None:
        return ConnectionOut(id="ai", name="AI helper", state="not_set_up",
                             detail="Not set up. Optional: it suggests where charge codes belong.",
                             page="/ai")
    service = next((s.name.split(" — ")[0] for s in catalog.SERVICES
                    if s.id == catalog.infer_service(got)), got.provider)
    key = got.provider == "mock" or got.prices.local or config.read_key(store, paths.sealed_keys_file) is not None
    checked = read_setting(session, AI_CHECKED_KEY)  # type: ignore[arg-type]
    if not key:
        return ConnectionOut(id="ai", name="AI helper", state="attention",
                             detail=f"{got.model} via {service}, but no key is saved on this computer.",
                             page="/ai")
    if isinstance(checked, dict) and checked.get("model") == got.model:
        return ConnectionOut(id="ai", name="AI helper", state="connected",
                             detail=f"{got.model} via {service} · checked {_when(str(checked.get('at')))}",
                             page="/ai")
    return ConnectionOut(id="ai", name="AI helper", state="attention",
                         detail=f"{got.model} via {service} · not checked yet — press “Check it works”.",
                         page="/ai")


def _email(session: object, store: KeyStore, paths: DesktopPaths) -> ConnectionOut:
    got = mail.read_settings(session)  # type: ignore[arg-type]
    state = mail.read_state(session)  # type: ignore[arg-type]
    if not got.ready:
        return ConnectionOut(id="email", name="Reports by email", state="not_set_up",
                             detail="Not set up. Optional: collects the night audit from a mailbox.",
                             page="/email")
    if not got.enabled:
        return ConnectionOut(id="email", name="Reports by email", state="attention",
                             detail=f"{got.username} is set up but collecting is switched off.", page="/email")
    if mail.read_password(store, paths.sealed_keys_file) is None:
        return ConnectionOut(id="email", name="Reports by email", state="attention",
                             detail=f"{got.username}: no password saved on this computer.", page="/email")
    schedule = f"every morning at {got.at}" if got.mode == "daily" else f"every {got.every_hours} hours"
    if state.last_error:
        return ConnectionOut(id="email", name="Reports by email", state="attention",
                             detail=f"{got.username}, {schedule} · last look failed: {state.last_error}",
                             page="/email")
    held = f" · {len(state.held)} sender{'s' if len(state.held) != 1 else ''} waiting to be allowed" if state.held else ""
    looked = f"last look {_when(state.last_run_at)}" if state.last_run_at else "hasn't looked yet"
    nxt = f", next {_when(state.next_run_at)}" if state.next_run_at else ""
    return ConnectionOut(id="email", name="Reports by email",
                         state="attention" if (state.held or not got.senders) else "connected",
                         detail=f"{got.username}, {schedule} · {looked}{nxt} · {len(got.senders)} sender{'s' if len(got.senders) != 1 else ''} allowed{held}",
                         page="/email")


def _bank(session: object) -> ConnectionOut:
    rows = session.execute(text(  # type: ignore[attr-defined]
        "SELECT p.property_id, MAX(s.last_date) FROM property p "
        "LEFT JOIN desktop.statement s ON s.property_id = p.property_id AND s.kind = 'bank' "
        "GROUP BY p.property_id ORDER BY p.property_id"
    )).all()
    if not rows:
        return ConnectionOut(id="bank", name="Bank statements", state="not_set_up",
                             detail="No hotel set up yet.", page="/bank")
    parts = [f"{code}: to {last.isoformat()}" if last else f"{code}: none yet" for code, last in rows]
    missing = sum(1 for _, last in rows if last is None)
    return ConnectionOut(id="bank", name="Bank statements", state="connected" if not missing else "not_set_up",
                         detail="; ".join(parts), page="/bank")


def _backups(paths: DesktopPaths) -> ConnectionOut:
    cfg = BackupConfig.load(paths.backup_config_file)
    if cfg.folder is None:
        return ConnectionOut(id="backups", name="Backups", state="attention",
                             detail="No backup folder chosen. If this computer is lost, so are the books.",
                             page="/backups")
    armed = paths.backup_wrap_file.is_file()
    if not armed:
        return ConnectionOut(id="backups", name="Backups", state="attention",
                             detail=f"Folder chosen ({cfg.folder}) but not armed: confirm your recovery code.",
                             page="/backups")
    return ConnectionOut(id="backups", name="Backups", state="connected",
                         detail=f"{cfg.folder} · last backup {_when(cfg.last_backup_at)}", page="/backups")


def _clocks(session: object) -> ConnectionOut:
    rows = session.execute(  # type: ignore[attr-defined]
        select(KioskDevice.property_id, func.count()).where(KioskDevice.revoked_at.is_(None))
        .group_by(KioskDevice.property_id).order_by(KioskDevice.property_id)
    ).all()
    if not rows:
        return ConnectionOut(id="clocks", name="Time clocks", state="not_set_up",
                             detail="No tablet enrolled. Optional: staff punch in and out on one.",
                             page="/kiosk-devices")
    return ConnectionOut(id="clocks", name="Time clocks", state="connected",
                         detail="; ".join(f"{code}: {n} tablet{'s' if n != 1 else ''}" for code, n in rows),
                         page="/kiosk-devices")


def _startup() -> ConnectionOut:
    if not window.startup_available():
        return ConnectionOut(id="startup", name="Starts with Windows", state="not_set_up",
                             detail="Not an installed copy.", page="/email")
    on = window.starts_with_windows()
    return ConnectionOut(id="startup", name="Starts with Windows", state="connected" if on else "attention",
                         detail="Open Hospitality starts when you sign in to Windows, so scheduled looks happen."
                         if on else "Off: the morning email look only happens while the app is open.",
                         page="/email")


def _paths(request: Request) -> DesktopPaths:
    return request.app.state.desktop_connections_paths  # type: ignore[no-any-return]


def _store(request: Request) -> KeyStore:
    return request.app.state.desktop_connections_store  # type: ignore[no-any-return]


@router.get("/api/desktop/connections")
def connections(request: Request, _: Principal = Depends(_owner)) -> ConnectionsOut:
    paths, store = _paths(request), _store(request)
    with request_session_factory(request)() as session:
        return ConnectionsOut(connections=[
            _hotels(session, date.today()),
            _ai(session, store, paths),
            _email(session, store, paths),
            _bank(session),
            _backups(paths),
            _clocks(session),
            _startup(),
        ])


@router.get("/api/desktop/startup")
def startup(_: Principal = Depends(_owner)) -> StartupOut:
    return StartupOut(enabled=window.starts_with_windows(), available=window.startup_available())


@router.put("/api/desktop/startup")
def set_startup(body: StartupIn, _: Principal = Depends(_owner)) -> StartupOut:
    window.set_start_with_windows(body.enabled)
    return StartupOut(enabled=window.starts_with_windows(), available=window.startup_available())


def install(app: FastAPI, *, paths: DesktopPaths, store: KeyStore) -> None:
    app.state.desktop_connections_paths = paths
    app.state.desktop_connections_store = store
    app.include_router(router)
