"""Where the owner's reports are, said plainly, with a button to open each.

Asked for by the owner: "show which folder has all reports". The folders were
only reachable from the tray icon, which most owners never right-click.

    GET  /api/desktop/folders             the owner's folders, with how many files each holds
    POST /api/desktop/folders/{id}/open   open one in File Explorer

Opening happens on this computer — the app and the browser window are the
same machine — and only ever one of the fixed folders below, by id. A path is
never taken from the request.
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


def install(
    app: FastAPI, *, paths: DesktopPaths, reveal_folder: Callable[[Path], None] = reveal,
) -> None:
    app.state.desktop_folders_paths = paths
    app.state.desktop_folders_reveal = reveal_folder
    app.include_router(router)
