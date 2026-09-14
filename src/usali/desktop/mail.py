"""Night-audit reports that arrive by email (PRD M4, "connected"; phase 4).

The owner connects one mailbox — the address their front-desk system emails
the night audit to — and says when to look: every morning at a time they
choose, or every few hours. Each look takes the PDF attachments of new
messages and puts them in **Drop reports here**, the folder the app already
watches, so a report that came by email is read exactly like one dropped by
hand: same detection, same "isn't set up here yet" message, same saved files.

**Which hotel.** The report says so itself — every night audit prints the
hotel's name or code — so nothing about the sender decides that. What the
sender DOES decide is whether the report is taken at all: only senders the
owner has allowed are read. A PDF from anyone else is held, and the Email page
lists the address with an "Allow" button. The first look after setup therefore
usually ends with "held: 1 sender" and one click.

**Why the built-in IMAP client, not the Himalaya CLI the plan named.** The
plan's reason for Himalaya was bundling something proven. Trying it: it is a
separate binary to fetch, pin, ship and sign; its account file wants the
password in it or a command that prints it; and its OAuth flows need an app
registration no owner will do. Python's own `imaplib` does the one thing
needed here — list new messages, take their PDFs, read-only — with none of
that, and it is what this module uses. The mailbox is behind a small port so a
different fetcher can be dropped in without touching the rest.

**What never happens.** The mailbox is opened read-only (`BODY.PEEK`, so
nothing is even marked read). No email body is parsed for instructions,
executed, followed or shown to a model. Only PDF attachments are taken. The
password lives in the OS keychain (`mail-password:<install id>`), never in the
database, a file, a log or an error.
"""

import email
import email.utils
import imaplib
import logging
import re
import socket
import ssl
import threading
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass, field, replace
from datetime import UTC, date, datetime, time, timedelta
from email.message import Message as EmailMessage
from pathlib import Path
from typing import Any, Protocol

from sqlalchemy.orm import Session

from usali.desktop.keystore import KeyStore, install_id
from usali.desktop.settings import read_setting, write_setting

_LOG = logging.getLogger(__name__)

SETTINGS_KEY = "mail_intake"
STATE_KEY = "mail_intake_state"
#: How far back the first look reaches. A hotel setting this up wants last
#: night's report, not a year of them.
FIRST_LOOK_DAYS = 14
_UNSAFE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_TIMEOUT = 30


def password_entry(iid: str) -> str:
    return f"mail-password:{iid}"


# --- the mailbox port ------------------------------------------------------------

@dataclass(frozen=True)
class Attachment:
    name: str
    data: bytes


@dataclass(frozen=True)
class Message:
    uid: int
    sender: str
    subject: str
    sent_at: datetime | None
    #: Only the PDFs. Anything else in the message is never read.
    attachments: tuple[Attachment, ...]


class Mailbox(Protocol):
    def messages(self, *, after_uid: int, since: date) -> list[Message]:
        """Messages newer than `after_uid` and not older than `since`."""
        ...

    def messages_by_uid(self, uids: Iterable[int]) -> list[Message]:
        ...

    def probe(self, *, since: date) -> int:
        """Connect, open the folder, count messages since `since`."""
        ...


class MailboxError(RuntimeError):
    """Said in the owner's words, and never carrying the password."""


@dataclass(frozen=True)
class Preset:
    id: str
    name: str
    host: str
    port: int
    hint: str


PRESETS: tuple[Preset, ...] = (
    Preset("gmail", "Gmail / Google Workspace", "imap.gmail.com", 993,
           "Use an app password, not your normal one: Google Account › Security › "
           "2-Step Verification › App passwords. IMAP must be on in Gmail's settings."),
    Preset("yahoo", "Yahoo Mail", "imap.mail.yahoo.com", 993,
           "Use an app password: Yahoo Account Security › Generate app password."),
    Preset("icloud", "iCloud Mail", "imap.mail.me.com", 993,
           "Use an app-specific password from appleid.apple.com › Sign-In and Security."),
    Preset("other", "Another mail service (IMAP)", "", 993,
           "Your mail provider's IMAP server address and port, and the password it accepts "
           "for mail apps. Microsoft 365 and Outlook.com no longer allow this — forward "
           "the reports to a Gmail address instead."),
)


def _decode(value: object) -> str:
    if value is None:
        return ""
    parts = email.header.decode_header(str(value))
    out = []
    for text, charset in parts:
        out.append(text.decode(charset or "utf-8", "replace") if isinstance(text, bytes) else text)
    return " ".join("".join(out).split())


