"""Taking Open Hospitality off a computer — without taking the books with it.

Asked for by the owner: "add uninstall as well". Reached three ways: Windows'
own **Settings › Apps › Installed apps** (the app registers itself there on
first run), the tray icon's **Uninstall…**, and `Open Hospitality.exe
--uninstall`.

What it removes, always: the Desktop and Start menu shortcuts, the entry in
Installed apps, the app window's browser profile, and the program folder.

What it keeps unless the owner says otherwise, in a second question whose
default answer is No: **the books** — the database, the keys that open it and
the logs, in the per-user app-data folder. Keeping them means installing again
opens the same books. Deleting them also deletes the keychain entries, because
a key for books that no longer exist is only a liability.

What it never deletes: the owner's own folder (Documents › Open Hospitality —
their reports, saved reports and anything they put there) and their backups.
Those are the owner's files, and the last screen says where they are.

The running app is asked to quit first (the same request-file mechanism as
opening a window), because Windows will not delete a folder whose program is
running, and a database stopped mid-write is how books get damaged.
"""

import logging
import shutil
import subprocess
import sys
import time
from pathlib import Path

from usali.desktop.keystore import KeyStore, entry_name, install_id
from usali.desktop.paths import APP_NAME, DesktopPaths
from usali.desktop.window import SingleInstance, remove_shortcuts

_LOG = logging.getLogger(__name__)

REGISTRY_KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\OpenHospitality"

# MessageBoxW flags.
_YESNO, _OK = 0x04, 0x00
_QUESTION, _WARNING, _INFO = 0x20, 0x30, 0x40
_DEFAULT_SECOND = 0x100
_IDYES = 6


def ask(title: str, text: str, *, warning: bool = False, default_no: bool = False) -> bool:
    if sys.platform != "win32":
        answer = input(f"{title}\n{text}\n[y/N] ").strip().lower()
        return answer in ("y", "yes")
    import ctypes

    flags = _YESNO | (_WARNING if warning else _QUESTION) | (_DEFAULT_SECOND if default_no else 0)
    return int(ctypes.windll.user32.MessageBoxW(None, text, title, flags)) == _IDYES


def tell(title: str, text: str) -> None:
    if sys.platform != "win32":
        print(f"{title}\n{text}")
        return
    import ctypes

    ctypes.windll.user32.MessageBoxW(None, text, title, _OK | _INFO)


# --- Installed apps -------------------------------------------------------------

def register(exe: Path, version: str) -> bool:
    """List the app under Settings › Apps, per user (no administrator
    rights, like the rest of the app). True when written."""
    if sys.platform != "win32" or not getattr(sys, "frozen", False):
        return False
    import winreg

    try:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, REGISTRY_KEY) as key:
            for name, value in (
                ("DisplayName", APP_NAME),
                ("DisplayVersion", version),
                ("Publisher", APP_NAME),
                ("DisplayIcon", f"{exe},0"),
                ("InstallLocation", str(exe.parent)),
                ("UninstallString", f'"{exe}" --uninstall'),
            ):
                winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)
            for name in ("NoModify", "NoRepair"):
                winreg.SetValueEx(key, name, 0, winreg.REG_DWORD, 1)
    except OSError:
        _LOG.warning("could not list the app under Installed apps")
        return False
    return True


def unregister() -> None:
    if sys.platform != "win32":
        return
    import winreg

    try:
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, REGISTRY_KEY)
    except OSError:
        pass  # not listed, which is the goal


# --- the steps --------------------------------------------------------------------

def stop_running_app(paths: DesktopPaths, wait_seconds: float = 60.0) -> bool:
    """Ask a running copy to quit, and wait until it has. True when nothing
    is running any more."""
    probe = SingleInstance(paths.system_root)
    if probe.acquire(ask_to_open=False):
        probe.release()
        return True
    SingleInstance.request_quit(paths.system_root)
    deadline = time.monotonic() + wait_seconds
    while time.monotonic() < deadline:
        time.sleep(1)
        if probe.acquire(ask_to_open=False):
            probe.release()
            return True
    return False


def delete_books(paths: DesktopPaths, store: KeyStore) -> None:
    """The database, keys and logs on this computer, and their keychain
    entries. Not the owner's folder, and not backups."""
    # The uninstaller's own log file is inside the folder being deleted.
    for handler in list(logging.root.handlers):
        name = getattr(handler, "baseFilename", None)
        if name is not None and Path(name).is_relative_to(paths.system_root):
            handler.close()
            logging.root.removeHandler(handler)
    iid = install_id(paths.sealed_keys_file)
    if iid is not None:
        for name in (entry_name(iid), f"ai-key:{iid}", f"mail-password:{iid}"):
            try:
                store.delete(name)
            except Exception:  # an entry already gone is what we want
                _LOG.debug("keychain entry %s was not there", name)
    shutil.rmtree(paths.system_root, ignore_errors=True)


def program_folder(exe: Path) -> Path | None:
    """The folder to delete — only when it is unmistakably ours: it holds this
    program and PyInstaller's `_internal` beside it. A copy run from anywhere
    else (a developer's checkout) deletes no folder at all."""
    if not getattr(sys, "frozen", False):
        return None
    folder = exe.parent
    if exe.name != f"{APP_NAME}.exe" or not (folder / "_internal").is_dir():
        return None
    if len(folder.parts) < 3:
        return None  # never a drive root or a top-level folder
    return folder


def remove_program_folder_after_exit(folder: Path) -> None:
    """This process is running from the folder, so the deleting is handed to
    a small detached command that waits for it to exit."""
    subprocess.Popen(  # noqa: S603, S607
        ["cmd.exe", "/c", f'timeout /t 3 /nobreak >nul & rmdir /s /q "{folder}"'],
        creationflags=getattr(subprocess, "DETACHED_PROCESS", 0)
        | getattr(subprocess, "CREATE_NO_WINDOW", 0),
        close_fds=True,
    )


def run(paths: DesktopPaths, store: KeyStore, exe: Path) -> int:
    if not ask(
        f"Uninstall {APP_NAME}",
        f"Remove {APP_NAME} from this computer?\n\n"
        f"Your reports and saved reports stay in:\n{paths.owner_root}\n\n"
        "Your backups are not touched.",
    ):
        return 1
    if not stop_running_app(paths):
        tell(f"Uninstall {APP_NAME}",
             f"{APP_NAME} is still running and didn't close. Quit it from the ◆ icon near "
             "the clock, then uninstall again.")
        return 1

    delete = ask(
        f"Uninstall {APP_NAME} — your books",
        "Also delete your books from this computer?\n\n"
        "Choose No to keep them: installing again opens the same books.\n\n"
        "Choose Yes only if you have a backup and your recovery code, or no longer "
        "need these books. This can't be undone.",
        warning=True, default_no=True,
    )
    if delete:
        delete_books(paths, store)
    else:
        shutil.rmtree(paths.system_root / "window", ignore_errors=True)
        (paths.system_root / "shortcuts.txt").unlink(missing_ok=True)

    remove_shortcuts()
    unregister()
    folder = program_folder(exe)
    tell(
        f"{APP_NAME} is uninstalled",
        f"{APP_NAME} has been removed."
        + ("" if delete else "\n\nYour books are kept on this computer for next time.")
        + f"\n\nYour reports are still in:\n{paths.owner_root}",
    )
    if folder is not None:
        remove_program_folder_after_exit(folder)
    return 0
