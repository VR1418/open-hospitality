"""Learning how a report is read from what the owner confirmed — offline."""

from datetime import date
from decimal import Decimal

from usali.desktop.ai.pages import Page
from usali.desktop.ai.recipes import LAYOUTS, Recipe, Row, infer, replay

NIGHT_ONE = (
    Page(1, "Cover Sheet\nPrinted by the night auditor"),
    Page(2, "\n".join([
        "Hotel Journal Summary",
        "Date Range: 9/10/2026 - 9/10/2026 Property Code: RTI22",
        "Description (Transaction Code) Postings Corrections Adjustments Totals",
        "Room Charge (RM) 7,147.07 0.00 0.00 7,147.07",
        "State Occ Tax (T1) 437.42 0.00 0.00 437.42",
        "Visa Payment (VI) (2,406.13) 0.00 0.00 (2,406.13)",
        "Total 5,178.36",
    ])),
)

CONFIRMED = [
    Row("RM", "Room Charge", Decimal("7147.07")),
    Row("T1", "State Occ Tax", Decimal("437.42")),
    Row("VI", "Visa Payment", Decimal("-2406.13")),
]


def test_a_recipe_is_learned_that_reads_exactly_what_was_confirmed() -> None:
    recipe = infer(NIGHT_ONE, CONFIRMED, date(2026, 9, 10))
    assert recipe is not None
    assert recipe.title == "Hotel Journal Summary"
    assert recipe.layout == "description (code) amounts"
    # The night's total is the last column.
    assert recipe.amount_index == -1
    assert (recipe.date_label, recipe.date_format) == ("Date Range", "m/d/yyyy")
    assert replay(recipe, NIGHT_ONE) == (date(2026, 9, 10), CONFIRMED)


def test_the_next_night_is_read_with_no_model_and_the_last_column_wins() -> None:
    recipe = infer(NIGHT_ONE, CONFIRMED, date(2026, 9, 10))
    assert recipe is not None
    night_two = (Page(1, "\n".join([
        "Hotel Journal Summary",
        "Date Range: 9/11/2026 - 9/11/2026 Property Code: RTI22",
        "Description (Transaction Code) Postings Corrections Adjustments Totals",
        "Room Charge (RM) 6,000.00 (100.00) 0.00 5,900.00",
        "Pet Fee (PET) 50.00 0.00 0.00 50.00",
    ])),)
    when, rows = replay(recipe, night_two)  # type: ignore[misc]
    assert when == date(2026, 9, 11)
    # A correction on the night shows why the total column, not postings.
    assert rows == [Row("RM", "Room Charge", Decimal("5900.00")),
                    Row("PET", "Pet Fee", Decimal("50.00"))]


def test_nothing_is_learned_when_the_confirmed_rows_were_edited() -> None:
    edited = [*CONFIRMED[:2], Row("VI", "Visa Payment", Decimal("-2400.00"))]
    assert infer(NIGHT_ONE, edited, date(2026, 9, 10)) is None
    # Nor from a date the pages do not print.
    assert infer(NIGHT_ONE, CONFIRMED, date(2026, 9, 11)) is None


def test_a_report_whose_shape_changed_is_not_silently_read() -> None:
    recipe = infer(NIGHT_ONE, CONFIRMED, date(2026, 9, 10))
    assert recipe is not None
    renamed = (Page(1, NIGHT_ONE[1].text.replace("Hotel Journal Summary", "Daily Journal")),)
    assert replay(recipe, renamed) is None
    no_date = (Page(1, NIGHT_ONE[1].text.replace("Date Range: 9/10/2026 - 9/10/2026", "")),)
    assert replay(recipe, no_date) is None


def test_other_layouts_and_date_styles() -> None:
    pages = (Page(1, "\n".join([
        "Trial Balance",
        "HARBOUR REST LODGE 07-07-26 03:26",
        "1000 *Accommodation 10,395.00",
        "5105 Parking 410.00",
        "9004 Visa (1,200.00)",
    ])),)
    confirmed = [Row("1000", "*Accommodation", Decimal("10395.00")),
                 Row("5105", "Parking", Decimal("410.00")),
                 Row("9004", "Visa", Decimal("-1200.00"))]
    recipe = infer(pages, confirmed, date(2026, 7, 7))
    assert recipe is not None and recipe.layout == "code description amounts"
    assert replay(recipe, pages) == (date(2026, 7, 7), confirmed)


def test_a_stored_recipe_is_only_ever_one_of_the_apps_own_layouts() -> None:
    recipe = infer(NIGHT_ONE, CONFIRMED, date(2026, 9, 10))
    assert recipe is not None
    assert Recipe.from_json(recipe.to_json()) == recipe
    # A recipe is data naming a layout, never a pattern someone supplied.
    assert Recipe.from_json({**recipe.to_json(), "layout": "(a+)+$"}) is None
    assert Recipe.from_json({**recipe.to_json(), "date_format": "%s"}) is None
    assert Recipe.from_json({"title": "x"}) is None
    assert set(LAYOUTS) == {"description (code) amounts", "code description amounts",
                            "description code amounts"}
    # The fingerprint is the shape, not the night.
    assert recipe.fingerprint == Recipe(**{**recipe.to_json(), "amount_index": 0}).fingerprint
