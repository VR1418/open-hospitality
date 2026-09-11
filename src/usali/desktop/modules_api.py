"""The module chooser's API (PRD 5.4, ADR-D3).

    GET /api/me/modules      every module, whether it is on, and what it can't do
    PUT /api/desktop/modules  change the choice (owner only); the local server
                              reloads so the new set is actually mounted

The GET answers from what is MOUNTED in this process, not from the stored
choice: the navigation must describe what is listening, and the two only
differ for the moment between saving and the reload.
"""

from collections.abc import Callable

from fastapi import APIRouter, BackgroundTasks, Depends, FastAPI, Request
from pydantic import BaseModel

from usali.auth import ORG_ADMIN, require_active_org, require_grants, require_operator
from usali.auth import request_session_factory
from usali.desktop.modules import MODULES, resolve
from usali.desktop.settings import MODULES_KEY, write_setting


class LimitationOut(BaseModel):
    text: str
    workaround: str | None


class ModuleOut(BaseModel):
    id: str
    name: str
    summary: str
    status: str
    required: bool
    enabled: bool
    nav: list[str]
    limitations: list[LimitationOut]


class ModulesOut(BaseModel):
    modules: list[ModuleOut]
    reloading: bool = False


class ModulesIn(BaseModel):
    enabled: list[str]


def _payload(enabled: frozenset[str], *, reloading: bool = False) -> ModulesOut:
    return ModulesOut(
        reloading=reloading,
        modules=[
            ModuleOut(
                id=m.id, name=m.name, summary=m.summary, status=m.status,
                required=m.required, enabled=m.id in enabled, nav=list(m.nav),
                limitations=[
                    LimitationOut(text=lim.text, workaround=lim.workaround)
                    for lim in m.limitations
                ],
            )
            for m in MODULES
        ],
    )


router = APIRouter(dependencies=[Depends(require_operator), Depends(require_active_org)])


@router.get("/api/me/modules")
def get_modules(request: Request) -> ModulesOut:
    enabled: frozenset[str] = request.app.state.desktop_enabled_modules
    return _payload(enabled)


@router.put("/api/desktop/modules")
def put_modules(
    body: ModulesIn, request: Request, background: BackgroundTasks,
    _owner: object = Depends(require_grants(ORG_ADMIN)),
) -> ModulesOut:
    chosen = resolve(body.enabled)
    with request_session_factory(request)() as session:
        write_setting(session, MODULES_KEY, sorted(chosen))
        session.commit()
    current: frozenset[str] = request.app.state.desktop_enabled_modules
    changed = chosen != current
    if changed:
        # After the response is sent: the reload stops THIS server.
        reload: Callable[[], None] = request.app.state.desktop_reload
        background.add_task(reload)
    return _payload(chosen, reloading=changed)


def install(app: FastAPI, *, enabled: frozenset[str], reload: Callable[[], None]) -> None:
    app.state.desktop_enabled_modules = enabled
    app.state.desktop_reload = reload
    app.include_router(router)
