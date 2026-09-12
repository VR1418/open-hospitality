"""What this hotel's transaction codes mean — the answer a person confirmed.

Upstream decides a code's USALI line from `usali_mapping_dictionary`, whose
rows are keyed (pms_source, pms_trx_code, usali_edition): global, with no
property and no org. `mapping/skytouch.yaml` says in its own header that
choiceADVANTAGE codes are franchise-configurable and ships all 22 rows as
confidence LOW / needs-review — so on a real hotel today every posted entry
rests on a guess nobody confirmed, and two hotels in one group cannot hold
different answers for the same code.

This module holds the per-hotel answer and hands it to upstream through
`transform.RESOLVER_KEY`, a resolver bound on the session. Bound there rather
than passed as an argument because `transform` is reached through eight
ingestion handlers and four entry points; the session is the one thing all of
them share. With no decisions recorded, the resolver declines every row and
ingestion behaves exactly as it did.

Plain SQL, like `settings.py`: the `desktop` schema sits outside upstream's
ORM tenancy hook, and one install is one owner's machine.
"""

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from usali.transform import RESOLVER_KEY, Classification

#: A decision a person chose outright, and one a person accepted from the
#: AI (PRD AI-6). The database's CHECK constraint holds the same two.
ORIGINS = ("owner", "ai-accepted")

_COLUMNS = """property_id, pms_source, pms_trx_code, usali_edition,
        usali_schedule_id, usali_major_category, usali_sub_category,
        usali_line_item, gl_account_code, origin, note, decided_by, decided_at"""


@dataclass(frozen=True)
class Decision:
    """One confirmed meaning, with who confirmed it."""

    property_id: str
    pms_source: str
    pms_trx_code: str
    usali_edition: int
    classification: Classification
    origin: str
    note: str | None
    decided_by: str
    decided_at: datetime


def _row_to_decision(r: Any) -> Decision:
    """One `desktop.mapping_decision` row as a `Decision`."""
    return Decision(
        property_id=r.property_id,
        pms_source=r.pms_source,
        pms_trx_code=r.pms_trx_code,
        usali_edition=r.usali_edition,
        classification=Classification(
            usali_schedule_id=r.usali_schedule_id,
            usali_major_category=r.usali_major_category,
            usali_sub_category=r.usali_sub_category,
            usali_line_item=r.usali_line_item,
            gl_account_code=r.gl_account_code,
        ),
        origin=r.origin,
        note=r.note,
        decided_by=r.decided_by,
        decided_at=r.decided_at,
    )


class DecisionResolver:
    """`transform.MappingResolver` over `desktop.mapping_decision`.

    Loaded once per (pms_source, edition) and cached for the session's life:
    `transform` asks per staged row, and a day's report is tens of rows, not
    one query each. `invalidate` drops the cache so a decision recorded and
    re-run inside one session sees itself — which is exactly what confirming
    a code and re-reading its reports does.
    """

    def __init__(self, session: Session) -> None:
        self._session = session
        self._cache: dict[tuple[str, int], dict[tuple[str, str], Classification]] = {}

    def invalidate(self) -> None:
        self._cache.clear()

    def _load(self, pms_source: str, edition: int) -> dict[tuple[str, str], Classification]:
        key = (pms_source, edition)
        cached = self._cache.get(key)
        if cached is None:
            rows = self._session.execute(
                text(
                    f"SELECT {_COLUMNS} FROM desktop.mapping_decision "
                    "WHERE pms_source = :s AND usali_edition = :e"
                ),
                {"s": pms_source, "e": edition},
            ).all()
            cached = {
                (r.property_id, r.pms_trx_code): _row_to_decision(r).classification for r in rows
            }
            self._cache[key] = cached
        return cached

    def __call__(
        self, *, property_id: str, pms_source: str, trx_code: str, edition: int
    ) -> Classification | None:
        return self._load(pms_source, edition).get((property_id, trx_code))


class DecidingSessionFactory:
    """The serving session factory, with this install's decisions bound to
    every session it hands out.

    Wraps (never mutates) the underlying factory, the `OrgBoundSessionFactory`
    precedent — and composes under it, so the founding-org paths (the folder
    watch, the CLI) and the per-request path both get a resolver.
    """

    def __init__(self, factory: Callable[[], Session]) -> None:
        self._factory = factory

    def __call__(self) -> Session:
        session = self._factory()
        session.info[RESOLVER_KEY] = DecisionResolver(session)
        return session


def resolver_on(session: Session) -> DecisionResolver | None:
    """The resolver bound to this session, if this is a desktop session."""
    bound = session.info.get(RESOLVER_KEY)
    return bound if isinstance(bound, DecisionResolver) else None


def record(
    session: Session,
    *,
    property_id: str,
    pms_source: str,
    trx_code: str,
    edition: int,
    classification: Classification,
    origin: str,
    decided_by: str,
    note: str | None = None,
) -> None:
    """Write (or replace) one hotel's decision about one code.

    Does not commit — the caller owns the transaction, so the decision, the
    audit row and any re-run of the affected days land together or not at all.
    """
    if origin not in ORIGINS:
        raise ValueError(f"origin must be one of {ORIGINS}, not {origin!r}")
    session.execute(
        text(
            "INSERT INTO desktop.mapping_decision ("
            "  property_id, pms_source, pms_trx_code, usali_edition,"
            "  usali_schedule_id, usali_major_category, usali_sub_category,"
            "  usali_line_item, gl_account_code, origin, note, decided_by)"
            " VALUES (:property_id, :pms_source, :trx_code, :edition,"
            "  :schedule_id, :major, :sub, :line_item, :gl, :origin, :note, :decided_by)"
            " ON CONFLICT (property_id, pms_source, pms_trx_code, usali_edition)"
            " DO UPDATE SET usali_schedule_id = EXCLUDED.usali_schedule_id,"
            "  usali_major_category = EXCLUDED.usali_major_category,"
            "  usali_sub_category = EXCLUDED.usali_sub_category,"
            "  usali_line_item = EXCLUDED.usali_line_item,"
            "  gl_account_code = EXCLUDED.gl_account_code,"
            "  origin = EXCLUDED.origin, note = EXCLUDED.note,"
            "  decided_by = EXCLUDED.decided_by, decided_at = now()"
        ),
        {
            "property_id": property_id,
            "pms_source": pms_source,
            "trx_code": trx_code,
            "edition": edition,
            "schedule_id": classification.usali_schedule_id,
            "major": classification.usali_major_category,
            "sub": classification.usali_sub_category,
            "line_item": classification.usali_line_item,
            "gl": classification.gl_account_code,
            "origin": origin,
            "note": note,
            "decided_by": decided_by,
        },
    )
    bound = resolver_on(session)
    if bound is not None:
        bound.invalidate()


def decisions_for(session: Session, *, property_id: str) -> Iterator[Decision]:
    """Every code this hotel has confirmed, newest decision first."""
    rows = session.execute(
        text(
            f"SELECT {_COLUMNS} FROM desktop.mapping_decision "
            "WHERE property_id = :p ORDER BY decided_at DESC, pms_trx_code"
        ),
        {"p": property_id},
    ).all()
    return (_row_to_decision(r) for r in rows)