def _pdfs(msg: EmailMessage) -> tuple[Attachment, ...]:
    found: list[Attachment] = []
    for part in msg.walk():
        if part.get_content_maintype() == "multipart":
            continue
        name = _decode(part.get_filename())
        is_pdf = part.get_content_type() == "application/pdf" or name.lower().endswith(".pdf")
        if not is_pdf:
            continue
        payload = part.get_payload(decode=True)
        if not isinstance(payload, bytes) or not payload.startswith(b"%PDF-"):
            continue
        found.append(Attachment(name=name or "report.pdf", data=payload))
    return tuple(found)


def parse_message(uid: int, raw: bytes) -> Message:
    msg = email.message_from_bytes(raw)
    sender = email.utils.parseaddr(_decode(msg.get("From")))[1].lower()
    sent: datetime | None = None
    try:
        parsed = email.utils.parsedate_to_datetime(msg.get("Date", ""))
        sent = parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    except (TypeError, ValueError):
        sent = None
    return Message(uid=uid, sender=sender, subject=_decode(msg.get("Subject"))[:200],
                   sent_at=sent, attachments=_pdfs(msg))


class ImapMailbox:
    """The port over `imaplib`, read-only, with the errors said plainly."""

    def __init__(self, host: str, port: int, username: str, password: str,
                 folder: str = "INBOX") -> None:
        self._host, self._port, self._user, self._password = host, port, username, password
        self._folder = folder or "INBOX"

    def _open(self) -> imaplib.IMAP4_SSL:
        try:
            box = imaplib.IMAP4_SSL(self._host, self._port, timeout=_TIMEOUT,
                                    ssl_context=ssl.create_default_context())
        except (OSError, socket.timeout, ssl.SSLError) as exc:
            raise MailboxError(
                f"Couldn't reach {self._host}. Check the server address and that this "
                "computer is online."
            ) from exc
        try:
            box.login(self._user, self._password)
        except imaplib.IMAP4.error as exc:
            box.logout()
            raise MailboxError(
                "The mail service refused the sign-in. For Gmail, Yahoo and iCloud that "
                "usually means an app password is needed rather than the normal one."
            ) from exc
        status, _ = box.select(self._folder, readonly=True)
        if status != "OK":
            box.logout()
            raise MailboxError(f"There is no folder called “{self._folder}” in that mailbox.")
        return box

    @staticmethod
    def _uids(box: imaplib.IMAP4_SSL, query: str) -> list[int]:
        status, data = box.uid("SEARCH", query)
        if status != "OK" or not data or not data[0]:
            return []
        return [int(u) for u in data[0].split()]

    @staticmethod
    def _fetch(box: imaplib.IMAP4_SSL, uids: list[int]) -> list[Message]:
        out: list[Message] = []
        for uid in uids:
            status, data = box.uid("FETCH", str(uid), "(BODY.PEEK[])")
            if status != "OK" or not data:
                continue
            raw = next((d[1] for d in data if isinstance(d, tuple) and isinstance(d[1], bytes)),
                       None)
            if raw is not None:
                out.append(parse_message(uid, raw))
        return out

    def messages(self, *, after_uid: int, since: date) -> list[Message]:
        box = self._open()
        try:
            query = f"(UID {after_uid + 1}:* SINCE {since:%d-%b-%Y})"
            uids = [u for u in self._uids(box, query) if u > after_uid]
            return self._fetch(box, uids)
        finally:
            box.logout()

    def messages_by_uid(self, uids: Iterable[int]) -> list[Message]:
        wanted = sorted(set(uids))
        if not wanted:
            return []
        box = self._open()
        try:
            return self._fetch(box, wanted)
        finally:
            box.logout()

    def probe(self, *, since: date) -> int:
        box = self._open()
        try:
            return len(self._uids(box, f"(SINCE {since:%d-%b-%Y})"))
        finally:
            box.logout()


# --- what the owner chose ---------------------------------------------------------

@dataclass(frozen=True)
class MailSettings:
    enabled: bool = False
    preset: str = "gmail"
    host: str = ""
    port: int = 993
    username: str = ""
    folder: str = "INBOX"
    #: "daily" at `at`, or "every" `every_hours`.
    mode: str = "daily"
    at: str = "06:00"
    every_hours: int = 2
    #: Addresses whose PDFs are read. Anyone else's are held.
    senders: tuple[str, ...] = ()

    @property
    def ready(self) -> bool:
        return bool(self.host and self.username)


