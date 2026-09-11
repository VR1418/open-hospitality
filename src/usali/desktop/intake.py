"""Folder-watch intake (PRD M1; E-5's zero-password fallback).

The owner — or a rule in their mail program — saves night-audit PDFs into
"Drop reports here". Each one runs through upstream's `process_file`
unchanged: detect, parse, stage, map, promote, then file the PDF under
"Reports we read" or "Reports we couldn't read" with the error recorded.
Parsing still fails loud and never writes a best-effort number (PRD §12).

One worker thread, one report at a time: a night-audit pack is seconds of
CPU, and serial processing means two saves of the same pack can never race
each other into the books.
"""

import logging
import os
import queue
import threading
import time
from collections.abc import Callable
from pathlib import Path

from sqlalchemy.orm import Session
from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer
from watchdog.observers.api import BaseObserver

from usali.adaptors.pack import split_pack
from usali.adaptors.pdf import extract_pages
from usali.detect import detect, load_registry
from usali.ingestion import ProcessingError, ProcessResult, process_file, process_pack
from usali.night_audit import PACK_UPLOAD
from usali.tenancy import SessionFactory

_LOG = logging.getLogger("usali.desktop.intake")

# How long a file may keep growing (a mail client or a sync client still
# writing it) before we give up on it for this launch.
_WRITE_SETTLE_TIMEOUT_SECONDS = 60.0


def _wait_until_written(path: Path, timeout: float = _WRITE_SETTLE_TIMEOUT_SECONDS) -> bool:
    """True once the file has stopped growing and can be opened (Windows
    refuses to open a file another process still holds for writing)."""
    deadline = time.monotonic() + timeout
    last = -1
    while time.monotonic() < deadline:
        if not path.exists():
            return False
        try:
            size = path.stat().st_size
            with path.open("rb"):
                pass
        except OSError:
            size = -1
        if size > 0 and size == last:
            return True
        last = size
        time.sleep(0.5)
    return False


def _is_pack(session: Session, path: Path) -> bool:
    """Does this PDF belong on `process_pack` rather than `process_file`?

    Upstream's night-audit upload decides by the PROPERTY's PMS
    (`night_audit.PACK_UPLOAD`), but a dropped file names no property until it
    is read. So ask the file the same question: split it the way process_pack
    splits it, and see whether any section is a report from a PMS that
    delivers packs. Read-only — nothing is staged or moved here — so a wrong
    "no" still ends in process_file's loud quarantine, never in a guess.
    """
    try:
        registry = load_registry(session)
        for section in split_pack(extract_pages(path)):
            try:
                det = detect(section.words, registry, section.title)
            except ValueError:
                continue  # filler or an unregistered property, as process_pack skips it
            if det.pms_source.upper() in PACK_UPLOAD:
                return True
    except Exception:
        _LOG.debug("pack check could not read %s; treating it as one report", path.name)
    return False


class _Handler(FileSystemEventHandler):
    def __init__(self, submit: Callable[[Path], None]) -> None:
        super().__init__()
        self._submit = submit

    def on_created(self, event: FileSystemEvent) -> None:
        if not event.is_directory:
            self._submit(Path(os.fsdecode(event.src_path)))

    def on_moved(self, event: FileSystemEvent) -> None:
        # Browsers and many mail clients write a temp name, then rename.
        if not event.is_directory and event.dest_path:
            self._submit(Path(os.fsdecode(event.dest_path)))


class ReportIntake:
    def __init__(
        self,
        session_factory: SessionFactory,
        *,
        drop_folder: Path,
        read_folder: Path,
        unreadable_folder: Path,
    ) -> None:
        self._factory = session_factory
        self._drop = drop_folder
        self._read = read_folder
        self._unreadable = unreadable_folder
        self._queue: queue.Queue[Path | None] = queue.Queue()
        self._observer: BaseObserver | None = None
        self._worker: threading.Thread | None = None

    def start(self) -> None:
        for folder in (self._drop, self._read, self._unreadable):
            folder.mkdir(parents=True, exist_ok=True)
        self._worker = threading.Thread(target=self._run, name="report-intake", daemon=True)
        self._worker.start()
        # Watch FIRST, then drain what is already waiting: a file landing in
        # between is then seen twice rather than never, and the worker skips
        # the second sighting because the first one filed it away.
        observer = Observer()
        observer.schedule(_Handler(self.submit), str(self._drop), recursive=False)
        observer.start()
        self._observer = observer
        for existing in sorted(self._drop.iterdir()):
            self.submit(existing)

    def submit(self, path: Path) -> None:
        if path.suffix.lower() == ".pdf":
            self._queue.put(path)

    def stop(self) -> None:
        if self._observer is not None:
            self._observer.stop()
            self._observer.join(timeout=5)
        self._queue.put(None)
        if self._worker is not None:
            self._worker.join(timeout=60)

    def _run(self) -> None:
        while True:
            path = self._queue.get()
            if path is None:
                return
            if not path.exists():
                continue  # a duplicate sighting of a file already filed
            if not _wait_until_written(path):
                _LOG.warning("gave up waiting for %s to finish saving", path.name)
                continue
            try:
                with self._factory() as session:
                    results: list[ProcessResult]
                    if _is_pack(session, path):
                        results = process_pack(
                            session, path, processed_dir=self._read, failed_dir=self._unreadable
                        )
                    else:
                        results = [process_file(
                            session, path, processed_dir=self._read, failed_dir=self._unreadable
                        )]
                for r in results:
                    _LOG.info(
                        "read %s: %s/%s %s %s mapped=%d unmapped=%d",
                        path.name, r.pms_source, r.report_type, r.property_id,
                        r.business_date, r.mapped, r.unmapped,
                    )
            except ProcessingError as exc:
                _LOG.warning("could not read %s: %s", path.name, exc)
            except Exception:
                # Keep the worker alive for the next report; the traceback
                # goes to the log file the owner can choose to send us.
                _LOG.exception("unexpected error reading %s", path.name)
