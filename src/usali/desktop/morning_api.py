"""This morning: what came in overnight and what is waiting, in one answer.

    GET /api/desktop/morning   the owner's morning in four lines, and the
                               last few reports read or refused

An owner opens the app with coffee and wants four ticks: last night's
reports are in, nothing new to confirm, the bank still matches, the books
are backed up. Each of those lived on its own page; this reads them all
and says, for each, done or not, with where to go. It changes nothing.

`recent` is the intake's own record (upstream's IngestBatch rows) — the
files read into the books and the ones set aside, newest first — so the
Add reports page can say what just happened rather than only how many
files each folder holds.
"""

from datetime import date, datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, FastAPI, Request
from pydantic import BaseModel
from sqlalchemy import func, select, text

from usali.auth import (
    ORG_ADMIN,
    Principal,
    request_session_factory,
    require_active_org,
    require_grants,
    require_operator,
)
from usali.desktop.backup import BackupConfig
from usali.desktop.codes_api import DEFAULT_EDITION, list_codes
from usali.desktop.connections_api import _when
from usali.desktop.paths import DesktopPaths
from usali.models import IngestBatch, IngestionCoverage, PmsDailyFinancialStage, Property

_owner = require_grants(ORG_ADMIN)
router = APIRouter(dependencies=[Depends(require_operator), Depends(require_active_org)])

#: How many recent files the Add reports page shows.
_RECENT = 8
#: A bank statement older than this is due for another.
_STATEMENT_DUE_DAYS = 35

State = Literal["done", "todo", "attention"]


class MorningItem(BaseModel):
    id: str
    state: State
    #: One line, in the owner's words: "RTI22: last night's audit is in".
    text: str
    page: str


class RecentFile(BaseModel):
    file: str
    state: Literal["read", "unreadable"]
    #: The hotel and night the file turned out to be for; None when it
    #: could not be read that far.
    property_id: str | None
    business_date: date | None
    when: datetime
    #: Why it was set aside, in the reader's words; None when it was read.
    reason: str | None


class MorningOut(BaseModel):
    #: The night the owner is asking about — yesterday.
    last_night: date
    items: list[MorningItem]
    recent: list[RecentFile]


def _reports(session: object, last_night: date) -> MorningItem:
    rows = session.execute(  # type: ignore[attr-defined]
        select(Property.property_id, func.max(IngestionCoverage.business_date))
        .outerjoin(IngestionCoverage, IngestionCoverage.property_id == Property.property_id)
        .group_by(Property.property_id).order_by(Property.property_id)
    ).all()
    if not rows:
        return MorningItem(id="reports", state="todo", text="No hotel set up yet.",
                           page="/welcome?add=hotel")
    parts, behind = [], 0
    for code, last in rows:
        if last is None:
            behind += 1
            parts.append(f"{code}: no reports yet")
        elif last >= last_night:
            parts.append(f"{code}: last night's audit is in")
        else:
            behind += 1
            parts.append(f"{code}: nothing since {last.isoformat()}")
    return MorningItem(id="reports", state="attention" if behind else "done",
                       text="; ".join(parts), page="/upload")


def _codes(session: object) -> MorningItem:
    ids = list(session.scalars(select(Property.property_id).order_by(Property.property_id)))  # type: ignore[attr-defined]
    waiting = sum(
        1 for pid in ids
        for item in list_codes(session, pid, DEFAULT_EDITION).items
        if item.status != "confirmed"
    )
    if waiting == 0:
        return MorningItem(id="codes", state="done", text="Every code on your reports is confirmed.",
                           page="/codes")
    return MorningItem(id="codes", state="todo",
                       text=f"{waiting} code{'s' if waiting != 1 else ''} to confirm.", page="/codes")


def _bank(session: object, today: date) -> MorningItem:
    ids = list(session.scalars(select(Property.property_id).order_by(Property.property_id)))  # type: ignore[attr-defined]
    latest = dict(session.execute(text(  # type: ignore[attr-defined]
        "SELECT property_id, MAX(last_date) FROM desktop.statement GROUP BY property_id"
    )).all())
    rows = [(code, latest.get(code)) for code in ids]
    parts, due = [], 0
    for code, last in rows:
        if last is None:
            due += 1
            parts.append(f"{code}: no statement checked yet")
        elif (today - last).days > _STATEMENT_DUE_DAYS:
            due += 1
            parts.append(f"{code}: last checked to {last.isoformat()}")
        else:
            parts.append(f"{code}: checked to {last.isoformat()}")
    if not rows:
        return MorningItem(id="bank", state="todo", text="No hotel set up yet.", page="/bank")
    return MorningItem(id="bank", state="todo" if due else "done", text="; ".join(parts),
                       page="/bank")


def _backup(paths: DesktopPaths) -> MorningItem:
    cfg = BackupConfig.load(paths.backup_config_file)
    if cfg.folder is None:
        return MorningItem(id="backup", state="attention",
                           text="No backup folder chosen. If this computer is lost, so are the books.",
                           page="/backups")
    if cfg.last_backup_at is None:
        return MorningItem(id="backup", state="attention",
                           text="No backup taken yet — the first is taken next time you start Open Hospitality.",
                           page="/backups")
    return MorningItem(id="backup", state="done",
                       text=f"Backed up {_when(cfg.last_backup_at)}.", page="/backups")


def _recent(session: object) -> list[RecentFile]:
    batches = session.execute(  # type: ignore[attr-defined]
        select(IngestBatch.source_file, IngestBatch.status, IngestBatch.message,
               IngestBatch.started_at, IngestBatch.finished_at)
        .order_by(IngestBatch.started_at.desc(), IngestBatch.batch_id.desc())
        .limit(_RECENT * 4)
    ).all()
    out: list[RecentFile] = []
    seen: set[str] = set()
    for file, status, message, started, finished in batches:
        if file in seen:
            continue  # a pack makes one batch per report inside it
        seen.add(file)
        found = session.execute(  # type: ignore[attr-defined]
            select(PmsDailyFinancialStage.property_id,
                   func.max(PmsDailyFinancialStage.business_date))
            .where(PmsDailyFinancialStage.source_file == file)
            .group_by(PmsDailyFinancialStage.property_id)
        ).first()
        failed = status == "failed"
        out.append(RecentFile(
            file=file, state="unreadable" if failed else "read",
            property_id=found[0] if found else None,
            business_date=found[1] if found else None,
            when=finished or started, reason=message if failed else None,
        ))
        if len(out) == _RECENT:
            break
    return out


def _paths(request: Request) -> DesktopPaths:
    return request.app.state.desktop_morning_paths  # type: ignore[no-any-return]


@router.get("/api/desktop/morning")
def morning(request: Request, _: Principal = Depends(_owner)) -> MorningOut:
    today = date.today()
    last_night = today - timedelta(days=1)
    with request_session_factory(request)() as session:
        return MorningOut(
            last_night=last_night,
            items=[_reports(session, last_night), _codes(session), _bank(session, today),
                   _backup(_paths(request))],
            recent=_recent(session),
        )


def install(app: FastAPI, *, paths: DesktopPaths) -> None:
    app.state.desktop_morning_paths = paths
    app.include_router(router)
