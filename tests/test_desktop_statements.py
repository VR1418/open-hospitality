"""Reading a statement CSV and matching it, offline."""

from datetime import date
from decimal import Decimal

import pytest

from usali.desktop import statements
from usali.desktop.statements import ParsedLine, StatementError, match_credit, merchant_key, parse_csv


def test_a_typical_bank_csv_reads_whatever_the_columns_are_called() -> None:
    lines = parse_csv(
        "Date,Description,Amount,Running Bal.\n"
        '09/12/2026,"BANKCARD DEP 1234567",  "$2,406.13",  "$10,000.00"\n'
        "09/12/2026,GUSTO PAYROLL 260912,(3210.55),6789.45\n"
        "9/13/2026,CHECK 1041,-125.00,\n"
    )
    assert [(ln.posted_on, ln.amount) for ln in lines] == [
        (date(2026, 9, 12), Decimal("2406.13")),
        (date(2026, 9, 12), Decimal("-3210.55")),
        (date(2026, 9, 13), Decimal("-125.00")),
    ]
    assert lines[0].balance == Decimal("10000.00") and lines[2].balance is None


def test_debit_and_credit_columns_and_other_date_styles() -> None:
    lines = parse_csv(
        "Posted Date;Details;Money out;Money in\n"
        "2026-09-12;AMEX SETTLEMENT;;590.10\n"
        "Sep 13, 2026;CITY WATER;88.20;\n"
    )
    assert [ln.amount for ln in lines] == [Decimal("590.10"), Decimal("-88.20")]
    assert lines[1].posted_on == date(2026, 9, 13)


def test_a_file_that_is_not_a_statement_is_refused_in_words() -> None:
    with pytest.raises(StatementError, match="name the columns"):
        parse_csv("hello,world\n1,2\n")
    with pytest.raises(StatementError, match="no rows"):
        parse_csv("Date,Description,Amount\n")
    with pytest.raises(StatementError, match="couldn't be read"):
        parse_csv("Date,Description,Amount\nnot a date,x,1\nnope,y,2\n09/12/2026,z,3\n")


SETTLED = {
    (date(2026, 9, 10), "Visa"): Decimal("1500.00"),
    (date(2026, 9, 10), "MasterCard"): Decimal("906.13"),
    (date(2026, 9, 11), "Visa"): Decimal("1200.00"),
    (date(2026, 9, 11), "American Express"): Decimal("590.10"),
    (date(2026, 9, 10), "Cash"): Decimal("300.00"),
}


def test_a_payout_is_one_nights_cards_exactly() -> None:
    used: set[tuple[date, str]] = set()
    got = match_credit(Decimal("2406.13"), date(2026, 9, 12), ("Visa", "MasterCard"),
                       "Visa/MasterCard", SETTLED, used)
    assert got is not None and got.kind == "settlement"
    assert got.note == "Visa/MasterCard settled 9/10"
    assert (date(2026, 9, 10), "Visa") in used and (date(2026, 9, 11), "Visa") not in used


def test_a_payout_can_be_several_nights_less_a_fee_and_nights_are_used_once() -> None:
    used: set[tuple[date, str]] = set()
    # Two nights of Visa/MC, 2.5% fee taken out.
    gross = Decimal("3606.13")
    net = (gross * Decimal("0.975")).quantize(Decimal("0.01"))
    got = match_credit(net, date(2026, 9, 13), ("Visa", "MasterCard"), "Visa/MasterCard",
                       SETTLED, used)
    assert got is not None and "settled 9/10–9/11, less $" in got.note
    assert got.matched_amount == gross
    # The same nights cannot pay out twice.
    again = match_credit(net, date(2026, 9, 13), ("Visa", "MasterCard"), "Visa/MasterCard",
                         SETTLED, used)
    assert again is None


def test_a_payout_too_far_below_is_not_matched() -> None:
    got = match_credit(Decimal("1000.00"), date(2026, 9, 12), ("Visa", "MasterCard"),
                       "Visa/MasterCard", SETTLED, set())
    assert got is None


def test_descriptions_say_what_they_are() -> None:
    def line(d: str, a: str) -> ParsedLine:
        return ParsedLine(date(2026, 9, 12), d, Decimal(a))

    used: set[tuple[date, str]] = set()
    amex = statements._match_one(line("AMERICAN EXPRESS SETTLEMENT", "590.10"), SETTLED, used)
    assert amex.kind == "settlement" and amex.note == "American Express settled 9/11"
    cash = statements._match_one(line("DEPOSIT", "300.00"), SETTLED, used)
    assert cash.kind == "cash"
    pay = statements._match_one(line("GUSTO PAYROLL", "-3210.55"), SETTLED, used)
    assert pay.kind == "payroll"
    loan = statements._match_one(line("SBA LOAN PMT", "-2500.00"), SETTLED, used)
    assert loan.kind == "unmatched" and "mark it" in loan.note
    stray = statements._match_one(line("BANKCARD DEP", "99.99"), SETTLED, used)
    assert stray.kind == "unmatched" and "No Visa/MasterCard settlement" in stray.note


def test_a_merchant_is_the_same_merchant_however_the_card_prints_it() -> None:
    assert merchant_key("AMAZON MKTPL*2K4J1 SEATTLE WA 09/12") == merchant_key("AMAZON MKTPL*9Q2X SEATTLE WA")
    assert merchant_key("HOME DEPOT #6512 CARLSBAD") == "HOME DEPOT CARLSBAD"
    assert merchant_key("SQ *JOE'S PLUMBING") != merchant_key("SQ *ANNIE'S FLOWERS")


def test_totals_by_category_read_unsorted_as_such() -> None:
    got = statements.totals_by_category([
        ("Utilities — Electricity", Decimal("-410.00")), (None, Decimal("-20.00")),
        ("Utilities — Electricity", Decimal("-90.00")),
    ])
    assert got == [("Utilities — Electricity", Decimal("500.00")), ("Not sorted yet", Decimal("20.00"))]


def test_a_transaction_date_column_is_not_mistaken_for_the_description() -> None:
    lines = parse_csv("Transaction Date,Description,Amount\n06/02/2026,HOME DEPOT #6512,-142.18\n")
    assert lines[0].description == "HOME DEPOT #6512"
