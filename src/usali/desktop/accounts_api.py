"""Local sign-in (PRD A-1 to A-7, ADR-D1).

Public (no session yet; loopback-only like everything else):

    GET  /api/desktop/status        does this install have an owner yet?
    POST /api/desktop/setup/owner   first run: create the owner (needs the tray's launch code)
    POST /api/desktop/signin        email + password -> session
    POST /api/desktop/setup-code    a new person sets their password with the owner's code
    POST /api/desktop/recover       the owner's recovery code -> new password, new code

Signed in:

    GET    /api/desktop/sessions         your sign-ins, per device
    DELETE /api/desktop/sessions/{id}    sign that device out
    POST   /api/desktop/signout          sign this device out
    POST   /api/desktop/password         change password (signs your other devices out)

Owner only (an org_admin grant):

    GET  /api/desktop/accounts                      people who can sign in
    POST /api/desktop/accounts/{subject}/setup-code a one-time code to hand to someone

Every refusal says what to do next (principle 5). Sign-in refusals never say
which half was wrong, so the screen can't be used to find real usernames.
"""

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

import jwt
from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import text

from usali.auth import (
    ORG_ADMIN,
    Principal,
    require_active_org,
    require_auth,
    require_grants,
    require_operator,
)
from usali.desktop import accounts as acct
from usali.desktop import backup
from usali.desktop.identity import DesktopUser, LocalIssuer
from usali.desktop.keystore import KeyStore
from usali.desktop.paths import DesktopPaths
from usali.desktop.passwords import (
    PasswordRejected,
    check_new_password,
    hash_secret,
    needs_rehash,
    new_recovery_code,
    normalise_recovery_code,
    verify_secret,
)
from usali.desktop.session_api import LaunchCodes
from usali.ratelimit import RateLimiter

# The owner's subject: the same one the first-run bootstrap granted
# org_admin to, so an M1 install keeps its books when its owner signs up.
OWNER_SUBJECT = "desktop-owner"
OWNER_ROLES = ("org_admin",)

_BAD_LOGIN = (
    "That email and password don't match. Check for typing mistakes — or, if you've "
    "forgotten your password, use your recovery code."
)
_LOCKED = (
    "Too many wrong passwords in a row. Wait 15 minutes and try again, or use your "
    "recovery code now."
)
_TOO_FAST = "Too many attempts from this computer. Wait a minute, then try again."
_LAUNCH_REFUSED = (
    "This set-up link has already been used or has expired. Open Open Hospitality again "
    "from its icon in the menu bar (Mac) or the system tray (Windows)."
)
_BAD_SETUP_CODE = (
    "That set-up code doesn't match, or it has expired. Ask the owner for a new one."
)
_BAD_RECOVERY = (
    "That recovery code doesn't match. Check it against the copy you saved when you set "
    "up Open Hospitality — dashes and capital letters don't matter."
)


class SessionChecker:
    """`session_is_live` for the verifier, with a five-second memory so a
    page load's burst of requests costs one lookup. `forget` drops a session
    at once when it is signed out, so the cache never outlives a sign-out."""

    def __init__(self, sessions: acct.SessionFactory, ttl_seconds: float = 5.0) -> None:
        self._sessions = sessions
        self._ttl = ttl_seconds
        self._seen: dict[str, tuple[float, bool]] = {}
        self._lock = threading.Lock()

    def __call__(self, session_id: str, subject: str) -> bool:
        key = f"{session_id}|{subject}"
        now = time.monotonic()
        with self._lock:
            hit = self._seen.get(key)
        if hit is not None and now - hit[0] < self._ttl:
            return hit[1]
        with self._sessions() as s:
            live = acct.session_is_live(s, session_id, subject)
            if live:
                acct.touch_session(s, session_id)
                s.commit()
        with self._lock:
            if len(self._seen) > 1000:
                self._seen.clear()
            self._seen[key] = (now, live)
        return live

    def forget(self, subject: str | None = None) -> None:
        with self._lock:
            if subject is None:
                self._seen.clear()
            else:
                self._seen = {k: v for k, v in self._seen.items()
                              if not k.endswith(f"|{subject}")}


_LOG = logging.getLogger(__name__)


@dataclass(frozen=True)
class _Context:
    issuer: LocalIssuer
    codes: LaunchCodes
    sessions: acct.SessionFactory
    org_alias: str
    checker: SessionChecker
    limiter: RateLimiter
    paths: DesktopPaths
    store: KeyStore


