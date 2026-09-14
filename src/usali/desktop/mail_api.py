"""Reports by email: the owner's mailbox, when to look, and what came in.

    GET    /api/desktop/mail            settings, presets, and what has happened
    PUT    /api/desktop/mail            change the settings (and the password, when given)
    DELETE /api/desktop/mail/password   forget the password
    POST   /api/desktop/mail/test       connect and count recent messages — nothing is taken
    POST   /api/desktop/mail/fetch      look now
    POST   /api/desktop/mail/allow      allow a held sender, and take what was held

The password is never returned: the GET says whether one is saved. See
usali.desktop.mail for what a look does and does not do.
"""

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request
from pydantic import BaseModel, Field

from usali.auth import ORG_ADMIN, Principal, request_session_factory, require_active_org, require_grants, require_operator
from usali.desktop import mail
from usali.desktop.keystore import KeyStore
from usali.desktop.paths import DesktopPaths

_owner = require_grants(ORG_ADMIN)
router = APIRouter(dependencies=[Depends(require_operator), Depends(require_active_org)])


class PresetOut(BaseModel):
    id: str
    name: str
    host: str
    port: int
    hint: str


class HeldOut(BaseModel):
    sender: str
    count: int
    subjects: list[str]


class StatusOut(BaseModel):
    last_run_at: str | None
    last_result: str | None
    last_error: str | None
    next_run_at: str | None
    held: list[HeldOut]
    fetched: list[str]


class MailOut(BaseModel):
    enabled: bool
    preset: str
    host: str
    port: int
    username: str
    folder: str
    mode: str
    at: str
    every_hours: int
    senders: list[str]
    password_saved: bool
    presets: list[PresetOut]
    status: StatusOut


class MailIn(BaseModel):
    enabled: bool = False
    preset: str = "gmail"
    host: str = Field(default="", max_length=200)
    port: int = Field(default=993, ge=1, le=65535)
    username: str = Field(default="", max_length=200)
    folder: str = Field(default="INBOX", max_length=200)
    mode: str = "daily"
    at: str = "06:00"
    every_hours: int = Field(default=2, ge=1, le=24)
    senders: list[str] = Field(default_factory=list)
    #: Write-only, only when set or replaced. Goes to the OS keychain.
    password: str | None = Field(default=None, max_length=500)


class TestOut(BaseModel):
    messages_seen: int
    days: int


class FetchOut(BaseModel):
    fetched: int
    held_senders: int
    files: list[str]
    summary: str


class AllowIn(BaseModel):
    sender: str = Field(min_length=3, max_length=200)


def _paths(request: Request) -> DesktopPaths:
    return request.app.state.desktop_mail_paths  # type: ignore[no-any-return]


def _store(request: Request) -> KeyStore:
    return request.app.state.desktop_mail_store  # type: ignore[no-any-return]


def _intake(request: Request) -> mail.MailIntake | None:
    return request.app.state.desktop_mail_intake  # type: ignore[no-any-return]


def _status(state: mail.MailState) -> StatusOut:
    return StatusOut(
        last_run_at=state.last_run_at, last_result=state.last_result,
        last_error=state.last_error, next_run_at=state.next_run_at,
        held=[HeldOut(sender=h.sender, count=len(h.uids), subjects=list(h.subjects))
              for h in state.held],
        fetched=list(state.fetched),
    )


@router.get("/api/desktop/mail")
def settings(request: Request, _: Principal = Depends(_owner)) -> MailOut:
    with request_session_factory(request)() as session:
        got = mail.read_settings(session)
        state = mail.read_state(session)
    return MailOut(
        enabled=got.enabled, preset=got.preset, host=got.host, port=got.port,
        username=got.username, folder=got.folder, mode=got.mode, at=got.at,
        every_hours=got.every_hours, senders=list(got.senders),
        password_saved=mail.read_password(_store(request), _paths(request).sealed_keys_file)
        is not None,
        presets=[PresetOut(**p.__dict__) for p in mail.PRESETS],
        status=_status(state),
    )


