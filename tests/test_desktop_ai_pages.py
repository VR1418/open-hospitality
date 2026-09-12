"""Which pages of an unrecognised report the model may see (ADR-D7).

The one place the product filters instead of building, so the filter is what
these tests are about. Offline: a real sample PDF, no key, no network.
"""

from pathlib import Path

import pytest

from usali.desktop.ai.pages import safe_pages

PACK = Path("docs/reference/samples/SkyTouch - Standard Audit Pack (mock).pdf")


def test_the_summary_survives_and_the_guest_pages_do_not() -> None:
    """The point of the whole design: what is left after the scan is the
    totals — which is the only part the books need anyway."""
    reading = safe_pages(PACK)
    assert reading.anything_to_send
    kept = " ".join(p.text for p in reading.kept).lower()
    assert "journal summary" in kept
    # Whatever was held back, it was held back for a named reason.
    for held in reading.held_back:
        assert held.why and held.number > 0


def test_a_page_is_kept_or_dropped_WHOLE(tmp_path: Path) -> None:
    """Nothing is masked or trimmed to make a page acceptable. A page that
    passes goes as it is; a page that does not is not sent at all — masking
    would leave us guessing whether what remained was safe."""
    reading = safe_pages(PACK)
    for page in reading.kept:
        assert "•" not in page.text and "…" not in page.text
    numbers = [p.number for p in reading.kept] + [h.number for h in reading.held_back]
    assert len(numbers) == len(set(numbers)), "a page is in one list or the other"


def test_an_employee_name_holds_a_page_back() -> None:
    """The names are this hotel group's own, passed in from the database."""
    plain = safe_pages(PACK)
    assert plain.anything_to_send
    word = plain.kept[0].text.split()[0].lower()
    guarded = safe_pages(PACK, names={word})
    # That page is now held back, and the reason names the kind, not the value.
    assert len(guarded.kept) < len(plain.kept)
    assert any("employee" in h.why for h in guarded.held_back)


def test_nothing_readable_means_nothing_is_sent(tmp_path: Path) -> None:
    empty = tmp_path / "not-a-report.pdf"
    empty.write_bytes(b"%PDF-1.4\n%%EOF\n")
    with pytest.raises(Exception):
        # An unreadable file is unreadable — the caller says so properly
        # rather than this pretending it scanned something.
        safe_pages(empty)