def _arm_backups(ctx: _Context, recovery_code: str) -> None:
    """Wrap the backup key under this recovery code (ADR-D4), so a backup can
    be opened on another computer. Called at the two moments the code exists
    in the clear. Best effort, always: a keychain hiccup must never cost the
    owner the account they were creating."""
    try:
        backup.write_wrap(ctx.paths, recovery_code=recovery_code, store=ctx.store)
    except Exception as exc:  # never fail sign-in over a backup
        _LOG.warning("backups are not armed yet: %s", exc)


def _ctx(request: Request) -> _Context:
    ctx: _Context = request.app.state.desktop_accounts
    return ctx


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "Bearer"
    expires_in: int
    recovery_code: str | None = None


def _token(ctx: _Context, s: object, account: acct.Account, device_label: str) -> TokenOut:
    session_id, expires = acct.start_session(s, account.subject, device_label)  # type: ignore[arg-type]
    ttl = max(1, int((expires - acct.now()).total_seconds()))
    user = DesktopUser(
        subject=account.subject, username=account.email or account.username,
        roles=account.roles, org_alias=ctx.org_alias,
    )
    return TokenOut(
        access_token=ctx.issuer.mint(user, session_id=session_id, ttl_seconds=ttl),
        expires_in=ttl,
    )


def _check_password(password: str, *, username: str, email: str) -> None:
    try:
        check_new_password(password, username=username, email=email)
    except PasswordRejected as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"


public = APIRouter()


class StatusOut(BaseModel):
    setup_required: bool


@public.get("/api/desktop/status")
def status(request: Request) -> StatusOut:
    with _ctx(request).sessions() as s:
        return StatusOut(setup_required=acct.count_accounts(s) == 0)


class OwnerSetupIn(BaseModel):
    code: str = Field(min_length=1, max_length=200)
    full_name: str = Field(min_length=1, max_length=200)
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(max_length=1000)
    device_label: str = Field(default="", max_length=200)


@public.post("/api/desktop/setup/owner", status_code=201)
def setup_owner(body: OwnerSetupIn, request: Request, response: Response) -> TokenOut:
    ctx = _ctx(request)
    if "@" not in body.email:
        raise HTTPException(status_code=422, detail="Enter the email address you'll sign in with.")
    # Checked BEFORE the launch code is spent: a password we refuse must not
    # cost the owner a trip back to the tray icon.
    _check_password(body.password, username=body.full_name, email=body.email)
    if not ctx.codes.redeem(body.code):
        raise HTTPException(status_code=401, detail=_LAUNCH_REFUSED)
    with ctx.sessions() as s:
        # One owner, ever: two tabs racing the first-run screen serialise here.
        s.execute(text("SELECT pg_advisory_xact_lock(hashtext('desktop-owner-setup'))"))
        if acct.count_accounts(s) > 0:
            raise HTTPException(
                status_code=409, detail="This computer already has an owner. Sign in instead."
            )
        acct.create_account(
            s, subject=OWNER_SUBJECT, username=body.email, email=body.email,
            full_name=body.full_name, roles=list(OWNER_ROLES),
            password_hash=hash_secret(body.password),
        )
        recovery = new_recovery_code()
        acct.set_recovery_code(s, OWNER_SUBJECT, recovery)
        account = acct.get_account(s, OWNER_SUBJECT)
        assert account is not None
        out = _token(ctx, s, account, body.device_label)
        s.commit()
    _arm_backups(ctx, recovery)
    _no_store(response)
    return out.model_copy(update={"recovery_code": recovery})


class SignInIn(BaseModel):
    login: str = Field(min_length=1, max_length=320)
    password: str = Field(max_length=1000)
    device_label: str = Field(default="", max_length=200)


@public.post("/api/desktop/signin")
def sign_in(body: SignInIn, request: Request, response: Response) -> TokenOut:
    ctx = _ctx(request)
    if not ctx.limiter.allow("signin"):
        raise HTTPException(status_code=429, detail=_TOO_FAST)
    with ctx.sessions() as s:
        account = acct.find_by_login(s, body.login)
        if account is not None and account.locked(acct.now()):
            raise HTTPException(status_code=429, detail=_LOCKED)
        ok = verify_secret(account.password_hash if account else None, body.password)
        if account is None or not ok or not account.enabled:
            if account is not None and account.enabled:
                acct.record_failure(s, account.subject)
                s.commit()
            raise HTTPException(status_code=401, detail=_BAD_LOGIN)
        acct.clear_failures(s, account.subject)
        if account.password_hash is not None and needs_rehash(account.password_hash):
            acct.set_password_hash(s, account.subject, hash_secret(body.password))
        out = _token(ctx, s, account, body.device_label)
        s.commit()
    _no_store(response)
    return out


