"""A made-up hotel group, for trying everything out and for the end-to-end test.

Three hotels on the three front-desk systems the app reads, ten staff each, a
month of night audits as PDFs the real readers parse, and bank and card
statements that line up with those audits (plus a few things that deliberately
don't, so the checks have something to show).

EVERYTHING here is invented and deterministic: the same hotel and date always
give the same figures, so a run can be repeated exactly. No real hotel, guest,
employee or figure appears in this file or in what it writes.

Used by scripts/desktop/e2e.py (the owner's and the staff's walk through the
packaged app) and by tests/test_desktop_demo.py (every generated report is
read by the real intake).
"""

import csv
import io
import random
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

_CENT = Decimal("0.01")


def money(value: Decimal | float | int) -> Decimal:
    return Decimal(value).quantize(_CENT, rounding=ROUND_HALF_UP)


def fmt(value: Decimal) -> str:
    return f"{value:,.2f}"


def paren(value: Decimal) -> str:
    """choiceADVANTAGE prints money going out in brackets."""
    return f"({fmt(-value)})" if value < 0 else fmt(value)


# --- the group --------------------------------------------------------------------

@dataclass(frozen=True)
class Hotel:
    code: str
    name: str
    pms: str
    entity: str
    rooms: int
    city: str


HOTELS: tuple[Hotel, ...] = (
    Hotel("RTI22", "Redstone Test Inn", "SKYTOUCH", "Redstone Hospitality LLC", 60, "Redstone"),
    Hotel("SHI01", "Seabright Harbor Inn", "OPERA", "Seabright Lodging LLC", 90, "Seabright"),
    Hotel("CPL07", "Cedar Point Lodge", "AUTOCLERK", "Cedar Point Hospitality LLC", 45, "Cedar Point"),
)


@dataclass(frozen=True)
class Person:
    full_name: str
    department: str
    pay_type: str  # hourly | salaried
    role: str | None = None  # an operator role gets a sign-in


_FIRST = ("Ana", "Ben", "Cora", "Dev", "Elena", "Femi", "Grace", "Hugo", "Ines", "Jonah",
          "Kai", "Lena", "Mateo", "Nia", "Omar", "Priya", "Quinn", "Rosa", "Sam", "Tara",
          "Uma", "Victor", "Wren", "Ximena", "Yusuf", "Zoe", "Arjun", "Bea", "Cal", "Dana")
_LAST = ("Patel", "Okafor", "Lindqvist", "Moreno", "Nakamura", "Osei", "Reyes", "Silva",
         "Tanaka", "Varga", "Walsh", "Young", "Zhang", "Adair", "Bishop")

#: Ten people a small hotel runs on.
_POSTS: tuple[tuple[str, str, str | None], ...] = (
    ("Front desk", "hourly", None),
    ("Front desk", "hourly", None),
    ("Front desk", "hourly", None),
    ("Housekeeping", "hourly", None),
    ("Housekeeping", "hourly", None),
    ("Housekeeping", "hourly", None),
    ("Housekeeping", "hourly", None),
    ("Breakfast", "hourly", None),
    ("Maintenance", "hourly", None),
    ("Front desk", "salaried", "property_gm"),
)


def staff(hotel: Hotel) -> list[Person]:
    rng = random.Random(f"staff:{hotel.code}")
    firsts = rng.sample(_FIRST, 10)
    lasts = rng.sample(_LAST, 10)
    return [
        Person(f"{f} {last}", department, pay_type, role)
        for (f, last), (department, pay_type, role) in zip(zip(firsts, lasts), _POSTS, strict=True)
    ]


# --- a night ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Night:
    business_date: date
    rooms: int
    occupied: int
    adr: Decimal
    room_revenue: Decimal
    parking: Decimal
    pet_fees: Decimal
    occupancy_tax: Decimal
    sales_tax: Decimal
    visa: Decimal
    mastercard: Decimal
    amex: Decimal
    discover: Decimal
    cash: Decimal
    direct_bill: Decimal

    @property
    def charges(self) -> Decimal:
        return (self.room_revenue + self.parking + self.pet_fees + self.occupancy_tax
                + self.sales_tax)

    @property
    def payments(self) -> Decimal:
        return self.visa + self.mastercard + self.amex + self.discover + self.cash + self.direct_bill


