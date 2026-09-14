"""The app's own window, one copy at a time, and the desktop icon."""

import subprocess
import sys
import threading
from pathlib import Path

import pytest

from usali.desktop import window
from usali.desktop.window import SingleInstance


def test_a_second_copy_asks_the_first_to_open_a_window_and_leaves(tmp_path: Path) -> None:
    first = SingleInstance(tmp_path)
    assert first.acquire() is True
    opened = threading.Event()
    first.serve(opened.set, poll_seconds=0.05)
    try:
        # Double-clicking the icon again: no second server on the same books.
        assert SingleInstance(tmp_path).acquire() is False
        assert opened.wait(2), "the running copy never opened a window"
        # The request is used up, and it carried nothing — the running copy
        # issues the sign-in code itself.
        assert not (tmp_path / "open-window.request").exists()
    finally:
        first.release()
    # Once the first copy has stopped, the next launch runs normally.
    again = SingleInstance(tmp_path)
    assert again.acquire() is True
    again.release()


def test_the_window_is_an_app_window_in_its_own_profile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    launched: list[list[str]] = []
    monkeypatch.setattr(window, "app_browser", lambda: Path("C:/Edge/msedge.exe"))
    monkeypatch.setattr(subprocess, "Popen", lambda args, **_: launched.append(args))
    window.open_window("http://127.0.0.1:8765/desktop/sign-in#code=abc", tmp_path / "window")
    [args] = launched
    assert args[0].endswith("msedge.exe")
    # No tabs, no address bar: the page is the window.
    assert "--app=http://127.0.0.1:8765/desktop/sign-in#code=abc" in args
    # Never the owner's own browsing profile.
    assert f"--user-data-dir={tmp_path / 'window'}" in args


def test_without_edge_or_chrome_it_still_opens(monkeypatch: pytest.MonkeyPatch) -> None:
    opened: list[str] = []
    monkeypatch.setattr(window, "app_browser", lambda: None)
    monkeypatch.setattr(window.webbrowser, "open", opened.append)
    window.open_window("http://127.0.0.1:1/x", Path("unused"))
    assert opened == ["http://127.0.0.1:1/x"]


def test_a_developer_run_makes_no_shortcuts(tmp_path: Path) -> None:
    # Only a packaged program is something to put on the Desktop.
    assert window.ensure_shortcuts(tmp_path) is False
    assert not (tmp_path / "shortcuts.txt").exists()


def test_the_shortcut_script_quotes_a_folder_with_an_apostrophe() -> None:
    script = window._shortcut_script(Path("C:/Users/o'brien/Open Hospitality/Open Hospitality.exe"))
    assert "o''brien" in script
    assert "GetFolderPath('Desktop')" in script and "GetFolderPath('Programs')" in script
    assert "'Open Hospitality.lnk'" in script


def test_starting_with_windows_is_only_offered_by_an_installed_copy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A developer's run, or one on separate books, has nothing to point a
    # Startup shortcut at — and must never touch this computer's Startup folder.
    assert window.startup_available() is False
    assert window.starts_with_windows() is False
    window.set_start_with_windows(True)  # a no-op, not an error
    monkeypatch.setenv("OH_DATA_DIR", r"C:\somewhere")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert window.startup_available() is False
