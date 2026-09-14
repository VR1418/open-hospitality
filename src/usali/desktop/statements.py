"""Checking the books against the bank, and sorting the card (PRD "Bank
cross-check: statement upload" and "Card expense sorting").

The owner downloads a statement from their bank or card as a CSV — every
bank offers one — and uploads it here.

**A bank statement** is checked against what the night audits said. Every
card settlement the front desk recorded (Visa, MasterCard, American Express,
Discover) and every cash deposit is a Settlements fact in the books. A credit
on the statement is matched to those facts by brand and amount: the processor
pays out one or several nights together, a day or a few later, and less its
fee — so a deposit is looked for as the sum of one to four consecutive nights'
settlements, exactly first, then within a fee's worth below. A debit that
reads like payroll is marked as payroll. Everything else is UNMATCHED and
listed for the owner, who can mark a line as "not the hotel's business" (a
loan payment, say). Nothing here writes to the books: it is a check.

**A card statement** is the hotel's own credit card — purchases. Each line is
sorted into a plain-language expense category, and the category is remembered
by merchant, so a supplier sorted once is sorted every month after. The
totals by category are what the accountant wants.

**What is stored.** The statement's lines — date, description, amount — and
the match or category for each. Descriptions are what the bank printed
(merchant names, "PAYROLL", card brands); a statement never carries a guest.
The file itself is not kept.
"""

import csv
import io
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from usali.desktop.settings import read_setting, write_setting
from usali.models import UsaliFinancialFact
from usali.reporting import SETTLEMENTS_MAJOR

MERCHANTS_KEY = "merchant_categories"

#: Plain-language expense categories for the hotel's card, in USALI's shape.
CARD_CATEGORIES: tuple[str, ...] = (
    "Rooms — Cleaning supplies",
    "Rooms — Guest supplies & amenities",
    "Rooms — Linen & laundry",
    "Breakfast & food",
    "Utilities — Electricity",
    "Utilities — Gas",
    "Utilities — Water & sewer",
    "Utilities — Internet, phone & TV",
    "Repairs & maintenance",
    "Landscaping & pool",
    "Office supplies",
    "Software & subscriptions",
    "Bank & card fees",
    "Advertising & marketing",
    "Franchise & brand fees",
    "Insurance",
    "Travel & meals",
    "Owner — personal (not the hotel's)",
    "Other",
)

#: How a bank names a card brand's payout, and which settlement lines it pays.
_BRANDS: tuple[tuple[re.Pattern[str], tuple[str, ...]], ...] = (
    (re.compile(r"\bAM(?:ERICAN)?\s*EX(?:PRESS)?\b|\bAMEX\b"), ("American Express",)),
    (re.compile(r"\bDISCOVER\b|\bDFS\b"), ("Discover",)),
    (re.compile(r"\bVISA\b|\bMASTERCARD\b|\bMSTRCARD\b|\bMC\b|\bV/MC\b|\bBANKCARD\b|"
                r"\bMERCH(?:ANT)?\b|\bCARD\s*SERV|\bELAVON\b|\bFISERV\b|\bHEARTLAND\b|"
                r"\bWORLDPAY\b|\bSHIFT4\b|\bSQUARE\b|\bSTRIPE\b"),
     ("Visa", "MasterCard")),
)
_CASH = re.compile(r"\bDEPOSIT\b|\bCASH\b")
_PAYROLL = re.compile(r"\bPAYROLL\b|\bGUSTO\b|\bADP\b|\bPAYCHEX\b|\bWAGES\b|\bDIRECT\s*DEP\b")
#: How much below the settled figure a payout may land (the processor's fee).
_FEE_CEILING = Decimal("0.045")
_LOOKBACK_DAYS = 7
_MAX_NIGHTS = 4


class StatementError(ValueError):
    """The file could not be read as a statement — said in the owner's words."""


@dataclass(frozen=True)
class ParsedLine:
    posted_on: date
    description: str
    amount: Decimal
    balance: Decimal | None = None


# --- reading the CSV -------------------------------------------------------------

_DATE_FORMATS = ("%m/%d/%Y", "%Y-%m-%d", "%m/%d/%y", "%d/%m/%Y", "%b %d, %Y", "%d %b %Y",
                 "%m-%d-%Y", "%Y/%m/%d", "%b %d %Y")


def _parse_date(text: str) -> date | None:
    s = text.strip().split(" ")[0] if "T" in text else text.strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _money(text: str) -> Decimal | None:
    s = text.strip().replace("$", "").replace(",", "").replace(" ", "")
    if s in ("", "-", "—"):
        return None
    negative = s.startswith("(") and s.endswith(")") or s.endswith("-") or s.startswith("-")
    s = s.strip("()-+")
    if s.upper().endswith("CR"):
        s, negative = s[:-2], False
    elif s.upper().endswith("DR"):
        s, negative = s[:-2], True
    try:
        value = Decimal(s)
    except InvalidOperation:
        return None
    return -value if negative else value