class SetupCodeIn(BaseModel):
    login: str = Field(min_length=1, max_length=320)
    code: str = Field(min_length=1, max_length=40)
    new_password: str = Field(max_length=1000)
    device_label: str = Field(default="", max_length=200)


@public.post("/api/desktop/setup-code")
def redeem_setup_code(body: SetupCodeIn, request: Request, response: Response) -> TokenOut:
    ctx = _ctx(request)
    if not ctx.limiter.allow("signin"):
        raise HTTPException(status_code=429, detail=_TOO_FAST)
    typed = normalise_recovery_code(body.code).replace("-", "")
    with ctx.sessions() as s:
        account = acct.find_by_login(s, body.login)
        valid = (
            account is not None and account.enabled
            and account.setup_code_expires_at is not None
            and account.setup_code_expires_at > acct.now()
        )
        matched = verify_secret(account.setup_code_hash if account else None, typed)
        if account is None or not (valid and matched):
            raise HTTPException(status_code=401, detail=_BAD_SETUP_CODE)
        _check_password(body.new_password, username=account.username, email=account.email or "")
        acct.set_password_hash(s, account.subject, hash_secret(body.new_password))
        acct.revoke_all_sessions(s, account.subject)
        fresh = acct.get_account(s, account.subject)
        assert fresh is not None
        out = _token(ctx, s, fresh, body.device_label)
        s.commit()
    ctx.checker.forget(account.subject)
    _no_store(response)
    return out


class RecoverIn(BaseModel):
    login: str = Field(min_length=1, max_length=320)
    recovery_code: str = Field(min_length=1, max_length=80)
    new_password: str = Field(max_length=1000)
    device_label: str = Field(default="", max_length=200)


@public.post("/api/desktop/recover")
def recover(body: RecoverIn, request: Request, response: Response) -> TokenOut:
    """Works even while the account is locked: this IS the way out of it."""
    ctx = _ctx(request)
    if not ctx.limiter.allow("signin"):
        raise HTTPException(status_code=429, detail=_TOO_FAST)
    with ctx.sessions() as s:
        account = acct.find_by_login(s, body.login)
        matched = verify_secret(
            account.recovery_code_hash if account else None,
            normalise_recovery_code(body.recovery_code),
        )
        if account is None or not matched or not account.enabled:
            raise HTTPException(status_code=401, detail=_BAD_RECOVERY)
        _check_password(body.new_password, username=account.username, email=account.email or "")
        acct.set_password_hash(s, account.subject, hash_secret(body.new_password))
        acct.revoke_all_sessions(s, account.subject)
        # A used recovery code is spent: the owner gets a new one, now.
        recovery = new_recovery_code()
        acct.set_recovery_code(s, account.subject, recovery)
        fresh = acct.get_account(s, account.subject)
        assert fresh is not None
        out = _token(ctx, s, fresh, body.device_label)
        s.commit()
    ctx.checker.forget(account.subject)
    # The old code no longer opens future backups; this one does. Files
    # already written keep the wrap they were taken with.
    _arm_backups(ctx, recovery)
    _no_store(response)
    return out.model_copy(update={"recovery_code": recovery})


# ---------------------------------------------------------------- signed in

signed_in = APIRouter(dependencies=[Depends(require_operator), Depends(require_active_org)])


def _session_id(request: Request) -> str | None:
    """The caller's own session. The gates above already verified the token,
    signature and liveness included; this only reads the claim back."""
    header = request.headers.get("authorization", "")
    token = header.removeprefix("Bearer ").strip()
    try:
        sid = jwt.decode(token, options={"verify_signature": False}).get("sid")
    except jwt.PyJWTError:
        return None
    return sid if isinstance(sid, str) else None


class SessionOut(BaseModel):
    session_id: str
    device_label: str
    created_at: datetime
    last_seen_at: datetime
    current: bool


@signed_in.get("/api/desktop/sessions")
def my_sessions(request: Request, principal: Principal = Depends(require_auth)) -> list[SessionOut]:
    current = _session_id(request)
    with _ctx(request).sessions() as s:
        rows = acct.list_sessions(s, principal.subject)
    return [
        SessionOut(session_id=r.session_id, device_label=r.device_label, created_at=r.created_at,
                   last_seen_at=r.last_seen_at, current=r.session_id == current)
        for r in rows
    ]