def night(hotel: Hotel, day: date) -> Night:
    rng = random.Random(f"{hotel.code}:{day.isoformat()}")
    weekend = day.weekday() >= 4
    occupancy = rng.uniform(0.72, 0.96) if weekend else rng.uniform(0.48, 0.82)
    occupied = max(1, min(hotel.rooms, round(hotel.rooms * occupancy)))
    base_adr = {"RTI22": 112, "SHI01": 158, "CPL07": 96}[hotel.code]
    adr = money(base_adr * rng.uniform(0.9, 1.18) * (1.12 if weekend else 1.0))
    room_revenue = money(adr * occupied)
    parking = money(rng.randint(3, 14) * 12)
    pet_fees = money(rng.choice((0, 0, 25, 50, 75)))
    occupancy_tax = money(room_revenue * Decimal("0.11"))
    sales_tax = money((parking + pet_fees) * Decimal("0.0825"))
    charges = room_revenue + parking + pet_fees + occupancy_tax + sales_tax
    # Settlements exactly offset charges (the Opera trial balance nets to zero).
    visa = money(charges * Decimal(rng.uniform(0.50, 0.58)))
    mastercard = money(charges * Decimal(rng.uniform(0.18, 0.24)))
    amex = money(charges * Decimal(rng.uniform(0.08, 0.13)))
    discover = money(charges * Decimal(rng.uniform(0.03, 0.06)))
    cash = money(charges * Decimal(rng.uniform(0.02, 0.05)))
    direct_bill = charges - visa - mastercard - amex - discover - cash
    return Night(day, hotel.rooms, occupied, adr, room_revenue, parking, pet_fees,
                 occupancy_tax, sales_tax, visa, mastercard, amex, discover, cash, direct_bill)


def nights(hotel: Hotel, last: date, days: int) -> list[Night]:
    return [night(hotel, last - timedelta(days=i)) for i in range(days - 1, -1, -1)]


# --- the PDFs -------------------------------------------------------------------------

def _courier_pages(path: Path, pages: list[tuple[list[str], bool]], size: float = 9.0) -> None:
    """Monospace pages: equal character widths become equal pixel columns,
    which is what the readers key on. (lines, landscape) per page."""
    from reportlab.lib.pagesizes import landscape, letter  # type: ignore[import-untyped]
    from reportlab.pdfgen import canvas as canvas_mod  # type: ignore[import-untyped]

    path.parent.mkdir(parents=True, exist_ok=True)
    c = canvas_mod.Canvas(str(path), pagesize=letter)
    for lines, wide in pages:
        page = landscape(letter) if wide else letter
        c.setPageSize(page)
        c.setFont("Courier", size)
        y = page[1] - 54.0
        for line in lines:
            c.drawString(54.0, y, line)
            y -= 13.0
        c.showPage()
    c.save()


