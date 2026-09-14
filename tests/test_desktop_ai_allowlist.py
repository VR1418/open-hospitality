"""What may leave this machine (PRD AI-4, ADR-D7).

The PRD asks for "a redaction layer with its own tests — not by prompt
instructions", so these are those tests. They run offline: no database, no
key, no network.

Two promises. The prompt is BUILT from a `CodeQuestion` and therefore contains
only what that object names. And the outbound scan REFUSES rather than masks,
because a mask would turn a construction bug into a silent near-miss.
"""

from datetime import date
from decimal import Decimal

import pytest

from usali.desktop.ai.allowlist import (
    BlockedContent,
    CodeQuestion,
    LineChoice,
    check,
    render,
)

CHOICES = (
    LineChoice("Operated Departments", "Rooms", "Room Revenue"),
    LineChoice("Operated Departments", "Rooms", "Other Rooms Revenue"),
    LineChoice("Miscellaneous Income", "Miscellaneous", "Pet Fee"),
)

QUESTION = CodeQuestion(
    pms_source="SKYTOUCH",
    code="ZZQ",
    description="Cabana Rental",
    times_seen=4,
    total_amount=Decimal("250.0000"),
    first_seen=date(2026, 4, 1),
    last_seen=date(2026, 4, 8),
    sample_amounts=(Decimal("50.0000"), Decimal("200.0000")),
    choices=CHOICES,
)


def test_the_prompt_holds_the_question_and_the_choices() -> None:
    text = render(QUESTION)
    assert "SKYTOUCH" in text and "ZZQ" in text and "Cabana Rental" in text
    assert "2026-04-01 to 2026-04-08" in text
    assert "250.0000" in text
    for i, choice in enumerate(CHOICES):
        assert f"{i}. {choice.render()}" in text


def test_the_prompt_tells_the_model_it_may_refuse() -> None:
    """AI-7: on tax and capitalisation it is REQUIRED to refuse. The
    instruction is in the prompt — and, because a prompt is not a control,
    a decline without a reason is refused in code (see the port's Answer)."""
    text = render(QUESTION).lower()
    assert "tax treatment" in text and "capital" in text
    assert "decline_reason" in text


def test_a_code_seen_on_one_day_says_that_day_once() -> None:
    one = CodeQuestion(**{**QUESTION.__dict__, "last_seen": date(2026, 4, 1)})
    assert "2026-04-01 to" not in render(one)
    assert "2026-04-01" in render(one)


def test_a_description_the_report_did_not_print_says_so() -> None:
    none = CodeQuestion(**{**QUESTION.__dict__, "description": None})
    assert "(no description printed)" in render(none)


def test_nothing_a_built_prompt_contains_is_refused() -> None:
    """The two halves have to agree: if construction is right, the scan is
    silent. A scan that blocked ordinary prompts would be worse than none,
    because it would be switched off."""
    check(render(QUESTION), names={"priya patel", "sam okonkwo"})


def test_a_card_number_is_refused_not_masked() -> None:
    with pytest.raises(BlockedContent) as e:
        check("charge on 4111 1111 1111 1111 today")
    assert "card number" in str(e.value)
    # The refusal never quotes the value it found — quoting it would copy the
    # number into the log this exception ends up in.
    assert "4111" not in str(e.value)


def test_a_social_security_number_is_refused() -> None:
    with pytest.raises(BlockedContent) as e:
        check("employee 123-45-6789 asked about this")
    assert "Social Security" in str(e.value)
    assert "123-45" not in str(e.value)


def test_a_long_run_of_digits_is_refused() -> None:
    """An account or routing number. Amounts carry a decimal point and codes
    are short, so nine bare digits in a row is not a thing a built prompt has."""
    with pytest.raises(BlockedContent) as e:
        check("deposits to 000123456789 this month")
    assert "account number" in str(e.value)


def test_an_employee_name_is_refused() -> None:
    with pytest.raises(BlockedContent) as e:
        check("refund approved by Priya Patel at the desk", names={"priya patel"})
    assert "employee's name" in str(e.value)
    assert "Priya" not in str(e.value)


def test_a_name_is_found_however_it_is_cased() -> None:
    with pytest.raises(BlockedContent):
        check("PRIYA PATEL signed for it", names={"priya patel"})


def test_a_short_name_is_not_used_as_a_needle() -> None:
    """`forbidden_names` drops very short names on purpose. Blocking every
    prompt containing "Ann" would block "Annual", and a scan that cries wolf
    gets turned off."""
    from usali.desktop.ai.allowlist import forbidden_names

    class _FakeSession:
        def scalars(self, _stmt: object) -> list[str]:
            return ["Ann", "  ", "Priya Patel"]

    assert forbidden_names(_FakeSession()) == frozenset({"priya patel"})  # type: ignore[arg-type]


