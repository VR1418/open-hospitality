"""What the model is allowed to see — built, not filtered (PRD AI-4, ADR-D7).

Two mechanisms, and the order matters.

**The control is construction.** `CodeQuestion` names every field that may
leave this machine: the PMS source, the transaction code, the description as
printed on the report, the dates it was seen, its amounts, and the USALI lines
it could be put on. There is no path from a database row to a prompt; a prompt
is assembled from this object and nothing else. Everything the PRD forbids —
employee names, pay rates, SSNs, bank details, account numbers, any figure
suppressed under ADR-006 — is *structurally absent*, because the queries that
build a `CodeQuestion` never touch a labour, payroll or PII table.

**The scan is defence in depth**, and it REFUSES rather than masks. `check`
runs on the fully serialized request body immediately before it is sent. If
something forbidden is in there, construction is broken, and a mask would turn
that bug into a silent near-miss nobody ever learns about. A refusal makes it a
failing test and a visible error.

What the scan can and cannot see: a card number, an SSN-shaped string, a long
bare digit run and a known employee's name are all recognisable in text. A pay
rate is not — "23.17" is indistinguishable from a room charge. That one rests
on construction alone, which is why construction is the control.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from usali.models import Employee
from usali.redaction import mask_pans


class BlockedContent(RuntimeError):
    """Something forbidden reached the outbound boundary.

    The message names the KIND of thing found and never the thing itself —
    quoting it would copy the very value into a log (AI-1).
    """

    def __init__(self, kind: str) -> None:
        self.kind = kind
        super().__init__(
            f"refusing to send: the request contained {kind}. Nothing was sent. "
            "This is a bug in how the request was built, not something you did."
        )


@dataclass(frozen=True)
class LineChoice:
    """One USALI line the model may pick. Curated product vocabulary, never
    anything a person typed."""

    major: str
    sub: str
    line_item: str

    def render(self) -> str:
        return f"{self.major} / {self.sub} / {self.line_item}"


@dataclass(frozen=True)
class CodeQuestion:
    """Everything the model is allowed to know about one transaction code.

    Adding a field here is a deliberate widening of what leaves the machine,
    and is reviewed as such (ADR-D7).
    """

    pms_source: str
    code: str
    description: str | None
    times_seen: int
    total_amount: Decimal
    first_seen: date
    last_seen: date
    sample_amounts: tuple[Decimal, ...]
    choices: tuple[LineChoice, ...]


#: The house style for a hotel's own books, and the refusals AI-7 requires.
INSTRUCTIONS = """You are helping a hotel bookkeeper file one charge code from
their front-desk system into the USALI chart of accounts.

Answer with a JSON object and nothing else:
  {"choice": <index into the numbered list, or null>,
   "confidence": "high" | "medium" | "low",
   "reason": "<one sentence, plain English>",
   "decline_reason": "<why you will not choose, or null>"}

Rules:
- Choose only from the numbered list. Do not invent a line.
- If the answer depends on this hotel's tax treatment, or on whether something
  is an expense or a capital item, set "choice" to null and say so in
  "decline_reason". Do not guess on those.
- If the description is too vague to tell, decline rather than guess.
"""


def render(question: CodeQuestion) -> str:
    """The prompt body, from the question object and nothing else."""
    seen = (
        question.first_seen.isoformat()
        if question.first_seen == question.last_seen
        else f"{question.first_seen.isoformat()} to {question.last_seen.isoformat()}"
    )
    samples = ", ".join(str(a) for a in question.sample_amounts)
    lines = "\n".join(
        f"{i}. {choice.render()}" for i, choice in enumerate(question.choices)
    )
    return (
        f"{INSTRUCTIONS}\n"
        f"Front-desk system: {question.pms_source}\n"
        f"Charge code: {question.code}\n"
        f"Printed on the report as: {question.description or '(no description printed)'}\n"
        f"Seen {question.times_seen} time(s), {seen}, totalling {question.total_amount}\n"
        f"Individual amounts: {samples}\n\n"
        f"Lines to choose from:\n{lines}\n"
    )


def forbidden_names(session: Session) -> frozenset[str]:
    """Every employee name in this hotel group, for the outbound scan.

    Read through the request's own org-bound session, so it is this group's
    people and no one else's. Names are the one PII category that is both
    recognisable in free text and plausibly present in a report description.
    """
    return frozenset(
        name.strip().lower()
        for name in session.scalars(select(Employee.full_name))
        if name and len(name.strip()) > 3
    )


def _has_pan(text: str) -> bool:
    """A Luhn-valid card-shaped digit run. Uses `redaction.mask_pans` rather
    than a second copy of the rule: if masking would change the text, a card
    number is in it."""
    return mask_pans(text) != text


def check(text: str, *, names: Iterable[str] = ()) -> None:
    """Refuse the send if anything forbidden is in the serialized body.

    Raises `BlockedContent`, which names the kind and never the value.
    """
    if _has_pan(text):
        raise BlockedContent("something shaped like a card number")

    digits: list[str] = []
    run = ""
    for ch in text:
        if ch.isdigit():
            run += ch
            continue
        if run:
            digits.append(run)
        run = ""
    if run:
        digits.append(run)
    # A bare run of nine or more digits: an account number, a routing number,
    # an unformatted SSN. Amounts carry a decimal point and so never reach
    # nine consecutive digits at these sizes; codes and dates are shorter.
    if any(len(d) >= 9 for d in digits):
        raise BlockedContent("a long run of digits, which could be an account number")

    lowered = text.lower()
    # An SSN as printed. The bare-digit rule above catches the unpunctuated form.
    for i in range(len(lowered) - 10):
        window = lowered[i : i + 11]
        if (
            window[3] == "-"
            and window[6] == "-"
            and window[:3].isdigit()
            and window[4:6].isdigit()
            and window[7:].isdigit()
        ):
            raise BlockedContent("something shaped like a Social Security number")

    for name in names:
        if name and name in lowered:
            raise BlockedContent("an employee's name")