@signed_in.delete("/api/desktop/sessions/{session_id}", status_code=204)
def sign_out_device(
    session_id: str, request: Request, principal: Principal = Depends(require_auth),
) -> Response:
    ctx = _ctx(request)
    with ctx.sessions() as s:
        found = acct.revoke_session(s, session_id, principal.subject)
        s.commit()
    if not found:
        raise HTTPException(status_code=404, detail="That sign-in has already ended.")
    ctx.checker.forget(principal.subject)
    return Response(status_code=204)


@signed_in.post("/api/desktop/signout", status_code=204)
def sign_out(request: Request, principal: Principal = Depends(require_auth)) -> Response:
    ctx = _ctx(request)
    current = _session_id(request)
    if current is not None:
        with ctx.sessions() as s:
            acct.revoke_session(s, current, principal.subject)
            s.commit()
        ctx.checker.forget(principal.subject)
    return Response(status_code=204)


class PasswordChangeIn(BaseModel):
    current_password: str = Field(max_length=1000)
    new_password: str = Field(max_length=1000)


@signed_in.post("/api/desktop/password", status_code=204)
def change_password(
    body: PasswordChangeIn, request: Request, principal: Principal = Depends(require_auth),
) -> Response:
    ctx = _ctx(request)
    with ctx.sessions() as s:
        account = acct.get_account(s, principal.subject)
        if account is None or not verify_secret(account.password_hash, body.current_password):
            raise HTTPException(status_code=401, detail="Your current password isn't right.")
        _check_password(body.new_password, username=account.username, email=account.email or "")
        acct.set_password_hash(s, account.subject, hash_secret(body.new_password))
        acct.revoke_other_sessions(s, account.subject, keep=_session_id(request))
        s.commit()
    ctx.checker.forget(principal.subject)
    return Response(status_code=204)


class AccountOut(BaseModel):
    subject: str
    full_name: str
    username: str
    email: str | None
    roles: list[str]
    enabled: bool
    has_password: bool
    is_owner: bool


@signed_in.get("/api/desktop/accounts")
def people(
    request: Request, _owner: Principal = Depends(require_grants(ORG_ADMIN)),
) -> list[AccountOut]:
    with _ctx(request).sessions() as s:
        rows = acct.list_accounts(s)
    return [
        AccountOut(subject=a.subject, full_name=a.full_name, username=a.username, email=a.email,
                   roles=list(a.roles), enabled=a.enabled, has_password=a.has_password,
                   is_owner=a.subject == OWNER_SUBJECT)
        for a in rows
    ]


class SetupCodeOut(BaseModel):
    setup_code: str
    valid_for_hours: int


@signed_in.post("/api/desktop/accounts/{subject}/setup-code")
def give_setup_code(
    subject: str, request: Request, response: Response,
    _owner: Principal = Depends(require_grants(ORG_ADMIN)),
) -> SetupCodeOut:
    if subject == OWNER_SUBJECT:
        raise HTTPException(
            status_code=409,
            detail="The owner resets their own password with their recovery code.",
        )
    with _ctx(request).sessions() as s:
        account = acct.get_account(s, subject)
        if account is None or not account.enabled:
            raise HTTPException(status_code=404, detail="That person can't sign in.")
        code = acct.issue_setup_code(s, subject)
        s.commit()
    _no_store(response)
    return SetupCodeOut(
        setup_code=code, valid_for_hours=int(acct.SETUP_CODE_TTL.total_seconds() // 3600)
    )


def install(
    app: FastAPI,
    *,
    issuer: LocalIssuer,
    codes: LaunchCodes,
    sessions: acct.SessionFactory,
    org_alias: str,
    checker: SessionChecker,
    paths: DesktopPaths,
    store: KeyStore,
) -> None:
    app.state.desktop_accounts = _Context(
        issuer=issuer, codes=codes, sessions=sessions, org_alias=org_alias, checker=checker,
        paths=paths, store=store,
        # Across every login on this computer: 30 password tries a minute is
        # plenty for a human and nothing for a guesser.
        limiter=RateLimiter(max_events=30, window_seconds=60.0),
    )
    app.include_router(public)
    app.include_router(signed_in)


def checker_for(sessions: acct.SessionFactory) -> Callable[[str, str], bool]:
    return SessionChecker(sessions)
