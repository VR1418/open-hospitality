"""What the AI helper knows, written as notes the owner can read (M4 phase 4).

The owner asked for the AI to have "memory", and suggested Obsidian for it.
An Obsidian vault is a folder of Markdown files, so the memory is written as
one: `Documents › Open Hospitality › AI memory`. Open that folder in Obsidian
(or read the files in any editor) to see, for each hotel, every charge code
that has been decided and how, and which reports have been read.

**A mirror, one way.** The database is the memory; these notes are rewritten
from it. Editing a note changes nothing about how the books are read — a hand
edit that silently changed how figures are filed is the failure the decision
records exist to prevent (docs/desktop/M4-ai-and-ledger.md, "Memory and
skills"). Every note says so at the top.

**What is in them.** Hotel names and codes, the ownership entity, charge
codes with the description the report prints and the line they were filed
under, who decided (you, or an AI suggestion you accepted — not a person's
name), and report counts. Never a guest, an employee, an amount or a rate.

Files are only rewritten when their content changes, so Obsidian (and a
syncing drive) is not woken every minute for nothing.
"""

import logging
import re
import threading
from collections import Counter
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from usali.desktop import report_recipes
from usali.desktop.mapping_decisions import decisions_for
from usali.desktop.saved_reports import Hotel, hotels
from usali.models import IngestionCoverage, PmsDailyFinancialStage, Property

_LOG = logging.getLogger(__name__)

FOLDER_NAME = "AI memory"
GUIDES = Path(__file__).resolve().parents[3] / "mapping" / "reading-guides"

#: What an owner calls each system (welcome_api.PMS_NAMES, without FastAPI).
PMS_NAMES = {"OPERA": "Oracle OPERA", "AUTOCLERK": "AutoClerk", "SKYTOUCH": "choiceADVANTAGE",
             "OTHER": "Another system (read with the AI helper)"}

_MIRROR = (
    "> [!info] Written by Open Hospitality\n"
    "> This note is rewritten from your books whenever they change. Editing it here "
    "does not change how your reports are read — make changes in the app.\n"
)

_ORIGIN = {"owner": "You", "ai-accepted": "AI suggestion, accepted by you"}
_UNSAFE = re.compile(r'[<>:"/\\|?*\x00-\x1f\[\]#^]')


def _cell(value: object) -> str:
    return str(value if value is not None else "").replace("|", "/").replace("\n", " ").strip()


def _note_name(hotel: Hotel) -> str:
    return _UNSAFE.sub("", f"{hotel.property_id} – {hotel.name}").strip(" .")


def hotel_note(session: Session, hotel: Hotel, pms_source: str) -> str:
    pms = PMS_NAMES.get(pms_source, pms_source)
    guide = pms_source.lower()
    lines = [
        "---",
        f"hotel_code: {hotel.property_id}",
        f'hotel_name: "{_cell(hotel.name)}"',
        f'ownership_entity: "{_cell(hotel.ownership_entity)}"',
        f"front_desk_system: {pms_source}",
        "tags: [hotel]",
        "---",
        "",
        f"# {hotel.name}",
        "",
        _MIRROR,
        f"- **Hotel code:** {hotel.property_id}",
        f"- **Ownership entity:** {hotel.ownership_entity or '—'}",
        f"- **Front-desk system:** {pms}",
        f"- **How its reports are read:** [[Reading guides/{guide}|{pms} reading guide]]",
        "",
    ]

    reports = session.execute(
        select(IngestionCoverage.report_type, func.count(), func.min(IngestionCoverage.business_date),
               func.max(IngestionCoverage.business_date))
        .where(IngestionCoverage.property_id == hotel.property_id)
        .group_by(IngestionCoverage.report_type)
        .order_by(IngestionCoverage.report_type)
    ).all()
    lines += ["## Reports read", ""]
    if reports:
        lines += ["| Report | Nights | First | Latest |", "|---|---:|---|---|"]
        lines += [
            f"| {_cell(kind.replace('_', ' ').capitalize())} | {n} | {first} | {latest} |"
            for kind, n, first, latest in reports
        ]
    else:
        lines.append("None yet.")
    lines.append("")

    learned = report_recipes.for_property(session, hotel.property_id)
    lines += ["## Report layouts learned", ""]
    if learned:
        lines += [
            "Read without the AI helper, the way you confirmed them. A report whose layout "
            "changes is sent to the AI helper again, and you are told.",
            "",
            "| Page title | Line layout | Amount column | Date printed after | Confirmed | Reports read |",
            "|---|---|---|---|---|---:|",
        ]
        for s_ in learned:
            r = s_.recipe
            column = "last" if r.amount_index == -1 else (
                f"{r.amount_index + 1}" if r.amount_index >= 0 else f"{-r.amount_index} from the end")
            lines.append(
                f"| {_cell(r.title)} | {_cell(r.layout)} | {column} "
                f"| {_cell(r.date_label) or 'first date on the page'} "
                f"| {s_.confirmed_at:%Y-%m-%d} | {s_.reads} |"
            )
    else:
        lines.append("None yet.")
    lines.append("")

    decided = list(decisions_for(session, property_id=hotel.property_id))
    descriptions = dict(session.execute(
        select(PmsDailyFinancialStage.pms_trx_code, func.max(PmsDailyFinancialStage.pms_trx_desc))
        .where(PmsDailyFinancialStage.property_id == hotel.property_id)
        .group_by(PmsDailyFinancialStage.pms_trx_code)
    ).tuples().all())
    lines += ["## Charge codes decided for this hotel", ""]
    if decided:
        origins = Counter(d.origin for d in decided)
        lines += [
            f"{len(decided)} decided — {origins.get('owner', 0)} by you, "
            f"{origins.get('ai-accepted', 0)} from AI suggestions you accepted. Codes nobody has "
            "decided are filed by the app's built-in dictionary.",
            "",
            "| Code | Printed on the report as | Filed under | Decided by | When |",
            "|---|---|---|---|---|",
        ]
        for d in sorted(decided, key=lambda d: d.pms_trx_code):
            c = d.classification
            lines.append(
                f"| {_cell(d.pms_trx_code)} | {_cell(descriptions.get(d.pms_trx_code)) or '—'} "
                f"| {_cell(c.usali_sub_category)} › {_cell(c.usali_line_item)} "
                f"| {_ORIGIN.get(d.origin, _cell(d.origin))} | {d.decided_at:%Y-%m-%d} |"
            )
    else:
        lines.append("None yet — every code is filed by the app's built-in dictionary.")
    lines.append("")
    return "\n".join(lines)