def skytouch_pack(hotel: Hotel, n: Night, month: list[Night], path: Path) -> None:
    """A choiceADVANTAGE Standard Audit Pack: filler, the Hotel Journal
    Summary, the Hotel Statistics — the shape the real reader splits."""
    d = f"{n.business_date.month}/{n.business_date.day}/{n.business_date.year}"
    header = [f"Property Name: {hotel.name}", f"Business Date: {d} Property Code: {hotel.code}", ""]
    label_w, col_w = 30, 13
    cols = ["Postings", "Corrections", "Adjustments", "Totals", "GuestLedger", "ARLedger", "AdvDepLedger"]
    rows: list[tuple[str, str, Decimal]] = [
        ("Room Charge", "(RM)", n.room_revenue),
        ("Parking", "(MS)", n.parking),
        ("Pet Fee", "(PET)", n.pet_fees),
        ("State Occ Tax", "(T1)", n.occupancy_tax),
        ("Sales Tax", "(T2)", n.sales_tax),
        ("Visa Payment", "(VI)", -n.visa),
        ("MasterCard Payment", "(MC)", -n.mastercard),
        ("American Express", "(AX)", -n.amex),
        ("Discover", "(DS)", -n.discover),
        ("Cash", "(CA)", -n.cash),
        ("Direct Bill", "(DB)", -n.direct_bill),
    ]
    journal = ["Hotel Journal Summary", "", *header,
               " " * label_w + "".join(h.ljust(col_w) for h in cols)]
    for label, code, amount in rows:
        cells = [paren(amount), "0.00", "0.00", paren(amount), paren(amount), "0.00", "0.00"]
        journal.append(f"{label} {code}".ljust(label_w) + "".join(x.ljust(col_w) for x in cells))
    journal.append("Today's Total:".ljust(label_w) + "".join("0.00".ljust(col_w) for _ in cols))

    so_far = [m for m in month if m.business_date <= n.business_date]
    ptd_occ = sum(m.occupied for m in so_far)
    ptd_rev = sum((m.room_revenue for m in so_far), Decimal("0"))
    ytd_occ, ytd_rev = ptd_occ * 8 + 1200, ptd_rev * 8 + Decimal("150000.00")
    stats_rows = [
        ("Total Rooms", [str(n.rooms), str(n.rooms * len(so_far)), str(n.rooms * len(so_far)),
                         str(n.rooms * (len(so_far) * 8 + 20)), str(n.rooms * (len(so_far) * 8 + 20))]),
        ("Total Occupied Rooms", [str(n.occupied), str(ptd_occ), str(int(ptd_occ * 0.95)),
                                  str(ytd_occ), str(int(ytd_occ * 0.97))]),
        ("ADR for Total Occupied Rooms", [fmt(n.adr), fmt(money(ptd_rev / max(ptd_occ, 1))),
                                          fmt(money(ptd_rev / max(ptd_occ, 1) * Decimal("0.98"))),
                                          fmt(money(ytd_rev / max(ytd_occ, 1))),
                                          fmt(money(ytd_rev / max(ytd_occ, 1) * Decimal("0.97")))]),
        ("RevPar", [fmt(money(n.room_revenue / n.rooms)),
                    fmt(money(ptd_rev / (n.rooms * len(so_far)))),
                    fmt(money(ptd_rev / (n.rooms * len(so_far)) * Decimal("0.95"))),
                    fmt(money(ytd_rev / (n.rooms * (len(so_far) * 8 + 20)))),
                    fmt(money(ytd_rev / (n.rooms * (len(so_far) * 8 + 20)) * Decimal("0.96")))]),
        ("Total Room Revenue", [fmt(n.room_revenue), fmt(ptd_rev), fmt(money(ptd_rev * Decimal("0.95"))),
                                fmt(ytd_rev), fmt(money(ytd_rev * Decimal("0.96")))]),
    ]
    stats_label_w, stats_col_w = 30, 18
    groups = [(d, ""), ("PTD", "Current "), ("PTD", "Last Year "), ("YTD", "Current "), ("YTD", "Last ")]
    line = [" "] * (stats_label_w + stats_col_w * len(groups))
    for i, (last, prefix) in enumerate(groups):
        start = stats_label_w + i * stats_col_w - len(prefix)
        for k, ch in enumerate(prefix + last):
            line[start + k] = ch
    stats = ["Hotel Statistics", "", *header,
             "Room Statistics".ljust(stats_label_w - 4) + "".join(line)[stats_label_w - 4:]]
    for label, values in stats_rows:
        stats.append(label.ljust(stats_label_w) + "".join(v.ljust(stats_col_w) for v in values))

    _courier_pages(path, [
        (["A/R Aging", "", "Account                     Balance",
          "Test Rewards Account         100.00", "Sample Direct Bill Co        250.00"], False),
        (["Guest Ledger", "", *header, "ROOM  NAME, COMPANY        BALANCE",
          "101   TEST, GUEST ONE        142.00", "204   SAMPLE, GUEST TWO      288.00"], False),
        (journal, True),
        (stats, True),
    ], size=8.0)


def opera_trial_balance(hotel: Hotel, n: Night, path: Path) -> None:
    d = f"{n.business_date:%m-%d-%y}"
    code_w, desc_w = 10, 46
    rows: list[tuple[str, str, str, Decimal]] = [
        ("Revenue", "1000", "Room Revenue", n.room_revenue),
        ("Revenue", "5105", "Parking", n.parking),
        ("Revenue", "5210", "Pet Fee", n.pet_fees),
        ("Non Revenue", "7100", "Transient Occupancy Tax", n.occupancy_tax),
        ("Non Revenue", "7104", "Sales Tax", n.sales_tax),
        ("Payment", "9004", "Visa", -n.visa),
        ("Payment", "9005", "MasterCard", -n.mastercard),
        ("Payment", "9003", "American Express", -n.amex),
        ("Payment", "9007", "Discover", -n.discover),
        ("Payment", "9002", "City Ledger", -(n.direct_bill + n.cash)),
    ]
    lines = [hotel.name.upper(), "Trial Balance", f"Business Date: {d}                 Property: {hotel.code}",
             "", "Code".ljust(code_w) + "Description".ljust(desc_w) + "Amount", "-" * 74]
    current: str | None = None
    for section, code, desc, amount in rows:
        if section != current:
            lines.extend(["", section])
            current = section
        lines.append(code.ljust(code_w) + desc.ljust(desc_w) + fmt(amount).rjust(14))
    guest = money(Decimal("18000") + n.room_revenue * Decimal("0.6"))
    ar = money(Decimal("5000") + n.direct_bill * 3)
    lines.extend([
        "", "Transaction Total Today".ljust(code_w + desc_w) + fmt(n.charges + (-n.payments)).rjust(14),
        "", "Guest Ledger", "Balance Today".ljust(code_w + desc_w) + fmt(guest).rjust(14),
        "", "AR Ledger", "Balance Today".ljust(code_w + desc_w) + fmt(ar).rjust(14),
        "", "Deposit Ledger", "Balance Today".ljust(code_w + desc_w) + fmt(Decimal("900.00")).rjust(14),
        "", "Package Ledger", "Balance Today".ljust(code_w + desc_w) + fmt(Decimal("0.00")).rjust(14),
        "", "Hotel Balance".ljust(code_w + desc_w) + fmt(guest + ar + Decimal("900.00")).rjust(14),
        "", "Guest Ledger is in balance",
    ])
    _courier_pages(path, [(lines, False)])


