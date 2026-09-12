"""The owner's first-run wizard (PRD M2): hotel group → first hotel → fiscal
year → modules.

    GET  /api/desktop/welcome           progress, and the PMSs this install can read
    PUT  /api/desktop/welcome/group     name the hotel group
    POST /api/desktop/welcome/property  a hotel, the name its reports print, its rooms
                                        and its fiscal calendar — all or nothing
    POST /api/desktop/welcome/finish    stop sending the owner here

The modules step uses PUT /api/desktop/modules (modules_api) unchanged.

Why a desktop endpoint creates the property rather than upstream's: its only
creator, `property_registry.create_first_property`, writes no detection
alias, and `detect.detect` resolves a report's property FROM the alias — a
hotel made that way could never have a report matched to it. Upstream's
`seed_properties` writes one, but from a YAML file. So the rows are written
here, as the ORM on the request's org-bound session: the org stamp and the
RLS wall apply exactly as they do to upstream's own property-config writes
(property_config_api), and nothing in upstream changes.

A hotel arrives with everything its first report needs: without the fiscal
calendar, ingestion reads the facts but posts nothing to the ledger, and the
statement (which reads the posted journal) stays empty.
"""

import re
from datetime import date
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select, update

from usali.auth import (
    ORG_ADMIN,
    Principal,
    request_session_factory,
    require_active_org,
    require_grants,
    require_operator,
)
from usali.desktop.backup import BackupConfig
from usali.desktop.paths import DesktopPaths
from usali.desktop.settings import read_setting, write_setting
from usali.detect import supported_pms_sources
from usali.mapping.property_registry import _DEFAULT_ORG
from usali.models import (
    AuditEvent,
    FiscalCalendar,
    Organization,
    Property,
    PropertyDetectionAlias,
    RoomInventory,
)
from usali.tenancy import FOUNDING_ORG_ID

FINISHED_KEY = "welcome_finished"

# What an owner calls each PMS. SKYTOUCH is the engine's identifier for
# choiceADVANTAGE's audit pack (README, "Naming note"); a source the engine
# gains later shows under its identifier until it is named here.
PMS_NAMES: dict[str, str] = {
    "OPERA": "Oracle OPERA",
    "AUTOCLERK": "AutoClerk",
    "SKYTOUCH": "choiceADVANTAGE",
}

# `detect` matches a phrase anywhere in a report's header, so a very short
# one would claim almost every report.
_MIN_REPORT_NAME = 4

_owner = require_grants(ORG_ADMIN)


class PmsChoice(BaseModel):
    id: str
    name: str


def pms_choices() -> list[PmsChoice]:
    """The engine's own detection registry, never a parallel list (README,
    "Supported PMS sources"). Upper case: the form `detect` and the facts use."""
    ids = sorted(s.upper() for s in supported_pms_sources())
    return sorted((PmsChoice(id=i, name=PMS_NAMES.get(i, i)) for i in ids),
                  key=lambda c: c.name.lower())


class WelcomeProperty(BaseModel):
    property_id: str
    name: str
    pms_source: str
    has_fiscal_calendar: bool
    has_rooms: bool


class WelcomeOut(BaseModel):
    finished: bool
    # PRD I-6: backups are set up DURING setup, not afterwards in a
    # settings page nobody opens.
    backup_folder_set: bool
    group_name: str
    group_named: bool
    properties: list[WelcomeProperty]
    pms_choices: list[PmsChoice]


router = APIRouter(dependencies=[Depends(require_operator), Depends(require_active_org)])


@router.get("/api/desktop/welcome")
def progress(request: Request, _: Principal = Depends(_owner)) -> WelcomeOut:
    with request_session_factory(request)() as session:
        org = session.get(Organization, FOUNDING_ORG_ID)
        group_name = org.name if org is not None else ""
        props = session.scalars(select(Property).order_by(Property.property_id)).all()
        with_calendar = set(session.scalars(select(FiscalCalendar.property_id)))
        with_rooms = set(session.scalars(select(RoomInventory.property_id)))
        finished = read_setting(session, FINISHED_KEY) is True
    paths: DesktopPaths = request.app.state.desktop_welcome_paths
    return WelcomeOut(
        finished=finished,
        backup_folder_set=BackupConfig.load(paths.backup_config_file).folder is not None,
        group_name=group_name,
        # A fresh install's group carries upstream's founding name until the
        # owner gives it theirs.
        group_named=bool(group_name) and group_name != _DEFAULT_ORG,
        properties=[
            WelcomeProperty(
                property_id=p.property_id, name=p.name, pms_source=p.pms_source,
                has_fiscal_calendar=p.property_id in with_calendar,
                has_rooms=p.property_id in with_rooms,
            )
            for p in props
        ],
        pms_choices=pms_choices(),
    )


class GroupIn(BaseModel):
    name: str = Field(max_length=200)


@router.put("/api/desktop/welcome/group", status_code=204)
def name_group(body: GroupIn, request: Request, _: Principal = Depends(_owner)) -> None:
    name = " ".join(body.name.split())
    if not name:
        raise HTTPException(status_code=422, detail="Give your hotel group a name.")
    with request_session_factory(request)() as session:
        # The desktop edition holds one hotel group, the founding one
        # (LocalAccountAdmin refuses to create another). `organization` is
        # org-scoped by its own key, so the RLS wall allows only that row.
        session.execute(
            update(Organization).where(Organization.org_id == FOUNDING_ORG_ID).values(name=name)
        )
        session.commit()


