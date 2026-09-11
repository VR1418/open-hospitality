"""Desktop sign-in, M1: a one-time launch code exchanged for a session.

M1 has no accounts yet (they are M2). The launcher — the process that
started the database and owns the tray icon — mints a random one-time code
and opens the owner's browser at ``/desktop-signin#code=…``. The page trades
the code here for a short-lived token from the local issuer. The code lives
in the URL FRAGMENT, which browsers never send to a server or put in a
Referer, and it dies on first use or after two minutes.

Two further locks, because "it only listens on localhost" is not a security
model on its own:

* Every request must name a loopback Host. A web page elsewhere can point a
  hostname it controls at 127.0.0.1 (DNS rebinding) and then read responses
  as same-origin; the Host header is what gives that away.
* No CORS headers are ever sent, so no other origin can read a response.

M2 replaces the launch code with the owner's password (ADR-D1); the
issuer, the token and everything downstream stay the same.
"""

import hashlib
import secrets
import threading
import time
from collections.abc import Callable

from fastapi import APIRouter, FastAPI, HTTPException, Request, Response
from pydantic import BaseModel, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware

from usali.desktop.identity import DesktopUser, LocalIssuer

LAUNCH_CODE_TTL_SECONDS = 120
LOOPBACK_HOSTS = ["127.0.0.1", "localhost"]

# Principle 5: no refusal without a next step.
_CODE_REFUSED = (
    "This sign-in link has already been used or has expired. Open Open Hospitality "
    "again from its icon in the menu bar (Mac) or the system tray (Windows)."
)


def _digest(code: str) -> str:
    return hashlib.sha256(code.encode()).hexdigest()


class LaunchCodes:
    """One-time codes, held only as hashes, each valid for a short window."""

    def __init__(
        self,
        ttl_seconds: float = LAUNCH_CODE_TTL_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._ttl = ttl_seconds
        self._clock = clock
        self._pending: dict[str, float] = {}
        self._lock = threading.Lock()

    def issue(self) -> str:
        code = secrets.token_urlsafe(32)
        with self._lock:
            now = self._clock()
            self._pending = {d: exp for d, exp in self._pending.items() if exp >= now}
            self._pending[_digest(code)] = now + self._ttl
        return code

    def redeem(self, code: str) -> bool:
        with self._lock:
            expiry = self._pending.pop(_digest(code), None)
            return expiry is not None and self._clock() <= expiry


class SessionRequest(BaseModel):
    code: str = Field(min_length=1, max_length=200)


class SessionResponse(BaseModel):
    access_token: str
    token_type: str = "Bearer"
    expires_in: int


router = APIRouter()


@router.post("/api/desktop/session")
def create_session(body: SessionRequest, request: Request, response: Response) -> SessionResponse:
    codes: LaunchCodes = request.app.state.desktop_launch_codes
    if not codes.redeem(body.code):
        raise HTTPException(status_code=401, detail=_CODE_REFUSED)
    issuer: LocalIssuer = request.app.state.desktop_issuer
    user: DesktopUser = request.app.state.desktop_user
    response.headers["Cache-Control"] = "no-store"
    return SessionResponse(access_token=issuer.mint(user), expires_in=issuer.ttl_seconds)


def install(app: FastAPI, *, issuer: LocalIssuer, user: DesktopUser, codes: LaunchCodes) -> None:
    """Mount desktop sign-in on an app built by `create_app`. Call BEFORE
    mounting the SPA: the SPA's catch-all mount would otherwise shadow it."""
    app.state.desktop_issuer = issuer
    app.state.desktop_user = user
    app.state.desktop_launch_codes = codes
    app.include_router(router)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=LOOPBACK_HOSTS)
