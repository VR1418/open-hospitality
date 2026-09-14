"""Starting a newer version over older books asks, rather than closing."""

import pytest

from usali.desktop import app as desktop_app
from usali.desktop.bootstrap import NeedsUpgradeConsent


def _runs(monkeypatch: pytest.MonkeyPatch, answers: list[bool]) -> list[bool]:
    seen: list[bool] = []

    def fake_run(args: object) -> int:
        seen.append(args.upgrade_database)  # type: ignore[attr-defined]
        if not args.upgrade_database:  # type: ignore[attr-defined]
            raise NeedsUpgradeConsent("This version needs to update how your books are stored.")
        return 0

    monkeypatch.setattr(desktop_app, "run", fake_run)
    monkeypatch.setattr(desktop_app, "_dialogs", lambda args: True)
    monkeypatch.setattr(desktop_app.uninstall, "ask", lambda title, text: answers.pop(0))
    told: list[str] = []
    monkeypatch.setattr(desktop_app.uninstall, "tell", lambda title, text: told.append(text))
    return seen


def test_a_yes_updates_the_books_and_starts(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = _runs(monkeypatch, [True])
    assert desktop_app.main(["--no-browser"]) == 0
    assert seen == [False, True]  # refused once, then allowed


def test_a_no_leaves_the_books_alone_and_says_why(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    seen = _runs(monkeypatch, [False])
    assert desktop_app.main(["--no-browser"]) == 1
    assert seen == [False]
    assert "update how your books are stored" in capsys.readouterr().err


def test_a_console_run_is_not_interrupted_by_a_dialog(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[bool] = []

    def fake_run(args: object) -> int:
        seen.append(True)
        raise NeedsUpgradeConsent("needs the flag")

    monkeypatch.setattr(desktop_app, "run", fake_run)
    monkeypatch.setattr(desktop_app.uninstall, "ask", lambda *a: pytest.fail("a dialog in a console run"))
    assert desktop_app.main(["--no-browser", "--no-tray"]) == 1
    assert seen == [True]
