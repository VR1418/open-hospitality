"""Learning how a report is read, from what the owner confirmed (M4 phase 4, step 3).

The first time a report nobody has a parser for is read, the AI helper reads
it and the owner confirms the rows. This module then works out a RECIPE that
reproduces exactly those rows from the same pages, and every later report of
that shape is read by replaying the recipe: no model call, no cost, and the
same reading every morning.

**The model never writes a recipe.** The app infers it, and only keeps one
that reproduces the confirmed rows exactly — every code, description and
amount, and the business date. If none does (the owner edited a row, or the
lines are laid out in a way no recipe here describes), nothing is learned and
the next report is read by the AI helper again, as before.

**A recipe is not code.** It picks from a fixed set of line layouts the app
defines, which column holds the night's amount, and where the date is printed.
Nothing in it is a pattern the model or a file supplied, so replaying one
cannot be made to run away.

**Drift is loud.** A recipe that finds no page with its title, no rows, or no
date returns None; the read then goes to the AI helper and the owner is told
the report's shape changed. It is never silently re-guessed.
"""

import hashlib
import re
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from usali.desktop.ai.pages import Page

_AMOUNT = r"\(?-?\$?[\d,]*\d\.\d{2}\)?-?"
_AMOUNTS = rf"(?P<amounts>{_AMOUNT}(?:\s+{_AMOUNT})*)"
_CODE = r"[A-Za-z0-9][A-Za-z0-9&/-]{0,11}"
_LONGEST_LINE = 300

#: The ways a charge line is laid out. Fixed here; a recipe only names one.
LAYOUTS: dict[str, re.Pattern[str]] = {
    # Room Charge (RM) 7,147.07 0.00 0.00 7,147.07
    "description (code) amounts": re.compile(rf"^(?P<desc>.*?\S)\s+\((?P<code>{_CODE})\)\s+{_AMOUNTS}$"),
    # 1000 *Accommodation 10,395.00
    "code description amounts": re.compile(rf"^(?P<code>{_CODE})\s+(?P<desc>.*?\S)\s+{_AMOUNTS}$"),
    # Accommodation 1000 10,395.00
    "description code amounts": re.compile(rf"^(?P<desc>.*?\S)\s+(?P<code>{_CODE})\s+{_AMOUNTS}$"),
}

_DATES = (
    (re.compile(r"(\d{1,2})/(\d{1,2})/(\d{4})"), "m/d/yyyy"),
    (re.compile(r"(\d{4})-(\d{2})-(\d{2})"), "yyyy-mm-dd"),
    (re.compile(r"(\d{2})-(\d{2})-(\d{2})\b"), "mm-dd-yy"),
)
#: "" last: some systems (OPERA) print the date beside the hotel name with no
#: label, so the first date on the page is the night.
_DATE_LABELS = ("Business Date", "Date Range", "Audit Date", "Report Date", "Date", "")


@dataclass(frozen=True)
class Row:
    code: str
    description: str
    amount: Decimal


@dataclass(frozen=True)
class Recipe:
    #: The first line of the page(s) the rows are on.
    title: str
    layout: str
    #: Which amount on the line is the night's: 0 is the first, -1 the last.
    amount_index: int
    #: The words the date follows, and how it is written.
    date_label: str
    date_format: str

    @property
    def fingerprint(self) -> str:
        return hashlib.sha256(f"{_norm(self.title)}|{self.layout}".encode()).hexdigest()

    def to_json(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_json(cls, raw: dict[str, Any]) -> "Recipe | None":
        try:
            recipe = cls(title=str(raw["title"]), layout=str(raw["layout"]),
                         amount_index=int(raw["amount_index"]),
                         date_label=str(raw["date_label"]), date_format=str(raw["date_format"]))
        except (KeyError, TypeError, ValueError):
            return None
        known_format = recipe.date_format in {f for _, f in _DATES}
        return recipe if recipe.layout in LAYOUTS and known_format else None


def _norm(text: str) -> str:
    return " ".join(text.split()).casefold()


def _title(page: Page) -> str:
    return next((line.strip() for line in page.text.splitlines() if line.strip()), "")


def _money(raw: str) -> Decimal | None:
    negative = raw.startswith("(") or raw.startswith("-") or raw.endswith("-")
    digits = raw.strip("()-$").replace(",", "").replace("$", "")
    try:
        value = Decimal(digits)
    except InvalidOperation:
        return None
    return -value if negative else value


def _rows(pages: Iterable[Page], layout: str, amount_index: int) -> list[Row]:
    pattern = LAYOUTS[layout]
    out: list[Row] = []
    for page in pages:
        for line in page.text.splitlines():
            if len(line) > _LONGEST_LINE:
                continue  # no charge line is this long; never worth the matching
            found = pattern.match(line.strip())
            if found is None:
                continue
            amounts = found.group("amounts").split()
            try:
                value = _money(amounts[amount_index])
            except IndexError:
                continue
            if value is not None:
                out.append(Row(found.group("code"), found.group("desc").strip(), value))
    return out


def _date(pages: Iterable[Page], label: str, fmt: str) -> date | None:
    pattern = next(p for p, f in _DATES if f == fmt)
    for page in pages:
        for line in page.text.splitlines():
            at = line.casefold().find(label.casefold())
            if at < 0:
                continue
            found = pattern.search(line[at + len(label):])
            if found is None:
                continue
            a, b, c = (int(g) for g in found.groups())
            try:
                if fmt == "m/d/yyyy":
                    return date(c, a, b)
                if fmt == "yyyy-mm-dd":
                    return date(a, b, c)
                return date(2000 + c, a, b)
            except ValueError:
                return None
    return None


def _pages_titled(pages: Sequence[Page], title: str) -> list[Page]:
    return [p for p in pages if _norm(_title(p)) == _norm(title)]


def replay(recipe: Recipe, pages: Sequence[Page]) -> tuple[date, list[Row]] | None:
    """Read `pages` by `recipe`, or None when the report is not that shape
    any more — no page with its title, no rows, or no date."""
    matching = _pages_titled(pages, recipe.title)
    if not matching:
        return None
    rows = _rows(matching, recipe.layout, recipe.amount_index)
    when = _date(pages, recipe.date_label, recipe.date_format)
    if not rows or when is None:
        return None
    return when, rows


def _key(rows: Iterable[Row]) -> Counter[tuple[str, str, Decimal]]:
    return Counter((r.code, _norm(r.description), r.amount) for r in rows)


def infer(pages: Sequence[Page], confirmed: Sequence[Row], business_date: date) -> Recipe | None:
    """The recipe that reads exactly the confirmed rows and date off these
    pages, or None. When more than one would, the LAST amount column is
    preferred — on a summary that is the night's total — then the first."""
    if not confirmed:
        return None
    wanted = _key(confirmed)
    titles = list(dict.fromkeys(_title(p) for p in pages if _title(p)))
    dates = [(label, fmt) for label in _DATE_LABELS for _, fmt in _DATES
             if _date(pages, label, fmt) == business_date]
    if not dates:
        return None
    label, fmt = dates[0]
    for title in titles:
        matching = _pages_titled(pages, title)
        for layout in LAYOUTS:
            for index in (-1, 0, 1, 2, 3, -2, -3):
                if _key(_rows(matching, layout, index)) == wanted:
                    return Recipe(title=title, layout=layout, amount_index=index,
                                  date_label=label, date_format=fmt)
    return None
