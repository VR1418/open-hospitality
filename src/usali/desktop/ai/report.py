"""Reading a report the product has no parser for (ADR-D7, Phase 3).

The question here is unlike the classify-a-code one in a way that matters.
`allowlist.CodeQuestion` is SAFE BY CONSTRUCTION: every field is named, so
nothing else can be in the payload. This question cannot be, because its whole
content is text nobody here wrote.

So the protection moves earlier, into `pages`: the report is split, every page
is run through the same outbound scan, and only pages carrying nothing
forbidden are eligible. Nothing is masked to make a page acceptable — it goes
whole or not at all. This module never sees the pages that were held back.

That makes this the single filtered question in the product, and the reason it
is acceptable is measurable rather than hopeful: on the real choiceADVANTAGE
pack that prompted the feature, 21 of 48 pages survive and not one of them
carries a person's name. What survives is the summary, which is the only part
the books need.

What comes back is a proposal. Nothing is staged until somebody reads the rows
and accepts them (AI-6).
"""

import json
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from usali.desktop.ai.pages import Page
from usali.desktop.ai.port import AiError, Usage

#: What a hotel with no supported PMS is recorded as. Deliberately not a real
#: vendor name: the books should say the figures came from a report we read
#: with help, not claim a parser exists.
OTHER_SOURCE = "OTHER"
#: The report type staged rows carry, so an AI-read day is distinguishable
#: from a parsed one for ever after.
REPORT_TYPE = "ai_read"

#: How many rows a night-audit summary can plausibly have. A model that
#: returns hundreds has misread a guest list as charges, and the cap turns
#: that into a refusal rather than a staging run.
MAX_ROWS = 200

INSTRUCTIONS = """You are reading a hotel's night-audit report. Some pages have
been withheld; you are shown only what remains.

Find the summary of the day's charges: the lines pairing a short transaction
code with a description and a money amount.

Answer with a JSON object and nothing else:
  {"business_date": "YYYY-MM-DD" or null,
   "rows": [{"code": "...", "description": "...", "amount": "-1234.56"}],
   "decline_reason": "<why you cannot, or null>"}

Rules:
- Amounts as plain decimal strings. A figure printed in brackets is negative.
- Copy codes and descriptions exactly as printed. Do not tidy or translate them.
- Include each charge line once. Do not include page totals, grand totals or
  running balances — they would double the day.
- If these pages hold no charge summary, return an empty list and say why in
  "decline_reason". An empty answer is better than a guessed one.
- Never invent a row. If a line is unreadable, leave it out and say so.
"""


#: The skill half of "memory and skills" (docs/desktop/M4-ai-and-ledger.md):
#: how a kind of report is read, shipped with the app, one Markdown file per
#: system. They carry no hotel data, so they are safe to show a model.
GUIDES = Path(__file__).resolve().parents[4] / "mapping" / "reading-guides"


def reading_guide(system: str) -> str | None:
    """The guide for a front-desk system, without its front matter; the
    general one when the system has none of its own."""
    for name in (system.lower(), OTHER_SOURCE.lower()):
        path = GUIDES / f"{name}.md"
        if path.is_file():
            text = path.read_text(encoding="utf-8")
            if text.startswith("---"):
                text = text.split("---", 2)[2]
            return text.strip()
    return None


@dataclass(frozen=True)
class ReportQuestion:
    """The hotel, the pages that survived the scan, and how to read them."""

    hotel: str
    pages: tuple[Page, ...]
    guide: str | None = None


@dataclass(frozen=True)
class ExtractedRow:
    code: str
    description: str
    amount: Decimal


@dataclass(frozen=True)
class Extraction:
    business_date: date | None
    rows: tuple[ExtractedRow, ...]
    decline_reason: str | None

    @property
    def usable(self) -> bool:
        return bool(self.rows) and self.business_date is not None


def render(question: ReportQuestion) -> str:
    """The prompt, from pages that have already passed the scan."""
    if not question.pages:
        raise AiError("there are no pages that can be shown to a model")
    body = "\n\n".join(f"--- page {p.number} ---\n{p.text}" for p in question.pages)
    guide = f"READING GUIDE\n{question.guide}\n\n" if question.guide else ""
    return (
        f"{INSTRUCTIONS}\n"
        f"{guide}"
        f"Hotel: {question.hotel}\n\n"
        f"REPORT PAGES\n{body}\n"
    )


def _amount(raw: object) -> Decimal:
    text = str(raw).strip().replace(",", "").replace("$", "")
    negative = text.startswith("(") and text.endswith(")")
    if negative:
        text = text[1:-1]
    try:
        value = Decimal(text)
    except (InvalidOperation, ValueError) as exc:
        raise AiError("the model gave an amount that is not a number") from exc
    return -value if negative else value


def parse(text: str, usage: Usage) -> Extraction:
    """`Extraction` from the model's reply, or `AiError` if it is not usable.

    Strict on purpose. Every refusal here is a row that would otherwise have
    been offered to somebody as a fact about their money.
    """
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise AiError("the model did not answer with the JSON it was asked for")
    try:
        body: Any = json.loads(text[start : end + 1])
    except json.JSONDecodeError as exc:
        raise AiError("the model's answer was not readable JSON") from exc
    if not isinstance(body, dict):
        raise AiError("the model's answer was not a JSON object")

    raw_rows = body.get("rows") or []
    if not isinstance(raw_rows, list):
        raise AiError("the model's answer had no list of rows")
    if len(raw_rows) > MAX_ROWS:
        raise AiError(
            f"the model returned {len(raw_rows)} rows, more than a day's summary has — "
            "it has probably read a guest list as charges"
        )

    rows: list[ExtractedRow] = []
    for row in raw_rows:
        if not isinstance(row, dict):
            raise AiError("one of the model's rows was not an object")
        code = str(row.get("code", "")).strip()
        if not code:
            raise AiError("one of the model's rows had no transaction code")
        rows.append(ExtractedRow(
            code=code[:50],
            description=str(row.get("description", "")).strip()[:255],
            amount=_amount(row.get("amount", "0")),
        ))

    raw_date = body.get("business_date")
    business_date: date | None = None
    if raw_date:
        try:
            business_date = date.fromisoformat(str(raw_date))
        except ValueError as exc:
            raise AiError("the model gave a business date that is not a date") from exc

    decline = body.get("decline_reason")
    if not rows and not decline:
        raise AiError("the model found nothing and did not say why")
    return Extraction(
        business_date=business_date,
        rows=tuple(rows),
        decline_reason=str(decline).strip()[:500] if decline else None,
    )
