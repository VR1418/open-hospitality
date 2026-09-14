"""The made-up group's reports are read by the real intake — every system,
every night — and its statements match its own nights."""

from datetime import date
from decimal import Decimal
from pathlib import Path

from sqlalchemy import func, select

from usali.desktop import demo, statements
from usali.desktop.demo import HOTELS, nights, staff
from usali.ingestion import process_upload
from usali.mapping.loader import load_mappings
from usali.mapping.schedules import seed_schedules
from usali.models import (
    PmsDailyStatisticStage,
    Property,
    PropertyDetectionAlias,
    UsaliFinancialFact,
    UsaliStatisticFact,
)
from usali.reporting import SETTLEMENTS_MAJOR

LAST = date(2026, 9, 12)


def _register(session: object) -> None:
    for h in HOTELS:
        session.add(Property(property_id=h.code, name=h.name.upper(), pms_source=h.pms))  # type: ignore[attr-defined]
    session.flush()  # type: ignore[attr-defined]
    for h in HOTELS:
        phrase = f"PROPERTY CODE: {h.code}" if h.pms == "SKYTOUCH" else h.name.upper()
        session.add(PropertyDetectionAlias(  # type: ignore[attr-defined]
            property_id=h.code, pms_source=h.pms, match_phrase=phrase,
        ))


def test_every_hotels_reports_are_read_by_the_real_intake(db_session, tmp_path: Path, founding_org) -> None:
    seed_schedules(db_session, "mapping/usali_schedules.yaml")
    for source in ("skytouch", "opera", "autoclerk"):
        load_mappings(db_session, f"mapping/{source}.yaml")
    _register(db_session)
    db_session.commit()

    for hotel in HOTELS:
        written = demo.write_reports(hotel, tmp_path / "drop" / hotel.code, LAST, days=3)
        assert len(written) == 3
        for path in written:
            results = process_upload(
                db_session, path, processed_dir=tmp_path / "read", failed_dir=tmp_path / "failed",
            )
            assert results, path.name
            assert all(r.property_id == hotel.code for r in results)
        assert not any((tmp_path / "failed").glob("*.pdf"))

        # The figures in the books are the figures that were invented.
        for n in nights(hotel, LAST, 3):
            settled = db_session.execute(
                select(func.sum(UsaliFinancialFact.amount)).where(
                    UsaliFinancialFact.property_id == hotel.code,
                    UsaliFinancialFact.business_date == n.business_date,
                    UsaliFinancialFact.usali_major_category == SETTLEMENTS_MAJOR,
                )
            ).scalar_one()
            assert abs(Decimal(settled)) == n.payments, (hotel.code, n.business_date)
            room = db_session.execute(
                select(func.sum(UsaliFinancialFact.amount)).where(
                    UsaliFinancialFact.property_id == hotel.code,
                    UsaliFinancialFact.business_date == n.business_date,
                    UsaliFinancialFact.usali_line_item == "Room Revenue",
                )
            ).scalar_one()
            assert Decimal(room) == n.room_revenue

    # choiceADVANTAGE packs carry the statistics the dashboard needs (the
    # night's own column is staged as ACTUAL; ingestion reads the room count
    # from it).
    rooms = db_session.execute(
        select(PmsDailyStatisticStage.value).where(
            PmsDailyStatisticStage.property_id == "RTI22",
            PmsDailyStatisticStage.metric_label == "Total Occupied Rooms",
            PmsDailyStatisticStage.business_date == LAST,
            PmsDailyStatisticStage.period_label == "ACTUAL",
        )
    ).scalar_one()
    assert int(rooms) == demo.night(HOTELS[0], LAST).occupied
    assert db_session.execute(
        select(func.count()).select_from(UsaliStatisticFact).where(
            UsaliStatisticFact.property_id == "RTI22", UsaliStatisticFact.period == "MTD",
        )
    ).scalar_one() > 0


def test_the_bank_statement_matches_its_own_nights() -> None:
    hotel = HOTELS[0]
    month = nights(hotel, LAST, 10)
    lines = statements.parse_csv(demo.bank_statement_csv(hotel, month))
    settled = {}
    for n in month:
        for line, amount in (("Visa", n.visa), ("MasterCard", n.mastercard),
                             ("American Express", n.amex), ("Discover", n.discover), ("Cash", n.cash)):
            settled[(n.business_date, line)] = amount
    used: set[tuple[date, str]] = set()
    matched = [statements._match_one(ln, settled, used) for ln in lines]
    by_desc = {ln.description: m for ln, m in zip(lines, matched, strict=True)}
    kinds = {m.kind for m in matched}
    assert {"settlement", "cash", "payroll", "unmatched"} <= kinds
    assert by_desc["SBA LOAN PMT"].kind == "unmatched" and by_desc["MOBILE DEPOSIT"].kind == "unmatched"
    payouts = [m for ln, m in zip(lines, matched, strict=True) if "BANKCARD" in ln.description]
    assert all(m.kind == "settlement" and "less $" in m.note for m in payouts)


def test_the_group_is_the_same_every_time() -> None:
    assert [p.full_name for p in staff(HOTELS[1])] == [p.full_name for p in staff(HOTELS[1])]
    assert len({p.full_name for h in HOTELS for p in staff(h)}) == 30
    assert sum(1 for p in staff(HOTELS[0]) if p.role == "property_gm") == 1
    a, b = demo.night(HOTELS[2], LAST), demo.night(HOTELS[2], LAST)
    assert a == b and a.charges == a.payments
    assert demo.card_statement_csv(HOTELS[0], LAST) == demo.card_statement_csv(HOTELS[0], LAST)
