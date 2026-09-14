"""The schedule, made easy to fill in (PRD "Payroll & People", desktop edition).

Upstream's schedule builder (schedule_api) has templates, weeks and shifts, and
is careful about the things that matter — the payroll Monday grid, overlaps,
property confinement. What it lacks is what an owner asked for after using it:

    POST /api/desktop/rota/starter          the standard hotel shifts, ready to use
    GET  /api/desktop/rota/templates        the ready-made shifts, with "until done"
    POST /api/desktop/rota/templates        a new one (the owner's own)
    PUT  /api/desktop/rota/templates/{id}   change one — name, times, department
    POST /api/desktop/rota/copy             copy a week's shifts to another week

**"Until done."** A housekeeper's shift is "9:00 AM until the rooms are done":
it has a start and no fixed end. Upstream's shift needs an end time, and the
hours projection needs one to estimate labour, so an until-done shift keeps a
PLANNED end (9 AM–3 PM, say) and is marked so every screen and printout says
"9:00 AM – Done". The mark lives in `desktop.setting` (`rota_until_done`, a
list of template ids) rather than a column on upstream's table: the engine is
not forked for a display flag. A shift made from such a template carries the
template's id, which is how the screen knows.

**Copying a week.** Every shift of the source week lands on the same weekday
of the target week, with the same person. A person who has since left, or who
would be double-booked, is left OPEN on the copy rather than refused — the
owner is told how many, and fills them in. Nothing already on the target week
is touched.

Every write goes through upstream's own rules (`_validate_shift`,
`require_scheduler`), so a copy can never place a shift the builder would
refuse.
"""

from datetime import date, time
from typing import Annotated

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from usali.auth import Principal, request_session_factory, require_active_org, require_operator
from usali.desktop.settings import read_setting, write_setting
from usali.models import Department, Employee, Property, Schedule, Shift, ShiftTemplate
from usali.schedule_api import (
    ShiftBody,
    TemplateModel,
    _require_property_access,
    _template_model,
    _validate_shift,
    require_scheduler,
)

UNTIL_DONE_KEY = "rota_until_done"

router = APIRouter(dependencies=[Depends(require_operator), Depends(require_active_org)])

#: The shifts most hotels run. Department, name, start, end, crosses midnight,
#: until done. The owner edits or deletes any of them; they are a start, not a
#: rule.
STARTER_SHIFTS: tuple[tuple[str, str, time, time, bool, bool], ...] = (
    ("Front desk", "Morning desk", time(7, 0), time(15, 0), False, False),
    ("Front desk", "Evening desk", time(15, 0), time(23, 0), False, False),
    ("Front desk", "Night audit", time(23, 0), time(7, 0), True, False),
    ("Housekeeping", "Housekeeping", time(9, 0), time(15, 0), False, True),
    ("Housekeeping", "Laundry", time(9, 0), time(17, 0), False, False),
    ("Breakfast", "Breakfast", time(5, 0), time(11, 0), False, False),
    ("Maintenance", "Maintenance", time(8, 0), time(16, 0), False, False),
)


class RotaTemplate(TemplateModel):
    until_done: bool