def _find(headers: list[str], *words: str, taken: set[int] | None = None) -> int | None:
    """The first column named by the strongest word: "description" beats
    "transaction", so "Transaction Date" is never taken for the description."""
    skip = taken or set()
    for word in words:
        for i, h in enumerate(headers):
            if i not in skip and word in h:
                return i
    return None


def parse_csv(text: str) -> list[ParsedLine]:
    """Lines from a bank's or card's CSV, whatever the column names — a date, a
    description, and either one amount column or debit and credit columns."""
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    # Some banks put a space before a quoted field; without this the quote
    # would be read as part of the value.
    dialect.skipinitialspace = True
    rows = [r for r in csv.reader(io.StringIO(text), dialect) if any(c.strip() for c in r)]
    if len(rows) < 2:
        raise StatementError("That file has no rows in it. Download the statement as a CSV.")
    headers = [h.strip().lower() for h in rows[0]]
    date_col = _find(headers, "date")
    taken = {date_col} if date_col is not None else set()
    desc_col = _find(headers, "description", "memo", "payee", "details", "narrative", "name",
                     "transaction", taken=taken)
    if desc_col is not None:
        taken.add(desc_col)
    amount_col = _find(headers, "amount", taken=taken)
    debit_col = _find(headers, "debit", "withdrawal", "money out", "paid out", "charge",
                      taken=taken)
    credit_col = _find(headers, "credit", "deposit", "money in", "paid in", "payment",
                       taken=taken)
    balance_col = _find(headers, "balance", "bal", taken=taken)
    if date_col is None or desc_col is None or (amount_col is None and debit_col is None
                                                 and credit_col is None):
        raise StatementError(
            "The first line should name the columns — a date, a description, and an amount "
            "(or a debit and a credit column). Most banks' CSV downloads do."
        )
    out: list[ParsedLine] = []
    bad = 0
    for row in rows[1:]:
        if len(row) <= max(i for i in (date_col, desc_col, amount_col, debit_col, credit_col)
                           if i is not None):
            bad += 1
            continue
        when = _parse_date(row[date_col])
        if when is None:
            bad += 1
            continue
        if amount_col is not None:
            amount = _money(row[amount_col])
        else:
            debit = _money(row[debit_col]) if debit_col is not None else None
            credit = _money(row[credit_col]) if credit_col is not None else None
            amount = (credit or Decimal("0")) - abs(debit or Decimal("0"))
            if debit is None and credit is None:
                amount = None
        if amount is None:
            bad += 1
            continue
        balance = _money(row[balance_col]) if balance_col is not None else None
        out.append(ParsedLine(
            posted_on=when, description=" ".join(row[desc_col].split())[:300],
            amount=amount.quantize(Decimal("0.01")), balance=balance,
        ))
    if not out:
        raise StatementError("None of the rows had a date and an amount that could be read.")
    if bad > len(out):
        raise StatementError(
            f"Most rows ({bad}) couldn't be read. Check the file is the statement itself, "
            "not a summary."
        )
    return out


# --- matching a bank statement ------------------------------------------------------

@dataclass(frozen=True)
class Match:
    kind: str  # settlement | cash | payroll | unmatched
    note: str
    matched_amount: Decimal | None = None


def _settlements(session: Session, property_id: str, start: date, end: date) -> dict[tuple[date, str], Decimal]:
    """Settled money per night and line, as a positive figure."""
    rows = session.execute(
        select(UsaliFinancialFact.business_date, UsaliFinancialFact.usali_line_item,
               func.sum(UsaliFinancialFact.amount))
        .where(UsaliFinancialFact.property_id == property_id,
               UsaliFinancialFact.usali_major_category == SETTLEMENTS_MAJOR,
               UsaliFinancialFact.business_date.between(start, end))
        .group_by(UsaliFinancialFact.business_date, UsaliFinancialFact.usali_line_item)
    ).all()
    return {(d, line): abs(Decimal(total)) for d, line, total in rows}


def _brand_lines(description: str) -> tuple[str, tuple[str, ...]] | None:
    upper = description.upper()
    for pattern, lines in _BRANDS:
        if pattern.search(upper):
            return ("/".join(lines), lines)
    return None


def _windows(posted: date) -> list[tuple[date, date]]:
    """Runs of one to four consecutive nights ending on or before the posting
    day, nearest first."""
    out: list[tuple[date, date]] = []
    for back in range(0, _LOOKBACK_DAYS + 1):
        end = posted - timedelta(days=back)
        for nights in range(1, _MAX_NIGHTS + 1):
            out.append((end - timedelta(days=nights - 1), end))
    return out


def _fmt(d: date) -> str:
    return f"{d.month}/{d.day}"


