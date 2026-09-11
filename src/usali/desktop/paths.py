"""Where the desktop edition keeps things on the owner's computer.

Two roots, on purpose:

* The OWNER'S FOLDER (default ``Documents/Open Hospitality``) is what the
  owner sees, names and copies: the folder they drop reports into, the
  reports we read, the ones we couldn't, and — from M3 — the nightly
  backups. PRD I-3.
* The SYSTEM FOLDER (the OS's per-user app-data directory) holds the live
  database cluster, keys and logs. A running Postgres data directory must
  never sit in a folder a cloud drive syncs: Documents is OneDrive-redirected
  on many Windows installs and iCloud-synced on many Macs, and a sync client
  copying half-written WAL files is how a database gets corrupted — silently,
  and on the one machine holding the books. The owner's portable copy is the
  backup (M3), which is a consistent snapshot rather than the live files.

``OH_DATA_DIR`` puts both roots under one directory (developers, tests).
"""

import os
import sys
from dataclasses import dataclass
from pathlib import Path

APP_NAME = "Open Hospitality"


def _documents_dir() -> Path:
    if sys.platform == "win32":
        # Ask the shell: a redirected Documents (OneDrive, a network share)
        # is NOT at ~/Documents, and that path may not even exist.
        import ctypes
        from ctypes import wintypes

        buf = ctypes.create_unicode_buffer(wintypes.MAX_PATH)
        csidl_personal, shgfp_type_current = 5, 0
        windll = getattr(ctypes, "windll")  # absent off Windows; keeps mypy portable
        if windll.shell32.SHGetFolderPathW(
            None, csidl_personal, None, shgfp_type_current, buf
        ) == 0 and buf.value:
            return Path(buf.value)
    return Path.home() / "Documents"


def _system_dir() -> Path:
    if sys.platform == "win32":
        local = os.environ.get("LOCALAPPDATA")
        base = Path(local) if local else Path.home() / "AppData" / "Local"
        return base / APP_NAME
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_NAME
    xdg = os.environ.get("XDG_DATA_HOME")
    return (Path(xdg) if xdg else Path.home() / ".local" / "share") / "open-hospitality"


@dataclass(frozen=True)
class DesktopPaths:
    owner_root: Path
    system_root: Path

    @classmethod
    def default(cls) -> "DesktopPaths":
        override = os.environ.get("OH_DATA_DIR")
        if override:
            root = Path(override).expanduser().resolve()
            return cls(owner_root=root, system_root=root / "system")
        return cls(owner_root=_documents_dir() / APP_NAME, system_root=_system_dir())

    # -- the owner's folder: plain-language names (PRD appendix A) ----------

    @property
    def drop_folder(self) -> Path:
        return self.owner_root / "Drop reports here"

    @property
    def read_folder(self) -> Path:
        return self.owner_root / "Reports we read"

    @property
    def unreadable_folder(self) -> Path:
        return self.owner_root / "Reports we couldn't read"

    # -- the system folder ---------------------------------------------------

    @property
    def database(self) -> Path:
        return self.system_root / "database"

    @property
    def sealed_keys_file(self) -> Path:
        """The install's keys, sealed under a master key in the OS keychain
        (usali.desktop.keystore)."""
        return self.system_root / "keys.sealed.json"

    @property
    def keys_file(self) -> Path:
        """M1's plain-text keys. Read once to seal them, then deleted."""
        return self.system_root / "keys.json"

    @property
    def state_file(self) -> Path:
        return self.system_root / "state.json"

    @property
    def logs(self) -> Path:
        return self.system_root / "logs"

    @property
    def uploads(self) -> Path:
        # Portal uploads stage here, NOT in the drop folder: the folder
        # watcher would otherwise race the upload request for the same file.
        return self.system_root / "uploads"

    @property
    def punch_photos(self) -> Path:
        return self.system_root / "punch-photos"

    def ensure(self) -> None:
        """Create every directory except the database, which initdb must
        find absent (or empty) to create."""
        for d in (
            self.drop_folder,
            self.read_folder,
            self.unreadable_folder,
            self.system_root,
            self.logs,
            self.uploads,
            self.punch_photos,
        ):
            d.mkdir(parents=True, exist_ok=True)
