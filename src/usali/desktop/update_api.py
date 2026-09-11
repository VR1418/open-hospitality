"""Is there a newer version? (PRD I-5, adapted — see usali.desktop.updates.)

    GET  /api/desktop/update        what this build is, and what is published
    POST /api/desktop/update/check  ask now rather than waiting for the cache

The answer is cached in `desktop.setting`, so opening the app is not a
request. A check that could not reach the published file is a line on the
page, never an error the owner has to clear — the books do not depend on it.
"""

import logging
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, FastAPI, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from usali import __version__
from usali.auth import ORG_ADMIN, Principal, request_session_factory, require_active_org
from usali.auth import require_grants, require_operator
from usali.desktop import updates
from usali.desktop.settings import read_setting, write_setting

_LOG = logging.getLogger(__name__)

UPDATE_KEY = "update_check"

_owner = require_grants(ORG_ADMIN)


class UpdateOut(BaseModel):
    # False until someone publishes somewhere for the app to look.
    configured: bool
    current: str
    latest: str | None
    url: str | None
    notes: str | None
    checked_at: datetime | None
    error: str | None
    update_available: bool


def _out(result: updates.CheckResult) -> UpdateOut:
    return UpdateOut(
        configured=result.configured, current=result.current, latest=result.latest,
        url=result.url, notes=result.notes, checked_at=result.checked_at,
        error=result.error, update_available=result.update_available,
    )


def _remember(session: Session, result: updates.CheckResult) -> None:
    write_setting(session, UPDATE_KEY, {
        "checked_at": result.checked_at.isoformat() if result.checked_at else None,
        "latest": result.latest, "url": result.url, "notes": result.notes,
        "error": result.error,
    })


def _recall(session: Session) -> updates.CheckResult | None:
    raw = read_setting(session, UPDATE_KEY)
    if not isinstance(raw, dict):
        return None
    when = raw.get("checked_at")
    return updates.CheckResult(
        configured=updates.configured_url() is not None,
        current=__version__,
        latest=raw.get("latest"),
        url=raw.get("url"),
        notes=raw.get("notes"),
        checked_at=datetime.fromisoformat(when) if isinstance(when, str) else None,
        error=raw.get("error"),
    )


def _check_and_remember(session: Session) -> updates.CheckResult:
    result = updates.check(__version__)
    _remember(session, result)
    session.commit()
    return result


router = APIRouter(dependencies=[Depends(require_operator), Depends(require_active_org)])


@router.get("/api/desktop/update")
def get_update(request: Request, _: Principal = Depends(_owner)) -> UpdateOut:
    """The last answer, asking again only when it has gone stale."""
    if updates.configured_url() is None:
        return _out(updates.CheckResult(configured=False, current=__version__))
    with request_session_factory(request)() as session:
        cached = _recall(session)
        if cached is not None and not updates.due(cached.checked_at, datetime.now(UTC)):
            return _out(cached)
        return _out(_check_and_remember(session))


@router.post("/api/desktop/update/check")
def check_now(request: Request, _: Principal = Depends(_owner)) -> UpdateOut:
    if updates.configured_url() is None:
        return _out(updates.CheckResult(configured=False, current=__version__))
    with request_session_factory(request)() as session:
        return _out(_check_and_remember(session))


def install(app: FastAPI) -> None:
    app.include_router(router)


def cached_payload(session: Session) -> dict[str, Any] | None:
    """The stored answer, for the launcher's log line at start-up."""
    raw = read_setting(session, UPDATE_KEY)
    return raw if isinstance(raw, dict) else None