class TemplateIn(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    property_id: str = Field(alias="property")
    department_id: int
    name: str = Field(min_length=1, max_length=100)
    start_time: time
    end_time: time
    crosses_midnight: bool = False
    until_done: bool = False


class TemplateEdit(BaseModel):
    department_id: int
    name: str = Field(min_length=1, max_length=100)
    start_time: time
    end_time: time
    crosses_midnight: bool = False
    until_done: bool = False


class StarterOut(BaseModel):
    departments_added: int
    shifts_added: int


class CopyIn(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    property_id: str = Field(alias="property")
    from_week_start: date
    to_week_start: date
    #: False copies the shifts as OPEN — the same coverage, nobody assigned yet.
    keep_people: bool = True


class CopyOut(BaseModel):
    schedule_id: int
    copied: int
    #: Shifts that landed OPEN because the person has left or was double-booked.
    left_open: int
    #: Shifts that could not be placed at all (a department that no longer exists).
    skipped: int


def _session(request: Request) -> Session:
    return request_session_factory(request)()


def until_done_ids(session: Session) -> set[int]:
    raw = read_setting(session, UNTIL_DONE_KEY)
    return {int(i) for i in raw} if isinstance(raw, list) else set()


def _mark_until_done(session: Session, template_id: int, flag: bool) -> None:
    ids = until_done_ids(session)
    (ids.add if flag else ids.discard)(template_id)
    write_setting(session, UNTIL_DONE_KEY, sorted(ids))


def _check_times(start: time, end: time, crosses_midnight: bool) -> None:
    if not crosses_midnight and end <= start:
        raise HTTPException(
            status_code=422,
            detail="The end has to be after the start, unless the shift runs past midnight.",
        )


def _property_here(session: Session, principal: Principal, property_id: str) -> None:
    _require_property_access(session, principal, property_id)
    if session.get(Property, property_id) is None:
        raise HTTPException(status_code=404, detail="property not found")


def _department_of(session: Session, property_id: str, department_id: int) -> Department:
    dept = session.get(Department, department_id)
    if dept is None or dept.property_id != property_id:
        raise HTTPException(status_code=422, detail="That department isn't one of this hotel's.")
    return dept


def _out(tpl: ShiftTemplate, done: set[int]) -> RotaTemplate:
    return RotaTemplate(**_template_model(tpl).model_dump(), until_done=tpl.template_id in done)


# --- the standard shifts ------------------------------------------------------

def seed_starter_shifts(session: Session, property_id: str) -> tuple[int, int]:
    """Departments and shifts most hotels run, for a hotel that has none of
    each by that name. Idempotent: run twice, adds nothing the second time.
    Does not commit."""
    depts = {
        d.name: d for d in session.scalars(
            select(Department).where(Department.property_id == property_id)
        )
    }
    names = set(session.scalars(
        select(ShiftTemplate.name).where(ShiftTemplate.property_id == property_id)
    ))
    depts_added = shifts_added = 0
    done = until_done_ids(session)
    for dept_name, name, start, end, crosses, until_done in STARTER_SHIFTS:
        dept = depts.get(dept_name)
        if dept is None:
            dept = Department(property_id=property_id, name=dept_name)
            session.add(dept)
            session.flush()
            depts[dept_name] = dept
            depts_added += 1
        if name in names:
            continue
        tpl = ShiftTemplate(
            property_id=property_id, department_id=dept.department_id, name=name,
            start_time=start, end_time=end, crosses_midnight=crosses,
        )
        session.add(tpl)
        session.flush()
        names.add(name)
        shifts_added += 1
        if until_done:
            done.add(tpl.template_id)
    write_setting(session, UNTIL_DONE_KEY, sorted(done))
    return depts_added, shifts_added


@router.post("/api/desktop/rota/starter")
def add_starter_shifts(
    request: Request,
    property_id: Annotated[str, Query(alias="property")],
    principal: Principal = Depends(require_scheduler),
) -> StarterOut:
    with _session(request) as session:
        _property_here(session, principal, property_id)
        depts, shifts = seed_starter_shifts(session, property_id)
        session.commit()
        return StarterOut(departments_added=depts, shifts_added=shifts)


# --- the ready-made shifts ------------------------------------------------------

@router.get("/api/desktop/rota/templates")
def list_templates(
    request: Request,
    property_id: Annotated[str, Query(alias="property")],
    principal: Principal = Depends(require_scheduler),
) -> list[RotaTemplate]:
    with _session(request) as session:
        _require_property_access(session, principal, property_id)
        done = until_done_ids(session)
        rows = session.scalars(
            select(ShiftTemplate)
            .where(ShiftTemplate.property_id == property_id)
            .order_by(ShiftTemplate.start_time, ShiftTemplate.name)
        ).all()
        return [_out(t, done) for t in rows]


@router.post("/api/desktop/rota/templates", status_code=201)
def create_template(
    body: TemplateIn, request: Request, principal: Principal = Depends(require_scheduler),
) -> RotaTemplate:
    _check_times(body.start_time, body.end_time, body.crosses_midnight)
    name = " ".join(body.name.split())
    with _session(request) as session:
        _property_here(session, principal, body.property_id)
        _department_of(session, body.property_id, body.department_id)
        taken = session.scalar(select(ShiftTemplate.template_id).where(
            ShiftTemplate.property_id == body.property_id,
            func.lower(ShiftTemplate.name) == name.lower(),
        ))
        if taken is not None:
            raise HTTPException(status_code=409, detail=f"There is already a shift called “{name}”.")
        tpl = ShiftTemplate(
            property_id=body.property_id, department_id=body.department_id, name=name,
            start_time=body.start_time, end_time=body.end_time,
            crosses_midnight=body.crosses_midnight,
        )
        session.add(tpl)
        session.flush()
        _mark_until_done(session, tpl.template_id, body.until_done)
        out = _out(tpl, until_done_ids(session))
        session.commit()
        return out


@router.put("/api/desktop/rota/templates/{template_id}")
def edit_template(
    template_id: int, body: TemplateEdit, request: Request,
    principal: Principal = Depends(require_scheduler),
) -> RotaTemplate:
    """Shifts already placed from this template keep their own times: a
    template is where a shift came from, not a rule it follows."""
    _check_times(body.start_time, body.end_time, body.crosses_midnight)
    name = " ".join(body.name.split())
    with _session(request) as session:
        tpl = session.get(ShiftTemplate, template_id)
        if tpl is None:
            raise HTTPException(status_code=404, detail="That shift no longer exists.")
        _require_property_access(session, principal, tpl.property_id)
        _department_of(session, tpl.property_id, body.department_id)
        taken = session.scalar(select(ShiftTemplate.template_id).where(
            ShiftTemplate.property_id == tpl.property_id,
            func.lower(ShiftTemplate.name) == name.lower(),
            ShiftTemplate.template_id != template_id,
        ))
        if taken is not None:
            raise HTTPException(status_code=409, detail=f"There is already a shift called “{name}”.")
        tpl.name, tpl.department_id = name, body.department_id
        tpl.start_time, tpl.end_time = body.start_time, body.end_time
        tpl.crosses_midnight = body.crosses_midnight
        session.flush()
        _mark_until_done(session, template_id, body.until_done)
        out = _out(tpl, until_done_ids(session))
        session.commit()
        return out


# --- copying a week -----------------------------------------------------------------

@router.post("/api/desktop/rota/copy", status_code=201)
def copy_week(
    body: CopyIn, request: Request, principal: Principal = Depends(require_scheduler),
) -> CopyOut:
    if body.from_week_start == body.to_week_start:
        raise HTTPException(status_code=422, detail="Pick a different week to copy to.")
    if (body.to_week_start - body.from_week_start).days % 7:
        raise HTTPException(status_code=422, detail="Weeks start on a Monday.")
    with _session(request) as session:
        _property_here(session, principal, body.property_id)
        source = session.scalar(select(Schedule).where(
            Schedule.property_id == body.property_id, Schedule.week_start == body.from_week_start,
        ))
        if source is None:
            raise HTTPException(status_code=404, detail="There is no schedule for that week yet.")
        target = session.scalar(select(Schedule).where(
            Schedule.property_id == body.property_id, Schedule.week_start == body.to_week_start,
        ))
        if target is None:
            # The same grid check upstream's create_week makes, by construction:
            # the source is on it and the target is whole weeks away.
            target = Schedule(property_id=body.property_id, week_start=body.to_week_start)
            session.add(target)
            session.flush()
        shift_by = body.to_week_start - body.from_week_start
        gone = set(session.scalars(select(Employee.employee_id).where(
            Employee.termination_date.is_not(None), Employee.termination_date <= body.to_week_start,
        )))
        copied = left_open = skipped = 0
        for shift in session.scalars(
            select(Shift).where(Shift.schedule_id == source.schedule_id)
            .order_by(Shift.business_date, Shift.start_time, Shift.shift_id)
        ).all():
            who = shift.employee_id if body.keep_people else None
            if who in gone:
                who = None
            proposed = ShiftBody(
                business_date=shift.business_date + shift_by, department_id=shift.department_id,
                start_time=shift.start_time, end_time=shift.end_time,
                crosses_midnight=shift.crosses_midnight, employee_id=who,
                template_id=shift.template_id,
            )
            try:
                _validate_shift(session, target, proposed)
            except HTTPException:
                if who is None:
                    skipped += 1
                    continue
                # Double-booked (or otherwise refused for this person): the
                # shift is still needed, so it is copied with nobody on it.
                proposed = proposed.model_copy(update={"employee_id": None})
                try:
                    _validate_shift(session, target, proposed)
                except HTTPException:
                    skipped += 1
                    continue
            if shift.employee_id is not None and proposed.employee_id is None and body.keep_people:
                left_open += 1
            session.add(Shift(
                schedule_id=target.schedule_id, business_date=proposed.business_date,
                department_id=proposed.department_id, start_time=proposed.start_time,
                end_time=proposed.end_time, crosses_midnight=proposed.crosses_midnight,
                employee_id=proposed.employee_id, template_id=proposed.template_id,
            ))
            session.flush()
            copied += 1
        session.commit()
        return CopyOut(
            schedule_id=target.schedule_id, copied=copied, left_open=left_open, skipped=skipped,
        )


def install(app: FastAPI) -> None:
    app.include_router(router)