def autoclerk_summary(hotel: Hotel, n: Night, month: list[Night], path: Path) -> None:
    so_far = [m for m in month if m.business_date <= n.business_date]

    def mtd(pick: str) -> Decimal:
        return sum((getattr(m, pick) for m in so_far), Decimal("0"))

    def ytd(pick: str) -> Decimal:
        return money(mtd(pick) * 7 + mtd(pick) / max(len(so_far), 1) * 40)

    name_w, col_w = 30, 16
    rows: list[tuple[str, str, str]] = [
        ("Room", "Room Rent", "room_revenue"), ("Tax", "Occupancy Tax", "occupancy_tax"),
        ("Tax", "County Tax", "sales_tax"), ("Misc", "Pet Fee", "pet_fees"),
        ("Parking", "Parking Fees", "parking"), ("Credit Cards", "Visa", "visa"),
        ("Credit Cards", "MasterCard", "mastercard"), ("Credit Cards", "American Express", "amex"),
        ("Credit Cards", "Discover", "discover"), ("Cash", "Cash", "cash"),
        ("Accounts", "Direct Bill", "direct_bill"),
    ]
    lines = [hotel.name.upper(), "Transaction Summary",
             f"Business Date: {n.business_date:%m/%d/%Y}", "",
             "Category".ljust(name_w) + "TODAY".rjust(col_w) + "MTD".rjust(col_w) + "YTD".rjust(col_w),
             "-" * 78]
    current: str | None = None
    total = Decimal("0")
    for category, label, pick in rows:
        if category != current:
            lines.extend(["", category])
            current = category
        sign = -1 if category in ("Credit Cards", "Cash", "Accounts") else 1
        today = getattr(n, pick) * sign
        total += today
        lines.append(("  " + label).ljust(name_w) + fmt(today).rjust(col_w)
                     + fmt(mtd(pick) * sign).rjust(col_w) + fmt(ytd(pick) * sign).rjust(col_w))
    lines.extend(["", "GRAND TOTAL".ljust(name_w) + fmt(total).rjust(col_w)])
    _courier_pages(path, [(lines, False)])


def write_reports(hotel: Hotel, out: Path, last: date, days: int = 30) -> list[Path]:
    """One night-audit PDF per night, named the way the systems name them."""
    month = nights(hotel, last, days)
    written: list[Path] = []
    for n in month:
        d = n.business_date
        if hotel.pms == "SKYTOUCH":
            path = out / f"All_Night_Audit_Reports_{hotel.code}_STANDARD AUDIT PACK_{d.isoformat()}.pdf"
            skytouch_pack(hotel, n, month, path)
        elif hotel.pms == "OPERA":
            path = out / f"Trial Balance {d:%m.%d.%Y} - Opera.pdf"
            opera_trial_balance(hotel, n, path)
        else:
            path = out / f"Autoclerk - Transaction Summary {d:%m.%d.%Y}.pdf"
            autoclerk_summary(hotel, n, month, path)
        written.append(path)
    return written


# --- the statements ----------------------------------------------------------------------

