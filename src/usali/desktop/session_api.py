"""Loopback hardening and one-time launch codes for the desktop edition.

"It only listens on localhost" is not a security model on its own:

* Every request must name a loopback Host. A web page elsewhere can point a
  hostname it controls at 127.0.0.1 (DNS rebinding) and then read responses
  as same-origin; the Host header is what gives that away.
* No CORS headers are ever sent, so no other origin can read a response.

Launch codes: the launcher — the process that started the database and owns
the tray icon — mints a random one-time code and opens the browser at
``/desktop-signin#code=…``. Since M2 a code no longer buys a session (that
would bypass the password); it gates ONE thing, creating the owner account
on a new install, so only the browser the launcher opened can claim it. The
code rides in the URL FRAGMENT, which browsers never send to a server or put
in a Referer, and dies on first use or after two minutes.
"""

import hashlib
import secrets
import threading
import time
from collections.abc import Callable

from fastapi import FastAPI
from starlette.middleware.trustedhost import TrustedHostMiddleware

LAUNCH_CODE_TTL_SECONDS = 120
LOOPBACK_HOSTS = ["127.0.0.1", "localhost"]


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


def install(app: FastAPI, *, codes: LaunchCodes) -> None:
    app.state.desktop_launch_codes = codes
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=LOOPBACK_HOSTS)
