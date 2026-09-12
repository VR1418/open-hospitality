"""A hotel's own meaning for its transaction codes (PRD M4, Phase 1).

The promise under test: upstream's shipped dictionary decides exactly as it
always did until a person confirms something, and a confirmation binds to ONE
hotel — because `usali_mapping_dictionary` is keyed with no property, and
choiceADVANTAGE codes are franchise-configurable, so a group's two hotels can
hold different answers for the same code.

Runs against the real bundled cluster: the resolver reaches `transform`
through the session, and only a real session proves that.
"""

from collections.abc import Iterator
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from usali.db import make_engine, make_session_factory
from usali.desktop.app import OWNER
from usali.desktop.bootstrap import DesktopKeys, app_url, prepare_database
from usali.desktop.mapping_decisions import (
    DecidingSessionFactory,
    Decision,
    decisions_for,
    record,
)
from usali.desktop.pg_runtime import PgCluster, PostgresNotFound, find_bin_dir, free_port
from usali.models import IngestBatch, MappingException, PmsDailyFinancialStage, UsaliFinancialFact
from usali.tenancy import FOUNDING_ORG_ID, OrgBoundSessionFactory
from usali.transform import Classification, transform

REPO = Path(__file__).resolve().parents[1]
try:
    BIN: Path | None = find_bin_dir(REPO)
except PostgresNotFound:
    BIN = None

pytestmark = pytest.mark.skipif(
    BIN is None, reason="bundled Postgres not fetched (scripts/desktop/fetch_postgres.py)"
)

SOURCE = "SKYTOUCH"
EDITION = 12
# What mapping/skytouch.yaml ships for the room-charge code — every row of it
# LOW confidence and needs-review, which is the whole reason for this feature.
SHIPPED = ("Operated Departments", "Rooms", "Room Revenue")
# What an owner might confirm instead, for one hotel whose franchise uses the
# same code for a package-inclusive rate.
CONFIRMED = Classification(
    usali_schedule_id=1,
    usali_major_category="Operated Departments",
    usali_sub_category="Rooms",
    usali_line_item="Other Rooms Revenue",
    gl_account_code="4000",
)


@pytest.fixture(scope="module")
def sessions(tmp_path_factory: pytest.TempPathFactory) -> Iterator[OrgBoundSessionFactory]:
    assert BIN is not None
    root = tmp_path_factory.mktemp("decisions")
    keys = DesktopKeys.generate()
    cluster = PgCluster(bin_dir=BIN, data_dir=root / "database", log_file=root / "db.log")
    cluster.init(keys.db_owner_password)
    port = free_port(55438)
    cluster.start(port)
    try:
        prepare_database(
            port=port, keys=keys, resources=REPO, state_file=root / "state.json",
            user=OWNER, allow_upgrade=False,
        )
        engine = make_engine(app_url(port, keys))
        # The same composition as desktop/app.py: decisions bound underneath
        # the org binding, so every session carries both.
        yield OrgBoundSessionFactory(
            DecidingSessionFactory(make_session_factory(engine)), FOUNDING_ORG_ID
        )
        engine.dispose()
    finally:
        cluster.stop()


def _stage(session: object, *, day: date, rows: list[tuple[str, str, str]]) -> None:
    """Stage `(property_id, trx_code, description)` rows for one day."""
    batch = IngestBatch(
        pms_source=SOURCE, report_type="hotel_journal", source_file=f"{day}.pdf",
        file_hash=f"hash-{day}", status="started", row_count=len(rows),
    )
    session.add(batch)  # type: ignore[attr-defined]
    session.flush()  # type: ignore[attr-defined]
    for i, (property_id, code, desc) in enumerate(rows):
        session.add(  # type: ignore[attr-defined]
            PmsDailyFinancialStage(
                property_id=property_id, pms_source=SOURCE, report_type="hotel_journal",
                business_date=day, pms_trx_code=code, pms_trx_desc=desc,
                raw_amount="100.0000", room_count=1, source_file=f"{day}.pdf",
                ingest_batch_id=batch.batch_id, row_hash=f"{day}-{i}",
            )
        )
    session.flush()  # type: ignore[attr-defined]


def _facts(session: object, day: date) -> dict[str, UsaliFinancialFact]:
    rows = session.execute(  # type: ignore[attr-defined]
        select(UsaliFinancialFact).where(UsaliFinancialFact.business_date == day)
    ).scalars()
    return {f.property_id: f for f in rows}


def test_without_a_decision_the_shipped_dictionary_decides(
    sessions: OrgBoundSessionFactory,
) -> None:
    day = date(2026, 3, 1)
    with sessions() as s:
        _stage(day=day, session=s, rows=[("AAA", "RM", "Room Charge"), ("BBB", "RM", "Room")])
        r = transform(s, source=SOURCE, business_date=day, edition=EDITION)
        assert (r.mapped, r.unmapped) == (2, 0)
        facts = _facts(s, day)
        for property_id in ("AAA", "BBB"):
            f = facts[property_id]
            assert (f.usali_major_category, f.usali_sub_category, f.usali_line_item) == SHIPPED
        s.rollback()