def read_settings(session: Session) -> MailSettings:
    raw = read_setting(session, SETTINGS_KEY)
    if not isinstance(raw, dict):
        return MailSettings()
    try:
        senders = tuple(str(s).lower() for s in raw.get("senders", []) if str(s).strip())
        return MailSettings(
            enabled=bool(raw.get("enabled", False)),
            preset=str(raw.get("preset", "gmail")),
            host=str(raw.get("host", "")), port=int(raw.get("port", 993)),
            username=str(raw.get("username", "")), folder=str(raw.get("folder", "INBOX")),
            mode="every" if raw.get("mode") == "every" else "daily",
            at=str(raw.get("at", "06:00")),
            every_hours=max(1, min(24, int(raw.get("every_hours", 2)))),
            senders=senders,
        )
    except (TypeError, ValueError):
        return MailSettings()


def write_settings(session: Session, settings: MailSettings) -> None:
    body = asdict(settings)
    body["senders"] = list(settings.senders)
    write_setting(session, SETTINGS_KEY, body)


def read_password(store: KeyStore, sealed: Path) -> str | None:
    iid = install_id(sealed)
    return None if iid is None else store.get(password_entry(iid))


def write_password(store: KeyStore, sealed: Path, password: str) -> None:
    iid = install_id(sealed)
    if iid is None:
        raise RuntimeError("this install has no id yet, so there is nowhere to keep the password")
    store.set(password_entry(iid), password)
    if store.get(password_entry(iid)) != password:
        store.delete(password_entry(iid))
        raise RuntimeError("this computer's password store accepted the password but did not keep it")


def clear_password(store: KeyStore, sealed: Path) -> None:
    iid = install_id(sealed)
    if iid is not None:
        store.delete(password_entry(iid))


# --- what has happened --------------------------------------------------------------

@dataclass(frozen=True)
class Held:
    sender: str
    uids: tuple[int, ...]
    subjects: tuple[str, ...]


@dataclass(frozen=True)
class MailState:
    last_uid: int = 0
    last_run_at: str | None = None
    last_result: str | None = None
    last_error: str | None = None
    next_run_at: str | None = None
    held: tuple[Held, ...] = ()
    #: Files fetched so far, newest first, for the page. Names only.
    fetched: tuple[str, ...] = field(default_factory=tuple)


def read_state(session: Session) -> MailState:
    raw = read_setting(session, STATE_KEY)
    if not isinstance(raw, dict):
        return MailState()
    try:
        held = tuple(
            Held(sender=str(h["sender"]), uids=tuple(int(u) for u in h.get("uids", [])),
                 subjects=tuple(str(s) for s in h.get("subjects", []))[:5])
            for h in raw.get("held", []) if isinstance(h, dict)
        )
        return MailState(
            last_uid=int(raw.get("last_uid", 0)),
            last_run_at=raw.get("last_run_at"), last_result=raw.get("last_result"),
            last_error=raw.get("last_error"), next_run_at=raw.get("next_run_at"),
            held=held, fetched=tuple(str(f) for f in raw.get("fetched", []))[:50],
        )
    except (TypeError, ValueError, KeyError):
        return MailState()


def write_state(session: Session, state: MailState) -> None:
    body: dict[str, Any] = asdict(state)
    body["held"] = [asdict(h) for h in state.held]
    body["fetched"] = list(state.fetched)
    write_setting(session, STATE_KEY, body)


# --- when to look ---------------------------------------------------------------------

def next_run(settings: MailSettings, after: datetime) -> datetime:
    """The next time to look, after `after` (local, naive)."""
    if settings.mode == "every":
        return after + timedelta(hours=settings.every_hours)
    try:
        hour, minute = (int(p) for p in settings.at.split(":"))
        at = time(hour, minute)
    except ValueError:
        at = time(6, 0)
    candidate = datetime.combine(after.date(), at)
    return candidate if candidate > after else candidate + timedelta(days=1)


# --- one look -----------------------------------------------------------------------------

@dataclass(frozen=True)
class FetchReport:
    fetched: int
    held_senders: int
    files: tuple[str, ...]

    @property
    def summary(self) -> str:
        parts = [f"{self.fetched} report{'' if self.fetched == 1 else 's'} fetched"]
        if self.held_senders:
            parts.append(
                f"{self.held_senders} sender{'' if self.held_senders == 1 else 's'} held — "
                "allow them on the Email page"
            )
        return "; ".join(parts) + "."


