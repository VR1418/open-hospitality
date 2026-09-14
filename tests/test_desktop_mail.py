"""Reports by email, offline: a stand-in mailbox, the drop folder, held senders,
and when to look. Nothing here opens a network connection."""

from collections.abc import Iterable
from datetime import date, datetime
from email.message import EmailMessage
from pathlib import Path

import pytest

from usali.desktop import mail
from usali.desktop.mail import (
    Attachment,
    MailSettings,
    MailState,
    Message,
    fetch_once,
    next_run,
    parse_message,
)
from usali.desktop.settings import read_setting, write_setting

PDF = b"%PDF-1.4\n%mock night audit\n"


class FakeSession:
    """Just enough of a session: the two settings rows this module uses."""

    def __init__(self) -> None:
        self.rows: dict[str, object] = {}
        self.commits = 0

    def execute(self, stmt: object, params: dict[str, object] | None = None) -> object:
        text = str(stmt)
        params = params or {}
        if text.startswith("SELECT"):
            value = self.rows.get(str(params["k"]))

            class _R:
                def scalar(self_inner) -> object:  # noqa: N805
                    return value
            return _R()
        import json
        self.rows[str(params["k"])] = json.loads(str(params["v"]))
        return None

    def commit(self) -> None:
        self.commits += 1

    def __enter__(self) -> "FakeSession":
        return self

    def __exit__(self, *exc: object) -> None:
        return None


class MockMailbox:
    def __init__(self, messages: list[Message]) -> None:
        self.all = messages
        self.calls: list[str] = []

    def messages(self, *, after_uid: int, since: date) -> list[Message]:
        self.calls.append(f"messages>{after_uid}")
        return [m for m in self.all if m.uid > after_uid]

    def messages_by_uid(self, uids: Iterable[int]) -> list[Message]:
        wanted = set(uids)
        self.calls.append(f"by_uid{sorted(wanted)}")
        return [m for m in self.all if m.uid in wanted]

    def probe(self, *, since: date) -> int:
        return len(self.all)


def _msg(uid: int, sender: str, *names: str, subject: str = "Night audit") -> Message:
    return Message(uid=uid, sender=sender, subject=subject, sent_at=None,
                   attachments=tuple(Attachment(n, PDF) for n in names))


def test_the_settings_module_stand_in_round_trips() -> None:
    s = FakeSession()
    write_setting(s, "x", {"a": 1})  # type: ignore[arg-type]
    assert read_setting(s, "x") == {"a": 1}  # type: ignore[arg-type]


def test_pdfs_from_allowed_senders_land_in_the_drop_folder(tmp_path: Path) -> None:
    session = FakeSession()
    box = MockMailbox([
        _msg(5, "audit@pms.example.com", "All_Night_Audit_Reports_TX901.pdf"),
        _msg(6, "newsletter@example.com", "brochure.pdf"),
        _msg(7, "audit@pms.example.com", "All_Night_Audit_Reports_TX901.pdf"),  # same name
        _msg(8, "audit@pms.example.com"),  # no PDF: nothing to take
    ])
    settings = MailSettings(host="imap.example.com", username="me@example.com",
                            senders=("audit@pms.example.com",))
    report = fetch_once(session, box, settings, tmp_path / "drop",  # type: ignore[arg-type]
                        now=datetime(2026, 9, 14, 6, 0))
    assert report.fetched == 2 and report.held_senders == 1
    names = sorted(p.name for p in (tmp_path / "drop").iterdir())
    # The second file of the same name is not overwritten.
    assert names == ["All_Night_Audit_Reports_TX901 (email 7).pdf",
                     "All_Night_Audit_Reports_TX901.pdf"]
    assert all(p.read_bytes() == PDF for p in (tmp_path / "drop").iterdir())
    assert "2 reports fetched; 1 sender held" in report.summary

    state = mail.read_state(session)  # type: ignore[arg-type]
    assert state.last_uid == 8 and state.last_error is None
    [held] = state.held
    assert held.sender == "newsletter@example.com" and held.uids == (6,)
    assert state.next_run_at == "2026-09-15T06:00:00"
    assert session.commits == 1


def test_allowing_a_held_sender_brings_its_reports_in_on_the_next_look(tmp_path: Path) -> None:
    session = FakeSession()
    box = MockMailbox([_msg(6, "audit@pms.example.com", "audit.pdf")])
    nobody = MailSettings(host="h", username="u")
    first = fetch_once(session, box, nobody, tmp_path / "drop")  # type: ignore[arg-type]
    assert first.fetched == 0 and first.held_senders == 1
    assert not (tmp_path / "drop").exists() or not any((tmp_path / "drop").iterdir())

    allowed = MailSettings(host="h", username="u", senders=("audit@pms.example.com",))
    second = fetch_once(session, box, allowed, tmp_path / "drop")  # type: ignore[arg-type]
    assert second.fetched == 1 and second.held_senders == 0
    # The held message was asked for by uid; nothing newer was re-read.
    assert box.calls[-2:] == ["by_uid[6]", "messages>6"]
    assert mail.read_state(session).held == ()  # type: ignore[arg-type]