def match_credit(amount: Decimal, posted: date, lines: tuple[str, ...], label: str,
                 settled: dict[tuple[date, str], Decimal], used: set[tuple[date, str]]) -> Match | None:
    best: tuple[Decimal, tuple[date, date]] | None = None
    for start, end in _windows(posted):
        days = [start + timedelta(days=i) for i in range((end - start).days + 1)]
        keys = [(d, line) for d in days for line in lines]
        if any(k in used for k in keys):
            continue
        # A run of nights is anchored on nights that settled something: a
        # window padded with empty days is the same money under a wider label.
        if not any((start, line) in settled for line in lines):
            continue
        if not any((end, line) in settled for line in lines):
            continue
        total = sum((settled.get(k, Decimal("0")) for k in keys), Decimal("0"))
        if total == amount:
            used.update(k for k in keys if k in settled)
            span = _fmt(start) if start == end else f"{_fmt(start)}–{_fmt(end)}"
            return Match("settlement", f"{label} settled {span}", total)
        fee = total - amount
        if Decimal("0") < fee <= total * _FEE_CEILING and (best is None or fee < best[0]):
            best = (fee, (start, end))
    if best is not None:
        fee, (start, end) = best
        days = [start + timedelta(days=i) for i in range((end - start).days + 1)]
        used.update((d, line) for d in days for line in lines if (d, line) in settled)
        span = _fmt(start) if start == end else f"{_fmt(start)}–{_fmt(end)}"
        return Match("settlement", f"{label} settled {span}, less ${fee:,.2f} in fees", amount + fee)
    return None


def match_lines(session: Session, property_id: str, lines: list[ParsedLine]) -> list[Match]:
    if not lines:
        return []
    first = min(line.posted_on for line in lines) - timedelta(days=_LOOKBACK_DAYS + _MAX_NIGHTS)
    last = max(line.posted_on for line in lines)
    settled = _settlements(session, property_id, first, last)
    used: set[tuple[date, str]] = set()
    out: list[Match] = []
    for line in sorted(lines, key=lambda ln: (ln.posted_on, -abs(ln.amount))):
        out.append(_match_one(line, settled, used))
    # Back in the caller's order.
    order = {id(ln): i for i, ln in enumerate(sorted(lines, key=lambda ln: (ln.posted_on, -abs(ln.amount))))}
    return [out[order[id(ln)]] for ln in lines]


def _match_one(line: ParsedLine, settled: dict[tuple[date, str], Decimal],
               used: set[tuple[date, str]]) -> Match:
    if line.amount > 0:
        brand = _brand_lines(line.description)
        if brand is not None:
            found = match_credit(line.amount, line.posted_on, brand[1], brand[0], settled, used)
            if found is not None:
                return found
            return Match("unmatched", f"No {brand[0]} settlement adds up to this in the week before.")
        if _CASH.search(line.description.upper()):
            found = match_credit(line.amount, line.posted_on, ("Cash", "Check"), "Cash and checks",
                                 settled, used)
            if found is not None:
                return Match("cash", found.note, found.matched_amount)
            return Match("unmatched", "No cash taken at the desk adds up to this deposit.")
        # An unnamed credit: try every card brand, then say so.
        for pattern_label, lines in (("Visa/MasterCard", ("Visa", "MasterCard")),
                                     ("American Express", ("American Express",)),
                                     ("Discover", ("Discover",))):
            found = match_credit(line.amount, line.posted_on, lines, pattern_label, settled, used)
            if found is not None:
                return found
        return Match("unmatched", "Money in that nothing in the night audits accounts for.")
    if _PAYROLL.search(line.description.upper()):
        return Match("payroll", "Payroll — check it against your pay run.")
    return Match("unmatched", "Money out. If it isn't the hotel's business, mark it as such.")


# --- sorting the card -------------------------------------------------------------------

def merchant_key(description: str) -> str:
    """"AMAZON MKTPL*2K4J1 SEATTLE WA 09/12" and "AMAZON MKTPL*9Q2 SEATTLE WA"
    are the same merchant: letters only, the first three words."""
    words = re.sub(r"[^A-Z ]", " ", description.upper()).split()
    return " ".join(w for w in words if len(w) > 1)[:40].strip() or description.upper()[:40]


def remembered_categories(session: Session) -> dict[str, str]:
    raw = read_setting(session, MERCHANTS_KEY)
    return {str(k): str(v) for k, v in raw.items()} if isinstance(raw, dict) else {}


def remember_category(session: Session, description: str, category: str | None) -> None:
    known = remembered_categories(session)
    key = merchant_key(description)
    if category is None:
        known.pop(key, None)
    else:
        known[key] = category
    write_setting(session, MERCHANTS_KEY, known)


def categories_for(session: Session, lines: list[ParsedLine]) -> list[str | None]:
    known = remembered_categories(session)
    return [known.get(merchant_key(line.description)) for line in lines]


def totals_by_category(rows: list[tuple[str | None, Decimal]]) -> list[tuple[str, Decimal]]:
    sums: dict[str, Decimal] = defaultdict(Decimal)
    for category, amount in rows:
        sums[category or "Not sorted yet"] += abs(amount)
    return sorted(sums.items(), key=lambda kv: -kv[1])