def test_a_decision_binds_to_one_hotel_and_leaves_the_others_alone(
    sessions: OrgBoundSessionFactory,
) -> None:
    day = date(2026, 3, 2)
    with sessions() as s:
        record(
            s, property_id="AAA", pms_source=SOURCE, trx_code="RM", edition=EDITION,
            classification=CONFIRMED, origin="owner", decided_by="owner-subject",
            note="This franchise bills package stays on RM.",
        )
        _stage(day=day, session=s, rows=[("AAA", "RM", "Room Charge"), ("BBB", "RM", "Room")])
        r = transform(s, source=SOURCE, business_date=day, edition=EDITION)
        assert (r.mapped, r.unmapped) == (2, 0)
        facts = _facts(s, day)
        assert facts["AAA"].usali_line_item == "Other Rooms Revenue"
        # The hotel that confirmed nothing still gets upstream's answer.
        assert facts["BBB"].usali_line_item == "Room Revenue"
        s.rollback()


def test_a_decision_gives_a_code_the_dictionary_never_had_a_home(
    sessions: OrgBoundSessionFactory,
) -> None:
    """The money that today lands in a MappingException and is swept into the
    clearing account, where no check will ever notice it."""
    day = date(2026, 3, 3)
    with sessions() as s:
        _stage(day=day, session=s, rows=[("AAA", "ZZQ", "Cabana Rental")])
        r = transform(s, source=SOURCE, business_date=day, edition=EDITION)
        assert (r.mapped, r.unmapped) == (0, 1)
        s.rollback()

    with sessions() as s:
        record(
            s, property_id="AAA", pms_source=SOURCE, trx_code="ZZQ", edition=EDITION,
            classification=CONFIRMED, origin="ai-accepted", decided_by="owner-subject",
        )
        _stage(day=day, session=s, rows=[("AAA", "ZZQ", "Cabana Rental")])
        r = transform(s, source=SOURCE, business_date=day, edition=EDITION)
        assert (r.mapped, r.unmapped) == (1, 0)
        assert _facts(s, day)["AAA"].usali_line_item == "Other Rooms Revenue"
        assert s.execute(select(MappingException).where(
            MappingException.business_date == day
        )).first() is None
        s.rollback()


def test_a_decision_is_seen_by_a_run_in_the_same_session(
    sessions: OrgBoundSessionFactory,
) -> None:
    """Confirming a code and re-reading its reports happens in one
    transaction, so the resolver's cache must not outlive the decision."""
    day = date(2026, 3, 4)
    with sessions() as s:
        # Prime the cache with a run that has no decision to find.
        _stage(day=day, session=s, rows=[("CCC", "RM", "Room Charge")])
        transform(s, source=SOURCE, business_date=day, edition=EDITION)
        assert _facts(s, day)["CCC"].usali_line_item == "Room Revenue"

        record(
            s, property_id="CCC", pms_source=SOURCE, trx_code="RM", edition=EDITION,
            classification=CONFIRMED, origin="owner", decided_by="owner-subject",
        )
        later = date(2026, 3, 5)
        _stage(day=later, session=s, rows=[("CCC", "RM", "Room Charge")])
        transform(s, source=SOURCE, business_date=later, edition=EDITION)
        assert _facts(s, later)["CCC"].usali_line_item == "Other Rooms Revenue"
        s.rollback()


def test_a_decision_says_who_made_it_and_why(sessions: OrgBoundSessionFactory) -> None:
    with sessions() as s:
        record(
            s, property_id="DDD", pms_source=SOURCE, trx_code="PET", edition=EDITION,
            classification=CONFIRMED, origin="owner", decided_by="priya",
            note="Pet fee is a room surcharge here.",
        )
        s.flush()
        [d] = list(decisions_for(s, property_id="DDD"))
        assert isinstance(d, Decision)
        assert (d.pms_trx_code, d.origin, d.decided_by) == ("PET", "owner", "priya")
        assert d.note == "Pet fee is a room surcharge here."
        assert d.classification == CONFIRMED
        assert d.decided_at is not None
        s.rollback()


def test_correcting_a_decision_replaces_it_and_re_stamps_who(
    sessions: OrgBoundSessionFactory,
) -> None:
    with sessions() as s:
        for who, line in (("priya", "Other Rooms Revenue"), ("sam", "Room Revenue")):
            record(
                s, property_id="EEE", pms_source=SOURCE, trx_code="RM", edition=EDITION,
                classification=Classification(1, "Operated Departments", "Rooms", line, "4000"),
                origin="owner", decided_by=who,
            )
        s.flush()
        [d] = list(decisions_for(s, property_id="EEE"))
        assert (d.decided_by, d.classification.usali_line_item) == ("sam", "Room Revenue")
        s.rollback()


def test_an_origin_we_do_not_recognise_is_refused_twice_over(
    sessions: OrgBoundSessionFactory,
) -> None:
    """In Python, so the caller gets a plain message — and in the database,
    so nothing that bypasses `record` can invent a provenance."""
    with sessions() as s:
        with pytest.raises(ValueError, match="origin must be one of"):
            record(
                s, property_id="FFF", pms_source=SOURCE, trx_code="RM", edition=EDITION,
                classification=CONFIRMED, origin="the-computer-said-so", decided_by="x",
            )
        s.rollback()

    with sessions() as s, pytest.raises(IntegrityError):
        s.execute(
            text(
                "INSERT INTO desktop.mapping_decision (property_id, pms_source,"
                " pms_trx_code, usali_edition, usali_major_category,"
                " usali_sub_category, usali_line_item, origin, decided_by)"
                " VALUES ('FFF', :s, 'RM', :e, 'Operated Departments', 'Rooms',"
                " 'Room Revenue', 'the-computer-said-so', 'x')"
            ),
            {"s": SOURCE, "e": EDITION},
        )
