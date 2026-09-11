"""Telling the owner when a newer version exists (PRD I-5, adapted).

The PRD says "updates check on launch and install on quit". This does the
first half and stops: the app asks a published file what the latest version
is, compares it with its own, and SAYS SO, with a link. It never downloads
or installs anything.

Why the smaller promise. An installer that replaces itself has to be trusted
to do that, which means signed builds — and the app is not signed yet
(docs/desktop/SIGNING.md). The one-folder build is ~250 MB, so an update is a
whole download either way. And an update that ran a migration the owner did
not accept is exactly what I-5 forbids; a link the owner clicks when they are
ready cannot.

What is sent: nothing. It is a plain GET of a static file — no install id, no
version of theirs, no identifiers of any kind (PRD: "Telemetry: None. No
analytics, no crash reporting, no phone-home"). The answer is cached, so a
launch does not mean a request.

Where it looks: `OH_UPDATE_URL`, or nowhere. The fork has no published home
yet, so until one exists the app says update checks aren't set up rather than
inventing an address.
"""

import json
import logging
import os
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

_LOG = logging.getLogger(__name__)

UPDATE_URL_ENV = "OH_UPDATE_URL"
CHECK_EVERY = timedelta(hours=20)
TIMEOUT_SECONDS = 5.0
# A version we can compare: 1.2.3, with anything after it (rc1, +dev) ignored
# for ordering but kept for display.
_VERSION = re.compile(r"^\s*v?(\d+(?:\.\d+)*)")


class UpdateCheckFailed(RuntimeError):
    """The published file could not be read. Never fatal — the owner's books
    do not depend on it."""


@dataclass(frozen=True)
class Release:
    version: str
    url: str | None = None
    notes: str | None = None


def configured_url() -> str | None:
    """Where to ask, or None when nobody has said."""
    url = os.environ.get(UPDATE_URL_ENV, "").strip()
    return url or None


def version_parts(version: str) -> tuple[int, ...]:
    """The comparable part of a version string, or () when it isn't one."""
    found = _VERSION.match(version)
    if found is None:
        return ()
    return tuple(int(part) for part in found.group(1).split("."))


def is_newer(latest: str, current: str) -> bool:
    """Is `latest` a later version than `current`? Unreadable versions are
    never "newer": an app that nags on a typo in a published file is worse
    than one that stays quiet."""
    there, here = version_parts(latest), version_parts(current)
    if not there or not here:
        return False
    width = max(len(there), len(here))
    return there + (0,) * (width - len(there)) > here + (0,) * (width - len(here))


def fetch(url: str, *, timeout: float = TIMEOUT_SECONDS) -> Release:
    """Read the published file. It is JSON: {"version": "0.2.0", "url": …,
    "notes": …} — the shape a GitHub release asset or a static file can both
    take, so publishing does not tie the app to one host."""
    import httpx

    try:
        response = httpx.get(url, timeout=timeout, follow_redirects=True)
        response.raise_for_status()
        doc: dict[str, Any] = json.loads(response.text)
    except (httpx.HTTPError, ValueError) as exc:
        raise UpdateCheckFailed(str(exc)) from exc
    version = str(doc.get("version", "")).strip()
    if not version:
        raise UpdateCheckFailed(f"{url} doesn't say what the latest version is.")
    link = doc.get("url")
    notes = doc.get("notes")
    return Release(
        version=version,
        url=str(link) if isinstance(link, str) and link else None,
        notes=str(notes) if isinstance(notes, str) and notes else None,
    )


@dataclass(frozen=True)
class CheckResult:
    """What the Updates page shows."""

    configured: bool
    current: str
    latest: str | None = None
    url: str | None = None
    notes: str | None = None
    checked_at: datetime | None = None
    error: str | None = None

    @property
    def update_available(self) -> bool:
        return self.latest is not None and is_newer(self.latest, self.current)


def check(current: str, *, url: str | None = None, now: datetime | None = None) -> CheckResult:
    """Ask once. A failure is reported, never raised: a hotel with no internet
    must open its books exactly as one with internet does."""
    now = now or datetime.now(UTC)
    where = url if url is not None else configured_url()
    if where is None:
        return CheckResult(configured=False, current=current)
    try:
        release = fetch(where)
    except UpdateCheckFailed as exc:
        _LOG.info("update check skipped: %s", exc)
        return CheckResult(configured=True, current=current, checked_at=now, error=str(exc))
    return CheckResult(
        configured=True, current=current, latest=release.version, url=release.url,
        notes=release.notes, checked_at=now,
    )


def due(checked_at: datetime | None, now: datetime | None = None) -> bool:
    now = now or datetime.now(UTC)
    return checked_at is None or now - checked_at >= CHECK_EVERY
