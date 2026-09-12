"""Which pages of an unrecognised report the model may be shown (ADR-D7).

`allowlist` protects the classify-a-code question by CONSTRUCTION: the payload
is assembled from a typed object, so nothing else can be in it. That is not
available here. Reading a report the product has no parser for means showing
the model text we did not write, and a night-audit export is full of things
that must never leave: a real choiceADVANTAGE pack carries guest names,
account numbers, guest tax IDs and balances across its A/R Aging, Guest
Ledger, In House, No Show, Pre-Paid and Tax Exempt sections.

So this is the one place the product filters rather than builds, and it is
deliberately blunt about it:

- The unit is the PAGE, not the word. Nothing is edited, masked or trimmed to
  make a page acceptable — a page either contains nothing forbidden and goes
  whole, or it is dropped whole. Masking would leave us guessing whether what
  remained was safe.
- The test is `allowlist.check`, the same scan that guards the outbound
  boundary everywhere else. One rule, not a second opinion.
- If nothing survives, nothing is sent, and the owner is told which pages were
  held back and why.

What survives, on every real export seen so far, is the summary: the totals
page listing transaction codes and amounts — which is the only part the books
need anyway.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from usali.adaptors.pdf import extract_pages
from usali.desktop.ai.allowlist import BlockedContent, check


@dataclass(frozen=True)
class Page:
    """One page of the report, and the text of it."""

    number: int
    text: str


@dataclass(frozen=True)
class HeldBack:
    """A page the model will not be shown, and the kind of thing on it.

    `why` names the KIND, never the value — the `BlockedContent` rule: a
    reason that quoted the guest's name would put it in the log the reason
    ends up in.
    """

    number: int
    why: str


@dataclass(frozen=True)
class Reading:
    kept: tuple[Page, ...]
    held_back: tuple[HeldBack, ...]

    @property
    def anything_to_send(self) -> bool:
        return bool(self.kept)


def page_text(words: Iterable[object]) -> str:
    return " ".join(str(getattr(w, "text", "")) for w in words).strip()


def safe_pages(pdf: str | Path, *, names: Iterable[str] = ()) -> Reading:
    """Split a report into pages and keep only those with nothing forbidden.

    `names` is this hotel group's employee names, from
    `allowlist.forbidden_names` — the one forbidden category that is
    recognisable in free text only if you know what to look for.
    """
    kept: list[Page] = []
    held: list[HeldBack] = []
    needles = tuple(names)
    for i, words in enumerate(extract_pages(Path(pdf)), start=1):
        text = page_text(words)
        if not text:
            continue  # a blank page is nothing to send and nothing to report
        try:
            check(text, names=needles)
        except BlockedContent as blocked:
            held.append(HeldBack(number=i, why=blocked.kind))
            continue
        kept.append(Page(number=i, text=text))
    return Reading(kept=tuple(kept), held_back=tuple(held))