def _save(drop: Path, message: Message, attachment: Attachment) -> Path:
    name = _UNSAFE.sub("", attachment.name).strip(" .") or "report.pdf"
    if not name.lower().endswith(".pdf"):
        name += ".pdf"
    target = drop / name
    if target.exists():
        target = drop / f"{Path(name).stem} (email {message.uid}){Path(name).suffix}"
    tmp = target.with_name(f"~{target.name}.part")
    tmp.write_bytes(attachment.data)
    # The folder watch reacts to the rename, and only sees a whole file.
    tmp.replace(target)
    return target


def fetch_once(
    session: Session, mailbox: Mailbox, settings: MailSettings, drop: Path,
    *, now: datetime | None = None,
) -> FetchReport:
    """Take the PDFs of new messages from allowed senders into the drop
    folder; hold the rest by sender. Records the run either way. Commits."""
    now = now or datetime.now()
    state = read_state(session)
    allowed = set(settings.senders)
    since = (now - timedelta(days=FIRST_LOOK_DAYS)).date()
    try:
        # Held messages whose sender has since been allowed come back first.
        retry = [u for h in state.held if h.sender in allowed for u in h.uids]
        messages = mailbox.messages_by_uid(retry) if retry else []
        messages += mailbox.messages(after_uid=state.last_uid, since=since)
    except MailboxError as exc:
        write_state(session, replace(
            state, last_run_at=now.isoformat(timespec="seconds"), last_error=str(exc),
            next_run_at=next_run(settings, now).isoformat(timespec="seconds"),
        ))
        session.commit()
        raise

    drop.mkdir(parents=True, exist_ok=True)
    still_held: dict[str, Held] = {h.sender: h for h in state.held if h.sender not in allowed}
    files: list[str] = []
    last_uid = state.last_uid
    for message in messages:
        last_uid = max(last_uid, message.uid)
        if not message.attachments:
            continue
        if message.sender not in allowed:
            prior = still_held.get(message.sender)
            uids = tuple(sorted({*(prior.uids if prior else ()), message.uid}))
            subjects = tuple(dict.fromkeys([*(prior.subjects if prior else ()), message.subject]))[:5]
            still_held[message.sender] = Held(sender=message.sender, uids=uids, subjects=subjects)
            continue
        for attachment in message.attachments:
            files.append(_save(drop, message, attachment).name)
    report = FetchReport(fetched=len(files), held_senders=len(still_held), files=tuple(files))
    write_state(session, MailState(
        last_uid=last_uid, last_run_at=now.isoformat(timespec="seconds"),
        last_result=report.summary, last_error=None,
        next_run_at=next_run(settings, now).isoformat(timespec="seconds"),
        held=tuple(still_held.values()),
        fetched=tuple([*reversed(files), *state.fetched][:50]),
    ))
    session.commit()
    _LOG.info("email: %s", report.summary)
    return report


def open_mailbox(settings: MailSettings, password: str | None) -> Mailbox:
    if not settings.ready:
        raise MailboxError("Fill in the mail service and address first.")
    if not password:
        raise MailboxError("There is no password saved on this computer for that mailbox.")
    return ImapMailbox(settings.host, settings.port, settings.username, password, settings.folder)


# --- looking on the owner's schedule ------------------------------------------------------

class MailIntake:
    """Looks at the mailbox when the owner said to, in the background."""

    def __init__(
        self, session_factory: Callable[[], Session], drop: Path, *,
        store: KeyStore, sealed: Path, poll_seconds: float = 30.0,
        mailbox_for: Callable[[MailSettings, str | None], Mailbox] = open_mailbox,
    ) -> None:
        self.session_factory, self.drop = session_factory, drop
        self.store, self.sealed = store, sealed
        self.poll_seconds, self.mailbox_for = poll_seconds, mailbox_for
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="mail-intake", daemon=True)
        self._thread.start()

    def due(self, now: datetime | None = None) -> bool:
        now = now or datetime.now()
        with self.session_factory() as session:
            settings = read_settings(session)
            if not (settings.enabled and settings.ready):
                return False
            planned = read_state(session).next_run_at
        if planned is None:
            return True
        try:
            return datetime.fromisoformat(planned) <= now
        except ValueError:
            return True

    def run_once(self) -> FetchReport:
        with self.session_factory() as session:
            settings = read_settings(session)
            mailbox = self.mailbox_for(settings, read_password(self.store, self.sealed))
            return fetch_once(session, mailbox, settings, self.drop)

    def _run(self) -> None:
        while not self._stop.wait(self.poll_seconds):
            try:
                if self.due():
                    self.run_once()
            except MailboxError as exc:
                _LOG.warning("email: %s", exc)  # already recorded for the page
            except Exception:
                _LOG.exception("email: looking at the mailbox failed; will try again")

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=10)