def _valid_clock(value: str) -> str:
    try:
        hour, minute = (int(p) for p in value.split(":"))
    except ValueError:
        raise HTTPException(status_code=422, detail="The time should look like 06:00.") from None
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise HTTPException(status_code=422, detail="The time should look like 06:00.")
    return f"{hour:02d}:{minute:02d}"


@router.put("/api/desktop/mail")
def save(body: MailIn, request: Request, _: Principal = Depends(_owner)) -> MailOut:
    preset = next((p for p in mail.PRESETS if p.id == body.preset), None)
    if preset is None:
        raise HTTPException(status_code=422, detail="That isn't a mail service we know.")
    host = body.host.strip() or preset.host
    if body.enabled and not (host and body.username.strip()):
        raise HTTPException(
            status_code=422, detail="Fill in the mail service and the email address first."
        )
    settings_now = mail.MailSettings(
        enabled=body.enabled, preset=body.preset, host=host,
        port=body.port if body.host.strip() or preset.id == "other" else preset.port,
        username=body.username.strip(), folder=body.folder.strip() or "INBOX",
        mode="every" if body.mode == "every" else "daily",
        at=_valid_clock(body.at), every_hours=body.every_hours,
        senders=tuple(dict.fromkeys(s.strip().lower() for s in body.senders if s.strip())),
    )
    with request_session_factory(request)() as session:
        mail.write_settings(session, settings_now)
        # A changed schedule starts from now, not from the old plan.
        state = mail.read_state(session)
        planned = mail.next_run(settings_now, datetime.now()).isoformat(timespec="seconds")
        mail.write_state(session, mail.MailState(**{**state.__dict__, "next_run_at": planned}))
        if body.password:
            try:
                mail.write_password(
                    _store(request), _paths(request).sealed_keys_file, body.password
                )
            except RuntimeError as exc:
                raise HTTPException(status_code=503, detail=str(exc)) from None
        session.commit()
    return settings(request)


@router.delete("/api/desktop/mail/password", status_code=204)
def forget_password(request: Request, _: Principal = Depends(_owner)) -> None:
    mail.clear_password(_store(request), _paths(request).sealed_keys_file)


@router.post("/api/desktop/mail/test")
def test_connection(request: Request, _: Principal = Depends(_owner)) -> TestOut:
    """Sign in, open the folder, count recent messages. Takes nothing."""
    with request_session_factory(request)() as session:
        got = mail.read_settings(session)
    intake = _intake(request)
    mailbox_for = intake.mailbox_for if intake is not None else mail.open_mailbox
    try:
        box = mailbox_for(got, mail.read_password(_store(request), _paths(request).sealed_keys_file))
        seen = box.probe(since=(datetime.now() - timedelta(days=mail.FIRST_LOOK_DAYS)).date())
    except mail.MailboxError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from None
    return TestOut(messages_seen=seen, days=mail.FIRST_LOOK_DAYS)


def _look_now(request: Request) -> FetchOut:
    intake = _intake(request)
    if intake is None:
        raise HTTPException(status_code=503, detail="Email isn't running in this copy.")
    try:
        report = intake.run_once()
    except mail.MailboxError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from None
    return FetchOut(fetched=report.fetched, held_senders=report.held_senders,
                    files=list(report.files), summary=report.summary)


@router.post("/api/desktop/mail/fetch")
def fetch_now(request: Request, _: Principal = Depends(_owner)) -> FetchOut:
    return _look_now(request)


@router.post("/api/desktop/mail/allow")
def allow_sender(body: AllowIn, request: Request, _: Principal = Depends(_owner)) -> FetchOut:
    """Allow a held sender, then look again so what was held comes in."""
    sender = body.sender.strip().lower()
    with request_session_factory(request)() as session:
        got = mail.read_settings(session)
        if sender not in got.senders:
            mail.write_settings(session, mail.MailSettings(
                **{**got.__dict__, "senders": (*got.senders, sender)}
            ))
            session.commit()
    return _look_now(request)


def install(
    app: FastAPI, *, paths: DesktopPaths, store: KeyStore, intake: mail.MailIntake | None,
) -> None:
    app.state.desktop_mail_paths = paths
    app.state.desktop_mail_store = store
    app.state.desktop_mail_intake = intake
    app.include_router(router)
