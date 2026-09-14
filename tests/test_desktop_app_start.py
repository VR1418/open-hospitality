"""Starting a newer version over older books asks, rather than closing."""

import argparse
from pathlib import Path

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


def test_a_backup_file_as_the_argument_is_a_restore(monkeypatch: pytest.MonkeyPatch) -> None:
    """Windows passes the file when a .ohbackup is double-clicked — the
    restore an owner can do without a command line."""
    seen: list[object] = []
    monkeypatch.setattr(desktop_app, "run", lambda args: seen.append(args.restore) or 0)
    assert desktop_app.main([r"C:\\Users\\pat\\Open Hospitality 2026-09-13.ohbackup"]) == 0
    assert desktop_app.main(["--restore", "a.ohbackup", "other.ohbackup"]) == 0
    assert desktop_app.main(["notes.txt"]) == 0
    assert seen == [r"C:\\Users\\pat\\Open Hospitality 2026-09-13.ohbackup", "a.ohbackup", None]


def test_the_recovery_code_is_asked_in_a_dialog_when_there_is_no_console(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    from usali.desktop.paths import DesktopPaths

    paths = DesktopPaths(owner_root=tmp_path / "o", system_root=tmp_path / "s")
    args = argparse.Namespace(no_tray=False)
    monkeypatch.setattr(desktop_app, "_dialogs", lambda args: True)
    told: list[str] = []
    monkeypatch.setattr(desktop_app.uninstall, "tell", lambda title, text: told.append(title))
    restored: list[str] = []
    monkeypatch.setattr(desktop_app.backup, "restore",
                        lambda p, a, *, recovery_code, store: restored.append(recovery_code) or {})

    monkeypatch.setattr(desktop_app.uninstall, "ask_text", lambda title, prompt: None)
    assert desktop_app._restore(paths, Path("x.ohbackup"), None, object(), args) == 1  # type: ignore[arg-type]
    assert restored == [] and told == ["Open a backup"]

    monkeypatch.setattr(desktop_app.uninstall, "ask_text", lambda title, prompt: "Z177D-WHZ9P")
    assert desktop_app._restore(paths, Path("x.ohbackup"), None, object(), args) == 0  # type: ignore[arg-type]
    assert restored == ["Z177D-WHZ9P"] and told[-1] == "Your books are back"

    # A refusal is told under the title of what was tried, not "couldn't start".
    def refuse(p: object, a: object, *, recovery_code: str, store: object) -> dict[str, object]:
        raise desktop_app.backup.BackupError("That recovery code doesn't open this backup.")

    monkeypatch.setattr(desktop_app.backup, "restore", refuse)
    assert desktop_app._restore(paths, Path("x.ohbackup"), None, object(), args) == 1  # type: ignore[arg-type]
    assert told[-1] == "Open a backup"


def test_registering_backup_files_is_a_no_op_outside_an_installed_copy() -> None:
    from usali.desktop import uninstall

    assert uninstall.register_backup_files(Path("oh.exe")) is False
    uninstall.unregister_backup_files()  # nothing to remove, nothing raised
