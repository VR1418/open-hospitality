"""Bank and card statements: upload, see the check, sort the card.

    GET    /api/desktop/statements?property=      the hotel's statements
    POST   /api/desktop/statements                upload a CSV (bank or card) — matched or sorted on the way in
    GET    /api/desktop/statements/{id}           one statement's lines
    PUT    /api/desktop/statements/lines/{id}     mark a bank line, or sort a card line (remembered by merchant)
    DELETE /api/desktop/statements/{id}           remove a statement (the lines go with it)
    GET    /api/desktop/statements/categories     the card categories

Nothing here writes to the books. See usali.desktop.statements.
"""

from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, FastAPI, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from usali.auth import ORG_ADMIN, Principal, request_session_factory, require_active_org, require_grants, require_operator
from usali.desktop import statements as st
from usali.desktop.codes_api import require_property

_owner = require_grants(ORG_ADMIN)
router = APIRouter(dependencies=[Depends(require_operator), Depends(require_active_org)])
_MAX_CSV = 10 * 1024 * 1024
BANK_KINDS = ("settlement", "cash", "payroll", "unmatched", "ignored")


class LineOut(BaseModel):
    line_id: int
    posted_on: date
    description: str
    amount: str
    balance: str | None
    match_kind: str
    match_note: str | None
    matched_amount: str | None
    category: str | None


class StatementOut(BaseModel):
    statement_id: int
    property_id: str
    kind: str
    account_label: str
    file_name: str
    uploaded_at: str
    first_date: date
    last_date: date
    lines: int
    #: Bank: money in that was matched / not; card: sorted / not.
    matched: int
    unmatched: int
    money_in: str
    money_out: str


class StatementDetail(StatementOut):
    rows: list[LineOut]
    #: Card statements: totals by category, largest first.
    by_category: list[tuple[str, str]]


class LineIn(BaseModel):
    match_kind: str | None = None
    match_note: str | None = Field(default=None, max_length=300)
    category: str | None = Field(default=None, max_length=100)


def _row(r: object) -> LineOut:
    m = r._mapping  # type: ignore[attr-defined]
    return LineOut(
        line_id=m["line_id"], posted_on=m["posted_on"], description=m["description"],
        amount=str(m["amount"]), balance=None if m["balance"] is None else str(m["balance"]),
        match_kind=m["match_kind"], match_note=m["match_note"],
        matched_amount=None if m["matched_amount"] is None else str(m["matched_amount"]),
        category=m["category"],
    )


def _summary(session: Session, statement_id: int, kind: str) -> tuple[int, int, int, Decimal, Decimal]:
    rows = session.execute(text(
        "SELECT amount, match_kind, category FROM desktop.statement_line WHERE statement_id = :s"
    ), {"s": statement_id}).all()
    money_in = sum((Decimal(a) for a, _, _ in rows if Decimal(a) > 0), Decimal("0"))
    money_out = sum((-Decimal(a) for a, _, _ in rows if Decimal(a) < 0), Decimal("0"))
    if kind == "bank":
        matched = sum(1 for _, k, _ in rows if k in ("settlement", "cash", "payroll", "ignored"))
    else:
        matched = sum(1 for _, _, c in rows if c is not None)
    return len(rows), matched, len(rows) - matched, money_in, money_out


def _statement(session: Session, r: object) -> StatementOut:
    m = r._mapping  # type: ignore[attr-defined]
    n, matched, unmatched, money_in, money_out = _summary(session, m["statement_id"], m["kind"])
    return StatementOut(
        statement_id=m["statement_id"], property_id=m["property_id"], kind=m["kind"],
        account_label=m["account_label"], file_name=m["file_name"],
        uploaded_at=m["uploaded_at"].isoformat(), first_date=m["first_date"],
        last_date=m["last_date"], lines=n, matched=matched, unmatched=unmatched,
        money_in=str(money_in), money_out=str(money_out),
    )


def _load(session: Session, statement_id: int) -> object:
    r = session.execute(text(
        "SELECT * FROM desktop.statement WHERE statement_id = :s"
    ), {"s": statement_id}).first()
    if r is None:
        raise HTTPException(status_code=404, detail="There's no statement by that number.")
    return r


@router.get("/api/desktop/statements/categories")
def categories(_: Principal = Depends(_owner)) -> list[str]:
    return list(st.CARD_CATEGORIES)


@router.get("/api/desktop/statements")
def list_statements(
    request: Request, property: str, _: Principal = Depends(_owner),
) -> list[StatementOut]:
    with request_session_factory(request)() as session:
        require_property(session, property)
        rows = session.execute(text(
            "SELECT * FROM desktop.statement WHERE property_id = :p "
            "ORDER BY last_date DESC, statement_id DESC"
        ), {"p": property}).all()
        return [_statement(session, r) for r in rows]