def test_the_question_names_every_field_that_may_leave() -> None:
    """The allow-list IS this field list. If it grows, that is a deliberate
    widening of what leaves the machine and this test is where it is noticed
    (ADR-D7)."""
    assert set(CodeQuestion.__dataclass_fields__) == {
        "pms_source",
        "code",
        "description",
        "times_seen",
        "total_amount",
        "first_seen",
        "last_seen",
        "sample_amounts",
        "choices",
    }
    # And none of them is a person, a rate, or an account.
    assert not {f for f in CodeQuestion.__dataclass_fields__ if "name" in f} - {"pms_source"}


def test_a_guest_name_is_refused_even_though_we_never_stored_it() -> None:
    """Employee names we can look up. A GUEST's we cannot — the product
    deliberately never stores one — so for report text the printed SHAPE is
    all that stands between a guest list and a third party."""
    with pytest.raises(BlockedContent) as e:
        check("CHECKED OUT DOE, JANE MARIE 318 3/4/26")
    assert "person's name" in str(e.value)
    assert "DOE" not in str(e.value)


def test_a_heading_that_looks_like_a_name_errs_towards_holding_it_back() -> None:
    """"NAME, COMPANY" is a column heading, not a person — but nothing in the
    text says so. The rule errs towards refusing, because the cost is one page
    withheld and the cost of the other mistake is a guest list sent to a third
    party. Measured on a real pack, it costs nothing: the summary pages the
    figures live on survive it."""
    with pytest.raises(BlockedContent):
        check("DATE ACCOUNT ROOM NAME, COMPANY GUEST TAX ID")
    # Ordinary prose and mixed case are untouched: the shape is ALL CAPS,
    # which is how a front-desk system prints a guest.
    check("Description (Transaction Code) Postings, Corrections, Adjustments")


def test_a_summary_line_of_codes_and_money_passes() -> None:
    """What a night-audit summary page actually looks like. If the scan
    blocked this there would be nothing left to send."""
    check(
        "Hotel Journal Summary Business Date: 9/10/2026 Property Code: RTI22 "
        "RM Room Charge 7,147.07 T1 State Occ Tax 437.42 VI Visa Payment (2,406.13)"
    )


# --- the shapes OCR and row-clustering produce (raised by upstream's author) -----

def test_a_card_number_split_across_a_line_break_is_still_refused() -> None:
    """An OCR'd pack, or a page the PDF reader clustered into rows, prints a
    card number with the break wherever the layout put it. The one-line rule
    misses that; this does not."""
    for text in (
        "Visa 4111 1111\n1111 1111 auth 3/4/26",
        "4111-1111-\n1111-1111",
        "card\t4111\t1111\t1111\t1111",
        "AMEX 3782 822463\n10005",
    ):
        with pytest.raises(BlockedContent) as e:
            check(text)
        assert "card number" in str(e.value) and "4111" not in str(e.value)


def test_four_year_like_columns_are_not_a_card() -> None:
    """Groups of four digits with spaces between them are also what a
    statistics page looks like. The Luhn check tells them apart."""
    check("Rooms available 2026 2025 2024 2022")
    check("Total Rooms 60 46 47 44 2026 47 318 45")


def test_a_social_security_number_split_across_a_break_is_still_refused() -> None:
    for text in ("123-45-\n6789", "123-\n45-6789", "SSN 123 - 45 - 6789"):
        with pytest.raises(BlockedContent) as e:
            check(text)
        assert "Social Security" in str(e.value)


def test_three_two_four_digits_with_plain_spaces_is_a_statistics_row() -> None:
    """"318 45 2026" is rooms, a percentage and a year — not a Social
    Security number. Holding every such page back would leave nothing."""
    check("In House 318 45 2026 Occupied 46")


def test_a_guest_name_with_the_break_after_the_comma_is_still_refused() -> None:
    with pytest.raises(BlockedContent):
        check("318 DOE,\nJANE MARIE 3/4/26")


def test_an_email_address_or_phone_number_is_refused() -> None:
    with pytest.raises(BlockedContent) as e:
        check("contact jane.doe@example.com")
    assert "email" in str(e.value) and "jane" not in str(e.value)
    for phone in ("(408) 555-0134", "408-555-0134", "408.555.0134"):
        with pytest.raises(BlockedContent):
            check(f"call {phone}")
    # Amounts and dates are not phone numbers.
    check("Total 7,147.07 437.42 on 9/10/2026 to 9/12/2026")
