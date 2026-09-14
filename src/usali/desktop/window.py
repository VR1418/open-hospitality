"""The app's own window, one copy at a time, and a desktop icon.

Reported by the owner: "it's opening in the browser — can we give the program
its own screen", and "make a desktop icon so the user can open it from there".

**Its own window.** Edge (on every copy of Windows 10 and 11) and Chrome both
have an app mode: `--app=<url>` opens a window with no tabs, no address bar
and no bookmarks — the page is the whole window. It runs in its own profile
under the install's system folder, so it never mixes with the owner's own
browsing, and it is a separate taskbar entry. When neither browser is found,
the default browser opens as before: a working tab beats no window.

A native web view (pywebview) was the alternative. It needs the main thread,
which the tray icon already has, and adds a dependency to sign and ship. App
mode gives the owner the same thing today.

**One copy at a time.** Double-clicking the icon while the app is running
must not start a second database on the same folder. The first copy holds a
lock file; a second copy that cannot take it leaves a request file beside it
and exits, and the first copy opens a window. The request carries nothing —
the running copy issues the one-time sign-in code itself, so no code is ever
written to disk.

**The desktop icon.** A packaged copy puts a shortcut on the Desktop and in
the Start menu the first time it runs, and again only if the program has
moved (the shortcut would point at nothing). One the owner deletes stays
deleted.
"""

import logging
import os
import shutil
import subprocess
import sys
import threading
import webbrowser
from collections.abc import Callable
from pathlib import Path
from typing import IO

_LOG = logging.getLogger(__name__)

APP_NAME = "Open Hospitality"
_REQUEST = "open-window.request"
_LOCK = "running.lock"
_SHORTCUTS = "shortcuts.txt"


# --- its own window ----------------------------------------------------------

def app_browser() -> Path | None:
    """Edge, else Chrome, wherever Windows put it."""
    if sys.platform != "win32":
        return None
    roots = [os.environ.get(v) for v in ("PROGRAMFILES(X86)", "PROGRAMFILES", "LOCALAPPDATA")]
    for relative in (Path("Microsoft/Edge/Application/msedge.exe"),
                     Path("Google/Chrome/Application/chrome.exe")):
        for root in roots:
            if root and (Path(root) / relative).is_file():
                return Path(root) / relative
    found = shutil.which("msedge") or shutil.which("chrome")
    return Path(found) if found else None


def open_window(url: str, profile: Path) -> None:
    """Open `url` as the app's own window, or in the default browser."""
    browser = app_browser()
    if browser is None:
        webbrowser.open(url)
        return
    profile.mkdir(parents=True, exist_ok=True)
    try:
        subprocess.Popen(  # noqa: S603 — a fixed executable and our own arguments
            [str(browser), f"--app={url}", f"--user-data-dir={profile}",
             "--no-first-run", "--no-default-browser-check", "--window-size=1440,920"],
            close_fds=True,
        )
    except OSError:
        _LOG.warning("could not open an app window; using the default browser")
        webbrowser.open(url)


# --- one copy at a time ------------------------------------------------------

class SingleInstance:
    """Held for the life of the running copy. `acquire` is False when another
    copy already holds it — that copy has then been asked to open a window."""

    def __init__(self, folder: Path) -> None:
        self.folder = folder
        self._handle: IO[bytes] | None = None
        self._stop = threading.Event()

    def acquire(self) -> bool:
        self.folder.mkdir(parents=True, exist_ok=True)
        handle = open(self.folder / _LOCK, "a+b")  # noqa: SIM115 — held until release
        try:
            _lock(handle)
        except OSError:
            handle.close()
            (self.folder / _REQUEST).touch()
            return False
        self._handle = handle
        # A request left by a copy that raced a previous shutdown is stale.
        (self.folder / _REQUEST).unlink(missing_ok=True)
        return True

    def serve(self, open_books: Callable[[], None], poll_seconds: float = 1.0) -> None:
        """Open a window whenever a second copy asks, until `release`."""
        def watch() -> None:
            request = self.folder / _REQUEST
            while not self._stop.wait(poll_seconds):
                if request.exists():
                    request.unlink(missing_ok=True)
                    try:
                        open_books()
                    except Exception:  # a window that won't open must not end the watch
                        _LOG.exception("could not open a window on request")

        threading.Thread(target=watch, name="window-requests", daemon=True).start()

    def release(self) -> None:
        self._stop.set()
        if self._handle is not None:
            self._handle.close()
            self._handle = None


def _lock(handle: IO[bytes]) -> None:
    if sys.platform == "win32":
        import msvcrt

        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
    else:
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


# --- the desktop icon --------------------------------------------------------

def ensure_shortcuts(folder: Path, target: Path | None = None) -> bool:
    """Put the icon on the Desktop and in the Start menu, once per location
    of the program. True when shortcuts were (re)made."""
    if sys.platform != "win32" or not getattr(sys, "frozen", False):
        return False  # a developer's `python -m` run is not an installed program
    exe = (target or Path(sys.executable)).resolve()
    record = folder / _SHORTCUTS
    if record.exists() and record.read_text(encoding="utf-8").strip() == str(exe):
        return False
    script = _shortcut_script(exe)
    try:
        subprocess.run(  # noqa: S603
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
             "-Command", script],
            check=True, capture_output=True, timeout=30,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError):
        _LOG.warning("could not create the desktop shortcut")
        return False
    folder.mkdir(parents=True, exist_ok=True)
    record.write_text(str(exe), encoding="utf-8")
    _LOG.info("desktop and Start menu shortcuts point at %s", exe)
    return True


def _ps_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _shortcut_script(exe: Path) -> str:
    """PowerShell that writes both .lnk files. `GetFolderPath('Desktop')`
    follows a Desktop that OneDrive has redirected, as it often has."""
    return "; ".join([
        "$shell = New-Object -ComObject WScript.Shell",
        "$places = @([Environment]::GetFolderPath('Desktop'), "
        "[Environment]::GetFolderPath('Programs'))",
        "foreach ($place in $places) { "
        f"$link = $shell.CreateShortcut((Join-Path $place {_ps_quote(APP_NAME + '.lnk')})); "
        f"$link.TargetPath = {_ps_quote(str(exe))}; "
        f"$link.WorkingDirectory = {_ps_quote(str(exe.parent))}; "
        f"$link.IconLocation = {_ps_quote(str(exe) + ',0')}; "
        "$link.Description = 'Open your hotel books'; "
        "$link.Save() }",
    ])