def index_note(entries: list[tuple[Hotel, str]], now: datetime) -> str:
    lines = [
        "# What your AI helper knows",
        "",
        _MIRROR,
        "Open this folder as a vault in [Obsidian](https://obsidian.md) to browse it, or read the "
        "files in any text editor.",
        "",
        "## Hotels",
        "",
    ]
    lines += [f"- [[Hotels/{_note_name(h)}|{h.name}]] · {h.property_id} · "
              f"{PMS_NAMES.get(pms, pms)}" for h, pms in entries] or ["None set up yet."]
    lines += [
        "",
        "## Reading guides",
        "",
        "How each front-desk system's night audit is read — the instructions the AI helper "
        "is given, and the rules the app's own readers follow.",
        "",
    ]
    lines += [f"- [[Reading guides/{p.stem}]]" for p in sorted(GUIDES.glob("*.md"))]
    lines += ["", f"<small>Last changed {now:%Y-%m-%d %H:%M}.</small>", ""]
    return "\n".join(lines)


def _write_if_changed(path: Path, content: str) -> bool:
    if path.is_file() and path.read_text(encoding="utf-8") == content:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.writing")
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(path)
    return True


def write_notes(session: Session, folder: Path) -> list[Path]:
    """Rewrite every note whose content changed. Returns what was written."""
    changed: list[Path] = []
    known = hotels(session)
    systems = dict(session.execute(select(Property.property_id, Property.pms_source)).tuples().all())
    entries = sorted(((h, systems.get(pid, "")) for pid, h in known.items()),
                     key=lambda e: e[0].property_id)
    for hotel, pms in entries:
        path = folder / "Hotels" / f"{_note_name(hotel)}.md"
        if _write_if_changed(path, hotel_note(session, hotel, pms)):
            changed.append(path)
    for guide in sorted(GUIDES.glob("*.md")):
        target = folder / "Reading guides" / guide.name
        if _write_if_changed(target, guide.read_text(encoding="utf-8")):
            changed.append(target)
    index = folder / "Start here.md"
    # The index's date moves only when something else did.
    if changed or not index.exists():
        _write_if_changed(index, index_note(entries, datetime.now()))
        changed.append(index)
    session.rollback()
    return changed


class MemoryNotes:
    """Keeps the notes current in the background."""

    def __init__(self, session_factory: Callable[[], Session], folder: Path,
                 interval: float = 60.0) -> None:
        self.session_factory = session_factory
        self.folder = folder
        self.interval = interval
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="memory-notes", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        while True:
            try:
                with self.session_factory() as session:
                    for path in write_notes(session, self.folder):
                        _LOG.info("memory note updated: %s", path.name)
            except Exception:
                _LOG.exception("updating the memory notes failed; will try again")
            if self._stop.wait(self.interval):
                return

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=10)
