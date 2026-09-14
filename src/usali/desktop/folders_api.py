"""Where the owner's reports are, said plainly, with a button to open each.

Asked for by the owner: "show which folder has all reports". The folders were
only reachable from the tray icon, which most owners never right-click.

    GET  /api/desktop/folders             the owner's folders, with how many files each holds
    POST /api/desktop/folders/{id}/open   open one in File Explorer
    POST /api/desktop/folders/pick        a folder dialog, for pages that ask where to put things

Opening happens on this computer — the app and the browser window are the
same machine — and only ever one of the fixed folders below, by id. A path is
never taken from the request.

The dialog exists because the Backups page and the setup wizard used to offer
a text box for a folder path, which an owner who has never typed one gets
wrong. The dialog is Windows' own; the page gets back the folder chosen, or
nothing when it was cancelled.
"""

import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request
from pydantic import BaseModel

from usali.auth import require_active_org, require_operator
from usali.desktop.backup import BackupConfig
from usali.desktop.paths import DesktopPaths

router = APIRouter(dependencies=[Depends(require_operator), Depends(require_active_org)])


class FolderOut(BaseModel):
    id: str
    name: str
    path: str
    what: str
    files: int


class FoldersOut(BaseModel):
    #: The one folder that holds all of the others.
    root: str
    folders: list[FolderOut]


class PickIn(BaseModel):
    #: Where the dialog opens; the owner's folder when not given.
    start: str | None = None
    title: str = "Choose a folder"


class PickOut(BaseModel):
    #: None when the owner cancelled.
    folder: str | None


def _folders(paths: DesktopPaths) -> list[tuple[str, str, Path, str, str]]:
    """(id, name, path, what it holds, file pattern)."""
    listed = [
        ("saved", "Saved reports", paths.saved_reports_folder,
         "Daily summaries (PDF) and each month's accountant pack (Excel), by hotel and month. "
         "Written by the app after every night audit.", "**/*.*"),
        ("drop", "Drop reports here", paths.drop_folder,
         "Put night audit PDFs here and they are read within a few seconds.", "*.pdf"),
        ("read", "Reports we read", paths.read_folder,
         "Every night audit PDF that has been read into your books.", "*.pdf"),
        ("unreadable", "Reports we couldn't read", paths.unreadable_folder,
         "PDFs that couldn't be read, with the reason on the Add reports page.", "*.pdf"),
        ("memory", "AI memory", paths.memory_folder,
         "What the AI helper knows about each hotel, and how each system's reports are read. "
         "Open the folder in Obsidian to browse it.", "**/*.md"),
    ]
    backups = BackupConfig.load(paths.backup_config_file).folder
    if backups is not None:
        listed.append(("backups", "Backups", Path(backups),
                       "A copy of your books, written each day.", "*.*"))
    return listed


def _count(folder: Path, pattern: str) -> int:
    try:
        return sum(1 for p in folder.glob(pattern) if p.is_file() and not p.name.startswith("~"))
    except OSError:
        return 0


def reveal(folder: Path) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    if sys.platform == "win32":
        getattr(os, "startfile")(str(folder))
    elif sys.platform == "darwin":
        subprocess.run(["open", str(folder)], check=False)  # noqa: S603, S607
    else:
        subprocess.run(["xdg-open", str(folder)], check=False)  # noqa: S603, S607


def _ps_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def pick_folder(start: Path | None, title: str) -> Path | None:
    """Windows' own folder dialog, on this computer. None when cancelled;
    OSError where there is no such dialog."""
    if sys.platform != "win32":
        raise OSError("no folder dialog on this platform")
    script = (
        "Add-Type -AssemblyName System.Windows.Forms; "
        "$d = New-Object System.Windows.Forms.FolderBrowserDialog; "
        f"$d.Description = {_ps_quote(title)}; $d.ShowNewFolderButton = $true; "
        + (f"$d.SelectedPath = {_ps_quote(str(start))}; " if start is not None else "")
        # An owner form on top, so the dialog is not lost behind the app window.
        + "$owner = New-Object System.Windows.Forms.Form -Property @{TopMost = $true}; "
        "if ($d.ShowDialog($owner) -eq 'OK') { Write-Output $d.SelectedPath }"
    )
    try:
        done = subprocess.run(  # noqa: S603
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-STA", "-Command", script],
            capture_output=True, text=True, timeout=600,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except subprocess.SubprocessError as exc:
        raise OSError(str(exc)) from exc
    chosen = done.stdout.strip()
    return Path(chosen) if chosen else None


def _paths(request: Request) -> DesktopPaths:
    return request.app.state.desktop_folders_paths  # type: ignore[no-any-return]


@router.get("/api/desktop/folders")
def folders(request: Request) -> FoldersOut:
    paths = _paths(request)
    return FoldersOut(
        root=str(paths.owner_root),
        folders=[
            FolderOut(id=i, name=name, path=str(path), what=what, files=_count(path, pattern))
            for i, name, path, what, pattern in _folders(paths)
        ],
    )


@router.post("/api/desktop/folders/{folder_id}/open", status_code=204)
def open_folder(folder_id: str, request: Request) -> None:
    found = {i: path for i, _, path, _, _ in _folders(_paths(request))}.get(folder_id)
    if found is None:
        raise HTTPException(status_code=404, detail="There's no folder by that name.")
    try:
        request.app.state.desktop_folders_reveal(found)
    except OSError:
        raise HTTPException(
            status_code=503, detail=f"Couldn't open it. You'll find it at {found}"
        ) from None


@router.post("/api/desktop/folders/pick")
def pick(body: PickIn, request: Request) -> PickOut:
    paths = _paths(request)
    start = Path(body.start) if body.start else paths.owner_root
    try:
        chosen = request.app.state.desktop_folders_pick(start, body.title[:120])
    except OSError:
        raise HTTPException(
            status_code=501, detail="There's no folder dialog here. Type the folder's path instead."
        ) from None
    return PickOut(folder=str(chosen) if chosen is not None else None)


def install(
    app: FastAPI, *, paths: DesktopPaths, reveal_folder: Callable[[Path], None] = reveal,
    pick: Callable[[Path | None, str], Path | None] = pick_folder,
) -> None:
    app.state.desktop_folders_paths = paths
    app.state.desktop_folders_reveal = reveal_folder
    app.state.desktop_folders_pick = pick
    app.include_router(router)