def test_a_mailbox_that_cannot_be_reached_is_recorded_and_raised(tmp_path: Path) -> None:
    class Down:
        def messages(self, *, after_uid: int, since: date) -> list[Message]:
            raise mail.MailboxError("Couldn't reach imap.example.com.")

        def messages_by_uid(self, uids: Iterable[int]) -> list[Message]:
            return []

        def probe(self, *, since: date) -> int:
            raise mail.MailboxError("no")

    session = FakeSession()
    with pytest.raises(mail.MailboxError):
        fetch_once(session, Down(), MailSettings(host="h", username="u"), tmp_path)  # type: ignore[arg-type]
    state = mail.read_state(session)  # type: ignore[arg-type]
    assert state.last_error == "Couldn't reach imap.example.com." and state.last_run_at
    assert state.next_run_at is not None  # it will try again on schedule


def test_when_to_look_next() -> None:
    daily = MailSettings(mode="daily", at="06:00")
    assert next_run(daily, datetime(2026, 9, 14, 5, 59)) == datetime(2026, 9, 14, 6, 0)
    assert next_run(daily, datetime(2026, 9, 14, 6, 0)) == datetime(2026, 9, 15, 6, 0)
    every = MailSettings(mode="every", every_hours=3)
    assert next_run(every, datetime(2026, 9, 14, 6, 0)) == datetime(2026, 9, 14, 9, 0)
    # A time that can't be read falls back to six in the morning.
    assert next_run(MailSettings(at="nonsense"), datetime(2026, 9, 14, 7, 0)) == datetime(2026, 9, 15, 6, 0)


def test_only_pdf_attachments_are_taken_from_a_real_message() -> None:
    msg = EmailMessage()
    msg["From"] = "Night Audit <Audit@PMS.example.com>"
    msg["Subject"] = "=?utf-8?q?Night_audit_=E2=80=94_TX901?="
    msg["Date"] = "Mon, 14 Sep 2026 06:00:00 +0000"
    msg.set_content("Please find the report attached. Click here to unsubscribe.")
    msg.add_attachment(PDF, maintype="application", subtype="pdf", filename="audit.pdf")
    msg.add_attachment(b"GIF89a", maintype="image", subtype="gif", filename="logo.gif")
    msg.add_attachment(b"not a pdf", maintype="application", subtype="pdf", filename="fake.pdf")
    parsed = parse_message(42, bytes(msg))
    assert parsed.sender == "audit@pms.example.com"
    assert parsed.subject == "Night audit — TX901"
    assert parsed.sent_at is not None and parsed.sent_at.year == 2026
    # The GIF is not a PDF; the "fake.pdf" does not start like one.
    assert [a.name for a in parsed.attachments] == ["audit.pdf"]


def test_the_state_and_settings_survive_a_round_trip() -> None:
    session = FakeSession()
    settings = MailSettings(enabled=True, preset="gmail", host="imap.gmail.com", port=993,
                            username="hotel@gmail.com", mode="every", every_hours=4,
                            senders=("a@b.com",))
    mail.write_settings(session, settings)  # type: ignore[arg-type]
    assert mail.read_settings(session) == settings  # type: ignore[arg-type]
    state = MailState(last_uid=9, last_result="ok", held=(mail.Held("x@y.com", (1, 2), ("s",)),),
                      fetched=("a.pdf",))
    mail.write_state(session, state)  # type: ignore[arg-type]
    assert mail.read_state(session) == state  # type: ignore[arg-type]
    # Rubbish reads as "not set up", never as an exception.
    session.rows[mail.SETTINGS_KEY] = {"port": "many"}
    assert mail.read_settings(session) == MailSettings()  # type: ignore[arg-type]


def test_the_intake_looks_only_when_due(tmp_path: Path) -> None:
    session = FakeSession()
    mail.write_settings(session, MailSettings(enabled=True, host="h", username="u"))  # type: ignore[arg-type]
    box = MockMailbox([])
    intake = mail.MailIntake(lambda: session, tmp_path, store=None, sealed=tmp_path / "x",  # type: ignore[arg-type,return-value]
                             mailbox_for=lambda s, p: box)
    assert intake.due(datetime(2026, 9, 14, 6, 0)) is True  # never looked
    mail.write_state(session, MailState(next_run_at="2026-09-15T06:00:00"))  # type: ignore[arg-type]
    assert intake.due(datetime(2026, 9, 15, 5, 59)) is False
    assert intake.due(datetime(2026, 9, 15, 6, 0)) is True
    mail.write_settings(session, MailSettings(enabled=False, host="h", username="u"))  # type: ignore[arg-type]
    assert intake.due(datetime(2026, 9, 15, 6, 0)) is False