class FiscalIn(BaseModel):
    calendar_type: Literal["calendar_month", "445"]
    fiscal_year_start_month: int = Field(ge=1, le=12)
    week_start_weekday: int | None = Field(default=None, ge=0, le=6)

    @model_validator(mode="after")
    def _paired(self) -> "FiscalIn":
        # The pair upstream's endpoint and the ck_fiscal_weekday_pair CHECK
        # enforce, refused here as a sentence rather than a constraint error.
        if (self.calendar_type == "445") != (self.week_start_weekday is not None):
            raise ValueError(
                "A 4-4-5 year needs the day its weeks start on, and only a 4-4-5 year has one."
            )
        return self


class PropertyIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    report_name: str = Field(min_length=1, max_length=200)
    pms_source: str = Field(min_length=1, max_length=20)
    total_rooms: int = Field(gt=0, le=100_000)
    # The owner's computer's IANA zone, sent by the browser. Optional: a bad
    # or missing one leaves upstream's column default in place.
    timezone: str = Field(default="", max_length=50)
    fiscal: FiscalIn


class PropertyOut(BaseModel):
    property_id: str
    name: str


def new_property_id(name: str, taken: set[str]) -> str:
    """A short readable code in the shape of upstream's (HISJ, SSSJ): the
    initials of a name of several words, else the start of the one word; a
    number is added on a clash."""
    words = re.findall(r"[A-Z0-9]+", name.upper())
    base = "".join(w[0] for w in words) if len(words) > 1 else (words[0][:8] if words else "")
    base = base or "HOTEL"
    candidate, n = base, 2
    while candidate in taken:
        candidate, n = f"{base}{n}", n + 1
    return candidate


def _valid_zone(zone: str) -> str | None:
    if not zone:
        return None
    try:
        ZoneInfo(zone)
    except (ZoneInfoNotFoundError, ValueError):
        return None
    return zone


@router.post("/api/desktop/welcome/property", status_code=201)
def add_property(
    body: PropertyIn, request: Request, principal: Principal = Depends(_owner),
) -> PropertyOut:
    name = " ".join(body.name.split())
    # `detect` joins the header's words with single spaces and upper-cases
    # them; the phrase is stored the same way so it matches as typed.
    phrase = " ".join(body.report_name.upper().split())
    pms = body.pms_source.upper()
    if pms not in {c.id for c in pms_choices()}:
        raise HTTPException(
            status_code=422,
            detail="Open Hospitality can't read reports from that system yet.",
        )
    if len(phrase) < _MIN_REPORT_NAME:
        raise HTTPException(
            status_code=422,
            detail="Type more of the hotel's name as your reports print it — a few letters "
                   "would match other hotels' reports too.",
        )
    with request_session_factory(request)() as session:
        # A report goes to the FIRST alias found in its header, so two
        # phrases where one contains the other would send one hotel's
        # reports to the other.
        for other, other_id in session.execute(
            select(PropertyDetectionAlias.match_phrase, PropertyDetectionAlias.property_id)
        ).all():
            known = " ".join(other.upper().split())
            if phrase in known or known in phrase:
                raise HTTPException(
                    status_code=409,
                    detail=f"Reports that say “{known}” already belong to {other_id}. Type the "
                           "hotel's name more fully, exactly as its reports print it, so the two "
                           "can't be mixed up.",
                )
        property_id = new_property_id(name, set(session.scalars(select(Property.property_id))))
        zone = _valid_zone(body.timezone)
        session.add(Property(
            property_id=property_id, name=name, pms_source=pms,
            **({"timezone": zone} if zone is not None else {}),
        ))
        # The dependants' composite FKs reference the property row.
        session.flush()
        session.add(PropertyDetectionAlias(
            property_id=property_id, pms_source=pms, match_phrase=phrase,
        ))
        # Effective from the start of last year, so a year of back reports
        # (and this year's comparison with last) has a room count in force.
        # Effective-dated upstream: a later change is a new row, not an edit.
        session.add(RoomInventory(
            property_id=property_id, effective_date=date(date.today().year - 1, 1, 1),
            total_rooms=body.total_rooms,
        ))
        session.add(FiscalCalendar(
            property_id=property_id, calendar_type=body.fiscal.calendar_type,
            fiscal_year_start_month=body.fiscal.fiscal_year_start_month,
            week_start_weekday=body.fiscal.week_start_weekday,
        ))
        session.add(AuditEvent(
            actor_subject=principal.subject, action="property_created",
            resource_type="property", resource_id=property_id,
        ))
        session.commit()
    return PropertyOut(property_id=property_id, name=name)


class FinishOut(BaseModel):
    finished: bool


@router.post("/api/desktop/welcome/finish")
def finish(request: Request, _: Principal = Depends(_owner)) -> FinishOut:
    with request_session_factory(request)() as session:
        if session.scalars(select(Property.property_id).limit(1)).first() is None:
            raise HTTPException(
                status_code=409,
                detail="Add your first hotel before finishing — every report needs a hotel "
                       "to belong to.",
            )
        write_setting(session, FINISHED_KEY, True)
        session.commit()
    return FinishOut(finished=True)


def install(app: FastAPI, *, paths: DesktopPaths) -> None:
    app.state.desktop_welcome_paths = paths
    app.include_router(router)