def bank_statement_csv(hotel: Hotel, month: list[Night]) -> str:
    """What the bank shows for the same nights: card payouts a couple of days
    later less the processor's fee, cash banked weekly, payroll every other
    Friday, the bills — and two lines that match nothing, on purpose."""
    rng = random.Random(f"bank:{hotel.code}")
    rows: list[tuple[date, str, Decimal]] = []
    cash_week = Decimal("0")
    for n in month:
        posted = n.business_date + timedelta(days=2)
        rows.append((posted, f"BANKCARD MERCH DEP {hotel.code[-3:]}0421",
                     money((n.visa + n.mastercard) * Decimal("0.975"))))
        rows.append((n.business_date + timedelta(days=3), "AMERICAN EXPRESS SETTLEMENT",
                     money(n.amex * Decimal("0.972"))))
        rows.append((posted, "DISCOVER NETWORK SETTLEMENT", money(n.discover * Decimal("0.98"))))
        cash_week += n.cash
        if n.business_date.weekday() == 0:  # Monday: the week's cash goes to the bank
            rows.append((n.business_date, "DEPOSIT", cash_week))
            cash_week = Decimal("0")
        if n.business_date.weekday() == 4 and n.business_date.day % 14 < 7:
            rows.append((n.business_date, "GUSTO PAYROLL 26", money(-Decimal(rng.randint(6200, 9800)))))
    first = month[0].business_date
    rows += [
        (first + timedelta(days=5), f"{hotel.city.upper()} ELECTRIC CO", money(-Decimal(rng.randint(1400, 2600)))),
        (first + timedelta(days=9), f"CITY OF {hotel.city.upper()} WATER", money(-Decimal(rng.randint(300, 700)))),
        (first + timedelta(days=12), "SBA LOAN PMT", Decimal("-2450.00")),  # nothing in the books
        (first + timedelta(days=15), "MOBILE DEPOSIT", Decimal("412.00")),  # nor this
        (first + timedelta(days=20), "FRANCHISE FEE ACH", money(-month[0].room_revenue * 3)),
    ]
    rows.sort(key=lambda r: r[0])
    balance = Decimal("48000.00")
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Date", "Description", "Amount", "Balance"])
    for posted, description, amount in rows:
        balance += amount
        w.writerow([f"{posted:%m/%d/%Y}", description, f"{amount:.2f}", f"{balance:.2f}"])
    return buf.getvalue()


_MERCHANTS: tuple[tuple[str, int, int], ...] = (
    ("HOME DEPOT #6512", 40, 320), ("AMAZON MKTPL*", 18, 240), ("SAMS CLUB #4410", 120, 480),
    ("COSTCO WHSE #0913", 150, 600), ("WALMART SUPERCENTER", 30, 180), ("LOWES #2201", 45, 260),
    ("OFFICE DEPOT #331", 20, 90), ("MICROSOFT*M365", 72, 72), ("GOOGLE *WORKSPACE", 36, 36),
    ("CHEVRON 0123", 30, 70), ("USPS PO 5510", 8, 40), ("ECOLAB SVCS", 180, 420),
    ("SYSCO FOODS", 220, 610), ("CINTAS CORP", 95, 210), ("STATE FARM INSURANCE", 640, 640),
    ("BEST WESTERN BRAND FEE", 900, 1400), ("SPECTRUM BUSINESS", 189, 189), ("PIZZA HUT 04412", 24, 60),
    ("UBER *TRIP", 14, 38), ("TRUE VALUE HDW", 12, 85),
)


def card_statement_csv(hotel: Hotel, last: date, days: int = 30) -> str:
    rng = random.Random(f"card:{hotel.code}:{last.isoformat()}")
    rows: list[tuple[date, str, Decimal]] = []
    for merchant, low, high in _MERCHANTS:
        for _ in range(rng.choice((1, 1, 2))):
            when = last - timedelta(days=rng.randint(0, days - 1))
            suffix = f" {rng.randint(1000, 9999)}" if merchant.endswith("*") else ""
            rows.append((when, f"{merchant}{suffix} {hotel.city.upper()}",
                         -money(Decimal(rng.randint(low * 100, high * 100)) / 100)))
    rows.append((last - timedelta(days=3), "PAYMENT - THANK YOU", Decimal("2500.00")))
    rows.sort(key=lambda r: r[0])
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Transaction Date", "Description", "Amount"])
    for when, description, amount in rows:
        w.writerow([f"{when:%m/%d/%Y}", description, f"{amount:.2f}"])
    return buf.getvalue()


def write_statements(hotel: Hotel, out: Path, last: date, days: int = 30) -> tuple[Path, Path]:
    out.mkdir(parents=True, exist_ok=True)
    bank = out / f"{hotel.code} bank statement {last:%Y-%m}.csv"
    card = out / f"{hotel.code} card statement {last:%Y-%m}.csv"
    bank.write_text(bank_statement_csv(hotel, nights(hotel, last, days)), encoding="utf-8")
    card.write_text(card_statement_csv(hotel, last, days), encoding="utf-8")
    return bank, card