@router.post("/api/desktop/statements", status_code=201)
def upload(
    request: Request,
    file: UploadFile,
    property: str = Form(),
    kind: str = Form(),
    account_label: str = Form(default=""),
    principal: Principal = Depends(_owner),
) -> StatementDetail:
    if kind not in ("bank", "card"):
        raise HTTPException(status_code=422, detail="Say whether it's a bank or a card statement.")
    raw = file.file.read(_MAX_CSV + 1)
    if len(raw) > _MAX_CSV:
        raise HTTPException(status_code=413, detail="That file is too large to be a statement.")
    try:
        content = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        content = raw.decode("latin-1")
    try:
        lines = st.parse_csv(content)
    except st.StatementError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    name = (file.filename or "statement.csv")[:255]
    label = " ".join(account_label.split())[:100] or ("Bank account" if kind == "bank" else "Card")
    with request_session_factory(request)() as session:
        require_property(session, property)
        statement_id = session.execute(text(
            "INSERT INTO desktop.statement (property_id, kind, account_label, file_name, "
            "uploaded_by, first_date, last_date) VALUES (:p, :k, :a, :f, :by, :first, :last) "
            "RETURNING statement_id"
        ), {
            "p": property, "k": kind, "a": label, "f": name, "by": principal.subject,
            "first": min(ln.posted_on for ln in lines), "last": max(ln.posted_on for ln in lines),
        }).scalar_one()
        if kind == "bank":
            matches = st.match_lines(session, property, lines)
            values = [
                {"s": statement_id, "d": ln.posted_on, "desc": ln.description, "a": ln.amount,
                 "b": ln.balance, "k": m.kind, "n": m.note, "ma": m.matched_amount, "c": None}
                for ln, m in zip(lines, matches, strict=True)
            ]
        else:
            values = [
                {"s": statement_id, "d": ln.posted_on, "desc": ln.description, "a": ln.amount,
                 "b": ln.balance, "k": "unmatched", "n": None, "ma": None, "c": c}
                for ln, c in zip(lines, st.categories_for(session, lines), strict=True)
            ]
        session.execute(text(
            "INSERT INTO desktop.statement_line (statement_id, posted_on, description, amount, "
            "balance, match_kind, match_note, matched_amount, category) "
            "VALUES (:s, :d, :desc, :a, :b, :k, :n, :ma, :c)"
        ), values)
        session.commit()
        return _detail(session, statement_id)


def _detail(session: Session, statement_id: int) -> StatementDetail:
    head = _statement(session, _load(session, statement_id))
    rows = session.execute(text(
        "SELECT * FROM desktop.statement_line WHERE statement_id = :s "
        "ORDER BY posted_on, line_id"
    ), {"s": statement_id}).all()
    by_category: list[tuple[str, str]] = []
    if head.kind == "card":
        totals = st.totals_by_category([(r._mapping["category"], Decimal(r._mapping["amount"]))
                                        for r in rows if Decimal(r._mapping["amount"]) < 0])
        by_category = [(c, str(v)) for c, v in totals]
    return StatementDetail(**head.model_dump(), rows=[_row(r) for r in rows],
                           by_category=by_category)


@router.get("/api/desktop/statements/{statement_id}")
def statement(request: Request, statement_id: int, _: Principal = Depends(_owner)) -> StatementDetail:
    with request_session_factory(request)() as session:
        return _detail(session, statement_id)


@router.put("/api/desktop/statements/lines/{line_id}")
def mark_line(
    line_id: int, body: LineIn, request: Request, _: Principal = Depends(_owner),
) -> LineOut:
    with request_session_factory(request)() as session:
        row = session.execute(text(
            "SELECT l.*, s.kind AS statement_kind FROM desktop.statement_line l "
            "JOIN desktop.statement s ON s.statement_id = l.statement_id WHERE l.line_id = :l"
        ), {"l": line_id}).first()
        if row is None:
            raise HTTPException(status_code=404, detail="There's no line by that number.")
        if row._mapping["statement_kind"] == "card":
            if body.category is not None and body.category not in st.CARD_CATEGORIES:
                raise HTTPException(status_code=422, detail="Pick a category from the list.")
            session.execute(text(
                "UPDATE desktop.statement_line SET category = :c WHERE line_id = :l"
            ), {"c": body.category, "l": line_id})
            # Remembered by merchant, so next month's line is sorted on the way in.
            st.remember_category(session, row._mapping["description"], body.category)
        else:
            if body.match_kind not in BANK_KINDS:
                raise HTTPException(status_code=422, detail="That isn't a way to mark a line.")
            session.execute(text(
                "UPDATE desktop.statement_line SET match_kind = :k, match_note = :n "
                "WHERE line_id = :l"
            ), {"k": body.match_kind, "n": body.match_note, "l": line_id})
        session.commit()
        fresh = session.execute(text(
            "SELECT * FROM desktop.statement_line WHERE line_id = :l"
        ), {"l": line_id}).first()
        return _row(fresh)


@router.delete("/api/desktop/statements/{statement_id}", status_code=204)
def remove(request: Request, statement_id: int, _: Principal = Depends(_owner)) -> None:
    with request_session_factory(request)() as session:
        _load(session, statement_id)
        session.execute(text("DELETE FROM desktop.statement WHERE statement_id = :s"),
                        {"s": statement_id})
        session.commit()


def install(app: FastAPI) -> None:
    app.include_router(router)
