"""Uninstalling: the program goes, the books stay unless the owner says so."""

import sys
import threading
from pathlib import Path

import pytest

from usali.desktop import uninstall
from usali.desktop.keystore import MemoryKeyStore, entry_name
from usali.desktop.paths import DesktopPaths
from usali.desktop.window import SingleInstance


@pytest.fixture
def paths(tmp_path: Path) -> DesktopPaths:
    p = DesktopPaths(owner_root=tmp_path / "Documents" / "Open Hospitality",
                     system_root=tmp_path / "AppData" / "Open Hospitality")
    p.ensure()
    (p.system_root / "database").mkdir()
    (p.system_root / "database" / "PG_VERSION").write_text("17")
    (p.system_root / "window").mkdir()
    p.sealed_keys_file.write_text('{"install_id": "abc123"}', encoding="utf-8")
    (p.read_folder / "night audit.pdf").write_bytes(b"%PDF")
    return p


@pytest.fixture
def quiet(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Never touch this computer's real Desktop shortcuts or registry."""
    told: list[str] = []
    monkeypatch.setattr(uninstall, "remove_shortcuts", lambda: told.append("shortcuts removed"))
    monkeypatch.setattr(uninstall, "unregister", lambda: told.append("unregistered"))
    monkeypatch.setattr(uninstall, "tell", lambda title, text: told.append(text))
    monkeypatch.setattr(uninstall, "remove_program_folder_after_exit",
                        lambda folder: told.append(f"delete {folder}"))
    return told


def _answers(monkeypatch: pytest.MonkeyPatch, *answers: bool) -> list[str]:
    asked: list[str] = []
    replies = iter(answers)

    def ask(title: str, text: str, **_: object) -> bool:
        asked.append(text)
        return next(replies)

    monkeypatch.setattr(uninstall, "ask", ask)
    return asked


def test_by_default_the_books_and_reports_are_kept(
    paths: DesktopPaths, quiet: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    asked = _answers(monkeypatch, True, False)
    store = MemoryKeyStore()
    store.set(entry_name("abc123"), "master")

    assert uninstall.run(paths, store, Path(sys.executable)) == 0

    assert "shortcuts removed" in quiet and "unregistered" in quiet
    # The books: still here, and still openable.
    assert (paths.system_root / "database" / "PG_VERSION").exists()
    assert store.get(entry_name("abc123")) == "master"
    # The window's browser profile is the app's, not the owner's: it goes.
    assert not (paths.system_root / "window").exists()
    # The owner's reports are never touched, and the last message says where.
    assert (paths.read_folder / "night audit.pdf").exists()
    assert str(paths.owner_root) in quiet[-1]
    assert "kept on this computer" in quiet[-1]
    # The first question names where the reports stay.
    assert str(paths.owner_root) in asked[0]


def test_saying_no_first_changes_nothing(
    paths: DesktopPaths, quiet: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _answers(monkeypatch, False)
    assert uninstall.run(paths, MemoryKeyStore(), Path(sys.executable)) == 1
    assert quiet == []
    assert (paths.system_root / "window").exists()


def test_deleting_the_books_takes_their_keys_too_but_never_the_reports(
    paths: DesktopPaths, quiet: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    asked = _answers(monkeypatch, True, True)
    store = MemoryKeyStore()
    store.set(entry_name("abc123"), "master")
    store.set("ai-key:abc123", "sk-123")

    assert uninstall.run(paths, store, Path(sys.executable)) == 0

    assert not paths.system_root.exists()
    assert store.get(entry_name("abc123")) is None and store.get("ai-key:abc123") is None
    assert (paths.read_folder / "night audit.pdf").exists()
    assert "can't be undone" in asked[1]


def test_a_running_copy_is_asked_to_quit_first(
    paths: DesktopPaths, monkeypatch: pytest.MonkeyPatch
) -> None:
    running = SingleInstance(paths.system_root)
    assert running.acquire()
    quitting = threading.Event()

    def quit_app() -> None:
        quitting.set()
        running.release()  # what stopping the tray and the database leads to

    running.serve(lambda: None, on_quit=quit_app, poll_seconds=0.05)
    monkeypatch.setattr(uninstall.time, "sleep", lambda _: quitting.wait(2))
    assert uninstall.stop_running_app(paths, wait_seconds=5) is True
    assert quitting.is_set()


def test_a_copy_that_will_not_quit_stops_the_uninstall(
    paths: DesktopPaths, quiet: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    stuck = SingleInstance(paths.system_root)
    assert stuck.acquire()
    try:
        _answers(monkeypatch, True)
        monkeypatch.setattr(uninstall, "stop_running_app", lambda p: False)
        assert uninstall.run(paths, MemoryKeyStore(), Path(sys.executable)) == 1
        assert "still running" in quiet[-1]
        assert (paths.system_root / "database").exists()
    finally:
        stuck.release()


def test_only_an_unmistakably_packaged_folder_is_ever_deleted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A developer's run is not a packaged program: no folder at all.
    assert uninstall.program_folder(Path(sys.executable)) is None

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    app = tmp_path / "Downloads" / "Open Hospitality"
    (app / "_internal").mkdir(parents=True)
    assert uninstall.program_folder(app / "Open Hospitality.exe") == app
    # Anything else by that name, without PyInstaller's folder beside it: no.
    other = tmp_path / "Other"
    other.mkdir()
    assert uninstall.program_folder(other / "Open Hospitality.exe") is None
    assert uninstall.program_folder(app / "python.exe") is None
